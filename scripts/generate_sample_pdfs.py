"""Genera los PDFs de ejemplo del TP (datos 100% ficticios).

Uso:
    python scripts/generate_sample_pdfs.py

Salida:
    data/sample_pdfs/memoria_andina_tech_2024.pdf
    data/sample_pdfs/anuario_valdoria_2023.pdf
"""
from __future__ import annotations

import io
import random
from pathlib import Path

from PIL import Image as PILImage, ImageDraw
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

OUT = Path(__file__).resolve().parent.parent / "data" / "sample_pdfs"

styles = getSampleStyleSheet()
H1 = styles["Title"]
H2 = styles["Heading2"]
BODY = styles["BodyText"]
CAPTION = ParagraphStyle("caption", parent=BODY, fontName="Helvetica-Bold", fontSize=10)
NOTE = ParagraphStyle("note", parent=BODY, fontSize=8, textColor=colors.grey)

GRID = TableStyle(
    [
        ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#DDDDDD")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
    ]
)


# ---------------------------------------------------------------- formato es-AR
def fmt(n: float, dec: int = 0, money: bool = False, pct: bool = False) -> str:
    """1234.5 -> '1.234,5'; negativos entre paréntesis."""
    s = f"{abs(n):,.{dec}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    if money:
        s = f"$ {s}"
    if pct:
        s = f"{s} %"
    return f"({s})" if n < 0 else s


# ===================================================================== DATOS PDF 1
YEARS = [2020, 2021, 2022, 2023, 2024]
INGRESOS = [85_400, 92_150, 104_780, 118_300, 131_920]
COSTO = [-41_200, -44_900, -50_300, -56_100, -61_800]
GASTOS_OP = [-28_500, -30_100, -33_400, -37_900, -41_600]
RES_FIN = [-17_900, -6_300, -4_100, -3_200, -2_700]
IMPUESTOS = [0, -3_700, -5_900, -7_300, -8_900]

GASTOS_CAT = {
    "Sueldos de administración": [12_000, 12_600, 13_400, 14_500, 15_600],
    "Comercialización": [7_300, 7_900, 8_700, 9_800, 10_400],
    "Investigación y desarrollo (I+D)": [6_200, 6_700, 8_100, 10_300, 12_100],
    "Otros gastos": [3_000, 2_900, 3_200, 3_300, 3_500],
}
for i in range(5):  # consistencia con el estado de resultados
    assert sum(v[i] for v in GASTOS_CAT.values()) == -GASTOS_OP[i]

MESES = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio",
         "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
REGIONES_AT = ["Norte", "Centro", "Sur"]


def ventas_mensuales() -> dict[int, list[list[int]]]:
    """Ventas mensuales por región que suman exactamente los ingresos anuales."""
    rng = random.Random(42)
    share = {"Norte": 0.28, "Centro": 0.50, "Sur": 0.22}
    out = {}
    for year, total in ((2023, INGRESOS[3]), (2024, INGRESOS[4])):
        rows = []
        for m in range(12):
            season = 1 + 0.15 * (m in (10, 11)) - 0.08 * (m in (0, 1))
            rows.append([round(total / 12 * share[r] * season * rng.uniform(0.92, 1.08))
                         for r in REGIONES_AT])
        diff = total - sum(map(sum, rows))
        rows[11][1] += diff  # el residuo va a Diciembre/Centro
        out[year] = rows
    return out


VENTAS = ventas_mensuales()

# ===================================================================== DATOS PDF 2
REG_V = ["Capital", "Litoral", "Montaña", "Desierto", "Austral"]
DESEMPLEO = {  # % 2019..2023
    "Capital": [7.2, 10.8, 9.1, 7.9, 7.4],
    "Litoral": [8.5, 12.1, 10.4, 9.2, 8.8],
    "Montaña": [6.1, 8.9, 7.7, 6.8, 6.5],
    "Desierto": [9.8, 13.4, 12.0, 11.1, 10.6],
    "Austral": [5.4, 7.6, 6.9, 6.2, 5.9],
}
POBLACION = {  # miles de habitantes 2021..2023
    "Capital": [4_812.3, 4_861.0, 4_905.7],
    "Litoral": [2_104.6, 2_121.9, 2_140.2],
    "Montaña": [1_388.1, 1_392.4, 1_397.0],
    "Desierto": [  612.9,   618.2,   624.8],
    "Austral": [  341.7,   345.3,   349.1],
}
EXPORT = {  # millones de USD 2021..2023
    "Capital": [3_420.5, 3_610.2, 3_755.8],
    "Litoral": [5_980.1, 6_402.7, 6_118.4],
    "Montaña": [2_215.0, 2_480.6, 2_691.3],
    "Desierto": [1_874.2, 2_103.9, 2_366.5],
    "Austral": [  954.8, 1_012.3, 1_098.7],
}


# ======================================================================= helpers
def table(data, style=GRID, col_widths=None, repeat=0, extra=None):
    t = Table(data, colWidths=col_widths, repeatRows=repeat)
    st = TableStyle(style.getCommands() + (extra or []))
    t.setStyle(st)
    return t


def image_table() -> Image:
    """Tabla rasterizada (imagen) para probar el 'saltear e informar'."""
    rows = [["Indicador", "2021", "2022", "2023"],
            ["Viviendas con agua de red (%)", "88,1", "89,4", "90,2"],
            ["Viviendas con gas natural (%)", "61,3", "62,0", "63,5"],
            ["Hogares con internet fijo (%)", "54,7", "58,9", "63,1"]]
    w, h, cw, rh = 900, 200, [420, 160, 160, 160], 50
    img = PILImage.new("RGB", (w, h), "white")
    d = ImageDraw.Draw(img)
    for r, row in enumerate(rows):
        x = 0
        for c, cell in enumerate(row):
            d.rectangle([x, r * rh, x + cw[c], (r + 1) * rh], outline="black",
                        fill="#DDDDDD" if r == 0 else "white")
            d.text((x + 10, r * rh + 18), cell, fill="black")
            x += cw[c]
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return Image(buf, width=16 * cm, height=16 * cm * h / w)


# ========================================================================= PDF 1
def build_memoria(path: Path) -> None:
    s = []
    s += [Paragraph("Andina Tech S.A. — Memoria Anual 2024", H1),
          Paragraph("Documento ficticio generado para fines académicos.", NOTE),
          Spacer(1, 12),
          Paragraph("1. Desempeño económico", H2),
          Paragraph(
              "Durante el ejercicio 2024 la compañía consolidó su crecimiento. "
              "El siguiente cuadro resume el estado de resultados de los últimos "
              "cinco ejercicios fiscales, expresado en miles de pesos nominales "
              "(sin ajuste por inflación).", BODY),
          Spacer(1, 6),
          Paragraph("Cuadro 1. Estado de resultados consolidado 2020–2024", CAPTION)]

    bruto = [a + b for a, b in zip(INGRESOS, COSTO)]
    oper = [a + b for a, b in zip(bruto, GASTOS_OP)]
    antes = [a + b for a, b in zip(oper, RES_FIN)]
    neto = [a + b for a, b in zip(antes, IMPUESTOS)]
    rows = [
        ("Ingresos por ventas", INGRESOS), ("Costo de ventas", COSTO),
        ("Resultado bruto", bruto), ("Gastos operativos", GASTOS_OP),
        ("Resultado operativo", oper), ("Resultado financiero", RES_FIN),
        ("Resultado antes de impuestos", antes),
        ("Impuesto a las ganancias", IMPUESTOS), ("Resultado neto", neto),
    ]
    # encabezado de dos filas con celda combinada
    data = [["Concepto", "Ejercicio fiscal (miles de $)", "", "", "", ""],
            ["", *map(str, YEARS)]]
    data += [[name, *[fmt(v, money=True) for v in vals]] for name, vals in rows]
    s.append(table(data, col_widths=[5.5 * cm] + [2.3 * cm] * 5, extra=[
        ("SPAN", (1, 0), (5, 0)), ("SPAN", (0, 0), (0, 1)),
        ("ALIGN", (1, 0), (5, 0), "CENTER"),
        ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor("#DDDDDD")),
        ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
    ]))
    s += [Paragraph("Nota: los valores negativos se presentan entre paréntesis. "
                    "El resultado financiero de 2020 incluye pérdidas extraordinarias "
                    "por diferencia de cambio.", NOTE),
          Spacer(1, 14),
          Paragraph("2. Ventas por región", H2),
          Paragraph(
              "La compañía opera en tres regiones comerciales: Norte, Centro y Sur. "
              "El cuadro siguiente detalla las ventas mensuales de 2023 y 2024 por "
              "región, en miles de pesos nominales. La suma anual coincide con los "
              "ingresos por ventas del Cuadro 1.", BODY),
          Spacer(1, 6),
          Paragraph("Cuadro 3. Ventas mensuales por región 2023–2024", CAPTION)]

    data = [["Año", "Mes", "Norte", "Centro", "Sur"]]
    for y in (2023, 2024):
        for m, vals in enumerate(VENTAS[y]):
            data.append([str(y), MESES[m], *[fmt(v) for v in vals]])
    # repeatRows=1 -> en la página siguiente se repite el encabezado
    s.append(table(data, col_widths=[2 * cm, 3.2 * cm, 3 * cm, 3 * cm, 3 * cm],
                   repeat=1, extra=[("ALIGN", (0, 0), (1, -1), "LEFT")]))
    s += [Paragraph("Fuente: sistema comercial interno. La región Centro incluye "
                    "las ventas online.", NOTE),
          Spacer(1, 14),
          Paragraph("3. Estructura de gastos", H2),
          Paragraph(
              "Los gastos operativos se desagregan en cuatro categorías. La inversión "
              "en investigación y desarrollo fue la que más creció en el período, "
              "en línea con la estrategia de producto de la compañía. Cifras en miles "
              "de pesos nominales.", BODY),
          Spacer(1, 6),
          Paragraph("Cuadro 2. Gastos operativos por categoría", CAPTION)]

    data = [["Categoría", *map(str, YEARS)]]
    data += [[k, *[fmt(x) for x in v]] for k, v in GASTOS_CAT.items()]
    data.append(["Total gastos operativos", *[fmt(-x) for x in GASTOS_OP]])
    s.append(table(data, col_widths=[5.5 * cm] + [2.3 * cm] * 5,
                   extra=[("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold")]))
    s += [Paragraph("Fuente: Gerencia de Administración y Finanzas.", NOTE),
          Spacer(1, 14),
          Paragraph("4. Perspectivas", H2),
          Paragraph("Para 2025 la dirección prevé continuar con la expansión en la "
                    "región Sur. Esta memoria no incluye proyecciones cuantitativas.",
                    BODY)]

    SimpleDocTemplate(str(path), pagesize=A4, title="Memoria Anual 2024 - Andina Tech",
                      topMargin=2 * cm, bottomMargin=2 * cm).build(s)


# ========================================================================= PDF 2
def build_anuario(path: Path) -> None:
    s = []
    s += [Paragraph("República de Valdoria — Anuario Estadístico 2023", H1),
          Paragraph("Instituto Nacional de Estadística (ficticio). Documento generado "
                    "para fines académicos.", NOTE),
          Spacer(1, 12),
          Paragraph("Capítulo 1. Mercado de trabajo", H2),
          Paragraph(
              "La tasa de desocupación se define como el porcentaje de personas "
              "desocupadas sobre la población económicamente activa de cada región. "
              "Los datos surgen de la Encuesta Regional de Hogares (cuarto trimestre "
              "de cada año). Este anuario publica solo los valores regionales.", BODY),
          Spacer(1, 6),
          Paragraph("Cuadro 1.1. Tasa de desocupación por región, 2019–2023", CAPTION)]
    data = [["Región", "2019", "2020", "2021", "2022", "2023"]]
    data += [[r, *[fmt(x, 1, pct=True) for x in v]] for r, v in DESEMPLEO.items()]
    s.append(table(data, col_widths=[4 * cm] + [2.4 * cm] * 5))
    s += [Paragraph("Nota: el aumento de 2020 refleja el impacto de la pandemia.", NOTE),
          Spacer(1, 14),
          Paragraph("Capítulo 2. Población", H2),
          Paragraph(
              "Las estimaciones de población a mitad de año se elaboran a partir del "
              "Censo 2020. Se presentan las estimaciones disponibles para el período "
              "2021–2023, en miles de habitantes.", BODY),
          Spacer(1, 6),
          Paragraph("Cuadro 2.1. Población estimada por región (miles de habitantes)",
                    CAPTION)]
    data = [["Región", "2021", "2022", "2023"]]
    data += [[r, *[fmt(x, 1) for x in v]] for r, v in POBLACION.items()]
    s.append(table(data, col_widths=[4 * cm] + [3 * cm] * 3))
    s += [Paragraph("Fuente: proyecciones demográficas del Instituto.", NOTE),
          PageBreak(),
          Paragraph("Capítulo 3. Comercio exterior", H2),
          Paragraph(
              "Las exportaciones se registran según la región de origen de la "
              "mercadería, valuadas FOB en millones de dólares estadounidenses "
              "corrientes.", BODY),
          Spacer(1, 6),
          Paragraph("Cuadro 3.1. Exportaciones por región de origen (millones de USD)",
                    CAPTION)]
    data = [["Región", "2021", "2022", "2023"]]
    data += [[r, *[fmt(x, 1, money=True).replace("$", "US$") for x in v]]
             for r, v in EXPORT.items()]
    s.append(table(data, col_widths=[4 * cm] + [3.2 * cm] * 3))
    s += [Paragraph("Fuente: Dirección de Aduanas.", NOTE),
          Spacer(1, 14),
          Paragraph("Capítulo 4. Vivienda", H2),
          Paragraph("El siguiente cuadro se incluye como imagen escaneada del informe "
                    "original de vivienda.", BODY),
          Spacer(1, 6),
          Paragraph("Cuadro 4.1. Indicadores de vivienda (imagen)", CAPTION),
          image_table(),
          Paragraph("Fuente: Encuesta de Condiciones de Vida.", NOTE)]

    SimpleDocTemplate(str(path), pagesize=A4, title="Anuario Estadistico 2023 - Valdoria",
                      topMargin=2 * cm, bottomMargin=2 * cm).build(s)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    build_memoria(OUT / "memoria_andina_tech_2024.pdf")
    build_anuario(OUT / "anuario_valdoria_2023.pdf")
    print("PDFs generados en", OUT)
