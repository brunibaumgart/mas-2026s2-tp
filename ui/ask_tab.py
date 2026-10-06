"""Pestaña "Preguntar": chat con el Analista."""
import streamlit as st

from agents.analyst.graph import run_config
from ui.resources import get_resources
from ui.widgets import table_data

NODE_LABELS = {
    "understand": "Consulta analizada",
    "retrieve": "Tablas candidatas recuperadas",
    "select": "Tablas seleccionadas",
    "codegen": "Código generado",
    "execute": "Código ejecutado",
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
    if node == "select":
        return f"estado preliminar: {values['status']}"
    if node == "codegen":
        return f"intento {values['code_attempts']}"
    if node == "execute":
        return "con error, se reintenta" if values.get("error") else "OK"
    return ""


def _run(question: str) -> dict | None:
    state: dict = {}
    with st.status("Pensando...", expanded=True) as status:
        try:
            updates = get_resources().analyst.stream(
                {"question": question}, config=run_config(question), stream_mode="updates"
            )
            for update in updates:
                for node, values in update.items():
                    state.update(values or {})
                    st.write(f"✔ {NODE_LABELS.get(node, node)} — {_detail(node, values or {})}")
        except Exception as exc:  # noqa: BLE001
            status.update(label="Error", state="error")
            st.error(f"{type(exc).__name__}: {exc}")
            return None
        status.update(label="Listo", state="complete", expanded=False)
    return state


def _render_result(state: dict) -> None:
    show, label = STATUS_BADGE[state["status"]]
    show(f"Estado: {label}")
    st.markdown(state["answer"])
    for m in state.get("missing_data", []):
        st.caption(f"Falta: {m}")

    attempts = state.get("code_attempts", 0)
    if attempts > 1:
        st.caption(f"Reintentos de código: {attempts - 1}")
    if state.get("selected_tables"):
        with st.expander(f"Tablas usadas ({len(state['selected_tables'])})"):
            for t in state["selected_tables"]:
                st.markdown(f"**{t.get('name')}** — {t.get('source')}")
                st.dataframe(table_data(t), hide_index=True, width="stretch")
    if state.get("code"):
        with st.expander("Código generado"):
            st.code(state["code"], language="python")
        with st.expander("Salida de la ejecución"):
            st.code(state.get("exec_stdout") or "(vacía)", language="text")
            if state.get("exec_stderr"):
                st.code(state["exec_stderr"], language="text")


def render() -> None:
    st.subheader("Hacer una pregunta")
    history = st.session_state.setdefault("chat", [])
    for turn in history:
        with st.chat_message("user"):
            st.write(turn["question"])
        with st.chat_message("assistant"):
            _render_result(turn["state"])

    question = st.chat_input("Ej.: ¿Cuánto crecieron las ventas de la región Sur en 2024?")
    if question:
        with st.chat_message("user"):
            st.write(question)
        with st.chat_message("assistant"):
            state = _run(question)
            if state:
                _render_result(state)
                history.append({"question": question, "state": state})
