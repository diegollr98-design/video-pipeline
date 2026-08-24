> ⛔ SUPERADO — no ejecutar.

# SEED — Caza de bugs en el pipeline y el dashboard

> ⛔ **REEMPLAZADO — NO EJECUTAR.** Usa **`SEED_D_caza_bugs.md`**, que acota la propiedad de
> ficheros para poder correr en paralelo con los otros tracks.


> PASO 0 OBLIGATORIO: invoca /seed-review sobre este SEED antes de tocar nada.

## Qué es esto

Revisión en busca de bugs de `c:\Users\diego\Desktop\YOUTUBE`: el pipeline
(`main.py` + `modules/`) y el dashboard (`dashboard.py` + `dashboard_runner.py`).

El proyecto genera vídeos de YouTube sin intervención humana: gameplay de Minecraft +
historia narrada + subtítulos + intro + miniatura, más shorts verticales. Lee `CLAUDE.md`
primero: documenta la arquitectura y, sobre todo, **los bugs ya encontrados y por qué
se escaparon**. Esa sección es tu mejor guía de dónde mirar.

## Regla de oro de este proyecto

**Auditar con ejecución real.** Los bugs de este repo NO se ven leyendo el código: se
ven ejecutándolo y mirando la salida. Ejemplos reales, todos encontrados así:

- `_concat_segments` llevaba roto **desde siempre** y nadie lo sabía, porque el único
  vídeo que se había procesado tomaba un atajo que no pasaba por ahí.
- Los subtítulos iban 1,5s por detrás de la voz en un vídeo que se había dado por bueno
  tras comprobar que los ficheros existían y que el log no daba errores.
- Los 4 shorts de una corrida contaban la misma historia. El log decía "completado".
- Un short salió con 4,5 segundos y el razonamiento del modelo como título. Exit code 0.

Si tu conclusión es "esto parece correcto", ejecútalo antes de escribirlo.

## Cómo ejecutarlo

Reparte por áreas y trabaja en paralelo. Sugerencia de reparto (ajústala si ves mejor
manera, pero cubre todo):

1. **Ingesta y pool** — `modules/video_cleaner.py`, `modules/gameplay_pool.py`
2. **Generación de texto** — `modules/script_generator.py`, `modules/shorts_generator.py`, `prompts/`
3. **Audio y subtítulos** — `modules/tts_engine.py`, `modules/subtitle_builder.py`
4. **Composición e imagen** — `modules/video_composer.py`, `modules/thumbnail_generator.py`
5. **Orquestación** — `main.py`, `modules/utils.py`, `config.yaml`
6. **Dashboard** — `dashboard.py`, `dashboard_runner.py`
7. **Competencia** — `modules/competitor_scout.py`, `modules/trend_advisor.py`

## Clases de bug que YA han aparecido aquí (busca más de lo mismo)

- **Rutas relativas donde la herramienta espera otra cosa.** El demuxer `concat` de
  FFmpeg resuelve las rutas del fichero de lista respecto al directorio de ESE fichero,
  no respecto al cwd. Revisa todo paso de rutas a ffmpeg, a Streamlit y a subprocess.
- **Errores que se tragan el mensaje útil.** Se registraban los primeros 500 caracteres
  de stderr de FFmpeg, que son el banner de compilación; el error real quedaba fuera.
  Busca `[:N]` sobre stderr y logs que corten por el principio.
- **Estado que se corrompe de forma permanente por un fallo transitorio.** Un corte de
  cuota marcaba canales como "sin vídeos" para siempre y la lista se vaciaba sola.
  Busca escrituras de estado que no distingan "no hay datos" de "no pude leerlos".
- **Salida del LLM sin validar.** Cualquier `_call_openrouter` cuyo resultado se use sin
  comprobar. Hay 3 sitios con guardia; comprueba que no falta ninguno.
- **Invariantes implícitos entre módulos.** `main.py` cuenta palabras del título para
  saber cuándo acaba la intro; cualquier transformación de texto que cambie el número de
  palabras rompe la animación sin dar error.
- **Config que miente.** `target_wpm` decía 150 cuando la voz habla a 200, y se tiraba el
  31% del gameplay sin que nada fallara. Busca constantes que nadie ha vuelto a medir.
- **Claves de config muertas.** `max_retries` estaba en `config.yaml` y el código lo
  ignoraba. Busca más claves declaradas y no usadas, y al revés: valores hardcodeados
  que deberían leerse de config.

## Puntos específicos del dashboard

- `st.stop()` dentro de una pestaña **corta todo el rerun** y deja sin renderizar las
  pestañas siguientes. Ya pasó una vez; por eso la pestaña Competencia vive en una
  función con `return`. Comprueba que no se ha colado otro `st.stop()`.
- El dashboard lanza el pipeline como **subproceso**, nunca importando funciones de fase
  (por logging duplicado, caché global de Whisper y el objeto `args`). La única excepción
  documentada es `competitor_scout`. Verifica que no se ha roto esa regla.
- `dashboard_runner.stop_run` mata el árbol de procesos con `taskkill /T`. Comprueba que
  se lleva de verdad a los ffmpeg hijos y que no deja ficheros a medias.
- Estado entre reruns: `st.session_state["run"]`, botones que disparan `st.rerun()`,
  y qué pasa si el usuario recarga la página con una corrida en marcha.
- Rutas y escrituras: el editor de config escribe `config.yaml` con backup `.bak` y
  **pierde los comentarios del YAML** (hay muchos, y documentan decisiones medidas).
  Evalúa si eso es aceptable o es un bug.
- Comprueba el dashboard con `streamlit.testing.v1.AppTest`, que ejecuta el script de
  verdad y captura excepciones. Prueba los dos caminos: con y sin `YOUTUBE_API_KEY`.

## Qué NO tocar

- **`input/`**: 13 GB de gameplay del usuario.
- **`data/`**: estado acumulado de competencia (221 canales descubiertos). Si necesitas
  un `data/` limpio, muévelo y restáuralo. Ya se borró una vez por un test.
- **`.env`**: contiene `OPENROUTER_API_KEY` y `YOUTUBE_API_KEY` reales.
- No hace falta procesar los 13 GB para un E2E: extrae un clip de ~3 min a un `input_dir`
  propio y baja `target_duration_min`. Receta en `CLAUDE.md`.

## Presupuesto

- OpenRouter: 1000 peticiones/día a modelos `:free`. Compartido entre agentes.
- YouTube Data API: 10.000 unidades/día. Un escaneo completo gasta ~470; re-medir, ~120.
  El gasto se contabiliza solo en `data/competitors.json`, así que si lo mueves, el
  contador se reinicia y puedes pasarte sin enterarte.

## Entregable

Una lista de bugs ordenada por gravedad. Para cada uno:

- **Qué falla y dónde** (`fichero:línea`).
- **Cómo reproducirlo** — el comando o script exacto, no una descripción.
- **Qué pasa de verdad vs qué debería pasar**, con la salida real pegada.
- **Impacto**: ¿rompe la producción, degrada la calidad en silencio, o es cosmético?
- Propuesta de arreglo, sin aplicarla.

Prioriza los que **fallan en silencio**: en este proyecto son los caros, porque el
pipeline es autónomo y nadie mira mientras corre. Un crash se ve; un vídeo con los
subtítulos descuadrados o cuatro shorts idénticos se sube a YouTube.

Si no encuentras nada en un área, dilo explícitamente en vez de rellenar con hallazgos
menores. Y marca por separado lo que has **verificado ejecutando** de lo que solo has
**leído**.
