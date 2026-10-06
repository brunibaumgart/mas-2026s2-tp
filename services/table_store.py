"""Persistencia de tablas extraídas como parquet (data/tables/{table_id}.parquet)."""
from pathlib import Path

import pandas as pd

TABLES_DIR = Path(__file__).resolve().parent.parent / "data" / "tables"


def save_table(df: pd.DataFrame, table_id: str, tables_dir: Path = TABLES_DIR) -> Path:
    tables_dir.mkdir(parents=True, exist_ok=True)
    path = tables_dir / f"{table_id}.parquet"
    df.to_parquet(path, index=False)
    return path


def table_path(table_id: str, tables_dir: Path = TABLES_DIR) -> Path:
    return tables_dir / f"{table_id}.parquet"


def load_table(table_id: str, tables_dir: Path = TABLES_DIR) -> pd.DataFrame:
    return pd.read_parquet(table_path(table_id, tables_dir))


def text_values(df: pd.DataFrame) -> list[str]:
    """Valores distintos de las columnas de texto (candidatos a encabezado de fila)."""
    values: list[str] = []
    for col in df.columns:
        if not pd.api.types.is_numeric_dtype(df[col]):
            for v in df[col].dropna().astype(str):
                if v not in values:
                    values.append(v)
    return values
