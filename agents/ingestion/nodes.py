"""Nodos del grafo de ingesta. Las dependencias externas llegan por ``IngestionDeps``."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pymupdf
from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel

from agents.ingestion.prompts import ENRICH_SYSTEM, enrich_user_prompt
from agents.ingestion.records import embedding_text, make_table_id, pinecone_metadata
from agents.ingestion.schemas import TableMetadata
from agents.ingestion.state import IngestionState
from agents.ingestion.validation import validate_metadata
from services.pdf_context import collect_context as collect_table_context
from services.pdf_extract import SkippedTable
from services.pdf_extract import extract_tables as extract_pdf_tables
from services.table_store import TABLES_DIR, save_table

ROOT = Path(__file__).resolve().parents[2]


@dataclass
class IngestionDeps:
    llm: BaseChatModel
    embeddings: Embeddings
    index: Any
    tables_dir: Path = TABLES_DIR
    max_attempts: int = 3


def load_pdf(state: IngestionState) -> IngestionState:
    path = Path(state["pdf_path"])
    if not path.is_file():
        raise FileNotFoundError(path)
    with pymupdf.open(path) as doc:
        if not doc.is_pdf:
            raise ValueError(f"{path} no es un PDF")
        page_texts = [page.get_text() for page in doc]
    return {
        "source": path.name,
        "page_texts": page_texts,
        "attempts": 0,
        "metadata": {},
        "feedback": {},
    }


def extract_tables(state: IngestionState) -> IngestionState:
    result = extract_pdf_tables(state["pdf_path"])
    return {"tables": result.tables, "skipped": result.skipped}


def collect_context(state: IngestionState) -> IngestionState:
    return {"contexts": collect_table_context(state["pdf_path"], state["tables"])}


def enrich(state: IngestionState, deps: IngestionDeps) -> IngestionState:
    """Pide metadatos al LLM para las tablas que todavía no tienen metadatos válidos."""
    metadata, feedback = state["metadata"], state["feedback"]
    pending = [i for i in range(len(state["tables"])) if i not in metadata]
    prompts = [
        [
            ("system", ENRICH_SYSTEM),
            ("human", enrich_user_prompt(state["tables"][i], state["contexts"][i], feedback.get(i))),
        ]
        for i in pending
    ]
    structured = deps.llm.with_structured_output(TableMetadata)
    answers = structured.batch(prompts, return_exceptions=True) if prompts else []
    candidates = {
        i: (a if isinstance(a, TableMetadata) else None) for i, a in zip(pending, answers)
    }
    return {"candidates": candidates, "attempts": state["attempts"] + 1}


def validate(state: IngestionState) -> IngestionState:
    metadata = dict(state["metadata"])
    feedback = {}
    for i, meta in state["candidates"].items():
        if meta is None:
            feedback[i] = "La respuesta no respetó el schema TableMetadata."
            continue
        errors = validate_metadata(meta, state["tables"][i].to_dataframe())
        if errors:
            feedback[i] = "\n".join(errors)
        else:
            metadata[i] = meta
    return {"metadata": metadata, "feedback": feedback}


def route_after_validate(state: IngestionState, max_attempts: int) -> str:
    return "enrich" if state["feedback"] and state["attempts"] < max_attempts else "index"


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def index(state: IngestionState, deps: IngestionDeps) -> IngestionState:
    """Guarda cada tabla válida como parquet y hace upsert en Pinecone (idempotente por id)."""
    source = state["source"]
    skipped = list(state["skipped"])
    ids, texts, payloads = [], [], []
    for i, table in enumerate(state["tables"]):
        meta = state["metadata"].get(i)
        if meta is None:
            skipped.append(
                SkippedTable(
                    caption=table.caption or f"Tabla {i + 1}",
                    title=table.title or "",
                    page=table.pages[0],
                    reason=f"metadatos inválidos tras {state['attempts']} intentos: "
                    f"{state['feedback'].get(i, '')}",
                )
            )
            continue
        table_id = make_table_id(source, table.pages[0], i)
        df = table.to_dataframe()
        parquet = save_table(df, table_id, deps.tables_dir)
        context = state["contexts"][i]
        ids.append(table_id)
        texts.append(embedding_text(table, meta))
        payloads.append(
            pinecone_metadata(table_id, source, table, meta, context, df, _display_path(parquet))
        )

    if ids:
        vectors = deps.embeddings.embed_documents(texts)
        deps.index.upsert(
            vectors=[
                {"id": tid, "values": vec, "metadata": md}
                for tid, vec, md in zip(ids, vectors, payloads)
            ]
        )
        _delete_stale(deps.index, source, vectors[0], keep=set(ids))
    return {"indexed": ids, "skipped": skipped}


def _delete_stale(index: Any, file: str, probe: list[float], keep: set[str]) -> None:
    """Borra vectores de una ingesta anterior del mismo archivo que ya no corresponden.

    Pinecone serverless no borra por filtro de metadatos: se buscan los ids con una
    consulta filtrada por archivo y se borran por id.
    """
    res = index.query(vector=probe, top_k=100, filter={"file": {"$eq": file}})
    stale = [m.id for m in res.matches if m.id not in keep]
    if stale:
        index.delete(ids=stale)
