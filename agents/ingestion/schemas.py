"""Schemas Pydantic que el LLM completa con with_structured_output."""
from typing import Literal

from pydantic import BaseModel, Field


class ColumnMetadata(BaseModel):
    name: str = Field(description="Nombre exacto de la columna, copiado tal cual de la lista dada.")
    description: str = Field(description="Qué representa la columna, en una frase.")
    type: Literal["texto", "numero"] = Field(
        description="'texto' si la columna es una etiqueta (región, mes, concepto, año como "
        "dimensión); 'numero' si contiene valores para calcular."
    )
    unit: str | None = Field(
        description="Unidad de los valores (p. ej. 'miles de $ nominales', '%', 'millones de USD'); "
        "null si la columna es una etiqueta."
    )


class TableMetadata(BaseModel):
    name: str = Field(description="Nombre corto y legible de la tabla.")
    description: str = Field(
        description="De 2 a 4 oraciones: qué mide la tabla, sus unidades, período y alcance "
        "(entidad, regiones, etc.). Se usa para búsqueda semántica."
    )
    unit: str | None = Field(description="Unidad general de los valores numéricos, según el contexto.")
    period: str | None = Field(description="Período que cubre la tabla, p. ej. '2020–2024'.")
    columns: list[ColumnMetadata] = Field(
        description="Exactamente una entrada por columna de la tabla, en el mismo orden."
    )
    row_headers: list[str] = Field(
        description="Etiquetas de fila (los valores de la columna que identifica cada fila, "
        "p. ej. conceptos, categorías o regiones), copiadas tal cual. Lista vacía si no hay."
    )
