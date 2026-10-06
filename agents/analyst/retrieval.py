"""Recuperación híbrida: búsqueda semántica (Pinecone) + BM25 sobre los metadatos, fusionadas con RRF.

Los embeddings captan paráfrasis ("ventas" ≈ "ingresos"), pero son flojos con términos exactos
como años, nombres de regiones o "I+D". BM25 premia esas coincidencias exactas. Reciprocal
Rank Fusion combina los dos rankings sin tener que calibrar sus puntajes:

    rrf(d) = Σ 1 / (k + rank_i(d))
"""
from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter

RRF_K = 60

_TOKEN_RE = re.compile(r"[a-z0-9]+(?:\+[a-z0-9]+)*")


def tokenize(text: str) -> list[str]:
    """Minúsculas, sin acentos; conserva términos como 'i+d'."""
    text = unicodedata.normalize("NFKD", text.casefold())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return _TOKEN_RE.findall(text)


def table_text(md: dict) -> str:
    """Texto de una tabla para BM25: los mismos campos que se usan para el embedding."""
    fields = [
        md.get("name"), md.get("caption"), md.get("description"), md.get("unit"),
        md.get("period"), " ".join(md.get("columns") or []),
        " ".join(md.get("column_descriptions") or []), " ".join(md.get("row_headers") or []),
    ]
    return " ".join(str(f) for f in fields if f)


def bm25_rank(query: str, docs: dict[str, str], k1: float = 1.5, b: float = 0.75) -> list[str]:
    """ids de ``docs`` ordenados por puntaje BM25 (solo los que tienen puntaje > 0)."""
    tokens = {doc_id: tokenize(text) for doc_id, text in docs.items()}
    if not tokens:
        return []
    n = len(tokens)
    avgdl = sum(len(t) for t in tokens.values()) / n or 1.0
    df = Counter(term for t in tokens.values() for term in set(t))
    q_terms = set(tokenize(query))
    scores = {}
    for doc_id, terms in tokens.items():
        tf = Counter(terms)
        score = 0.0
        for term in q_terms & tf.keys():
            idf = math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
            score += idf * tf[term] * (k1 + 1) / (tf[term] + k1 * (1 - b + b * len(terms) / avgdl))
        if score > 0:
            scores[doc_id] = score
    return sorted(scores, key=scores.get, reverse=True)


def rrf(rankings: list[list[str]], k: int = RRF_K) -> list[tuple[str, float]]:
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, doc_id in enumerate(ranking, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1 / (k + rank)
    return sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
