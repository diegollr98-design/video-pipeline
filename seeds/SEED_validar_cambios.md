> ✅ EJECUTADO (10-ago-2026).

# SEED — Validar en paralelo que los últimos cambios son óptimos (v2, REESCRITO)

> PASO 0 OBLIGATORIO: invoca /seed-review sobre este SEED antes de tocar nada.
>
> **YA SE HIZO.** Este fichero es la v2, resultado de ese review (10-ago-2026, TIER PANEL:
> 1 agente ciego + 3 críticos adversariales, veredicto ✏️ CON EDICIONES, aprobado por Diego
> con dos enmiendas). La v1 está descrita abajo en §Qué cambió y por qué. Si vuelves a
> ejecutar este SEED, el review ya está hecho: no lo repitas, léelo.

---

## Qué cambió respecto a la v1 y por qué

La v1 encargaba barrer 6 parámetros en paralelo con 6 agentes. El panel encontró que **4 de
los 6 bloques no tenían instrumento válido**, que el paralelismo **corrompía las mediciones en
silencio**, y que el trabajo de más impacto eran cuatro defectos reales que nadie estaba mirando.

**Lo que la v1 acertó** (se conserva íntegro):
- El presupuesto: **la premisa de la v1 era CORRECTA y `CLAUDE.md` estaba desactualizado**.
  Verificado con `GET /api/v1/credits` → `{'total_credits': 10, 'total_usage': 0.0638}`,
  `is_free_tier: False`. Son **10 créditos y 1000 peticiones/día**, no 50.
  (Ojo: `/api/v1/key` devolvió `limit: 5` — eso es el tope de gasto de la clave, NO el saldo.
  Es la trampa que el propio repo documenta; no la repitas.)
- La prohibición de fixture con texto repetido.
- "Mide tu propia línea base, no te fíes del número de `CLAUDE.md`" — resultó profético: el
  número de `target_wpm` de `CLAUDE.md` estaba medido en el régimen equivocado.
- "Si un bloque no llega a conclusión, dilo. Es una respuesta válida."

**Lo que la v1 falló:**

| # | Fallo de la v1 | Evidencia |
|---|---|---|
| 1 | Barría parámetros mientras 4 defectos reales seguían vivos | ver §Fase 1 |
| 2 | Bloque A no tiene instrumento: el referí propuesto (whisper small) **es el mismo modelo que produce los timestamps** → circularidad direccional (Whisper crudo gana por construcción) | `tts_engine.py:13-20` vs `config.yaml:29` |
| 3 | edge-tts **no es determinista**: mismo texto, mismo rate, md5 distinto (23.625 bytes de 60.480). Todo A/B que re-sintetice confunde variante con varianza del servicio | medido en el review |
| 4 | Bloque D pedía n=30 para estimar una tasa del 1%: `P(ver ≥1) = 26%`. Harían falta ~300 | binomial |
| 5 | Bloque E citaba un baseline ("0,48 → 0,01") **que no existe en el repo** | `grep -rniE "similitud\|SequenceMatcher"` → solo el propio SEED |
| 6 | Bloque F pedía re-scoring offline sobre un corpus donde **los descartados no se guardan** (`competition_report.json` solo persiste los 12 virales de `videos_analyzed: 206`) → supervivencia de la muestra | `data/competition_report.json` |
| 7 | "Lanza los agentes EN PARALELO, son independientes" → **NO lo son**: `pipeline.log` es ruta fija (`main.py:30`), `cleanup_temp` hace `rmtree(temp_dir)` (`utils.py:76`), `temp/concat_list.txt`, `chunk_part.mp4` y `frames_analysis/` tienen nombres fijos, `assets/.tint_index` es read-modify-write sin lock | |
| 8 | "NO aplicar cambios al repo" era incompatible con los bloques A y B: `PALABRAS_RESPIRO`/`PALABRAS_LIMITE` son **constantes de módulo**, no config | `tts_engine.py:150-151` |

**Evidencia caducada que NO hay que perseguir:** el review citó `pipeline.log:125,144`
(`Error ingesting ...: FFmpeg concat failed`) como prueba de que la ingesta del gameplay real
falla. Son de las **01:25 y 01:31, anteriores al fix de `video_cleaner`** (~17:05); después de
ese fix la ingesta del fichero real **completó** (`pipeline.log:438,559` → `Ingestados 1/1`).
El bloqueo real está en otro punto: **`take_chunk` → `_concat_videos`**. Busca ahí, no en la ingesta.

---

## REGLAS DE EJECUCIÓN (cambian respecto a la v1)

- **EN SERIE, no en paralelo.** Ver fallo #7. Si algún paso se paraleliza, cada agente necesita
  su propio `temp_dir` vía `--config`, y aun así `pipeline.log` y `assets/.tint_index` colisionan.
- **Prohibido `python main.py` sin `--config`.** Ese comando ingiere los 13,8 GB de `input/`,
  recodifica y escribe en `output/`. Todos los comandos de `CLAUDE.md` §Ejecución lo omiten.
- **Presupuesto: 1000 peticiones/día** (verificado). No es el cuello de botella; el cuello es
  el reloj y el disco (**31 GB libres de 476, al 94%**).
- **Intocables:** `input/`, `pool/`, `data/`, `test_e2e/clip.mp4`, `test_e2e/output/`,
  `test_e2e/shorts/`. Nada de eso está en git (`.gitignore`) y el repo tiene **1 solo commit**:
  un borrado es permanente.
- **`git commit -m "pre-fix ..."` antes de editar, `fix ...` después.** Aquí sí se edita código:
  la v1 lo prohibía y por eso no podía arreglar nada.
- **Verificación por EJECUCIÓN.** Cada fase pega la salida real del comando.

---

## FASE 1 — Defectos reales (0 peticiones de OpenRouter). Va primero.

Los cuatro los introdujo la tanda de agosto y los confirmó Diego ejecutando.

### 1.1 🔴 El gemelo del bug del `concat` está VIVO — el más caro de la tanda
`modules/gameplay_pool.py:74` escribe rutas **relativas** en el fichero de lista del demuxer:
```python
safe = p.replace("\\", "/")      # SIN os.path.abspath
```
El fix se aplicó solo a `video_cleaner._concat_segments:205`. **Regla 11 del repo (bug en un path
→ revisa los paths análogos) incumplida.**

Se dispara desde `take_chunk` (`gameplay_pool.py:229`) cuando `len(selected) > 1`, es decir
**cuando el pool tiene 2 o más ficheros: el caso normal en producción real.** El fixture E2E
tiene 1 solo fichero, así que el camino nunca se ejerció.

- Arreglar con `os.path.abspath`.
- **Reproducir el fallo ANTES del fix** (dos ficheros en un pool de prueba → debe fallar) y
  volver a correrlo DESPUÉS (debe pasar). Sin el "antes", el "después" no demuestra nada.

### 1.2 🔴 `target_wpm: 195` está mal calibrado, y arrastra un efecto de cuota no reportado
`target_wpm` **no es la velocidad de la voz**: es palabras pedidas por minuto de gameplay
(`utils.calculate_target_words`). La velocidad real depende de la longitud: ~200 wpm en textos
cortos, **160,6 wpm** en la única producción larga real (5047 palabras / 1885 s).

Medido sobre `pipeline.log` (n=10, coste 0):

| `target_wpm` | Palabras pedidas | Audio resultante | Ratio sobre chunk de 30 min |
|---|---|---|---|
| 150 | 4500 | 28,0 min | 0,93 |
| **160** | **4800** | **29,9 min** | **1,00** |
| 195 | 5850 | 36,4 min | 1,21 |

El "96-104% validado" de `CLAUDE.md` es cierto **para clips de 3 minutos**, que es el régimen
equivocado (a 3 min el modelo se pasa y manda `_truncate_to_words`; a 30 min se queda corto).

**ENMIENDA DE DIEGO — separar el knob (el fallo de raíz).** `main.py:80` usa `target_wpm` para
calcular **cuántos shorts** se generan. Son dos ritmos distintos metidos en una sola clave: los
shorts hablan a ~200 wpm y las historias largas a ~160. El arreglo **debe separarlos**, no solo
cambiar el número.

Efecto colateral confirmado y no reportado en su día: el cambio 150→195 pasó de **33 a 43 shorts**
por vídeo de 30 min = **+10 peticiones, ~30% más de gasto**, contra la regla explícita del repo
("un cambio que sube las peticiones por vídeo se reporta aunque nadie lo pregunte").

### 1.3 🟠 El validador cubre solo un tercio de las peticiones
`_validar_salida` se llama en `_generate_first_block` (`script_generator.py:253`) y en
`_generate_short_story` (`shorts_generator.py:93`), pero **NO en `_generate_continuation`**
(devuelve el texto crudo, `script_generator.py:308`). En una historia de 30 min son 4-6 bloques:
el guardia protege el primero y deja los demás sin red.

### 1.4 🟠 Falso positivo garantizado en el validador
`_MARCADORES_RAZONAMIENTO` (`script_generator.py:114-119`) contiene **`"vamos a"`**, que es
español corrientísimo. Un título legítimo como *"...Y Ahora Vamos A Juicio"* se tira a la basura.
Comprobar el resto de marcadores por el mismo criterio (`"historia:"`, `"título:"` son subcadenas).

**Validación gratis:** los **71 títulos reales** que ya están en `pipeline.log` se pasan por
`_validar_salida` sin gastar una petición. Longitudes observadas 10-38 palabras: el techo de 45
**nunca se ha activado** y el suelo de 12 solo disparó sobre el verdadero positivo histórico
(*"The user wants a viral micro-story script for YouTube Shorts/TikTok."*, 10 palabras).

---

## FASE 2 — Infraestructura de medición (sin esto, nada se puede cerrar)

### 2.1 Escribir `scripts/eval_sync.py` y correr `/eval` una vez
`data/eval/` no existe. `scripts/` no existe. El skill `/eval` especifica el medidor línea a
línea y dice "si no existe, créalo" — **nadie lo creó**. Hoy el gate no puede aprobar ni bloquear
nada, y `sessions-log.md` ya lo declara pendiente. Es el prerrequisito de todo cierre en
superficie sensible.

### 2.2 Bloque B (comas de respiración) — el único bloque de la v1 que sobrevive entero
Es la única superficie sensible genuinamente frágil, y cuesta **0 peticiones** (se corre sobre
texto ya existente; edge-tts es gratis).

- **`_CONECTORES_SEGUROS` tiene "aunque" 5 veces de 12 entradas** → 7 conectores únicos reales.
- **`_CONECTORES_LARGOS` incluye `que`, `para`, `sin`, `con`, `desde`, `hasta`**, que no son
  conjunciones coordinantes. Coma antes de `que` convierte una relativa especificativa en
  explicativa y **cambia el significado** ("el coche que compré" ≠ "el coche, que compré").
  Esto se **cuenta**, no se le pregunta a un LLM juez (regla §18: un juicio que el modelo no
  puede dar produce ruido plausible).
- **El invariante "no cambia el número de palabras" no tiene ni un `assert` ni un test.**
  `_ensure_breathing_commas` es pura (str→str): property test sobre textos reales + adversarios
  (línea vacía, palabra suelta, texto sin puntuación, conector al inicio). Es el único gate con
  dientes de este bloque.
- Al barrer umbrales: **monkeypatch en un driver propio** (`import modules.tts_engine as t;
  t.PALABRAS_RESPIRO = 6`), verificado que funciona porque las constantes se leen en tiempo de
  llamada. No editar el módulo mientras otra cosa mide.
- Medir a la vez **duración/ppm**: bajar los umbrales siempre reduce pausas inesperadas y
  siempre alarga el audio. Medir solo pausas recomienda 6/10 por construcción.

---

## FASE 3 — Lo que NO es medible con el instrumental actual (decirlo es la respuesta)

### 3.1 Bloque A (anclaje) — sin A/B automático, PERO con un gate que sí funciona
No se puede arbitrar con whisper small timestamps derivados de whisper small (fallo #2), y
edge-tts no es determinista (fallo #3). Además traslación, afín y traslación+comas **clavan las
tres `s_start = sent["start"]`**: a nivel de frase son idénticas por construcción.

**ENMIENDA DE DIEGO:** la verificación que **sí funcionó** en agosto no era un A/B, era otra:
**extraer fotogramas del vídeo final y comparar la palabra en pantalla con el instante en que
suena.** Eso es independiente del alineador. Se conserva como **gate**, no como barrido.

Lo único no circular que queda: `SentenceBoundary` sí es ground truth válido para la variante
*Whisper crudo* (única sin anclar).

Si algún día se quiere el A/B de verdad: hace falta un aligner de **otra familia**
(wav2vec2-xlsr-es o whisper large-v3) y comprobar si cambia el **orden** de las variantes.
Y diseño **pareado** (una síntesis, varias variantes sobre el mismo audio) — ojo: eso haría que
los números idénticos entre corridas pasen a ser lo *esperado*, y el `/eval` hoy los prohíbe
como firma de artefacto. Anotarlo antes de que muerda.

### 3.2 Bloque D (validador) — la pregunta estadística es irresoluble; la determinista no
"¿La tasa de razonamiento es <1%?" no se responde con n=30 (fallo #4). Se reformula a lo que sí
se puede: los 71 títulos del log + arreglar `"vamos a"` + extender el guardia (§1.3, §1.4). Hecho.

### 3.3 Bloque E (anti-repetición) — el proxy no discrimina
Medido con difflib sobre títulos reales: los 4 shorts buenos dan **0,376** de media; "misma
historia con otras palabras" da **0,542** — por encima de 5 de los 6 pares considerados buenos.
La similitud léxica de títulos no separa "misma historia" de "historia distinta", y hay Goodhart
directo (al modelo se le enseñan exactamente los títulos y se le pide cambiarlos).

Defecto real que sí conviene anotar, confirmado por aritmética: `main.py:104` siembra con los
**últimos 8** títulos del disco y `_build_avoid_block` se queda con los **últimos 12** de la
lista; como los 8 del disco van al principio, salen de la ventana en cuanto se generan 12 shorts
nuevos. En una tanda larga, la protección entre corridas cubre solo los primeros shorts.

### 3.4 Bloque F (competencia) — supervivencia de la muestra
Irresoluble offline (fallo #6). Además `score_videos` calcula engagement/velocidad/frescura por
percentil **dentro de `fresh`**, y `fresh` se define **después** del filtro de `min_views`:
re-puntuar con los `pct_*` guardados da un número que no corresponde a ninguna configuración real.
Y de 221 canales, `llm_in_niche` es `None` en **168** (la clasificación murió por rate-limit):
auditar los 25 "fuera de nicho" mira donde no está el fallo.

**Lo accionable:** que el próximo escaneo **persista el corpus `fresh`**, no solo los 12 virales.
Sin eso la pregunta no se puede responder nunca.

---

## FASE 4 — Cierre: la prueba que manda

**No se da por bueno el pipeline hasta que la ingesta de los 33 minutos reales complete de
verdad y `take_chunk` produzca un chunk con ≥2 ficheros en el pool.** Es lo único que demuestra
que el gemelo del `concat` (§1.1) está muerto — el fixture de 3 min no lo ejerce.

Ojo al disco: 31 GB libres al 94%. `input/2026-01-27 21-29-26.mp4` son 13,8 GB / **2013,5 s =
33,6 min** (stock para *un* vídeo, no "horas").

Y actualizar `CLAUDE.md` §OpenRouter: dice "0 créditos comprados, saldo −0,06 USD, 50/día" y hoy
son **10 créditos y 1000/día**. Lo hace el ejecutor de este SEED, no Diego, para no chocar en el
mismo fichero.

---

## Entregable

Informe con: qué se arregló (con la salida real del antes/después), qué se midió, qué se declaró
**no medible y por qué**, el gasto de peticiones por vídeo recalculado, y la lista de lo que
queda abierto. Entrada factual en `.claude/incident-ledger.md` por cada defecto cazado.

"No concluyente" sigue siendo una respuesta válida y preferible a inventar una recomendación.
