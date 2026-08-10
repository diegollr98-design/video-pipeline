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
