"""Evaluación automatizada en LangSmith: sube las preguntas como dataset y corre un experimento.

Uso:
    python scripts/langsmith_eval.py                    # una corrida por pregunta
    python scripts/langsmith_eval.py --repeats 3        # tres corridas por pregunta

Los evaluadores son código (no LLM-as-judge): miden por separado recuperación, selección,
estado y valores, con las mismas reglas que scripts/run_eval.py. El experimento queda en la UI
de LangSmith, dentro del dataset, y se puede comparar con corridas anteriores.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402
from langsmith import Client, evaluate  # noqa: E402

from agents.analyst.graph import build_graph, default_deps, run_config  # noqa: E402
from evaluation.cases import CASES  # noqa: E402
from evaluation.metrics import score  # noqa: E402

DATASET = "mas-2026s2-preguntas-de-prueba"
BY_ID = {c.id: c for c in CASES}


def ensure_dataset(client: Client) -> None:
    """Crea el dataset la primera vez (si ya existe, no lo duplica)."""
    if client.has_dataset(dataset_name=DATASET):
        return
    ds = client.create_dataset(DATASET, description="Preguntas de data/preguntas_prueba.md")
    client.create_examples(
        dataset_id=ds.id,
        examples=[
            {
                "inputs": {"question": c.question},
                "outputs": {"case_id": c.id, "status": c.status},
                "metadata": {"case_id": c.id},
            }
            for c in CASES
        ],
    )


def make_target():
    graph = build_graph(default_deps())

    def target(inputs: dict) -> dict:
        q = inputs["question"]
        state = graph.invoke({"question": q}, config=run_config(q))
        keep = ("file", "caption", "name")
        return {
            "status": state["status"],
            "answer": state.get("answer", ""),
            "result": state.get("result"),
            "candidates": [{k: c.get(k) for k in keep} for c in state.get("candidates", [])],
            "selected_tables": [{k: t.get(k) for k in keep} for t in state.get("selected_tables", [])],
            "code_attempts": state.get("code_attempts", 0),
            "verifier_flags": len(state["verdict"].violations) if state.get("verdict") else 0,
        }

    return target


def _metric(key: str):
    def evaluator(outputs: dict, reference_outputs: dict) -> dict:
        case = BY_ID[reference_outputs["case_id"]]
        value = score(case, {**outputs, "verdict": None})[key]
        return {"key": key, "score": None if value is None else int(bool(value))}

    evaluator.__name__ = key
    return evaluator


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repeats", type=int, default=1, help="corridas por pregunta")
    args = parser.parse_args()
    load_dotenv()
    client = Client()
    ensure_dataset(client)
    results = evaluate(
        make_target(),
        data=DATASET,
        evaluators=[_metric(k) for k in ("retrieval", "selection", "status", "values", "correct")],
        experiment_prefix="analista",
        num_repetitions=args.repeats,
        max_concurrency=1,
        client=client,
    )
    print(f"Experimento: {results.experiment_name}")


if __name__ == "__main__":
    main()
