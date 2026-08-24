> 🔵 ABIERTO.

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

## 🔴 EXCLUSIÓN MUTUA CON EL TRACK C — léelo antes de la primera llamada

**Puede haber otra sesión trabajando en este mismo repo a la vez que tú: el track C
(`SEED_C_competencia.md`).** Es el único otro track que toca la API de YouTube, y comparte contigo
el contador de cuota. **NO asumas que está o que no está corriendo: PREGÚNTASELO A DIEGO** antes de
tu primera llamada real. El contador vive en **`data/competitors.json`**, que es un fichero **sin lock**: si los
dos escribís a la vez se **pierden actualizaciones** y el corte preventivo deja de proteger — o sea,
te comes un `403` a mitad de una subida de 1,5 GB.

> **REGLA: solo UNO de B y C puede hacer llamadas REALES a la API de YouTube a la vez.**
> Tú gastas **1.650 unidades por vídeo** (1.600 `videos.insert` + 50 `thumbnails.set`) de un tope de
> **10.000/día**; C gasta ~470 por escaneo.

**Protocolo, obligatorio (no es prosa: son pasos que dejan rastro):**
1. **PIDE TURNO A DIEGO** antes de tu primera llamada real. No la hagas "solo para probar".
2. **Anota el contador ANTES**: lee `data/competitors.json` y pega el valor en tu informe.
3. Haz tu tanda de llamadas.
4. **Anota el contador DESPUÉS** y **comprueba que el delta es exactamente el que esperabas**
   (1.650 por vídeo subido). **Si no cuadra, otra sesión escribió encima: párate y avísale a Diego.**
   Ese descuadre es la firma de la actualización perdida, y es la única forma de detectarla.
5. Devuelve el turno diciéndolo explícitamente en tu informe final.

El arreglo de verdad —un lock atómico sobre el contador— **NO lo hagas ahora**: `QuotaMeter` vive en
`modules/competitor_scout.py`, que es **propiedad del track C**, y tocarlo desde aquí es justo la
colisión que este bloque existe para evitar. Regístralo en el ledger como deuda y sigue.

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

   ⚠️ **El refresh token CADUCA A LOS 7 DÍAS si la pantalla de consentimiento está en "Testing".**
   Verificado contra la fuente oficial (`developers.google.com/identity/protocols/oauth2`, 13-ago-2026):
   *"A Google Cloud Platform project with an OAuth consent screen configured for an external user
   type and a publishing status of 'Testing' is issued a refresh token expiring in 7 days, unless
   the only OAuth scopes requested are a subset of name, email address, and user profile."*
   El scope de este proyecto es `youtube.upload`, así que **NO** está en esa excepción.
   **Consecuencia:** en "Testing" el pipeline dejaría de subir cada semana y habría que re-autorizar
   a mano — lo contrario de autónomo. La salida es poner la app **"In production"**; el consentimiento
   mostrará una advertencia de app no verificada que hay que aceptar **una vez**.
   **Compruébalo tú antes de dar la subida por cerrada**: no basta con que funcione hoy. Y cuando el
   refresh token muera, el fallo tiene que ser **ruidoso y accionable** en el dashboard, no un error
   mudo en un log que nadie lee (§12, §13).
3. **El preflight de cuota infra-reserva 50 unidades.** `puede_subir` comprueba solo las 1.600 de
   `videos.insert`; una subida completa son 1.650. Entre 1.600 y 1.649 restantes el preflight sale
   verde, sube 1,5 GB y la miniatura falla por cuota → portada = fotograma al azar. Degrada bien,
   pero es justo el fallo que el preflight existe para evitar.
4. **DECIDIDO POR DIEGO (13-ago): la subida MANTIENE su OK en el dashboard.** No lo quites, no lo
   propongas, no lo "mejores" con un modo automático opcional. El motivo es sólido: el auditor ya
   dio verde a un vídeo que Diego rechazó de oído, así que la última puerta la abre una persona.
   El pipeline es autónomo **hasta dejar el vídeo en la cola**; publicar es un acto humano.
5. **Prueba el ciclo entero con un vídeo real** de `output/` (privado), incluida la miniatura, y
   comprueba en YouTube Studio que el título corto (`*_title_yt.txt`, ≤100 caracteres) llega bien.

## Techo duro: los shorts NO se pueden subir solos

51 subidas × 1.600 = **81.600 unidades** contra 10.000/día. Con cuota gratuita es **imposible**, y
> ⚠️ CORRECCIÓN (24-ago-2026): ese modelo de cuota era el VIEJO de Google. Hoy `videos.insert`
> cuesta **1** unidad y tiene cupo propio de **100 llamadas/día** (ver `QUOTA_BUCKET` en
> `competitor_scout.py`, con la cita oficial). La conclusión de no subir los shorts **se mantiene**,
> pero por otra razón: se saltarían la revisión humana. [QUOTA-02]
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
