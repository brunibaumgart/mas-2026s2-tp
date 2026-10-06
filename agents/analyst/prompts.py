"""Prompts del Analista."""
import json

import pandas as pd

from agents.analyst.schemas import PartSelection, QueryPlan

PREVIEW_ROWS = 8

UNDERSTAND_SYSTEM = """Analizás preguntas sobre datos que están en tablas de informes en PDF \
(estados contables, anuarios estadísticos).

- Identificá entidades, métricas, períodos y operaciones.
- Reescribí la consulta para buscar tablas por similitud semántica.
- Separá la pregunta en partes si pide cosas distintas. Ejemplo: "¿Qué región tuvo la tasa \
más alta en 2023 y por cuánto superó al promedio nacional?" → p1 "¿Qué región tuvo la tasa \
más alta en 2023 y cuál fue?", p2 "¿Por cuánto superó esa tasa al promedio nacional de 2023?".
- Si la pregunta pide una sola cosa (aunque sea para varios años), usá una sola parte.
- Puede haber conversación previa. Si la pregunta nueva depende de ella ("¿y en 2023?", \
"¿y para esa región?", "¿cuánto es eso en porcentaje?"), escribí en standalone_question la \
pregunta completa, tomando de la conversación solo lo necesario (métrica, entidad, período). \
Si no depende, copiala tal cual. La consulta reescrita y las partes se arman sobre la pregunta \
autocontenida. Nunca copies números de respuestas anteriores a la pregunta."""

SELECT_SYSTEM = """Decidís qué tablas hacen falta para responder cada parte de una pregunta. \
Solo podés usar las tablas candidatas: nunca conocimiento general, fuentes externas ni \
estimaciones.

Una parte es respondible (answerable=true) solo si TODOS los valores que necesita el cálculo \
están en las tablas candidatas. Marcala como NO respondible si:
- Falta un período o una entidad. Ej.: piden 2020 y la tabla cubre 2021–2023. No uses el año \
más cercano, no interpoles ni extrapoles.
- Necesita una conversión con datos externos: tipo de cambio (USD → pesos), ajuste por \
inflación, o una cifra per cápita sin una tabla de población.
- Falta un valor de comparación. Ej.: "promedio nacional" cuando ninguna tabla lo publica. NO \
lo reemplaces por el promedio de las regiones listadas, salvo que la pregunta lo defina así.
- La unidad o el significado de una columna es ambiguo y la elección cambia el resultado.
- Ninguna tabla trata el tema de la pregunta.

Conversiones permitidas (anotalas en `conversions`): cambio de escala (miles → millones), \
porcentaje ↔ fracción, sumar los meses para obtener un año cuando están todos, y combinar \
tablas que comparten entidades y período (p. ej. exportaciones / población). En cocientes \
como el per cápita, indicá que ambas magnitudes se pasan a unidades y que el resultado va en \
unidades simples (p. ej. "USD por habitante").

En `tables` copiá exactamente el table_id, los nombres de columna y las etiquetas de fila de \
los metadatos. Si una parte necesita varias tablas, listalas todas.
En `missing` explicá qué falta y qué cubre la tabla relacionada, si existe. Ej.: "La tabla \
'Exportaciones por región' cubre 2021–2023; 2020 no está disponible"."""

CODEGEN_SYSTEM = """Escribís un programa Python autocontenido que calcula la respuesta a \
partes de una pregunta usando tablas de datos.

- Cargá cada tabla con pandas.read_parquet('<archivo>') desde el directorio actual. Son los \
únicos archivos disponibles y no hay acceso a la red.
- Usá los nombres EXACTOS de columnas y etiquetas de fila indicados. Los nombres de columna \
de años son strings ('2023'), no enteros.
- Calculá SOLO las partes listadas en "Partes a calcular". La pregunta original es contexto: \
no calcules las partes marcadas como no respondibles ni las reemplaces por aproximaciones \
(p. ej. no calcules un "promedio nacional" promediando regiones).
- Calculá todo a partir de los DataFrames: no copies números del enunciado ni inventes datos.
- Cocientes entre magnitudes con distinta escala (per cápita, X por Y): pasá ambas a \
unidades antes de dividir (millones ×1e6, miles ×1e3) y expresá el resultado en unidades \
simples. Ej.: 500 (millones de $) / 250 (miles de habitantes) → 500e6 / 250e3 = 2000 \
"$ por habitante" (nunca "miles de $ por habitante"). Informá el cambio de escala en la \
explicación. Esta regla tiene prioridad sobre las conversiones sugeridas.
- Si el resultado es una sola magnitud de una tabla (un total, un máximo), mantené la \
unidad de la tabla (p. ej. "miles de $").
- Librerías disponibles: pandas, numpy, json, math y la biblioteca estándar.
- Si al calcular descubrís que falta un dato, poné "result": null y "missing": "<qué falta>" \
en esa parte.
- Si la pregunta pide una proporción o un porcentaje, devolvé porcentajes (21.75, no 0.2175) \
con unit "%".
- La ÚLTIMA línea impresa tiene que ser un único JSON en una sola línea:
  print(json.dumps({"parts": [{"part_id": "p1", "result": ..., "unit": "...", \
"explanation": "...", "cells": [...]}]}, ensure_ascii=False))
  - result: número, string o un dict/list chico con los valores, redondeados a 2 decimales.
  - unit: unidad del resultado (p. ej. "%", "miles de $", "USD por habitante").
  - explanation: una oración con el cálculo y las conversiones realizadas.
  - cells: TODAS las celdas de las tablas que usó el cálculo, para poder verificarlas. Cada una \
es {"table": "<archivo>.parquet", "row": <etiqueta de fila>, "column": "<columna>", \
"value": <valor>}. "row" es la etiqueta de la fila tal como está en la tabla, o una lista de \
etiquetas si la fila se identifica con más de una columna (p. ej. ["2023", "Diciembre"]). \
"value" es el valor original de la celda, sin redondear ni convertir. Armá la lista en el \
código a partir del DataFrame (no la escribas a mano); si usaste una columna entera, citá \
todas sus celdas.
- Convertí los tipos de numpy a float/int/str de Python antes de json.dumps.
- Gráfico: si el resultado de alguna parte es una serie (varios años, meses, regiones o \
categorías), guardá además un gráfico simple con matplotlib: import matplotlib.pyplot as \
plt; ...; plt.title('<qué muestra> (<unidad>)'); plt.savefig('chart.png', dpi=120, \
bbox_inches='tight'). Un solo gráfico, sin plt.show(). Si todos los resultados son un único \
número, no hagas gráfico."""

VERIFY_SYSTEM = """Sos un verificador. No resolvés la pregunta: revisás si un programa que ya \
se ejecutó calcula lo que pide cada parte respetando las reglas. Revisá solo las partes \
listadas en "Partes a calcular".

Reportá una violación SOLO si es clara y concreta:
- kind "calculo" (se corrige reescribiendo el código): calcula otra cosa que la que pide la \
parte; usa filas, columnas o años distintos de los pedidos; aproxima un dato que falta \
(promediar las regiones para obtener un "promedio nacional", usar el año más cercano, \
interpolar o extrapolar); usa números escritos a mano en lugar de valores de las tablas; hace \
una conversión que necesita datos externos (tipo de cambio, inflación); o calcula una parte \
marcada como NO respondible.
- kind "dato_faltante" (no se puede corregir): la parte necesita un dato que no está en \
ninguna de las tablas disponibles.

No reportes estilo, redondeo, nombres de variables, formato del JSON ni conversiones \
permitidas (cambio de escala, % ↔ fracción, sumar meses cuando están todos, combinar tablas \
con las mismas entidades y período). Si todo está bien, devolvé ok=true y violations vacío."""

ANSWER_SYSTEM = """Redactás la respuesta final para el usuario, en español, a partir de \
resultados ya calculados. No calcules nada nuevo ni uses conocimiento externo.

- El estado ya está decidido y no lo cambiás.
- answered: dá los resultados con su unidad.
- partial: respondé las partes calculadas y, para cada parte que no se puede responder, \
explicá qué dato falta, sin dar ningún número para esa parte (aunque aparezca en otra \
explicación).
- cannot_answer: NO muestres ningún resultado numérico. Explicá qué falta y, si hay una tabla \
relacionada, qué cubre (nombre y período).
- Indicá qué tablas (y páginas) se usaron y explicá brevemente el cálculo y las conversiones.
- Sé breve: como máximo unas 8 líneas."""


def _json(data) -> str:
    return json.dumps(data, ensure_ascii=False, indent=1)


def candidate_summary(md: dict) -> dict:
    keys = (
        "table_id", "name", "description", "source", "unit", "period",
        "columns", "column_descriptions", "row_headers", "preview",
    )
    return {k: md[k] for k in keys if k in md}


def plan_text(plan: QueryPlan) -> str:
    return "\n".join(f"- {p.id}: {p.question}" for p in plan.parts)


def select_user_prompt(question: str, plan: QueryPlan, candidates: list[dict]) -> str:
    return (
        f"Pregunta: {question}\n\nPartes:\n{plan_text(plan)}\n\n"
        f"Tablas candidatas:\n{_json([candidate_summary(c) for c in candidates])}"
    )


def table_block(file: str, md: dict, df: pd.DataFrame) -> str:
    dtypes = {str(c): str(t) for c, t in df.dtypes.items()}
    return "\n".join([
        f"Archivo: {file}",
        f"Nombre: {md.get('name')} ({md.get('source')})",
        f"Unidad: {md.get('unit')}",
        f"Descripción: {md.get('description')}",
        f"Columnas y dtypes: {_json(dtypes)}",
        f"Filas: {len(df)}",
        f"Primeras {PREVIEW_ROWS} filas:\n{df.head(PREVIEW_ROWS).to_string(index=False)}",
    ])


def codegen_user_prompt(
    question: str,
    plan: QueryPlan,
    selection: list[PartSelection],
    tables: list[str],
    previous_code: str | None = None,
    error: str | None = None,
) -> str:
    questions = {p.id: p.question for p in plan.parts}
    part_lines = []
    for s in (s for s in selection if s.answerable):
        uses = "; ".join(
            f"{u.table_id}.parquet columnas={u.columns} filas={u.row_labels or 'todas'}"
            for u in s.tables
        )
        line = f"- {s.part_id}: {questions.get(s.part_id, '')}\n  Datos: {uses}"
        if s.conversions:
            line += f"\n  Conversiones a informar: {s.conversions}"
        part_lines.append(line)
    skipped = [
        f"- {questions.get(s.part_id, s.part_id)} (falta: {s.missing})"
        for s in selection
        if not s.answerable
    ]
    text = f"Pregunta original (contexto): {question}\n\nPartes a calcular:\n" + "\n".join(part_lines)
    if skipped:
        text += "\n\nPartes NO respondibles (no las calcules ni las aproximes):\n" + "\n".join(skipped)
    text += "\n\nTablas:\n\n" + "\n\n".join(tables)
    if previous_code and error:
        text += (
            f"\n\nTu programa anterior falló. Corregilo.\n\nCódigo anterior:\n{previous_code}\n\n"
            f"Error:\n{error}"
        )
    return text


def answer_user_prompt(
    question: str,
    status: str,
    plan: QueryPlan,
    selection: list[PartSelection],
    result: dict | None,
    used_tables: list[dict],
    candidates: list[dict],
) -> str:
    questions = {p.id: p.question for p in plan.parts}
    outputs = {e.get("part_id"): e for e in (result or {}).get("parts", [])}
    parts = []
    for s in selection:
        item = {"parte": questions.get(s.part_id, s.part_id)}
        if s.answerable and s.part_id in outputs:
            out = outputs[s.part_id]
            item |= {k: out.get(k) for k in ("result", "unit", "explanation")}
            if s.conversions:
                item["conversiones"] = s.conversions
        else:
            item["falta"] = s.missing
        parts.append(item)
    used = [{"nombre": t.get("name"), "fuente": t.get("source")} for t in used_tables]
    related = [
        {"nombre": c.get("name"), "periodo": c.get("period"), "fuente": c.get("source")}
        for c in candidates[:3]
    ]
    text = (
        f"Pregunta: {question}\nEstado: {status}\n\nPartes:\n{_json(parts)}\n\n"
        f"Tablas usadas:\n{_json(used)}"
    )
    if status != "answered":
        text += f"\n\nTablas relacionadas encontradas:\n{_json(related)}"
    return text


def understand_user_prompt(question: str, history: list[dict]) -> str:
    if not history:
        return question
    turns = "\n".join(
        f"- Pregunta: {h.get('question')}\n  Interpretada como: {h.get('standalone')}\n"
        f"  Tablas usadas: {', '.join(h.get('tables') or []) or 'ninguna'}\n"
        f"  Estado: {h.get('status')}"
        for h in history
    )
    return f"Conversación previa (la más reciente al final):\n{turns}\n\nPregunta nueva: {question}"


def verify_user_prompt(
    question: str,
    plan: QueryPlan,
    selection: list[PartSelection],
    tables: list[str],
    code: str,
    result: dict,
) -> str:
    questions = {p.id: p.question for p in plan.parts}
    to_check = [
        f"- {s.part_id}: {questions.get(s.part_id, '')}"
        + (f" (conversiones permitidas: {s.conversions})" if s.conversions else "")
        for s in selection
        if s.answerable
    ]
    skipped = [
        f"- {s.part_id}: {questions.get(s.part_id, '')} (falta: {s.missing})"
        for s in selection
        if not s.answerable
    ]
    slim = {
        "parts": [
            {k: v for k, v in e.items() if k != "cells"}
            for e in (result or {}).get("parts", [])
            if isinstance(e, dict)
        ]
    }
    text = f"Pregunta: {question}\n\nPartes a calcular:\n" + "\n".join(to_check)
    if skipped:
        text += "\n\nPartes NO respondibles (no se deben calcular):\n" + "\n".join(skipped)
    text += "\n\nTablas disponibles:\n\n" + "\n\n".join(tables)
    text += f"\n\nCódigo ejecutado:\n{code}\n\nResultado (JSON, sin las celdas citadas):\n{_json(slim)}"
    return text
