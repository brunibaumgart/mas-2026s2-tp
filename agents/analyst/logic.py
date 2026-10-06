"""Lógica determinística del Analista: verificación de la selección, estado y salida del código."""
from __future__ import annotations

import json
import math
from collections.abc import Callable

import pandas as pd

from agents.analyst.schemas import PartSelection, QuestionPart, Selection, TableUse
from agents.analyst.state import Status
from services.table_store import text_values


def compute_status(answerable: list[bool]) -> Status:
    if answerable and all(answerable):
        return "answered"
    if any(answerable):
        return "partial"
    return "cannot_answer"


def _match_label(requested: str, available: list[str]) -> str | None:
    """Etiqueta exacta, o la única que coincide ignorando mayúsculas / como subcadena."""
    if requested in available:
        return requested
    req = requested.casefold().strip()
    exact = [a for a in available if a.casefold().strip() == req]
    if len(exact) == 1:
        return exact[0]
    partial = [a for a in available if req and req in a.casefold()]
    return partial[0] if len(partial) == 1 else None


def mark_unanswerable(sel: PartSelection, missing: str) -> PartSelection:
    return sel.model_copy(update={"answerable": False, "tables": [], "missing": missing})


def check_selection(
    parts: list[QuestionPart],
    selection: Selection,
    candidates: dict[str, dict],
    load_df: Callable[[str], pd.DataFrame],
) -> list[PartSelection]:
    """Verifica contra los datos reales que las tablas, columnas y filas elegidas existan.

    Una parte que el LLM marcó como respondible pasa a no respondible si pide una columna
    (p. ej. un año) o una fila que la tabla no tiene.
    """
    by_id = {p.part_id: p for p in selection.parts}
    checked = []
    for part in parts:
        sel = by_id.get(part.id)
        if sel is None:
            sel = PartSelection(
                part_id=part.id, answerable=False, tables=[],
                missing="El selector no evaluó esta parte.", conversions=None,
            )
        if not sel.answerable:
            checked.append(sel if sel.missing else mark_unanswerable(sel, "Faltan datos."))
            continue
        if not sel.tables:
            checked.append(mark_unanswerable(sel, "No se indicó ninguna tabla."))
            continue

        problems, fixed_uses = [], []
        for use in sel.tables:
            md = candidates.get(use.table_id)
            if md is None:
                problems.append(f"La tabla {use.table_id} no está entre las candidatas.")
                continue
            try:
                df = load_df(use.table_id)
            except FileNotFoundError:
                problems.append(f"Los datos de '{md.get('name')}' no están disponibles.")
                continue
            columns = [str(c) for c in df.columns]
            labels = text_values(df)
            cols = [_match_label(c, columns) for c in use.columns]
            rows = [_match_label(r, labels) for r in use.row_labels]
            bad_cols = [c for c, m in zip(use.columns, cols) if m is None]
            bad_rows = [r for r, m in zip(use.row_labels, rows) if m is None]
            if bad_cols:
                problems.append(
                    f"'{md.get('name')}' no tiene las columnas {bad_cols} (tiene: {columns})."
                )
            if bad_rows:
                problems.append(f"'{md.get('name')}' no tiene las filas {bad_rows}.")
            fixed_uses.append(use.model_copy(update={"columns": cols, "row_labels": rows}))

        if problems:
            checked.append(mark_unanswerable(sel, " ".join(problems)))
        else:
            checked.append(sel.model_copy(update={"tables": fixed_uses}))
    return checked


def missing_data(parts: list[QuestionPart], selection: list[PartSelection]) -> list[str]:
    questions = {p.id: p.question for p in parts}
    return [
        f"{questions.get(s.part_id, s.part_id)}: {s.missing}"
        for s in selection
        if not s.answerable
    ]


# ------------------------------------------------------------- salida del código
def parse_output(stdout: str) -> dict | None:
    """Parsea la última línea JSON del stdout."""
    for line in reversed(stdout.strip().splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                return None
            return data if isinstance(data, dict) else None
    return None


def _has_nan(value) -> bool:
    if isinstance(value, float):
        return math.isnan(value) or math.isinf(value)
    if isinstance(value, dict):
        return any(_has_nan(v) for v in value.values())
    if isinstance(value, list):
        return any(_has_nan(v) for v in value)
    return False


def validate_output(output: dict | None, part_ids: list[str]) -> list[str]:
    if output is None:
        return [
            "La última línea de stdout no es un JSON válido. Terminá con "
            "print(json.dumps({'parts': [...]}, ensure_ascii=False))."
        ]
    entries = output.get("parts")
    if not isinstance(entries, list):
        return ["El JSON tiene que tener una clave 'parts' con una lista."]
    by_id = {e.get("part_id"): e for e in entries if isinstance(e, dict)}
    errors = []
    for pid in part_ids:
        entry = by_id.get(pid)
        if entry is None:
            errors.append(f"Falta la parte '{pid}' en el JSON.")
        elif entry.get("result") is None and not entry.get("missing"):
            errors.append(f"La parte '{pid}' no tiene 'result' ni 'missing'.")
        elif _has_nan(entry.get("result")):
            errors.append(
                f"La parte '{pid}' dio NaN/inf: revisá los nombres de filas y columnas."
            )
    return errors


def apply_output(selection: list[PartSelection], output: dict) -> list[PartSelection]:
    """Las partes en las que el código informó un dato faltante pasan a no respondibles."""
    by_id = {e.get("part_id"): e for e in output.get("parts", []) if isinstance(e, dict)}
    updated = []
    for sel in selection:
        entry = by_id.get(sel.part_id, {})
        if sel.answerable and entry.get("result") is None and entry.get("missing"):
            updated.append(mark_unanswerable(sel, str(entry["missing"])))
        else:
            updated.append(sel)
    return updated


# ------------------------------------------------------------- citas a nivel de celda
VALUE_TOLERANCE = 0.006  # el código puede redondear a 2 decimales


def _find_rows(df: pd.DataFrame, row) -> list[int]:
    """Índices de las filas cuyas celdas de texto contienen todas las etiquetas pedidas.

    ``row`` puede ser una etiqueta ("Litoral") o varias (["2023", "Diciembre"]) cuando la fila
    se identifica con más de una columna.
    """
    wanted = [row] if not isinstance(row, list) else row
    wanted = [str(w).casefold().strip() for w in wanted]
    text_cols = [c for c in df.columns if not pd.api.types.is_numeric_dtype(df[c])]
    hits = []
    for i in range(len(df)):
        values = {str(df.iloc[i][c]).casefold().strip() for c in text_cols}
        if wanted and all(w in values for w in wanted):
            hits.append(i)
    return hits


def _same_value(cited, actual) -> bool:
    try:
        return abs(float(cited) - float(actual)) <= VALUE_TOLERANCE
    except (TypeError, ValueError):
        return str(cited).casefold().strip() == str(actual).casefold().strip()


def check_citation(cell: dict, tables: dict[str, pd.DataFrame]) -> str | None:
    """None si la celda citada existe y tiene ese valor; si no, el problema."""
    name = str(cell.get("table", ""))
    df = tables.get(name) if name.endswith(".parquet") else tables.get(f"{name}.parquet")
    if df is None:
        return f"la tabla '{name}' no es ninguno de los archivos disponibles ({list(tables)})"
    column = _match_label(str(cell.get("column", "")), [str(c) for c in df.columns])
    if column is None:
        return f"'{name}' no tiene la columna {cell.get('column')!r}"
    rows = _find_rows(df, cell.get("row"))
    if not rows:
        return f"'{name}' no tiene ninguna fila {cell.get('row')!r}"
    if len(rows) > 1:
        return f"la fila {cell.get('row')!r} es ambigua en '{name}' (agregá más etiquetas)"
    actual = df.iloc[rows[0]][df.columns[[str(c) for c in df.columns].index(column)]]
    if not _same_value(cell.get("value"), actual):
        return f"en '{name}', fila {cell.get('row')!r}, columna {column!r} el valor es {actual}, no {cell.get('value')}"
    return None


def check_citations(
    output: dict, part_ids: list[str], tables: dict[str, pd.DataFrame]
) -> tuple[list[dict], list[str]]:
    """Verifica en código las celdas que el programa dice haber usado.

    Devuelve las citas anotadas (``ok`` y ``problem``) y los errores para reintentar.
    """
    by_id = {e.get("part_id"): e for e in output.get("parts", []) if isinstance(e, dict)}
    cited, errors = [], []
    for pid in part_ids:
        entry = by_id.get(pid, {})
        if entry.get("result") is None:
            continue  # la parte informó un dato faltante: no hay nada que citar
        cells = entry.get("cells")
        if not isinstance(cells, list) or not cells:
            errors.append(f"La parte '{pid}' no tiene 'cells' con las celdas de origen.")
            continue
        for cell in cells:
            if not isinstance(cell, dict):
                errors.append(f"La parte '{pid}' tiene una celda que no es un objeto: {cell!r}.")
                continue
            problem = check_citation(cell, tables)
            cited.append({"part_id": pid, **cell, "ok": problem is None, "problem": problem})
            if problem:
                errors.append(f"Cita inválida en '{pid}': {problem}.")
    return cited, errors


# ------------------------------------------------------------- verificador
def apply_verdict(selection: list[PartSelection], verdict) -> tuple[list[PartSelection], list[str]]:
    """Aplica el veredicto del verificador.

    - ``dato_faltante``: la parte pasa a no respondible (el estado baja).
    - ``calculo``: se devuelve como error para que el código se reescriba.
    """
    answerable = {s.part_id for s in selection if s.answerable}
    missing = {
        v.part_id: v.detail for v in verdict.violations
        if v.kind == "dato_faltante" and v.part_id in answerable
    }
    calc_errors = [
        f"El verificador rechazó el cálculo de '{v.part_id}': {v.detail}"
        for v in verdict.violations
        if v.kind == "calculo" and v.part_id in answerable and v.part_id not in missing
    ]
    updated = [mark_unanswerable(s, missing[s.part_id]) if s.part_id in missing else s for s in selection]
    return updated, calc_errors


# ------------------------------------------------------------- revisión humana
def apply_review(selection: list[PartSelection], decision: dict) -> list[PartSelection]:
    """Aplica la decisión del usuario sobre las tablas seleccionadas.

    ``decision``: ``{"action": "approve"}``, ``{"action": "cancel"}`` o
    ``{"action": "edit", "tables": {part_id: [table_id, ...]}}``. Solo se editan las partes
    respondibles; una parte que se queda sin tablas pasa a no respondible.
    """
    action = decision.get("action", "approve")
    if action == "cancel":
        return [
            mark_unanswerable(s, "El usuario canceló el cálculo.") if s.answerable else s
            for s in selection
        ]
    if action != "edit":
        return selection
    chosen = decision.get("tables", {})
    updated = []
    for s in selection:
        if not s.answerable or s.part_id not in chosen:
            updated.append(s)
            continue
        current = {u.table_id: u for u in s.tables}
        uses = [
            current.get(tid) or TableUse(table_id=tid, columns=[], row_labels=[])
            for tid in chosen[s.part_id]
        ]
        if uses:
            updated.append(s.model_copy(update={"tables": uses}))
        else:
            updated.append(mark_unanswerable(s, "El usuario descartó las tablas de esta parte."))
    return updated
