# QA multiagente sobre tablas en PDFs

Dos agentes en LangGraph sobre una UI de Streamlit:

1. **Agente de Ingesta:** recibe un PDF, extrae sus tablas, infiere sus metadatos (nombre, descripción, columnas, encabezados de fila) a partir del contexto con un LLM, y las indexa en Pinecone.
2. **Agente Analista:** recibe una pregunta, recupera y selecciona las tablas necesarias, escribe un programa Python que calcula la respuesta, lo ejecuta en un sandbox, se autocorrige si falla y responde con estado `answered` / `partial` / `cannot_answer`.

Todas las llamadas a LLM y embeddings pasan por el proxy LiteLLM de la universidad, y cada ejecución queda trazada en LangSmith.

**Video demo:** *link pendiente*

## Instalación

Requiere Python 3.11+ (probado con 3.12) y [uv](https://docs.astral.sh/uv/).

```bash
uv venv --python 3.12 .venv
source .venv/bin/activate
uv pip install -r requirements.txt
cp .env.example .env
```

Completar el `.env`:

| Variable | Uso |
|---|---|
| `LLM_SERVICE_URL`, `LLM_API_KEY` | URL y clave del proxy LiteLLM. También se aceptan los nombres del enunciado, `LITELLM_BASE_URL` y `LITELLM_API_KEY`. |
| `LLM_MODEL` | Modelo de chat (usamos `gpt-4.1`). |
| `EMBEDDING_MODEL` | Modelo de embeddings (`text-embedding-3-small`, dimensión 1536). |
| `PINECONE_API_KEY`, `PINECONE_INDEX_NAME` | Índice serverless, dimensión 1536, métrica cosine. |
| `LANGSMITH_TRACING=true`, `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT` | Trazas. |

## Ejecución

```bash
streamlit run app.py                                         # UI: subir, explorar, preguntar
python -m agents.ingestion data/sample_pdfs/*.pdf            # ingesta por línea de comandos
python -m agents.analyst "¿Cuánto crecieron las ventas de la región Sur en 2024?"
python scripts/run_eval.py                                   # corre las 11 preguntas de prueba
pytest                                                       # tests (sin llamadas reales)
```

Para regenerar los PDFs de ejemplo: `python scripts/generate_sample_pdfs.py`. El extractor y los tests dependen de estos PDFs.

## Estructura

```
app.py                  punto de entrada de Streamlit
ui/                     una pestaña por módulo (ingest_tab, explore_tab, ask_tab) + widgets
agents/ingestion/       grafo, nodos, prompts, schemas, validación, armado de registros
agents/analyst/         grafo, nodos, prompts, schemas, lógica determinística (estado)
services/               extracción de PDF, contexto, LLM, Pinecone, almacén de tablas, sandbox
data/sample_pdfs/       PDFs de la demo
data/preguntas_prueba.md  preguntas de prueba con estado y respuesta esperados
data/tables/            parquet generados por la ingesta (no versionado)
scripts/                generación de PDFs y evaluación
tests/                  pytest, con dobles del LLM, los embeddings y Pinecone
EVALUATION.md           informe de evaluación
```

## Arquitectura

```mermaid
flowchart LR
    UI[Streamlit] -->|PDF| ING[Agente de Ingesta]
    UI -->|pregunta| AN[Agente Analista]
    ING -->|upsert metadatos + embedding| PC[(Pinecone)]
    ING -->|parquet por table_id| TS[(data/tables)]
    AN -->|búsqueda| PC
    AN -->|carga de datos| TS
    AN -->|código| SB[Sandbox: subproceso aislado]
    ING & AN -.->|LLM / embeddings| LL[Proxy LiteLLM]
    ING & AN -.->|trazas| LS[LangSmith]
```

### Grafo de ingesta

```mermaid
graph TD;
    __start__([inicio]) --> load_pdf
    load_pdf --> extract_tables
    extract_tables --> collect_context
    collect_context --> enrich
    enrich --> validate
    validate -. "errores y quedan intentos (con feedback)" .-> enrich
    validate -. "todo válido o sin intentos" .-> index
    index --> __end__([fin])
```

| Nodo | Qué hace |
|---|---|
| `load_pdf` | Abre el PDF y conserva el texto de cada página. |
| `extract_tables` | `services/pdf_extract.py`, **sin LLM**: `find_tables()`, aplana encabezados de dos filas, une tablas multipágina, convierte números es-AR (`($ 41.200)`, `7,2 %`, `US$ 3.420,5`, `4.812,3`) a `float`, deja las celdas vacías como nulos e informa en `skipped` las tablas que no se pueden leer (p. ej. una imagen). |
| `collect_context` | Para cada tabla: título de sección, párrafo y rótulo de arriba; nota o fuente de abajo (en una tabla multipágina, la de la última página). |
| `enrich` | `with_structured_output(TableMetadata)`: nombre, descripción de 2–4 oraciones, unidad, período, columnas (descripción, tipo, unidad) y encabezados de fila. Las tablas van en lote; en un reintento solo vuelven las que fallaron, con el error de validación en el prompt. |
| `validate` | Código puro: misma cantidad de columnas, cada nombre existe en el DataFrame, ninguna columna sin cubrir, y los encabezados de fila existen y no se repiten. Hasta 3 intentos; si se agotan, la tabla se saltea y se informa (nunca se indexan metadatos inválidos). |
| `index` | `table_id` = sha1 de archivo, página inicial e índice de la tabla. Guarda `data/tables/{table_id}.parquet`, embebe nombre + descripción + columnas + encabezados de fila y hace upsert con los metadatos, `source` (archivo y páginas) y una vista previa de 5 filas. Borra los vectores de una ingesta anterior del mismo archivo que ya no corresponden. |

### Grafo del Analista

```mermaid
graph TD;
    __start__([inicio]) --> understand
    understand --> retrieve
    retrieve --> select
    select -. "cannot_answer" .-> answer
    select -. "alguna parte respondible" .-> codegen
    codegen --> execute
    execute -. "error y quedan intentos (con stderr)" .-> codegen
    execute -. "OK o sin intentos" .-> answer
    answer --> __end__([fin])
```

| Nodo | Qué hace |
|---|---|
| `understand` | Salida estructurada `QueryPlan`: entidades, métricas, períodos, operaciones, consulta reescrita para la búsqueda y **partes** de la pregunta (p. ej. "qué región" / "por cuánto superó al promedio nacional"). |
| `retrieve` | Embedding de la consulta reescrita y top-k = 5 en Pinecone. |
| `select` | El LLM decide, por parte, si es respondible y con qué tablas, columnas y filas (`Selection`), siguiendo las reglas de respondibilidad del enunciado con ejemplos negativos. Después, **`check_selection` verifica en código contra el parquet** que esas columnas y filas existan: si el LLM pide la columna `2020` y la tabla cubre 2021–2023, la parte pasa a no respondible. El **estado se calcula en código**: todas respondibles → `answered`; algunas → `partial`; ninguna → `cannot_answer`. |
| `codegen` | Salida estructurada `GeneratedCode`. El prompt lleva los nombres exactos de columnas, dtypes y las primeras filas de cada tabla, la lista de partes a calcular y la de partes que **no** debe calcular. En un reintento recibe el código anterior y el error. |
| `execute` | Corre el código en el sandbox, parsea la última línea JSON del stdout y la valida (están todas las partes, sin NaN). Si el código informa un dato faltante en una parte, esa parte baja de estado. Si se agotan los intentos (3), las partes pendientes quedan como no respondibles. |
| `answer` | Redacta la respuesta con los resultados, las tablas y páginas usadas y el cálculo. No cambia el estado; en `cannot_answer` explica qué falta y qué cubre la tabla relacionada, sin números. |

El estado del grafo (`status`, `missing_data`, `selection`, `code`, `code_attempts`, `exec_stdout`, etc.) se puede testear: ver `tests/test_analyst.py`.

## Decisiones de diseño

- **Extracción con PyMuPDF.** No necesita Java ni Ghostscript, y da a la vez las tablas (`find_tables()`) y los bloques de texto con sus coordenadas, que se usan para el contexto. La extracción es determinística: el LLM solo interviene en el enriquecimiento.
- **Unión de tablas multipágina.** Una tabla se une con la anterior si es la primera de su página, la anterior terminó en la página previa, tienen la misma cantidad de columnas, el encabezado se repite o falta, y **no tiene rótulo propio** ("Cuadro N"). La condición del rótulo evita unir tablas distintas con el mismo encabezado en páginas consecutivas (en el anuario, los Cuadros 2.1 y 3.1 tienen ambos `Región, 2021, 2022, 2023`).
- **Números.** Se asume formato es-AR (punto de miles y coma decimal). Una columna se convierte a número solo si todos sus valores son numéricos; las columnas de años (`Año`) quedan como texto porque son una dimensión.
- **Almacén de tablas: un parquet por `table_id`** en `data/tables/`. Los metadatos de Pinecone tienen un límite de unos 40 KB por registro, así que los datos completos no van ahí: Pinecone guarda los metadatos, una vista previa de 5 filas y la ruta del parquet. Parquet conserva los tipos (float / texto) que deja el extractor.
- **Embeddings: un vector por tabla**, armado con nombre + descripción + unidad + período + columnas (con descripción y unidad) + encabezados de fila. No se hace chunking: una tabla es la unidad de recuperación y su descripción entra holgada en un embedding.
- **Idempotencia.** El `table_id` es determinístico, así que reingerir el mismo PDF sobrescribe los mismos registros. Si una tabla desaparece entre ingestas, se borra su vector: se buscan los ids del archivo con una consulta filtrada por metadatos, porque Pinecone serverless no borra por filtro.
- **El estado de respondibilidad lo decide el código.** El LLM propone la selección, pero el estado sale de `compute_status` sobre la selección ya verificada contra los datos, y puede bajar después de la ejecución. La redacción final no lo cambia.
- **Sandbox** (`services/sandbox.py`):
  - **Proceso aislado:** subproceso aparte (`python -I`), con timeout de 20 s y límite de CPU.
  - **Directorio y entorno:** corre en un directorio temporal que solo contiene los parquet seleccionados, y con un entorno vacío, así que no ve las API keys.
  - **Audit hook (PEP 578):** bloquea red, creación de procesos, `ctypes` y la lectura o escritura de archivos fuera del directorio de trabajo y de la instalación de Python.
  - **Tests:** hay tests para cada caso.
- **Nombres de variables del proxy.** Se usan los nombres del proxy de la materia (`LLM_SERVICE_URL`, `LLM_API_KEY`) y también se aceptan los del enunciado.
- **Inyección de dependencias.** Los nodos reciben el LLM, los embeddings y el índice por `IngestionDeps` y `AnalystDeps`. Así los tests usan dobles y no gastan presupuesto del proxy.

## Observabilidad

Con `LANGSMITH_TRACING=true`, cada ejecución se registra con:

- **Nombre:** `ingesta:<archivo>` o `analista: <pregunta>`.
- **Tags:** `ingestion` o `analyst`.
- **Metadatos:** el archivo o la pregunta.

Cada nodo del grafo es un span, y adentro se ven las llamadas al LLM con sus prompts y salidas estructuradas. Hay tres trazas representativas en [EVALUATION.md](EVALUATION.md).

## Evaluación

Las 11 preguntas de [`data/preguntas_prueba.md`](data/preguntas_prueba.md) dan bien en la corrida final (11 de 11). El informe completo, con el historial de corridas que fallaron, está en [EVALUATION.md](EVALUATION.md).

## Limitaciones conocidas

- **Continuaciones rotuladas.** Si un PDF rotula también la continuación ("Cuadro 3 (cont.)"), la segunda parte tiene rótulo propio y **no se une**. Habría que reconocer el sufijo "(cont.)" o comparar el número de cuadro con el de la tabla anterior.
- **Formato de los rótulos.** Se detectan con el patrón `Cuadro N.`; otros formatos ("Tabla 3") no se asocian. Una tabla sin rótulo se indexa igual, con el nombre que infiere el LLM.
- **Detección de tablas.** Depende de `find_tables()`: funciona bien con tablas con bordes; las tablas sin líneas o con diseños complejos pueden detectarse mal.
- **Sin OCR.** Las tablas en imagen se saltean y se informan.
- **Formato numérico.** Se asume es-AR; un PDF con formato en-US (`1,234.5`) se convertiría mal.
- **El sandbox no es un contenedor.** Las extensiones nativas (p. ej. pyarrow) pueden abrir archivos sin pasar por el audit hook. Para producción haría falta un contenedor o un microVM sin red.
- **Recuperación.** El top-k es fijo (5) y no hay reranking. Con muchos PDFs indexados, una pregunta multitabla podría no recuperar todas las tablas necesarias.
- **No determinismo del LLM.** Aun con temperatura 0, la selección y el código pueden variar entre corridas (ver [EVALUATION.md](EVALUATION.md)).

## Créditos

El código se escribió con asistencia de IA (Cursor). Los PDFs de ejemplo son ficticios y se generan con `scripts/generate_sample_pdfs.py` (reportlab).
