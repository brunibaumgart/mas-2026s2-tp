"""Smoke test de la UI con Streamlit AppTest y dobles (sin proxy ni Pinecone)."""
from pathlib import Path
from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest

import ui.ask_tab
import ui.explore_tab
import ui.ingest_tab
import ui.resources
from agents.analyst.graph import build_graph, memory_checkpointer
from agents.analyst.schemas import GeneratedCode, QueryPlan, Selection
from tests.test_analyst import PER_CAPITA_CODE, ScriptedLLM, deps, plan  # noqa: F401
from tests.test_analyst_distintivos import CHART_CODE, PER_CAPITA_SEL

APP = Path(__file__).resolve().parent.parent / "app.py"


@pytest.fixture
def app(deps, monkeypatch):
    def make(llm):
        d = deps(llm)
        res = SimpleNamespace(index=d.index, ingestion=None,
                              analyst=build_graph(d, checkpointer=memory_checkpointer()))
        for module in (ui.resources, ui.ask_tab, ui.explore_tab, ui.ingest_tab):
            monkeypatch.setattr(module, "get_resources", lambda: res)
        return AppTest.from_file(str(APP), default_timeout=60).run()

    return make


def _llm(n=1, code=PER_CAPITA_CODE):
    return ScriptedLLM({
        QueryPlan: [plan("¿Per cápita Litoral 2023?") for _ in range(n)],
        Selection: [PER_CAPITA_SEL for _ in range(n)],
        GeneratedCode: [GeneratedCode(code=code) for _ in range(n)],
    }, answer="Litoral: 2.858,8 USD por habitante.")


def test_pregunta_de_punta_a_punta(app):
    at = app(_llm(code=CHART_CODE))
    assert not at.exception
    at.chat_input[0].set_value("¿Per cápita Litoral 2023?").run()
    assert not at.exception
    assert any("answered" in s.value for s in at.success)
    assert any("2.858,8" in m.value for m in at.markdown)
    assert any("celdas citadas verificadas: 2/2" in c.value for c in at.caption)
    assert at.session_state.chat[0]["state"]["chart"].startswith(b"\x89PNG")


def test_revision_humana_en_la_ui(app):
    at = app(_llm())
    at.toggle[0].set_value(True).run()
    at.chat_input[0].set_value("¿Per cápita Litoral 2023?").run()
    assert not at.exception
    assert any("Revisá las tablas" in i.value for i in at.info)
    assert at.chat_input[0].disabled
    [submit] = [b for b in at.button if b.label == "Calcular con estas tablas"]
    submit.click().run()
    assert not at.exception
    assert any("answered" in s.value for s in at.success)
    assert any("revisión humana: approve" in c.value for c in at.caption)
