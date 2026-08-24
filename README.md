# YouTube Automation — historias de Reddit sobre gameplay de Minecraft

Pipeline autónomo en Python que convierte **gameplay en bruto** en vídeos de YouTube: historia
generada por LLM, narración por voz, subtítulos sincronizados palabra a palabra, intro animada,
miniatura y shorts verticales — sin intervención humana en la producción.

Lo que este repo vende no es "genera vídeos solo" — eso es fácil y, sin más, una granja de
contenido. Lo interesante es **cómo se impide que un sistema autónomo publique basura sin que
nadie lo mire**: un gate que mide cada salida contra un baseline numérico, una auditoría
adversarial que intenta activamente demostrar que el vídeo está roto, y un registro de
incidentes append-only donde cada defecto que se coló queda con su evidencia y su causa. El
detalle está más abajo, con las cifras y de dónde salen.

**Coste de operación: 0 €.** Modelos gratuitos de OpenRouter, TTS de Microsoft Edge, FFmpeg y
Whisper en local.

---

## Quickstart

```bash
git clone <este repo>
cd video-pipeline
pip install -r requirements.txt
```

FFmpeg no es un paquete de Python, así que no está en `requirements.txt` — se instala aparte:
`winget install Gyan.FFmpeg` en Windows, `apt install ffmpeg` en Linux/WSL.

```bash
cp env.example .env         # o "copy env.example .env" en Windows
```

Rellena `OPENROUTER_API_KEY` en `.env` (obligatoria). `YOUTUBE_API_KEY` es opcional: solo la usa
el análisis de competencia (Fase 3); el resto del pipeline corre sin ella.

```bash
streamlit run dashboard.py
```

**Dos cosas que hay que saber antes de que fallen en silencio:**

- `assets/3.png` (plantilla de miniatura/intro) y el `.mp3` del woosh **no se distribuyen** — son
  recursos de terceros. Sin ellos el pipeline corre igual, pero el vídeo sale sin miniatura y sin
  sonido de intro. Detalle en [`assets/README.md`](assets/README.md).
- `/eval` (el gate, ver más abajo) necesita `test_e2e/input/clip.mp4`, que tampoco se versiona
  (1,5 GB de gameplay). Un clon fresco no puede correr el gate tal cual; sirve cualquier `.mp4`
  corto de gameplay puesto en esa ruta.

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

### Mapa de evidencia

Ninguna cifra de este README es de memoria; todas están en un JSON versionado:

| Cifra | Fichero | Qué es |
|---|---|---|
| medio `0,0723 s` · máximo `0,40 s` · sesgo `−0,0669 s` · `422` palabras emparejadas | [`data/eval/2026-08-10.json`](data/eval/2026-08-10.json) | primera corrida del gate `/eval` sobre el fixture de 3 min (10-ago-2026), **antes** de la serie de arreglos del anclaje |
| medio `0,045 s` · p95 `0,090 s` · 0 palabras >0,5 s tarde | salida real de `scripts/audit_run.py --stem video_012` (20-ago-2026, ver `.claude/rules/sessions-log.md` v1.2/v1.3) | el **mismo fixture de 3 min**, después de esos arreglos |
| resto de decisiones técnicas (sección siguiente) | [`.claude/incident-ledger.md`](.claude/incident-ledger.md) | registro append-only, un incidente por línea con su evidencia |

Las dos primeras filas son el **mismo fixture en dos momentos**, no fixture contra producción —
si el README las cita juntas sin esta nota, parece una contradicción. La única corrida a escala
de producción real (30 min, 10-ago-2026) dio un error bastante peor
([`data/eval/2026-08-10-produccion-real.json`](data/eval/2026-08-10-produccion-real.json),
`0,153 s` medio, `1,82 s` máximo) porque a esa escala aparecen defectos que un clip de 3 minutos
no puede ejercer — detalle en `CLAUDE.md`, sección "Validación E2E".

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

**Subida a YouTube:** está implementada (`modules/youtube_uploader.py`, OAuth de aplicación de
escritorio, pestaña 📤 Subir del dashboard), pero **nunca se ha ejecutado en real** — hace falta
un `client_secret.json` propio de Google Cloud Console, que no se distribuye. Por diseño sube en
**privado** y solo el vídeo largo (no los shorts: 50 subidas gastarían más cuota de la YouTube API
de la que hay en un día), y se dispara a mano desde una cola con el veredicto del auditor a la
vista — nunca automáticamente al terminar una corrida.

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
  otros arreglos del anclaje sobre el mismo fixture (ver "Mapa de evidencia" arriba).
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

## Cómo se construyó

Empecé este proyecto sin saber programar y lo levanté trabajando con Claude Code: 92 de los 120
commits del repo llevan `Co-Authored-By: Claude`, y `CLAUDE.md` (506 líneas) es el contrato real
de cómo se trabaja aquí — qué superficies son sensibles, qué gate hay que pasar antes de cerrar
un cambio, qué no se hace nunca. No es un detalle que esconder: es el método.

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

## Estado

La cadena corre de punta a punta y cada corrida se audita automáticamente antes de ofrecerse
para subir (ver el gate más arriba). Eso no significa que esté todo cerrado: hay defectos
conocidos y abiertos, y la forma honesta de verlos no es una lista de intenciones sino
[`.claude/incident-ledger.md`](.claude/incident-ledger.md) — un registro append-only de
incidentes reales, cada uno con su evidencia, su clase y si sigue pendiente o ya se arregló.

## Licencia

Código bajo MIT. `assets/` (plantilla de miniatura/intro, woosh) **no se distribuye** — son
recursos de terceros; ver [`assets/README.md`](assets/README.md).
