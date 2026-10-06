"""Grafo del Analista:

understand → retrieve → select ─┬─(cannot_answer)──────────────────────────────────┐
                                ├─(human_review)→ review ─┬─(cannot_answer)────────┤
                                │                         ↓                        │
                                └───────────────────→ codegen → execute ─→ verify ─┴→ answer
                                                         ↑         │          │
                                                         └─────────┴──────────┘
                                          reintento con el error de ejecución, de las citas
                                          o del verificador (comparten el límite de intentos)

Con un checkpointer, el estado persiste por ``thread_id``: eso habilita la memoria de la
conversación (``history``) y la pausa de ``review`` (``interrupt``).
"""
from __future__ import annotations

from functools import partial

from langgraph.graph import END, START, StateGraph

from agents.analyst import nodes
from agents.analyst.nodes import AnalystDeps
from agents.analyst.state import AnalystState


def build_graph(deps: AnalystDeps, checkpointer=None):
    g = StateGraph(AnalystState)
    for name in ("understand", "retrieve", "select", "review", "codegen", "execute", "verify", "answer"):
        g.add_node(name, partial(getattr(nodes, name), deps=deps))

    g.add_edge(START, "understand")
    g.add_edge("understand", "retrieve")
    g.add_edge("retrieve", "select")
    g.add_conditional_edges(
        "select", nodes.route_after_select,
        {"codegen": "codegen", "review": "review", "answer": "answer"},
    )
    g.add_conditional_edges(
        "review", nodes.route_after_review, {"codegen": "codegen", "answer": "answer"}
    )
    g.add_edge("codegen", "execute")
    g.add_conditional_edges(
        "execute",
        partial(nodes.route_after_execute, max_attempts=deps.max_code_attempts, verify=deps.verify),
        {"codegen": "codegen", "verify": "verify", "answer": "answer"},
    )
    g.add_conditional_edges(
        "verify",
        partial(nodes.route_after_verify, max_attempts=deps.max_code_attempts),
        {"codegen": "codegen", "answer": "answer"},
    )
    g.add_edge("answer", END)
    return g.compile(checkpointer=checkpointer)


def default_deps() -> AnalystDeps:
    from services.llm import get_chat_model, get_embeddings, get_fast_chat_model
    from services.vector_store import get_index

    return AnalystDeps(
        llm=get_chat_model(), llm_fast=get_fast_chat_model(),
        embeddings=get_embeddings(), index=get_index(),
    )


def run_config(question: str, thread_id: str | None = None) -> dict:
    """Nombre, tags y metadatos de la traza en LangSmith (y el hilo, si hay memoria)."""
    short = question if len(question) <= 60 else question[:57] + "..."
    config = {"run_name": f"analista: {short}", "tags": ["analyst"], "metadata": {"question": question}}
    if thread_id:
        config["configurable"] = {"thread_id": thread_id}
        config["metadata"]["thread_id"] = thread_id
    return config


def ask(question: str, deps: AnalystDeps | None = None) -> AnalystState:
    """Una pregunta suelta, sin memoria ni revisión humana (CLI y evaluación)."""
    graph = build_graph(deps or default_deps())
    return graph.invoke({"question": question}, config=run_config(question))
