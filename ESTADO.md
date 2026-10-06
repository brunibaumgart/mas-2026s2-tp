# Estado del TP — QA multiagente sobre tablas en PDFs

> Resumen para retomar el trabajo (con o sin asistente). Estado al **martes 6/10/2026, 19:30**.
> Entrega: **miércoles 7/10/2026** — link al repo + SHA completo del commit (`git rev-parse HEAD`), con timestamp anterior a la fecha límite.
> Enunciado completo: [`consigna.md`](consigna.md).

## TL;DR

- Todo lo obligatorio que se resuelve con código está **hecho y probado** contra el proxy LiteLLM, Pinecone y el sandbox reales.
- **72 tests** con `pytest`; evaluación real **11/11** ([EVALUATION.md](EVALUATION.md)).
- **Falta (manual):** links/capturas de 3 trazas de LangSmith, video demo ≤5 min, crear el repo remoto, push y entregar el SHA.

## Checklist de la consigna (sección 8 y 9)

| Requisito | Estado | Dónde |
|---|:---:|---|
| Ingesta como grafo LangGraph con ciclo validación/reintento | ✅ | `agents/ingestion/` |
| Tablas de PDFs con capa de texto, multipágina unidas, metadatos inferidos del contexto | ✅ | `services/pdf_extract.py`, `services/pdf_context.py` |
| Metadatos (`table_id`, `name`, `description`, `columns`, `row_headers`, `source`) con Pydantic | ✅ | `agents/ingestion/schemas.py`, `records.py` |
| Embeddings en Pinecone + datos en almacén cargable (parquet) | ✅ | `services/vector_store.py`, `services/table_store.py` |
| Tablas ilegibles (imagen) salteadas e informadas en la UI | ✅ | `skipped` → `ui/ingest_tab.py` |
| Analista como grafo: recupera, selecciona (1+ tablas), genera código, ejecuta, se autocorrige | ✅ | `agents/analyst/` |
| Reglas de respondibilidad y estado `answered`/`partial`/`cannot_answer` decidido por código y guardado en el estado | ✅ | `agents/analyst/logic.py` |
| UI Streamlit: subir (con progreso), explorar, preguntar (chat), errores visibles | ✅ | `app.py`, `ui/` |
| Todas las llamadas por el proxy LiteLLM | ✅ | `services/llm.py` |
| Trazas en LangSmith con nombres, tags y metadatos | ✅ | `run_config()` en ambos `graph.py` |
| Secretos en `.env` + `.env.example` versionado | ✅ | `.gitignore` excluye `.env` |
| Código generado aislado, con timeout | ✅ | `services/sandbox.py` |
| Setup reproducible | ✅ | `requirements.txt`, README |
| Reingesta idempotente | ✅ | `table_id` determinístico + borrado de huérfanos |
| README con instalación, diagramas Mermaid, decisiones, limitaciones | ✅ | `README.md` |
| ≥2 PDFs (≥1 multipágina) + ≥8 preguntas con estado esperado | ✅ | `data/sample_pdfs/`, `data/preguntas_prueba.md` (11) |
| Informe de evaluación | ✅ | `EVALUATION.md` |
| **3 trazas de LangSmith (links o capturas)** | ❌ | Completar en `EVALUATION.md` (sección "Trazas representativas") |
| **Video demo ≤5 min (link en el README)** | ❌ | Completar "Video demo" en `README.md` |
| **Repo remoto + SHA** | ❌ | Hoy el repo es solo local (rama `master`, sin remoto) |

## Cómo correrlo

```bash
cd ~/Desktop/itba/sm
source .venv/bin/activate
streamlit run app.py
python -m agents.ingestion data/sample_pdfs/memoria_andina_tech_2024.pdf data/sample_pdfs/anuario_valdoria_2023.pdf
python -m agents.analyst "¿Qué región tuvo la tasa de desocupación más alta en 2023, y por cuánto superó al promedio nacional?"
python scripts/run_eval.py
pytest
```

- El índice de Pinecone ya tiene las 6 tablas de los dos PDFs (el Cuadro 4.1 es imagen y se saltea). Los parquet están en `data/tables/` (no versionado): si se clona el repo en otra máquina, hay que reingerir los PDFs.
- Una corrida completa de `run_eval.py` son ~50 llamadas al LLM (~2 min).

## Arquitectura en una pantalla

- **Ingesta:** `load_pdf → extract_tables → collect_context → enrich → validate → (enrich con feedback | index)`.
  - Extracción sin LLM (PyMuPDF `find_tables()`): aplana encabezados de dos filas, une tablas multipágina (misma cantidad de columnas, encabezado repetido o ausente, **sin rótulo propio**), convierte números es-AR a `float`.
  - `enrich` usa `with_structured_output(TableMetadata)`; `validate` es código puro (columnas y encabezados de fila contra el DataFrame), máx. 3 intentos.
  - `index`: `table_id = sha1(archivo|página|índice)`, parquet en `data/tables/{table_id}.parquet`, upsert con metadatos + preview de 5 filas.
- **Analista:** `understand → retrieve → select → (answer si cannot_answer | codegen → execute → (codegen con error | answer))`.
  - `understand` divide la pregunta en partes; `select` elige tablas por parte y `check_selection` verifica en código que columnas/filas existan (p. ej. pedir `2020` en una tabla 2021–2023 → no respondible).
  - Estado: todas las partes respondibles → `answered`; algunas → `partial`; ninguna → `cannot_answer`. Puede bajar después de ejecutar si el código informa un dato faltante.
  - Sandbox: subproceso `python -I`, timeout 20 s, límite de CPU, cwd temporal con solo los parquet, entorno sin secretos y audit hook que bloquea red, procesos y archivos fuera del directorio.
- **Tests:** dobles del LLM, embeddings y Pinecone en `tests/fakes.py` y `tests/test_analyst.py` (no gastan presupuesto).

## Datos de prueba

- `memoria_andina_tech_2024.pdf`: Cuadro 1 (estado de resultados 2020–2024, encabezado de dos filas), **Cuadro 3** (ventas mensuales por región, **multipágina**), Cuadro 2 (gastos por categoría). En el PDF el orden es 1, 3, 2.
- `anuario_valdoria_2023.pdf`: Cuadro 1.1 (desocupación, sin promedio nacional), 2.1 (población), 3.1 (exportaciones), 4.1 (imagen).
- Preguntas y respuestas esperadas: `data/preguntas_prueba.md`. Resultados y respuestas completas: `EVALUATION.md`, `data/eval_results.md`.

## Configuración y trampas conocidas

- Python **3.12** en `.venv` creado con **uv** (no 3.14: `langchain-pinecone` no tiene versión compatible; no instalar uv con brew en macOS 14).
- Variables del proxy: `LLM_SERVICE_URL` / `LLM_API_KEY` (también acepta `LITELLM_BASE_URL` / `LITELLM_API_KEY`). URL sin `/v1`.
- Modelos: `gpt-4.1` (chat) y `text-embedding-3-small` (dim 1536). Evitar Claude (schemas por el proxy) y `gpt-5*` (rechazan `temperature`).
- Pinecone: índice serverless `mas-2026s2-tables`, dim 1536, cosine, sin integrated embedding. Las stats tardan unos segundos en actualizarse.
- pandas 3: las columnas de texto tienen dtype `str`, no `object` (usar `pd.api.types.is_numeric_dtype`).
- El sandbox precarga pandas/numpy/pyarrow antes del audit hook porque cargan librerías nativas con `ctypes`.
- En zsh no pegar comandos con comentarios `#`.

## Próximos pasos sugeridos (en orden)

1. **Repo remoto:** crear un repo privado en GitHub (`gh repo create`), push de `master`, dar acceso de lectura al equipo docente.
2. **Trazas:** correr desde la UI las preguntas 3, 7 y 9 (o 1 si hay reintento), compartirlas en LangSmith (*Share*) y pegar los links en `EVALUATION.md`.
3. **Video:** ingesta de un PDF, pestaña Explorar, y 3 preguntas (sugeridas: 3 multitabla, 7 `partial`, 9 `cannot_answer`). Link en `README.md`.
4. Commit final y `git rev-parse HEAD` antes de la fecha límite.
5. **Bonus (opcional, si sobra tiempo):** gráfico generado por el Analista (que el código guarde un PNG en el directorio del sandbox y la UI lo muestre) o human-in-the-loop con `interrupt` antes de `codegen`.

## Forma de trabajar

- Respuestas en español rioplatense, concisas. Avanzar de a pasos verificables: implementar → test → probar contra el proxy real → commit (solo cuando se pide).
- Mantener el código simple: hay que poder explicarlo en un oral.
- Cuidar el presupuesto del proxy: usar los dobles de los tests y correr la evaluación completa solo cuando haga falta.
