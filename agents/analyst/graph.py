"""Grafo del Analista:

understand → retrieve → select ─┬─(cannot_answer)──────────────────────────┐
                                └→ codegen → execute ─┬→ answer ←───────────┘
                                      ↑               │
                                      └── reintento ──┘ (con el error)
"""
from __future__ import annotations

from functools import partial

from langgraph.graph import END, START, StateGraph

from agents.analyst import nodes
from agents.analyst.nodes import AnalystDeps
from agents.analyst.state import AnalystState


def build_graph(deps: AnalystDeps):
    g = StateGraph(AnalystState)
    g.add_node("understand", partial(nodes.understand, deps=deps))
    g.add_node("retrieve", partial(nodes.retrieve, deps=deps))
    g.add_node("select", partial(nodes.select, deps=deps))
    g.add_node("codegen", partial(nodes.codegen, deps=deps))
    g.add_node("execute", partial(nodes.execute, deps=deps))
    g.add_node("answer", partial(nodes.answer, deps=deps))

    g.add_edge(START, "understand")
    g.add_edge("understand", "retrieve")
    g.add_edge("retrieve", "select")
    g.add_conditional_edges(
        "select", nodes.route_after_select, {"codegen": "codegen", "answer": "answer"}
    )
    g.add_edge("codegen", "execute")
    g.add_conditional_edges(
        "execute",
        partial(nodes.route_after_execute, max_attempts=deps.max_code_attempts),
        {"codegen": "codegen", "answer": "answer"},
    )
    g.add_edge("answer", END)
    return g.compile()


def default_deps() -> AnalystDeps:
    from services.llm import get_chat_model, get_embeddings
    from services.vector_store import get_index

    return AnalystDeps(llm=get_chat_model(), embeddings=get_embeddings(), index=get_index())


def run_config(question: str) -> dict:
    """Nombre, tags y metadatos de la traza en LangSmith."""
    short = question if len(question) <= 60 else question[:57] + "..."
    return {"run_name": f"analista: {short}", "tags": ["analyst"], "metadata": {"question": question}}


def ask(question: str, deps: AnalystDeps | None = None) -> AnalystState:
    graph = build_graph(deps or default_deps())
    return graph.invoke({"question": question}, config=run_config(question))
