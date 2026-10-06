"""Extracción determinística de tablas de PDFs (sin LLM).

1. Detecta tablas con ``page.find_tables()`` y las asocia a su rótulo ("Cuadro N. ...").
2. Aplana encabezados de dos filas con celda combinada.
3. Une tablas que continúan en la página siguiente (encabezado repetido, sin rótulo propio).
4. Convierte números en formato es-AR (``($ 41.200)``, ``7,2 %``, ``4.812,3``) a ``float``.

Los rótulos sin tabla de texto debajo (p. ej. tablas escaneadas como imagen) se informan
en ``ExtractionResult.skipped``; no se intenta leerlos.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

CAPTION_RE = re.compile(r"^Cuadro\s+(\d+(?:\.\d+)*)\.?\s*(.*)$", re.S)
NUMBER_RE = re.compile(r"^\d+(?:\.\d+)?$")
YEAR_RE = re.compile(r"^(19|20)\d{2}$")
# Distancia máxima (pt) entre el rótulo y el borde superior de su tabla.
CAPTION_MAX_GAP = 40

Cell = str | float | None


@dataclass
class Table:
    caption: str | None
    title: str | None
    pages: list[int]
    columns: list[str]
    rows: list[list[Cell]]
    header_group: str | None = None
    # Un bbox (x0, y0, x1, y1) por cada página de ``pages``.
    bboxes: list[tuple[float, float, float, float]] = field(default_factory=list)

    def to_dataframe(self):
        import pandas as pd

        return pd.DataFrame(self.rows, columns=self.columns)


@dataclass
class SkippedTable:
    caption: str
    title: str
    page: int
    reason: str


@dataclass
class ExtractionResult:
    tables: list[Table] = field(default_factory=list)
    skipped: list[SkippedTable] = field(default_factory=list)

    def get(self, caption: str) -> Table:
        for t in self.tables:
            if t.caption == caption:
                return t
        raise KeyError(caption)


# ------------------------------------------------------------------- números
def parse_number(text: str | None) -> float | None:
    """Convierte un número es-AR a float; devuelve None si el texto no es un número.

    Asume punto como separador de miles y coma decimal: '4.812,3' -> 4812.3.
    """
    if text is None:
        return None
    s = " ".join(text.split())
    if not s:
        return None
    negative = False
    if s.startswith("(") and s.endswith(")"):
        negative, s = True, s[1:-1].strip()
    if s[:1] in ("-", "−"):
        negative, s = True, s[1:].strip()
    for token in ("US$", "$", "%"):
        s = s.replace(token, "")
    s = s.replace(" ", "").replace(".", "").replace(",", ".")
    if not NUMBER_RE.match(s):
        return None
    value = float(s)
    return -value if negative else value


def _clean(cell: str | None) -> str:
    return " ".join(cell.split()) if cell else ""


def _typed_rows(rows: list[list[str]]) -> list[list[Cell]]:
    """Convierte a float las columnas totalmente numéricas; las de años quedan como texto."""
    ncols = len(rows[0]) if rows else 0
    numeric = []
    for c in range(ncols):
        values = [r[c] for r in rows if r[c]]
        is_year_dim = bool(values) and all(YEAR_RE.match(v) for v in values)
        numeric.append(
            bool(values) and not is_year_dim and all(parse_number(v) is not None for v in values)
        )
    return [
        [parse_number(v) if numeric[c] else (v or None) for c, v in enumerate(r)] for r in rows
    ]


# ---------------------------------------------------------------- encabezados
def _flatten_header(raw: list[list[str | None]]) -> tuple[list[str], str | None, int]:
    """Devuelve (columnas, rótulo combinado, filas de encabezado consumidas).

    Una celda combinada horizontalmente llega como texto seguido de ``None``:
    ``['', 'Ejercicio fiscal (miles de $)', None, ...]`` + ``['Concepto', '2020', ...]``
    -> ``['Concepto', '2020', ...]`` con rótulo combinado ``'Ejercicio fiscal (miles de $)'``.
    """
    first = raw[0]
    if len(raw) < 2 or None not in first[1:]:
        return [_clean(c) for c in first], None, 1
    group = next(
        (_clean(c) for i, c in enumerate(first[:-1]) if c and first[i + 1] is None), None
    )
    columns = [_clean(b) or _clean(a) for a, b in zip(first, raw[1])]
    return columns, group, 2


# -------------------------------------------------------------------- rótulos
def _caption_blocks(page: pymupdf.Page) -> list[tuple[tuple[float, ...], str, str]]:
    """Bloques de texto que empiezan con 'Cuadro N.': (bbox, 'Cuadro N', título)."""
    out = []
    for b in page.get_text("blocks"):
        if b[6] != 0:
            continue
        m = CAPTION_RE.match(_clean(b[4]))
        if m:
            out.append((tuple(b[:4]), f"Cuadro {m[1]}", m[2].strip()))
    return out


def _caption_for(table_bbox, captions):
    """Rótulo inmediatamente arriba de la tabla, si existe.

    El bloque del rótulo puede solaparse unos pt con el borde de la tabla (descendentes),
    por eso se compara con su borde superior.
    """
    y0 = table_bbox[1]
    above = [c for c in captions if c[0][1] < y0 and y0 - c[0][3] <= CAPTION_MAX_GAP]
    return max(above, key=lambda c: c[0][1]) if above else None


# ----------------------------------------------------------------------- API
def extract_tables(pdf_path: str | Path) -> ExtractionResult:
    result = ExtractionResult()
    pending: list[tuple[Table, list[list[str]]]] = []

    with pymupdf.open(pdf_path) as doc:
        for page in doc:
            page_no = page.number + 1
            captions = _caption_blocks(page)
            used = set()

            for idx, t in enumerate(page.find_tables().tables):
                raw = t.extract()
                if t.header.external:
                    raw = [t.header.names, *raw]
                if not raw:
                    continue
                caption = _caption_for(t.bbox, captions)
                if caption:
                    used.add(caption[1])

                prev = pending[-1] if pending else None
                header = [_clean(c) for c in raw[0]]
                is_continuation = (
                    caption is None
                    and idx == 0
                    and prev is not None
                    and prev[0].pages[-1] == page_no - 1
                    and len(header) == len(prev[0].columns)
                )
                if is_continuation:
                    body = raw[1:] if header == prev[0].columns else raw
                    prev[0].pages.append(page_no)
                    prev[0].bboxes.append(tuple(t.bbox))
                    prev[1].extend([_clean(c) for c in r] for r in body)
                    continue

                columns, group, n_header = _flatten_header(raw)
                table = Table(
                    caption=caption[1] if caption else None,
                    title=caption[2] if caption else None,
                    pages=[page_no],
                    columns=columns,
                    rows=[],
                    header_group=group,
                    bboxes=[tuple(t.bbox)],
                )
                pending.append((table, [[_clean(c) for c in r] for r in raw[n_header:]]))

            has_images = bool(page.get_images())
            for _, label, title in captions:
                if label not in used:
                    reason = (
                        "la tabla es una imagen (no hay texto extraíble)"
                        if has_images
                        else "no se detectó una tabla debajo del rótulo"
                    )
                    result.skipped.append(SkippedTable(label, title, page_no, reason))

    for table, rows in pending:
        table.rows = _typed_rows(rows)
        result.tables.append(table)
    return result


if __name__ == "__main__":
    import sys

    for path in sys.argv[1:]:
        res = extract_tables(path)
        print(f"===== {path}")
        for t in res.tables:
            print(f"\n{t.caption} — {t.title} (págs. {t.pages}, {len(t.rows)} filas)")
            if t.header_group:
                print(f"[{t.header_group}]")
            print(t.to_dataframe().to_string(index=False))
        for s in res.skipped:
            print(f"\nSALTEADO {s.caption} (pág. {s.page}): {s.reason}")
