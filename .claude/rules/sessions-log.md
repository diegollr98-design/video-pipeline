# Sessions Log — YOUTUBE

Bitácora por hito. **Más reciente arriba.** Mantener ≤ 100 líneas: las entradas viejas se archivan en
`docs/sessions-log-archive.md` (fuera del contexto) vía `/optimize` Paso 5.

**Plantilla de entrada:**
```
## vX.Y — fecha — <título> <✅|🔴>
**Qué se hizo:** ...
**Incidentes:** [id] del ledger, si los hubo
**Verificación:** qué se EJECUTÓ y qué demostró (salida real, no "reportó que OK")
**Pendiente:** ...
```

---

## v0.8 — 2026-08-13 — El alineador repartía sobre la ventana entera de edge-tts 🔶
**Qué se hizo:** `/seed-review` (1 ciego + 3 críticos) sobre `SEED_alineador_ventana_aplastada.md`.
La **causa raíz del SEED quedó CONFIRMADA cuatro veces** (el agente ciego llegó a la misma línea sin
verlo), pero el panel tumbó **3 de sus 5 criterios de aceptación** y la receta del tercer corpus.
Cambios: **[ANCLA-06]** la rama de reparto usa los **tramos de voz medidos** en vez de `s_dur`;
**[PARTIR-01]** `titulo_en_curso` sale del bucle de párrafos; **[BASURA-03]** el índice Markdown del
modelo se narraba (27% del vídeo) y los tres guardias lo daban por limpio; **[INSTR-06]**; tercer
corpus del banco congelado con su audio; `{stem}_story.txt` persistido en shorts.
**Incidentes:** [ANCLA-06] [BASURA-03] [INSTR-06] · cierra [PARTIR-01] y [LOOP-01].
**Verificación:** banco offline sobre **tres** corpus, con el control del instrumento en
0,0027-0,0047 s. Ventana del caso: **22 palabras >0,5 s tarde → 0**, y **0 pronto** (sin
sobrecorrección: `util=8` daba 0 tardías con 6,58 s de pantalla en blanco); p95 global +0,391 →
**+0,119**; 11-ago 2 ventanas rotas → 0; **0 ventanas que EMPEORAN** en los tres. Guarda dura: el fix
toca SOLO las ventanas de la rama (1 de 18 y 2 de 110), las otras **547 y 5261 palabras idénticas bit
a bit**. El camino `span<=0.05`, que ningún corpus con audio ejercía, pasa de **+1,063 s y 13 tardías
a +0,369 y 0**. Gemelo: 6 shorts reproducen su línea base, y con la rama **forzada** mejora
(0,339 → 0,260). [BASURA-03]: 604 → 472 palabras cortando en la última frase real, **0 falsos
positivos** en 5290 y 5334 palabras de historias buenas.
**Lo que esto enseña:** (a) **el criterio de aceptación obvio era de un solo lado y pasaba por
construcción** — un panel que solo hubiera validado el diagnóstico habría dado el visto bueno a un
fix que vacía la pantalla; (b) el mecanismo tenía **dos** componentes (cola de silencio + pausas
internas aplanadas) y el escalar solo cubría uno; (c) **el mapeo afín quedó refutado por medición**
(+7,6 s): el ritmo crudo de una ventana aplastada es basura, conservarlo conserva el error; (d) un
agente reconstruyó un corpus "histórico" **importando el módulo en caliente** con el fix de hoy
aplicado, y escribió esa conclusión falsa dentro del propio instrumento [INSTR-06].
**Pendiente:** **`/eval` + `output-audit` NO se han corrido** (el pipeline estaba ocupado; decisión de
Diego: cerrar con banco offline y dejar el gate en cola) — **el cambio NO está cerrado del todo**. No
hay vídeo nuevo. Dentro de la ventana, `|err| max` queda en **0,443 s** contra el objetivo de 0,30 y
la mediana en +0,119 contra +0,10: no se ha tuneado la constante contra el propio instrumento
([SYNC-01]), se declara. La ventana pasa de 0,00 a **0,39 s** de voz sin subtítulo. El corpus del
10-ago **no es evaluable** para este fix (no se conservó su audio), y `data/evidence/` está
gitignored: el tercer corpus vive solo en disco.

## v0.7 — 2026-08-12 — Revisión del 12-ago: la palanca era la longitud de frase, no las comas ✅
**Qué se hizo:** `/seed-review` (1 ciego + 3 críticos) sobre `SEED_revision_12ago.md`. El panel **refutó
la evidencia principal del SEED**: el "primer veredicto limpio del auditor" se emitió a las 16:43 con un
auditor reescrito a las 17:13 y un guardia de las 17:30 — y el dashboard seguía ofreciendo ese vídeo
para **subir a YouTube**. Cambios: veredictos firmados con la **huella del auditor** [AUDIT-01];
**partidor de frases en código** (`_ensure_breathing_periods`), que es la palanca dominante;
`_ensure_title_at_start` arreglado (mutilaba la 1.ª frase y **borraba frases legítimas**);
auditor cortando por **pausas medidas acústicamente** en vez de por densidad de comas [COMA-04];
`target_wpm` 160 → **187**; `_strip_trailing_metadata` [BASURA-02]; y el cue de fin de frase que se iba
mientras la voz seguía sonando [SUBT-01].
**Incidentes:** [AUDIT-01] [COMA-04] [BASURA-02] [SUBT-01] [LLM-01].
**Verificación:** A/B acústico controlado con edge-tts sobre el guion REAL de 26 min (misma entrada, dos
códigos): frase mediana **48 → 15**, pausas sin ningún signo detrás **86 → 47**, wpm 201,4 → 187,3;
barrido de `cada` en 12/18/25 antes de fijar la constante. `target_wpm` recalibrado sobre el AUDIO y
**después** del partidor (n=2: 187,3 y 188,0). `/eval` completo con shorts: **pausas inventadas 0,0 por
1000**, ratio 0,779 → **0,949**, 6/6 títulos únicos — y marcó `FALLA` en voz sin subtítulo (1,60 s), que
era **efecto de mi propio partidor** y se cerró a **0,00 s** con starts intactos, 0 solapes y fin del
título Δ 0,0000 s.
**Lo que esto enseña:** (a) **dos instrumentos propios mintieron y la calibración los cazó** — el
emparejador por reloj de habla daba 8% de acierto y sus números (103 → 170) eran basura plausible; con
Whisper independiente (98-100%) el diagnóstico cambia: las pausas largas caen TODAS en punto y el
defecto real son respiraciones cortas; (b) **[COMA-03] ya había medido el día anterior** que las comas
eran la palanca débil, y el fix del 12-ago las atacó igualmente: el ledger existía y no se consultó;
(c) el guardia de comas juzgaba el guion **crudo**, que el pipeline reescribe aguas abajo.
**Pendiente:** **no hay vídeo largo nuevo** — todo se midió sintetizando el guion real, no produciendo.
"Cuesta de entender" sigue sin verificarse con el oído de Diego. Disco: 659 MB liberados, **15 GB
libres** (una corrida larga pide ~12). `input/` son 13,8 GB y mover a D: sigue aplazado.

## v0.6 — 2026-08-12 — El vídeo del 11-ago no era un problema de comas: era 3 defectos que nadie medía ✅
**Qué se hizo:** `/seed-review` (1 ciego + 3 críticos) **reordenó el SEED**: refutó que las comas
explicaran wpm y ratio (la voz articula igual; 90% del delta es silencio, y del silencio 63% son
PUNTOS), que el objetivo de 8,5 comas/100 fuera alcanzable (techo real **5,59**) y que el 10-ago
tuviera ratio 1,00 (**0,894**). Y destapó tres defectos que el SEED no nombraba, dos peores que las
comas. Cerrados: **[CIERRE-01]** la historia se quedaba sin final por DOS caminos (el `while` salía sin
pedir el desenlace — 1 de 3 corridas — y `_truncate_to_words` decapitaba el epílogo); **[ANCLA-05]**
ventana con el interior FABRICADO por stable-ts (26 de 29 palabras con duración idéntica + 2 huecos
inventados de los que el cierre retenía 0,80 s cada uno); **[GATE-02]** el auditor era ciego POR
CONSTRUCCIÓN a la cobertura y ahora **corta** la cola de subida; **[TITULO-01]** el eco del título
parafraseado; **[TITULO-02]** título corto para el campo de 100 caracteres de YouTube; miniatura
(`thumbnails.set`), `--max-shorts`, y un guardia de puntuación tras el juicio de Diego.
**Incidentes:** [CIERRE-01] [ANCLA-05] [GATE-02] [GATE-03] [TITULO-01] [TITULO-02] [MAIN-01]
[REVIEW-01] [COMA-03].
**Verificación:** Corrida real de 45 min: **veredicto del auditor sin defectos MEDIBLES, el primero
limpio**. El bug de [CIERRE-01] **se reprodujo a escala** y el `if` lo paró. Voz sin subtítulo
8,3 → **0,76 s**; racha aplastada 28 → **2**; anclaje sobre las DOS producciones con `anchor_bench`:
palabras desincronizadas 204 → 9 y 73 → 0, **0 ventanas empeoran**, fin del título Δ 0,0000 s.
**Lo que esto enseña:** (a) **un mock no ve que el modelo no responda lo que se le pide** — tres
fallos pasaron los tests de los subagentes y solo salieron contra la API real: `max_tokens=200`,
`Another option: "..."` camino del título de YouTube, y un `NameError` que compilaba limpio; (b) el
gate **no es determinista** [GATE-03] y su comparación relativa necesita un A/B controlado; (c) dos de
los tres hallazgos "de bulto" del propio review comparaban contra la **referencia equivocada** (un
umbral de otro formato, un binario de otro commit).
**Pendiente:** `seeds/SEED_revision_12ago.md` — 9 cambios en una sesión, diseñados y auditados por el
mismo, y el **mismo error de clase dos veces el mismo día** (`NameError` fuera de alcance). Diego pidió
revisarlos con seed fresco. Abierto: **longitud de frase** (la palanca dominante según el A/B del repo,
sin tocar: mediana 48-59 palabras contra 13 de la corrida buena), el **salto de 1645 palabras** que
introduce el truncado, el ratio 0,793, y **disco en 7,6 GB** (la corrida larga necesita ~12).

## v0.4 — 2026-08-10 — `/optimize`: 4 clases del ledger promovidas a regla ✅
**Qué se hizo:** Primer `/optimize` desde el 05-ago (9 commits de por medio). Promovidas 4 clases:
**instrumento no calibrado** (SYNC-01+INSTR-01+INSTR-02, n=3) → `produccion-loop.md` §D regla madre;
**régimen de validación equivocado** (ANCLA-01+BASURA-01+WPM-01, n=3) → `produccion-loop.md` §C "el
techo del gate"; **fix no propagado al gemelo** (PATH-02+LOG-02, n=2) → `decision-making.md` §11 con
tabla de pares + grep obligatorio; **guardia existente pero no aplicado** (GUARD-01+BASURA-01) → §17
2.º corolario. `SEED_4_validar_cambios.md` marcada ⛔ SUPERADA (era la v1 que un panel tumbó y seguía
ejecutable). Tablas de barrido movidas a `docs/mediciones-frases.md`; v0.1 archivada.
**Incidentes:** ninguno nuevo — sesión de config.
**Verificación:** [DOC-01] seguía **VIVO en 6 ficheros** (`decision-making`, `change-loop`,
`file-organization`, `produccion-loop`, `engineer`, `daily-run`, `run`) meses después de corregirse en
`CLAUDE.md`: `grep -rn "tope de 50"` → 0 falsos restantes tras el fix. `decision-making.md:7` afirmaba
"no se auto-carga" siendo falso (los 5 rules están en contexto): corregido. Modelo de producción
verificado VIVO contra `GET /api/v1/models` (399 modelos; `nvidia/nemotron-3-ultra-550b-a55b:free`
presente, `google/gemini-2.0-flash-001` ausente). `CLAUDE.md` decía "cadena completa y validada" y
listaba la producción de 30 min como pendiente **cuando ya se había corrido y salido no publicable**.
**Pendiente:** [ANCLA-01] **sigue vivo** en `tts_engine.py:458` — `SEED_sincronismo_produccion.md` es
ahora la seed nº 0 (bloqueante). Contexto auto-cargado: **935 → 1009 líneas** (+74 neto: ~+95 de
reglas nuevas, −21 de compresión). El `/optimize` de hoy **no ahorró tokens, los gastó**: es el precio
de 4 promociones. El próximo debería ser de poda.

## v0.5 — 2026-08-11 — Anclaje cerrado tras 3 versiones, subida a YouTube, y una causa aguas arriba 🔶
**Qué se hizo:** El anclaje pasó por **tres versiones y dos la tumbó la medición**: (1) la del SEED,
refutada aritméticamente; (2) la propia, que arreglaba el vídeo largo y **rompía 3 de 16 shorts**;
(3) la actual, que distingue **ancla corrupta** (outlier aislado) de **deriva del alineador**
(residuos crecientes en ventanas seguidas) y trata la **ventana aplastada** (>330 wpm). Además:
subida a YouTube completa (privado · solo el largo · cola con OK en el dashboard), auditor de
corrida `scripts/audit_run.py`, techo de bitrate, loudness a −14 LUFS, dedup de bloques, guarda de
aperturas en títulos de shorts, y `components.html` deprecado fuera.
**Incidentes:** [DEDUP-01] [ANCLA-02] [ANCLA-03] [ANCLA-04] [COMA-02] [INSTR-04].
**Verificación:** contra transcripción independiente en **las dos** producciones reales — 10-ago:
209 palabras / 60,7 s desincronizadas → **15 / 5,9 s**, p95 1,010 → 0,283; 11-ago: peor ventana
**7,43 → 1,45 s**; solapes 2 → 0 en ambas. `/eval` con shorts: media 0,0723 → **0,043**, máx 0,400 →
0,320, pausas 1 → 0 → **PASA**. Loudness −22,2 → −14,8 LUFS y bitrate 11,4 → 7,8 Mbps, ambos medidos
por ejecución. Dashboard verificado con `AppTest`: 0 excepciones, 8 pestañas.
**Lo que esto enseña:** (a) la **mediana esconde el defecto local** — una zona con mediana −0,110 s
contenía 40 palabras a −7,4 s, y el mismo error se cometió dos veces; (b) un fix puede dar verde en
el vídeo largo y romper el gemelo; (c) cuando Whisper y edge-tts discrepan 5 s, lo decide un
instrumento que no dependa de Whisper (`silencedetect`) — y tenía razón edge-tts.
**Pendiente:** `seeds/SEED_comas_y_cierre.md`. La causa aguas arriba: el modelo entregó una historia
con **10 comas** (0,2/100) frente a 448, y de ahí salen encadenados 101 pausas inventadas, 202 wpm y
ratio 0,79. **`target_wpm` NO es calibrable** (n=3: 160,6 / 177,2 / 202,3). La corrida de validación
a escala quedó SIN hacer, y la subida espera a que Diego cree el `client_secret.json`.

## v0.4 — 2026-08-10 — ANCLA-01 arreglado y medido; dos premisas del SEED refutadas ✅
**Qué se hizo:** `/seed-review` (TIER PANEL: 1 ciego + 3 críticos) sobre `SEED_sincronismo_produccion.md`
tumbó dos cosas del plan: (a) su fix del anclaje estaba **refutado aritméticamente** —el paso 1.ª→2.ª
palabra no predice el error, con inversión de rango (paso 2,11→err 1,07; paso 1,98→err **1,48**)— y
(b) su bloque A partía de una premisa falsa. Además el ciego destapó un defecto que el SEED no
nombraba. Se arregló el anclaje (offset = **mediana de residuos del vecindario** + cierre de
silencios inventados dentro de la ventana + guarda de orden), el dedup de bloques, y se le dio al
gate la métrica que le faltaba.
**Incidentes:** [DEDUP-01] [ANCLA-02] [INSTR-04] del ledger.
**Verificación:** Banco offline sobre la producción real (214 ventanas, contra transcripción
independiente), con **control del instrumento**: reproduce el `.ass` publicado desde las palabras
crudas con 0,005 s de media / 0,010 s de máximo. Anclaje viejo → nuevo: palabras desincronizadas
**204 → 20**, vídeo afectado **60,3 s → 7,2 s**, p95 **1,010 → 0,286 s**, sesgo **+0,005 → −0,040 s**,
solapes **2 → 0**; las dos ventanas de 94 y 95 palabras pasan de **+1,05 s a −0,065 s**. Invariantes
comprobados: fin del título **Δ 0,0000 s** (la intro no se mueve), 5290 palabras conservadas, orden
monótono. `/eval` con shorts (5 peticiones): media **0,0723 → 0,043**, máx **0,400 → 0,320**, sesgo
−0,0669 → −0,0173 (sigue delante), cobertura 94,6% → 98,1%, pausas fuera de puntuación **1 → 0**
→ **PASA**. Medido por primera vez el **gemelo**: `short_009` da media 0,026 s, máx 0,300 s, sesgo
−0,011 s, 0 palabras >0,5 s tarde.
**Lo que esto enseña:** el emparejador `difflib` **global y el local dan resultados idénticos**
(5062 pares, 0,153 s, +0,003 s) y coinciden con las transcripciones frescas en las 6 zonas: [INSTR-02]
acusó al instrumento de un fallo que era ANCLA-01. Comparar un número de producción con el baseline
del fixture de 3 min es comparar dos regímenes. `data/eval/2026-08-10-produccion-real.json` **no
estaba mal** y se conserva intacto.
**Pendiente:** (1) corrida larga de validación — **aplazada por disco** (~7,3 GB con 16 libres; nada
borrado, decisión de Diego). (2) `output-audit` sobre la salida del gate. (3) `target_wpm`: dejar en
160 (seis corridas dan 152-162; el 177 es el outlier contaminado). (4) Variedad de los 50 shorts: es
juicio de Diego (50/50 empiezan por "Mi ‹alguien›"). (5) `short_story.txt` sigue sin directrices.

## v0.3 — 2026-08-10 — Primera producción real de 30 min: destapó un vídeo no publicable 🔴
**Qué se hizo:** Corrida completa a escala real (33,4 min de gameplay → vídeo de 29,85 min + 50
shorts, 53 peticiones, ~2h40). Antes: baseline de `/eval` fijado sobre el fixture de 3 min y
`--keep-temp` añadido porque `cleanup_temp` borraba el `.ass` que el gate mide.
**Incidentes:** [BASURA-01] [ANCLA-01] [INSTR-02] (+ los 6 de v0.2).
**Verificación:** El vídeo resultante **NO es publicable**: (a) basura del modelo narrada y
subtitulada en el minuto 15:38-15:47 (`temp/video_001_subs.ass:2756` → `ONEAN`, `0230`, `0207-`);
(b) 4 ventanas de anclaje con frases enteras ~1 s por detrás de la voz, confirmado con
transcripciones frescas de 40 s (1000-1040 s: **+1,050 s**, 90 de 125 palabras >0,5 s; control
300-340 s: **−0,110 s**). Causa raíz localizada por `bug-hunter` y validada por ejecución:
`tts_engine.py:458` traslada la ventana entera usando UNA sola palabra. (a) arreglado con
`_detectar_basura` (0 falsos positivos sobre ~12.700 palabras de español real); (b) **fix
propuesto, NO aplicado**.
**Lo que esto enseña:** `/eval` sobre 3 min (12 ventanas de anclaje) dio verde a este vídeo. La
producción real tiene 214 ventanas. **El gate no puede ver esta clase de fallo.**
**Pendiente:** `seeds/SEED_sincronismo_produccion.md` — arreglar el emparejado global de
`eval_sync` (dio 3 falsos positivos hoy), aplicar y verificar el fix del anclaje, `target_wpm`
177 (n=2), variedad de los 50 shorts, y decidir qué hacer con un gate que no cubre producción.

## v0.2 — 2026-08-10 — SEED de validación: revisado, reescrito y ejecutado ✅
**Qué se hizo:** El `SEED_validar_cambios.md` pedía barrer 6 parámetros con 6 agentes en paralelo.
`/seed-review` (TIER PANEL: 1 agente ciego + 3 críticos) lo tumbó: 4 de 6 bloques no tenían
instrumento válido, el paralelismo corrompía las mediciones (`pipeline.log` es ruta fija,
`cleanup_temp` hace `rmtree` del temp compartido) y "no aplicar cambios" era incompatible con
barrer constantes de módulo. Diego validó los hallazgos, dio el OK a la reescritura y añadió dos
enmiendas (separar el knob de wpm; conservar la verificación por fotogramas como gate del bloque A).
SEED reescrito a v2 y ejecutado **en serie**: 4 defectos arreglados, bloque B auditado, medidor del
gate escrito.
**Incidentes:** [PATH-02] [LOG-02] [GUARD-01] [COMA-01] [WPM-01] [DOC-01] [SYNC-01] del ledger.
**Verificación:** concat multi-fichero reproducido ANTES (`FALLO: Error concatenating`) y DESPUÉS
(`OK duration=2.000000`), más integración con 3 trozos de gameplay real → chunk de 152,6 s con
**desvío 0,00 s**. Validador contra 50 títulos reales del log: 3/3 casos de control legítimos
pasaron de rechazados a aceptados, verdaderos positivos siguen cazados. Comas auditadas sobre
7.399 palabras generadas + property test con **0 violaciones del invariante en 1.248
comprobaciones**; TTS real con `silencedetect` calibrado a −35 dB (instrumento no circular):
sin comas 26 silencios/10 signos, con comas 31/22. Cuota verificada con `GET /api/v1/credits`
→ 10 créditos, **1000 peticiones/día** (`CLAUDE.md` decía 50 y estaba desactualizado).
**Pendiente:** (1) baseline de `/eval` — `scripts/eval_sync.py` ya existe, falta la corrida que
fija la línea base. (2) Producción real de 30 min de punta a punta. (3) `short_story.txt` sigue sin
recibir las directrices de competencia. (4) Bloques A/E/F declarados NO medibles con el
instrumental actual (referí circular, proxy que no discrimina, supervivencia de la muestra):
lo accionable es que el próximo escaneo persista el corpus `fresh`.

<!-- entradas anteriores archivadas en docs/sessions-log-archive.md (v0.1) -->
