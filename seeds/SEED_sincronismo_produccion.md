> ⛔ SUPERADO — no ejecutar.

# SEED v2 — Lo que queda del sincronismo de producción

> PASO 0 OBLIGATORIO: invoca /seed-review sobre este SEED antes de tocar nada.

**v2 (10-ago-2026, sesión de tarde).** La v1 pasó por `/seed-review` (1 agente ciego + 3 críticos) y
**no sobrevivió entera**: su fix del bloque B estaba refutado aritméticamente, el criterio de
aceptación del bloque A usaba el estadístico equivocado, faltaba un defecto que también impide
publicar, y su premisa central sobre el instrumento resultó ser **falsa al medirla**. Lo que sigue es
el estado tras ejecutar la parte de coste cero. Las mediciones de abajo son salidas reales, no
resúmenes.

---

## LO QUE YA ESTÁ HECHO Y MEDIDO (no lo repitas)

### ✅ Anclaje robusto — ANCLA-01 arreglado (`modules/tts_engine.py`)

El diagnóstico de la v1 era correcto pero **incompleto**: hay DOS modos de fallo, no uno, y por eso
su fix propuesto ("si el paso de la 1.ª a la 2.ª palabra supera un umbral, adelanta el resto") no
podía funcionar — el paso no predice el error (paso 2,11 → err 1,07; paso 1,98 → err **1,48**).

- **Modo 1 — ancla corrupta.** Whisper coloca la 1.ª palabra dentro del silencio anterior y
  `offset = s_start - w_first` propaga ese silencio a las ~95 palabras de la ventana.
  *Fix:* el offset es la **mediana de los residuos del vecindario** (±3 ventanas); el residuo propio
  solo se usa si concuerda (`ANCLA_TOL = 0.40`). Cuando se descarta, la 1.ª palabra se clava a mano en
  `s_start`, que sigue siendo exacto.
- **Modo 2 — silencio inventado DENTRO de la ventana.** Ahí el ancla es correcta y lo roto es el ritmo
  interior: `'El silencio que siguió fue absoluto.'` (6 palabras, 2,91 s según edge-tts) salió de
  Whisper con 2,09 s entre la 1.ª y la 2.ª palabra, cuando la voz las dice a 0,36 s.
  *Fix:* se cierra todo hueco interno > `ANCLA_HUECO_MAX = 0.80` y se adelanta el resto.
- **Guarda de orden** (`_enforce_monotonic`): solapes y arranques desordenados. El `.ass` publicado ya
  tenía 2 solapes y 1 palabra desordenada, sin que nada los cortase.

**Umbral elegido por barrido, no por gusto** (214 ventanas reales contra transcripción independiente):
`1.0` → 20 palabras malas / p95 0,289 · `0.8` → 20 / **0,286** · `0.7` → 15 / 0,327 ·
`0.6` → ya adelanta de más dos ventanas largas SANAS (−0,517 s en una de 76 palabras).

**Resultado medido** (`python scripts/anchor_bench.py bench`):

| métrica | anclaje viejo | anclaje nuevo |
|---|---|---|
| palabras desincronizadas | **204** | **20** |
| segundos de vídeo afectados | **60,3 s** | **7,2 s** |
| \|error\| medio | 0,151 s | 0,118 s |
| p95 | 1,010 s | 0,286 s |
| sesgo | +0,005 s (detrás, MAL) | −0,040 s (delante, correcto) |
| peor tramo de 40 palabras | +1,108 s | −0,236 s |
| solapes de subtítulo | 2 | 0 |

Las dos ventanas catastróficas (94 y 95 palabras = 27 s + 26 s de pantalla) pasan de **+1,05 s a
−0,065 s**, que era exactamente el criterio de aceptación que pedía la v1.

### ✅ Párrafo repetido entre bloques — defecto NUEVO que la v1 no nombraba

`temp/video_001_story.txt` tiene **83 palabras repetidas literalmente** (posiciones 2687 y 2792) y 72
n-gramas de 12 duplicados: el vídeo publicado **narra dos veces el mismo párrafo**.
`script_generator.py:492` concatenaba bloques sin comparar nada, y `_validar_continuacion` juzga el
bloque aislado. Arreglado con `_strip_duplicated_opening` (≥12 palabras consecutivas idénticas, solo
al arranque del bloque nuevo). Validado: corta 84 palabras en la costura real, **0 falsos positivos**
en 200 costuras arbitrarias del mismo texto español y en los 50 shorts; casos degenerados cubiertos.

### ✅ El medidor: emparejado local + métrica que sí ve este fallo (`scripts/eval_sync.py`)

⚠️ **La premisa del bloque A de la v1 era FALSA.** Decía que el `difflib` global de `eval_sync.py`
inflaba la media "de 0,072 a 0,153 s" y que el JSON de la corrida larga estaba mal. Medido A/B sobre
los mismos datos, global y local dan **exactamente lo mismo** (5062 pares, 0,153 s, +0,003 s) y **los
6 veredictos de zona coinciden** con las transcripciones frescas. El 0,072 era el baseline del fixture
de 3 min: comparar eso con producción es comparar dos regímenes distintos. El 0,153 **es el número
real** de ese vídeo, y su causa es ANCLA-01, no el instrumento. `data/eval/2026-08-10-produccion-real.json`
**no está mal**; se conserva intacto y la re-medición vive en `-v2.json`.
(El script `validar_veredicto.py` que la v1 citaba como evidencia ya no existe en el repo.)

Lo que sí se cambió, y aporta:
- emparejado **local por ventanas** (no puede enganchar una repetición lejana, aunque aquí no lo hacía);
- métricas nuevas: **`peor_tramo`** (mediana del tramo de 40 palabras más desincronizado), `error_p95`
  y `palabras_muy_tarde`. **La media y el sesgo dieron por bueno este vídeo; el peor tramo lo caza:
  +1,110 s en t=690 s.** Esa es la métrica que faltaba en el gate;
- `--transcripcion` para re-medir una corrida vieja sin repetir 10 min de CPU del referí.

### 🔧 Instrumento reutilizable: `scripts/anchor_bench.py`

Reproduce la cadena real sobre artefactos ya pagados, con **control del instrumento**: parte de las
palabras crudas + el anclaje viejo y reproduce el `.ass` publicado con **0,005 s de media y 0,010 s de
máximo**. Si ese control no sale ~0, el banco no está midiendo la corrida real y nada de lo que diga
vale. Datos en el scratchpad de la sesión: `raw_words.json`, `sentences.json`, `whisper_video001.json`.

---

## LO QUE QUEDA

### BLOQUE 1 — El gemelo en shorts (regla 11) — SIN VERIFICAR
`shorts_generator.py:295` llama a `run_tts`, así que **hereda el fix por construcción**. Pero un short
son ~200 palabras = 1-3 ventanas: si la mala es la única, el short **entero** queda detrás y el error
sobrevive al `/1.5` como ~0,7 s. No se ha medido ningún short con el anclaje nuevo. Los
`temp/short_*_subs.srt` no sirven: no guardan los `SentenceBoundary`. Hace falta capturarlos o medir un
short generado contra transcripción independiente.

### BLOQUE 2 — La corrida larga de validación — APLAZADA POR DISCO
Es la única verificación concluyente del fix a escala real (214 ventanas). Cuesta **~2h40, 53
peticiones y ~7,3 GB**. Con **16 GB libres** y la evidencia de la corrida rota intacta
(`output/` 3,19 GB + `shorts_tiktok/` 4,4-4,65 GB + `temp/`), el margen es de ~2 GB: si se llena a
mitad, `take_chunk` ya habrá vaciado el pool y se pierden la ingesta y las peticiones.
**Decisión pendiente de Diego: qué se libera.** Nada se ha borrado.

### BLOQUE 3 — El gate no cubre esta clase de fallo
`/eval` corre sobre 3 min / 12 ventanas; producción tiene 214, y con ~2% de ventanas malas el fixture
tiene ~25% de probabilidad de ver una. Ahora al menos el gate **mide el peor tramo**, así que si lo ve
lo canta. Opciones abiertas: fixture largo (10-15 min), o aceptar la clase de fallo y fijar cada
cuánto se corre producción con medición completa. ⚠️ `test_e2e/config.yaml` no se toca para que el gate
apruebe; ampliarlo es otra cosa y lo aprueba Diego.

### BLOQUE 4 — `target_wpm` — NO LO TOQUES SOBRE n=2
La v1 proponía 160 → ~177 con n=2. Contra el `pipeline.log`, seis corridas largas reales dan
152,3 / 157,7 / 160,4 / 160,6 / 161,5 y **177,2 solo en la corrida contaminada por la basura del
modelo**. 160 está bien calibrado; 177 es el outlier. Fuera del camino crítico.

### BLOQUE 5 — Variedad de los 50 shorts: es juicio de Diego, no medición
50/50 títulos únicos y 24 parentescos distintos, pero **50/50 empiezan por "Mi ‹alguien›"**, 33/50 usan
"vendió"/"robó" y 23/50 nombran una autoridad. No es "la misma historia" (eso lo desmiente el léxico:
Jaccard máximo 0,210); es **la misma plantilla de título**. Si eso es estilo de nicho o huele a granja
lo decide Diego leyendo los 50 títulos, no un umbral.

### BLOQUE 6 — Heredado: `prompts/short_story.txt` no recibe las directrices de competencia
Sin cambios. Sigue abierto desde la sesión anterior.

---

## REGLAS DE ESTA SESIÓN (siguen vigentes)

- **En serie.** `pipeline.log` es ruta fija, `cleanup_temp` hace `rmtree` del temp compartido y
  `assets/.tint_index` es read-modify-write sin lock.
- **`--keep-temp` obligatorio** en cualquier corrida que vayas a medir.
- **Prohibido `python main.py` sin `--config`** si no quieres re-ingerir 13,8 GB.
- **Intocables:** `input/`, `test_e2e/clip.mp4`, `test_e2e/output/`, `test_e2e/shorts/`, `data/`, y el
  `temp/` de la corrida rota (es la evidencia con la que se midió todo esto).
- **Nunca sobrescribir un JSON de `data/eval/`**: `data/` está gitignored y un borrado es permanente.
  Escribe `-v2`, `-postfix`, etc. El baseline del fixture está respaldado en
  `2026-08-10-BASELINE-fixture-3min.json`.
- `git commit -m "pre-fix ..."` antes de editar. **No uses `git add -A`** (en una sesión anterior se
  coló `PORTAFOLIO/*.html`); añade por ruta explícita. `docs/video_guion.md` y `assets/.tint_index`
  están modificados de antes y no son de este trabajo.
- **Verificación por EJECUCIÓN.** Pega la salida real.

## TRAMPAS DE MEDICIÓN YA PAGADAS

1. `exceso = nº silencios − nº signos de puntuación`: mete la variable manipulada en el denominador.
2. Hueco entre subtítulos como `siguiente.start − previa.start`: eso es la DURACIÓN de la palabra.
3. **Comparar un número de producción con el baseline del fixture de 3 min y culpar al instrumento.**
   Es lo que hizo la v1 de este SEED. Dos regímenes distintos no se comparan sin decirlo.
4. **Control de reproducción por ÍNDICE** entre el `.ass` (5256 cues) y las palabras (5290): acumula un
   desfase falso que llegaba a 22 s. Empareja por texto.
5. La media y el sesgo globales **no ven** un defecto local: 204 palabras rotas entre 5290 mueven la
   media 0,03 s. Mide el peor tramo.
6. Fixture con texto repetido = medición falsa · `--no-shorts` oculta una clase entera de fallos ·
   `--dry-run` valida la historia, no la cadena.
