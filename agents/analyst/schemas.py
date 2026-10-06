"""Schemas Pydantic de las salidas estructuradas del Analista."""
from typing import Literal

from pydantic import BaseModel, Field


class QuestionPart(BaseModel):
    id: str = Field(description="Identificador corto: 'p1', 'p2', ...")
    question: str = Field(description="Sub-pregunta autocontenida que se responde con un cálculo.")


class QueryPlan(BaseModel):
    standalone_question: str = Field(
        description="La pregunta reescrita para que se entienda sin la conversación previa "
        "(resolviendo 'y en 2023?', 'esa región', etc.). Si no hay conversación previa o ya es "
        "autocontenida, copiala tal cual."
    )
    rewritten_query: str = Field(
        description="Consulta reescrita para búsqueda semántica de tablas: métricas, entidades "
        "y períodos explícitos, sin palabras de relleno."
    )
    entities: list[str] = Field(description="Entidades mencionadas (empresas, regiones, países).")
    metrics: list[str] = Field(description="Métricas o variables (ingresos, desocupación...).")
    periods: list[str] = Field(description="Períodos mencionados (años, rangos).")
    operations: list[str] = Field(
        description="Operaciones necesarias (crecimiento, proporción, máximo, diferencia...)."
    )
    parts: list[QuestionPart] = Field(
        description="Partes de la pregunta. Una sola si la pregunta pide una única cosa; varias "
        "si pide cosas distintas (p. ej. 'qué región' y 'por cuánto superó a X')."
    )


class TableUse(BaseModel):
    table_id: str = Field(description="table_id exacto de una tabla candidata.")
    columns: list[str] = Field(description="Columnas exactas de esa tabla que hacen falta.")
    row_labels: list[str] = Field(
        description="Etiquetas de fila exactas que hacen falta (vacío si se usan todas las filas)."
    )


class PartSelection(BaseModel):
    part_id: str = Field(description="id de la parte de la pregunta.")
    answerable: bool = Field(
        description="true solo si TODOS los valores necesarios están en las tablas candidatas."
    )
    tables: list[TableUse] = Field(description="Tablas necesarias (vacío si no es respondible).")
    missing: str | None = Field(
        description="Si no es respondible: qué dato falta y qué cubre la tabla relacionada, si hay."
    )
    conversions: str | None = Field(
        description="Conversiones permitidas que hay que hacer e informar (cambio de escala, "
        "% a fracción, suma de meses), o null."
    )


class Selection(BaseModel):
    parts: list[PartSelection]


class GeneratedCode(BaseModel):
    code: str = Field(description="Programa Python completo, sin bloques markdown.")


class Violation(BaseModel):
    part_id: str = Field(description="id de la parte con el problema.")
    kind: Literal["calculo", "dato_faltante"] = Field(
        description="'calculo': el programa calcula mal o aproxima algo que no debe (se puede "
        "corregir reescribiendo el código). 'dato_faltante': la parte necesita un dato que no "
        "está en las tablas (no se puede corregir)."
    )
    detail: str = Field(description="Qué está mal, en una o dos oraciones, citando el código.")


class Verdict(BaseModel):
    ok: bool = Field(description="true si no hay ninguna violación.")
    violations: list[Violation] = Field(description="Violaciones encontradas (vacío si ok).")
