"""Componentes de presentación reutilizados por varias pestañas."""
import io

import pandas as pd
import streamlit as st

from services.table_store import load_table


def table_data(md: dict) -> pd.DataFrame:
    """Datos completos desde el parquet; si no está, la vista previa guardada en Pinecone."""
    try:
        return load_table(md["table_id"])
    except (FileNotFoundError, OSError):
        return pd.read_csv(io.StringIO(md.get("preview", ""))) if md.get("preview") else pd.DataFrame()


def table_card(md: dict, expanded: bool = False) -> None:
    title = f"{md.get('name', md['table_id'])} — {md.get('source', '')}"
    with st.expander(title, expanded=expanded):
        st.write(md.get("description", ""))
        cols = st.columns(3)
        cols[0].caption(f"Rótulo: {md.get('caption') or '—'}")
        cols[1].caption(f"Unidad: {md.get('unit') or '—'}")
        cols[2].caption(f"Período: {md.get('period') or '—'}")
        if md.get("column_descriptions"):
            st.markdown("**Columnas**")
            st.markdown("\n".join(f"- {c}" for c in md["column_descriptions"]))
        if md.get("row_headers"):
            st.markdown("**Encabezados de fila:** " + ", ".join(md["row_headers"]))
        st.dataframe(table_data(md), hide_index=True, width="stretch")
        st.caption(f"table_id: `{md['table_id']}`")


def skipped_list(skipped) -> None:
    for s in skipped:
        st.warning(f"Salteada: **{s.caption}** (pág. {s.page}) — {s.reason}")
