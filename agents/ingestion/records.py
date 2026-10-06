"""Armado del id, el texto a embeber y los metadatos de Pinecone de cada tabla."""
import hashlib

import pandas as pd

from agents.ingestion.prompts import PREVIEW_ROWS
from agents.ingestion.schemas import TableMetadata
from services.pdf_context import TableContext
from services.pdf_extract import Table


def make_table_id(source: str, page_start: int, index: int) -> str:
    return hashlib.sha1(f"{source}|{page_start}|{index}".encode()).hexdigest()


def format_source(file: str, pages: list[int]) -> str:
    span = f"p. {pages[0]}" if len(pages) == 1 else f"pp. {pages[0]}–{pages[-1]}"
    return f"{file}, {span}"


def _column_lines(meta: TableMetadata) -> list[str]:
    return [
        f"{c.name}: {c.description} [{c.type}" + (f", {c.unit}]" if c.unit else "]")
        for c in meta.columns
    ]


def embedding_text(table: Table, meta: TableMetadata) -> str:
    """Nombre + descripción + columnas + encabezados de fila (una entrada por tabla)."""
    lines = [
        f"{meta.name} ({table.caption})" if table.caption else meta.name,
        meta.description,
        f"Unidad: {meta.unit}" if meta.unit else "",
        f"Período: {meta.period}" if meta.period else "",
        "Columnas: " + "; ".join(_column_lines(meta)),
        "Filas: " + ", ".join(meta.row_headers) if meta.row_headers else "",
    ]
    return "\n".join(line for line in lines if line)


def pinecone_metadata(
    table_id: str,
    file: str,
    table: Table,
    meta: TableMetadata,
    context: TableContext,
    df: pd.DataFrame,
    parquet_path: str,
) -> dict:
    payload = {
        "table_id": table_id,
        "name": meta.name,
        "description": meta.description,
        "source": format_source(file, table.pages),
        "file": file,
        "caption": table.caption,
        "unit": meta.unit,
        "period": meta.period,
        "page_start": table.pages[0],
        "pages": [str(p) for p in table.pages],
        "columns": [str(c) for c in df.columns],
        "column_descriptions": _column_lines(meta),
        "row_headers": meta.row_headers,
        "n_rows": len(df),
        "preview": df.head(PREVIEW_ROWS).to_csv(index=False),
        "context_above": context.above,
        "context_below": context.below,
        "parquet_path": parquet_path,
    }
    # Pinecone rechaza metadatos con valor null.
    return {k: v for k, v in payload.items() if v is not None}
