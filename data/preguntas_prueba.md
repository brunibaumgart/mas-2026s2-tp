# Preguntas de prueba

PDFs: `memoria_andina_tech_2024.pdf` (M) y `anuario_valdoria_2023.pdf` (A). Datos ficticios; las respuestas se calcularon desde `scripts/generate_sample_pdfs.py`.

| # | Pregunta | Estado esperado | Respuesta esperada | Tablas | Qué prueba |
|---|----------|-----------------|--------------------|--------|------------|
| 1 | ¿Cuál fue el crecimiento interanual promedio de los ingresos entre 2020 y 2024? | `answered` | **11,51 %** (promedio de 7,90 %, 13,71 %, 12,90 % y 11,51 %). La tasa compuesta (CAGR) sería 11,48 %; se acepta si lo aclara. | M Cuadro 1 (p. 1) | Encabezado de dos filas con celda combinada, `$` y paréntesis |
| 2 | ¿Qué proporción de los gastos operativos totales representó I+D en cada año? | `answered` | 2020: 21,75 % · 2021: 22,26 % · 2022: 24,25 % · 2023: 27,18 % · 2024: 29,09 % | M Cuadro 2 (p. 2) | Separador de miles, fila de total |
| 3 | ¿Qué porcentaje de los ingresos por ventas representó el gasto en I+D en 2024? | `answered` | **9,17 %** (12.100 / 131.920) | M Cuadro 1 + Cuadro 2 | **Multitabla** |
| 4 | ¿Cuánto crecieron las ventas de la región Sur en 2024 respecto de 2023? | `answered` | **+11,32 %** (26.291 → 29.268 miles de $) | M Cuadro 3 (p. 1–2) | **Tabla multipágina**: Diciembre 2023 está en la pág. 2. Si no se une, 2023 da mal. |
| 5 | ¿Qué mes de 2024 tuvo las mayores ventas totales y cuánto vendió? | `answered` | **Diciembre**, 12.033 miles de $ (le sigue Noviembre con 11.933) | M Cuadro 3 (p. 2) | Suma entre columnas, tabla unida |
| 6 | ¿Cuáles fueron las exportaciones per cápita de la región Litoral en 2023? | `answered` | **≈ 2.858,80 USD por habitante** (6.118,4 M USD / 2.140,2 miles de hab.). Tiene que explicitar el cambio de escala. | A Cuadro 3.1 + Cuadro 2.1 | **Multitabla** + cambio de escala permitido |
| 7 | ¿Qué región tuvo la tasa de desocupación más alta en 2023, y por cuánto superó al promedio nacional? | `partial` | Desierto, 10,6 %. La comparación no se puede: el anuario no publica un promedio nacional (no vale promediar las regiones). | A Cuadro 1.1 | Falta valor de comparación |
| 8 | ¿Cuáles fueron las exportaciones per cápita de Montaña en 2020? | `cannot_answer` | Sin número. Exportaciones y población cubren solo 2021–2023; 2020 no está. | A Cuadro 3.1 + 2.1 | Falta período (no usar el año más cercano) |
| 9 | ¿A cuántos pesos equivalen las exportaciones de Litoral en 2023? | `cannot_answer` | Sin número. Requiere un tipo de cambio que no está en ninguna tabla. | A Cuadro 3.1 | Conversión con datos externos |
| 10 | ¿Cuál fue la inflación de Argentina en 2023? | `cannot_answer` | Sin número. Ninguna tabla indexada trata ese tema. | — | Pregunta no relacionada |
| 11 | ¿Cuáles fueron los ingresos por ventas de Andina Tech en 2025? | `cannot_answer` | Sin número. El Cuadro 1 cubre 2020–2024. | M Cuadro 1 | Falta año (no extrapolar) |

## Casos de ingesta para verificar a mano

- **M Cuadro 1:** encabezado de dos filas (`Ejercicio fiscal (miles de $)` combinado sobre los años). PyMuPDF lo devuelve como `Col0, Ejercicio fiscal..., Col2...` con los años en la primera fila: hay que aplanarlo a `Concepto, 2020, …, 2024`.
- **M Cuadro 3:** 11 filas en la pág. 1 + 13 en la pág. 2, con el encabezado repetido. Tiene que quedar **una** tabla de 24 filas con `source` = páginas 1–2.
- **A Cuadro 4.1:** es una imagen. Tiene que saltearse e informarse en la UI, no inventarse.
- **Formatos:** `$ 85.400`, `($ 41.200)`, `7,2 %`, `US$ 3.420,5`, `4.812,3` → todos a `float`.
