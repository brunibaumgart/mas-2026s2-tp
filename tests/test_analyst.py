from types import SimpleNamespace

import pandas as pd
import pytest

from agents.analyst import logic
from agents.analyst.graph import build_graph
from agents.analyst.nodes import AnalystDeps
from agents.analyst.schemas import (
    GeneratedCode,
    PartSelection,
    QueryPlan,
    QuestionPart,
    Selection,
    TableUse,
)
from tests.fakes import FakeEmbeddings, FakeIndex

EXP = pd.DataFrame({"Región": ["Capital", "Litoral"], "2022": [3610.2, 6402.7], "2023": [3755.8, 6118.4]})
POB = pd.DataFrame({"Región": ["Capital", "Litoral"], "2022": [4861.0, 2121.9], "2023": [4905.7, 2140.2]})


class ScriptedLLM:
    """LLM guionado: por cada schema, una lista de respuestas que se consumen en orden."""

    def __init__(self, responses: dict, answer: str = "Respuesta redactada."):
        self.responses = {k: list(v) for k, v in responses.items()}
        self.answer = answer
        self.calls: list[tuple[type | None, str]] = []

    def with_structured_output(self, schema):
        llm = self

        class _Structured:
            def invoke(self, messages):
                llm.calls.append((schema, messages[-1][1]))
                return llm.responses[schema].pop(0)

        return _Structured()

    def invoke(self, messages):
        self.calls.append((None, messages[-1][1]))
        return SimpleNamespace(content=self.answer)

    def prompts_for(self, schema):
        return [p for s, p in self.calls if s is schema]


def plan(*questions):
    return QueryPlan(
        rewritten_query="exportaciones población región",
        entities=[], metrics=[], periods=[], operations=[],
        parts=[QuestionPart(id=f"p{i}", question=q) for i, q in enumerate(questions, 1)],
    )


def part(pid, answerable, tables=(), missing=None, conversions=None):
    return PartSelection(
        part_id=pid, answerable=answerable, tables=list(tables),
        missing=missing, conversions=conversions,
    )


def use(table_id, columns, rows=()):
    return TableUse(table_id=table_id, columns=list(columns), row_labels=list(rows))


PER_CAPITA_CODE = """
import json
import pandas as pd
exp = pd.read_parquet('exp.parquet').set_index('Región')
pob = pd.read_parquet('pob.parquet').set_index('Región')
v = exp.loc['Litoral', '2023'] * 1e6 / (pob.loc['Litoral', '2023'] * 1e3)
print(json.dumps({"parts": [{"part_id": "p1", "result": round(float(v), 2),
                  "unit": "USD por habitante", "explanation": "exportaciones / población"}]}))
"""


@pytest.fixture
def deps(tmp_path):
    tables_dir = tmp_path / "tables"
    tables_dir.mkdir()
    index = FakeIndex()
    for tid, df, name in (("exp", EXP, "Exportaciones"), ("pob", POB, "Población")):
        df.to_parquet(tables_dir / f"{tid}.parquet", index=False)
        md = {"table_id": tid, "name": name, "source": "anuario.pdf, p. 1",
              "period": "2022–2023", "columns": list(df.columns)}
        index.upsert([{"id": tid, "values": [1.0, 0.0, 0.0], "metadata": md}])

    def make(llm, max_code_attempts=3):
        return AnalystDeps(
            llm=llm, embeddings=FakeEmbeddings(), index=index, tables_dir=tables_dir,
            max_code_attempts=max_code_attempts, timeout=20,
        )

    return make


def run(deps_factory, llm, **kw):
    return build_graph(deps_factory(llm, **kw)).invoke({"question": "pregunta de prueba"})


# ------------------------------------------------------------------ lógica pura
@pytest.mark.parametrize(
    "answerable, expected",
    [([True], "answered"), ([True, False], "partial"), ([False], "cannot_answer"), ([], "cannot_answer")],
)
def test_compute_status(answerable, expected):
    assert logic.compute_status(answerable) == expected


def test_check_selection_columna_inexistente_no_es_respondible():
    sel = Selection(parts=[part("p1", True, [use("exp", ["Región", "2020"], ["Montaña"])])])
    [checked] = logic.check_selection(
        plan("¿x?").parts, sel, {"exp": {"name": "Exportaciones"}}, lambda _: EXP
    )
    assert not checked.answerable
    assert "['2020']" in checked.missing and "['Montaña']" in checked.missing


def test_check_selection_corrige_etiquetas_aproximadas():
    sel = Selection(parts=[part("p1", True, [use("exp", ["2023"], ["litoral"])])])
    [checked] = logic.check_selection(
        plan("¿x?").parts, sel, {"exp": {"name": "Exportaciones"}}, lambda _: EXP
    )
    assert checked.answerable
    assert checked.tables[0].row_labels == ["Litoral"]


def test_check_selection_tabla_no_candidata_y_parte_sin_evaluar():
    sel = Selection(parts=[part("p1", True, [use("otra", ["2023"])])])
    checked = logic.check_selection(plan("¿a?", "¿b?").parts, sel, {}, lambda _: EXP)
    assert [c.answerable for c in checked] == [False, False]
    assert "no está entre las candidatas" in checked[0].missing
    assert "no evaluó" in checked[1].missing


def test_parse_y_validate_output():
    out = logic.parse_output('debug\n{"parts": [{"part_id": "p1", "result": 1.5}]}\n')
    assert out == {"parts": [{"part_id": "p1", "result": 1.5}]}
    assert logic.validate_output(out, ["p1"]) == []
    assert logic.parse_output("sin json") is None
    assert "no es un JSON" in logic.validate_output(None, ["p1"])[0]
    assert "Falta la parte 'p2'" in logic.validate_output(out, ["p1", "p2"])[0]
    nan = logic.parse_output('{"parts": [{"part_id": "p1", "result": NaN}]}')
    assert "NaN" in logic.validate_output(nan, ["p1"])[0]


def test_apply_output_baja_las_partes_con_dato_faltante():
    sel = [part("p1", True, [use("exp", ["2023"])]), part("p2", True, [use("exp", ["2023"])])]
    out = {"parts": [{"part_id": "p1", "result": 2.0}, {"part_id": "p2", "result": None, "missing": "no hay 2024"}]}
    updated = logic.apply_output(sel, out)
    assert [s.answerable for s in updated] == [True, False]
    assert updated[1].missing == "no hay 2024"


# ------------------------------------------------------------------ grafo
def test_multitabla_answered(deps):
    llm = ScriptedLLM({
        QueryPlan: [plan("¿Exportaciones per cápita de Litoral en 2023?")],
        Selection: [Selection(parts=[part(
            "p1", True,
            [use("exp", ["Región", "2023"], ["Litoral"]), use("pob", ["Región", "2023"], ["Litoral"])],
            conversions="millones de USD / miles de habitantes",
        )])],
        GeneratedCode: [GeneratedCode(code=PER_CAPITA_CODE)],
    })
    state = run(deps, llm)
    assert state["status"] == "answered"
    assert state["code_attempts"] == 1
    assert state["result"]["parts"][0]["result"] == 2858.8
    assert [t["table_id"] for t in state["selected_tables"]] == ["exp", "pob"]
    assert state["missing_data"] == []
    codegen_prompt = llm.prompts_for(GeneratedCode)[0]
    assert "exp.parquet" in codegen_prompt and "'2023': 'float64'" not in codegen_prompt
    assert '"2023": "float64"' in codegen_prompt


def test_cannot_answer_no_genera_codigo(deps):
    llm = ScriptedLLM({
        QueryPlan: [plan("¿Exportaciones de Litoral en pesos?")],
        Selection: [Selection(parts=[part("p1", False, missing="Requiere tipo de cambio.")])],
    })
    state = run(deps, llm)
    assert state["status"] == "cannot_answer"
    assert state["code"] is None
    assert llm.prompts_for(GeneratedCode) == []
    assert state["missing_data"] == ["¿Exportaciones de Litoral en pesos?: Requiere tipo de cambio."]
    assert "Tablas relacionadas" in llm.prompts_for(None)[0]


def test_seleccion_con_anio_inexistente_se_corrige_a_cannot_answer(deps):
    llm = ScriptedLLM({
        QueryPlan: [plan("¿Exportaciones de Capital en 2020?")],
        Selection: [Selection(parts=[part("p1", True, [use("exp", ["2020"], ["Capital"])])])],
    })
    state = run(deps, llm)
    assert state["status"] == "cannot_answer"
    assert "['2020']" in state["missing_data"][0]
    assert llm.prompts_for(GeneratedCode) == []


def test_partial(deps):
    code = PER_CAPITA_CODE
    llm = ScriptedLLM({
        QueryPlan: [plan("¿Per cápita Litoral 2023?", "¿Comparado con el promedio nacional?")],
        Selection: [Selection(parts=[
            part("p1", True, [use("exp", ["2023"], ["Litoral"]), use("pob", ["2023"], ["Litoral"])]),
            part("p2", False, missing="No hay promedio nacional."),
        ])],
        GeneratedCode: [GeneratedCode(code=code)],
    })
    state = run(deps, llm)
    assert state["status"] == "partial"
    assert len(state["missing_data"]) == 1
    prompt = llm.prompts_for(GeneratedCode)[0]
    calcular, no_calcular = prompt.split("Partes NO respondibles")
    assert "- p1:" in calcular and "- p2:" not in calcular
    assert "promedio nacional" in no_calcular.split("Tablas:")[0]


def test_autocorreccion_con_el_error(deps):
    llm = ScriptedLLM({
        QueryPlan: [plan("¿Per cápita Litoral 2023?")],
        Selection: [Selection(parts=[part("p1", True, [use("exp", ["2023"]), use("pob", ["2023"])])])],
        GeneratedCode: [GeneratedCode(code="raise ValueError('boom')"), GeneratedCode(code=PER_CAPITA_CODE)],
    })
    state = run(deps, llm)
    assert state["status"] == "answered"
    assert state["code_attempts"] == 2
    retry_prompt = llm.prompts_for(GeneratedCode)[1]
    assert "Código anterior" in retry_prompt and "ValueError: boom" in retry_prompt


def test_salida_sin_json_se_reintenta(deps):
    llm = ScriptedLLM({
        QueryPlan: [plan("¿x?")],
        Selection: [Selection(parts=[part("p1", True, [use("exp", ["2023"]), use("pob", ["2023"])])])],
        GeneratedCode: [GeneratedCode(code="print(42)"), GeneratedCode(code=PER_CAPITA_CODE)],
    })
    state = run(deps, llm)
    assert state["code_attempts"] == 2
    assert "no es un JSON" in llm.prompts_for(GeneratedCode)[1]


def test_reintentos_agotados(deps):
    llm = ScriptedLLM({
        QueryPlan: [plan("¿x?")],
        Selection: [Selection(parts=[part("p1", True, [use("exp", ["2023"])])])],
        GeneratedCode: [GeneratedCode(code="1/0"), GeneratedCode(code="1/0")],
    })
    state = run(deps, llm, max_code_attempts=2)
    assert state["code_attempts"] == 2
    assert state["status"] == "cannot_answer"
    assert "ZeroDivisionError" in state["error"]
    assert "falló tras 2 intentos" in state["missing_data"][0]


def test_codigo_informa_dato_faltante(deps):
    code = 'import json\nprint(json.dumps({"parts": [{"part_id": "p1", "result": None, "missing": "no hay 2024"}]}))'
    llm = ScriptedLLM({
        QueryPlan: [plan("¿x?")],
        Selection: [Selection(parts=[part("p1", True, [use("exp", ["2023"])])])],
        GeneratedCode: [GeneratedCode(code=code)],
    })
    state = run(deps, llm)
    assert state["status"] == "cannot_answer"
    assert state["missing_data"] == ["¿x?: no hay 2024"]
