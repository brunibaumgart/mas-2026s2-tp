"""Punto de entrada de la UI (Streamlit). Uso: streamlit run app.py"""
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from ui import ask_tab, explore_tab, ingest_tab  # noqa: E402
from ui.resources import get_resources  # noqa: E402

st.set_page_config(page_title="Analista de tablas en PDF", layout="wide")
st.title("Analista de tablas en PDF")

try:
    get_resources()
except Exception as exc:  # noqa: BLE001
    st.error(
        f"No se pudo inicializar el sistema ({type(exc).__name__}: {exc}). "
        "Revisá el archivo .env (ver .env.example)."
    )
    st.stop()

subir, explorar, preguntar = st.tabs(["Subir PDF", "Explorar tablas", "Preguntar"])
with subir:
    ingest_tab.render()
with explorar:
    explore_tab.render()
with preguntar:
    ask_tab.render()
