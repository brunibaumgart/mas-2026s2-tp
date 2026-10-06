"""Acceso al índice de Pinecone configurado en .env."""
import os

from dotenv import load_dotenv
from pinecone import Pinecone


def get_index():
    load_dotenv()
    pc = Pinecone(api_key=os.environ["PINECONE_API_KEY"])
    return pc.Index(os.environ["PINECONE_INDEX_NAME"])


def list_tables(index) -> list[dict]:
    """Metadatos de todas las tablas indexadas, ordenados por archivo y página."""
    ids = [i for batch in index.list() for i in batch]
    tables = []
    for start in range(0, len(ids), 100):
        fetched = index.fetch(ids=ids[start:start + 100]).vectors
        tables += [dict(v.metadata or {}, table_id=k) for k, v in fetched.items()]
    return sorted(tables, key=lambda t: (t.get("file", ""), t.get("page_start", 0)))
