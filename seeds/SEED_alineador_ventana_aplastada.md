# SEED A — La ventana aplastada del alineador (diagnóstico CERRADO, falta el fix)

> PASO 0 OBLIGATORIO: invoca /seed-review sobre este SEED antes de tocar nada.

**Modelo de trabajo:** Opus 5 orquesta y audita, Sonnet 5 implementa (`CLAUDE.md` §ORQUESTACIÓN).
**Rama:** `git checkout -b fix/alineador`. **Nunca `git push`.**

> **Esta es la v2.** La v1 la escribió una sesión anclada en su propio diagnóstico y un panel
> adversarial la reescribió: decía "investiga el alineador" cuando el diagnóstico ya se podía
> cerrar con lo que hay en disco, daba un criterio de aceptación **ciego a este fallo**, afirmaba
> una reproducibilidad que **no existe**, y apartaba del foco una segunda causa aguas arriba.

---

## 🚨 ANTES DE NADA — dos acciones de 30 segundos

1. **Copia la evidencia fuera de `temp/`:**
   ```
   cp test_e2e/temp/video_004_subs.ass  data/evidence/video_004_subs.ass
   cp test_e2e/temp/video_004_audio.mp3 data/evidence/video_004_audio.mp3
   ```
   `cleanup_temp` hace `shutil.rmtree(temp_dir)` sobre `test_e2e/temp/`, así que **cualquier
   `main.py --config test_e2e/config.yaml` sin `--keep-temp` borra la única evidencia física del bug
   que vienes a arreglar.**
2. **NO ejecutes `main.py` ni `/eval`.** El track E es la única sesión autorizada (`pipeline.log` es
   ruta fija, `temp/` es compartido, `assets/.tint_index` es read-modify-write sin lock). Todo tu
   trabajo se hace con bancos offline.

⚠️ **`scripts/anchor_bench.py dump-raw` con sus defaults ESCRIBE EN `data/evidence/`**
(`SCRATCH = os.environ.get("ANCHOR_BENCH_DIR", "data/evidence")`, `RAW = raw_words.json`), que está
declarado **INTOCABLE** y contiene el corpus del 10-ago. El comando de su propio docstring se ejecuta
sin error y **destruye la evidencia**. Exporta `ANCHOR_BENCH_DIR` a un directorio de trabajo antes de
usarlo.

## El diagnóstico, CERRADO (no lo repitas: verifícalo y arregla)

**La causa NO es la longitud de frase ni la constante `PALABRAS_FRASE_MAX`.** Es una expresión
concreta en el anclaje.

### Dónde está el error, palabra a palabra
Ventana = `ass[317:374]` de `video_004_subs.ass`, 57 palabras, t **110,13 → 126,12 s**.
Medido contra transcripción independiente (faster-whisper `small`, cobertura 94,9%):

```
ANTES de la ventana (60 pal): mediana -0.100  max +0.100  >0,5 s tarde:  0
DENTRO      (57 pal):         mediana +0.460  max +0.910  >0,5 s tarde: 21
DESPUES     (60 pal):         mediana -0.140  max +0.380  >0,5 s tarde:  0
```
**Las 21 palabras tardías de TODA la corrida están dentro de esa ventana.** El error crece
monótonamente dentro (+0,04 → +0,91) y se resetea al salir. El `peor tramo +0,610 s en t=115,81 s`
que tumbó el gate cae ahí.

### La línea culpable
`modules/tts_engine.py:936`
```python
util = min(s_dur, len(indices) / ANCLA_WPM_TIPICO * 60) if ritmo_inservible else s_dur
```
Con `ANCLA_WPM_TIPICO = 210` y 57 palabras: `57/210*60 = 16,29 s`, pero `s_dur = 15,99 s`, así que
**el tope de 210 wpm NO limita y `util` degenera en `s_dur` entero** — la ventana completa de
edge-tts, **silencio de cola incluido**. Que es exactamente el pecado original que `CLAUDE.md`
documenta: *las ventanas de `SentenceBoundary` tilan el audio entero, silencios incluidos*.

Instrumento **no circular** (`silencedetect`, no depende de Whisper): la voz de esa frase va de
**110,338 a 125,195 = 14,857 s → 230 wpm**. El `s_dur` trae **1,13 s de silencio de cola** que el
reparto reparte entre las 57 palabras.

Simulación del mismo reparto con distintos `util`, re-medida contra la misma transcripción:

| `util` | wpm implícito | mediana | max | >0,5 s tarde |
|---|---|---|---|---|
| 15,99 | 214 | +0,454 | +0,906 | **21** ← lo publicado |
| 16,29 | 210 | +0,563 | +1,193 | 30 ← el tope actual, si limitara |
| **14,86** | **230** | **−0,154** | +0,447 | **0** ← span de voz medido |
| 14,49 | 236 | −0,218 | +0,382 | 0 |

### De los tres bugs posibles, cuál es
- El detector **dispara y es verdadero positivo** (span crudo 10,32 s frente a 14,86 s reales = 1,44x
  de compresión). **No** es un falso positivo.
- El **ancla está bien** (110,13 contra voz en 110,338).
- **El defecto está en `util`.** Y hay material para arreglarlo ya en el fichero: **`_tramos_de_voz()`
  (`tts_engine.py:599`) devuelve el span de voz real** y ya se usa en `_extend_sentence_final_words`.
- En la rama de reparto, `offset_ventana` **no se usa nunca** (`cursor = s_start`): el
  `Ancla descartada en t=110.14s` del log es trabajo calculado y tirado, no un segundo hecho.

### Ya medido y DESCARTADO — no lo propongas otra vez
**[ANCLA-04] probó reescalar la ventana** cuando ocupa más de lo que se tarda en decirla: **empeora
con todos los umbrales** (3 → 6 → 14 → 23 ventanas malas con 1.5/1.25/1.15). Es lo primero que se le
ocurre a cualquiera. No lo repitas.

## SEGUNDA CAUSA, aguas arriba — está EN TU ALCANCE

`_ensure_breathing_periods` inicializa `titulo_en_curso = True` **dentro** del bucle
`for parrafo in text.split("\n")`, así que la exención pensada para el título **se aplica a la
primera frase de CADA párrafo**. Reproducido: un párrafo formado por una sola frase larga **no se
parte ni con `cada=12`**.

Consecuencia medida: la frase de 57 palabras que se convirtió en la ventana aplastada **es la primera
de su párrafo, y mide 57 palabras con `cada` = 12, 20, 30 y 40 por igual**.

```
cada=12: 31 frases, mediana 18, max 57, exceden el limite: 23
cada=20: 26 frases, mediana 24, max 57, exceden: 16
cada=30: 23 frases, mediana 31, max 57, exceden: 12
cada=40: 22 frases, mediana 33, max 57, exceden:  3
```
**Esto reexplica la tabla A/B del barrido mejor que la sesión anterior**: no es que "unos cortes
parten la zona patológica y otros no" — **ningún valor de la constante la toca**, y las diferencias
de aquella tabla eran ruido de las *otras* frases. Misma conclusión (**no toques la constante**),
razón correcta, y con un bug concreto detrás.

No es suficiente por sí sola: `video_003` arrastra una frase de **181 palabras** exenta y midió
limpio. Pero es la condición que permite que un solo fallo del alineador se coma 16 s de vídeo.

## ⚠️ El criterio de aceptación obvio es CIEGO a este fallo

`scripts/anchor_bench.py` corre hoy y su control pasa (`dif media 0,0043 s, max 0,0100 s`), y con el
código actual ya da `0 ventanas que empeoran` en las dos producciones. **Y aun así no vería tu fix
romperse**, porque:

```
10-ago: 214 ventanas | 1 aplastada (t=1594,02; n=5; util=1,43)  <- limita el tope de 210 wpm
11-ago: 110 ventanas | 1 aplastada (t= 137,82; n=44; util=12,57) <- limita el tope de 210 wpm
video_004:  18 ventanas | 1 aplastada                            <- limita s_dur  ← EL CASO
```
**En los dos corpus del banco, `util` lo limita el tope de 210 wpm; solo en `video_004` lo limita
`s_dur`.** Un fix puede dar *"0 ventanas empeoran"* **sin haber tocado nunca el caso que rompe**.

> **Por tanto: `anchor_bench` en verde es NECESARIO y NO SUFICIENTE. Sin un tercer corpus que
> contenga una ventana aplastada limitada por `s_dur`, el verde no significa nada.**

### Y ese corpus no existe: hay que construirlo
Las **entradas** de `_validate_and_fix_alignment` —las palabras crudas de stable-ts y la lista de
`SentenceBoundary`— **no se persisten en ningún sitio** (`sentences` solo vive en memoria dentro de
`run_tts`), y `dump-raw` **solo vuelca palabras crudas, nunca las sentences**. Lo que hay en
`test_e2e/temp/video_004_*` es el `.ass` **posterior** al anclaje.

Vía más barata, sin pipeline y **sin gastar una sola petición de OpenRouter**: re-sintetizar solo el
TTS de `test_e2e/temp/video_004_story.txt` (edge-tts + stable-ts, sin composición y sin
`pipeline.log`) y volcar **palabras crudas + `SentenceBoundary`** como tercer corpus del banco. Eso
es además **el instrumento que falta desde [ANCLA-05]**, así que vale para siempre.

⚠️ **`video_004` se produjo con el commit `27f025e` (`PALABRAS_FRASE_MAX = 40`); HEAD es `d1496a8`
(30).** Diagnosticar un binario de otro commit es la clase [REVIEW-01], ya pagada aquí. Si
re-sintetizas, hazlo con el partidor de `27f025e` o el corpus no reproducirá el caso.

## El gemelo de shorts: [ANCLA-05] dice que no hay banco — pero SÍ se puede medir hoy

Un fix del alineador puede dar verde en el vídeo largo y **romper los shorts** ([ANCLA-03]: 3 de 16
rotos con el vídeo largo mejorando). No hace falta banco: compara `short_00X_subs.ass` contra
faster-whisper de `short_00X_audio.mp3` (misma línea de tiempo). **Línea base ya medida, úsala como
no-regresión:**

```
short_005: 157 pares, cobertura 98,7%, |err| medio 0,134 s, sesgo -0,129 s, max 0,240 s,
           0 palabras >0,5 s tarde
```

## Trampas ya pagadas

1. **[INSTR-05] La métrica acústica del auditor es un NETO** (`silencios − signos`): **cuenta, no
   localiza**. Da 0 mientras el instrumento posicional marca pausas mal puestas. No la uses sola.
2. **[GATE-03] El gate NO es determinista**: historia nueva cada corrida. Para llamar regresión a
   algo hace falta A/B controlado.
3. **[SYNC-01] La variable que manipulas no puede estar dentro del instrumento con el que eliges.**
   Así se eligió mal una constante ayer.
4. **Calibra el emparejador antes de creerle**: el de reloj de habla dio **8%** de acierto sobre
   26 min; con Whisper independiente sobre tramos cortos, 98-100%.
5. **`target_wpm` está acoplado a `PALABRAS_FRASE_MAX`**: si tocas una, re-mide la otra **sobre el
   audio**. Hoy están en 30 y 196.
6. **La mediana esconde el defecto local** ([ANCLA-01]). Mira el peor tramo.

## Fuera de alcance (no te distraigas)

`pipeline.log` de la corrida roja trae otros dos WARNING que **no son tuyos**: la historia que llegó
al límite sin bloque de cierre, y el truncado que descarta 1.540 palabras del cuerpo. Son del régimen
de 3 minutos del fixture y los cubre el track E.

Tampoco es tuyo el juicio de si la narración "se entiende": Diego ya eligió de oído entre cinco
versiones y declaró **no distinguir** entre frases de mediana 26, 32 y 43. **No le pidas que escuche
variantes de longitud de frase.**

## Criterio de aceptación

1. La ventana `t=110,13→126,12` de `video_004` baja de **21 palabras >0,5 s tarde a 0**, medido
   contra transcripción independiente.
2. `anchor_bench` sobre las **dos** producciones reales: **0 ventanas que empeoran** (necesario).
3. **El tercer corpus** (el que contiene la aplastada limitada por `s_dur`) existe, está en el banco,
   y el fix se demuestra sobre él (suficiente).
4. Los shorts no empeoran contra la línea base de arriba.
5. El bug de `titulo_en_curso` arreglado, con el invariante de **número de palabras** intacto (hay un
   `raise` que lo fuerza) y `target_wpm` re-medido si la distribución de frases cambia.

Entrada factual en `.claude/incident-ledger.md` por cada defecto. **El retro no escribe reglas, solo
`/optimize` promueve.**
