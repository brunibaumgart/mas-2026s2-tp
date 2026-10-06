from pathlib import Path

import pytest

from services.pdf_context import collect_context
from services.pdf_extract import extract_tables

PDFS = Path(__file__).resolve().parent.parent / "data" / "sample_pdfs"


def contexts_by_caption(name):
    path = PDFS / name
    tables = extract_tables(path).tables
    return {t.caption: c for t, c in zip(tables, collect_context(path, tables))}


@pytest.fixture(scope="module")
def memoria():
    return contexts_by_caption("memoria_andina_tech_2024.pdf")


@pytest.fixture(scope="module")
def anuario():
    return contexts_by_caption("anuario_valdoria_2023.pdf")


def test_contexto_cuadro1(memoria):
    c = memoria["Cuadro 1"]
    assert c.above.startswith("1. Desempeño económico")
    assert "miles de pesos nominales" in c.above
    assert c.below.startswith("Nota: los valores negativos se presentan entre paréntesis")


def test_contexto_tabla_multipagina_toma_la_nota_de_la_ultima_pagina(memoria):
    c = memoria["Cuadro 3"]
    assert c.above.startswith("2. Ventas por región")
    assert c.below.startswith("Fuente: sistema comercial interno")


def test_contexto_no_mezcla_la_nota_de_la_tabla_anterior(memoria):
    c = memoria["Cuadro 2"]
    assert c.above.startswith("3. Estructura de gastos")
    assert "sistema comercial interno" not in c.above
    assert c.below == "Fuente: Gerencia de Administración y Finanzas."


def test_contexto_anuario(anuario):
    assert anuario["Cuadro 3.1"].above.startswith("Capítulo 3. Comercio exterior")
    assert anuario["Cuadro 3.1"].below == "Fuente: Dirección de Aduanas."
    assert "miles de habitantes" in anuario["Cuadro 2.1"].above
