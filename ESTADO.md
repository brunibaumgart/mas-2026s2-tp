# Estado del TP — QA multiagente sobre tablas en PDFs

> Resumen para retomar el trabajo. Estado al **martes 6/10/2026, noche**.
> Entrega: **miércoles 7/10/2026** — link al repo + SHA completo del commit (`git rev-parse HEAD`), con timestamp anterior a la fecha límite.
> Enunciado completo: [`consigna.md`](consigna.md).

## TL;DR

- Todo lo obligatorio está hecho. Repo en GitHub: `brunibaumgart/mas-2026s2-tp` (privado).
- Sobre eso se sumaron los **distintivos** (ver la sección del README): agente verificador, citas por celda verificadas en código, recuperación híbrida BM25 + RRF, memoria de la conversación, revisión humana con `interrupt`, gráfico, ruteo de modelos y evaluación por etapas repetida y en LangSmith.
- **99 tests** con `pytest`, sin llamadas reales (incluye smoke tests de la UI con `AppTest`).
- La evaluación real 11/11 es de la versión anterior a los distintivos: **hay que volver a correrla**.

## Qué falta (en orden)

1. **Correr la evaluación con los distintivos** contra el proxy real y pegar la tabla en `EVALUATION.md`:
   `python scripts/run_eval.py --repeats 3` (~165 llamadas, unos 6–8 min) y, si hay tiempo, `python scripts/langsmith_eval.py --repeats 3`.
   Si alguna pregunta empeora, anotarlo en el historial de corridas (es parte del reporte honesto).
2. **Probar la UI a mano:** una pregunta con gráfico (2), una repregunta ("¿y en 2023?"), una con la revisión humana activada.
3. **Trazas:** compartir en LangSmith las de las preguntas 3, 7 y 9 y pegar los links en `EVALUATION.md`.
4. **Video** (≤5 min): ingesta, Explorar, y preguntas 3 (multitabla con citas), 7 (`partial` + verificador), 9 (`cannot_answer`), más una repregunta y la revisión humana si entra. Link en `README.md`.
5. **Docentes** como colaboradores con lectura en GitHub.
6. Commit final, push y `git rev-parse HEAD` antes de la fecha límite.

## Cómo correrlo

```bash
cd ~/Desktop/itba/sm
source .venv/bin/activate
uv pip install -r requirements.txt          # suma matplotlib
streamlit run app.py
python -m agents.ingestion data/sample_pdfs/memoria_andina_tech_2024.pdf data/sample_pdfs/anuario_valdoria_2023.pdf
python -m agents.analyst "¿Qué región tuvo la tasa de desocupación más alta en 2023, y por cuánto superó al promedio nacional?"
python scripts/run_eval.py --repeats 3
pytest
```

- Agregar `LLM_MODEL_FAST=gpt-4.1-mini` al `.env` (opcional; si falta, usa `LLM_MODEL`).
- El índice de Pinecone ya tiene las 6 tablas. Si se clona el repo en otra máquina, hay que reingerir los PDFs (los parquet no se versionan).

## Configuración y trampas conocidas

- Python **3.12** en `.venv` creado con **uv** (no 3.14: `langchain-pinecone` no tiene versión compatible; no instalar uv con brew en macOS 14).
- Variables del proxy: `LLM_SERVICE_URL` / `LLM_API_KEY` (también acepta `LITELLM_BASE_URL` / `LITELLM_API_KEY`). URL sin `/v1`.
- Modelos: `gpt-4.1` (principal), `gpt-4.1-mini` (rápido) y `text-embedding-3-small` (dim 1536). Evitar Claude por el proxy (schemas) y `gpt-5*` (rechazan `temperature`).
- pandas 3: las columnas de texto tienen dtype `str`, no `object` (usar `pd.api.types.is_numeric_dtype`).
- El sandbox precarga pandas/numpy/pyarrow (y matplotlib si el código lo usa) antes del audit hook.
- El checkpointer de la UI es en memoria: reiniciar Streamlit borra las conversaciones.
- En zsh no pegar comandos con comentarios `#`.
