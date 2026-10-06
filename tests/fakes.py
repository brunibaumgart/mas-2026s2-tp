"""Dobles de prueba para el LLM, los embeddings y el índice de Pinecone."""
import json
import re
from collections import defaultdict
from types import SimpleNamespace

from langchain_core.embeddings import Embeddings

from agents.ingestion.schemas import ColumnMetadata, TableMetadata

COLUMNS_RE = re.compile(r"^Columnas \(\d+\): (\[.*\])$", re.M)
CAPTION_RE = re.compile(r"^Rótulo: (Cuadro \d+(?:\.\d+)*)", re.M)


def good_metadata(columns: list[str], row_headers: list[str] | None = None) -> TableMetadata:
    return TableMetadata(
        name="Tabla de prueba",
        description="Descripción de prueba. Segunda oración.",
        unit=None,
        period="2020–2024",
        columns=[
            ColumnMetadata(name=c, description=f"col {c}", type="numero", unit=None)
            for c in columns
        ],
        row_headers=row_headers or [],
    )


class FakeLLM:
    """``answer(caption, columns, attempt)`` devuelve TableMetadata o lanza una excepción."""

    def __init__(self, answer=None):
        self.answer = answer or (lambda caption, columns, attempt: good_metadata(columns))
        self.prompts: list[str] = []
        self._attempts = defaultdict(int)

    def with_structured_output(self, schema):
        assert schema is TableMetadata
        return self

    def batch(self, inputs, return_exceptions=False):
        out = []
        for messages in inputs:
            human = messages[-1][1]
            self.prompts.append(human)
            caption = CAPTION_RE.search(human)[1]
            columns = json.loads(COLUMNS_RE.search(human)[1])
            self._attempts[caption] += 1
            try:
                out.append(self.answer(caption, columns, self._attempts[caption]))
            except Exception as exc:  # noqa: BLE001
                if not return_exceptions:
                    raise
                out.append(exc)
        return out


class FakeEmbeddings(Embeddings):
    def embed_documents(self, texts):
        return [[float(len(t)), 1.0, 0.0] for t in texts]

    def embed_query(self, text):
        return self.embed_documents([text])[0]


def _matches(metadata: dict, flt: dict | None) -> bool:
    if not flt:
        return True
    return all(metadata.get(k) == cond["$eq"] for k, cond in flt.items())


class FakeIndex:
    """Imita la parte del cliente de Pinecone que usa el proyecto."""

    def __init__(self):
        self.vectors: dict[str, dict] = {}
        self.queries: list[dict] = []

    def upsert(self, vectors):
        for v in vectors:
            self.vectors[v["id"]] = v

    def delete(self, ids):
        for i in ids:
            self.vectors.pop(i, None)

    def query(self, vector, top_k, filter=None, include_metadata=False):
        self.queries.append({"vector": vector, "top_k": top_k, "filter": filter})
        matches = [
            SimpleNamespace(id=k, score=1.0, metadata=v["metadata"])
            for k, v in self.vectors.items()
            if _matches(v["metadata"], filter)
        ]
        return SimpleNamespace(matches=matches[:top_k])

    def list(self):
        yield list(self.vectors)

    def fetch(self, ids):
        return SimpleNamespace(
            vectors={
                i: SimpleNamespace(id=i, metadata=self.vectors[i]["metadata"])
                for i in ids
                if i in self.vectors
            }
        )

    def describe_index_stats(self):
        return SimpleNamespace(total_vector_count=len(self.vectors))
