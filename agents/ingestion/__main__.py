"""Uso: python -m agents.ingestion data/sample_pdfs/*.pdf"""
import sys
import time

from agents.ingestion.graph import build_graph, default_deps, run_config


def main(paths: list[str]) -> None:
    deps = default_deps()
    graph = build_graph(deps)
    ids: set[str] = set()
    for path in paths:
        state = graph.invoke({"pdf_path": path}, config=run_config(path))
        ids.update(state["indexed"])
        print(f"{state['source']}: {len(state['indexed'])} tablas indexadas "
              f"({state['attempts']} intento/s de enriquecimiento)")
        for s in state["skipped"]:
            print(f"  salteado {s.caption} (pág. {s.page}): {s.reason}")

    # Pinecone actualiza las estadísticas con unos segundos de demora.
    count = 0
    for _ in range(15):
        count = deps.index.describe_index_stats().total_vector_count
        if count >= len(ids):
            break
        time.sleep(2)
    print(f"total_vector_count: {count}")


if __name__ == "__main__":
    main(sys.argv[1:])
