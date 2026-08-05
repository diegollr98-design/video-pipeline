# Loop de Producción — YOUTUBE

> **Tesis central:** el modo de fallo de este proyecto **no es que el pipeline pete**. Es que produzca
> un `video_XXX_final.mp4` **que parece terminado** y esté roto de una forma que nadie ve: los
> subtítulos un segundo por detrás de la voz, los 4 shorts contando la misma historia, la intro que se
> corta a mitad de la frase del título, la ingesta que descarta media grabación.
>
> **El pipeline es autónomo por diseño: nadie mira los 30 minutos de salida.** Esa es exactamente la
> propiedad que hace que un defecto silencioso salga caro — se sube a YouTube tal cual.
>
> **Y su límite, que es lo que hace honesto a este loop:** ningún agente puede verificar que una
> historia enganche ni que una voz suene natural. Lo verificable **por ejecución** es (1) que la voz y
> el subtítulo caen en el mismo instante, medido contra una transcripción independiente; (2) que las
> pausas caen en puntuación y no a mitad de idea; (3) que los artefactos existen, cuadran en duración y
> no se repiten entre sí. Todo lo demás es juicio, y el juicio lo pone Diego.

---

## §A — La regla madre: verificación por EJECUCIÓN, nunca por informe

**Ningún cambio se cierra con "reportó que está OK".** El orquestador corre él mismo el comando
(`ffprobe`, la medición de alineación, el `/eval`) y **pega la SALIDA REAL** en el siguiente paso. Un
resumen de un subagente no es evidencia; la salida del comando sí.

Esta regla no es teórica aquí: **todos** los bugs graves documentados en `CLAUDE.md` se cazaron
midiendo, y **ninguno** se habría cazado leyendo el código o confiando en que "el pipeline terminó".

| Bug | Lo que decía la señal fácil | Lo que dijo la medición |
|---|---|---|
| Demuxer `concat` | "la ingesta terminó" | nunca funcionó; rutas relativas mal resueltas |
| Subtítulos por detrás | "los subtítulos salen" | +0,435s de sesgo medio, 1,064s máximo |
| Shorts repetidos | "se generaron 4 shorts" | los 4 con el mismo argumento |
| Comas del prompt | "la regla está en el prompt" | 167, 129, **0 y 0** comas en 4 generaciones |

## §B — Superficies sensibles (calibrado de ceremonia)

El gate lo fija **qué costura se toca**, no cuántas líneas cambian.

**Superficies sensibles** → ritual completo: `/eval` obligatorio antes de cerrar + `output-audit`.

| Superficie | Dónde vive | Por qué es sensible |
|---|---|---|
| **alineación** | `tts_engine.py` (`align`, `_validate_and_fix_alignment`) | rompe el sincronismo de TODO el vídeo, y es invisible salvo midiendo |
| **limpieza de texto** | `tts_engine.py` (`_clean_speech_for_tts`, `_ensure_breathing_commas`) | alimenta al TTS **y** al emparejado palabra-a-palabra que sostiene los timestamps |
| **ingesta** | `video_cleaner.py`, `gameplay_pool.py` | un fallo aquí tira horas de gameplay y aborta la corrida entera |
| **historia** | `script_generator.py`, `prompts/*.txt` | el título forzado y la variedad de shorts son garantías impuestas en código (`decision-making.md` §17) |
| **composición** | `video_composer.py`, `subtitle_builder.py`, `shorts_generator.py` | PlayRes, posición, offset de audio y timing de la intro; los shorts son el gemelo que nadie mira |
| **cuota** | `_call_openrouter`, `competitor_scout.py` | 50 peticiones/día (OpenRouter free) y 10.000 unidades/día (YouTube API) son topes DUROS |

**Superficie única no sensible** → ceremonia mínima (leer, cambiar, comprobar que compila, decirlo):
copy del dashboard, un color de miniatura, un texto de log, una pestaña de Streamlit.

**INVARIANTES que viven en varios sitios** — tocar uno obliga a revisar todos:
- `_ensure_breathing_commas` **no puede cambiar el número de palabras** (las comas se pegan a la
  palabra anterior). `main.py` cuenta palabras para saber cuándo acaba el título: romperlo descuadra
  la intro de todos los vídeos, en silencio.
- La **posición de subtítulo** y el **PlayRes** son un par: `(960,540)`+`1920x1080` en largos,
  `(540,960)`+`1080x1920` en shorts. Cambiar uno sin el otro distorsiona el texto.
- **Vídeo largo y short comparten intro, woosh, alineación y subtítulos** con parámetros distintos.
  Enumera las dos etapas, no solo la función que estás tocando.

## §C — Tres capas de verificación

### Capa 1 — `/eval` sobre el clip E2E (el SUELO, y es determinista)
`test_e2e/` ya tiene el fixture: un clip corto + su propio `config.yaml` con `target_duration_min`
bajado. `/eval` corre el pipeline **entero** contra él y reporta métricas medidas contra un baseline.
No hace falta procesar los 13 GB para validar la cadena.

**La métrica primaria es el ERROR DE SINCRONISMO, no "el vídeo se generó".** Detalle completo del
gate, sus métricas y su veredicto: `.claude/skills/eval/SKILL.md`.

**Gate con dientes:** un cambio en superficie sensible **no se cierra** si `/eval` empeora respecto al
baseline. No es un aviso: es un no.

### Capa 2 — `output-audit` (agéntico, adversarial)
Subagente Opus, autocontenido, cuyo trabajo es **intentar demostrar que el vídeo está roto**, midiendo
los artefactos (ASS, WAV, MP4, títulos) — no viéndolo. Default escéptico: si no puede probar que una
propiedad se cumple, es un hallazgo.

**Refutación asimétrica:** el presupuesto va a las cosas que el pipeline **da por hechas**, no a las
que ya avisa. Un error que aborta la corrida lo ve Diego en el log en 10 segundos; un desfase de 400 ms
que crece dentro de la frase **no lo ve nadie** hasta que el vídeo lleva semanas publicado.

### Capa 3 — El ojo de Diego (la única verdad)
La validación E2E de ago 2026 se cerró revisando la salida **fotograma a fotograma**. Ninguna capa
automática sustituye eso para: si la historia engancha, si la voz suena natural, si la miniatura
llama, si la intro queda bien.

**Límite honesto:** las capas 1 y 2 verifican **sincronismo, estructura y coherencia**, no calidad.
La capa 3 no es opcional ni sustituible — pero su presupuesto es escaso (mirar 30 min cuesta 30 min),
así que **todo lo que sea medible debe medirse antes**, para que él mire solo lo que no lo es.

## §D — Trampas de medición ya conocidas (no las repitas)

1. **Fixture con texto repetido = medición falsa.** Repetir un párrafo para construir una frase larga
   hace que el emparejador enganche la copia equivocada: 2,525s de error "medido", **idéntico** en 3 de
   5 repeticiones. Un valor idéntico entre corridas es la firma del artefacto. Los fixtures de
   sincronismo llevan contenido **no repetido**.
2. **`--no-shorts` oculta una clase entera de fallos.** Los shorts repetidos vivieron ahí.
3. **Medir con `--dry-run`** valida la historia, no la cadena. Sirve para el prompt, no para cerrar un
   cambio de composición.
4. **Confundir `/api/v1/key` con `/api/v1/credits`** en OpenRouter: el primero da el tope de gasto
   configurado en la clave, **no el saldo**. Ya llevó a creer que había dinero cuando no lo había.

## §E — Retro y meta-mejora (cómo este loop se mejora sin derivar)

Dos leyes, heredadas del resto de repos y no negociables:

1. **El retro solo registra HECHOS → append a `.claude/incident-ledger.md`.** Cuando una corrida caza
   un defecto o toca superficie sensible, se añade una entrada **factual**: qué pasó, evidencia real
   (el comando y su salida), clase, id. **El retro NO edita reglas.** Una regla es una generalización
   sobre el futuro y eso no se verifica por ejecución; auto-aplicarla desde n=1 es sobreajuste.
2. **Escritor único de reglas: `/optimize`** (el GLOBAL, `C:\Users\diego\.claude\skills\optimize\` —
   este proyecto **no** define uno propio, a propósito: en `ecxm-ops` el `/optimize` de proyecto
   sombreaba al global, no sabía del ledger, y el loop de auto-mejora nunca llegó a activarse).
   Promueve incidente → regla solo con **≥2 incidencias independientes de la misma clase**, o **1 de
   clase irreversible** (gameplay original destruido, cuota agotada, vídeo publicado defectuoso).
   Cada regla nacida así se etiqueta con su `[id]`, y `/optimize` la retira si el id no reaparece en
   >5 sesiones (convergencia, no acumulación).
3. **Conjunto INMUTABLE** (solo Diego lo toca; ni `/optimize` ni ningún auto-proceso): el
   §"LO QUE NUNCA DEBES HACER" de `CLAUDE.md`, la lista de **superficies sensibles** (§B de este
   archivo) y las **reglas de oro**.
4. **Tope de meta-trabajo.** El retro son 2-3 líneas. Si mejorarse cuesta más que el trabajo real, la
   regla se rompió → para.
