# SEED B — Que el vídeo se publique SOLO (último paso de "autónomo")

> PASO 0 OBLIGATORIO: invoca /seed-review sobre este SEED antes de tocar nada.

**Modelo de trabajo:** Opus 5 orquesta y audita, Sonnet 5 implementa (`CLAUDE.md` §ORQUESTACIÓN).
**Rama:** `git checkout -b feat/subida`. **Nunca `git push`.**

## Corre en PARALELO con otros tracks — respeta esto o rompes su trabajo

**Ficheros que te pertenecen:** `modules/youtube_uploader.py` · `requirements.txt` ·
`main.py` **solo el enganche de subida** · `dashboard.py` **solo la pestaña Resultados/Subida**.

**Prohibido:** ejecutar `main.py` como pipeline (produce vídeos: colisiona con el track E por
`pipeline.log`, que es ruta fija, y por `temp/`, que `cleanup_temp` borra entero) · editar
`modules/tts_engine.py`, `script_generator.py`, `trend_advisor.py`, `competitor_scout.py`,
`prompts/*` · reescribir `config.yaml` (si necesitas claves nuevas, **añade** un bloque al final
marcado `# [track B]`).

**Cuota de YouTube — coordinación obligatoria:** el contador vive en `data/competitors.json`, es un
fichero sin lock, y lo compartes con el track C sobre un tope de **10.000 unidades/día**. Una subida
completa son **1.650** (1.600 `videos.insert` + 50 `thumbnails.set`). **Solo uno de B y C puede
hacer llamadas reales a la vez**: confírmalo con Diego antes de la primera.

## Qué está YA hecho (no lo rehagas)

El 11-ago se implementó la subida: OAuth, `subir_video`, `subir_miniatura`, cola con OK en el
dashboard, veredicto del auditor bloqueando la cola, y preflight de cuota. **`SEED_2_subida_youtube.md`
está SUPERADO: no lo ejecutes.** Lee `modules/youtube_uploader.py` entero antes de escribir nada.

## Lo que falta, en orden

1. **`requirements.txt` no tiene `google-api-python-client` ni `google-auth-oauthlib`.** En una
   instalación limpia el uploader **no arranca**. Verificado hoy: el fichero lista 9 paquetes y
   ninguno es de Google. Es el arreglo más barato del repo y bloquea todo lo demás.
2. **`data/client_secret.json` no existe.** Lo crea Diego en Google Cloud Console (OAuth de
   aplicación de escritorio, API de YouTube Data v3 habilitada). Sin él **no puedes probar nada
   real**: hasta que lo tengas, trabaja contra respuestas simuladas — pero lee la trampa nº1 de abajo
   antes de fiarte de un mock.
3. **El preflight de cuota infra-reserva 50 unidades.** `puede_subir` comprueba solo las 1.600 de
   `videos.insert`; una subida completa son 1.650. Entre 1.600 y 1.649 restantes el preflight sale
   verde, sube 1,5 GB y la miniatura falla por cuota → portada = fotograma al azar. Degrada bien,
   pero es justo el fallo que el preflight existe para evitar.
4. **Decide con Diego si la subida sigue exigiendo su OK.** Hoy el dashboard pide confirmación a
   propósito. Quitarlo es media hora y convierte el pipeline en autónomo de verdad — **y también
   significa que un vídeo defectuoso puede publicarse sin que nadie lo mire**. El auditor ya dio
   verde a un vídeo que Diego rechazó de oído. **No lo decidas tú.**
5. **Prueba el ciclo entero con un vídeo real** de `output/` (privado), incluida la miniatura, y
   comprueba en YouTube Studio que el título corto (`*_title_yt.txt`, ≤100 caracteres) llega bien.

## Techo duro: los shorts NO se pueden subir solos

51 subidas × 1.600 = **81.600 unidades** contra 10.000/día. Con cuota gratuita es **imposible**, y
el uploader ya lo documenta. "Autónomo" solo puede significar el vídeo largo (1.650/día ⇒ 1 vídeo
diario). **No gastes tiempo intentando automatizar los shorts.**

## Trampas ya pagadas

1. **Un mock no ve que el modelo/servicio no responde lo que esperas.** Tres fallos del 12-ago
   pasaron los tests de los subagentes con la llamada monkeypatcheada y **solo salieron contra la
   API real** ([TITULO-02], [LLM-01]). Lo que vaya a producción, pruébalo contra la API real.
2. **Verde local ≠ funciona** ([MAIN-01]): el cableado del auditor petó en ejecución con un
   `NameError` teniendo `compileall` limpio y el dashboard arrancando. En `main.py` **`logger` es
   local a cada función**, no de módulo. Pasa `pyflakes`, no solo `compileall`.
3. **Un veredicto de auditoría CADUCA** desde hoy: `lee_veredicto` compara la huella de
   `audit_run.py`+`eval_sync.py`. Si tocas el auditor, los veredictos viejos dejan de valer **a
   propósito** — no lo "arregles" desactivándolo.
4. **Nunca `git push`** y nunca borres `output/`, `input/`, `pool/` ni `test_e2e/clip.mp4`.

## Criterio de aceptación

Un vídeo de `output/` sube a YouTube **en privado**, con su miniatura, su título corto correcto, el
contador de cuota descontando **1.650**, y el preflight cortando limpio cuando no quedan unidades.
Pega la **salida real** de la subida y el ID del vídeo. Entrada factual en `.claude/incident-ledger.md`
por cada defecto nuevo — **el retro no escribe reglas, solo `/optimize` promueve**.
