# SEED v2 — Cierre del producto: final de historia, subtítulos rotos, miniatura, y prosodia

> PASO 0 OBLIGATORIO: invoca /seed-review sobre este SEED antes de tocar nada.
> **/seed-review YA CORRIDO (11-ago-2026, TIER PANEL: 1 agente ciego + 3 críticos).** Veredicto:
> ✏️ **CON EDICIONES**, aplicadas en esta v2. Lo que cambió respecto a la v1 está en §QUÉ TUMBÓ EL
> PANEL. Si vuelves a ejecutar esto desde cero, el review ya está hecho: no lo repitas, léelo.

## Por qué existe

El 11-ago-2026 se arregló el anclaje de subtítulos y se construyó la subida a YouTube. La corrida de
ese día produjo un vídeo **no publicable**. La v1 de este SEED atribuyó eso a la densidad de comas.
**El panel lo refutó**: las comas son un defecto real pero de tercer orden. El vídeo del 11-ago es no
publicable por razones más gruesas que ninguna métrica de sincronismo estaba mirando.

Todo lo de abajo está **verificado por ejecución**; lo que no lo esté, lo dice.

---

## QUÉ TUMBÓ EL PANEL (lee esto antes de fiarte de cualquier número de la v1)

| Afirmación de la v1 | Estado | Evidencia |
|---|---|---|
| "Una sola causa (comas) explica pausas + wpm + ratio" | **REFUTADA en 2 de 3** | La articulación de la voz es la MISMA en las dos corridas (236→242 wpm por tiempo de fonación; por ventanas incluso al revés, 227 vs 208). De los 208 s de diferencia, **187 s (90%) son silencio, no velocidad**. Y del silencio perdido, **63% son PUNTOS (1,29 s c/u) y 38% comas (0,25 s c/u)**: un punto vale 5,9 comas. El inserter solo puede poner comas → ataca el término menor |
| "Densidad objetivo ~8-9 comas/100" | **IMPOSIBLE con ese mecanismo** | Techo medido del inserter con umbrales a **1**: `298 comas = 5,59/100`. Harían falta **453**. Solo hay **397 conectores** en todo el texto (309 son `y`, casi todos rechazados por `coordina_sintagma`). El objetivo no es difícil: no cabe |
| "ratio vídeo/chunk 1,00 el 10-ago" | **FALSA** | 1790,9 s / 2004 s = **0,894**, que el propio `audit_run.py:135` ya marca como AVISO. El delta real es 0,894→0,789, no 1,00→0,79: la v1 **duplicaba** el efecto atribuido a las comas |
| "las comas cuadran el ratio" | **REFUTADA** | Contrafactual con el coeficiente medido (+0,248 s/coma): 453 comas compran **+76 s** → ratio 0,83. Para 0,90 harían falta 897 comas más (una cada 5 palabras) o 172 frases más. Ningún caso observado tuvo ratio 1,00 |
| "el residuo del anclaje es 1 ventana, +1,45 s" | **INFRAVALORADO 10x** | Son **19,4 s de vídeo estructuralmente roto** en t=131,9-151,3 (ver BLOQUE 2). "+1,45 s" es la mediana comprimiendo un defecto de forma en un escalar de magnitud — la trampa nº1 de este mismo documento, aplicada a su propia métrica |
| "las comas curarían las ventanas estiradas" (bloque 2) | **REFUTADA, gratis** | De las 5 ventanas estiradas del 10-ago (8,9 comas/100), **3 YA TENÍAN comas internas**. Las comas no las previenen. No hacía falta la corrida para saberlo |
| "`shorts_tiktok/` = basura conocida", "`output/` = defectuoso conocido" | **CERRÓ LA CARPETA ANTES DE MIRARLA** | Ahí dentro había 4 defectos que la v1 no nombra, tres de ellos peores que las comas |

**Lo que SÍ aguantó el ataque, comprobado:** todas las cifras crudas de la v1 (448/8,47 · 10/0,19 ·
146/2,74 · frase mediana 13 vs 42 · 101 vs 33 pausas · 177/202 wpm · ratio 0,789) son **exactas**. El
síntoma de pausas fuera de puntuación **sobrevive a la normalización** (0,72% → 2,00% de sitios no
puntuados con pausa, **2,8x peor**), contrastado con `silencedetect -35dB` real sobre el audio
(333 silencios/216,9 s vs 325/238,2 s derivados del `.ass`: concuerdan al 2,5%). `target_wpm` **no es
calibrable**, y por una razón mejor que la que daba la v1. El aviso de no reescalar ventanas estiradas
(3 → 6/14/23 con los tres umbrales) está bien fundado. Y la advertencia sobre `_CONECTORES_LARGOS`
es el aviso más valioso del documento.

---

## CORRECCIONES AL PROPIO REVIEW (el autor del SEED v1 revisó el veredicto y cazó dos fallos míos)

El review también se equivoca. Estas tres están **verificadas por ejecución** y son vinculantes:

1. **El techo de bitrate SÍ llegó a los shorts.** `shorts_generator.py:294` → `-maxrate 12M`,
   deliberado: 1080x1920@60 y esa es la recomendación de YouTube. El `8M` es del largo, que es **720p**.
   Medido: 11,59 / 12,01 Mbps = en su techo (antes 23,6). **Comparé contra el umbral del formato
   equivocado. NO lo bajes a 8M.** El BLOQUE 5-[F] queda retirado.
2. **El vídeo que medí es anterior al último fix.** `output/video_001_final.mp4` mtime **12:47:49**,
   commit `13aec78`; ANCLA-04 (ventana aplastada) entró en `a7766ac` a las **13:29**. Sobre los mismos
   datos crudos con el código de hoy, el tramo baja a 29 palabras / 8,3 s. **Re-mide antes de diseñar
   el fix del BLOQUE 2.** El hallazgo de fondo (8,5 s de voz sin subtítulo, invisible al auditor por
   construcción) **sigue en pie** y es lo valioso.
3. **La miniatura: confirmado, falta y es del autor del uploader.** `thumbnails.set`, 50 unidades.

**Lección para esta sesión:** dos de mis tres hallazgos "de bulto" comparaban contra la referencia
equivocada — un umbral de otro formato y un binario de otro commit. **Antes de llamar defecto a una
medición sobre un artefacto viejo, comprueba con qué commit se produjo** (`git log --format='%h %ad' --date=format:'%H:%M'`
contra el `mtime` del fichero). Es barato y aquí habría ahorrado dos falsos positivos.

---

## ESTADO EXACTO DEL REPO (verificado)

| Cosa | Estado |
|---|---|
| `input/` | `2026-01-27 21-29-26.mp4`, 13,8 GB, 33,6 min. **Intacto** |
| `temp/chunk_1786444528.mp4` | 3,7 GB, 2004,4 s, 1280x720@60. **Conservado**: relanzar NO exige re-ingerir (ahorra ~23 min) |
| `temp/video_001_audio.mp3` | ✅ **YA PRESERVADO** en `data/evidence/audio_11ago.mp3` (11-ago). Único espécimen grabado de una narración a 0,2 comas/100. También se preservaron los 50 `.srt` de shorts en `data/evidence/srt_11ago/`, que son el corpus que demuestra [TITULO-01] |
| `output/video_001_final.mp4` | 1582,0 s, 1280x720, 7,87 Mbps. **No publicable** (BLOQUES 1, 2). El 720p **no es defecto**: es la resolución del `input/` |
| `shorts_tiktok/` | **VACIADO el 11-ago** con el OK de Diego (eran 14 shorts de la corrida abortada). Su bitrate estaba **en su techo y correcto** (ver §CORRECCIONES) |
| `data/evidence/` | Alineación cruda, `SentenceBoundary`, transcripción independiente de las dos producciones, guiones, `.ass`, 50 títulos de shorts. **Intocable** |
| Disco | **27 GB libres** tras la limpieza del 11-ago (llegó a 7,5 GB y no cabía la corrida larga). ⚠️ El pico real de una corrida sigue siendo **~12 GB**, no 4-5: `take_chunk` **copia** el chunk a `temp/` antes de borrar el del pool (+7,4 GB transitorios) |
| Cuota OpenRouter | Verifícala con `GET /api/v1/credits`, **nunca** con `/api/v1/key`. Una corrida completa son ~55-61 peticiones, de las cuales **~50 son los shorts** |
| Cuota YouTube | 10.000/día, compartidas entre competencia y subida (`videos.insert` = 1600) |
| git | 7 commits nuevos, ninguno pusheado. `assets/.tint_index` y `docs/video_guion.md` modificados de antes, no son de este trabajo |

---

## BLOQUE 1 — La historia se quedó SIN FINAL [CIERRE-01] · **ES EL DEFECTO DOMINANTE**

26,4 minutos de historia de venganza cuyo pago —lo que el espectador viene a ver— **no llega**.
`data/evidence/video_001_story_11ago.txt` termina literalmente:

> *"…y pienso que este es el momento en el que todo se juega y que no hay vuelta atrás y que mi padre
> me está esperando arriba en la habitación dos catorce y que yo voy a entrar y nada ni nadie me va a
> detener."*

Sin sentencia, sin confrontación, sin consecuencia. (El 10-ago **sí** cierra: sentencia firme, 387.000 €,
el padre pidiendo perdón.)

**Causa raíz, en el código, no en una hipótesis** — `modules/script_generator.py:537-539`:

```python
while word_count < target_words * 0.85 and block <= max_attempts:
    words_remaining = target_words - word_count
    is_final = (words_remaining <= WORDS_PER_BLOCK * 1.3) or (block >= max_attempts)
```

Bloque 1 = 1768 palabras → `words_remaining` = 3577 > 2600 → se pide **"continuación"**. Ese bloque
devuelve 3566 palabras de golpe, `word_count` cruza el 85% y **el `while` sale**. Nunca se pide el
bloque final. Confirmado en `pipeline.log:5330-5336`.

**Frecuencia medida sobre las 3 corridas largas del log: 1 de 3 falla.** Depende solo de cuánto escriba
el modelo en el bloque 1 — es una lotería en cada corrida.

**Es §17 en estado puro**: aquí ni siquiera hay prosa que prometa el cierre; no hay ningún `if` que lo
fuerce. **Qué hacer:** no salir del bucle sin un bloque marcado `is_final`, y añadir a `_validar_salida`
una comprobación de cierre narrativo. `scripts/audit_run.py` **no lo detecta** (no mide cierre) → hay
que instrumentarlo (BLOQUE 6). Coste: minutos, 0-1 peticiones extra por vídeo.

---

## BLOQUE 2 — Subtítulos rotos en t=131-151 [ANCLA-05]

> ⚠️ **MIDE OTRA VEZ CON EL CÓDIGO DE HOY ANTES DE DISEÑAR EL FIX.** El MP4 que se midió se compuso a
> las **12:47:49** con `13aec78`; el tratamiento de la **ventana aplastada** (ANCLA-04) entró en
> `a7766ac` a las **13:29**, 42 min después. Sobre los mismos datos crudos y con el código actual, ese
> tramo baja a **29 palabras / 8,3 s**. Parte del defecto de abajo ya está arreglado: perseguirlo entero
> es perseguir un fantasma. **Lo que hay que hacer primero es reproducir la zona con el código de hoy.**
>
> **Lo que SÍ sobrevive intacto y es el hallazgo de fondo:** los **8,5 s con voz sonando y ningún
> subtítulo** son **invisibles para `eval_sync` por construcción** — un subtítulo ausente no genera par
> de error, así que no puede aparecer nunca como desfase, con ningún umbral. **Eso es un agujero del
> auditor, no un matiz** (→ BLOQUE 6).

Dos agentes independientes lo encontraron en la misma zona, con instrumentos distintos. Medido sobre
el `.ass` **quemado en el MP4 pre-ANCLA-04** (md5 verificado idéntico a `data/evidence/video_001_subs_11ago.ass`):

```
t=131,89-136,48  (4,59s, 22 palabras)  err medio +1,374 s  'DÍAS LIMPIABA COCINABA LE LLEVABA LA COMPRA'
t=139,22-140,62  28 palabras en 1,40 s  = 1200 wpm en pantalla (estroboscopio ilegible)
t=142,80-151,31  8,51 s SIN NINGÚN SUBTÍTULO, de los cuales 6,65 s son voz sonando
                 (contrastado con silencedetect -35dB sobre el audio real, no con Whisper)
```

Las 28 palabras tienen duración **exactamente 0,050 s** = `paso_min` en `tts_engine.py:451`.

**Mecanismo, medido paso a paso:**
1. La alineación cruda de stable-ts colapsa en **una** ventana (t=128,6, 29 palabras, error mediano
   **9,89 s**). Deja un relleno uniforme de 34 palabras × 0,200 s y un salto atrás de −6,800 s
   (`raw_11ago.json` idx=464). *No verificado*: si el relleno lo produce stable-ts o
   `_fix_alignment_gaps` (`tts_engine.py:302`) — la aritmética de esa función no cuadra, así que se
   **infiere** stable-ts. Requiere re-ejecutar la alineación para cerrarlo.
2. `_validate_and_fix_alignment` ancla bien el *arranque* (err −0,06 s) pero hereda el desorden. Sus
   dos guardias no lo ven: `ANCLA_WPM_MAX=330` mide **ritmo** (ese tramo da 143-259 wpm) y el de ancla
   corrupta disparó en otro sitio. **El log canta "110/110 frases ancladas": creyó que todo iba bien.**
3. `_enforce_monotonic` (`tts_engine.py:441`) resuelve el desorden empujando a `paso_min=0.05` →
   las 28 palabras aplastadas. Y lo registra como `WARNING` que nadie lee.

**Fuera de esta zona el vídeo está bien**: `|err|` mediana 0,080 s, p95 0,340 s. El anclaje del 11-ago
**sí mejoró** — este es un modo de fallo distinto que quedó debajo.

**Qué hacer:**
1. ~~Detector de ventana DESPLAZADA~~ — **HECHO, y mi hipótesis era falsa.** Re-medido con el código de
   hoy: ANCLA-04 ya cierra la ventana aplastada (mediana −3,990 → +0,041 s, la racha de 28 palabras a
   `paso_min` desaparece, el hueco de 5,07 s de voz sin subtítulo se cierra). Lo que quedaba **no** era
   una ventana desplazada: **el ancla acierta a 0,010 s**. Era el **INTERIOR FABRICADO** — stable-ts
   rellenó 26 de 29 palabras con duración idéntica de 0,200 s y metió dos huecos inventados de 2,82 s y
   2,62 s, de los que el cierre de huecos **retiene 0,80 s cada uno** (= 1,60 s de silencio inexistente
   que empuja tarde a las 27 palabras siguientes). Arreglado en `07e4e85` [ANCLA-05]: detector
   *uniformidad ≥50% **Y** ≥1 hueco inventado* (2 de 268 ventanas, 0 falsos positivos), enrutado a la
   rama de reparto que ya existía. Medido: 11-ago **+1,450 → +0,129 s**, 10-ago **+0,507 → −0,068 s**,
   **0 ventanas empeoran**, invariantes intactos (fin del título Δ 0,0000 s).
2. **`_enforce_monotonic` con dientes (§12).** Hoy aplasta 41 palabras y escribe un warning. Debe
   marcar la salida: racha de ≥4 palabras en el suelo → o se rechaza, o se omiten esas palabras
   (pantalla limpia > parpadeo a 1200 wpm).
3. **Verificable OFFLINE, coste 0**: reprocesar `raw_11ago.json` + `sents_11ago.json` contra
   `whisper_v001_11ago.json` y exigir que las 2 regiones desincronizadas bajen a 0 **sin tocar las 107
   ventanas sanas**.
4. **También pasa en los shorts**: `short_002` (40 palabras ≤0,08 s) y `short_008` (**15 palabras
   seguidas a 0,05 s** y un blanco de 3,72 s en un short de 33,7 s = 11%).

⚠️ **NO reescales la ventana cuando ocupa más de lo que se tarda en decirla**: barrido con 1.5/1.25/1.15
→ el 10-ago pasa de 3 a **6, 14 y 23** ventanas malas. Medido y descartado.

---

## BLOQUE 3 — La subida NO está hecha: no sube la miniatura y el título pierde el gancho [SUBE-02]

La v1 daba la subida por **HECHA**. Verificado: `grep -rn "thumbnails" modules/` → **cero llamadas a
`thumbnails.set`**. `youtube_uploader.py:149,158` solo expone la ruta del `.jpg` para que el dashboard
la pinte, y `dashboard.py:516,560` la ofrece como **descarga manual**.

**Consecuencia: YouTube elige un fotograma al azar de Minecraft borroso como portada.** Todo
`thumbnail_generator.py` se tira a la basura en el último metro, y la miniatura es la palanca nº1 del
objetivo upstream.

Segundo: `youtube_uploader.py:235-242` recorta el título a 100 caracteres (correcto, el límite es real).
Pero el título del 11-ago son **172 caracteres**, así que lo que se publicaría es:

> `Mi Hermano Mayor Robó La Herencia De Mi Padre Falsificando El Testamento Ante La Notaría Pero No...`

**El gancho entero se pierde.** La estrategia de "títulos de 20-35 palabras" (que viene del análisis de
competencia) es estructuralmente incompatible con el campo de 100 caracteres de YouTube, y **nadie lo
decidió: se descubre por truncado**. Decisión de Diego: o título corto para YouTube + título largo solo
para la miniatura/intro, o asumir el truncado.

**Confirmado por el autor del uploader: falta y es suyo.** La llamada es `thumbnails.set`, cuesta **50
unidades** de las 10.000/día — nada. No hay decisión que tomar aquí, solo implementarla.

### DECISIÓN TOMADA (Diego, 11-ago): título corto para YouTube, frase larga para narrar

El límite de 100 caracteres es de YouTube y **no se negocia**; recortar pierde el gancho. Solución:
**generar un título corto de verdad para el campo de YouTube (10-14 palabras, que lleve el gancho)** y
que la **frase larga siga siendo la que se narra y la que va en la intro y la miniatura**. Son dos
campos distintos, no uno truncado. Cambio de diseño pequeño; toca `script_generator` (un campo más),
`*_title.txt` y el uploader.

**Bloqueantes que siguen siendo de Diego** (verificados): `data/client_secret.json` no existe, y
`googleapiclient`/`google_auth_oauthlib` **no están instalados ni en `requirements.txt`**.

---

## BLOQUE 4 — Prosodia: la densidad de PAUSAS (no de comas) [COMA-03]

Reencuadrado tras el panel. El síntoma es real y sobrevive a la normalización:

```
10-ago: 33 pausas fuera de puntuación / 4572 sitios no puntuados = 0,72%
11-ago: 101 / 5052 = 2,00%   (2,8x peor)
```

Pero **lo que este bloque puede comprar está acotado por aritmética**, y hay que declararlo antes de
medir para no narrar cualquier resultado como éxito:

- **Cierra**: pausas inventadas (respiración en sitio equivocado).
- **NO cierra el ratio.** 453 comas compran **+76 s** → 0,79 → 0,83. El umbral 0,90 de `audit_run.py`
  sigue fallando. **Son dos problemas, no uno.**
- **NO cierra el wpm.** La voz articula igual; lo que cambia es cuánto calla.

**Palanca correcta, por orden de rendimiento:**
1. **Guardia en `_validar_salida`** (`script_generator.py:142`, que hoy no mira ni comas ni longitud de
   frase): rechazar y reintentar por debajo de un suelo de puntuación. Habría **rechazado** el bloque
   del 11-ago (0,19/100) y **aceptado** el del 10-ago (8,47/100). Es la doctrina §17, cuesta ~1
   petición, y no toca la gramática. **Es la mejor relación valor/coste del bloque.**
2. **Insertar PUNTOS en frontera de cláusula, no solo comas**: 1,295 s frente a 0,220 s por inserción
   (**5,9x**), ataca el término del 63%, y respeta igual el invariante (el signo se pega a la palabra
   anterior). No probado — es la propuesta con más recorrido y más riesgo gramatical.
3. **Bajar `PALABRAS_RESPIRO`/`PALABRAS_LIMITE`**: barato pero de techo bajo (146→298 comas máximo) y
   arriesga comas incorrectas. Red secundaria, no el arreglo.

⚠️ **El grupo de conectores fue recortado a propósito** porque el grupo ambiguo metía comas
gramaticalmente incorrectas (partía locuciones, separaba verbo y complemento, convertía relativas
especificativas en explicativas). **Ampliar por ahí ya falló una vez.**

### El ratio, aparte: es un ORDEN DE OPERACIONES, no un defecto de la voz

`main.py:387-388` hace `os.remove(chunk_path)` sobre el chunk **entero**: los 422 s no usados **se
destruyen**, no vuelven a `pool/`. `take_chunk` ya sabe devolver sobrante (`gameplay_pool.py:206-209`).
**~10 líneas y el síntoma vale 0, con independencia del wpm.** Es la palanca determinista que la v1 no
nombraba.

### Criterio de éxito PRE-REGISTRADO (declararlo antes de medir, no después)

| | Métrica | Instrumento | Éxito |
|---|---|---|---|
| P1 | Silencios fuera de puntuación / 100 sitios no puntuados, **con el clasificador congelado al texto PRE-cambio** | silencedetect calibrado | ≤ 1,00% (hoy 2,00%) |
| P2 | Silencios NUEVOS creados donde antes no pausaba | idem | 0 (guarda anti-entrecortado) |
| P3 | Duración total del audio | ffprobe | +76 s ± 25 (**predicción falsable**) |
| P4 | Comas insertadas gramaticalmente incorrectas | 50 muestras a mano | ≤ 2 |
| P5 | Invariante nº de palabras | property test 1.248 casos | 0 violaciones |
| P6 | `sum(len(s["text"].split()) for s in sentences) == len(aligned_words)` | assert nuevo | exacto |

**Calibración obligatoria del instrumento antes de emitir veredicto** (`silencedetect` es el que produjo
[SYNC-01], el veredicto falso): reproducir el caso conocido de `docs/mediciones-frases.md` §A — frase
de 49 palabras SIN comas → **2** pausas inesperadas; CON comas → **0**. Si no reproduce 2 y 0, el
instrumento no mide. Y barre `n=-30/-35/-40 dB` × `d=0.20/0.25/0.35`: **si el veredicto cambia de
signo, no hay veredicto.**

⚠️ **La métrica premia la coma incorrecta**: clasifica un silencio como "malo" si la palabra previa no
lleva signo, así que una coma mal puesta hace pausar en sitio incorrecto **pero puntuado** → cuenta
como bueno. Hoy es segura (solo el 1% de las 101 pausas va seguida de conector); se vuelve insegura en
proporción exacta a cuánto se afloje la restricción de conectores. **Por eso P4 es a mano y no es
opcional.**

### INVARIANTES — la v1 nombraba uno de dos

1. **Nº de palabras** (`main.py:251-256` indexa `aligned_words[title_word_count-1]["end"]` para saber
   cuándo acaba la intro). Real, protegido con `raise` en `tts_engine.py:233`, y **hoy se cumple**
   (5290=5290, 5334=5334). Verificado por mí: el inserter con umbrales a 1 conserva 5334 palabras.
2. **El que la v1 no nombra, y es peor**: `tts_engine.py:532` reparte palabras en ventanas
   **secuencialmente por conteo** (`len(sent["text"].split())`). El texto lo emite edge-tts, las
   palabras el alineador. **Un descuadre de UNA palabra desplaza todas las ventanas siguientes y
   desincroniza el vídeo entero en silencio.** El property test actual solo verifica el total. Cualquier
   inserción que emita el signo como token suelto, o que meta un `\n` (el troceo de 4096 bytes prioriza
   saltos de línea), lo rompe **sin** disparar el `raise`. → **P6.**

### El gemelo entra por la puerta de atrás

`shorts_generator` → `run_tts` → `_clean_speech_for_tts` → `_ensure_breathing_commas`: **los shorts
reciben el cambio automáticamente**, con dos amplificadores: (a) audio a x1.5, así que una coma de
0,248 s queda en 0,165 s en pantalla; (b) `main.py:85-93` predice la duración del short con
`narration_wpm` **fijo en config** — si la wpm real baja, los `offset` de gameplay se descuadran y los
shorts repiten gameplay. **Verificable con 3 micro-historias A/B por edge-tts, 0 peticiones.**

Colateral en el anclaje, medido: con 8,9 comas/100 (el 10-ago), **6 de 472** huecos tras coma superan
`ANCLA_HUECO_MAX=0.80` y se comprimen como "silencio inventado"; con 2,74 son **0 de 146**. Subir la
densidad proyecta ~6 compresiones nuevas por corrida: es la clase exacta que rompió 3 de 16 shorts
[ANCLA-03]. **Barrer `ANCLA_HUECO_MAX` a la densidad nueva con `anchor_bench`, offline.**

---

## BLOQUE 5 — Los shorts: dos defectos que la v1 tapó con "basura conocida"

**[C] 7 de 48 shorts empiezan narrando un fragmento MUTILADO de su propio título.** Es el primer
segundo del short, que en formato vertical es el producto entero:

| short | lo que se oye tras la frase del título |
|---|---|
| 012 | *"…Vació Mi **Carteras Fría** Y Desapareció Con Mis Bitcoins.* **cartera fría, y desapareció con mis bitcoins.**" |
| 031 | *"…Mientras Yo Estaba En Coma.* **de arquitectura a mi rival mientras yo estaba en coma.**" |
| 004, 019, 026, 029, 036 | mismo patrón |

Mecanismo en `script_generator.py:297-330`: `_ensure_title_at_start` recorta el solape por **prefijo
palabra a palabra**. Si el modelo parafraseó ("Mi padrino **de bautismo** vendió…"), el match rompe en
la 2.ª palabra y queda pegada la cola. **2 de los 14 del 11-ago, 7 de los 48 del corpus.** Arreglo:
emparejado por sufijo/fuzzy, no por prefijo estricto. (`short_012_title.txt` además dice *"Vació Mi
Carteras Fría"*, agramatical.)

**[D] Los 50 títulos son una plantilla rellenada 50 veces, y 39 de ellos cuentan el final.** Medido
sobre `data/evidence/shorts_titulos/` (n=50): **50/50** son "Mi ‹pariente›" semánticamente · **43/50**
siguen `Mi <agresor> <verbo> Mi <objeto>` (vendió 18, robó 7, falsificó 4) · **49/50** llevan
`Y <autoridad> lo castigó` · **39/50 revelan el desenlace**, 16 con el mismo cierre adverbial. El fix
del 11-ago (`shorts_generator.py:84`, `RACHA_MAX_APERTURA=5`) **solo vigila la primera palabra**:
12/14 de los nuevos siguen empezando por "Mi". La anti-repetición de *contenido* **sí funciona** (50/50
únicos, 0 pares con ≥40% de solape). Lo colapsado es el **molde**.
→ Un título que dice *"y la policía lo detuvo inmediatamente"* elimina la razón de ver el short.

**DECISIÓN TOMADA (Diego, 11-ago): NO se toca.** Es el formato del nicho, y la guarda de racha
(`RACHA_MAX_APERTURA=5`) es de ayer. **Se revisa cuando haya 50 títulos NUEVOS que mirar — con datos,
no con impresión.** No rediseñes el molde en esta sesión.

**[F] ~~El techo de bitrate no se propagó al gemelo~~ — RETIRADO, era un falso positivo del review.**
`shorts_generator.py:294` tiene su propio `-maxrate 12M`, deliberado y comentado: los shorts son
**1080x1920@60** y 12M es la recomendación de YouTube para ese formato; el `8M` es del vídeo largo, que
es **720p**. Medido: 11,59 y 12,01 Mbps = **en su techo, funcionando** (antes iban a 23,6). El review
comparó contra el umbral del formato equivocado. **NO lo bajes a 8M.**

---

## BLOQUE 6 — El auditor está CIEGO a casi todo esto, y ni siquiera está cableado

`scripts/audit_run.py` (239 líneas, leído entero) mide sincronismo, pausas, basura, n-gramas repetidos,
ratio, loudness, geometría, títulos únicos y primera palabra. **NO mide**: cierre narrativo [B1],
rachas de palabras a `paso_min` [B2], huecos de subtítulo **con voz debajo** [B2], arranque mutilado de
shorts [B5-C], colapso de plantilla más allá de la 1.ª palabra [B5-D], ni longitud de título contra los
100 caracteres [B3].

> **El agujero estructural, reconocido por el autor del auditor:** `eval_sync` empareja subtítulo con
> transcripción y mide el desfase del par. **Un subtítulo que NO EXISTE no genera par**, así que 8,5 s
> de voz sin texto en pantalla son invisibles **por construcción**, con cualquier umbral. Ninguna
> métrica de desfase puede verlo. La métrica que falta es de **cobertura**, no de desfase: *"¿hay voz
> sonando (silencedetect, no Whisper) sin ningún subtítulo activo?"*. Es la primera que hay que añadir.

Y **no está enganchado**: no aparece en `main.py`, `dashboard_runner.py` ni `dashboard.py`. Es un script
suelto que hay que acordarse de correr — y la corrida del 11-ago murió antes de que nadie lo corriera.
(Comprobado que **habría cazado** lo del BLOQUE 2: simulando su `peor_tramo` sobre el `.ass` real →
`-5,185 s at t=138,6` = FALLA.)

**Sin instrumentar y cablear esto, la corrida del BLOQUE 7 vuelve con "sin defectos MEDIBLES" sobre un
vídeo que puede salir otra vez sin final.** Un gate nuevo es superficie nueva (§16): pásale el conjunto
vacío y el dato ausente antes de fiarte.

---

## BLOQUE 7 — La corrida de validación (SOLO con los bloques 1, 2, 6 cerrados)

⚠️ **No la lances con el reparto de la v1.** Números del reloj real: los 14 shorts costaron 31 min
(2,2 min/short) → los 50 shorts son **~1h50 de las 2h30 y ~50 de las ~55-61 peticiones**: el **73% del
reloj y el 85% de la cuota** se irían en producir 50 shorts cuya plantilla ya sabemos colapsada.

**Preparación obligatoria, antes de tocar nada:**
1. `cp temp/video_001_audio.mp3 data/evidence/audio_11ago.mp3` — evidencia irremplazable, 9,5 MB.
2. Arreglar `scripts/anchor_bench.py:24-31`: el directorio de datos está **hardcodeado al scratchpad de
   otra sesión** y `STORY`/`AUDIO` apuntan a `temp/video_001_*`. Hoy funciona por casualidad; tras la
   corrida nueva compararía **zonas de una corrida contra el audio de otra**. → `ANCHOR_BENCH_DIR=data/evidence`
   y parametrizar.
3. `cp` en vez de `mv` para devolver el chunk al pool (3,7 GB de los 22, pero el original sobrevive a un
   fallo antes de `take_chunk`).
4. Presupuestar **~12 GB de pico sobre 22 libres**, no 4-5.

**Corrida:** `python main.py --skip-ingest --keep-temp` con `shorts.generate_per_video` bajado a **3-5**.
Cumple "mide siempre algún short" (la regla es medir el gemelo, no producir 50), ahorra ~1h40 y ~45
peticiones, y deja los 50 para cuando la plantilla esté arreglada. **Mide el largo en cuanto exista, no
al final**: no hay reanudación, y un fallo en el short 40 obliga a repetir los 3 bloques de historia.

Luego `python scripts/audit_run.py --chunk-dur 2004 --shorts 3` **ya instrumentado** (BLOQUE 6). Corre
la auditoría **antes** de mirar el vídeo: para eso existe.

---

## LO QUE QUEDA DESPUÉS (no bloquea la corrida)

| # | Qué | Estado |
|---|---|---|
| 1 | Directrices de competencia en shorts | `trend_advisor.py:423` solo inyecta en `reddit_story.txt`. ⚠️ Los prompts se releen **EN CALIENTE** (`shorts_generator.py:105`, `script_generator.py:356`): no los edites con una corrida en marcha |
| 2 | Escaneo de competencia programado | Hoy solo manual |
| 3 | Miniatura ilegible en móvil | Medido por un agente, **no verificado a mano**: título de 34 palabras → 5,8 px de altura de letra. Se solapa con el BLOQUE 3 (título de 100 chars) |
| 4 | Saturación de la intro de shorts | **Decisión de Diego, no defecto.** Gameplay SATAVG 10,4, intro 99-115 |
| 5 | Los ~50 shorts siguen subiéndose a mano | La subida cubre 1 de ~51 artefactos por corrida |

**Deriva documental detectada:** `CLAUDE.md` dice que los shorts duran "60-90 s"; los 14 reales miden
**31,6-43,2 s**, que es lo que `config.yaml:156` predice. El `.md` está caducado, no el pipeline.

---

## REGLAS DE ESTA SESIÓN

- **En serie.** `pipeline.log` es ruta fija, `cleanup_temp` hace `rmtree` del temp compartido y
  `assets/.tint_index` es read-modify-write sin lock.
- **`--keep-temp` obligatorio** en cualquier corrida que vayas a medir.
- **Prohibido `python main.py` sin `--skip-ingest`** si el chunk sigue en `temp/`: re-ingerir son 23 min.
- **Intocables:** `input/`, `test_e2e/clip.mp4`, `data/evidence/`. Nada está en git y un borrado es
  permanente. **Nunca sobrescribas un JSON de `data/eval/`**: escribe `-v2`, `-postfix`…
- `git commit -m "pre-fix ..."` antes de editar, y **nunca `git add -A`**. Añade por ruta explícita.
- **Verificación por EJECUCIÓN.** Pega la salida real.

## TRAMPAS DE MEDICIÓN YA PAGADAS (no las repitas)

1. **La mediana esconde el defecto local.** Una zona de 40 s con mediana −0,110 s contenía 40 palabras
   a −7,4 s. **La v1 de este SEED volvió a caer**: describió como "+1,45 s" un tramo con 28 palabras a
   1200 wpm y 8,5 s sin subtítulo. Mira **la forma del defecto**, no solo su magnitud media.
2. **Medir pausas sobre la alineación que estás juzgando es CIRCULAR.** Los huecos de `raw_*.json` en la
   zona rota dan "106 pausas inventadas" que **no existen** en el audio. Usa `silencedetect` sobre el WAV.
3. **Un fix puede arreglar el vídeo largo y romper los shorts.** Pasó: 3 de 16.
4. `exceso = nº silencios − nº signos` mete la variable manipulada en el denominador.
5. **Recuentos crudos cuando el propio cambio mueve el denominador**: los sitios puntuados pasan de 684
   a 253 entre corridas. Normaliza, y **congela el clasificador al texto pre-cambio**.
6. Hueco entre subtítulos como `siguiente.start − previa.start` es la DURACIÓN de la palabra.
7. **Comparar producción con el baseline del fixture de 3 min** y culpar al instrumento.
8. Fixture con texto repetido = medición falsa · `--no-shorts` oculta una clase entera de fallos ·
   `--dry-run` valida la historia, no la cadena.
9. **Etiquetar una carpeta como "basura conocida" es dejar de mirarla.** Cuatro defectos salieron de
   `shorts_tiktok/` y `output/` en 40 minutos, sin gastar una petición.

## ENTREGABLE

Por bloque: qué se cambió, la **salida real** del antes/después, y qué quedó sin resolver. Entrada
factual en `.claude/incident-ledger.md` por cada defecto nuevo — **el retro no escribe reglas, solo
`/optimize` promueve**. Y el gasto de peticiones por vídeo recalculado si tocaste algo que lo mueva.

"No concluyente" es una respuesta válida y preferible a inventar una recomendación.
