"""Grafo de ingesta:

load_pdf → extract_tables → collect_context → enrich → validate ─┬→ index
                                                   ↑               │
                                                   └── reintento ──┘ (con feedback)
"""
from __future__ import annotations

from functools import partial
from pathlib import Path

from langgraph.graph import END, START, StateGraph

from agents.ingestion import nodes
from agents.ingestion.nodes import IngestionDeps
from agents.ingestion.state import IngestionState


def build_graph(deps: IngestionDeps):
    g = StateGraph(IngestionState)
    g.add_node("load_pdf", nodes.load_pdf)
    g.add_node("extract_tables", nodes.extract_tables)
    g.add_node("collect_context", nodes.collect_context)
    g.add_node("enrich", partial(nodes.enrich, deps=deps))
    g.add_node("validate", nodes.validate)
    g.add_node("index", partial(nodes.index, deps=deps))

    g.add_edge(START, "load_pdf")
    g.add_edge("load_pdf", "extract_tables")
    g.add_edge("extract_tables", "collect_context")
    g.add_edge("collect_context", "enrich")
    g.add_edge("enrich", "validate")
    g.add_conditional_edges(
        "validate",
        partial(nodes.route_after_validate, max_attempts=deps.max_attempts),
        {"enrich": "enrich", "index": "index"},
    )
    g.add_edge("index", END)
    return g.compile()


def default_deps() -> IngestionDeps:
    from services.llm import get_chat_model, get_embeddings
    from services.vector_store import get_index

    return IngestionDeps(llm=get_chat_model(), embeddings=get_embeddings(), index=get_index())


def run_config(pdf_path: str | Path) -> dict:
    """Nombre, tags y metadatos de la traza en LangSmith."""
    name = Path(pdf_path).name
    return {"run_name": f"ingesta:{name}", "tags": ["ingestion"], "metadata": {"file": name}}


def ingest_pdf(pdf_path: str | Path, deps: IngestionDeps | None = None) -> IngestionState:
    graph = build_graph(deps or default_deps())
    return graph.invoke({"pdf_path": str(pdf_path)}, config=run_config(pdf_path))
