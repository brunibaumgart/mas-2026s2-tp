"""Nodos del grafo del Analista. Las dependencias externas llegan por ``AnalystDeps``."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel

from agents.analyst import logic
from agents.analyst.prompts import (
    ANSWER_SYSTEM,
    CODEGEN_SYSTEM,
    SELECT_SYSTEM,
    UNDERSTAND_SYSTEM,
    answer_user_prompt,
    codegen_user_prompt,
    select_user_prompt,
    table_block,
)
from agents.analyst.schemas import GeneratedCode, QueryPlan, Selection
from agents.analyst.state import AnalystState
from services.sandbox import DEFAULT_TIMEOUT, run_code
from services.table_store import TABLES_DIR, load_table, table_path

MAX_ERROR_CHARS = 2000


@dataclass
class AnalystDeps:
    llm: BaseChatModel
    embeddings: Embeddings
    index: Any
    tables_dir: Path = TABLES_DIR
    top_k: int = 5
    max_code_attempts: int = 3
    timeout: int = DEFAULT_TIMEOUT


def understand(state: AnalystState, deps: AnalystDeps) -> AnalystState:
    plan = deps.llm.with_structured_output(QueryPlan).invoke(
        [("system", UNDERSTAND_SYSTEM), ("human", state["question"])]
    )
    return {"plan": plan, "code": None, "code_attempts": 0, "error": None, "result": None}


def retrieve(state: AnalystState, deps: AnalystDeps) -> AnalystState:
    vector = deps.embeddings.embed_query(state["plan"].rewritten_query)
    res = deps.index.query(vector=vector, top_k=deps.top_k, include_metadata=True)
    candidates = [dict(m.metadata or {}, table_id=m.id, score=m.score) for m in res.matches]
    return {"candidates": candidates}


def _status_fields(state: AnalystState, selection) -> AnalystState:
    by_id = {c["table_id"]: c for c in state["candidates"]}
    used = list(dict.fromkeys(u.table_id for s in selection if s.answerable for u in s.tables))
    return {
        "selection": selection,
        "status": logic.compute_status([s.answerable for s in selection]),
        "missing_data": logic.missing_data(state["plan"].parts, selection),
        "selected_tables": [by_id[t] for t in used if t in by_id],
    }


def select(state: AnalystState, deps: AnalystDeps) -> AnalystState:
    plan, candidates = state["plan"], state["candidates"]
    if candidates:
        raw = deps.llm.with_structured_output(Selection).invoke([
            ("system", SELECT_SYSTEM),
            ("human", select_user_prompt(state["question"], plan, candidates)),
        ])
    else:
        raw = Selection(parts=[])
    selection = logic.check_selection(
        plan.parts,
        raw,
        {c["table_id"]: c for c in candidates},
        lambda tid: load_table(tid, deps.tables_dir),
    )
    if not candidates:
        selection = [
            s.model_copy(update={"missing": "No hay tablas indexadas relacionadas."})
            for s in selection
        ]
    return _status_fields(state, selection)


def route_after_select(state: AnalystState) -> str:
    return "answer" if state["status"] == "cannot_answer" else "codegen"


def codegen(state: AnalystState, deps: AnalystDeps) -> AnalystState:
    tables = [
        table_block(f"{t['table_id']}.parquet", t, load_table(t["table_id"], deps.tables_dir))
        for t in state["selected_tables"]
    ]
    retrying = state["code_attempts"] > 0
    prompt = codegen_user_prompt(
        state["question"], state["plan"], state["selection"], tables,
        previous_code=state.get("code") if retrying else None,
        error=state.get("error") if retrying else None,
    )
    generated = deps.llm.with_structured_output(GeneratedCode).invoke(
        [("system", CODEGEN_SYSTEM), ("human", prompt)]
    )
    return {"code": generated.code, "code_attempts": state["code_attempts"] + 1}


def execute(state: AnalystState, deps: AnalystDeps) -> AnalystState:
    files = {
        f"{t['table_id']}.parquet": table_path(t["table_id"], deps.tables_dir)
        for t in state["selected_tables"]
    }
    res = run_code(state["code"], files=files, timeout=deps.timeout)
    out: AnalystState = {"exec_stdout": res.stdout, "exec_stderr": res.stderr}

    output = logic.parse_output(res.stdout) if res.ok else None
    if res.ok:
        part_ids = [s.part_id for s in state["selection"] if s.answerable]
        errors = logic.validate_output(output, part_ids)
    else:
        errors = [res.stderr[-MAX_ERROR_CHARS:] or f"El proceso terminó con código {res.returncode}."]

    if not errors:
        selection = logic.apply_output(state["selection"], output)
        return out | _status_fields(state, selection) | {"result": output, "error": None}

    out |= {"error": "\n".join(errors), "result": None}
    if state["code_attempts"] >= deps.max_code_attempts:
        msg = f"No se pudo calcular: el código falló tras {state['code_attempts']} intentos."
        selection = [
            logic.mark_unanswerable(s, msg) if s.answerable else s for s in state["selection"]
        ]
        out |= _status_fields(state, selection)
    return out


def route_after_execute(state: AnalystState, max_attempts: int) -> str:
    if state.get("error") and state["code_attempts"] < max_attempts:
        return "codegen"
    return "answer"


def answer(state: AnalystState, deps: AnalystDeps) -> AnalystState:
    prompt = answer_user_prompt(
        state["question"],
        state["status"],
        state["plan"],
        state["selection"],
        state.get("result"),
        state["selected_tables"],
        state["candidates"],
    )
    msg = deps.llm.invoke([("system", ANSWER_SYSTEM), ("human", prompt)])
    return {"answer": msg.content}
