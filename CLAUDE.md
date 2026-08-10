# YouTube Automation — Reddit Stories + Minecraft Gameplay

Pipeline Python autónomo que genera videos de YouTube: historias estilo subforos narradas en español con subtítulos estilizados sobre gameplay de Minecraft.

---

## ⚠️ CÓMO TRABAJAR CON EL USUARIO (Diego) — LEER SIEMPRE PRIMERO

Diego pregunta/propone POCO; cuando lo hace es señal de ALTA prioridad y suele tener razón (detecta patrones bien). Detalle en `.claude/rules/decision-making.md`.

1. **Ancla en SU plan, no en la cultura del repo.** Los defaults conservadores (diff mínimo, "validar antes de actuar", no over-engineer) son para situaciones AMBIGUAS — **no overrides de un plan explícito**. Si declaró un plan, el trabajo que implica SE HACE.
2. **No re-litigues premisas que él no planteó.** Si ves un riesgo real, dilo en UNA línea con dato y sigue.
3. **Verifica con datos/código REALES ANTES de afirmar.** Lee el código, no la doc. Si te equivocas, corrige y avanza — **no compenses con más caveats**.
4. **Si pushea, repite, o dice "¿seguro?" → PARA.** Ha detectado algo que se te escapó. Reanaliza desde SU marco.
5. **No tengas miedo al código.** "No tocar nada" está mal calibrado cuando él pide acción.
6. Si el contexto es muy largo y notas que empiezas a repetir errores → **avísale y sugiere sesión fresca**.

## ⚙️ MODELO DE ORQUESTACIÓN

- **Opus (orquestador): gasta poco contexto.** Delega la implementación, revisa veredictos, **valida lo crítico por ejecución** y actúa directo solo en lo crítico.
- **Sonnet en paralelo = implementación.** Tareas independientes → varios subagentes `engineer` a la vez (un mensaje, varias tool calls).
- **Protocolo de bug:** cada bug → subagente **`bug-hunter`** (Opus, autocontenido, **sin contexto**, en paralelo) localiza la causa raíz con evidencia medida → el orquestador **valida** el veredicto **antes** de aplicar el fix.
- **Todo vídeo generado tras un cambio sensible** → subagente **`output-audit`** (Opus) intenta demostrar que está roto midiendo sus artefactos.
- **Gate con Diego tras cada hito:** entregar checklist "cómo probarlo" y **PARAR** hasta su OK.

## 🔁 EL LOOP QUE IMPORTA AQUÍ

El modo de fallo de este proyecto **no** es que el pipeline pete: es que produzca un vídeo **que parece terminado** y esté roto de una forma que nadie ve — subtítulos por detrás de la voz, 4 shorts con la misma historia, media grabación descartada en la ingesta. **Nadie mira los 30 minutos de salida**: por eso un defecto silencioso se sube a YouTube tal cual.

Los cuatro bugs graves de este repo produjeron **vídeos completos y reproducibles**. Lo que los delató fue **medir**.

- **Loop de Producción** (`.claude/rules/produccion-loop.md`) — cómo impedimos que salga un vídeo roto. Es el loop central.
- **Loop de Cambios** (`.claude/rules/change-loop.md`) — protocolo ante cualquier cambio.
- **Meta-loop** — `/optimize` (el GLOBAL) promueve incidentes del ledger a reglas. Es el **único** que escribe reglas.

## REGLAS DE ORO

- Antes de tocar código: `git commit -m "pre-fix [desc]"`. Después: `git commit -m "fix [desc]"`.
- **Verificación por EJECUCIÓN, nunca por informe.** Corre el comando tú y pega la SALIDA REAL. "Reportó que está OK" no cierra nada.
- **Una garantía prometida en el prompt no está garantizada hasta que un `if` la fuerza.** Ya falló tres veces aquí (comas, título, variedad de shorts).
- Cambios en **superficies sensibles** (alineación, limpieza de texto, ingesta, historia, composición, cuota — tabla en `produccion-loop.md` §B) → **`/eval` antes de cerrar** + `output-audit`.
- **El coste es cuota, no dinero:** 1000 peticiones/día en OpenRouter free (verificado ago 2026: 10 créditos comprados), 10.000 unidades/día en la YouTube API. Un cambio que sube las peticiones por vídeo se reporta aunque nadie lo pregunte.

## LO QUE NUNCA DEBES HACER

- **Cerrar un cambio sensible sin medir la salida.** El demuxer `concat` estuvo roto **desde siempre** terminando sin error.
- **Validar con `--no-shorts`.** Oculta una clase entera de fallos (los 4 shorts idénticos vivieron ahí).
- **Confiar en que el modelo obedezca el prompt** para algo que importa. Se impone en código o no está.
- **Borrar `pool/`, `input/`, `output/` o `test_e2e/clip.mp4`** — son horas de grabación y el fixture del gate.
- **Llamar a OpenRouter fuera de `_call_openrouter`** ni usar rutas relativas en un fichero de lista de `concat`.
- **Silenciar errores** (`except: pass`, fallback mudo, un segmento fallido que igualmente entra en la lista). Log ruidoso + propagar + marcar la salida.
- **Confundir `/api/v1/key` con el saldo** de OpenRouter (es el tope de gasto de la clave).
- **Commitear `.env`** o cualquier API key.
- **`git push` sin que Diego lo pida** en ese mismo mensaje.

## DETALLES → ver `.claude/`

| Archivo | Cuándo leerlo |
|---|---|
| `rules/decision-making.md` | cómo trabajar y decidir (agnóstico de dominio) |
| `rules/produccion-loop.md` | **el loop central**: superficies sensibles, 3 capas de verificación, trampas de medición |
| `rules/change-loop.md` | ante CUALQUIER propuesta de cambio |
| `rules/file-organization.md` | al crear un archivo o buscar dónde vive algo |
| `rules/sessions-log.md` | bitácora por hito (≤100 líneas) |
| `incident-ledger.md` | ledger append-only; **solo `/optimize` promueve** a regla |
| `agents/` | `engineer` (Sonnet) · `bug-hunter` (Opus) · `output-audit` (Opus) |
| `skills/eval` | **el gate**: corre la cadena sobre `test_e2e/` y mide |
| `skills/run` | levantar dashboard / lanzar pipeline y ver la salida real |
| `skills/daily-run` | loop diario con presupuesto de peticiones de OpenRouter |

**`/optimize` es el GLOBAL** (`C:\Users\diego\.claude\skills\optimize\`), a propósito: es el que conoce el ledger. Este proyecto **no** define uno propio — en `ecxm-ops` el `/optimize` de proyecto sombreaba al global, no sabía del ledger, y el loop de auto-mejora nunca llegó a activarse. No repetir ese fallo aquí.

---

## Stack

- **Python 3.x** — lenguaje principal
- **OpenRouter** (API gratuita) — generación de historias via `nvidia/nemotron-3-ultra-550b-a55b:free`
- **YouTube Data API v3** (10.000 unidades/día gratis) — análisis de competencia
- **Streamlit** — dashboard de operación
- **edge-tts** (gratis) — text-to-speech español de España (hombre/mujer auto)
- **stable-ts + faster-whisper** — forced alignment para subtítulos sincronizados al 100%
- **FFmpeg** — composición de video + audio + subtítulos + intro animada
- **Pillow** — miniaturas y title cards

## Pipeline

```
Fase 1 — Ingestión:
  input/*.mp4 -> video_cleaner (quita pausa/escritorio via hotbar detection)
    -> recodificación (13GB -> ~2GB, CRF 23)
    -> pool/ (cola de gameplay limpio)

Fase 2 — Producción (mientras pool >= 20 min):
  pool/ -> tomar chunk (20-39 min: usar todo, >=40 min: cortar en 30 min)
    -> OpenRouter (título largo 20-35 palabras + historia en bloques)
    -> título forzado al inicio del speech
    -> edge-tts (audio, voz hombre/mujer según protagonista)
    -> forced alignment (stable-ts + whisper small = timestamps exactos por palabra)
    -> subtitle_builder (SRT -> ASS, MAYÚSCULAS, Impact 150, centrado fijo)
    -> thumbnail_generator (gameplay blur + tinte color golden angle + plantilla + título)
    -> title_card (plantilla + título transparente para intro)
    -> video_composer:
        - intro animada (slide derecha->izquierda con rebote elástico)
        - woosh sound sincronizado con llegada al centro
        - intro visible hasta que narrador termina frase del título
        - fade out suave
        - subtítulos aparecen DESPUÉS de la intro
        - audio offset -100ms (voz siempre antes que subtítulo)
        - subtítulos desaparecen en pausas (solo gameplay visible)
    -> output/*.mp4 + *_thumbnail.jpg + *_title.txt

Fase 2b — Shorts (opcional, si enabled: true en config):
  pool/ -> para cada video generado:
    -> generar N shorts (~200 palabras cada uno)
    -> OpenRouter (micro-historia, estilo matching)
    -> edge-tts (normal speed) -> audio atempo x1.5 (preserva calidad)
    -> forced alignment -> escalar timestamps /1.5
    -> subtitle_builder vertical (font 80, pos center, skip intro)
    -> title_card vertical (1080x1920, template escalado)
    -> intro background (blur+tint, live gameplay)
    -> video_composer (crop 9:16, intro animada, woosh)
    -> shorts_tiktok/*.mp4 + *_title.txt

  sobrante -> queda en pool/ para próxima ejecución

Fase 3 — Competencia (independiente, no produce videos):
  config keywords + seed_channels
    -> search.list (100 unidades c/u) -> canales candidatos
    -> channels.list -> filtros (subs, idioma, país)
    -> playlistItems.list (uploads) + videos.list -> últimos N videos por canal
    -> filtro de formato (descarta canales solo-shorts)
    -> scoring: outlier (vistas/mediana del canal) + engagement + velocidad + frescura
    -> data/competitors.json (lista que crece) + data/competition_report.json
    -> OpenRouter debate el top-N -> veredicto + directrices + titulares
    -> data/competition_advice.json
    -> [con OK del usuario] inyección en prompts/reddit_story.txt entre marcadores
```

## Estructura

- `main.py` — orquestador + CLI
- `dashboard.py` — dashboard Streamlit (7 pestañas)
- `dashboard_runner.py` — lanza el pipeline como subproceso (funciones puras, sin Streamlit)
- `config.yaml` — toda la configuración
- `.env` — OPENROUTER_API_KEY, YOUTUBE_API_KEY
- `data/` — state de competencia, informes y consejos (generado, no versionado)
- `seeds/` — seeds de handoff a sesión fresca. **PASO 0 de cada uno: `/seed-review`**
- `assets/3.png` — plantilla miniatura/intro (PNG transparente)
- `assets/stereogenicstudio-swish-swoosh-woosh-sfx-27-357164.mp3` — woosh sound
- `assets/.tint_index` — rotación de color para miniaturas (golden angle)
- `prompts/reddit_story.txt` — prompt completo estilo "Dosis de Subforos"
- `prompts/short_story.txt` — prompt para micro-historias de shorts (~200 palabras)
- `modules/`
  - `video_cleaner.py` — detecta hotbar Minecraft, elimina pausa/escritorio/menús
  - `gameplay_pool.py` — cola de gameplay, recodificación, chunks 20-40 min
  - `script_generator.py` — genera historias en bloques via OpenRouter, título forzado al inicio
  - `tts_engine.py` — edge-tts + forced alignment (stable-ts/whisper), detección género
  - `subtitle_builder.py` — SRT -> ASS, MAYÚSCULAS, pos fija (960,540), skip durante intro
  - `video_composer.py` — FFmpeg: intro animada + woosh + subs + audio offset
  - `shorts_generator.py` — genera YouTube Shorts/TikToks (9:16, x1.5 speed, micro-historias)
  - `thumbnail_generator.py` — miniatura (blur+tinte+plantilla+título) + title card transparente
  - `competitor_scout.py` — YouTube Data API: descubre competidores, mide virales, puntúa
  - `trend_advisor.py` — debate LLM sobre qué atacar + inyección/reversión en el prompt
  - `utils.py` — utilidades (FFmpeg, config, dotenv, duración)

## Ejecución

```bash
streamlit run dashboard.py        # dashboard de operación (recomendado)

python main.py                    # ingesta + producción completa
python main.py --skip-ingest      # solo produce del pool existente
python main.py --dry-run          # solo genera historia sin video
python main.py --style horror     # override de estilo
python main.py --no-shorts        # sin shorts en esta corrida

# Competencia (no produce videos)
python main.py --scan-competition                 # escanea + debate, no toca el prompt
python main.py --scan-competition --apply-trends  # además inyecta las directrices
python main.py --scan-competition --no-discover   # solo re-mide conocidos (~90 unidades)
```

## Output por video

### Videos largos (output/)
Cada video genera 3 archivos en `output/`:
- `video_XXX_final.mp4` — video completo con intro, narración, subtítulos
- `video_XXX_thumbnail.jpg` — miniatura para YouTube (1280x720)
- `video_XXX_title.txt` — título para copiar a YouTube

### Shorts/TikToks (shorts_tiktok/)
Cada set de shorts genera 2 archivos por short en `shorts_tiktok/` (configurable):
- `short_NNN.mp4` — short vertical (9:16, 60-90s con speed x1.5)
- `short_NNN_title.txt` — título para copiar

## Especificaciones de edición

### Intro animada
- Plantilla con título (MAYÚSCULAS) sobre gameplay
- Entra de derecha a izquierda con rebote elástico (W * e^(-12t) * cos(18t))
- Woosh sound sincronizado con llegada al centro (pico a 0.25s)
- Visible mientras narrador dice la frase del título
- Fade out 0.8s cuando termina la frase
- Sin subtítulos durante la intro

### Subtítulos
- Palabra a palabra, MAYÚSCULAS
- Font Impact, tamaño 150, outline negro 8px
- Posición fija centro (960,540) — nunca se mueve
- Sincronizados via forced alignment (whisper small)
- Desaparecen en pausas entre frases (solo gameplay visible)
- Audio offset -100ms para que voz siempre preceda al subtítulo

### Voz
- Español de España
- Hombre (es-ES-AlvaroNeural) o mujer (es-ES-ElviraNeural) según protagonista
- Detección automática por patrones ("mi esposa" = hombre, "mi esposo" = mujer)
- Texto limpio: sin comillas, sin markdown, sin headers de bloques

### Miniatura
- Frame del gameplay con blur + tinte de color vibrante (rotación golden angle)
- Plantilla PNG superpuesta
- Título completo en MAYÚSCULAS, Arial Bold, auto-size
- Cada miniatura color diferente, nunca se repiten consecutivos

### Historia/Script
- Títulos largos (20-35 palabras) estilo competencia
- Primera frase del speech = título completo (forzado en código)
- Generación en bloques (~2000 palabras/bloque) para historias largas
- Narración fluida: párrafos continuos, sin fragmentar, sin diálogos con comillas

## Especificaciones de Shorts

### Formato
- Resolución: 1080x1920 (9:16 vertical)
- Duración: 60-90 segundos (a velocidad x1.5)
- Texto original: ~200 palabras

### Velocidad de narración
- TTS genera audio a velocidad normal (1x)
- Audio se acelera a x1.5 con FFmpeg atempo (preserva calidad sin artefactos)
- Todos los timestamps se escalan: divide por 1.5

### Subtítulos (Shorts)
- Font Impact, tamaño 80 (menor que videos largos)
- Outline negro 5px (más delgado, para verticalidad)
- Posición fija centro (540,960 en 1080x1920)
- MAYÚSCULAS
- **No aparecen durante la intro** (skip_until = título end time)

### Intro
- Title card vertical (1080x1920) con template escalado
- Intro background: blur + color tint (live gameplay, no static)
- Animación elástica (derecha->izquierda, rebote amortiguado)
- Woosh sound sincronizado
- Fade out cuando termina la frase del título

### Historia/Script (Shorts)
- Títulos cortos (10-18 palabras)
- Primera frase del speech = título completo
- Estructura comprimida: hook + contexto mínimo + injusticia + reacción + consecuencia
- Generación en UN solo bloque (~200 palabras)
- Sin diálogos directos (todo narración indirecta)

## Decisiones técnicas críticas (aprendidas en producción)

### Subtítulos — forced alignment
- **Modelo**: `small` (no `tiny` ni `base`) — mejor precisión en español no-inglés
- **Parámetros align()**: `nonspeech_error=0.3, gap_padding=None` — evita drift en silencios (Issue #468 stable-ts)
- **Anclas duras**: `_validate_and_fix_alignment` usa `SentenceBoundary` de edge-tts como anclas. Fija el INICIO de cada frase y **traslada** los tiempos de Whisper; NO los estira ni los sustituye
- **Por qué traslación y no reparto proporcional** (medido ago 2026, era la causa de que los subtítulos fueran ~1s por detrás de la voz):
  - edge-tts NO emite `WordBoundary` (0 eventos), solo `SentenceBoundary`: una ventana por frase
  - Esas ventanas **tilan el audio completo, silencios incluidos**: medido, terminan en 7.72s cuando la voz acaba en 6.76s. La ventana NO mide la frase hablada
  - El código anterior repartía las palabras linealmente por nº de caracteres **para rellenar la ventana entera**, empujando cada palabra más tarde de cuando suena. El retraso crecía dentro de la frase y se reseteaba en la siguiente
  - Colaba con frases cortas. Los modelos que escriben frases largas con comas producen ventanas de ~49 palabras y ~15s, y ahí el retraso llegaba a 1,5s
  - A/B contra una transcripción independiente: error medio 0.502s -> 0.146s, máximo 1.064s -> 0.248s, sesgo +0.435s (detrás) -> -0.146s (delante)
- Al trasladar, el silencio final de cada ventana queda libre: eso es lo que hace que el subtítulo desaparezca en las pausas, como pide la especificación
- **Gap compression bug**: al mover `start` hay que preservar `old_dur` y recalcular `end = new_start + old_dur` (si no, subtítulo congelado)
- **PlayRes en shorts**: `PlayResX: 1080, PlayResY: 1920` — si se deja en 1920x1080, el texto sale distorsionado en 9:16

### TTS — limpieza de comillas
- La clase de comillas en `_clean_speech_for_tts` DEBE incluir las tipográficas (`“ ” ‘ ’ „ ‟ ‹ ›`), no solo `"` y los guillemets. Las tipográficas llegaban intactas al TTS y al forced alignment, donde el emparejamiento palabra a palabra es lo que sostiene los timestamps
- No se notaba con Gemini; los modelos que escriben con tipografía correcta sí las emiten

### Subtítulos — posición
- Videos largos: `\pos(960,540)` con PlayRes 1920x1080
- Shorts: `\pos(540,960)` con PlayRes 1080x1920 (configurado via `play_res_x/y` en SHORT_SUB_CONFIG)

### FFmpeg — composición de shorts
- **NO usar `-hwaccel cuda`** con filtros CPU (ass, boxblur, overlay) — causa transferencias GPU↔CPU constantes → 10-15 min por short
- **boxblur lento**: `boxblur=25:25` en 1080x1920 = 2M píxeles × 25 iteraciones = muy lento. Usar `scale=iw/6:-1,gblur=sigma=20,scale=1080:1920` (36x más rápido, resultado visual idéntico)
- **stream_loop + -ss**: funciona bien, `-ss` antes de `-i` hace seek del input correctamente

### FFmpeg — demuxer concat (bug encontrado en el E2E de ago 2026)
- El demuxer `concat` resuelve las rutas relativas del fichero de lista **respecto al directorio de ese fichero**, NO respecto al cwd. Con `temp_dir: "./temp"`, la línea `file './temp/segment_000.mp4'` dentro de `./temp/concat_list.txt` se resolvía como `./temp/./temp/segment_000.mp4` y fallaba siempre
- Consecuencia: `_concat_segments` **nunca funcionó**. La única corrida real que existía (jun 2026) se salvó porque su vídeo era >95% gameplay y toma el atajo de recorte simple con `-ss/-to`, sin pasar por concat. Cualquier grabación con pausas —el caso para el que existe el módulo— abortaba la ingesta entera
- Arreglado escribiendo rutas **absolutas** en la lista. Además, un segmento que falla al extraerse ya no se añade a la lista (antes reventaba el concat con un error incomprensible)
- Los errores de FFmpeg se registran con el **final** de stderr, no el principio: los primeros 500 caracteres son el banner de compilación y el error real quedaba fuera del log

### FFmpeg — encoding
- Preset `p2` (no `p4`) — YouTube recomprime de todos modos, misma calidad percibida
- `-threads 4` — limita uso de CPU, evita que congele el PC durante producción

### Shorts — repetición de historias (bug encontrado en el E2E de ago 2026)
- Cada short es una llamada independiente con un prompt IDÉNTICO, así que el modelo
  producía siempre la misma historia. Medido en una corrida real, los 4 shorts salieron
  con el mismo argumento y solo cambiaba el final:
  *"Mi Hermano Vendió Mi Coche Clásico Para Pagar Sus Deudas Y La Policía..."* /
  *"...Sin Pedirme Permiso"* / *"Mi **Hermana** Vendió Mi Coche..."* / *"...Y Lo Denuncié"*
- La regla del prompt "la historia debe ser DISTINTA a cualquier otra" no servía de nada:
  el modelo no podía saber cuáles eran las otras
- Arreglado pasando los títulos ya generados en el prompt (`avoid` en `generate_short` ->
  `_build_avoid_block`). `generate_short` ahora **devuelve el título** y
  `generate_shorts_for_video` lo acumula
- También arrastra los títulos de shorts anteriores que sigan en `shorts_dir`, para que dos
  corridas seguidas no produzcan lo mismo. Se limita a los 12 últimos para no inflar el prompt
- Ojo al validar shorts: correr con `--no-shorts` oculta esta clase de fallo por completo

### Shorts — generación
- `generate_per_video` se calcula dinámicamente: `chunk_duration / (target_words/wpm * 60 / speed)`
- Cada short usa offset diferente de gameplay: `offset = i * short_real_dur`
- Conteo de shorts desde disco (`len(glob(...))`) para evitar colisiones de numeración

### Competencia — cuota de la YouTube API
- `search.list` cuesta **100 unidades**; `channels.list`, `playlistItems.list` y `videos.list` cuestan **1** (hasta 50 IDs por llamada)
- Por eso los últimos videos de un canal se leen por su **playlist de subidas**, NO con search. Un escaneo de 40 canales cuesta ~90 unidades; el gasto dominante son las búsquedas de descubrimiento
- El gasto se contabiliza por día natural (UTC) en `data/competitors.json` y se corta **antes** de que Google devuelva 403
- Las keywords **rotan** entre escaneos (`keyword_offset` en el state): con 4 búsquedas por corrida y 8 keywords, no se gastan siempre las mismas

### Competencia — scoring de virales
- El **outlier** (vistas / mediana del propio canal) NO se puntúa por percentil sino con curva logarítmica saturada (`outlier_cap`). Medido: por percentil, un video a x11.7 (2.4M vistas) quedaba **por debajo** de otro a x1.9, porque el percentil solo ordena y ambos caían en los dos primeros puestos (1.00 vs 0.95)
- Engagement, velocidad y frescura **sí** van por percentil dentro del corpus escaneado: eso es lo que los auto-calibra al nicho sin umbrales inventados
- `metrics_partial` marca los videos cuyo canal oculta likes/comentarios, para no leer engagement 0 como "video malo"

### Competencia — descubrimiento (aprendido con la API real)
- **Las keywords deben apuntar al FORMATO, no solo al tema.** Buscando por tema ("mi suegra me humilló") entran canales de terror, novelas chinas dobladas y cortometrajes que compiten en otra liga. Buscando "historias de reddit minecraft" aparecieron los competidores reales: Lo Redditor (542k subs), Historias Reddit (236k), HISTORIAS DE LA RED, Poro-Snax
- **`topicDetails` es la única pista de gameplay** y sale gratis (en la API v3 el coste es por método, no por part). Da 0% en canales de otro formato y 60-100% en los que sí narran sobre gameplay. NO sirve como filtro duro (`require_gameplay` existe pero va desactivado): un canal real puede no emitirla
- **Suelo de vistas obligatorio** (`scoring.min_views`): un canal con mediana de 47 vistas colocó un video de 286 vistas en el puesto 4 del ranking. xN sobre una mediana ridícula es ruido, no viralidad
- **El heurístico de idioma no puede usar palabras ambiguas**: con "me" y "y" dentro, el título inglés "a dream made me kiss my friend and now we're both g@y" puntuaba como español (la `y` sale de "g@y") y colaba un canal inglés en el puesto 2. Ahora exige ganarle a un set de marcadores ingleses, y las grafías ñ/tildes/¿¡ valen doble
- **Sin texto suficiente NO se rechaza por idioma**: se aplaza al filtro de contenido, que juzga por títulos de videos. Rechazar de golpe tiraba a rBarra Historias (124k subs) y Venganza En Solitario (58.9k), españoles ambos, solo por tener la descripción del canal vacía
- **Los rechazos se reconsideran** (`revive_rejected`): al cambiar los filtros de `discovery` o pasar `recheck_rejected_after_days`, los rechazos no permanentes se re-cualifican con los datos ya guardados, sin gastar cuota. Sin esto, un filtro mal calibrado dejaba canales muertos para siempre
- **Un corte de cuota no debe rechazar canales**: si hay IDs de video pero no llegan datos, se deja el canal intacto para la próxima corrida. Antes quedaba marcado "sin videos recientes" de forma permanente y la lista se vaciaba sola
- **El `keyword_offset` avanza solo por búsquedas realmente hechas**, y se reinicia si cambia la lista de keywords (huella en el state). Si no, las keywords nuevas tardaban varios escaneos en entrar en rotación

### Competencia — clasificación de nicho (por qué la hace un LLM y no un heurístico)
- El nicho es "historias de Reddit narradas en primera persona sobre gameplay". Buscando por tema entran **granjas de drama asiático doblado** (Oro Drama, ReyDrama, ChiNo Drama, Silk Heart Drama, Gatito Giratorio…), películas, cortometrajes y podcasts de terror
- Se probaron tres heurísticos y **ninguno separa**:
  - `topicDetails` de gameplay: 0% en canales de otro formato, 60-100% en los buenos, pero un competidor real puede no emitirla
  - Puntuación CJK (`【】`) en títulos: precisa pero solo caza a los que no traducen los corchetes (1 de 13 de la granja)
  - Ratio de primera persona en títulos: da 0% en rBarra Historias (competidor real, 124k subs) y 25% en Cuando Los Ángeles Caen (líder, 1M de mediana), pero 75% en Gatito Giratorio (drama doblado). Cualquier umbral mata competencia real o deja pasar la granja
- Por eso `trend_advisor.classify_channels` le pasa 4 títulos de muestra por canal al LLM. Es coste $0, se pregunta **una sola vez por canal** (`llm_in_niche` queda en el state) y si falla el escaneo continúa sin clasificar
- **Lotes de 8, no de 25**: con 25 el modelo devolvió veredicto de 3 canales y se saltó 49 en silencio. Los canales que el modelo omite se quedan activos y se avisa por log
- Los heurísticos se conservan como **columnas informativas** (`gameplay_ratio`, `first_person_ratio`) para curar la lista a mano desde el dashboard

### Competencia — inyección en el prompt
- `prompts/reddit_story.txt` se consume con `str.format(target_words=, style=)`. El texto generado por el LLM se inyecta con **llaves duplicadas** (`{` -> `{{`): una llave suelta reventaría `generate_story` con `KeyError` a mitad de una historia de 8 bloques
- El bloque va entre marcadores (`BEGIN_MARK`/`END_MARK`) justo antes de `Historia:`. Aplicar es idempotente y `remove_from_prompt` devuelve el prompt **byte a byte** al original

### OpenRouter — modelo y reintentos
- `google/gemini-2.0-flash-001` fue **retirado** de OpenRouter (404 "no endpoints found") y ya no queda ningún Gemini gratuito
- Sustituto validado contra el prompt real: `nvidia/nemotron-3-ultra-550b-a55b:free` (título de 34 palabras cumpliendo la regla 20-35, ~1900 palabras/bloque, ~80s)
- Descartado: `inclusionai/ling-3.0-flash:free` — rápido pero no separa título y speech con línea en blanco, y `_parse_title_and_speech` se traga el primer párrafo entero como título (543 palabras)
- `_call_openrouter` reintenta 429/5xx **y el caso de 200 sin `choices`**: los modelos free devuelven a veces un 200 con cuerpo de error, y sin ese guardia reventaba con `KeyError('choices')`
- **Nemotron es un modelo de razonamiento**: a veces escribe su razonamiento en voz alta, agota el presupuesto y devuelve un fragmento sin formato (medido: 448 caracteres, cero secciones). Por eso `_call_openrouter` acepta `max_tokens` y `trend_advisor.debate` valida las secciones y reintenta con una instrucción más dura en vez de guardar un consejo vacío

### Intonación variable de voz
- **Inevitable** con edge-tts (servicio Microsoft, sin control de prosodia)
- Solución real requeriría Azure Cognitive Services con SSML completo (de pago)

### El modelo suelta su razonamiento: validar SIEMPRE la salida
- `nvidia/nemotron-3-ultra` razona, y de vez en cuando escribe el razonamiento en vez de la historia. Caso real: un short salió con el título **"The user wants a viral micro-story script for YouTube Shorts/TikTok."** y un vídeo de 4,5s
- Es grave porque el título va a la MINIATURA y a la INTRO del vídeo largo
- `script_generator._validar_salida` lo comprueba y ambas rutas (historia larga y short) reintentan con una instrucción más dura. Verifica: longitud de título plausible, sin marcadores de razonamiento (`the user`, `here is`, `el usuario quiere`, ```` ``` ````, `Titulo:`…), que parezca español, y speech con cuerpo suficiente
- El mismo patrón ya estaba en `trend_advisor.debate`; si se añade otra llamada al LLM, ponerle su guardia

### OpenRouter — tope DIARIO de peticiones (no es cuestión de dinero)
- Los modelos `:free` tienen un límite de **peticiones al día**, no solo de rate: con menos de 10 créditos comprados son **50/día**; a partir de 10 créditos, 1000/día. El error es `429 Rate limit exceeded: free-models-per-day`
- Un vídeo de 30 min son 3 bloques de historia + 45 shorts = **48 peticiones** (suelo, cero reintentos; recalculado ago 2026 tras separar `shorts.narration_wpm` de `story.target_wpm`), más el análisis de competencia (5-15)
- **Estado de la cuenta: 10 créditos comprados, saldo 9,94 USD → tope de 1000 peticiones/día** (VERIFICADO 10-ago-2026 con `GET /api/v1/credits` → `{'total_credits': 10, 'total_usage': 0.0638}`, `is_free_tier: False`). Con eso caben **~20 vídeos/día**, así que la cuota dejó de ser el cuello de botella: ahora lo son el reloj y el disco
- ⚠️ Este apartado dijo durante meses "0 créditos, saldo −0,06 USD, 50/día" **cuando ya era falso**, y tres revisiones independientes lo repitieron como hecho porque estaba escrito aquí. Un dato de estado de cuenta caduca: **verifícalo con la API antes de dimensionar nada**, no lo leas de este fichero
- **Ojo al leer la API**: `/api/v1/key` devuelve `limit` y `limit_remaining`, que son el **tope de gasto configurado en esa clave**, NO el saldo. El saldo real está en `/api/v1/credits` (`total_credits` - `total_usage`). Confundirlos lleva a creer que hay dinero cuando no lo hay
- Referencia por si algún día se compra crédito: modelos de pago baratos cuestan ~0,001-0,003 USD por vídeo (30k tokens de salida) y no tienen tope diario

### Longitud de frase y comas (medido ago 2026)
Se puede eliminar la pausa "inventada" a mitad de frase escribiendo mejor el texto:

| Variante | Pausas inesperadas | Ventana de anclaje | pal/min |
|---|---|---|---|
| Frase larga (49 pal) SIN comas | 2 | 50 palabras | 207 |
| Frase larga CON comas | 0 | 50 palabras | 204 |
| Frases cortas (12-16 pal) | 0 | 12 palabras | **172** |
| **Frases medias (20-25 pal) + comas** | **0** | **22 palabras** | **198** |

- Con comas bien puestas, edge-tts pausa EN la coma en vez de inventarse el sitio
- Las frases muy cortas también funcionan pero la pausa en punto es de **1,1-1,3s** (vs 0,3-0,6s en coma): narración entrecortada y **19% más de duración**, ~4 min de silencio extra en un vídeo de 30 min
- Ganador: frases de 15-25 palabras con una coma cada 8-12. Bonus: la ventana de anclaje baja de 50 a 22 palabras, así que el sincronismo de subtítulos también mejora

### Las comas NO se le pueden pedir al modelo: se imponen en código
- Pedirlo en el prompt **no funciona**. Medido con la regla puesta, 4 generaciones dieron **167, 129, 0 y 0 comas**, con frases de 19 a 67 palabras de media y máximos de 116. El prompt ORIGINAL oscilaba igual (20, 139, 163), así que no es una regresión de la regla: el modelo alterna entre dos modos (frases largas con comas / frases medias sin ninguna) y ninguno cumple
- Por eso `_ensure_breathing_commas` (en tts_engine) inserta comas de respiración en código, igual que `_ensure_title_at_start` fuerza el título. Solo inserta **delante de conectores** (`pero`, `mientras`, `porque`, `aunque`…), nunca en mitad de un sintagma, y a los conectores ambiguos (`y`, `o`, `que`…) les exige un tramo más largo para no meter comas incorrectas
- Verificado con TTS real: pausas inesperadas **2 -> 0**, todas las restantes caen en puntuación
- **INVARIANTE**: no cambia el número de palabras (las comas se pegan a la palabra anterior). `main.py` cuenta palabras para saber cuándo acaba el título, así que romperlo descuadraría la intro. Comprobado con 300 textos aleatorios
- La regla sigue también en los prompts: no basta, pero sube la probabilidad del modo bueno y no cuesta nada

### Longitud de frase: distribución real y por qué NO hay que partirlas
Muestra de 10 historias generadas (417 frases, 16.048 palabras):

| Longitud | % frases | % palabras |
|---|---|---|
| ≤25 palabras | 18,0% | 9,3% |
| 26-40 | 44,1% | 37,5% |
| 41-60 | 28,3% | 35,2% |
| 61-100 | 9,4% | 17,4% |
| >100 | 0,2% | 0,7% |

- Mediana 36 palabras, percentil 90 en 60, máximo observado 105. Una frase de >100 palabras sale ~1 vez cada 10 historias
- **No degradan el sincronismo**: con contenido real, una frase de 95 palabras da 0,19-0,21s de error máximo (estable en 3 repeticiones), igual o mejor que una de 25. El anclaje por traslación aguanta ventanas largas
- Con `_ensure_breathing_commas` activo, 0 de 10 historias salieron sin comas (antes 2 de 4), así que el problema real de las frases largas —las pausas inventadas— ya está resuelto aguas abajo

### Trampa al medir sincronismo: NO usar texto repetido como fixture
- Un test que construía la frase larga repitiendo 4 veces el mismo párrafo daba 2,525s de error máximo, **exactamente el mismo valor** en 3 de 5 repeticiones, y solo emparejaba 112/132 palabras
- No era desfase real: con frases repetidas, el emparejador (difflib contra una transcripción independiente) engancha la copia equivocada. Un valor idéntico entre corridas es la señal de que el artefacto es del test, no del audio
- Los fixtures de sincronismo deben tener **contenido no repetido**

### Pausas a mitad de frase (medido ago 2026)
Hay TRES causas distintas y solo una es inevitable:
1. **Prosodia de edge-tts — INEVITABLE.** Con una frase de 52 palabras y CERO puntuación interna, mete pausas de 0.44s y 0.42s donde no hay nada. Decide por su cuenta dónde respirar. Solo se quitaría con SSML de pago
2. **Dos puntos convertidos en punto — ARREGLADO.** `_clean_speech_for_tts` sustituía `: ` + mayúscula por `. `, y eso metía una pausa de **1.18s** en mitad de la idea (el triple que una coma). Ahora sustituye por `, ` + minúscula: 0.44s
3. **Troceo de edge-tts a mitad de frase — ARREGLADO.** `Communicate` parte el texto cada **4096 bytes** (`split_text_by_byte_length`) y cada trozo es una petición de síntesis distinta, así que un corte a mitad de frase se oye como un parón. Elige el punto priorizando **saltos de línea** y, si no hay, cualquier espacio. La limpieza unía los párrafos con espacios y borraba todos los saltos: medido con texto de tamaño de producción, **2 de 2 cortes caían a mitad de frase; uniendo con `\n`, 0 de 2**. Un vídeo de 30 min son ~7 trozos
- Los números con punto de millar (4.500) NO provocan pausa
- Al tocar esta limpieza, verificar que la alineación sigue fina: con texto multi-párrafo el error debe quedar en ~0.13s medio / ~0.23s máximo contra una transcripción independiente

## Reglas de desarrollo

- **Coste $0**: OpenRouter free tier, edge-tts gratis, FFmpeg gratis
- **Idioma**: español de España (historias, voz, subtítulos)
- **Autónomo**: el pipeline funciona sin intervención humana
- **Dependencias**: requests, edge-tts, pyyaml, Pillow, faster-whisper, stable-ts

## Estado del proyecto

### Videos largos (COMPLETO)
- [x] Pipeline completo funcional
- [x] Limpieza de gameplay (hotbar detection)
- [x] Pool de gameplay con recodificación
- [x] Generación de historias en bloques
- [x] TTS con detección de género
- [x] Forced alignment con anclas duras (SentenceBoundary)
- [x] Intro animada con rebote + woosh
- [x] Miniaturas con colores vibrantes
- [x] Title card transparente para intro

### Shorts/TikToks (COMPLETO)
- [x] Generación de micro-historias (200 palabras)
- [x] Audio speed-up sin artefactos (atempo x1.5)
- [x] Subtítulos adaptados a 9:16 (PlayRes correcto, posición correcta)
- [x] Intro vertical con title card + background blur+tint golden angle
- [x] Composición con crop center + animaciones
- [x] Integración en main.py (Phase 2b)
- [x] Número dinámico de shorts por duración de gameplay
- [x] Offset diferente por short (gameplay no repetido)

### Dashboard de operación (COMPLETO)
- [x] `dashboard.py` + `dashboard_runner.py`, se ejecuta con `streamlit run dashboard.py`
- [x] Pipeline lanzado como SUBPROCESO (nunca importando funciones de fase)
- [x] 7 pestañas: Roadmap, Estado, Operar, Progreso, Resultados, Competencia, Config

### Análisis de competencia (COMPLETO)
- [x] Descubrimiento de competidores por keywords rotativas + canales semilla
- [x] Lista persistente en `data/competitors.json` que crece entre escaneos
- [x] Filtros: suscriptores, idioma/país, formato (descarta solo-shorts), actividad
- [x] Detección de virales por outlier + engagement + velocidad + frescura
- [x] Contabilidad de cuota por día con corte limpio y avisos de cobertura parcial
- [x] Debate LLM: veredicto argumentado + directrices + titulares de ejemplo
- [x] Inyección reversible en el prompt de historias, con el OK del usuario

### Validación E2E (ago 2026) — COMPLETA
- Corrida real con clip de 3 min: ingesta (hotbar 18/18) -> pool (1120MB -> 296MB) ->
      historia -> TTS -> forced alignment (anclas duras 9/9) -> ASS -> intro -> composición
      -> miniatura -> 3 shorts. Salida verificada FOTOGRAMA A FOTOGRAMA
- Reproducible: clip corto en un `input_dir` propio + config con `target_duration_min`
      bajado. No hace falta procesar el gameplay de 13 GB para validar la cadena
- Destapó el bug del demuxer `concat` (ver arriba), que llevaba desde siempre roto

### Lo que falta para que el pipeline esté FINALIZADO

La cadena de producción está completa y validada. Lo que queda tiene su seed escrita en
`seeds/` (cada una con `/seed-review` como paso 0). Orden recomendado: 1 → 2 → 3.

| # | Seed | Qué cierra |
|---|---|---|
| 1 | `SEED_1_cierre_funcional.md` | Directrices de competencia en `short_story.txt` (hoy solo llegan a `reddit_story.txt`, así que los shorts ignoran el análisis) · escaneo de competencia programado (hoy solo manual) · `st.components.v1.html` deprecado desde 2026-06-01 |
| 2 | `SEED_2_subida_youtube.md` | **La subida a YouTube**: el pipeline se para en `output/` y el usuario sube a mano. Es el último paso para cumplir el objetivo "autónomo". Necesita OAuth y decisiones del usuario. `videos.insert` cuesta 1.600 unidades de las 10.000 diarias, compartidas con el análisis de competencia |
| 3 | `SEED_3_produccion_30min.md` | Validación de volumen: 30 min reales con ~30 shorts. A esa escala entran por primera vez el encadenado de 4-6 bloques, el troceo de edge-tts en ~7 trozos y la lista anti-repetición más allá de sus 12 títulos |

**Calidad, no bloquean** (una por día: se comen la cuota de OpenRouter):

| # | Seed | Qué hace |
|---|---|---|
| 4 | `SEED_4_validar_cambios.md` | 6 agentes en paralelo retando con datos los parámetros elegidos (anclaje, umbrales de comas, `target_wpm`, validación de salida, anti-repetición a N=30, scoring de competencia) |
| 5 | `SEED_5_caza_bugs.md` | Revisión de bugs del pipeline y del dashboard, con las clases de fallo ya vistas aquí como guía |

**No paralelizar a la ligera**: la 3 monopoliza GPU y `pool/`/`output/`; la 4 y la 5 compiten
por las 1000 peticiones/día de OpenRouter; la 1 y la 2 chocan en `dashboard.py`, `main.py` y
`config.yaml`. Y el contador de cuota de YouTube vive en `data/competitors.json`: dos procesos
escribiéndolo a la vez pierden actualizaciones y el corte preventivo deja de proteger.
