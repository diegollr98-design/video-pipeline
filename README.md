# YouTube Automation — historias de Reddit sobre gameplay de Minecraft

Pipeline autónomo en Python que convierte **gameplay en bruto** en vídeos de YouTube listos para
publicar: historia, narración, subtítulos sincronizados palabra a palabra, intro animada, miniatura
y shorts verticales. Sin intervención humana en ningún fotograma.

**Coste de operación: 0 €.** Modelos gratuitos de OpenRouter, TTS de Microsoft Edge, FFmpeg y
Whisper en local.

---

## Lo que produce

Una corrida toma un `.mp4` de gameplay y deja en `output/`:

| Artefacto | Qué es |
|---|---|
| `video_NNN_final.mp4` | vídeo completo con intro animada, narración y subtítulos |
| `video_NNN_thumbnail.jpg` | miniatura 1280×720 |
| `video_NNN_title.txt` | título largo (va a la miniatura y a la intro) |
| `video_NNN_title_yt.txt` | título corto, recortado al límite de 100 caracteres de YouTube |
| `shorts_tiktok/short_NNN.mp4` | N shorts verticales 9:16, cada uno con su micro-historia |

## La tesis del proyecto

> El modo de fallo aquí **no es que el pipeline pete**. Es que entregue un vídeo que **parece
> terminado** y esté roto donde nadie mira: el subtítulo un segundo por detrás de la voz, cuatro
> shorts contando la misma historia, media grabación descartada en la ingesta.

El pipeline es autónomo por diseño, así que **nadie ve los 30 minutos de salida** — y un defecto
silencioso se sube a YouTube tal cual. Por eso la mitad del código de este repo no genera vídeo:
lo **mide**.

```
$ python scripts/audit_run.py --stem video_012

  OK   sincronismo: medio 0.045s  p95 0.090s  sesgo -0.018s  (0 palabras >0,5 s tarde)
  OK   pausas inventadas (acústico): 0 = 0.0 por 1000 palabras (máximo 12.0)
  OK   voz SIN subtítulo: 0.00s en 0 tramo(s)
  OK   cierre narrativo · truncado narrativo · basura del modelo · párrafos repetidos
  OK   loudness: -14.6 LUFS · geometría: PlayRes 1920x1080 + pos(960,540)
  VEREDICTO: sin defectos MEDIBLES.
```

Ese veredicto **corta**: si encuentra un defecto medible, el botón de subir a YouTube queda
deshabilitado. Y **caduca solo** — cada veredicto se firma con una huella de los criterios con los
que se emitió, así que al cambiar el auditor los veredictos viejos dejan de valer en vez de
mentir.

## Arquitectura

```
Fase 1 · Ingesta      input/*.mp4 → detección de hotbar de Minecraft fotograma a fotograma
                      → descarta pausa/escritorio/menús → recodifica → pool/

Fase 2 · Producción   pool/ → chunk → OpenRouter (título + historia)
                      → edge-tts → forced alignment (stable-ts + faster-whisper)
                      → SRT→ASS → intro animada + woosh → FFmpeg → output/

Fase 2b · Shorts      micro-historias ~200 palabras → audio ×1.5 → crop 9:16 → shorts_tiktok/

Fase 3 · Competencia  YouTube Data API → descubre competidores, puntúa virales por outlier
                      sobre la mediana del propio canal → debate LLM → directrices
```

Operación desde un **dashboard de Streamlit** de 8 pestañas que lanza el pipeline como
**subproceso** (nunca importando funciones de fase) y enseña el comando exacto que ejecuta.

## Decisiones técnicas que costaron una medición

Estas no son opiniones: cada una salió de un defecto real, reproducido y medido. El detalle
completo está en [`CLAUDE.md`](CLAUDE.md) y el registro de incidentes en
[`.claude/incident-ledger.md`](.claude/incident-ledger.md).

- **Los subtítulos iban ~0,5 s por detrás de la voz durante meses** y el pipeline no daba error.
  Causa: `edge-tts` no emite marcas de palabra, solo de frase, y esa ventana **incluye los
  silencios**; el código repartía las palabras para rellenarla entera. El fix fue cambiar de
  mecanismo (trasladar en vez de repartir), no de constante. Medido contra una transcripción
  independiente del audio, no contra el texto de partida: **error medio 0,502 s → 0,146 s**, máximo
  1,064 → 0,248, y el sesgo pasa de **+0,435 s (detrás)** a **−0,146 s (delante)**. Después vinieron
  otros arreglos del anclaje, y el gate sobre el fixture de 3 min da hoy **0,072 s** de error medio.
  *(Son medidas de corridas distintas: emparejar el «antes» de una con el «después» de otra infla la
  mejora, y ese es justo el tipo de cifra que este proyecto no publica.)*
- **Lo que se le pide al modelo en prosa no está garantizado hasta que un `if` lo fuerza.** Pedir
  comas en el prompt dio 167, 129, **0 y 0** comas en cuatro generaciones. Se imponen en código.
  Lo mismo con el título forzado al inicio del speech y con la variedad de los shorts.
- **Un guardia puede existir, llamarse en todas las rutas y aun así ser inerte** si su constante
  cae fuera del rango del defecto: el que rechaza guiones impuntuables estaba en `p90 > 30` cuando
  `edge-tts` respira cada ~21 palabras. No disparó en nueve corridas. Con el corte en 21, las
  pausas inventadas pasaron de **16,8 por 1000 palabras a 0**.
- **El demuxer `concat` de FFmpeg nunca funcionó** — resolvía las rutas relativas respecto al
  directorio del fichero de lista, no del cwd — y nadie lo notó porque la única grabación real era
  95 % gameplay y tomaba un atajo. Terminaba sin error.
- **Un instrumento roto no da un error: da un veredicto equivocado con aspecto de evidencia.** Por
  eso cada medidor se calibra contra un caso de resultado conocido antes de juzgar nada con él.

## Stack

Python 3 · OpenRouter (`nvidia/nemotron-3-ultra`) · edge-tts · stable-ts + faster-whisper ·
FFmpeg · Pillow · Streamlit · YouTube Data API v3

## Uso

```bash
streamlit run dashboard.py          # operación (recomendado)

python main.py                      # ingesta + producción completa
python main.py --skip-ingest        # solo produce del pool existente
python main.py --dry-run            # solo la historia, sin vídeo
python main.py --no-shorts          # sin shorts en esta corrida

python main.py --scan-competition   # análisis de competencia (no produce vídeo)
python scripts/audit_run.py         # audita la salida y emite veredicto
```

Requiere un `.env` con `OPENROUTER_API_KEY` y, opcionalmente, `YOUTUBE_API_KEY` (solo hace falta
para el análisis de competencia; el resto del pipeline corre sin ella).

## Estado

La cadena funciona de punta a punta y la salida se audita automáticamente. Lo que queda abierto
está en [`seeds/`](seeds/), con su evidencia, y los defectos conocidos con su medición en el
[registro de incidentes](.claude/incident-ledger.md) — incluidos los que **siguen sin arreglar**.
