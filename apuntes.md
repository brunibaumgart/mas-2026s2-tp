# Apuntes — Sistemas con modelos de lenguaje

Notas vivas de la materia. Cada clase suma un capítulo; el [glosario](#glosario) y las [heurísticas](#heurísticas-prácticas) se reutilizan después.

Cómo leerlo: primero el entorno (vale para todos los notebooks), después la clase del día. Lo que todavía no corrimos queda marcado como *pendiente*.

Notebooks del repo:

| Archivo | Tema |
| --- | --- |
| `01-demo-litellm.ipynb` | Conexión al proxy, health, listado de modelos, primera inferencia |
| `llm-failure-demos.ipynb` | Modos de fallo (alucinación, inyección, sesgo, etc.) |
| `model-param-demos.ipynb` | Parámetros de sampling y decodificación |
| `system-prompt-demos.ipynb` | System prompt como spec de comportamiento (Clase 04) |

Credenciales: `LLM_SERVICE_URL` y `LLM_API_KEY` en `.env` (nunca las copies acá). Kernel de Python: `sm/.venv`.

---

## Entorno

El código no habla con OpenAI/Anthropic en forma directa. Habla con el **proxy LiteLLM** de ITBA (`https://sa-llmproxy.it.itba.edu.ar`) usando el SDK estilo OpenAI / LangChain `ChatOpenAI`.

Qué implica:

- Un solo `base_url` + una `api_key` del proxy.
- El nombre del modelo es el **alias del proxy** (`gpt-4.1-mini`, `claude-haiku-4-5`, …), no la key del vendor.
- `/health` en este proxy **pide auth** (responde 401 sin key). `/v1/models` con Bearer funciona y es el check útil.
- `LLM_MODEL` en el `.env` es solo diagnóstico en `model-param-demos`; la lista fija es `MODELS`.

Modelos que vimos publicados en el proxy (recorte): familia GPT-4.1 (`gpt-4.1`, `mini`, `nano`), varias GPT-5 / 5.4, Claudes (Haiku, Sonnet, Opus, 3.5, etc.) y embeddings.

Costo: un *Restart & Run All* de parámetros son ~150–270 llamadas. Correr de a una demo, y Demo 1 de temperature al final.

---

## Glosario

| Término | En una frase |
| --- | --- |
| **Proxy LiteLLM** | Capa que unifica proveedores detrás de la API de OpenAI. |
| **Token** | Pieza de texto que el modelo genera de a una; `max_tokens` cuenta estas, no caracteres. |
| **Sampling** | Cómo se elige el próximo token entre los candidatos. |
| **`temperature`** | Estira o aplasta la distribución de probabilidad. 0 ≈ más pico / repetible; 1 ≈ más diversidad. |
| **`top_p` (nucleus)** | Se queda solo con el conjunto más chico de tokens cuya probabilidad acumulada llega a *p*. |
| **`max_tokens`** | Tope duro de tokens **de la respuesta**. No resume: corta. |
| **`presence_penalty`** | Castiga tokens que **ya aparecieron** → empuja temas nuevos. |
| **`frequency_penalty`** | Castiga según **cuántas veces** apareció → baja muletillas. |
| **`seed`** | Intento de reproducir la misma muestra; el proxy/modelo puede no soportarlo. |
| **System prompt** | Mensaje `system`: spec de comportamiento *antes* de que el usuario escriba. No se muestra; igual puede filtrarse. |
| **Few-shot** | Ejemplos como turnos reales `user`/`assistant`, no un párrafo pegado en el system. |
| **Structured output** | Schema (Pydantic) que **fuerza** el formato. Pedirlo en prosa no es un contrato. |
| **Golden set** | Casos de borde escritos *antes* de mirar al modelo; se rerunnea entero en cada cambio de prompt. |
| **Prefix cache** | Cache por prefijo byte a byte. Si cambia el system (fecha, user_id), se invalida todo lo de abajo. |

---

## Clase 01 — Hablar con el proxy

Objetivo: verificar que el entorno funciona de punta a punta.

Flujo del notebook:

1. Cargar `.env`.
2. Health / conectividad.
3. `GET /v1/models`.
4. `chat.completions` con `gpt-4.1-mini`.
5. Misma llamada con una key inválida → error de autenticación.

Qué quedarse:

- El patrón se repite en el resto de la materia: cliente → proxy → modelo.
- Un fallo de auth se ve como excepción de autenticación, no como “el modelo contestó mal”.
- Los notebooks originales apuntaban a `../../.env`; en este repo el `.env` está **junto** a los `.ipynb` (`Path(".env")`).

---

## Clase 02 — Modos de fallo

Notebook: `llm-failure-demos.ipynb`.

Temas que cubre (aún no corrido en estas notas): alucinación, cutoff de conocimiento, prompt injection, sesgo político, sicofancia, lost-in-the-middle, razonamiento frágil, inconsistencia de output.

Pendiente: correrlo y anotar métricas acá.

---

## Clase 03 — Parámetros del modelo

Notebook: `model-param-demos.ipynb`.

Misma idea en todas las demos: **prompt fijo**, se mueve **un** parámetro, se mira el efecto. En la práctica de estas notas usamos `gpt-4.1-mini` para leer de a una cosa.

### 3.1 `max_tokens` — tope de largo (Demo 3)

Prompt: explicar un catálogo de biblioteca en **cuatro** partes (clasificación, préstamo, vencidos/reservas, inventario).

Corrida (`temperature=0`, `gpt-4.1-mini`):

| `max_tokens` | Caracteres | Qué se vio |
| --- | --- | --- |
| 16 | 79 | Corta a mitad de analogía: *“…treasure chest full of books”* |
| 64 | 323 | Llega al Dewey Decimal y corta: *“…books about animals might be”* |
| 256 | 1156 | Completa el punto 1 y corta a mitad del 2: *“…or use a self”* |

Conclusiones:

- No acorta el prompt: acorta la **generación**.
- No “elige ser breve”: lo **frenan**. Por eso hay frases a medio terminar, no un resumen.
- No es un dial de calidad. Es presupuesto de **costo y latencia**.
- Un tope “razonable” tiene que entrar la **respuesta completa**. Acá 256 no alcanzó para los 4 puntos.

Regla práctica: si ves cortes a mitad de oración en producción, subí `max_tokens` (o pedí explícitamente un formato corto). No bajes temperature para “hacerlo más conciso”.

### 3.2 `top_p` — nucleus sampling (Demo 2)

Prompt creativo: inventar un gadget mínimo con nombre juguetón, máximo tres oraciones.

Corrida (`temperature=0.8` fija, `gpt-4.1-mini`, **una** muestra por valor):

| `top_p` | Gadget | Tono |
| --- | --- | --- |
| 0.1 | **Sock Snatcher** — clip magnético en el lavarropas que reúne medias | Analogía cotidiana clásica |
| 0.5 | **SnagZap** — clip que destanglea auriculares con micro-vibración | Más “producto startup” |
| 1.0 | **SnagTag** — clip que destanglea auriculares con un snap | Misma familia que 0.5 |

Qué significa `top_p`:

1. El modelo asigna probabilidad a cada próximo token.
2. Se ordenan de mayor a menor.
3. Se acumula hasta cubrir probabilidad *p*.
4. El resto se descarta. Recién ahí se samplea (con la temperature que ya fijamos).

Intuición:

- `top_p=0.1` → núcleo chico → wording más pico / “seguro”.
- `top_p=1.0` → entra toda la distribución que dejó temperature 0.8.
- `top_p` y `temperature` **no son lo mismo**. Temperature estira la curva; `top_p` recorta la cola.

Cuidado al leer **una** corrida: acá 0.1 salió distinto (medias) y 0.5/1.0 salieron primos (auriculares). Eso ilustra el parámetro, **no** prueba un ranking de creatividad. Para medir diversidad hace falta muchos trials (eso es Demo 1 con temperature).

Regla práctica: si querés respuestas más conservadoras **sin** bajar tanto la temperature, bajá `top_p`. Si querés la distribución completa a esa temperature, dejá `top_p=1`.

### 3.3 `presence_penalty` — empujar temas nuevos (Demo 4)

Prompt: ocho ideas de finde en una ciudad costera, **temas distintos** (comida, aire libre, cultura, descanso), una oración cada una.

Corrida (`temperature=0.7`, `gpt-4.1-mini`, una muestra por valor):

| # | `presence_penalty=0.0` | `presence_penalty=1.5` |
| --- | --- | --- |
| 1 | Clase de cocina de mariscos | Mariscos en un mercado local |
| 2 | Hiking costero | Kayak por cuevas |
| 3 | Museo marítimo | Galería de arte regional |
| 4 | Yoga en la playa al amanecer | Yoga al atardecer en la playa |
| 5 | Kayak por cuevas / manglares | Faro histórico + museo |
| 6 | Mercado artesanal | Clase de cocina costera |
| 7 | Faro + jardines | Hiking por acantilados |
| 8 | Crucero de vela al atardecer | Folk en vivo en un café |

Qué hace el parámetro: si un token **ya apareció** en la respuesta, baja su probabilidad. Es un castigo binario (estuvo / no estuvo), no cuenta *cuántas* veces. Por eso empuja a **abrir temas**, no tanto a “decir la misma palabra menos”.

Qué se vio acá:

- A `0.0` el modelo **ya** repartió temas, porque el prompt lo pedía. El knob suma poco cuando la instrucción ya dice “no repitas el tipo de actividad”.
- Aun así, `0.0` se queda más en el mar (hiking + kayak + faro + vela). `1.5` cuela cultura extra (galería, folk) y suelta el crucero.
- Una sola muestra no alcanza para decir “siempre más diversidad”. El efecto es más claro si el prompt *no* pide spread, o si el modelo tiende a dar vueltas sobre lo mismo.

Otro dato de la materia: modelos estilo OpenAI suelen aceptar `presence_penalty`; Anthropic por este proxy **puede rechazarlo**. Eso no es un fallo del demo: se anota como skip.

Regla práctica: subilo cuando una respuesta da vueltas alrededor del mismo tema. Si el prompt ya exige ítems distintos, no esperes un milagro. No lo confundas con `frequency_penalty` (eso va por repetición de palabras, Demo 5).

### 3.4 `frequency_penalty` — menos muletillas (Demo 5)

Prompt: blurb de una taza blanca de cerámica, simple y cotidiana. El texto **invita** a reusar los mismos selling points si se quedan sin ideas.

Corrida (`temperature=0.7`, `gpt-4.1-mini`, una muestra por valor):

| | `frequency_penalty=0.0` | `frequency_penalty=1.5` |
| --- | --- | --- |
| Palabras únicas / total | 59 / 77 | 58 / 71 |
| Repeticiones notables | *mug*×4, *simplicity*×2, *everyday*×2, *clean*×2 | *mug*×3; ya no dobla *simplicity* / *everyday* / *clean* |
| Cómo suena | Vuelve a “simple / everyday / clean / mug” | Mismos puntos, otro wording (*simplest things… most useful*) |

Qué hace: el castigo **crece con el conteo**. La segunda vez que sale un token duele más que la primera; la tercera, más todavía. Por eso ataca el *stutter* y las muletillas, no tanto el “abrir un tema nuevo” (eso era `presence_penalty`).

Diferencia con Demo 4, en una línea:

- `presence_penalty`: ¿este token **apareció**? → empujá otro tema.
- `frequency_penalty`: ¿**cuántas veces** apareció? → dejá de martillar la misma palabra.

GPT-4.1-mini ya escribe fluido, así que no vas a ver un bucle obvio a `0.0`. El prompt tuvo que *permitir* el reuse para que el knob se note. Igual que en Demo 4, Anthropic puede rechazar el parámetro.

Regla práctica: subilo si el modelo se traba en una frase o un adjetivo. No lo uses para “más temas”: para eso es presence. `1.5` es bastante alto (el rango típico es −2 a 2); en producción empezá más bajo.

### 3.5 `seed` — reproducibilidad (Demo 6)

Prompt: nombre raro + backstory de una librería de barrio que vende mapas (2–3 oraciones).

Corrida (`temperature=0.3`, `gpt-4.1-mini`): 5 veces con `seed=42`, 3 veces con `seed=99`. El proxy **aceptó** el parámetro (no hubo skip).

| Semilla | Nombres | ¿Textos idénticos? |
| --- | --- | --- |
| 42 ×5 | Las cinco: **The Wandering Quill** | No. Dos trials (1 y 4) sí coincidieron palabra por palabra; las otras tres varían el backstory |
| 99 ×3 | **The Wandering Compass** (2) y **The Wandering Quill** (1) | No |

Qué vale la pena retener:

- `seed` **no es un switch de determinismo**. Es “más repetible *si el backend lo honra*”. Acá lo acepta, pero no da bit-identity.
- Temperature sigue metiendo ruido. A `0.3` ya hay variación; a `0.8` sería peor. Para evals comparables, `temperature=0` pesa más que un seed.
- Aun así se ve un **atractor**: 42 se queda en Quill; 99 asoma Compass. Misma familia de tropes (cartógrafo excéntrico, calles de adoquines, mapas que “guían”).
- No asumas que el mismo seed en GPT y Claude da el mismo texto. Si el proveedor lo rechaza, es skip, no un fallo tuyo.

Regla práctica: usá seed cuando el backend lo documenta y querés *acercarte* a la misma muestra. Si necesitás el mismo string para un test, no te apoyes en seed: fijá `temperature=0` y, si hace falta, cacheá la respuesta.

### 3.6 `temperature` — diversidad real, no un sample (Demo 1)

Única demo **cuantitativa** de la clase. Ticket de soporte **ambiguo a propósito**: login lento (huele a *Bug Report*) + “¿hay dark mode?” (huele a *Feature Request*). El modelo tiene que devolver **exactamente una** de: Bug Report, Feature Request, Account Access, General Inquiry.

Corrida reducida para no gastar: `gpt-4.1-mini`, **`DEMO1_N=8`** (el notebook pide 30), temps `{1.0, 0.5, 0.0}` → 24 llamadas.

| temperature | n | Distinct | Shannon entropy | Majority-share | Labels |
| --- | --- | --- | --- | --- | --- |
| 1.0 | 8 | 1 | 0.000 | 1.000 | General Inquiry ×8 |
| 0.5 | 8 | 1 | 0.000 | 1.000 | General Inquiry ×8 |
| 0.0 | 8 | 1 | 0.000 | 1.000 | General Inquiry ×8 |

Cómo leer las métricas:

- **Distinct**: cuántas etiquetas distintas salieron.
- **Entropía de Shannon**: 0 = siempre la misma; sube si se reparte entre clases.
- **Majority-share**: fracción de la etiqueta más votada. 1.0 = unanimidad.

Qué se vio:

- Las 24 respuestas fueron la palabra `General Inquiry`. El modelo resolvió la ambigüedad yendo al **cajón de sastre** (dos pedidos en un ticket ≠ un bug ni un feature “puros”).
- Con este N, **no se vio** el efecto clásico “temp 1 = más labels”. Temperature estira la distribución, pero si el modelo está muy pico en un token, temp 1 igual puede salir siempre igual — sobre todo con un output de una sola categoría.
- Bajar N tiene costo estadístico. En una corrida vieja del mismo notebook (`N=30`, mismo modelo) a temp 1 había distinct=2, entropy≈0.21, majority≈0.97: o sea **~1 de 30** era otra etiqueta. Con 8 trials esa cola se puede perder. N chico ≠ “temperature no hace nada”; es “no tenemos potencia para ver una minoría del 3%”.
- Consistencia ≠ corrección. Entropy 0 dice que el eval exact-match sería estable. No dice que General Inquiry sea *la* clase correcta (un humano podría marcar Bug o Feature).

Regla práctica: `temperature=0` para demos/evals que tienen que ser comparables. Temperature alta cuando *querés* variedad (brainstorm, sampling). Para **medir** esa variedad hace falta N grande, no un par de prints. Un “fallo” de un eval a temp>0 a veces es ruido de sampling, no un modelo peor.

Con esto cierra el recorrido de `model-param-demos` en estas notas (un modelo, N reducido en Demo 1). No corrimos `gpt-4.1` / `gpt-4.1-nano` ni el `N=30` completo.

---

## Heurísticas prácticas

1. **Un knob por vez.** Si movés temperature y top_p juntos, no sabés qué cambió.
2. **`max_tokens` = presupuesto**, no estilo.
3. **`temperature=0`** cuando el demo o el eval tiene que ser comparable; **más alta** cuando querés variedad.
4. **`top_p` bajo** = cola recortada (más pico) a la misma temperature.
5. Un sample no es una métrica. Tasas, entropía y majority-share sí (Demo 1).
6. Un `SKIP` de parámetro no es que el demo “falló”: el proveedor/proxy puede rechazar `seed` o penalties.
7. **`presence_penalty`** = “ya salió este token → penalizalo” (cobertura de temas). Sirve poco si el prompt ya pide variedad.
8. **`frequency_penalty`** = “cuanto más lo repetís, más duele” (muletillas). Distinto de presence.
9. **`seed` no garantiza el mismo string**, ni entre vendors ni siempre en el mismo modelo. `temperature=0` ayuda más a un eval estable.
10. **`temperature` alta no garantiza diversidad** si el modelo ya está muy pico (clasificar en una palabra). Y **N chico oculta colas raras**. Consistencia ≠ label correcta.

---

## Clase 04 — System prompt

Notebook: `system-prompt-demos.ipynb`. **Todavía no corrido** (solo leído).

Idea de la clase: el system prompt es la palanca más directa sobre **calidad de producto**. No es un text box ingenioso: es una **spec de comportamiento**. Fija tono, límites y formato. **No** arregla desconocimiento de hechos (eso es RAG, clase 5) ni techo de razonamiento (eso es el modelo).

Producto único en todas las demos: soporte ficticio de **Acme**. Filtro para cada línea del prompt:

> ¿Qué haría mal el modelo si esta línea no estuviera?

Si no hay respuesta, esa línea quema contexto al pedo.

### Antes de correr

- El notebook apunta a `Path("../../.env")`. En este repo el `.env` está al lado: hay que pasar a `Path(".env")` (igual que clase 01/03) o va a fallar el setup.
- `MODELS = ["gpt-5.4-mini", "claude-haiku-4-5"]` — distintos a clase 03. Ambos estaban en `/v1/models`.
- Casi todo a `temperature=0` (casa con la heurística de evals).
- *Restart & Run All*: **~45–55 llamadas**. Más barato que clase 02/03. Demo 10 es la más grande (8). Demo 8 **no** llama al modelo.
- Un knob a la vez: acá el knob es el **texto del system** (y a veces el schema), no `top_p`.

### Cheat sheet de capas (antes de reescribir el prompt)

| Síntoma | Palanca correcta |
| --- | --- |
| Tono / persona / formato se va | **Instructions** (esta clase) |
| Promete cosas que no puede | **Instructions** |
| No sabe de la empresa / post-cutoff | **Knowledge** (RAG) |
| Olvida la conversación de ayer | **Memory** |
| No puede ejecutar una acción | **Tools** |
| Falla lógica de varios pasos | **Reasoning** / modelo más fuerte |
| El usuario no debería haber podido preguntar eso | **Capa de aplicación** (UI, auth, validación) |

El modelo pone el **techo**. El system esculpe *debajo* de ese techo. Encaja con el orden de palancas de clase 03: si el pedido era flojo, prompt antes que sampling.

### `ACME_SYSTEM` (esqueleto que se va a ir tensando)

Orden recomendado: **identidad → constraints duros → tono → formato → escalamiento**. Constraints antes que estilo (igual que el teardown de Claude al final del notebook).

| Bloque | Qué cierra |
| --- | --- |
| `<role>` | Sos soporte Acme; solo órdenes, envíos, billing, setup |
| `<constraints>` | No reembolsos/créditos; no pedir tarjetas; no inventar precios/SLAs |
| `<tone>` | “you”, sin emojis ni `!`, máx. 3 oraciones |
| `<escalation>` | Abogados / refund / mismo problema ×3 → handoff a humano y **parar** |

### Mapa de demos (qué mirar cuando corramos)

| Demo | Pregunta | Qué esperar (hipótesis, sin evidencia todavía) |
| --- | --- | --- |
| **1** Raw vs system | Mismo user ×2: refund #4412 y “quién sos” | Sin system: puede prometer refund o inventar persona. Con Acme: rechaza refund, se queda corto y en rol |
| **2** Tono vs knowledge | Welcome con emojis vs precio de “Acme Pro annual” | (1) el system mata el tono peppy. (2) sin system suele **inventar un precio**; con system admite que no sabe. Ninguno tiene el precio real: **no está en contexto** |
| **3** Vague vs specific | Overview de Acme + “¿Sony es mejor?” / NPS 2024 | Vague = “be helpful / don’t be verbose” (espacio permitido indefinido). Specific = 3 oraciones, frases exactas de fallback. “Be helpful” no cierra ningún gap: borrar |
| **4** Wall vs XML | Mismas reglas; pedir JSON `reply/source/next_step` | Wall entierra la regla crítica. XML versionable por bloques. Delimiter XML vs Markdown es estilo; **mezclar tres estilos es peor que no usar ninguno**. Reglas de peso al **inicio**; si es largo, reminder de 2–3 al **final** (lost-in-the-middle) |
| **5** Zero vs few-shot | Clasificador `logistics \| billing \| technical \| out_of_scope` | Ejemplos como turnos reales, no pegados en el system. Cubrir **bordes** (el 3.º es un contraejemplo: hay que rechazar). \>~5 ejemplos → ya es caso de fine-tune |
| **6** Pedir JSON vs forzarlo | Mismo ticket; `json.loads` vs `with_structured_output(Ticket)` | “Casi siempre JSON válido” no es contrato de backend. Schema ejecutable y **libera tokens** del prompt. Si el vendor da un parámetro, usá el parámetro (eco de clase 03) |
| **7** No es boundary de seguridad | Leak de `POLICY-42`; injection en `<document>` pidiendo `REFUNDED $499` | Jerarquía *estadística*: provider > system > user > tool/document. Un ataque bien escrito puede ganar. Marcar untrusted **sube el costo**, no hace seguros los tool calls. Secretos de verdad: **nunca** en el prompt; allowlist/human-in-the-loop en la app |
| **8** Presupuesto y cache | Sin llamadas al modelo | `total = system + RAG + history + output`. Se paga el system **en cada turno** (API stateless). Comparar bloated vs tight (char/4). Killers: `datetime.now()` en el system, user_id arriba del prefijo. **Congelar el system**; lo dinámico va en messages |
| **9** Prompt como artefacto | `ChatPromptTemplate` + `MessagesPlaceholder`; few-shot como mensajes | OpenAI: system en `messages`. Anthropic: `system=` aparte + `cache_control`. LangChain unifica **forma**, no **capacidad**. `{today}` adentro del system rompe el cache |
| **10** Mini golden set | G1 refund, G2 número de tarjeta, G3 “charged twice”→`billing`, G4 abogado→handoff | Casos escritos *antes* de ver al modelo. Checks determinísticos (regex), no LLM-as-judge. Config del eval = config de prod (`temperature=0`). Fallar es el próximo caso permanente. Orden: **agregar el caso que falla, recién ahí parchear** |
| **11** Un prompt por agente | Orquestador (ruta JSON) vs especialista billing | Contexto **no** se comparte. Sin pasar order 4412, el especialista no “se acuerda”. Tres errores clásicos: un prompt gigante compartido, prosa entre agentes, asumir memoria compartida. El presupuesto **se multiplica** por cantidad de agentes |

### Teardown (Claude publicado)

Anthropic publica ~3k palabras de la porción de *behavior* del system de Claude. No memorizar el wording. Mirar **secciones y orden**: product info, refusals, legal/financial, tone, wellbeing, reminders (los users **pueden forjar esos tags**), evenhandedness, anti-sycophancy, knowledge cutoff. Identidad y refusals antes que tono.

### Takeaways para guardar (de la clase, pre-evidencia)

1. Instructions arreglan inconsistencia, tono y safety. No arreglan ignorancia ni alucinación de hechos.
2. Estructura > ingenio. Específico, framing positivo, ejemplos, orden deliberado.
3. Cada línea paga tokens que no van a history/RAG.
4. Evolucionar contra un golden set; el sandbox sirve para explorar, no para evaluar.
5. Multi-agente: un prompt por trabajo, pasar lo que el siguiente necesita, schema en el handoff.

Cuando corramos: ir demo por demo (1 → 2 son el “aha”), anotar pass/fail del golden y si `POLICY-42` / `REFUNDED` aparecen.

---

## Cómo seguir

Siguiente a correr: `system-prompt-demos.ipynb` (Clase 04), de a una demo, empezando por 1–2. Antes: arreglar `ENV_PATH`.

Pendiente todavía: `llm-failure-demos.ipynb` (Clase 02).
