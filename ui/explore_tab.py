"""Pestaña "Explorar": tablas indexadas en Pinecone."""
import streamlit as st

from services.vector_store import list_tables
from ui.resources import get_resources
from ui.widgets import table_card


def render() -> None:
    st.subheader("Tablas indexadas")
    if st.button("Actualizar"):
        st.session_state.pop("tables", None)
    if "tables" not in st.session_state:
        try:
            st.session_state["tables"] = list_tables(get_resources().index)
        except Exception as exc:  # noqa: BLE001
            st.error(f"No se pudieron leer las tablas de Pinecone: {type(exc).__name__}: {exc}")
            return

    tables = st.session_state["tables"]
    if not tables:
        st.info("Todavía no hay tablas indexadas. Subí un PDF en la pestaña anterior.")
        return
    files = sorted({t.get("file", "") for t in tables})
    chosen = st.multiselect("Archivo", files, default=files)
    for t in tables:
        if t.get("file", "") in chosen:
            table_card(t)
