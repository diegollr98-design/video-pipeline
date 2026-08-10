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

## v0.1 — 2026-08-05 — Config de Claude Code importada del resto de repos ✅
**Qué se hizo:** El proyecto tenía un `CLAUDE.md` técnico excelente (359 líneas de decisiones medidas)
pero **cero capa operativa**: sin `rules/`, sin `agents/`, sin `skills/`, con un `settings.json` de 8
líneas sin `deny` (y `.env` con dos API keys legible), sin git y con el ledger vacío. Importado desde
`Resellermaster` (el más maduro), `escoltaeliteapp`, `pumpfun-bot` y `ecxm-ops`, re-anclado a los
episodios REALES de este repo: `settings.json` con deny + hook `compileall` en `PostToolUse`;
`rules/` (decision-making, produccion-loop, change-loop, file-organization, sessions-log);
`agents/` (engineer, bug-hunter, output-audit); `skills/` (`/eval`, `/run`, `/daily-run`);
capa operativa al inicio de `CLAUDE.md`; `git init`.
**Incidentes:** ninguno — sesión de config, no toca código de producto.
**Verificación:** ver el cierre de la sesión. `/eval` **aún no tiene baseline**: la primera corrida
establece la línea base y no puede aprobar ni bloquear nada.
**Pendiente:** (1) correr `/eval` una vez para fijar el baseline — hasta entonces el gate no tiene
dientes. (2) Los dos TODO abiertos de `CLAUDE.md` siguen: validar `target_wpm: 195` (ratio
duración-vídeo/chunk ≈ 1.0) y la producción real de 30 min. (3) `short_story.txt` no recibe las
directrices de competencia.
