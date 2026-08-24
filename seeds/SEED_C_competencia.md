> ✅ EJECUTADO (14-ago-2026).

# SEED C — Que el análisis de competencia llegue a los shorts y se ejecute solo

> PASO 0 OBLIGATORIO: invoca /seed-review sobre este SEED antes de tocar nada.

**Modelo de trabajo:** Opus 5 orquesta y audita, Sonnet 5 implementa (`CLAUDE.md` §ORQUESTACIÓN).
**Rama:** `git checkout -b feat/competencia`. **Nunca `git push`.**

## Corre en PARALELO con otros tracks — respeta esto o rompes su trabajo

**Ficheros que te pertenecen:** `modules/trend_advisor.py` · `modules/competitor_scout.py` ·
`prompts/reddit_story.txt` y `prompts/short_story.txt` · `dashboard.py` **solo la pestaña
Competencia** · un módulo/script nuevo para la programación.

**Prohibido:** ejecutar `main.py` como pipeline · editar `main.py`, `modules/tts_engine.py`,
`script_generator.py`, `youtube_uploader.py` · reescribir `config.yaml` (**añade** tu bloque al
final marcado `# [track C]`).

**OpenRouter:** presupuesto **≤30 peticiones** para este track (el debate del LLM y la
clasificación de canales). Verifica el tope con `GET /api/v1/credits` antes de gastar — **no lo leas
de un `.md`**, ese dato caduca ([DOC-01]: tres revisiones repitieron un valor falso porque estaba
escrito en `CLAUDE.md`).

## 🔴 EXCLUSIÓN MUTUA CON EL TRACK B — léelo antes de la primera llamada

**Puede haber otra sesión trabajando en este mismo repo a la vez que tú: el track B
(`SEED_B_subida_youtube.md`).** Es el único otro track que toca la API de YouTube, y comparte
contigo el contador de cuota. **NO asumas que está o que no está corriendo: PREGÚNTASELO A DIEGO**
antes de tu primera llamada real. El contador vive en **`data/competitors.json`**, que es un fichero **sin lock**:
si los dos escribís a la vez se **pierden actualizaciones** y el corte preventivo deja de proteger.
Para B eso significa comerse un `403` a mitad de una subida de 1,5 GB; para ti, que un escaneo se
corte en falso o siga cuando ya no debería.

> **REGLA: solo UNO de B y C puede hacer llamadas REALES a la API de YouTube a la vez.**
> Tú gastas ~**470 unidades** por escaneo con descubrimiento (`search.list` cuesta 100 cada una y es
> el gasto dominante); B gasta **1.650 por vídeo**. El tope es **10.000/día** para los dos juntos.

**Protocolo, obligatorio (no es prosa: son pasos que dejan rastro):**
1. **PIDE TURNO A DIEGO** antes de tu primer escaneo real. Mientras esperas, trabaja con los datos
   ya cacheados en `data/competitors.json` y `data/competition_report.json`, que dan de sobra para
   desarrollar la inyección en los prompts.
2. **Anota el contador ANTES**: lee `data/competitors.json` y pega el valor en tu informe.
3. Haz tu tanda de llamadas.
4. **Anota el contador DESPUÉS** y **comprueba que el delta es el que esperabas**. **Si no cuadra,
   otra sesión escribió encima: párate y avísale a Diego.** Ese descuadre es la firma de la
   actualización perdida, y es la única forma de detectarla.
5. Devuelve el turno diciéndolo explícitamente en tu informe final.

**Tú SÍ eres el dueño de `QuotaMeter`** (`modules/competitor_scout.py`). Si arreglas la carrera con
un lock atómico sobre el contador, **avisa a Diego para que se lo diga al track B**, porque hasta que
mergéis los dos siguen dependiendo del protocolo humano de arriba.

## Los dos huecos

### 1. Los shorts ignoran el análisis de competencia
`trend_advisor` inyecta las directrices **solo** en `reddit_story.txt` (verificado: la ruta sale de
`config.paths.prompt_template`, y no hay ninguna referencia a `short_prompt` en el módulo). Así que
todo el trabajo de competencia no toca a los ~50 shorts por vídeo, que son el 98% de los artefactos
que produce el pipeline.

Cuidado al hacerlo:
- Los prompts se consumen con `str.format(...)`. El texto del LLM se inyecta con **llaves duplicadas**
  (`{` → `{{`): una llave suelta revienta la generación **a mitad de una historia de 8 bloques**.
- La inyección va **entre marcadores** y debe ser **idempotente**; `remove_from_prompt` tiene que
  devolver el fichero **byte a byte** al original. Pruébalo con round-trip.
- Las directrices buenas para un vídeo de 26 min **no son las mismas** que para un short de 40 s
  (títulos de 10-18 palabras frente a 20-35). Si inyectas el mismo bloque en los dos, mídelo antes
  de darlo por bueno.
- ⚠️ **Los prompts se releen EN CALIENTE.** No los edites con una corrida en marcha.

### 2. No existe ningún disparo programado
Verificado: no hay scheduler en el repo. Hoy el escaneo de competencia es **solo manual** y la
producción también. Para que el pipeline sea autónomo hace falta un disparo desatendido.

Decisiones que **no tomes tú solo** — plánteaselas a Diego:
- ¿Programar solo el **escaneo** (barato, ~470 unidades) o también la **producción** (que consume
  gameplay, disco y ~55 peticiones)?
- ¿Con qué mecanismo? El Programador de tareas de Windows es lo nativo aquí; un bucle en Python que
  duerma es frágil y se pierde al reiniciar. **No inventes un demonio propio sin preguntar.**
- Si programas producción: el disco es el límite real (15 GB libres, una corrida pide ~12). Una
  corrida desatendida que llene el disco deja el repo inservible.

## Lo que ya está medido — NO lo repitas

- La clasificación de nicho la hace un **LLM y no un heurístico** porque se probaron tres y ninguno
  separa (detalle en `CLAUDE.md`). Lotes de **8**, no de 25: con 25 el modelo devolvió veredicto de
  3 canales y se saltó 49 en silencio.
- El **outlier** va por curva logarítmica saturada, **no** por percentil; engagement, velocidad y
  frescura **sí** por percentil.
- `search.list` cuesta **100** unidades; `channels.list`/`playlistItems.list`/`videos.list`, **1**.
  > ⚠️ CORRECCIÓN (24-ago-2026): dato caducado. `search.list` es **1 llamada de un cupo propio de
  > 100/día**, no 100 unidades del bote. Ver `QUOTA_BUCKET`. [QUOTA-02]
- Un corte de cuota **no debe rechazar canales**, y los rechazos se reconsideran (`revive_rejected`).
- El heurístico de idioma **no puede usar palabras ambiguas** ("me", "y").

## Trampas ya pagadas

1. **Una garantía pedida en el prompt no está garantizada hasta que un `if` la fuerza** — este repo
   lleva **cuatro** episodios (comas, título, variedad de shorts, puntuación). Si la directriz
   inyectada "debe" cambiar algo medible, **mídelo**, no lo asumas.
2. **`trend_advisor.debate` ya valida secciones y reintenta**: si añades otra llamada al LLM,
   ponle su guardia. El modelo razona en voz alta y devuelve fragmentos sin formato.
3. **Verde local ≠ funciona** ([MAIN-01]): pasa `pyflakes`, no solo `compileall`.
4. **Un gate nuevo es superficie nueva** (§16): pásale el conjunto vacío, el dato ausente y el valor
   desconocido antes de cantar victoria.

## Criterio de aceptación

(a) Un escaneo real inyecta directrices en **los dos** prompts, la inyección es idempotente y
`remove_from_prompt` devuelve ambos ficheros byte a byte al original — pega la salida del round-trip.
(b) El disparo programado se ejecuta solo al menos una vez y deja constancia en su log.
(c) Reporta el gasto de cuota REAL de ambas APIs. Entrada factual en `.claude/incident-ledger.md`
por cada defecto nuevo — **el retro no escribe reglas, solo `/optimize` promueve**.
