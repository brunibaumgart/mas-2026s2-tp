"""Métricas por etapa: recuperación, selección, estado y valores.

Separar las etapas permite ubicar cada falla: una respuesta incorrecta puede venir de no haber
recuperado la tabla, de haber elegido mal, de un estado mal decidido o de un cálculo mal hecho.
"""
from __future__ import annotations

import json

from evaluation.cases import Case


def table_key(md: dict) -> tuple[str, str]:
    return (md.get("file", ""), md.get("caption", ""))


def retrieval_hit(case: Case, candidates: list[dict]) -> bool | None:
    """¿Están todas las tablas esperadas entre las candidatas? None si el caso no espera tablas."""
    if not case.tables:
        return None
    found = {table_key(c) for c in candidates}
    return all(t in found for t in case.tables)


def selection_ok(case: Case, selected: list[dict]) -> bool:
    """Respondibles: las tablas usadas son exactamente las esperadas. cannot_answer: ninguna."""
    used = {table_key(t) for t in selected}
    if case.status == "cannot_answer":
        return not used
    return used == set(case.tables)


def _numbers(value) -> list[float]:
    if isinstance(value, bool):
        return []
    if isinstance(value, (int, float)):
        return [float(value)]
    if isinstance(value, dict):
        return [n for v in value.values() for n in _numbers(v)]
    if isinstance(value, list):
        return [n for v in value for n in _numbers(v)]
    return []


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= max(0.015, abs(b) * 0.001)


def values_ok(case: Case, result: dict | None) -> bool | None:
    """True/False si el caso espera valores; en cannot_answer, que no haya resultado; si no, None."""
    if case.status == "cannot_answer":
        return result is None
    if not case.numbers and not case.texts:
        return None
    if not result:
        return False
    found = [n for p in result.get("parts", []) for n in _numbers(p.get("result"))]
    candidates = found + [n * 100 for n in found]  # acepta fracción en lugar de %
    ok_numbers = all(any(_close(c, alt) for c in candidates for alt in alts) for alts in case.numbers)
    dump = json.dumps(result, ensure_ascii=False)
    return ok_numbers and all(t in dump for t in case.texts)


def score(case: Case, state: dict) -> dict:
    status_ok = state.get("status") == case.status
    vals = values_ok(case, state.get("result"))
    return {
        "retrieval": retrieval_hit(case, state.get("candidates", [])),
        "selection": selection_ok(case, state.get("selected_tables", [])),
        "status": status_ok,
        "values": vals,
        "correct": status_ok and vals is not False,
        "attempts": state.get("code_attempts", 0),
        "verifier_flags": len(state["verdict"].violations) if state.get("verdict") else 0,
    }
