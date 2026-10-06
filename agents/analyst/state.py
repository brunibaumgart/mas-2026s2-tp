from typing import Literal, TypedDict

from agents.analyst.schemas import PartSelection, QueryPlan

Status = Literal["answered", "partial", "cannot_answer"]


class AnalystState(TypedDict, total=False):
    question: str
    plan: QueryPlan
    candidates: list[dict]
    # Selección del LLM ya verificada contra los datos (ver logic.check_selection).
    selection: list[PartSelection]
    selected_tables: list[dict]
    status: Status
    missing_data: list[str]
    code: str | None
    code_attempts: int
    exec_stdout: str
    exec_stderr: str
    error: str | None
    result: dict | None
    answer: str
