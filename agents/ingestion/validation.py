"""Validación determinística de los metadatos generados por el LLM."""
import pandas as pd

from agents.ingestion.schemas import TableMetadata
from services.table_store import text_values

MAX_LISTED_VALUES = 30


def validate_metadata(meta: TableMetadata, df: pd.DataFrame) -> list[str]:
    """Devuelve la lista de errores (vacía si los metadatos son válidos)."""
    df_columns = [str(c) for c in df.columns]
    errors = []
    names = [c.name for c in meta.columns]
    if len(names) != len(df_columns):
        errors.append(f"La tabla tiene {len(df_columns)} columnas y devolviste {len(names)}.")
    unknown = [n for n in names if n not in df_columns]
    if unknown:
        errors.append(f"Estas columnas no existen en la tabla: {unknown}.")
    uncovered = [c for c in df_columns if c not in names]
    if uncovered:
        errors.append(f"Faltan estas columnas: {uncovered}.")
    if errors:
        errors.append(f"Columnas válidas, en orden: {df_columns}.")

    labels = text_values(df)
    repeated = sorted({r for r in meta.row_headers if meta.row_headers.count(r) > 1})
    if repeated:
        errors.append(f"Encabezados de fila repetidos: {repeated}. Listá cada uno una vez.")
    bad_rows = [r for r in meta.row_headers if r not in labels]
    if bad_rows:
        errors.append(
            f"Estos encabezados de fila no aparecen en la tabla: {bad_rows}. "
            f"Valores válidos: {labels[:MAX_LISTED_VALUES]}."
        )
    return errors
