"""Métricas de evaluación por etapa y armado del informe (sin llamadas reales)."""
import sys
from pathlib import Path

from evaluation.cases import CASES, A, M
from evaluation.metrics import retrieval_hit, score, selection_ok, values_ok

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import langsmith_eval  # noqa: E402
import run_eval  # noqa: E402

BY_ID = {c.id: c for c in CASES}


def md(file, caption, name="t"):
    return {"file": file, "caption": caption, "name": name}


def test_los_casos_coinciden_con_preguntas_prueba():
    assert [c.id for c in CASES] == list(range(1, 12))
    assert sum(c.status == "cannot_answer" for c in CASES) == 4
    assert sum(len(c.tables) > 1 for c in CASES if c.status != "cannot_answer") >= 2  # multitabla


def test_recuperacion_y_seleccion():
    c3 = BY_ID[3]
    cands = [md(M, "Cuadro 1"), md(M, "Cuadro 2"), md(A, "Cuadro 1.1")]
    assert retrieval_hit(c3, cands) is True
    assert retrieval_hit(c3, cands[:1]) is False
    assert retrieval_hit(BY_ID[10], cands) is None  # no relacionada: no espera tablas
    assert selection_ok(c3, cands[:2]) is True
    assert selection_ok(c3, cands) is False  # usó una de más
    assert selection_ok(BY_ID[9], []) is True and selection_ok(BY_ID[9], cands[:1]) is False


def test_valores():
    assert values_ok(BY_ID[2], {"parts": [{"result": [0.2175, 0.2226, 0.2425, 0.2718, 0.2909]}]})
    assert values_ok(BY_ID[5], {"parts": [{"result": {"mes": "Diciembre", "ventas": 12033}}]})
    assert not values_ok(BY_ID[5], {"parts": [{"result": {"mes": "Noviembre", "ventas": 12033}}]})
    assert values_ok(BY_ID[9], None) is True and values_ok(BY_ID[9], {"parts": []}) is False


def test_score_e_informe_con_repeticiones():
    good = {"status": "answered", "result": {"parts": [{"result": 9.17}]}, "code_attempts": 1,
            "candidates": [md(M, "Cuadro 1"), md(M, "Cuadro 2")],
            "selected_tables": [md(M, "Cuadro 1"), md(M, "Cuadro 2")]}
    bad = good | {"status": "partial"}
    runs = []
    for state in (good, bad):
        s = score(BY_ID[3], state)
        runs.append(s | {"got_status": state["status"], "tables": []})
    text = run_eval.to_markdown([{"case": BY_ID[3], "runs": runs, "answers": [("ok", [])], "errors": []}], 2)
    assert "⚠️ 1/2" in text and "answered, partial" in text
    assert "Preguntas correctas en todas las corridas:** 0 / 1" in text


def test_evaluador_de_langsmith():
    outputs = {"status": "cannot_answer", "result": None, "candidates": [md(A, "Cuadro 3.1")],
               "selected_tables": [], "code_attempts": 0}
    ref = {"case_id": 9}
    assert langsmith_eval._metric("status")(outputs, ref) == {"key": "status", "score": 1}
    assert langsmith_eval._metric("selection")(outputs, ref)["score"] == 1
    assert langsmith_eval._metric("retrieval")(outputs, {"case_id": 10})["score"] is None
