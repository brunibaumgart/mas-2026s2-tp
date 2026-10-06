"""Uso: python -m agents.analyst "¿Pregunta?" """
import sys

from agents.analyst.graph import ask


def main(question: str) -> None:
    state = ask(question)
    print(f"Estado: {state['status']}  (intentos de código: {state.get('code_attempts', 0)})")
    for m in state.get("missing_data", []):
        print(f"  falta: {m}")
    print("Tablas:", ", ".join(f"{t['name']} ({t['source']})" for t in state["selected_tables"]))
    if state.get("code"):
        print("\n--- código ---\n" + state["code"])
        print("\n--- salida ---\n" + state.get("exec_stdout", ""))
    print("\n--- respuesta ---\n" + state["answer"])


if __name__ == "__main__":
    main(" ".join(sys.argv[1:]))
