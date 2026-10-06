from typing import TypedDict

from agents.ingestion.schemas import TableMetadata
from services.pdf_context import TableContext
from services.pdf_extract import SkippedTable, Table


class IngestionState(TypedDict, total=False):
    pdf_path: str
    source: str
    page_texts: list[str]
    tables: list[Table]
    skipped: list[SkippedTable]
    contexts: list[TableContext]
    # Las claves son el índice de la tabla en ``tables``.
    candidates: dict[int, TableMetadata | None]
    metadata: dict[int, TableMetadata]
    feedback: dict[int, str]
    attempts: int
    indexed: list[str]
