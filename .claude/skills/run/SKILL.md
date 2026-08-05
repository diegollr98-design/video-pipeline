---
name: run
description: Levanta el dashboard de YOUTUBE o lanza el pipeline, y verifica que arranca limpio con la salida REAL. Úsalo para comprobar un cambio en la app real, no solo que compile.
allowed-tools: Bash, Read, Glob, Grep
---

# /run — Levantar el dashboard / lanzar el pipeline

Verificar un cambio en la app **real**. `compileall` limpio y el dashboard roto es un estado
perfectamente posible en Streamlit, y el pipeline "terminando" no significa que la salida sirva.

## A. Comprobar sintaxis primero (barato, caza el 90%)

```bash
PYTHONUTF8=1 python -m compileall -q modules main.py dashboard.py dashboard_runner.py
```

## B. Dashboard

```bash
streamlit run dashboard.py --server.headless true --server.port 8501
```

Correr **en background** y capturar la salida. Un arranque limpio no imprime tracebacks.
**Un `Traceback` en el arranque es un fallo aunque la página cargue** — Streamlit renderiza
parcialmente y esconde el error abajo.

Comprueba que las 7 pestañas montan (Roadmap, Estado, Operar, Progreso, Resultados, Competencia,
Config). Recuerda que `st.components.v1.html` (diagrama del Roadmap) está deprecado desde 2026-06-01:
un warning ahí es esperado, un error no.

## C. Pipeline

```bash
python main.py --dry-run                          # solo historia — valida prompt/modelo, NO la cadena
python main.py --config test_e2e/config.yaml      # cadena entera sobre el clip corto
python main.py --config test_e2e/config.yaml --skip-ingest   # solo produce del pool de test
```

**`--dry-run` no valida el vídeo.** Para cerrar un cambio de composición, alineación o shorts hace
falta la cadena entera, y eso es `/eval` — no `/run`.

**Nunca uses `--no-shorts` para verificar** algo que los shorts comparten.

## D. Reportar la salida REAL

Pega el log, no escribas "arranca bien". Y para FFmpeg, lee el **final** de stderr: los primeros 500
caracteres son el banner de compilación y el error real queda fuera.

## Gotchas de este entorno (Windows)

- **Encoding:** prefija `PYTHONUTF8=1` si aparece `UnicodeDecodeError` — los nombres de archivo de
  gameplay y los títulos llevan tildes y emojis.
- **PowerShell:** `;` para encadenar, no `&&`. El tool de Bash (Git Bash) sí acepta `&&`.
- **No dejes procesos huérfanos.** Si arrancas Streamlit en background, **páralo al terminar**: un
  puerto ocupado hace que el siguiente arranque falle con un error que no tiene nada que ver con tu
  cambio, y se diagnostica mal. Lo mismo con FFmpeg — un render de 40 min en background consume la CPU
  de la siguiente verificación (`-threads 4` existe justo para eso).
- **Una corrida real gasta cuota**: peticiones del tope de 50/día de OpenRouter. `--dry-run` también.

## REGLAS

- **Nunca** reportar "funciona" sin haber visto la salida del arranque.
- **Nunca** dejar Streamlit o FFmpeg huérfanos.
- Si el cambio toca una superficie sensible → **`/run` no basta**: corre `/eval`.
