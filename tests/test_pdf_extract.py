from pathlib import Path

import pytest

from services.pdf_extract import extract_tables, parse_number

PDFS = Path(__file__).resolve().parent.parent / "data" / "sample_pdfs"


@pytest.fixture(scope="module")
def memoria():
    return extract_tables(PDFS / "memoria_andina_tech_2024.pdf")


@pytest.fixture(scope="module")
def anuario():
    return extract_tables(PDFS / "anuario_valdoria_2023.pdf")


@pytest.mark.parametrize(
    "text, expected",
    [
        ("$ 85.400", 85400.0),
        ("($ 41.200)", -41200.0),
        ("7,2 %", 7.2),
        ("US$ 3.420,5", 3420.5),
        ("4.812,3", 4812.3),
        ("2.596", 2596.0),
        ("$ 0", 0.0),
        ("-1.000", -1000.0),
        ("", None),
        (None, None),
        ("Enero", None),
        ("Capital", None),
    ],
)
def test_parse_number(text, expected):
    assert parse_number(text) == expected


def test_cuadro1_encabezado_aplanado(memoria):
    t = memoria.get("Cuadro 1")
    assert t.columns == ["Concepto", "2020", "2021", "2022", "2023", "2024"]
    assert t.header_group == "Ejercicio fiscal (miles de $)"
    assert len(t.rows) == 9
    assert t.rows[0] == ["Ingresos por ventas", 85400.0, 92150.0, 104780.0, 118300.0, 131920.0]
    assert t.rows[1][1] == -41200.0


def test_ventas_mensuales_unidas_en_una_tabla(memoria):
    t = memoria.get("Cuadro 3")
    assert t.pages == [1, 2]
    assert t.columns == ["Año", "Mes", "Norte", "Centro", "Sur"]
    assert len(t.rows) == 24
    assert "Año" not in [r[0] for r in t.rows]

    sur = {y: sum(r[4] for r in t.rows if r[0] == y) for y in ("2023", "2024")}
    assert sur == {"2023": 26291.0, "2024": 29268.0}

    dic_2024 = next(r for r in t.rows if r[0] == "2024" and r[1] == "Diciembre")
    assert sum(dic_2024[2:]) == 12033.0


def test_cuadro2_gastos(memoria):
    t = memoria.get("Cuadro 2")
    assert t.pages == [2]
    assert len(t.rows) == 5
    assert t.rows[-1] == ["Total gastos operativos", 28500.0, 30100.0, 33400.0, 37900.0, 41600.0]


def test_memoria_sin_salteados(memoria):
    assert [t.caption for t in memoria.tables] == ["Cuadro 1", "Cuadro 3", "Cuadro 2"]
    assert memoria.skipped == []


def test_anuario_formatos(anuario):
    assert anuario.get("Cuadro 1.1").rows[0] == ["Capital", 7.2, 10.8, 9.1, 7.9, 7.4]
    assert anuario.get("Cuadro 2.1").rows[0] == ["Capital", 4812.3, 4861.0, 4905.7]
    assert anuario.get("Cuadro 3.1").rows[1] == ["Litoral", 5980.1, 6402.7, 6118.4]


def test_tablas_con_mismo_encabezado_y_rotulo_propio_no_se_unen(anuario):
    poblacion, export = anuario.get("Cuadro 2.1"), anuario.get("Cuadro 3.1")
    assert (poblacion.pages, len(poblacion.rows)) == ([1], 5)
    assert (export.pages, len(export.rows)) == ([2], 5)


def test_tabla_imagen_se_informa_como_salteada(anuario):
    assert [t.caption for t in anuario.tables] == ["Cuadro 1.1", "Cuadro 2.1", "Cuadro 3.1"]
    assert len(anuario.skipped) == 1
    s = anuario.skipped[0]
    assert (s.caption, s.page) == ("Cuadro 4.1", 2)
    assert "imagen" in s.reason
