> ⛔ SUPERADO — no ejecutar.

# SEED 2 — Subida automática a YouTube (el último paso para ser autónomo)

> ⛔ **SUPERADO — NO EJECUTAR.** La subida se implementó el 11-ago (OAuth, `subir_video`,
> `subir_miniatura`, cola con OK en el dashboard, preflight de cuota). Lo que queda vivo está en
> **`SEED_B_subida_youtube.md`**.


> PASO 0 OBLIGATORIO: invoca /seed-review sobre este SEED antes de tocar nada.

## Contexto

`c:\Users\<usuario>\Desktop\YOUTUBE` genera vídeos de YouTube y shorts verticales sin
intervención humana... hasta el último paso. El pipeline termina dejando en `output/`:

- `video_XXX_final.mp4`
- `video_XXX_thumbnail.jpg`
- `video_XXX_title.txt`

y en `shorts_tiktok/`: `short_NNN.mp4` + `short_NNN_title.txt`.

**El usuario los sube a mano.** `CLAUDE.md` declara el objetivo "Autónomo: el pipeline
funciona sin intervención humana", así que este es el hueco que lo cierra.

Lee `CLAUDE.md` antes de empezar.

## PREGÚNTALE AL USUARIO ANTES DE IMPLEMENTAR

Hay decisiones que no son técnicas y que cambian el diseño. **No las supongas.**

1. **Privacidad al subir.** ¿`private`, `unlisted`, programado con fecha, o `public`?
   Recomendación fundada: NUNCA público automático. En una sola corrida de pruebas
   salieron cuatro shorts contando la misma historia y un short de 4,5 segundos con el
   título "The user wants a viral micro-story script for YouTube Shorts/TikTok."
   Ambos fallos ya están arreglados, pero demuestran la clase de cosa que se escapa.
2. **Cuándo subir.** ¿Automático al terminar la producción, o un botón "Subir" en la
   pestaña Resultados del dashboard tras revisar?
3. **Qué subir.** ¿Vídeos largos, shorts, o ambos?
4. **Descripción y etiquetas.** ¿Plantilla fija, generada por el LLM, o vacía?
   Ojo: si la genera el LLM, son más peticiones del bote diario.
5. **Playlist / categoría** de destino.

## Restricciones REALES (medidas, no supuestas)

- **Cuota de YouTube Data API: 10.000 unidades/día.**
  - `videos.insert` cuesta **1.600 unidades**. Es de lejos lo más caro del proyecto.
  - `thumbnails.set` cuesta **50**.
  - Un vídeo largo con miniatura ≈ **1.650** → caben ~6 subidas al día.
  - **El análisis de competencia usa el MISMO bote**: un escaneo completo gasta ~470.
    Si subes 6 vídeos, no queda cuota para escanear. Hay que compartir presupuesto.
  - Ya existe un contador de cuota por día natural UTC:
    `modules/competitor_scout.py::QuotaMeter`, persistido en `data/competitors.json`.
    **Reutilízalo**, no crees un contador paralelo, o el corte deja de significar nada.
- **La subida requiere OAuth 2.0**, no vale la `YOUTUBE_API_KEY` que ya está en `.env`
  (esa solo sirve para leer datos públicos). Hace falta autorizar una vez con la cuenta
  del canal y guardar un token de refresco. El usuario tendrá que hacer ese paso a mano
  en el navegador: **prepáralo y guíalo con instrucciones claras**, igual que se hizo con
  la API key (hay un precedente en la pestaña Competencia del dashboard).
- **Dependencias**: el proyecto es deliberadamente ligero (`requirements.txt`). Valora
  `google-auth-oauthlib` + `google-api-python-client` frente a implementar el flujo con
  `requests` a pelo. Elige y **justifica**; si añades dependencias, actualiza
  `requirements.txt` con el comentario de para qué sirve cada una.
- **Coste $0**: la API de subida es gratuita dentro de la cuota. No introduzcas nada de pago.

## Lo que no puede fallar

- **Idempotencia.** Nunca subir dos veces el mismo fichero. Lleva registro de lo subido
  (con el videoId devuelto) y compruébalo antes de cada subida. Una doble subida gasta
  1.600 unidades y ensucia el canal.
- **Corte por cuota antes de intentarlo.** Si no quedan 1.650 unidades, no lo intentes:
  avisa y déjalo para mañana. Un 403 a mitad de subida de un fichero de 300 MB es peor.
- **Nada de fallos silenciosos.** Si una subida falla, tiene que verse: log ruidoso, el
  fichero NO marcado como subido, y el error real (no los primeros caracteres de una
  traza, que aquí ya ocultaron un bug: se registraba el banner de FFmpeg en vez del error).
- **Los shorts necesitan `#Shorts`** en el título o la descripción para que YouTube los
  trate como tales. Verifícalo, no lo des por hecho.
- **Reintentos**: las subidas son grandes (55-330 MB) y se cortan. Usa subida reanudable
  (resumable upload) si la biblioteca lo permite.

## Integración esperada

- Un módulo nuevo, `modules/youtube_uploader.py`, siguiendo la organización de
  `.claude/rules/file-organization.md`.
- Un flag en `main.py` (p. ej. `--upload`), coherente con los que ya existen
  (`--scan-competition`, `--apply-trends`, `--no-shorts`).
- Botón en la pestaña **Resultados** del dashboard, junto a cada vídeo, mostrando el
  estado (pendiente / subido / error) y la cuota restante del día.
- El dashboard lanza el pipeline como **subproceso**, nunca importando funciones de fase.
  Una subida desde el dashboard puede correr en proceso si es rápida y no toca logging
  global (hay precedente documentado con `competitor_scout`), pero justifícalo.

## Verificación exigida

- **Una subida real**, en privado, con un vídeo de prueba corto (los hay en `test_e2e/`).
  Comprueba en el canal que aparece con su título, su miniatura y su privacidad correcta.
- Comprueba el corte por cuota **forzando** el contador cerca del límite, sin gastar
  cuota real.
- Comprueba la idempotencia: lanzar dos veces no debe subir dos veces.
- No cierres esto con "el código parece correcto": en este repo los bugs pasan todos los
  checks estáticos y terminan con exit code 0.

## Qué no tocar

- `input/` (13 GB de gameplay del usuario), `data/` (estado de competencia acumulado),
  `test_e2e/clip.mp4` (fixture del gate).
- `.env` contiene claves reales: no lo commitees ni lo imprimas.
- No hagas `git push` salvo que el usuario lo pida en ese mismo mensaje.

## Entregable

El módulo funcionando, la salida real de la subida de prueba, las instrucciones de
OAuth para el usuario en un sitio visible (dashboard y `CLAUDE.md`), y el recálculo
del presupuesto diario de cuota contando ya las subidas.
