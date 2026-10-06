"""Texto alrededor de cada tabla: sección/párrafo/rótulo de arriba y nota/fuente de abajo."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pymupdf

from services.pdf_extract import CAPTION_RE, Table

# Título de sección + párrafo introductorio + rótulo.
ABOVE_BLOCKS = 3
# Distancia máxima (pt) entre el borde inferior de la tabla y su nota/fuente.
BELOW_MAX_GAP = 30


@dataclass
class TableContext:
    above: str
    below: str


def _clean(text: str) -> str:
    return " ".join(text.split())


def _text_blocks(page: pymupdf.Page) -> list[tuple]:
    return sorted(
        (b for b in page.get_text("blocks") if b[6] == 0 and b[4].strip()), key=lambda b: b[1]
    )


def _context_for(doc: pymupdf.Document, table: Table, tables: list[Table]) -> TableContext:
    first_page, (_, top, _, _) = table.pages[0], table.bboxes[0]
    # No mirar más arriba que el final de otra tabla de la misma página.
    floor = max(
        (
            bbox[3]
            for other in tables
            for page, bbox in zip(other.pages, other.bboxes)
            if page == first_page and bbox[3] <= top
        ),
        default=0.0,
    )
    above = [b for b in _text_blocks(doc[first_page - 1]) if floor <= b[1] < top]
    above_text = "\n".join(_clean(b[4]) for b in above[-ABOVE_BLOCKS:])

    last_page, (_, _, _, bottom) = table.pages[-1], table.bboxes[-1]
    below = [
        b
        for b in _text_blocks(doc[last_page - 1])
        if bottom - 2 <= b[1] <= bottom + BELOW_MAX_GAP
    ]
    below_text = _clean(below[0][4]) if below else ""
    if CAPTION_RE.match(below_text):
        below_text = ""
    return TableContext(above=above_text, below=below_text)


def collect_context(pdf_path: str | Path, tables: list[Table]) -> list[TableContext]:
    with pymupdf.open(pdf_path) as doc:
        return [_context_for(doc, t, tables) for t in tables]
