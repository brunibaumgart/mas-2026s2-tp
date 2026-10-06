"""Tests de los distintivos del Analista: citas, verificador, híbrido, memoria, revisión humana,
gráfico y ruteo de modelos. Todos con dobles: no gastan presupuesto del proxy."""
from langgraph.types import Command

from agents.analyst import logic, retrieval
from agents.analyst.graph import build_graph, memory_checkpointer, run_config
from agents.analyst.schemas import GeneratedCode, QueryPlan, Selection, Verdict, Violation
from services.sandbox import run_code
from tests.test_analyst import EXP, PER_CAPITA_CODE, POB, ScriptedLLM, deps, part, plan, run, use  # noqa: F401

PER_CAPITA_SEL = Selection(parts=[part(
    "p1", True, [use("exp", ["Región", "2023"], ["Litoral"]), use("pob", ["Región", "2023"], ["Litoral"])],
)])

NO_CELLS_CODE = PER_CAPITA_CODE.replace('"cells": cells', '"cells": []')
WRONG_CELL_CODE = PER_CAPITA_CODE.replace(
    "\"value\": float(exp.loc['Litoral', '2023'])", '"value": 9999.0'
)


def scripted(*codes, verdicts=(), selection=PER_CAPITA_SEL, questions=("¿Per cápita Litoral 2023?",)):
    responses = {
        QueryPlan: [plan(*questions)],
        Selection: [selection],
        GeneratedCode: [GeneratedCode(code=c) for c in codes],
    }
    if verdicts:
        responses[Verdict] = list(verdicts)
    return ScriptedLLM(responses)


# ------------------------------------------------------------------ citas a nivel de celda
def test_check_citation_valida_fila_columna_y_valor():
    tables = {"exp.parquet": EXP}
    ok = {"table": "exp.parquet", "row": "Litoral", "column": "2023", "value": 6118.4}
    assert logic.check_citation(ok, tables) is None
    assert logic.check_citation(ok | {"value": 6118.401}, tables) is None  # redondeo
    assert "el valor es 6118.4" in logic.check_citation(ok | {"value": 6000}, tables)
    assert "no tiene ninguna fila" in logic.check_citation(ok | {"row": "Montaña"}, tables)
    assert "no tiene la columna" in logic.check_citation(ok | {"column": "2020"}, tables)
    assert "no es ninguno de los archivos" in logic.check_citation(ok | {"table": "otra"}, tables)


def test_check_citation_fila_con_varias_etiquetas_y_ambigua():
    import pandas as pd

    ventas = pd.DataFrame({"Año": ["2023", "2024"], "Mes": ["Diciembre", "Diciembre"], "Sur": [2515.0, 2978.0]})
    tables = {"v.parquet": ventas}
    cell = {"table": "v.parquet", "row": ["2024", "Diciembre"], "column": "Sur", "value": 2978}
    assert logic.check_citation(cell, tables) is None
    assert "ambigua" in logic.check_citation(cell | {"row": "Diciembre"}, tables)


def test_citas_correctas_quedan_en_el_estado(deps):
    state = run(deps, scripted(PER_CAPITA_CODE))
    assert state["status"] == "answered"
    assert [c["ok"] for c in state["citations"]] == [True, True]


def test_cita_con_valor_inventado_se_reintenta(deps):
    llm = scripted(WRONG_CELL_CODE, PER_CAPITA_CODE)
    state = run(deps, llm)
    assert state["code_attempts"] == 2 and state["status"] == "answered"
    assert "Cita inválida" in llm.prompts_for(GeneratedCode)[1]


def test_resultado_sin_celdas_se_reintenta(deps):
    llm = scripted(NO_CELLS_CODE, PER_CAPITA_CODE)
    state = run(deps, llm)
    assert state["code_attempts"] == 2
    assert "no tiene 'cells'" in llm.prompts_for(GeneratedCode)[1]


# ------------------------------------------------------------------ verificador
def test_verificador_rechaza_el_calculo_y_se_reescribe(deps):
    bad = Verdict(ok=False, violations=[Violation(
        part_id="p1", kind="calculo", detail="Promedia las regiones para el promedio nacional.")])
    llm = scripted(PER_CAPITA_CODE, PER_CAPITA_CODE, verdicts=[bad, Verdict(ok=True, violations=[])])
    state = run(deps, llm)
    assert state["code_attempts"] == 2
    assert state["status"] == "answered" and state["verdict"].ok
    assert "El verificador rechazó el cálculo" in llm.prompts_for(GeneratedCode)[1]
    assert len(llm.prompts_for(Verdict)) == 2


def test_verificador_dato_faltante_baja_el_estado_sin_reintentar(deps):
    sel = Selection(parts=[PER_CAPITA_SEL.parts[0], part("p2", True, [use("exp", ["2023"])])])
    missing = Verdict(ok=False, violations=[Violation(
        part_id="p2", kind="dato_faltante", detail="No hay promedio nacional en las tablas.")])
    code = PER_CAPITA_CODE.replace(
        '"cells": cells}]}', '"cells": cells}, {"part_id": "p2", "result": 1.0, "cells": cells}]}'
    )
    llm = scripted(code, verdicts=[missing], selection=sel, questions=("¿a?", "¿b?"))
    state = run(deps, llm)
    assert state["code_attempts"] == 1
    assert state["status"] == "partial"
    assert "No hay promedio nacional" in state["missing_data"][0]


def test_verificador_sin_intentos_marca_la_parte(deps):
    bad = Verdict(ok=False, violations=[Violation(part_id="p1", kind="calculo", detail="Usa 2022.")])
    llm = scripted(PER_CAPITA_CODE, verdicts=[bad])
    state = run(deps, llm, max_code_attempts=1)
    assert state["status"] == "cannot_answer"
    assert "verificador rechazó" in state["missing_data"][0]


def test_el_verificador_ve_el_codigo_y_las_partes_no_respondibles(deps):
    sel = Selection(parts=[PER_CAPITA_SEL.parts[0], part("p2", False, missing="No hay promedio nacional.")])
    llm = scripted(PER_CAPITA_CODE, selection=sel, questions=("¿a?", "¿b?"))
    run(deps, llm)
    prompt = llm.prompts_for(Verdict)[0]
    assert "Código ejecutado" in prompt and "exp.loc['Litoral', '2023']" in prompt
    assert "Partes NO respondibles" in prompt and "No hay promedio nacional" in prompt
    assert '"cells"' not in prompt.split("Resultado (JSON")[1]


# ------------------------------------------------------------------ retrieval híbrido
def test_tokenize_y_bm25():
    assert retrieval.tokenize("Gasto en I+D, Región Montaña 2023") == ["gasto", "en", "i+d", "region", "montana", "2023"]
    docs = {"a": "exportaciones por región 2021 2022 2023", "b": "gastos en I+D por año", "c": "población"}
    assert retrieval.bm25_rank("¿Cuánto fue el I+D?", docs)[0] == "b"
    assert retrieval.bm25_rank("nada que ver", docs) == []


def test_rrf_premia_lo_que_aparece_arriba_en_ambos():
    fused = retrieval.rrf([["a", "b", "c"], ["b", "c", "a"]])
    assert [d for d, _ in fused][0] == "b"


def test_retrieve_hibrido_registra_los_tres_rankings(deps):
    state = run(deps, scripted(PER_CAPITA_CODE))
    r = state["retrieval"]
    assert set(r) == {"dense", "bm25", "fused"}
    assert set(r["fused"]) <= {"exp", "pob"}


# ------------------------------------------------------------------ ruteo de modelos
def test_modelo_rapido_para_interpretar_y_redactar(deps):
    strong = scripted(PER_CAPITA_CODE)
    fast = ScriptedLLM({QueryPlan: [plan("¿Per cápita Litoral 2023?")]})
    d = deps(strong)
    d.llm_fast = fast
    build_graph(d).invoke({"question": "¿x?"})
    assert [s for s, _ in fast.calls] == [QueryPlan, None]  # understand y answer
    assert {s for s, _ in strong.calls} == {Selection, GeneratedCode, Verdict}


# ------------------------------------------------------------------ memoria del hilo
def test_memoria_del_hilo_con_checkpointer(deps):
    llm = ScriptedLLM({
        QueryPlan: [plan("¿Per cápita Litoral 2023?"), plan("¿Per cápita Litoral 2022?")],
        Selection: [PER_CAPITA_SEL, PER_CAPITA_SEL],
        GeneratedCode: [GeneratedCode(code=PER_CAPITA_CODE), GeneratedCode(code=PER_CAPITA_CODE)],
    })
    graph = build_graph(deps(llm), checkpointer=memory_checkpointer())
    config = run_config("¿?", thread_id="hilo-1")
    graph.invoke({"question": "¿Per cápita Litoral 2023?"}, config=config)
    state = graph.invoke({"question": "¿y en 2022?"}, config=config)

    second = llm.prompts_for(QueryPlan)[1]
    assert "Conversación previa" in second and "¿Per cápita Litoral 2023?" in second
    assert second.endswith("Pregunta nueva: ¿y en 2022?")
    assert [t["question"] for t in state["history"]] == ["¿Per cápita Litoral 2023?", "¿y en 2022?"]
    assert state["history"][1]["standalone"] == "¿Per cápita Litoral 2022?"
    assert state["code_attempts"] == 1  # los campos de la pregunta anterior se reiniciaron


def test_sin_checkpointer_no_hay_memoria(deps):
    llm = scripted(PER_CAPITA_CODE)
    state = run(deps, llm)
    assert "Conversación previa" not in llm.prompts_for(QueryPlan)[0]
    assert len(state["history"]) == 1


# ------------------------------------------------------------------ revisión humana
def _review_graph(deps, llm):
    return build_graph(deps(llm), checkpointer=memory_checkpointer())


def test_revision_humana_pausa_y_aprueba(deps):
    llm = scripted(PER_CAPITA_CODE)
    graph = _review_graph(deps, llm)
    config = run_config("¿?", thread_id="r1")
    first = graph.invoke({"question": "¿x?", "human_review": True}, config=config)
    [pending] = first["__interrupt__"]
    assert pending.value["parts"][0]["tables"] == ["exp", "pob"]
    assert llm.prompts_for(GeneratedCode) == []  # todavía no generó código

    state = graph.invoke(Command(resume={"action": "approve"}), config=config)
    assert state["status"] == "answered" and state["review"] == {"action": "approve"}


def test_revision_humana_descarta_tablas(deps):
    llm = scripted(PER_CAPITA_CODE)
    graph = _review_graph(deps, llm)
    config = run_config("¿?", thread_id="r2")
    graph.invoke({"question": "¿x?", "human_review": True}, config=config)
    state = graph.invoke(Command(resume={"action": "edit", "tables": {"p1": []}}), config=config)
    assert state["status"] == "cannot_answer"
    assert "descartó" in state["missing_data"][0]
    assert llm.prompts_for(GeneratedCode) == []


def test_apply_review_agrega_una_tabla_y_cancela():
    sel = [part("p1", True, [use("exp", ["2023"], ["Litoral"])])]
    [edited] = logic.apply_review(sel, {"action": "edit", "tables": {"p1": ["exp", "pob"]}})
    assert [u.table_id for u in edited.tables] == ["exp", "pob"]
    assert edited.tables[0].row_labels == ["Litoral"] and edited.tables[1].columns == []
    [cancelled] = logic.apply_review(sel, {"action": "cancel"})
    assert not cancelled.answerable


# ------------------------------------------------------------------ gráfico
CHART_CODE = PER_CAPITA_CODE + """
import matplotlib.pyplot as plt
plt.bar(['Litoral'], [v]); plt.title('Exportaciones per cápita (USD por habitante)')
plt.savefig('chart.png', dpi=80, bbox_inches='tight')
"""


def test_grafico_generado_en_el_sandbox():
    res = run_code("import matplotlib.pyplot as plt\nplt.plot([1, 2]); plt.savefig('chart.png')")
    assert res.ok and res.chart.startswith(b"\x89PNG")
    assert run_code("print(1)").chart is None


def test_grafico_llega_al_estado(deps):
    state = run(deps, scripted(CHART_CODE))
    assert state["status"] == "answered"
    assert state["chart"].startswith(b"\x89PNG")
