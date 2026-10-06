import json

from agents.ingestion.validation import MAX_LISTED_VALUES
from services.pdf_context import TableContext
from services.pdf_extract import Table
from services.table_store import text_values

PREVIEW_ROWS = 5

ENRICH_SYSTEM = """Documentás tablas extraídas de PDFs para que después se puedan encontrar \
por búsqueda semántica y analizar con código.

Reglas:
- Usá solo la información del rótulo, el contexto y las filas de muestra. No inventes datos.
- En `columns` devolvé exactamente una entrada por columna, en el mismo orden, con el nombre \
copiado carácter por carácter de la lista dada (no lo traduzcas, no lo completes, no le \
agregues unidades).
- La unidad sale del contexto (p. ej. "miles de pesos nominales"). Si no está, usá null. \
Si el contexto aclara si los montos son nominales o reales, incluilo en la unidad.
- En `row_headers` copiá tal cual los valores de la columna que identifica cada fila \
(conceptos, categorías, regiones). Si las filas se identifican por varias columnas \
(p. ej. año y mes), usá los valores de la más descriptiva sin repetir.
- La descripción tiene de 2 a 4 oraciones: qué mide, unidades, período y alcance.
- Escribí en español."""


def enrich_user_prompt(table: Table, context: TableContext, feedback: str | None = None) -> str:
    df = table.to_dataframe()
    preview = df.head(PREVIEW_ROWS).to_csv(index=False)
    parts = [
        f"Rótulo: {table.caption or '(sin rótulo)'}. {table.title or ''}".strip(),
        f"Páginas: {', '.join(map(str, table.pages))}",
    ]
    if table.header_group:
        parts.append(f"Encabezado agrupado sobre las columnas: {table.header_group}")
    parts += [
        f"Texto de arriba de la tabla:\n{context.above or '(vacío)'}",
        f"Texto de abajo de la tabla (nota/fuente):\n{context.below or '(vacío)'}",
        f"Columnas ({len(table.columns)}): {json.dumps(table.columns, ensure_ascii=False)}",
        f"Primeras {PREVIEW_ROWS} filas (CSV):\n{preview}",
        "Valores de las columnas de texto (candidatos a row_headers): "
        + json.dumps(text_values(df)[:MAX_LISTED_VALUES], ensure_ascii=False),
    ]
    if feedback:
        parts.append(
            f"Tu respuesta anterior no pasó la validación:\n{feedback}\n"
            "Corregila respetando exactamente la lista de columnas."
        )
    return "\n\n".join(parts)
