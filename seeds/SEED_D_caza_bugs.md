> ✅ EJECUTADO (14-ago-2026).

# SEED D — Caza de bugs, sin pisar a los otros tracks

> PASO 0 OBLIGATORIO: invoca /seed-review sobre este SEED antes de tocar nada.

**Modelo de trabajo:** Opus 5 orquesta y audita, Sonnet 5 implementa (`CLAUDE.md` §ORQUESTACIÓN).
Cada bug → un subagente **`bug-hunter`** autocontenido y sin contexto, en paralelo; el orquestador
**valida el veredicto por ejecución ANTES** de aplicar el fix.
**Rama:** `git checkout -b fix/bugs`. **Nunca `git push`.**

## Corre en PARALELO — y eres el track con MÁS riesgo de colisión

Los otros tres tracks están editando ficheros concretos ahora mismo. Por eso aquí manda una regla
que no tiene ningún otro seed:

> **Si el bug está en un fichero de otro track, NO lo arregles: repórtalo.** Escribe el hallazgo con
> su evidencia en `.claude/incident-ledger.md` y sigue.

| Fichero | Dueño | Tú |
|---|---|---|
| `modules/tts_engine.py`, `scripts/anchor_bench.py` | track A | reportar |
| `modules/youtube_uploader.py`, `requirements.txt`, `main.py` | track B | reportar |
| `modules/trend_advisor.py`, `competitor_scout.py`, `prompts/*` | track C | reportar |
| `dashboard.py` | tracks B y C | **reportar, nunca editar** |
| `config.yaml` | compartido | **no lo reescribas** |
| `modules/video_cleaner.py`, `gameplay_pool.py`, `video_composer.py`, `subtitle_builder.py`, `thumbnail_generator.py`, `shorts_generator.py`, `utils.py`, `dashboard_runner.py`, `scripts/*` (salvo `anchor_bench`) | **tuyos** | arreglar |

**Prohibido:** ejecutar `main.py` como pipeline (colisiona con el track E: `pipeline.log` es ruta
fija y `cleanup_temp` borra `temp/` entero) · gastar más de **10 peticiones** de OpenRouter.

## Dónde mirar — las clases que YA se escaparon aquí

`CLAUDE.md` §"Decisiones técnicas críticas" y `.claude/incident-ledger.md` son tu mapa. Las clases
con reincidencia probada, por orden de rentabilidad:

1. **`NameError` / variable fuera de alcance que `compileall` NO caza.** Tres episodios
   ([MAIN-01] y dos más el mismo día). En `main.py` **`logger` es local a cada función**. Pasa
   `python -m pyflakes` sobre todo el repo y un escáner AST propio para nombres usados en
   `except`/`finally` que solo se enlazan dentro del `try`.
2. **Guardia que existe pero no se aplica en todas las rutas** ([GUARD-01], [BASURA-01], [BASURA-02]).
   Para cada guardia: `grep -rn` su nombre, enumera **todos** los sitios que producen ese valor, y
   justifica cada hueco. La basura del modelo apareció por la cabecera, luego por el cuerpo, luego
   por la cola.
3. **Fix no propagado al gemelo** ([PATH-02], [LOG-02], [ANCLA-03]). Pares conocidos:
   `video_cleaner` ↔ `gameplay_pool` (FFmpeg + demuxer `concat` + logging de stderr) ·
   `video_composer` ↔ `shorts_generator` (intro, woosh, subtítulos, alineación).
   **El gemelo de shorts es el que nadie mira.**
4. **Fallback silencioso** ([§13]): `except: pass`, un valor por defecto que se traga un error, un
   segmento que falla y aun así entra en la lista de `concat`.
5. **Errores ilegibles**: FFmpeg se registra con el **final** de stderr, no con los primeros 500
   caracteres (que son el banner de compilación). Comprueba que no queda ningún sitio con el bug.
6. **Rutas relativas en un fichero de lista de `concat`**: el demuxer las resuelve respecto al
   directorio **del fichero de lista**, no del cwd. Ya rompió la ingesta entera durante meses.

## Dos hallazgos abiertos que puedes cerrar (medidos, no arreglados)

- **`--max-shorts` es inalcanzable desde el dashboard.** `dashboard_runner.build_command` solo emite
  `--video/--style/--dry-run/--skip-ingest/--no-shorts`; tampoco expone `--keep-temp`. Cualquier
  corrida lanzada desde el dashboard con un chunk de 33 min sigue produciendo ~50 shorts.
  `generate_per_video` de `config.yaml` **no limita** (solo se consulta cuando no hay duración).
  **`dashboard_runner.py` es tuyo; `dashboard.py` no** — si el arreglo necesita tocar la UI, repórtalo.
- **El auditor no tiene `try/except` por vídeo**: una excepción en uno mata `main()` y deja a
  **todos** sin veredicto, y sin veredicto la cola de subida queda bloqueada. `scripts/audit_run.py`
  es tuyo.

## Trampas de medición ya pagadas

1. **Comprueba con qué commit se produjo un artefacto** (`mtime` contra `git log`) antes de llamarlo
   defecto. Dos falsos positivos costó no hacerlo ([REVIEW-01]).
2. **Un mock no ve que el modelo no responde lo que se le pide** ([TITULO-02], [LLM-01]).
3. **Un guardia nuevo que da cero en verde es sospechoso**, no tranquilizador ([GATE-02]).
4. **Calibra el instrumento contra un caso de resultado conocido** antes de juzgar nada con él
   ([SYNC-01], [INSTR-01], [INSTR-02], [INSTR-05]). Un instrumento roto no da un error: da un
   veredicto equivocado con aspecto de evidencia.
5. **`--no-shorts` oculta una clase entera de fallos**; **`--dry-run`** valida la historia, no la cadena.

## Criterio de aceptación

Cada bug arreglado lleva: **fichero:línea**, el escenario concreto que lo dispara, la **salida real**
del repro antes y después, y los casos degenerados probados. Cada bug **reportado y no arreglado**
lleva su entrada en el ledger con la misma evidencia. `pyflakes` limpio sobre todo el repo.
**El retro no escribe reglas, solo `/optimize` promueve.**
