# Informe de evaluación

## Cómo se evaluó

- **Datos:** los dos PDFs de `data/sample_pdfs/` (ficticios, generados con `scripts/generate_sample_pdfs.py`), ingeridos con el Agente de Ingesta: 6 tablas indexadas, el Cuadro 4.1 (imagen) salteado e informado.
- **Preguntas:** las 11 de [`data/preguntas_prueba.md`](data/preguntas_prueba.md), con estado y respuesta esperados escritos antes de correr el sistema (6 `answered`, 1 `partial`, 4 `cannot_answer`; 3 multitabla, 1 multipágina, 1 no relacionada).
- **Script:** `python scripts/run_eval.py` corre el grafo del Analista completo (proxy LiteLLM, Pinecone y sandbox reales) y compara:
  - **Estado:** `status` del estado del grafo contra el esperado (exacto).
  - **Valores:** los números del JSON que imprime el código generado contra los esperados (tolerancia 0,1 % relativa o 0,015 absoluta; se acepta fracción en lugar de porcentaje) y textos obligatorios ("Diciembre", "Desierto"). En `cannot_answer` se exige que no haya resultado numérico.
- **Modelo:** `gpt-4.1` (temperatura 0) y `text-embedding-3-small`, vía el proxy de la universidad.

> **Versiones evaluadas.** Los resultados de abajo son del commit `15bd5ef`, antes de sumar el verificador, las citas por celda, la recuperación híbrida y el ruteo de modelos. Esos cambios tocan el prompt de código y el grafo, así que hay que volver a correr la evaluación: ver [Corrida con los distintivos](#corrida-con-los-distintivos).

## Resultados (corrida final, commit 15bd5ef)

| # | Pregunta | Estado esperado | Estado obtenido | Estado | Valores | Intentos de código | Tablas usadas |
|---|---|---|---|:---:|:---:|:---:|---|
| 1 | Crecimiento interanual promedio de ingresos 2020–2024 | answered | answered | ✅ | ✅ 11,51 % | 1 | Estado de resultados |
| 2 | Proporción de I+D sobre gastos operativos por año | answered | answered | ✅ | ✅ | 1 | Gastos operativos por categoría |
| 3 | I+D como % de ingresos 2024 (multitabla) | answered | answered | ✅ | ✅ 9,17 % | 1 | Gastos operativos + Estado de resultados |
| 4 | Crecimiento de ventas Sur 2024 vs 2023 (multipágina) | answered | answered | ✅ | ✅ 11,32 % | 1 | Ventas mensuales por región |
| 5 | Mes de 2024 con mayores ventas | answered | answered | ✅ | ✅ Diciembre, 12.033 | 1 | Ventas mensuales por región |
| 6 | Exportaciones per cápita Litoral 2023 (multitabla) | answered | answered | ✅ | ✅ 2.858,8 USD/hab | 1 | Exportaciones + Población |
| 7 | Región con mayor desocupación y diferencia con el promedio nacional | partial | partial | ✅ | ✅ Desierto, 10,6 % | 1 | Desocupación por región |
| 8 | Exportaciones per cápita Montaña 2020 | cannot_answer | cannot_answer | ✅ | ✅ | 0 | — |
| 9 | Exportaciones de Litoral en pesos | cannot_answer | cannot_answer | ✅ | ✅ | 0 | — |
| 10 | Inflación de Argentina 2023 | cannot_answer | cannot_answer | ✅ | ✅ | 0 | — |
| 11 | Ingresos de Andina Tech 2025 | cannot_answer | cannot_answer | ✅ | ✅ | 0 | — |

**11 / 11 correctas.** Las respuestas completas en lenguaje natural están en [`data/eval_results.md`](data/eval_results.md).

Notas por pregunta:

- **2:** el código devolvió fracciones (0,2175…) en lugar de porcentajes; la respuesta lo aclara ("fracción"). Se considera correcta porque la conversión % ↔ fracción está permitida, pero el formato no es el ideal.
- **7:** la parte "región más alta" se responde y la parte "promedio nacional" queda como faltante, sin promediar las regiones. En una primera versión el código sí promediaba las regiones y ese número aparecía en la respuesta aunque el estado era `partial` (ver historial).
- **8 y 11:** el selector marcó la parte como no respondible. Además, si el LLM hubiera pedido una columna `2020` o `2025`, `check_selection` la rechaza en código porque no existe en el parquet (cubierto por tests).
- **8–11:** no se generó ni ejecutó código (el grafo va directo de `select` a `answer`).

## Historial de corridas

El set se corrió varias veces mientras se ajustaban los prompts. Se reportan todas:

| Corrida | Resultado | Qué falló | Cambio |
|---|---|---|---|
| 1 | 10/11 | **6:** "2,86 miles de USD por persona" (cálculo correcto, unidad distinta a la esperada y redondeo que pierde precisión). **1 y 4** necesitaron 2 intentos de código (el primer programa falló y se autocorrigió con el error). | Regla de escala en el prompt de código. |
| 2 | 10/11 | **5:** "12.033.000 pesos" (correcto, pero convirtió la escala sin necesidad). | La conversión de escala solo aplica a cocientes; una magnitud sola mantiene la unidad de la tabla. |
| 3 (parcial: 5 y 6) | 1/2 | **6:** volvió a "miles de USD por persona". La traza mostró que el selector escribía en `conversions` "expresar en miles de USD por persona" y el código lo obedecía. | Prompt del selector: en cocientes, resultado en unidades simples; la regla de unidades del código tiene prioridad. |
| Final | 11/11 | — | — |

Antes de la corrida 1, la pregunta 7 se probó suelta y dio el estado correcto (`partial`) pero el código calculó igual un "promedio nacional" promediando regiones. Se corrigió pasándole al generador de código la lista explícita de partes que **no** debe calcular.

## Corrida con los distintivos

Corrida sobre el commit `ad88cf5`, 3 corridas por pregunta: **11/11 correctas en las 33 corridas**. Comandos:

```bash
python scripts/run_eval.py --repeats 3          # tabla por etapa en data/eval_results.md
python scripts/langsmith_eval.py --repeats 3    # el mismo set como experimento en LangSmith
```

`run_eval.py` ahora reporta, por pregunta y sobre 3 corridas:

- **Recuperación:** ¿las tablas esperadas (por archivo y rótulo) estaban entre las 5 candidatas?
- **Selección:** ¿las tablas usadas son exactamente las esperadas (ninguna en `cannot_answer`)?
- **Estado** y **valores**, con las mismas reglas que antes.
- **Intentos de código** promedio y **observaciones del verificador**.

Así una falla queda ubicada en una etapa ("no recuperó la tabla" no es lo mismo que "calculó mal"), y la variación entre corridas queda medida en lugar de anecdótica (la pregunta 6 pasó y falló con el mismo prompt).

| # | Esperado | Obtenido | Recuperación | Selección | Estado | Valores | Correcta | Intentos (prom.) | Obs. del verificador |
|---|---|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| 1 | answered | answered | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 | 1.0 | 0 |
| 2 | answered | answered | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 | 1.0 | 0 |
| 3 | answered | answered | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 | 1.0 | 0 |
| 4 | answered | answered | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 | 1.3 | 0 |
| 5 | answered | answered | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 | 2.0 | 0 |
| 6 | answered | answered | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 | 1.0 | 0 |
| 7 | partial | partial | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 | 1.0 | 0 |
| 8 | cannot_answer | cannot_answer | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 | 0.0 | 0 |
| 9 | cannot_answer | cannot_answer | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 | 0.0 | 0 |
| 10 | cannot_answer | cannot_answer | — | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 | 0.0 | 0 |
| 11 | cannot_answer | cannot_answer | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 | 0.0 | 0 |

- **Recuperación:** 30 / 30
- **Selección:** 33 / 33
- **Estado:** 33 / 33
- **Correctas:** 33 / 33
- **Preguntas correctas en todas las corridas:** 11 / 11 (33 corridas)

## Trazas representativas de LangSmith

Proyecto: `LANGSMITH_PROJECT` del `.env`. Cada ejecución aparece como `ingesta:<archivo>` o `analista: <pregunta>`, con un span por nodo.

1. **Multitabla `answered` con citas** (pregunta 3): `understand → retrieve → select → codegen → execute → verify → answer`; en `execute` se ven las celdas citadas de las dos tablas. — [traza](https://smith.langchain.com/public/a0808d5b-9915-4f09-9307-88430500f9d6/r)
2. **`partial` con verificador** (pregunta 7): la selección marca "promedio nacional" como no respondible, el código solo calcula la otra parte y el verificador lo aprueba. — [traza](https://smith.langchain.com/public/57d9c120-b729-478f-ba5a-38821f9b5390/r)
3. **`cannot_answer` sin código** (pregunta 9), o una con reintento de código o revisión humana si aparece en las corridas. — [traza](https://smith.langchain.com/public/9d6860ed-886a-4b60-b378-603b316c702e/r)

> Para compartirlas: en LangSmith, abrir la traza → *Share* → copiar el link público, o adjuntar capturas en `docs/`.

## Limitaciones de la evaluación

- **Set chico y conocido:** 11 preguntas sobre 2 PDFs propios. Los prompts se ajustaron mirando estas mismas preguntas, así que el 11/11 sobreestima el rendimiento en PDFs nuevos.
- **No determinismo:** aun con temperatura 0, el modelo varía entre corridas (la pregunta 6 pasó y falló con el mismo prompt). Por eso la evaluación nueva corre cada pregunta varias veces; aun así, 3 corridas son pocas para estimar una tasa.
- **Chequeo automático acotado:** se verifican números y estado, no la calidad de la redacción. La regla "en `cannot_answer` no se muestra ningún número" se verifica sobre el resultado del código, no sobre el texto final (que puede mencionar años o períodos).
