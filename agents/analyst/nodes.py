"""Nodos del grafo del Analista. Las dependencias externas llegan por ``AnalystDeps``.

Roles (cada uno con su prompt y su salida estructurada):
- understand (modelo rápido): interpreta la pregunta usando la memoria del hilo.
- select (modelo principal): elige tablas; el código verifica la elección contra los datos.
- codegen (modelo principal): escribe el programa.
- verify (modelo principal): agente verificador; solo evalúa, no resuelve.
- answer (modelo rápido): redacta a partir de resultados ya calculados y verificados.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel
from langgraph.types import interrupt

from agents.analyst import logic, retrieval
from agents.analyst.prompts import (
    ANSWER_SYSTEM,
    CODEGEN_SYSTEM,
    SELECT_SYSTEM,
    UNDERSTAND_SYSTEM,
    VERIFY_SYSTEM,
    answer_user_prompt,
    codegen_user_prompt,
    select_user_prompt,
    table_block,
    understand_user_prompt,
    verify_user_prompt,
)
from agents.analyst.schemas import GeneratedCode, QueryPlan, Selection, Verdict
from agents.analyst.state import AnalystState
from services.sandbox import DEFAULT_TIMEOUT, run_code
from services.table_store import TABLES_DIR, load_table, table_path
from services.vector_store import list_tables

MAX_ERROR_CHARS = 2000


@dataclass
class AnalystDeps:
    llm: BaseChatModel  # selección, código y verificación: donde un error es caro
    embeddings: Embeddings
    index: Any
    llm_fast: BaseChatModel | None = None  # interpretar y redactar; si falta, usa ``llm``
    tables_dir: Path = TABLES_DIR
    top_k: int = 5  # candidatas que ve el selector
    dense_k: int = 10  # resultados de Pinecone que entran a la fusión
    hybrid: bool = True  # BM25 + RRF además de la búsqueda semántica
    verify: bool = True  # agente verificador después de ejecutar
    history_turns: int = 3  # ventana de la memoria del hilo
    max_code_attempts: int = 3  # intentos de código, compartidos por ejecución y verificador
    timeout: int = DEFAULT_TIMEOUT

    @property
    def fast(self) -> BaseChatModel:
        return self.llm_fast or self.llm


def question_of(state: AnalystState) -> str:
    """La pregunta autocontenida (resuelta con la memoria del hilo) o, si no hay, la original."""
    plan = state.get("plan")
    return (plan.standalone_question if plan else None) or state["question"]


# --------------------------------------------------------------------- understand
def understand(state: AnalystState, deps: AnalystDeps) -> AnalystState:
    history = (state.get("history") or [])[-deps.history_turns:]
    plan = deps.fast.with_structured_output(QueryPlan).invoke(
        [("system", UNDERSTAND_SYSTEM), ("human", understand_user_prompt(state["question"], history))]
    )
    # Reinicia los campos de la pregunta anterior: con memoria (checkpointer) el estado persiste.
    return {
        "plan": plan, "candidates": [], "retrieval": {}, "selection": [], "selected_tables": [],
        "review": None, "missing_data": [], "code": None, "code_attempts": 0,
        "exec_stdout": "", "exec_stderr": "", "error": None, "result": None,
        "citations": [], "verdict": None, "chart": None, "answer": "",
    }


# --------------------------------------------------------------------- retrieve
def _search_text(plan: QueryPlan) -> str:
    return " ".join([plan.rewritten_query, *plan.entities, *plan.metrics, *plan.periods])


def retrieve(state: AnalystState, deps: AnalystDeps) -> AnalystState:
    plan = state["plan"]
    vector = deps.embeddings.embed_query(plan.rewritten_query)
    res = deps.index.query(vector=vector, top_k=deps.dense_k, include_metadata=True)
    dense = {m.id: dict(m.metadata or {}, table_id=m.id, score=m.score) for m in res.matches}
    dense_ids = list(dense)

    if not deps.hybrid:
        ids = dense_ids[: deps.top_k]
        return {"candidates": [dense[i] for i in ids], "retrieval": {"dense": dense_ids, "fused": ids}}

    catalog = {t["table_id"]: t for t in list_tables(deps.index)}
    bm25_ids = retrieval.bm25_rank(
        _search_text(plan), {tid: retrieval.table_text(md) for tid, md in catalog.items()}
    )[: deps.dense_k]
    fused = retrieval.rrf([dense_ids, bm25_ids])[: deps.top_k]
    candidates = []
    for tid, score in fused:
        md = dense.get(tid) or catalog.get(tid)
        if md is not None:
            candidates.append(dict(md, table_id=tid, score=score))
    return {
        "candidates": candidates,
        "retrieval": {"dense": dense_ids, "bm25": bm25_ids, "fused": [tid for tid, _ in fused]},
    }


# --------------------------------------------------------------------- select
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
            ("human", select_user_prompt(question_of(state), plan, candidates)),
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
    if state["status"] == "cannot_answer":
        return "answer"
    return "review" if state.get("human_review") else "codegen"


# --------------------------------------------------------------------- review (humano)
def review(state: AnalystState, deps: AnalystDeps) -> AnalystState:
    """Human-in-the-loop: pausa el grafo hasta que el usuario confirma o cambia las tablas."""
    questions = {p.id: p.question for p in state["plan"].parts}
    decision = interrupt({
        "parts": [
            {"part_id": s.part_id, "question": questions.get(s.part_id, ""),
             "tables": [u.table_id for u in s.tables]}
            for s in state["selection"] if s.answerable
        ],
        "candidates": [
            {"table_id": c["table_id"], "name": c.get("name"), "source": c.get("source")}
            for c in state["candidates"]
        ],
    })
    selection = logic.apply_review(state["selection"], decision or {})
    return _status_fields(state, selection) | {"review": decision}


def route_after_review(state: AnalystState) -> str:
    return "answer" if state["status"] == "cannot_answer" else "codegen"


# --------------------------------------------------------------------- codegen / execute
def _table_blocks(state: AnalystState, deps: AnalystDeps) -> list[str]:
    return [
        table_block(f"{t['table_id']}.parquet", t, load_table(t["table_id"], deps.tables_dir))
        for t in state["selected_tables"]
    ]


def codegen(state: AnalystState, deps: AnalystDeps) -> AnalystState:
    retrying = state["code_attempts"] > 0
    prompt = codegen_user_prompt(
        question_of(state), state["plan"], state["selection"], _table_blocks(state, deps),
        previous_code=state.get("code") if retrying else None,
        error=state.get("error") if retrying else None,
    )
    generated = deps.llm.with_structured_output(GeneratedCode).invoke(
        [("system", CODEGEN_SYSTEM), ("human", prompt)]
    )
    return {"code": generated.code, "code_attempts": state["code_attempts"] + 1}


def _give_up(state: AnalystState, reason: str) -> AnalystState:
    """Sin intentos: las partes que seguían respondibles pasan a no respondibles."""
    selection = [
        logic.mark_unanswerable(s, reason) if s.answerable else s for s in state["selection"]
    ]
    return _status_fields(state, selection) | {"result": None}


def execute(state: AnalystState, deps: AnalystDeps) -> AnalystState:
    files = {
        f"{t['table_id']}.parquet": table_path(t["table_id"], deps.tables_dir)
        for t in state["selected_tables"]
    }
    res = run_code(state["code"], files=files, timeout=deps.timeout)
    out: AnalystState = {"exec_stdout": res.stdout, "exec_stderr": res.stderr, "chart": res.chart}

    output = logic.parse_output(res.stdout) if res.ok else None
    citations: list[dict] = []
    if res.ok:
        part_ids = [s.part_id for s in state["selection"] if s.answerable]
        errors = logic.validate_output(output, part_ids)
        if not errors:
            tables = {name: load_table(name.removesuffix(".parquet"), deps.tables_dir) for name in files}
            citations, errors = logic.check_citations(output, part_ids, tables)
    else:
        errors = [res.stderr[-MAX_ERROR_CHARS:] or f"El proceso terminó con código {res.returncode}."]
    out["citations"] = citations

    if not errors:
        selection = logic.apply_output(state["selection"], output)
        return out | _status_fields(state, selection) | {"result": output, "error": None}

    out |= {"error": "\n".join(errors), "result": None}
    if state["code_attempts"] >= deps.max_code_attempts:
        out |= _give_up(
            state, f"No se pudo calcular: el código falló tras {state['code_attempts']} intentos."
        )
    return out


def route_after_execute(state: AnalystState, max_attempts: int, verify: bool) -> str:
    if state.get("error"):
        return "codegen" if state["code_attempts"] < max_attempts else "answer"
    return "verify" if verify and state["status"] != "cannot_answer" else "answer"


# --------------------------------------------------------------------- verify
def verify(state: AnalystState, deps: AnalystDeps) -> AnalystState:
    """Agente verificador: revisa el código ejecutado contra las reglas de respondibilidad."""
    verdict = deps.llm.with_structured_output(Verdict).invoke([
        ("system", VERIFY_SYSTEM),
        ("human", verify_user_prompt(
            question_of(state), state["plan"], state["selection"], _table_blocks(state, deps),
            state["code"], state["result"],
        )),
    ])
    selection, calc_errors = logic.apply_verdict(state["selection"], verdict)
    out = _status_fields(state, selection) | {"verdict": verdict, "error": None}
    if not calc_errors:
        return out
    if state["code_attempts"] < deps.max_code_attempts:
        return out | {"error": "\n".join(calc_errors)}
    rejected = {v.part_id for v in verdict.violations if v.kind == "calculo"}
    selection = [
        logic.mark_unanswerable(s, "El verificador rechazó el cálculo y no quedan intentos.")
        if s.answerable and s.part_id in rejected else s
        for s in selection
    ]
    return out | _status_fields(state, selection)


def route_after_verify(state: AnalystState, max_attempts: int) -> str:
    if state.get("error") and state["code_attempts"] < max_attempts:
        return "codegen"
    return "answer"


# --------------------------------------------------------------------- answer
def answer(state: AnalystState, deps: AnalystDeps) -> AnalystState:
    prompt = answer_user_prompt(
        question_of(state),
        state["status"],
        state["plan"],
        state["selection"],
        state.get("result"),
        state["selected_tables"],
        state["candidates"],
    )
    msg = deps.fast.invoke([("system", ANSWER_SYSTEM), ("human", prompt)])
    turn = {
        "question": state["question"],
        "standalone": question_of(state),
        "tables": [t.get("name") for t in state["selected_tables"]],
        "status": state["status"],
    }
    return {"answer": msg.content, "history": [turn]}
