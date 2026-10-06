"""Recursos compartidos por las pestañas (clientes y grafos), creados una sola vez."""
from dataclasses import dataclass

import streamlit as st

from agents.analyst.graph import build_graph as build_analyst
from agents.analyst.nodes import AnalystDeps
from agents.ingestion.graph import build_graph as build_ingestion
from agents.ingestion.nodes import IngestionDeps
from services.llm import get_chat_model, get_embeddings
from services.vector_store import get_index


@dataclass
class Resources:
    index: object
    ingestion: object
    analyst: object


@st.cache_resource(show_spinner="Conectando con el proxy y Pinecone...")
def get_resources() -> Resources:
    llm, embeddings, index = get_chat_model(), get_embeddings(), get_index()
    return Resources(
        index=index,
        ingestion=build_ingestion(IngestionDeps(llm=llm, embeddings=embeddings, index=index)),
        analyst=build_analyst(AnalystDeps(llm=llm, embeddings=embeddings, index=index)),
    )
