# SEED A — La ventana aplastada del alineador (diagnóstico CERRADO, falta el fix)

> PASO 0 OBLIGATORIO: invoca /seed-review sobre este SEED antes de tocar nada.

**Modelo de trabajo:** Opus 5 orquesta y audita, Sonnet 5 implementa (`CLAUDE.md` §ORQUESTACIÓN).
**Rama:** `git checkout -b fix/alineador`. **Nunca `git push`.**

> **Esta es la v3**, reescrita por `/seed-review` (1 agente ciego + 3 críticos, 13-ago-2026).
> La **causa raíz de la v2 quedó CONFIRMADA por cuatro mediciones independientes** — incluido un
> agente que no vio el SEED y llegó a la misma línea. Lo que el panel tumbó fue **el criterio de
> aceptación (3 de 5 criterios pasaban por construcción o eran inejecutables), la receta del tercer
> corpus, y la descripción del mecanismo** — que estaba incompleta *de una forma que cambia el fix*.
> Las correcciones van marcadas **[v3]**.

---

## 🚨 ANTES DE NADA

1. La evidencia **ya está copiada** fuera de `temp/` (hecho el 13-ago 17:53): `data/evidence/video_004_subs.ass`,
   `video_004_audio.mp3`, `video_004_story.txt`. **No la borres ni la sobrescribas.**
   `cleanup_temp` hace `shutil.rmtree(test_e2e/temp/)`: cualquier `main.py --config test_e2e/config.yaml`
   sin `--keep-temp` se lleva los originales.
2. **NO ejecutes `main.py` ni `/eval`.** El track E es la única sesión autorizada (`pipeline.log` es
   ruta fija, `temp/` es compartido, `assets/.tint_index` es read-modify-write sin lock). Todo tu
   trabajo se hace con bancos offline.

⚠️ **`scripts/anchor_bench.py dump-raw` con sus defaults ESCRIBE EN `data/evidence/`**
(`SCRATCH = os.environ.get("ANCHOR_BENCH_DIR", "data/evidence")`, `RAW = raw_words.json`), que
contiene el corpus del 10-ago. El comando de su propio docstring se ejecuta sin error y **destruye la
evidencia**. Exporta `ANCHOR_BENCH_DIR` a un directorio de trabajo antes de usarlo. *(Verificado por
el panel: el aviso es real, `anchor_bench.py:28,31`.)*

## El diagnóstico, CERRADO (verificado 4 veces — no lo repitas)

**La causa NO es la longitud de frase ni la constante `PALABRAS_FRASE_MAX`.** Es `modules/tts_engine.py:936`.

Ventana = `ass[317:374]` de `video_004_subs.ass`, 57 palabras, t **110,13 → 126,12 s**.
Contra transcripción independiente (faster-whisper `small`, cobertura 94,9% global, **51/57 = 89,5%
dentro de la ventana** — declara el denominador **[v3]**):

```
ANTES de la ventana (60 pal): mediana -0.100  max +0.100  >0,5 s tarde:  0
DENTRO      (57 pal):         mediana +0.460  max +0.910  >0,5 s tarde: 21
DESPUES     (60 pal):         mediana -0.140  max +0.380  >0,5 s tarde:  0
```
**Las 21 palabras tardías de TODA la corrida están dentro de esa ventana.** Reproducido al dígito por
tres agentes distintos (uno de ellos sin ver este SEED).

### La línea culpable
```python
# modules/tts_engine.py:936
util = min(s_dur, len(indices) / ANCLA_WPM_TIPICO * 60) if ritmo_inservible else s_dur
```
Con `ANCLA_WPM_TIPICO = 210` y 57 palabras: `57/210*60 = 16,29 s`, pero `s_dur = 15,99 s`, así que
**el tope de 210 wpm NO limita y `util` degenera en `s_dur` entero** — la ventana completa de
edge-tts, silencio incluido. Es el pecado original que `CLAUDE.md` documenta, sobreviviendo en la
rama de *fallback* después de que la rama de traslación dejara de cometerlo.

**Demostrado por reconstrucción, no por lectura**: reajustando el reparto por caracteres desde
110,13, solo `s_dur` reproduce el `.ass` publicado — `util=15,99 → max|pred−real| 0,0071 s`;
`util=16,29 → 0,2969 s`; `util=14,86 → 1,0960 s`.

Instrumento no circular (`silencedetect`): la voz va de **110,338 a 125,195 = 14,857 s → 230 wpm**.
Robusto al umbral **[v3]**: −25/−30/−35/−40/−45 dB dan 14,810 / 14,840 / **14,857** / 14,882 / 14,884.

### ⚠️ [v3] EL MECANISMO TIENE DOS COMPONENTES, NO UNO — y por eso cambiar `util` NO basta
La v2 decía *"el error crece monótonamente dentro"*. **Es falso: es un diente de sierra con tres
reinicios**, y los tres caen exactamente en los tres silencios internos medidos
(113,245-113,671 / 118,815-119,218 / 119,984-120,350 = **1,196 s de pausas internas**):

```
112.97 +0.650 EN | 113.11 +0.430 | 113.32 +0.480 ... 113.66 +0.040 HE   <- reset
118.58 +0.720    | 118.85 +0.750 ...................  119.48 +0.300     <- reset
119.82 +0.340    ....................................  120.38 +0.060 HE <- reset
124.39 +0.710 | 125.22 +0.820 | 125.57 +0.910 EL | 125.70 +0.900 PECHO.
```
Hay **dos** fuentes de error: (a) la cola de silencio — que un `util` mejor sí quita — y (b) el
reparto lineal por caracteres, que **aplana 1,196 s de pausas internas** y que ningún escalar toca.
Con el mejor escalar (`util = 14,86`) el residuo queda `min −0,68 / max +0,45`: rango 1,13 s ≈ justo
la pausa interna ignorada.

**Consecuencia para el fix: repartir SOBRE LOS TRAMOS DE VOZ, saltando los silencios, no elegir mejor
un escalar.** `_tramos_de_voz()` (`tts_engine.py:599`) ya devuelve lo que hace falta y ya se usa en
`_extend_sentence_final_words`. Medido por dos agentes de forma independiente, dentro de la ventana:

| variante | mediana | max | >0,5 s tarde | p95 |
|---|---|---|---|---|
| publicado (`util = s_dur`) | +0,460 | +0,910 | **21** | 0,460 |
| escalar `util = 14,86` (lo que proponía la v2) | −0,150 | +0,450 | 0 | 0,253 |
| **reparto por tramos de voz** | **+0,030** | **+0,440** | **0** | **0,220** |

⚠️ **Ninguna de las dos alcanza el `|err| max ≤ 0,30` que el gate declara como objetivo.** O se relaja
ese objetivo con argumento, o hace falta algo más (ver *mapeo afín*, abajo). **Descúbrelo ahora, no
después de implementar.**

### [v3] Todos estos números están en la línea de tiempo del MP3. El gate mide el MP4, que va +0,100 s
`modules/video_composer.py:88` compone con `-itsoffset -0.10`. Medido: MP3 → `peor tramo +0,510 en
t=115,81`, 21 tardías; el auditor sobre el MP4 registró `+0,610 s en t=115,81` y **28** tardías —
Δ exactamente +0,100 s, misma t. **Todo umbral que escribas tiene que decir sobre qué fichero se
mide**, o el mismo fix pasa o falla según quién lo corra.

### De los tres bugs posibles, cuál es
- El detector **dispara y es verdadero positivo** (span crudo 10,32 s → 331 wpm). **No** es falso positivo.
  **[v3] Ojo al borde: dispara por 1,4 wpm** (331 vs `ANCLA_WPM_MAX = 330`). Una ventana a 328 wpm se
  va por la rama de traslación y este fix no la toca.
- El **ancla está bien** (110,13 contra voz en 110,338). **[v3] Y por eso el `cursor = s_start` deja
  0,208 s de cabeza sin corregir**: la v2 decía "1,13 s de silencio de cola" cuando son **0,925 de
  cola + 0,208 de cabeza**. Al colocar bien el arranque (start=110,338) la métrica **empeora**
  (mediana +0,050, 1 tardía) — es decir, parte de la ganancia del fix viene de dejar el subtítulo
  ~0,2 s adelantado, que es barato. **Dilo así**, o la siguiente sesión "corregirá" la cabeza y
  romperá el resultado.
- **El defecto está en `util`** (y en el reparto plano, ver arriba).
- En la rama de reparto, `offset_ventana` **no se usa nunca** (`cursor = s_start`): el
  `Ancla descartada en t=110.14s` del log es trabajo calculado y tirado.

### Ya medido y DESCARTADO — pero OJO al alcance real de la prohibición **[v3]**
**[ANCLA-04] descartó reescalar la ventana cuando OCUPA MÁS de lo que se tarda en decirla** (ratios
span/necesario **>1**: 1.5/1.25/1.15 → 3/6/14/23 ventanas malas). `video_004` es **el caso contrario**:
span/necesario = 10,32/16,29 = **0,63**. La cita no aplica aquí.

Y hay un dato que la v2 no explotó: del log, `residuo −4,742` ⇒ el crudo de stable-ts va de **114,882
a 125,202**, y el fin real de la voz es **125,195** — acertó el final con **7 ms** y falló el arranque
por 4,54 s. Un **mapeo afín del ritmo crudo sobre `[110,338 , 125,195]`** conservaría las pausas
internas que el reparto por caracteres destruye, y **no es lo que ANCLA-04 midió**. Es la vía a probar
si el reparto por tramos no llega al `max ≤ 0,30`. (No demostrable con lo que hay en disco: las
palabras crudas de `video_004` no se persistieron — otra razón para el corpus de abajo.)

## SEGUNDA CAUSA: no es "secundaria", es la que devuelve el guardia a su régimen válido **[v3]**

`_ensure_breathing_periods` inicializa `titulo_en_curso = True` **dentro** del bucle
`for parrafo in text.split("\n")` (`tts_engine.py:281-285`), así que la exención pensada para el
título **se aplica a la primera frase de CADA párrafo**. Confirmado leyendo el código y reproducido:
la frase de 57 palabras es **la primera de su párrafo** y mide 57 con `cada` = 12, 20, 30 y 40.

**Por qué importa más de lo que decía la v2:** el tope `n·60/210` crece **linealmente con n** y el
silencio de la ventana no. Medido, la velocidad real sobre TIEMPO DE VOZ es 210 wpm (`video_004`) y
235 (11-ago), o sea `ANCLA_WPM_TIPICO` está **en o por debajo** del ritmo real: el tope solo muerde si
el silencio de la ventana supera ≈`0,025·n` s. Para n=44 (1,13 s) muerde; para n=57 harían falta 1,42
y solo había 1,13. **El guardia es inerte justo en las ventanas largas, que son las que más daño
hacen.** Con frases ≤30 palabras el umbral baja a ~0,75 s, que es la cola típica → **el tope vuelve a
morder solo**.

**Pero NO cierra el caso por sí solo [v3]:** con el fix, la frase pasa de 57 a **43-45** palabras,
sigue por encima del límite, y si el aplastamiento se reparte uniforme el wpm implícito **sigue siendo
~331** → sigue disparando `aplastada`. Redúcelo de "la condición que permite el fallo" a lo que es:
**encoge el daño de ~16 s a ~12 s y devuelve el tope a su régimen**. No lo apuntes como cierre.

### El fix, y lo que NO puede romper (verificado)
- **Sacar `titulo_en_curso = True` fuera del bucle.** NO detectar el título por número de palabras:
  eso sí acoplaría con `main.py`.
- **El título sigue protegido**: `script_generator.py:597-600,648` fuerza `title_sentence = title + "."`
  → el título es la 1.ª frase del párrafo 0 y acaba en punto, que es lo que apaga el flag. Y
  `_clean_speech_for_tts:89-90` garantiza que todo párrafo acaba en `.!?`.
- **El invariante de palabras aguanta**: el `raise` de `tts_engine.py:318` compara sobre la salida
  completa. Verificado con el fix en 3 corpus × 4 valores de `cada`: 604=604, 5290=5290, 5334=5334,
  **0 violaciones**.
- **`target_wpm` NO es bloqueante [v3]**: el fix añade ~14 frases sobre 163 (+8,6%) → **~1,4 wpm**
  (0,7%), por debajo de la dispersión 0,6% que el propio `config.yaml` declara para n=2. Decláralo
  medido por interpolación con la tabla de `config.yaml:78-86`; **no gastes una síntesis de 26 min**.
- ⚠️ **Toca los SHORTS**: `shorts_generator.py:396 → run_tts → _clean_speech_for_tts` usa la misma
  función y el mismo `PALABRAS_FRASE_MAX = 30`. En un short de ~180 palabras y 7 frases, cada punto
  nuevo son ~0,73 s a x1.5 y **+40% de ventanas de anclaje** sobre una base de 7. Precedente exacto:
  [ANCLA-03], 3 de 16 shorts rotos por un fix que dejaba el largo en verde.
- ⚠️ **Y el texto de los shorts NO SE PERSISTE** (`shorts_generator` solo escribe `{stem}_title.txt`;
  el `story` muere en memoria). Sin eso, medir el efecto del fix en un short exige una petición nueva
  de OpenRouter y una historia distinta = [GATE-03], gate no determinista. **Primer paso del bloque:
  persistir `short_00X_story.txt` (2 líneas en `generate_short`).**

## [v3] La premisa "el banco es ciego a este modo" era DEMASIADO FUERTE

La v2 decía que en los dos corpus `util` lo limita siempre el tope de 210. **Falso**: hay 5 ventanas
de reparto (no 2), y una ya está limitada por `s_dur`:

```
10ago t=  606.48 n= 6 s_dur= 2.91 tope210= 1.71 util= 1.71  <- TOPE210
10ago t=  609.39 n= 5 s_dur= 2.44 tope210= 1.43 util= 2.44  <- s_dur (span crudo NEGATIVO, -0.09)
10ago t= 1594.02 n= 5 s_dur= 2.50 tope210= 1.43 util= 1.43  <- TOPE210
11ago t=  128.55 n=29 s_dur= 9.28 tope210= 8.29 util= 8.29  <- TOPE210
11ago t=  137.82 n=44 s_dur=13.49 tope210=12.57 util=12.57  <- TOPE210
```
Y `t=609.39` es **la peor de las cinco**: `mediana +0,355 max +0,539, 1 palabra >0,5 s tarde`. O sea:
el banco **sí tiene sonda** del modo de fallo, débil (n=5). Lo honesto es *"el verde con n=5 no cubre
n=57"*, no *"el verde no significa nada"*. El tercer corpus sigue mereciendo la pena — por tamaño, no
porque sea la diferencia entre medir y no medir.

### [v3] La receta del tercer corpus de la v2 ERA INCORRECTA
Medido con 3 síntesis: los **`SentenceBoundary` son deterministas al milisegundo** (18 sentences,
`start 110,138 dur 15,988`, idénticas entre corridas), **pero la forma de onda NO**: mismo tamaño de
fichero, **48,5% de los bytes distintos**, md5 distinto. Y la ventana aplastada **no es propiedad del
texto: es lo que stable-ts hizo con ESE audio**. Si sigues la receta literal de la v2 (re-sintetizar y
alinear el audio nuevo), **el corpus puede salir sin la ventana aplastada** y el criterio "suficiente"
se cae sin que nadie lo note.

**Receta correcta y más barata:**
1. `sentences` de la re-síntesis (probado idéntico) — o directamente del `.ass`: `s_start = 110,130`
   y `s_dur = 15,990` son el start del primer cue y el end del último de la rama.
2. **palabras crudas: `_forced_align` sobre `data/evidence/video_004_audio.mp3`, el audio PUBLICADO.**
   Nunca sobre uno re-sintetizado. No se mezclan líneas de tiempo.
3. **Congélalo como DATOS** en `data/evidence/`: `raw_words_v004.json` + `sents_v004.json` +
   `whisper_v004.json` (el referí, congelado, para que el antes/después use la MISMA referencia).
   **Nunca como "receta para regenerar desde el story.txt"**: en cuanto entre el fix de
   `titulo_en_curso`, la frase de 57 desaparece y el corpus deja de probar el bug **en silencio**.
4. **ORDEN OBLIGATORIO: congela el corpus ANTES de tocar `_ensure_breathing_periods`.**

**[v3] El aviso de commit de la v2 (`27f025e` vs `d1496a8`) NO es load-bearing**: verificado, con el
partidor de HEAD (30) el caso se reproduce igual — `n=57, dur 15,988, limitado por s_dur`, solo
desplazado 0,6 s. Puedes construir el corpus en HEAD. Lo que destruye el caso es el criterio 5, no el
commit.

## [v3] El fix necesita el AUDIO, y eso rompe el criterio 2 tal y como estaba escrito

`_validate_and_fix_alignment(words, sentences)` **no recibe audio** (`tts_engine.py:708`), y
`scripts/anchor_bench.py:303,329` la llama con dos posicionales. Además **no existe el audio del
10-ago** (en `data/evidence/` solo hay `audio_11ago.mp3` y `video_004_audio.mp3`).

- ✅ Ambas rutas (largo y short) pasan por `run_tts`, que **ya tiene `audio_path`**: pasarlo cubre el
  gemelo gratis y sobre el fichero correcto (`_audio_normal.mp3`, **antes** del atempo).
- ⛔ **PROHIBIDO el fallback mudo** `audio_path=None → comportamiento viejo`: el banco daría
  `0 ventanas empeoran` **sin haber ejercido el fix** (`decision-making.md` §13, y es exactamente el
  verde ciego que este SEED denuncia). Si falta el audio: **WARNING ruidoso + marcar la corrida como
  no evaluable**, igual que hace `_extend_sentence_final_words:642-647`.
- El criterio 2 se reescribe: **0 ventanas que empeoran en 11-ago (medible); 10-ago NO evaluable por
  falta de audio, declarado.**

### [v3] Casos degenerados: medidos, y la mayoría NO ocurren (esto va a favor del fix)
Sobre el único corpus con audio (11-ago, 110 ventanas):
```
ventanas cuyo START cae DENTRO de un tramo de voz: 0/110
ventanas cuyo END   cae DENTRO de un tramo de voz: 0/110
span_voz/s_dur: min 0.320  p50 0.912  p95 0.959  max 0.975
ventanas donde span_voz > s_dur (el fix alargaria): 0     ventanas sin ningun tramo de voz: 0
```
"Otro hablante" y "música" no aplican: `run_tts` recibe el MP3 del TTS puro (el mezclado es otro
fichero). **Quedan dos que SÍ hay que cubrir:** (a) `_tramos_de_voz` devuelve un último tramo
`(cursor, inf)` — un `b−a` ingenuo da `inf`; (b) si ffmpeg falla, degrada con warning, no revientes la
alineación.

**Y donde el tope de 210 SÍ mordía hoy, el fix las mejora** (medido en 11-ago):
```
t=128.55: ANTES mediana +0.112 max +0.416 -> DESPUES +0.031 / +0.332
t=137.82: ANTES mediana +0.043 max +0.470 -> DESPUES -0.066 / +0.388
ventanas que EMPEORAN >0.05s: 0      |err| medio global 0.1021 -> 0.1022
```

## El gemelo de shorts: la línea base es correcta pero **INERTE para este fix** **[v3]**

`short_005: 157 pares, cobertura 98,7%, |err| medio 0,134 s, sesgo −0,129 s, max 0,240 s, 0 >0,5 s tarde`
— **reproducida al dígito** por el panel. Dos avisos:
- ⚠️ Mídela contra **`short_005_audio.mp3`** (x1.5), no contra `_audio_normal.mp3`: el fichero
  equivocado da `cobertura 100%` y `0 palabras >0,5 s tarde` con **11,4 s de error medio**. La métrica
  de tardanza es de un solo lado y no te avisa.
- ⚠️ **Ningún short entra en la rama que vas a cambiar**: todos los de `pipeline.log` dan
  `0 repartidas por caracteres`. Un fix que solo toque `util` deja `short_005_subs.ass` bit a bit
  idéntico → **este criterio devolverá los mismos números haga lo que haga el fix**. Es un control de
  no-daño colateral, **no** una prueba del cambio. Para probar el gemelo hace falta forzar la rama con
  una alineación aplastada sintética, o declarar explícitamente que no está cubierto.

## 🔴 [v3] DEFECTO MAYOR EN EL MISMO ARTEFACTO, sin dueño en ningún track — decisión de Diego

`video_004` **narra y subtitula el índice en Markdown que el modelo escribió sobre sí mismo**:
```
data/evidence/video_004_subs.ass, cue 449 -> ultimo cue
0:02:31.66 RESUMEN / DE / LOS / ELEMENTOS / SOLICITADOS / INCLUIDOS: / 1. / PLAN ...
0:03:27.45 ... LA METAFORA DE LA MADERA QUE SE FORTALECE AL CORTARSE BIEN.   <- ultimo cue
```
**55,8 s de 208 = 27% del vídeo.** Y los guardias, ejecutados sobre ese texto en HEAD, dan:
`_strip_trailing_metadata` → **no-op** (604 → 604 palabras) · `_detectar_basura` → `(False, '')` ·
el auditor → `OK basura del modelo: ninguna`. Peor: `_truncate_to_words` **ascendió esa cola a
"desenlace"** (`pipeline.log`: *"se descartan 1540 palabras del CUERPO... se conservan las ultimas 256"*
— y los dos últimos párrafos suman exactamente 256 palabras), así que el `\n\n` que crea **también
fabricó el párrafo cuya primera frase es la ventana aplastada**. La cadena causal empieza ahí.

`_RE_META_FINAL` (`script_generator.py:395-406`) solo caza `PALABRAS: N` / `FIN DE LA HISTORIA`. Esta
forma no está contemplada. **Gemelo: `shorts_generator.py:201` usa la misma función.**

**Implicación para este track:** el criterio de aceptación de abajo mide **sincronismo**, no
publicabilidad. `video_004` seguirá siendo **impublicable** al cerrar el track, por un defecto 27
veces mayor que el que vienes a arreglar. Está registrado como **[BASURA-03]**; **Diego decide** si
entra aquí, en el track D (caza-bugs) o en el E.

## Trampas ya pagadas

1. **[INSTR-05] La métrica acústica del auditor es un NETO** (`silencios − signos`): cuenta, no
   localiza. No la uses sola.
2. **[GATE-03] El gate NO es determinista**: historia nueva cada corrida. Para llamar regresión a algo
   hace falta A/B controlado.
3. **[SYNC-01] La variable que manipulas no puede estar dentro del instrumento con el que eliges.**
   **[v3] Aplica a este SEED**: la fila `util=14,86` de la v2 se eligió *porque daba 0 contra esa
   transcripción*. Implementarla y volver a medirla no es un test, es repetir la calibración.
4. **Calibra el emparejador antes de creerle.** Verificado: `eval_sync.py:120` y `anchor_bench.py:161`
   **no** son `difflib` global (ventanas locales de 100, holgura 150) — [INSTR-02] está cerrado. Y la
   cobertura es invariante al retiming (emparejan por texto): `543 pares / 94,9%` idénticos para
   `util ∈ {15,99 · 14,86 · 12 · 10 · 8}`. **No puedes falsear el criterio moviendo la cobertura**,
   pero tampoco te avisa de nada.
5. **[v3] `target_wpm` NO bloquea** (ver arriba, ~1,4 wpm por interpolación).
6. **La mediana esconde el defecto local** ([ANCLA-01]). Mira el peor tramo.
7. **[v3] `anchor_bench` es ciego a los `end`**: su control corre
   `_validate_and_fix_alignment → _enforce_monotonic` (`anchor_bench.py:302-303`) y **se salta**
   `_extend_sentence_final_words`, que sí corrió en producción (`run_tts`, `tts_engine.py:976-980`).
   Los `start` no dependen de los `end`, así que el control debería seguir dando ~0 — **verifícalo, no
   lo asumas**. Lo que el banco **no** puede evaluar es "voz sin subtítulo", que vive en los `end`.

## Fuera de alcance

`pipeline.log` trae dos WARNING más: la historia que llegó al límite sin bloque de cierre y el
truncado que descarta 1.540 palabras. **[v3] Ya no son "solo del régimen del fixture"**: el truncado
fabricó el párrafo de la ventana aplastada (ver §BASURA-03). Siguen sin ser tuyos de *arreglar*, pero
**nómbralos en el cierre** en vez de declararlos irrelevantes.

Tampoco es tuyo el juicio de si la narración "se entiende": Diego ya eligió de oído entre cinco
versiones y declaró **no distinguir** entre frases de mediana 26, 32 y 43. **No le pidas que escuche
variantes de longitud de frase.**

## ✅ Criterio de aceptación **[v3 — reescrito entero; el de la v2 pasaba por construcción]**

> La v2 pedía *"la ventana baja de 21 palabras >0,5 s tarde a 0"*. **`util = 8,0` cumple eso al 100%
> dejando 6,58 s de voz sin ningún subtítulo en pantalla** (4,84 s seguidos), que es el defecto
> [GATE-02]/[SUBT-01] que este repo ya pagó. Y `util = 13,0` también da 0, con 43 palabras a más de
> 0,5 s **por delante**. El criterio era de un solo lado y no distinguía el mecanismo del atajo.

**Declara SIEMPRE sobre qué fichero mides** (MP3 del TTS o MP4 final; Δ = +0,100 s). Los umbrales de
abajo son sobre el **MP3**, contra `whisper_v004.json` **congelado**.

| # | Comprobación | Umbral | Línea base medida hoy |
|---|---|---|---|
| 1a | ventana 317-373: palabras >0,5 s **tarde** | `= 0` | 21 |
| 1b | ventana 317-373: palabras >0,5 s **pronto** | `= 0` | 0 publicado · **48 con `util=8`** |
| 1c | mediana de la ventana | `−0,25 ≤ m ≤ +0,10` | +0,460 |
| 1d | `\|err\| max` dentro de la ventana | `≤ 0,30`, **o argumenta por qué no se alcanza** | 0,910 (escalar 14,86 → 0,45; por tramos → 0,44) |
| 1e | `eval_sync.peor_tramo` global | `\|mediana\| ≤ 0,35` | +0,510 (MP4: +0,610) |
| 1f | `audit_run.voz_sin_subtitulo` | `≤ 0,44 s` | 0,44 s · **6,58 s con `util=8`** |
| 2 | `anchor_bench`: 0 ventanas que empeoran en **11-ago** | 0 | 0 · **10-ago declarado NO evaluable (sin audio)** |
| 2b | ventanas que **no** entran en la rama | timestamps **idénticos** a los de hoy | — |
| 3 | tercer corpus **congelado como JSON** (`raw_words_v004` + `sents_v004` + `whisper_v004`), crudas alineadas contra el **audio publicado** | control del banco `dif media ≤ 0,05 s` | pendiente |
| 4 | shorts: `short_005` contra `_audio.mp3` (x1.5) | no empeora vs `0,134 / −0,129 / 0,240` | reproducido — **pero INERTE, ver arriba** |
| 4b | el gemelo: forzar la rama con una alineación aplastada sintética **o** declarar explícitamente que no está cubierto | — | 0 shorts ejercen la rama |
| 5 | `titulo_en_curso` fuera del bucle; invariante de palabras intacto (`raise` de `:318`) | 0 violaciones | verificado en 3 corpus × 4 `cada` |
| 5b | persistir `short_00X_story.txt` (prerrequisito de 4b) | existe | no existe hoy |

**Gobierno:** tocar `_ensure_breathing_periods` es **superficie sensible** ("limpieza de texto",
`produccion-loop.md` §B) → exige `/eval` + `output-audit` antes de cerrar, y **este SEED prohíbe correr
`/eval`** (track E tiene el pipeline). **Cola el `/eval` detrás del track E; no lo dejes implícito.**

Entrada factual en `.claude/incident-ledger.md` por cada defecto. **El retro no escribe reglas, solo
`/optimize` promueve.**
