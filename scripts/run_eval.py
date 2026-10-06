"""Corre las preguntas de prueba contra el Analista y escribe los resultados por etapa.

Uso:
    python scripts/run_eval.py                 # todas, una vez
    python scripts/run_eval.py 3 7             # solo algunas
    python scripts/run_eval.py --repeats 3     # cada pregunta 3 veces (mide la variación)

Salida: tabla en consola y data/eval_results.md (para pegar en EVALUATION.md).
Requiere los dos PDFs de ejemplo ya ingeridos. Cada corrida de una pregunta son ~5 llamadas al LLM.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agents.analyst.graph import ask, default_deps  # noqa: E402
from evaluation.cases import CASES, Case  # noqa: E402
from evaluation.metrics import score  # noqa: E402

OUT = ROOT / "data" / "eval_results.md"
STAGES = ("retrieval", "selection", "status", "values", "correct")


def run(cases: list[Case], repeats: int) -> list[dict]:
    deps = default_deps()
    rows = []
    for case in cases:
        runs, answers, errors = [], [], []
        for i in range(repeats):
            print(f"[{case.id}] ({i + 1}/{repeats}) {case.question}", flush=True)
            try:
                state = ask(case.question, deps)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{type(exc).__name__}: {exc}")
                print(f"    ERROR {exc}")
                continue
            s = score(case, state)
            s["got_status"] = state["status"]
            s["tables"] = [t.get("name") for t in state.get("selected_tables", [])]
            runs.append(s)
            answers.append((state.get("answer", ""), state.get("missing_data", [])))
            print("    " + " ".join(f"{k}={s[k]}" for k in (*STAGES, "attempts", "verifier_flags")))
        rows.append({"case": case, "runs": runs, "answers": answers, "errors": errors})
    return rows


def _frac(runs: list[dict], key: str) -> str:
    vals = [r[key] for r in runs if r[key] is not None]
    if not vals:
        return "—"
    ok = sum(1 for v in vals if v)
    mark = "✅" if ok == len(vals) else ("❌" if ok == 0 else "⚠️")
    return f"{mark} {ok}/{len(vals)}"


def to_markdown(rows: list[dict], repeats: int) -> str:
    lines = [
        f"Corridas por pregunta: {repeats}.\n",
        "| # | Esperado | Obtenido | Recuperación | Selección | Estado | Valores | Correcta | "
        "Intentos (prom.) | Obs. del verificador |",
        "|---|---|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|",
    ]
    for r in rows:
        c, runs = r["case"], r["runs"]
        if not runs:
            lines.append(f"| {c.id} | {c.status} | error | — | — | ❌ | ❌ | ❌ | — | {r['errors'][0]} |")
            continue
        got = ", ".join(sorted({x["got_status"] for x in runs}))
        attempts = sum(x["attempts"] for x in runs) / len(runs)
        flags = sum(x["verifier_flags"] for x in runs)
        lines.append(
            f"| {c.id} | {c.status} | {got} | {_frac(runs, 'retrieval')} | {_frac(runs, 'selection')} | "
            f"{_frac(runs, 'status')} | {_frac(runs, 'values')} | {_frac(runs, 'correct')} | "
            f"{attempts:.1f} | {flags} |"
        )
    all_runs = [x for r in rows for x in r["runs"]]
    n = len(rows) * repeats
    lines.append("")
    for key, label in (("retrieval", "Recuperación"), ("selection", "Selección"),
                       ("status", "Estado"), ("correct", "Correctas")):
        vals = [x[key] for x in all_runs if x[key] is not None]
        lines.append(f"- **{label}:** {sum(1 for v in vals if v)} / {len(vals)}")
    always = sum(1 for r in rows if r["runs"] and len(r["runs"]) == repeats and all(x["correct"] for x in r["runs"]))
    lines.append(f"- **Preguntas correctas en todas las corridas:** {always} / {len(rows)} ({n} corridas)\n")

    lines.append("### Respuestas (primera corrida)\n")
    for r in rows:
        c = r["case"]
        lines.append(f"**{c.id}. {c.question}**\n")
        if not r["answers"]:
            lines.append(f"> Error: {r['errors'][0]}\n")
            continue
        answer, missing = r["answers"][0]
        lines.append("> " + answer.replace("\n", "\n> ") + "\n")
        for m in missing:
            lines.append(f"- Falta: {m}")
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("ids", nargs="*", type=int, help="ids de las preguntas (por defecto, todas)")
    parser.add_argument("--repeats", type=int, default=1, help="corridas por pregunta")
    args = parser.parse_args()
    selected = [c for c in CASES if not args.ids or c.id in args.ids]
    rows = run(selected, args.repeats)
    md = to_markdown(rows, args.repeats)
    OUT.write_text(md, encoding="utf-8")
    print("\n" + md.split("### Respuestas")[0])
    print(f"Detalle en {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
