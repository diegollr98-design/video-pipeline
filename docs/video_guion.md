# Guión — Recorrido del dashboard (vídeo hero del portfolio)

> Pieza central de `#recorrido` en `Portafolio/YOUTUBE-PIPELINE.html`. **Formato:** voz en off sobre
> screen-recording del dashboard real (`streamlit run dashboard.py`), **sin talking-head**.
> **Idiomas:** ES + EN sobre la **misma** grabación (dos locuciones o subtítulos).
> **Tono:** honesto, preciso, sin hype — la voz del portfolio. El límite reconocido (la subida a
> YouTube aún no existe) no se esconde: dicho de frente, refuerza todo lo demás.
>
> **Enfoque:** este NO re-narra el HTML. **Recorre las 7 pestañas reales del dashboard** y, dentro de
> 📡 Progreso, **enseña el pipeline entero corriendo de verdad** — ingesta → historia → voz →
> alineación → composición → shorts. Es "el sistema en marcha", no diapositivas.
>
> **Duración:** tour completo ≈ **5:20**. Para un hero más corto, graba/monta solo las filas ★
> (≈ **3:00**); las filas ○ son el tour extendido. Los tiempos son del **tour completo**.
>
> **Regla de honestidad (marca del proyecto):** cada cifra dicha está verificada contra la fuente
> (ver §Cifras verificadas). Cero inventos. Si al grabar una cifra no cuadra con lo que muestra la
> pantalla en ese instante, **manda la pantalla** — se corrige el guión, no la pantalla. Y **oculta
> secretos**: la sección 🔑 API Keys enseña los 6 primeros caracteres de cada clave; no te detengas
> ahí y nunca abras `.env` en cámara.

**Leyenda:** ★ = corte tight (hero ~3:00) · ○ = tour extendido · `⏸` = beat/pausa.
Columnas: **PANTALLA** (lo que se graba) · **ES** (voz) · **EN** (voice-over).

---

## 0 · Hook — 0:00–0:20  ★

| t | PANTALLA | ES | EN |
|---|---|---|---|
| 0:00 | `video_001_final.mp4` a pantalla completa, 6 s en un tramo con subtítulo (palabra en MAYÚSCULAS, centrada). Corte rápido a la rejilla de los 4 shorts verticales. | «Esto —vídeo, voz, subtítulos, miniatura y cuatro shorts verticales— lo ha producido un pipeline entero a partir de una grabación de Minecraft en bruto. Nadie ha tocado un fotograma.» | "This —video, voice, subtitles, thumbnail and four vertical shorts— was produced end to end by a pipeline, out of a raw Minecraft recording. Nobody touched a single frame." |
| 0:10 | El dashboard abriéndose en **🗺️ Roadmap**. ⏸ | «Y el modo de fallo de algo así no es que pete: es que entregue un vídeo que **parece terminado** y esté roto donde nadie mira. Te enseño el sistema en marcha, pestaña por pestaña.» | "And the failure mode of something like this isn't crashing: it's shipping a video that **looks finished** and is broken where nobody looks. Let me show you the system running, tab by tab." |

---

## 1 · 🗺️ Roadmap — la foto entera — 0:20–0:45  ★

| t | PANTALLA | ES | EN |
|---|---|---|---|
| 0:20 | Tab **🗺️ Roadmap**, el SVG «El viaje completo de un video». Sigue el flujo con el cursor. | «El dashboard es el mapa del viaje: gameplay en bruto entra por un lado y salen vídeos y shorts listos para subir. Cada pestaña es un paso de ese viaje, no un menú de opciones sueltas.» | "The dashboard is the map of the journey: raw gameplay goes in one end, and out come videos and shorts ready to upload. Each tab is a step of that journey, not a menu of loose options." |
| 0:34 | El `st.info` de una frase, justo debajo del diagrama. | «En una frase: en **Operar** doy al play, el pipeline hace el trabajo, lo veo en **Progreso** y lo recojo en **Resultados**. **Estado** y **Config** son apoyo, para cuando quiera.» | "In one line: in **Operate** I hit play, the pipeline does the work, I watch it in **Progress** and pick it up in **Results**. **Status** and **Config** are support, for whenever I want." |

---

## 2 · 📊 Estado — ¿puede producir? — 0:45–1:08

| t | PANTALLA | ES | EN |
|---|---|---|---|
| 0:45 ★ | Tab **📊 Estado** → **🎮 Pool de gameplay**: métricas *Archivos en el pool* / *Minutos totales*, la barra de progreso y el mensaje **✅ Hay material suficiente para producir**. | «Estado es la foto previa. El *pool* es una cola de gameplay ya limpio, sin pausas ni escritorio, esperando a convertirse en vídeo. Si no alcanza el mínimo, el pipeline no arranca — y lo dice **antes**, no a mitad de una corrida de cuarenta minutos.» | "Status is the pre-flight shot. The *pool* is a queue of already-clean gameplay —no pauses, no desktop— waiting to become a video. If it's below the minimum, the pipeline won't start — and it says so **up front**, not halfway through a forty-minute run." |
| 0:58 ○ | Baja por **📁 Archivos** (entrada `.mp4` + GB, vídeos producidos, shorts) → **🔧 Dependencias** (*FFmpeg / FFprobe: OK*) → **🔑 API Keys**. No te detengas en las claves. | «Debajo, el inventario, las dependencias comprobadas de verdad en el sistema, y las claves. La de YouTube solo afecta al análisis de competencia: el resto del pipeline funciona sin ella, y el dashboard lo dice en vez de fallar más tarde.» | "Below: the inventory, the dependencies actually checked on the system, and the keys. The YouTube one only affects competitor analysis: the rest of the pipeline runs without it, and the dashboard says so instead of failing later." |

---

## 3 · 🎬 Operar — el único botón — 1:08–1:45  ★

| t | PANTALLA | ES | EN |
|---|---|---|---|
| 1:08 | Tab **🎬 Operar**: modo *Procesar un archivo de gameplay nuevo* → fuente *Seleccionar de input/* → elige el clip. Luego **Opciones**: estilo `dramatic`, ✅ *Generar shorts*. | «Operar es el arranque. Elijo el gameplay, el estilo de la historia y si quiero shorts. Eso es todo lo que tengo que decidir.» | "Operate is the launcher. I pick the gameplay, the story style, and whether I want shorts. That's everything I have to decide." |
| 1:24 | Zoom al bloque **Comando que se ejecutará** con el `st.code`: `python main.py --video … --style dramatic`. Déjalo 2 s. | «Y aquí está la decisión de diseño que más me importa: el dashboard **no importa funciones del pipeline**. Enseña el comando exacto y lanza `main.py` como un **subproceso**. Lo que ves es lo que corre — y si cierro el dashboard, la corrida sigue viva.» | "And here's the design decision I care most about: the dashboard **doesn't import pipeline functions**. It shows the exact command and launches `main.py` as a **subprocess**. What you see is what runs — and if I close the dashboard, the run stays alive." |
| 1:38 | Click en **🚀 Ejecutar pipeline** → el toast «Corrida lanzada (PID …)». ⏸ | «Le doy al play.» | "I hit play." |

---

## 4 · 📡 Progreso — el pipeline entero, en marcha — 1:45–2:52  ★

| t | PANTALLA | ES | EN |
|---|---|---|---|
| 1:45 | Tab **📡 Progreso**: **🟢 Ejecutando… (PID …)**, **Fase actual: Ingestando**, y el log en vivo corriendo solo. Resalta `--- Ingesting: …` y `Recodificando para pool`. | «Progreso es la ventana al motor: el log real del proceso y la fase deducida de él. Primera fase, **ingesta**: detecta la *hotbar* de Minecraft fotograma a fotograma y tira pausa, escritorio y menús. Lo que sobrevive se recodifica y entra al pool.» | "Progress is the window into the engine: the process's real log, and the phase inferred from it. First phase, **ingest**: it detects Minecraft's hotbar frame by frame and drops pause, desktop and menus. Whatever survives is re-encoded and enters the pool." |
| 2:05 | Timelapse ×8. **Fase actual: Generando historia**. En el log: `=== Produciendo pool_0001 (200s / 3.3min) ===`, `Duración: 200s -> objetivo: 650 palabras`, `Título: Mi Madre Firmó La Casa…`. | "Segunda: la **historia**. El pipeline calcula cuántas palabras caben en ese gameplay a la velocidad real de esta voz —195 palabras por minuto, **medida**, no supuesta— y se las pide al modelo. El título va **forzado** como primera frase del speech, porque de él dependen la miniatura y la intro." | "Second: the **story**. The pipeline works out how many words fit that gameplay at this voice's real speed —195 words per minute, **measured**, not assumed— and asks the model for them. The title is **forced** as the speech's first sentence, because the thumbnail and the intro both depend on it." |
| 2:22 | **Fase actual: Sintetizando voz**. Log: `Sintetizando audio`, `Alineando texto con audio (forced alignment, small)`, y sobre todo `Anclas duras: N/N frases ancladas a SentenceBoundary`. Deja esa línea 2 s. | «Tercera: **voz y sincronismo**. Text-to-speech en español, y encima un *forced alignment* con Whisper que localiza dónde suena exactamente cada palabra. Esa línea de **anclas duras** es el corazón del proyecto — al final del vídeo te enseño por qué.» | "Third: **voice and sync**. Spanish text-to-speech, and on top of it a *forced alignment* with Whisper that locates exactly where each word sounds. That **hard anchors** line is the heart of the project — at the end I'll show you why." |
| 2:38 ○ | **Fase actual: Componiendo video** (`Titulo (N palabras) termina en: X s`) → **Generando shorts** (`--- Generando short 1 para video 1 (offset=…s) ---`). | «Cuarta: **composición**. La intro animada dura exactamente lo que el narrador tarda en decir el título, y los subtítulos empiezan después. Y quinta: los **shorts** verticales, cada uno con un tramo distinto del gameplay.» | "Fourth: **composition**. The animated intro lasts exactly as long as the narrator takes to say the title, and subtitles start after it. And fifth: the vertical **shorts**, each one on a different stretch of gameplay." |
| 2:48 | `✅ Terminado: 1 video(s) producido(s)` y **Fase actual: Terminado**. ⏸ | «Y termina. Ojo a esto: *terminar sin error* **no** significa que esté bien. Eso lo decide otra capa.» | "And it finishes. Careful with that: *finishing without an error* does **not** mean it's correct. Another layer decides that." |

---

## 5 · 🖼️ Resultados — la bandeja de salida — 2:52–3:32  ★

| t | PANTALLA | ES | EN |
|---|---|---|---|
| 2:52 | Tab **🖼️ Resultados** → **🎬 Videos largos**: la tarjeta con miniatura, el título completo y `video_001_final.mp4 — 316,3 MB`. | «Resultados es la bandeja de salida: por cada vídeo, el MP4, la miniatura y el título en un `.txt` para copiar y pegar en YouTube. La miniatura lleva un tinte de color que rota, para que dos seguidas nunca salgan iguales.» | "Results is the output tray: for each video, the MP4, the thumbnail and the title in a `.txt` to paste into YouTube. The thumbnail carries a rotating colour tint, so two in a row are never the same." |
| 3:06 | **▶️ Abrir video** → salta a un punto con voz. Ralentiza o ve fotograma a fotograma 1–2 s sobre una palabra. | «Y aquí está lo que hay que mirar de cerca: la palabra aparece en pantalla **justo antes** de oírse. Está puesto a propósito — el audio va cien milisegundos por delante. Que el subtítulo llegue tarde se siente mal aunque no sepas por qué.» | "And here's what to look at closely: the word appears on screen **just before** you hear it. That's deliberate — the audio runs a hundred milliseconds ahead. A late subtitle feels wrong even when you can't say why." |
| 3:18 | Sección **📱 Shorts**: los 4 con sus títulos visibles a la vez. Recorre los títulos con el cursor. | «Y los shorts. Fíjate en los títulos: el hermano y el coche, la suegra y la cerradura, la exnovia y los videojuegos, el socio y la receta. **Cuatro historias distintas** — y eso no lo garantiza el prompt: a cada llamada se le pasan los títulos ya generados para que el modelo **no pueda** repetirse.» | "And the shorts. Look at the titles: the brother and the car, the mother-in-law and the lock, the ex and the retro games, the partner and the recipe. **Four different stories** — and the prompt doesn't guarantee that: each call is handed the titles already generated, so the model **can't** repeat itself." |

---

## 6 · 🔍 Competencia — qué contar, medido — 3:32–4:05

| t | PANTALLA | ES | EN |
|---|---|---|---|
| 3:32 ★ | Tab **🔍 Competencia** → **🔥 Videos virales de la competencia**: la tabla con el multiplicador de *outlier*. | «Competencia es la única pestaña que **no** produce vídeo. Mide el nicho con la API de YouTube: qué canales compiten de verdad, y qué vídeos se les han disparado **sobre su propia mediana** — no en absoluto, porque un canal grande siempre gana esa comparación.» | "Competition is the only tab that **doesn't** produce video. It measures the niche with the YouTube API: which channels really compete, and which of their videos spiked **against their own median** — not in absolute terms, because a big channel always wins that comparison." |
| 3:46 ○ | El contador de cuota + el expander **📋 Lista de competidores**. | «Y va contando la cuota. Una búsqueda cuesta **cien** unidades de las diez mil del día; leer los últimos vídeos de un canal por su lista de subidas cuesta **una**. Por eso el escaneo está montado así — y por eso corta él solo antes de que Google devuelva un error.» | "And it keeps counting quota. One search costs **a hundred** units of the daily ten thousand; reading a channel's latest videos through its uploads playlist costs **one**. That's why the scan is built this way — and why it cuts itself off before Google returns an error." |
| 3:56 ○ | **🧠 Qué atacar** → botón *Debatir* → veredicto y el expander **Ver el bloque inyectado**. | «Con esos datos, un modelo debate qué atacar y devuelve directrices. Se inyectan en el prompt de las historias **solo si yo lo apruebo**, entre marcadores — y se revierten dejando el prompt byte a byte como estaba.» | "With that data, a model debates what to attack and returns guidelines. They're injected into the story prompt **only if I approve**, between markers — and reverting leaves the prompt byte for byte as it was." |

---

## 7 · ⚙️ Config — los mandos curados — 4:05–4:20  ○

| t | PANTALLA | ES | EN |
|---|---|---|---|
| 4:05 | Tab **⚙️ Config**, recorrido rápido: **🎙️ TTS** → **💬 Subtítulos** → **📖 Historia** (párate en *Palabras por minuto (WPM): 195*) → **📱 Shorts** → **🎞️ Video**. | «Config son los mandos curados, no el YAML entero. Y casi cada número de aquí sale de una medición: 195 palabras por minuto es la velocidad **real** de esta voz. Con el valor que había antes, el vídeo salía un tercio más corto que el gameplay y el resto se tiraba a la basura.» | "Config exposes curated knobs, not the whole YAML. And almost every number here comes from a measurement: 195 words per minute is this voice's **real** speed. With the previous value, the video came out a third shorter than the gameplay and the rest was thrown away." |

---

## 8 · EXTRA · El gate y el panel que intenta romperlo — 4:20–4:48

| t | PANTALLA | ES | EN |
|---|---|---|---|
| 4:20 ★ | Terminal: `/eval` corriendo sobre `test_e2e/`, o la salida de la medición de sincronismo. | «Nada de esto se cierra a ojo. Hay un **gate** que corre la cadena entera contra un clip fijo y **mide la salida**: error de sincronismo entre voz y subtítulo, pausas que caen fuera de puntuación, variedad de los shorts. Si un cambio empeora el baseline, no se cierra. No es un aviso: es un no.» | "None of this closes by eye. There's a **gate** that runs the whole chain against a fixed clip and **measures the output**: voice-to-subtitle sync error, pauses landing outside punctuation, shorts variety. If a change worsens the baseline, it doesn't close. That's not a warning: it's a no." |
| 4:36 ○ | Los agentes en `.claude/agents/` o el diagrama `#metodo` del portfolio. | «Y encima, un panel adversarial: un agente que busca la causa raíz **sin ver el contexto**, y otro cuyo único trabajo es **intentar demostrar que el vídeo está roto** midiendo sus artefactos. Yo re-derivo cada veredicto **ejecutando**, nunca por informe.» | "And on top, an adversarial panel: one agent that finds the root cause **with no context**, and another whose only job is to **try to prove the video is broken** by measuring its artifacts. I re-derive every verdict by **executing**, never by report." |

---

## 9 · El bug que solo se ve midiendo + cierre — 4:48–5:20  ★

| t | PANTALLA | ES | EN |
|---|---|---|---|
| 4:48 | El bloque `#desfase` del portfolio con la línea de tiempo animada: la pista roja «ANTES» quedándose atrás frente a la cian «AHORA». | «Y esta es la razón de todo lo anterior. Durante meses los subtítulos fueron **por detrás** de la voz. El pipeline no daba ningún error: producía MP4 perfectos. La causa era que el motor de voz **no marca palabras, solo frases** — y esa ventana incluye los silencios, así que el reparto empujaba cada palabra más tarde de cuando sonaba. Medido contra una transcripción independiente: **medio segundo** de error medio. Hoy son **0,146** — y por delante, no por detrás.» | "And this is the reason for everything above. For months the subtitles ran **behind** the voice. The pipeline threw no error: it produced perfect MP4s. The cause was that the voice engine **doesn't mark words, only sentences** — and that window includes the silences, so spreading words across it pushed every one later than it sounded. Measured against an independent transcript: **half a second** of mean error. Today it's **0.146** — and ahead, not behind." |
| 5:06 | Vuelta al dashboard, o la carpeta `output/` con los tres archivos. Cierre en contacto. ⏸ | «El pipeline se para en `output/`: la subida automática a YouTube es el siguiente paso y **aún no está construida**. Lo digo porque prefiero decirlo. Empecé sin saber programar y lo levanté **solo, con IA**. Si buscas a alguien que construya sistemas autónomos **y** las medidas que impiden que se engañen a sí mismos… hablemos.» | "The pipeline stops at `output/`: automatic upload to YouTube is the next step and it **isn't built yet**. I'd rather say it than imply otherwise. I started not knowing how to code and built it **solo, with AI**. If you want someone who builds autonomous systems **and** the measurements that stop them fooling themselves… let's talk." |

---

## Preparación de la toma

Grabar §4 exige una **corrida real**. Una de producción son ~40 min de render y ~46 de las 50 peticiones
diarias del tier gratuito: inviable para una toma. Se graba con el **clip corto del gate**.

1. **Copia** (no muevas) `test_e2e/input/clip.mp4` → `input/`. La ingesta **no borra** el archivo de
   `input/`, solo el temporal limpio, así que el fixture queda intacto igualmente.
   ⚠️ `input/` ya contiene la grabación real (**12,91 GB**, tal como la muestra 📊 Estado): aparecerá en el desplegable de 🎬 Operar.
   **No la elijas en cámara.**
2. En **⚙️ Config → 📖 Historia**, baja *Duración mínima para producir (segundos)* de `1200` a `150`
   y guarda. Es el único mando que hay que tocar: el dashboard lee `config.yaml` y `build_command`
   **no** acepta `--config`, así que no se puede apuntar a `test_e2e/config.yaml` desde la interfaz.
   👉 Este cambio es un buen plano en sí mismo (§7), pero **restaura `1200` al terminar**:
   `target_duration_min` es superficie sensible y quedaría alterada en producción.
3. **Presupuesto de la toma** con el clip de 200 s: 650 palabras → **1 bloque** + **4 shorts** =
   **~5 peticiones** de las 50 del día. Deja margen para un reintento.
4. **Elige un clip con pausas.** Si el gameplay es 100 % continuo, la ingesta toma el atajo de recorte
   y el plano de §4 no enseña nada. Con pausas se ejecuta la ruta real (detección + concatenado).
5. **Cronometra la corrida** y apunta el tiempo real: sirve para calibrar el timelapse y por si quieres
   decir la cifra. No la inventes en el guión.
6. **Plan B sin correr nada:** `test_e2e/output/` y `test_e2e/shorts/` ya contienen los artefactos
   reales de la validación de agosto (1 vídeo + 4 shorts con títulos distintos). Sirven para §0 y §5;
   solo §4 necesita la corrida en vivo.

---

## Notas de producción

- **Todas las pantallas son reales.** El dashboard se levanta con `streamlit run dashboard.py`. Los
  únicos planos fuera de él son la terminal de §8 y el bloque `#desfase` del portfolio en §9.
- **Ritmo:** deja cada cifra 1–2 s en pantalla mientras se nombra. No leas un número que la pantalla no
  muestre en ese instante. En §4 usa timelapse ×8, pero **con la etiqueta *Fase actual* siempre visible**:
  es lo que cuenta la historia.
- **El clip del fixture es 720p**, así que el vídeo de salida también. No digas «1080p» en cámara.
- **Ocultar secretos:** 🔑 API Keys enseña los 6 primeros caracteres de cada clave. No te pares ahí y
  no abras `.env` en cámara.
- **Bilingüe:** una sola grabación, dos locuciones (o subtítulos ES/EN). El portfolio ya alterna idioma.
- **Corte hero vs tour:** filas ★ ≈ 3:00 (Hook + Roadmap + Operar + Progreso + Resultados + gate +
  cierre). Filas ○ = tour extendido pestaña a pestaña (~5:20).
- **Embeber luego:** reemplaza el `<div class="video-ph">` de `Portafolio/YOUTUBE-PIPELINE.html`
  (instrucciones en el comentario justo encima) por el `<iframe>`/`<video>`.

---

## Estructura real del dashboard usada (verificada en `dashboard.py`, `st.tabs` L168)

| Pestaña | Secciones (tal cual en el dashboard) |
|---|---|
| 🗺️ Roadmap | El viaje completo de un video (SVG) · Qué hace cada pestaña · Un par de decisiones que quizá te sorprendan |
| 📊 Estado | 🎮 Pool de gameplay · 📁 Archivos · 🔧 Dependencias · 🔑 API Keys |
| 🎬 Operar | Modo · Fuente · Opciones (estilo · shorts · dry-run) · **Comando que se ejecutará** · 🚀 Ejecutar pipeline |
| 📡 Progreso | Estado + PID · **Fase actual** · Log en vivo (tail 200 líneas, refresco 2 s) · ⏹️ Detener corrida |
| 🖼️ Resultados | 🎬 Videos largos (miniatura · título · MP4 · descargas) · 📱 Shorts |
| 🔍 Competencia | 🔥 Videos virales · 📋 Lista de competidores · 🧠 Qué atacar (debate + inyección) |
| ⚙️ Config | 🎙️ TTS · 💬 Subtítulos · 📖 Historia · 📱 Shorts · 🎞️ Video |

*(7 pestañas · el pipeline se lanza como subproceso vía `dashboard_runner.launch_run`, nunca importando
funciones de fase.)*

---

## Cifras verificadas (contra fuente, 2026-08-10)

| Cifra en el guión | Fuente | Estado |
|---|---|---|
| 4 shorts = **4 historias distintas** (hermano/coche · suegra/cerradura · exnovia/videojuegos · socio/receta) | `test_e2e/shorts/short_00N_title.txt` (leídos) | ✅ |
| Clip de entrada 200 s · vídeo de salida 182,6 s | `ffprobe` sobre `test_e2e/input/clip.mp4` y `output/video_001_final.mp4` | ✅ |
| Shorts verticales 1080×1920 · 26–49 s | `ffprobe` sobre los 4 `short_00N.mp4` | ✅ |
| Vídeo de salida 720p (lo hereda del clip) | `ffprobe`: clip 1280×720 | ✅ |
| 195 wpm **medido** (antes 150 → vídeo ~30 % más corto que el chunk) | `config.yaml` `story.target_wpm` + comentario | ✅ |
| Título forzado como primera frase del speech | `script_generator._ensure_title_at_start` | ✅ |
| Anti-repetición: se pasan los títulos ya generados | `shorts_generator._build_avoid_block` (`avoid[-12:]`) | ✅ |
| Anclas duras sobre `SentenceBoundary` | `tts_engine._validate_and_fix_alignment` (log L453) | ✅ |
| Audio offset −100 ms (voz antes que subtítulo) | `CLAUDE.md` §Subtítulos + `video_composer` | ✅ |
| 0,502 s → **0,146 s** de error medio · sesgo +0,435 → −0,146 | `CLAUDE.md` §Subtítulos — forced alignment | ✅ |
| `search.list` = 100 unidades · `playlistItems` = 1 · 10.000/día | `CLAUDE.md` §Competencia + `config.yaml` `quota.daily_limit` | ✅ |
| Inyección reversible entre marcadores, con OK del usuario | `trend_advisor` (`BEGIN_MARK`/`END_MARK`, `remove_from_prompt`) | ✅ |
| El dashboard lanza `main.py` como **subproceso** y enseña el comando | `dashboard_runner.build_command` + `launch_run`; `dashboard.py` L528-L531 | ✅ |
| *Fase actual* se deduce del log, no del código | `dashboard_runner.current_phase` | ✅ |
| Presupuesto de la toma ≈ 5 peticiones (1 bloque + 4 shorts) | fórmula de `main.py` L79-L86 + `WORDS_PER_BLOCK=2000` → coincide con los 4 shorts reales | ✅ |
| La subida a YouTube **no está construida** (1.600 unidades/vídeo) | `seeds/SEED_2_subida_youtube.md` + `CLAUDE.md` §Lo que falta | ✅ |

**Nota de coherencia:** la frase que usa la línea de tiempo animada del portfolio
(*«Mi hermano vendió mi coche clásico para pagar sus deudas…»*) es el **título real** de
`short_001`, no un ejemplo inventado. Si en §9 enseñas ese bloque justo después de los shorts de §5,
el espectador reconoce la frase — merece la pena montarlo en ese orden.
