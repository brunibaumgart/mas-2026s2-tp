"""Pestaña "Preguntar": chat con el Analista, con memoria de la conversación y revisión humana."""
from uuid import uuid4

import pandas as pd
import streamlit as st
from langgraph.types import Command

from agents.analyst.graph import run_config
from ui.resources import get_resources
from ui.widgets import table_data

NODE_LABELS = {
    "understand": "Consulta analizada",
    "retrieve": "Tablas candidatas recuperadas",
    "select": "Tablas seleccionadas",
    "review": "Tablas confirmadas",
    "codegen": "Código generado",
    "execute": "Código ejecutado",
    "verify": "Cálculo verificado",
    "answer": "Respuesta redactada",
}
STATUS_BADGE = {
    "answered": (st.success, "answered — respondida"),
    "partial": (st.warning, "partial — respondida en parte"),
    "cannot_answer": (st.error, "cannot_answer — no se puede responder con las tablas"),
}


def _detail(node: str, values: dict) -> str:
    if node == "understand":
        return f"búsqueda: “{values['plan'].rewritten_query}”"
    if node == "retrieve":
        return f"{len(values['candidates'])} candidatas"
    if node in ("select", "review"):
        return f"estado: {values['status']}"
    if node == "codegen":
        return f"intento {values['code_attempts']}"
    if node == "execute":
        return "con error, se reintenta" if values.get("error") else "OK"
    if node == "verify":
        verdict = values.get("verdict")
        if verdict is None or verdict.ok:
            return "sin observaciones"
        return f"{len(verdict.violations)} observación(es)" + (", se reintenta" if values.get("error") else "")
    return ""


def _stream(graph_input, config: dict) -> tuple[dict | None, dict | None]:
    """Corre el grafo mostrando el avance. Devuelve (estado, pedido de revisión pendiente)."""
    graph = get_resources().analyst
    pending = None
    with st.status("Pensando...", expanded=True) as status:
        try:
            for update in graph.stream(graph_input, config=config, stream_mode="updates"):
                for node, values in update.items():
                    if node == "__interrupt__":
                        pending = values[0].value
                        continue
                    st.write(f"✔ {NODE_LABELS.get(node, node)} — {_detail(node, values or {})}")
        except Exception as exc:  # noqa: BLE001
            status.update(label="Error", state="error")
            st.error(f"{type(exc).__name__}: {exc}")
            return None, None
        label = "Esperando tu confirmación" if pending else "Listo"
        status.update(label=label, state="complete", expanded=False)
    return graph.get_state(config).values, pending


# ------------------------------------------------------------------ resultado
def _citations(state: dict) -> pd.DataFrame:
    names = {f"{t['table_id']}.parquet": t.get("name") for t in state.get("selected_tables", [])}
    rows = [
        {
            "Parte": c.get("part_id"),
            "Tabla": names.get(str(c.get("table")), c.get("table")),
            "Fila": " · ".join(c["row"]) if isinstance(c.get("row"), list) else c.get("row"),
            "Columna": c.get("column"),
            "Valor": c.get("value"),
            "Verificada": "✔" if c.get("ok") else f"✘ {c.get('problem')}",
        }
        for c in state.get("citations", [])
    ]
    return pd.DataFrame(rows)


def _retrieval(state: dict) -> pd.DataFrame:
    r = state.get("retrieval") or {}
    names = {c["table_id"]: c.get("name") for c in state.get("candidates", [])}

    def rank(key, tid):
        ids = r.get(key) or []
        return ids.index(tid) + 1 if tid in ids else None

    return pd.DataFrame([
        {"Tabla": names.get(tid, tid), "Semántica": rank("dense", tid), "BM25": rank("bm25", tid),
         "Fusión (RRF)": i}
        for i, tid in enumerate(r.get("fused", []), start=1)
    ])


def _render_result(question: str, state: dict) -> None:
    plan = state.get("plan")
    if plan and plan.standalone_question.strip() != question.strip():
        st.caption(f"Interpretada como: {plan.standalone_question}")
    show, label = STATUS_BADGE[state["status"]]
    show(f"Estado: {label}")
    st.markdown(state["answer"])
    for m in state.get("missing_data", []):
        st.caption(f"Falta: {m}")

    if state.get("chart"):
        st.image(state["chart"], width=520)

    notes = []
    attempts = state.get("code_attempts", 0)
    if attempts > 1:
        notes.append(f"reintentos de código: {attempts - 1}")
    verdict = state.get("verdict")
    if verdict is not None:
        notes.append("verificador: sin observaciones" if verdict.ok else "verificador: con observaciones")
    citations = state.get("citations", [])
    if citations:
        ok = sum(1 for c in citations if c.get("ok"))
        notes.append(f"celdas citadas verificadas: {ok}/{len(citations)}")
    if state.get("review"):
        notes.append(f"revisión humana: {state['review'].get('action')}")
    if notes:
        st.caption(" · ".join(notes))

    if verdict is not None and verdict.violations:
        with st.expander("Observaciones del verificador"):
            for v in verdict.violations:
                st.markdown(f"- **{v.part_id}** ({v.kind}): {v.detail}")
    if citations:
        with st.expander("Celdas usadas en el cálculo"):
            st.dataframe(_citations(state), hide_index=True, width="stretch")
    if state.get("selected_tables"):
        with st.expander(f"Tablas usadas ({len(state['selected_tables'])})"):
            for t in state["selected_tables"]:
                st.markdown(f"**{t.get('name')}** — {t.get('source')}")
                st.dataframe(table_data(t), hide_index=True, width="stretch")
    if state.get("retrieval", {}).get("fused"):
        with st.expander("Recuperación (semántica + BM25)"):
            st.dataframe(_retrieval(state), hide_index=True, width="stretch")
    if state.get("code"):
        with st.expander("Código generado"):
            st.code(state["code"], language="python")
        with st.expander("Salida de la ejecución"):
            st.code(state.get("exec_stdout") or "(vacía)", language="text")
            if state.get("exec_stderr"):
                st.code(state["exec_stderr"], language="text")


# ------------------------------------------------------------------ revisión humana
def _review_form(pending: dict) -> dict | None:
    """Formulario de la revisión: devuelve la decisión cuando el usuario la envía."""
    request = pending["request"]
    names = {c["table_id"]: f"{c.get('name')} ({c.get('source')})" for c in request["candidates"]}
    st.info("Revisá las tablas que eligió el Analista antes de que genere el código.")
    with st.form("review"):
        chosen = {}
        for p in request["parts"]:
            chosen[p["part_id"]] = st.multiselect(
                f"{p['part_id']}: {p['question']}",
                options=list(names),
                default=[t for t in p["tables"] if t in names],
                format_func=names.get,
                key=f"review_{pending['id']}_{p['part_id']}",
            )
        calc, cancel = st.columns(2)
        go = calc.form_submit_button("Calcular con estas tablas", type="primary")
        stop = cancel.form_submit_button("Cancelar")
    if stop:
        return {"action": "cancel"}
    if go:
        original = {p["part_id"]: p["tables"] for p in request["parts"]}
        return {"action": "approve"} if chosen == original else {"action": "edit", "tables": chosen}
    return None


# ------------------------------------------------------------------ pestaña
def _controls(ss) -> None:
    left, right = st.columns([3, 1])
    ss.human_review = left.toggle(
        "Revisar las tablas antes de calcular",
        value=ss.get("human_review", False),
        help="El Analista se pausa después de elegir las tablas y te deja confirmarlas o cambiarlas.",
    )
    if right.button("Nueva conversación", width="stretch"):
        ss.chat, ss.pending, ss.thread_id = [], None, uuid4().hex
        st.rerun()


def render() -> None:
    ss = st.session_state
    ss.setdefault("chat", [])
    ss.setdefault("pending", None)
    ss.setdefault("thread_id", uuid4().hex)

    st.subheader("Hacer una pregunta")
    st.caption(
        "La conversación tiene memoria: podés repreguntar (\"¿y en 2023?\"). "
        "\"Nueva conversación\" la borra."
    )
    _controls(ss)

    for turn in ss.chat:
        with st.chat_message("user"):
            st.write(turn["question"])
        with st.chat_message("assistant"):
            _render_result(turn["question"], turn["state"])

    pending = ss.pending
    if pending:
        config = run_config(pending["question"], thread_id=ss.thread_id)
        with st.chat_message("user"):
            st.write(pending["question"])
        with st.chat_message("assistant"):
            decision = _review_form(pending)
            if decision is not None:
                state, _ = _stream(Command(resume=decision), config)
                ss.pending = None
                if state:
                    ss.chat.append({"question": pending["question"], "state": state})
                st.rerun()

    question = st.chat_input(
        "Ej.: ¿Cuánto crecieron las ventas de la región Sur en 2024?", disabled=bool(pending)
    )
    if question:
        config = run_config(question, thread_id=ss.thread_id)
        with st.chat_message("user"):
            st.write(question)
        with st.chat_message("assistant"):
            state, request = _stream({"question": question, "human_review": ss.human_review}, config)
            if request:
                ss.pending = {"id": uuid4().hex, "question": question, "request": request}
                st.rerun()
            elif state:
                _render_result(question, state)
                ss.chat.append({"question": question, "state": state})
