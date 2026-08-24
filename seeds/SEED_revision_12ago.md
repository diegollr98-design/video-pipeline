> ✅ EJECUTADO (12-ago-2026).

# SEED — Revisar los cambios del 12-ago y cerrar lo que queda

> PASO 0 OBLIGATORIO: invoca /seed-review sobre este SEED antes de tocar nada.

## Por qué existe, dicho sin adornos

El 12-ago se metieron **9 cambios** en una sola sesión. Todos están medidos y ninguno se cerró "por
informe"… pero **los diseñé yo y los audité yo**. Ese es el modo de fallo que este repo tiene
documentado: el self-review. Además la sesión dio la señal que `CLAUDE.md` §6 dice que hay que mirar —
**el mismo error de clase dos veces el mismo día**: un `NameError` por variable fuera de alcance
(`logger` en el cableado del auditor, `args` en el tope de shorts). Los dos habrían petado en
producción y los dos pasaron `compileall` limpios.

Diego lo pidió explícitamente: *"revisamos tus últimos cambios con un seed fresco para ver si son los
óptimos"*. **Ese es el trabajo principal de esta sesión, no un trámite.** Lo segundo es cerrar lo que
queda.

---

## PARTE 1 — LO QUE HAY QUE REVISAR (y no dar por bueno)

Todo lo de abajo está en `git log` del 12-ago y **funciona**. La pregunta no es si funciona: es si es
**la solución correcta**. Siete decisiones concretas que merecen que alguien sin cariño por ellas las
ataque.

### 1.1 El truncado que introduce un SALTO en la narración ⚠️ EL MÁS DUDOSO

`_truncate_to_words` (`script_generator.py`) ya no decapita la historia: conserva las últimas ~600
palabras. Pero para hacerlo **tira el medio de golpe**. Medido en la corrida real del 12-ago:

```
Truncado: se descartan 1645 palabras del CUERPO (frases 85-115 de 128).
Se conservan las ultimas 616 para no quedarse sin desenlace.
Esto introduce un SALTO en la narracion en ese punto.
```

**31% de la historia cortada de una vez.** Es mejor que quedarse sin final, pero es curar el síntoma:
el modelo escribió **6979 palabras cuando se le pidieron 5345** (+31%). Las preguntas reales:
- ¿Por qué se sobregenera un 31%, y por qué no se ataca ahí (pedir menos por bloque, ajustar el
  objetivo, o parar antes)?
- ¿Un salto seco de 1645 palabras es aceptable para el espectador? **Diego no lo ha juzgado todavía.**
- ¿Existe un corte mejor que "cuerpo + últimas 600"? (¿cortar en frontera de párrafo, elegir el punto
  de menor daño narrativo, comprimir en vez de cortar…?)

### 1.2 El guardia de puntuación: ¿es la palanca correcta? ⚠️ EL MÁS RECIENTE Y MENOS VALIDADO

Diego escuchó el vídeo y dijo: *"hay muchas pausas, además en sitios que no debería, y cuesta de
entender"*. Medido: el modelo escribió **1 coma en 5334 palabras**, frases de mediana **48**.

Se puso un guardia que rechaza y reintenta por debajo de **2,5 comas/100** (`_validar_puntuacion`).

**Lo que NO está verificado, y hay que verificarlo:**
- **¿Reintentar convierte un mal sorteo en uno bueno?** Mi única prueba contra la API real salió
  buena **a la primera**, así que el camino del reintento **nunca se ejerció de verdad**. Si el modelo
  se atasca en su modo sin comas, el guardia cuesta ~12 peticiones y no arregla nada.
- **El umbral es n=3** (0,02 y 0,19 malas; 8,47 buena). Tres puntos.
- **Puede ser la palanca equivocada.** `docs/mediciones-frases.md` §A mide, con un A/B controlado, que
  añadir comas mueve la velocidad **207 → 204 wpm (1,5%)** y **acortar las frases 207 → 172 (17%)**. Y
  la atribución del silencio es **63% puntos / 38% comas**: un punto vale 5,9 comas. En mi prueba
  real, con 6,31 comas/100, la frase mediana seguía siendo de **59 palabras**.
  → **La longitud de frase está sin tocar y puede ser lo que Diego sigue oyendo.**

### 1.3 Dejar los shorts FUERA del guardia de puntuación
Decisión mía, medida: de los 50 shorts del 12-ago, **27 caen bajo el umbral ya después** de
`_ensure_breathing_commas`; con `max_retries: 5` serían **~108 peticiones extra por vídeo** de 1000/día.
¿Es la llamada correcta, o es que el umbral/los reintentos están mal dimensionados y por eso "no
cabe"? Un short son 40 s; un vídeo, 26 min. Contrástalo.

### 1.4 El título corto de YouTube como llamada LLM aparte
`generar_titulo_youtube` gasta **+1 petición por vídeo** y usa `max_tokens=2000` para producir 100
caracteres (porque con 200 el modelo de razonamiento no llegaba a escribir la respuesta: 5 de 5
intentos devolvían razonamiento cortado). ¿Era mejor pedirlo en la misma llamada del primer bloque
(0 peticiones) y asumir el riesgo de tocar el prompt de la historia? Yo elegí no tocarlo por ser la
superficie que más veces se ha roto aquí — **discútelo**.
Ojo al parseo: se queda con el tramo entrecomillado si ocupa ≥60% de la línea, porque el modelo
devolvió `Another option: "Mi Vecino Falsificó..."` **y eso se habría publicado en YouTube**.

### 1.5 `--max-shorts` como flag de CLI
El número de shorts se calcula dinámicamente del chunk y **`generate_per_video` de `config.yaml` no lo
limita** (solo se usa cuando no hay duración). Puse un tope por CLI. ¿No debería arreglarse el cálculo
o la config en vez de añadir una bandera que hay que acordarse de pasar?

### 1.6 El auditor BLOQUEA la cola de subida, y su default es denegar
Sin `_audit.json`, `ok=False` y el vídeo no se ofrece para subir. Es §16 (el default cae del lado
barato), pero: ¿qué pasa con los vídeos viejos legítimos? ¿Es recuperable sin borrar ficheros a mano?
Hoy la única salida documentada es borrar el `_audit.json`.

### 1.7 El reintento del 400 "transitorio"
`_call_openrouter` ahora reintenta un 400 si el cuerpo contiene `degraded|temporarily|overloaded|try
again`. Nació de un caso real (`DEGRADED function cannot be invoked` de Nvidia tumbó un short). ¿Es
una lista de marcadores sostenible o el topo otra vez? ¿Riesgo de reintentar algo que no debe?

---

## PARTE 2 — ESTADO REAL DEL REPO (verificado al escribir esto)

| Cosa | Estado |
|---|---|
| Disco | 🔴 **7,6 GB libres, 99% usado.** Una corrida larga necesita **~12 GB de pico**: **NO CABE**. Hay que liberar antes de producir |
| `input/` | 13 GB, intacto |
| `temp/chunk_1786444528.mp4` | 3,5 GB, 2004 s. **Conservado**: relanzar no exige re-ingerir |
| `output/` | `video_001` (11-ago, defectuoso) y `video_002` (12-ago, **el que Diego escuchó**) |
| `shorts_tiktok/` | 4 shorts del 12-ago |
| `pool/` | vacío |
| Cuota OpenRouter | 10 créditos, 0,0638 USD usados → **1000/día**. Verificado con `GET /api/v1/credits` el 12-ago. **Vuelve a verificarlo, no lo leas de aquí** |
| git | **20 commits sin pushear**. `assets/.tint_index` y `docs/video_guion.md` modificados de antes, no son de este trabajo |
| Disco D: | exFAT, 716 GB libres. Se habló de mover `input/` allí (solo `input/`, no el repo): **decisión aplazada por Diego** |

### La corrida del 12-ago, que es la evidencia principal
`python main.py --skip-ingest --keep-temp --max-shorts 4` → 45 min, ~11 peticiones, vídeo de 26,48 min.
**Veredicto del auditor: sin defectos MEDIBLES** (el primero limpio). Y el bug de [CIERRE-01] **se
reprodujo a escala real y el guardia lo paró** — sin él, este vídeo salía otra vez sin final.

| | 11-ago | 12-ago |
|---|---|---|
| Historia sin final | **sí** | cerrada (el guardia disparó) |
| Voz sin subtítulo | 8,3 s | **0,76 s** |
| Palabras aplastadas | racha 28 | racha **2** |
| Pausas fuera de puntuación | 101 | **88** ← lo que Diego oyó |
| Ratio vídeo/chunk | 0,79 | **0,793** ← sin resolver |

Las 87 palabras >0,5 s tarde de esa corrida están **dispersas** (80 rachas, la mayor de 4 palabras), no
agrupadas: no es la clase de defecto del 11-ago (90 seguidas).

---

## PARTE 3 — LO QUE QUEDA POR CERRAR

| # | Qué | Estado |
|---|---|---|
| 1 | **Longitud de frase** | La palanca que el A/B del repo dice que es dominante (17% vs 1,5%) y **está sin tocar**. Frase mediana 48-59 palabras contra 13 de la corrida buena. Probablemente es lo que Diego sigue oyendo |
| 2 | **Ratio 0,793** | `main.py:480` hace `os.remove` del chunk entero: la cola no usada **se destruye** en vez de volver a `pool/`. `take_chunk` ya sabe hacerlo. ⚠️ Matiz medido: con los 50 shorts naturales, los offsets barren el chunk entero, así que solo hay desperdicio real cuando los shorts van capados |
| 3 | **Salto del truncado** | Ver §1.1. **Diego aún no ha juzgado si es tolerable**: está en `output/video_002_final.mp4`, alrededor del minuto 17-18 |
| 4 | **`client_secret.json`** | Acción de Diego. Sin él no hay subida. `data/client_secret.json`, y faltan `googleapiclient`/`google_auth_oauthlib` en `requirements.txt` |
| 5 | Directrices de competencia en shorts | `trend_advisor.py:423` solo inyecta en `reddit_story.txt`. ⚠️ Los prompts se releen EN CALIENTE: no los edites con una corrida en marcha |
| 6 | Escaneo de competencia programado | Hoy solo manual |
| 7 | Miniatura ilegible en móvil | Medido por un agente, **no verificado a mano**: 34 palabras → 5,8 px de altura de letra |
| 8 | Molde de títulos de shorts | **Decisión tomada: NO se toca.** Se revisa cuando haya 50 títulos nuevos, con datos |

---

## REGLAS DE ESTA SESIÓN

- **En serie.** `pipeline.log` es ruta fija, `cleanup_temp` hace `rmtree` del temp compartido y
  `assets/.tint_index` es read-modify-write sin lock.
- **`--keep-temp` obligatorio** en cualquier corrida que vayas a medir.
- **Intocables:** `input/`, `test_e2e/clip.mp4`, `data/evidence/`. Nada está en git. **Nunca
  sobrescribas un JSON de `data/eval/`**: escribe `-v2`, `-postfix`…
- `git commit -m "pre-fix ..."` antes de editar, **nunca `git add -A`** (añade por ruta explícita), y
  **nunca `git push`** sin que Diego lo pida en ese mismo mensaje.
- **Verificación por EJECUCIÓN.** Pega la salida real.

## TRAMPAS DE MEDICIÓN YA PAGADAS

1. **Un mock no puede ver que el modelo no responde lo que se le pide.** Tres fallos del 12-ago pasaron
   los tests de los subagentes con `_call_openrouter` monkeypatcheado y **solo aparecieron contra la
   API real**: `max_tokens=200` (5 de 5 intentos devolvían razonamiento), `Another option: "..."` en el
   campo de título, y un `NameError` que compilaba limpio. **Prueba contra la API real lo que vaya a
   producción.**
2. **La mediana esconde el defecto local.** Mira el peor tramo y el min/max, nunca solo la mediana.
3. **Medir pausas sobre la alineación que juzgas es CIRCULAR.** Usa `silencedetect` sobre el WAV.
4. **`/eval` no es determinista** [GATE-03]: genera una historia nueva cada corrida, así que su
   comparación contra baseline **no distingue un cambio de código de otra tirada del modelo**. La
   dispersión propia del fixture en 5 corridas es media 0,043-0,112 y máx 0,32-0,88. Para llamar
   regresión a algo hace falta un **A/B controlado** (misma entrada, dos códigos).
5. **Comprueba con qué commit se produjo un artefacto** antes de llamarlo defecto (`mtime` contra
   `git log`). Dos falsos positivos costó no hacerlo [REVIEW-01].
6. Un guardia nuevo que da **cero en verde** es sospechoso, no tranquilizador.
7. `--no-shorts` oculta una clase entera de fallos · `--dry-run` valida la historia, no la cadena.

## ENTREGABLE

Por cada una de las 7 decisiones de la PARTE 1: **se queda / se cambia / no concluyente**, con la
medición que lo sostiene. Luego lo que se cierre de la PARTE 3. Entrada factual en
`.claude/incident-ledger.md` por cada defecto nuevo — **el retro no escribe reglas, solo `/optimize`
promueve**. Y el gasto de peticiones por vídeo recalculado si tocaste algo que lo mueva.

"No concluyente" es una respuesta válida y preferible a inventar una recomendación.
