import operator
from typing import Annotated, Literal, TypedDict

from agents.analyst.schemas import PartSelection, QueryPlan, Verdict

Status = Literal["answered", "partial", "cannot_answer"]


class Turn(TypedDict):
    """Un turno de la conversación, guardado en la memoria del hilo."""

    question: str
    standalone: str
    tables: list[str]
    status: Status


class AnalystState(TypedDict, total=False):
    # ---- entrada
    question: str
    human_review: bool  # pausar antes de generar código para que el usuario confirme las tablas

    # ---- memoria del hilo: con un checkpointer persiste entre preguntas del mismo thread_id;
    # cada respuesta agrega un turno (reducer operator.add).
    history: Annotated[list[Turn], operator.add]

    # ---- por pregunta (understand los reinicia)
    plan: QueryPlan
    candidates: list[dict]
    retrieval: dict  # rankings denso, BM25 y fusionado (para la UI y la evaluación)
    # Selección del LLM ya verificada contra los datos (ver logic.check_selection).
    selection: list[PartSelection]
    selected_tables: list[dict]
    review: dict | None  # decisión del usuario en la revisión humana
    status: Status
    missing_data: list[str]
    code: str | None
    code_attempts: int
    exec_stdout: str
    exec_stderr: str
    error: str | None
    result: dict | None
    citations: list[dict]  # celdas citadas por el código, verificadas contra los parquet
    verdict: Verdict | None
    chart: bytes | None
    answer: str
