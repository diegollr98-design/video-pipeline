# SEED — Densidad de comas, residuo del anclaje, y cierre del pipeline

> PASO 0 OBLIGATORIO: invoca /seed-review sobre este SEED antes de tocar nada.

## Por qué existe

El 11-ago-2026 se arregló el anclaje de subtítulos (tres versiones, dos tumbadas por medición) y
se construyó la subida a YouTube. Al medir la corrida de ese día apareció una causa **aguas arriba**
que no estaba en ningún plan: el modelo entregó una historia **sin comas**, y de ahí salían
encadenados tres síntomas que parecían problemas distintos.

Esta sesión se corta a propósito: el contexto se había hecho muy largo y tres hipótesis del que la
escribió fueron refutadas por la medición. Todo lo de abajo está **verificado por ejecución**; lo que
no lo esté, lo dice.

---

## ESTADO EXACTO DEL REPO (verificado al escribir esto)

| Cosa | Estado |
|---|---|
| `input/` | `2026-01-27 21-29-26.mp4`, 13,8 GB, 33,6 min. **Intacto** |
| `temp/chunk_*.mp4` | **El chunk de 33,4 min está conservado** (3,7 GB): relanzar NO exige re-ingerir los 13,8 GB (ahorra ~23 min). Devuélvelo a `pool/` con `mv` |
| `output/` | `video_001_final.mp4` de la corrida del 11-ago. **Defectuoso conocido** (ver abajo), no publicar |
| `shorts_tiktok/` | 14 shorts de esa corrida abortada. Basura conocida |
| `data/evidence/` | Los datos que hacen reproducible todo esto **sin regenerar nada**: alineación cruda, `SentenceBoundary` y transcripción independiente de **las dos** producciones (10 y 11 de agosto), sus guiones y sus `.ass`, y los 50 títulos de shorts |
| Disco | **23 GB libres**. Una corrida completa pesa ahora ~4-5 GB (antes 7,3: se le puso techo de bitrate) |
| Cuota OpenRouter | 10 créditos → **1000 peticiones/día**. Verifícalo con `GET /api/v1/credits`, nunca con `/api/v1/key`. Una corrida son ~55-61 |
| Cuota YouTube | 10.000 unidades/día, **compartidas** entre competencia y subida (`videos.insert` = 1600) |
| git | 7 commits nuevos, **ninguno pusheado**. `assets/.tint_index` y `docs/video_guion.md` están modificados de antes y no son de este trabajo |

---

## BLOQUE 1 — Densidad de comas (0 peticiones para diseñarlo; es LO PRINCIPAL)

**Una sola causa explica tres síntomas** que la auditoría del 11-ago reportó como independientes:

| | 10-ago | 11-ago |
|---|---|---|
| comas que entregó el modelo | 448 (8,5 por 100 palabras) | **10 (0,2)** |
| tras `_ensure_breathing_commas` | 473 (8,9) | **146 (2,7)** |
| frase mediana | 13 palabras | **42 palabras** |
| pausas fuera de puntuación | 33 (1,1/min) | **101 (3,9/min)**, mediana 0,44 s |
| velocidad de la voz | 177 wpm | **202 wpm** |
| ratio vídeo/chunk | 1,00 | **0,79** (7 min de gameplay sin usar) |

`_ensure_breathing_commas` inserta **solo delante de conectores**, y con frases de 42 palabras eso da
un tercio de la densidad natural. Sin respiraderos, edge-tts **se inventa dónde respirar** (0,44 s es
exactamente su pausa típica), la narración corre más y el vídeo sale corto.

**Corolario que cierra una pregunta vieja:** `target_wpm` **no es calibrable**. La velocidad la fija la
densidad de comas, no una constante — medido n=3 en régimen largo: 160,6 / 177,2 / 202,3 wpm. No
vuelvas a tocar ese knob para cuadrar el ratio.

**Qué hacer:** que `_ensure_breathing_commas` apunte a una **densidad objetivo** (referencia medida:
~8-9 comas por 100 palabras, que es lo que produce el modelo cuando escribe bien), no solo a los
conectores. Ojo: el grupo de conectores fue auditado en agosto y se recortó a propósito porque el
grupo ambiguo metía comas **gramaticalmente incorrectas** (partía locuciones, separaba verbo y
complemento, convertía relativas especificativas en explicativas). Ampliar por ahí ya falló una vez.

**INVARIANTE DURO:** no puede cambiar el número de palabras (las comas se pegan a la palabra
anterior). `main.py` cuenta palabras para saber cuándo acaba el título y arrancar la intro. Hay
precedente de property test con 1.248 comprobaciones; repítelo.

**Cómo verificarlo (sin gastar cuota):** las dos historias reales están en `data/evidence/`. Mide
densidad antes/después, y luego **TTS real + `silencedetect -35dB`** para contar pausas que caen
fuera de puntuación. No uses `nº silencios − nº signos` como métrica: mete la variable manipulada en
el denominador y ya dio un número falso una vez.

---

## BLOQUE 2 — El residuo del anclaje (probablemente se cure solo con el bloque 1)

El anclaje está arreglado y medido contra transcripción independiente en **las dos** producciones:

| | anclaje viejo | anclaje nuevo |
|---|---|---|
| 10-ago (214 ventanas) | 209 palabras / 60,7 s · p95 1,010 · peor 1,48 · 2 solapes | **15 / 5,9 s · p95 0,283 · peor 0,76 · 0 solapes** |
| 11-ago (110 ventanas) | 73 / 14,3 s · p95 0,347 · peor **7,43** · 2 solapes | **29 / 8,3 s · p95 0,286 · peor 1,45 · 0 solapes** |

Reproducible con `python scripts/anchor_bench.py bench` (tiene **control del instrumento**: reproduce
el `.ass` publicado desde las palabras crudas con 0,005 s de media; si eso no sale ~0, el banco no
está midiendo la corrida real).

**Lo que queda:** 1 ventana el 11-ago (29 palabras, +1,45 s) y 3 el 10-ago (15 palabras, peor 0,76).
Todas del caso *"Whisper ESTIRA la ventana"* (span mayor que la frase, wpm implícito 106-143).

⚠️ **NO repitas esto:** reescalar la ventana cuando ocupa más de lo que se tarda en decirla **empeora**
con todos los umbrales barridos — el 10-ago pasa de 3 a **6, 14 y 23** ventanas malas con 1.5, 1.25 y
1.15. Está medido y descartado.

**Hipótesis razonable, NO verificada:** las ventanas estiradas son frases largas sin puntuación
interna, así que el bloque 1 podría reducirlas en origen. Compruébalo **después** del bloque 1, no
antes.

---

## BLOQUE 3 — Relanzar y auditar (2h30, ~55-61 peticiones, ~4-5 GB)

Con el bloque 1 cerrado. `mv temp/chunk_*.mp4 pool/pool_0001.mp4` y
`python main.py --skip-ingest --keep-temp` (el `--skip-ingest` ahorra los 23 min de ingesta).

Luego `python scripts/audit_run.py --chunk-dur 2004 --shorts 3`, que mide de una vez sincronismo
**por tramos**, basura del modelo, párrafos repetidos, aperturas de títulos, loudness, ratio,
geometría y artefactos. Corre la auditoría **antes** de mirar el vídeo: para eso existe.

⚠️ **Mide siempre algún short.** El 11-ago un fix daba verde en el vídeo largo mientras rompía 3 de
16 shorts. El gemelo es el que nadie mira.

---

## BLOQUE 4 — Lo que queda para dar el pipeline por CERRADO

| # | Qué | Estado real (verificado en código) |
|---|---|---|
| 1 | **Subida a YouTube** | **HECHA** (`modules/youtube_uploader.py` + pestaña 📤 Subir). Privado · solo el vídeo largo · cola con el OK de Diego. **Bloqueada por una acción suya**: crear el `client_secret.json` en Google Cloud Console y ponerlo en `data/`. El dashboard lleva las instrucciones dentro |
| 2 | Directrices de competencia en shorts | `trend_advisor.py:423` solo inyecta en `reddit_story.txt`. Los ~50 shorts ignoran el análisis. ⚠️ **Los prompts se releen EN CALIENTE** (`shorts_generator.py:105`, `script_generator.py:356`): no los edites con una corrida en marcha |
| 3 | Escaneo de competencia programado | Hoy solo manual |
| 4 | Miniatura ilegible en móvil | Medido por un agente, **no verificado a mano**: título de 34 palabras → 5,8 px de altura de letra en el thumbnail móvil |
| 5 | Saturación de la intro de shorts | **Decisión de Diego, no defecto.** Medido: el gameplay tiene SATAVG 10,4 y la intro sale a 99-115 (con `saturation=1.4` quedaría en ~75). La especificación pide "tinte vibrante", así que no se tocó |

Ya no hacen falta: techo de bitrate (14,0 → 7,9 Mbps), loudness (−23,4 → −14,8 LUFS, **entra en la
próxima corrida, aún sin validar a escala**), `components.html` deprecado, dedup de bloques.

---

## REGLAS DE ESTA SESIÓN

- **En serie.** `pipeline.log` es ruta fija, `cleanup_temp` hace `rmtree` del temp compartido y
  `assets/.tint_index` es read-modify-write sin lock.
- **`--keep-temp` obligatorio** en cualquier corrida que vayas a medir.
- **Prohibido `python main.py` sin `--skip-ingest`** si el chunk sigue en `temp/`: re-ingerir son 23 min.
- **Intocables:** `input/`, `test_e2e/clip.mp4`, `data/evidence/`. Nada está en git y un borrado es
  permanente. **Nunca sobrescribas un JSON de `data/eval/`**: escribe `-v2`, `-postfix`…
- `git commit -m "pre-fix ..."` antes de editar, y **nunca `git add -A`** (en una sesión anterior se
  coló `PORTAFOLIO/*.html`). Añade por ruta explícita.
- **Verificación por EJECUCIÓN.** Pega la salida real.

## TRAMPAS DE MEDICIÓN YA PAGADAS (no las repitas)

1. **La mediana esconde el defecto local.** Una zona de 40 s con mediana −0,110 s parecía sana y
   contenía 40 palabras a −7,4 s. Mira siempre el **peor tramo** y el min/max, no solo la mediana.
   El mismo error se cometió dos veces el 11-ago.
2. **Un fix puede arreglar el vídeo largo y romper los shorts.** Pasó: 3 de 16.
3. **Contrasta con un instrumento que no dependa de Whisper.** `silencedetect` sobre el audio decidió
   quién mentía cuando Whisper y edge-tts discrepaban 5 s: tenía razón edge-tts.
4. `exceso = nº silencios − nº signos` mete la variable manipulada en el denominador.
5. Hueco entre subtítulos como `siguiente.start − previa.start` es la DURACIÓN de la palabra.
6. **Comparar producción con el baseline del fixture de 3 min** y culpar al instrumento: los dos
   regímenes no se comparan. Ya llevó a acusar a `eval_sync.py` de un fallo que no tenía.
7. Fixture con texto repetido = medición falsa · `--no-shorts` oculta una clase entera de fallos ·
   `--dry-run` valida la historia, no la cadena.

## ENTREGABLE

Por bloque: qué se cambió, la **salida real** del antes/después, y qué quedó sin resolver. Entrada
factual en `.claude/incident-ledger.md` por cada defecto nuevo — **el retro no escribe reglas, solo
`/optimize` promueve**. Y el gasto de peticiones por vídeo recalculado si tocaste algo que lo mueva.

"No concluyente" es una respuesta válida y preferible a inventar una recomendación.
