"""Pestaña "Subir PDF": corre el grafo de ingesta mostrando cada nodo."""
import tempfile
from pathlib import Path

import streamlit as st

from agents.ingestion.graph import run_config
from agents.ingestion.records import format_source, make_table_id
from ui.resources import get_resources
from ui.widgets import skipped_list, table_card

NODE_LABELS = {
    "load_pdf": "PDF cargado",
    "extract_tables": "Tablas extraídas",
    "collect_context": "Contexto recolectado",
    "enrich": "Metadatos generados con el LLM",
    "validate": "Metadatos validados",
    "index": "Tablas indexadas en Pinecone",
}


def _detail(node: str, values: dict) -> str:
    if node == "load_pdf":
        return f"{len(values['page_texts'])} páginas"
    if node == "extract_tables":
        return f"{len(values['tables'])} tablas, {len(values['skipped'])} salteadas"
    if node == "enrich":
        return f"intento {values['attempts']}"
    if node == "validate":
        bad = len(values["feedback"])
        return "todas válidas" if not bad else f"{bad} con errores, se reintenta"
    if node == "index":
        return f"{len(values['indexed'])} tablas"
    return ""


def _ingest(name: str, data: bytes) -> dict | None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / name
        path.write_bytes(data)
        state: dict = {}
        with st.status(f"Ingiriendo {name}...", expanded=True) as status:
            try:
                updates = get_resources().ingestion.stream(
                    {"pdf_path": str(path)}, config=run_config(path), stream_mode="updates"
                )
                for update in updates:
                    for node, values in update.items():
                        state.update(values or {})
                        st.write(f"✔ {NODE_LABELS.get(node, node)} — {_detail(node, values or {})}")
            except Exception as exc:  # noqa: BLE001
                status.update(label=f"Error al ingerir {name}", state="error")
                st.error(f"{type(exc).__name__}: {exc}")
                return None
            status.update(label=f"{name}: {len(state['indexed'])} tablas indexadas", state="complete")
    return state


def _summary(state: dict) -> list[dict]:
    """Metadatos de cada tabla indexada, en el mismo formato que guarda Pinecone."""
    cards = []
    for i, table in enumerate(state["tables"]):
        meta = state["metadata"].get(i)
        if meta is None:
            continue
        cards.append({
            "table_id": make_table_id(state["source"], table.pages[0], i),
            "name": meta.name,
            "description": meta.description,
            "source": format_source(state["source"], table.pages),
            "caption": table.caption,
            "unit": meta.unit,
            "period": meta.period,
            "column_descriptions": [
                f"{c.name}: {c.description} [{c.type}" + (f", {c.unit}]" if c.unit else "]")
                for c in meta.columns
            ],
            "row_headers": meta.row_headers,
        })
    return cards


def render() -> None:
    st.subheader("Subir PDF")
    st.caption("Solo PDFs con capa de texto. Las tablas en imagen se saltean y se informan.")
    files = st.file_uploader("PDFs", type="pdf", accept_multiple_files=True)
    if files and st.button("Ingerir", type="primary"):
        results = []
        for f in files:
            state = _ingest(f.name, f.getvalue())
            if state:
                results.append({"file": f.name, "cards": _summary(state), "skipped": state["skipped"]})
        st.session_state["ingest_results"] = results

    for res in st.session_state.get("ingest_results", []):
        st.markdown(f"#### {res['file']}")
        skipped_list(res["skipped"])
        for card in res["cards"]:
            table_card(card)
