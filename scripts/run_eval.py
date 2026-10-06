"""Corre las preguntas de prueba contra el Analista y escribe los resultados.

Uso:
    python scripts/run_eval.py            # todas
    python scripts/run_eval.py 3 7        # solo algunas

Salida: tabla en consola y data/eval_results.md (para pegar en EVALUATION.md).
Requiere los dos PDFs de ejemplo ya ingeridos.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agents.analyst.graph import ask, default_deps  # noqa: E402

OUT = ROOT / "data" / "eval_results.md"


@dataclass
class Case:
    id: int
    question: str
    status: str
    # Cada elemento es un conjunto de alternativas aceptables; tienen que aparecer todos.
    numbers: list[tuple[float, ...]] = field(default_factory=list)
    texts: list[str] = field(default_factory=list)


CASES = [
    Case(1, "¿Cuál fue el crecimiento interanual promedio de los ingresos entre 2020 y 2024?",
         "answered", [(11.51, 11.48)]),
    Case(2, "¿Qué proporción de los gastos operativos totales representó I+D en cada año?",
         "answered", [(21.75,), (22.26,), (24.25,), (27.18,), (29.09,)]),
    Case(3, "¿Qué porcentaje de los ingresos por ventas representó el gasto en I+D en 2024?",
         "answered", [(9.17,)]),
    Case(4, "¿Cuánto crecieron las ventas de la región Sur en 2024 respecto de 2023?",
         "answered", [(11.32,)]),
    Case(5, "¿Qué mes de 2024 tuvo las mayores ventas totales y cuánto vendió?",
         "answered", [(12033,)], ["Diciembre"]),
    Case(6, "¿Cuáles fueron las exportaciones per cápita de la región Litoral en 2023?",
         "answered", [(2858.80,)]),
    Case(7, "¿Qué región tuvo la tasa de desocupación más alta en 2023, y por cuánto superó "
            "al promedio nacional?", "partial", [(10.6,)], ["Desierto"]),
    Case(8, "¿Cuáles fueron las exportaciones per cápita de Montaña en 2020?", "cannot_answer"),
    Case(9, "¿A cuántos pesos equivalen las exportaciones de Litoral en 2023?", "cannot_answer"),
    Case(10, "¿Cuál fue la inflación de Argentina en 2023?", "cannot_answer"),
    Case(11, "¿Cuáles fueron los ingresos por ventas de Andina Tech en 2025?", "cannot_answer"),
]


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


def check_values(case: Case, result: dict | None) -> bool | None:
    """True/False si el caso espera valores; None si no aplica."""
    if not case.numbers and not case.texts:
        return None
    if not result:
        return False
    found = [n for p in result.get("parts", []) for n in _numbers(p.get("result"))]
    candidates = found + [n * 100 for n in found]  # acepta fracción en lugar de %
    ok_numbers = all(any(_close(c, alt) for c in candidates for alt in alts) for alts in case.numbers)
    dump = json.dumps(result, ensure_ascii=False)
    return ok_numbers and all(t in dump for t in case.texts)


def run(cases: list[Case]) -> list[dict]:
    deps = default_deps()
    rows = []
    for case in cases:
        print(f"[{case.id}] {case.question}", flush=True)
        try:
            state = ask(case.question, deps)
        except Exception as exc:  # noqa: BLE001
            rows.append({"case": case, "error": f"{type(exc).__name__}: {exc}"})
            print(f"    ERROR {exc}")
            continue
        values_ok = check_values(case, state.get("result"))
        if case.status == "cannot_answer":
            values_ok = state.get("result") is None
        row = {
            "case": case,
            "status": state["status"],
            "status_ok": state["status"] == case.status,
            "values_ok": values_ok,
            "attempts": state.get("code_attempts", 0),
            "tables": [t.get("name") for t in state.get("selected_tables", [])],
            "missing": state.get("missing_data", []),
            "answer": state.get("answer", ""),
        }
        rows.append(row)
        print(f"    estado={row['status']} (esperado {case.status}) valores_ok={values_ok} "
              f"intentos={row['attempts']}")
    return rows


def _mark(ok: bool | None) -> str:
    return "—" if ok is None else ("✅" if ok else "❌")


def to_markdown(rows: list[dict]) -> str:
    lines = [
        "| # | Estado esperado | Estado obtenido | Estado | Valores | Intentos de código | Tablas usadas |",
        "|---|---|---|:---:|:---:|:---:|---|",
    ]
    for r in rows:
        c = r["case"]
        if "error" in r:
            lines.append(f"| {c.id} | {c.status} | error | ❌ | ❌ | — | {r['error']} |")
            continue
        lines.append(
            f"| {c.id} | {c.status} | {r['status']} | {_mark(r['status_ok'])} | "
            f"{_mark(r['values_ok'])} | {r['attempts']} | {', '.join(r['tables']) or '—'} |"
        )
    ok = sum(1 for r in rows if r.get("status_ok") and r.get("values_ok") is not False)
    lines.append(f"\n**Correctas: {ok} / {len(rows)}**\n")
    lines.append("### Respuestas\n")
    for r in rows:
        c = r["case"]
        lines.append(f"**{c.id}. {c.question}**\n")
        if "error" in r:
            lines.append(f"> Error: {r['error']}\n")
            continue
        lines.append("> " + r["answer"].replace("\n", "\n> ") + "\n")
        for m in r["missing"]:
            lines.append(f"- Falta: {m}")
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    wanted = {int(a) for a in sys.argv[1:]}
    selected = [c for c in CASES if not wanted or c.id in wanted]
    results = run(selected)
    md = to_markdown(results)
    OUT.write_text(md, encoding="utf-8")
    print("\n" + md.split("### Respuestas")[0])
    print(f"Detalle en {OUT.relative_to(ROOT)}")
