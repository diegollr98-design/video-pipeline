---
name: daily-run
description: Loop diario de producción — mide el presupuesto de peticiones de OpenRouter ANTES de lanzar, decide cuántos shorts caben, corre el pipeline, audita la salida y reporta. Evita morir a mitad de corrida con un 429.
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, Agent
---

# /daily-run — Loop diario de producción

Capa Claude sobre `main.py`. El script hace ingesta → producción → shorts → competencia.
Este skill hace lo que el script no puede: **presupuestar la cuota antes de gastarla**, decidir el
alcance de la corrida, auditar la salida y resumir.

**Cuándo usar:** una vez al día. **No sube nada a YouTube** — el pipeline no publica y este skill
tampoco. Produce archivos y te dice qué salió.

---

## Por qué existe: el cuello de botella es la cuota Y el reloj

Los modelos `:free` de OpenRouter tienen un tope de **peticiones al día**, no solo de rate:
**50/día** con menos de 10 créditos comprados, **1000/día a partir de 10**. El error es
`429 Rate limit exceeded: free-models-per-day`.

**El estado de la cuenta caduca: verifícalo, no lo leas de aquí** (`GET /api/v1/credits`; ver el aviso
de `/api/v1/key` más abajo). Última verificación: **10 créditos, 1000/día, 10-ago-2026** — con eso
caben ~20 vídeos/día. Este apartado dijo "0 créditos, tope de 50" cuando ya era falso [DOC-01].

Reparto del gasto, medido en la producción real de 30 min (10-ago-2026, **53 peticiones**):

| Concepto | Peticiones |
|---|---|
| Historia de un vídeo de 30 min | 3 bloques (un bloque ≈ 2000 palabras) |
| **Shorts** | **1 por short** — salieron **50** de un chunk de 33 min |
| Escaneo de competencia + debate | 5-15 |

**Los shorts son los que se comen el día.** Pero con 1000/día la cuota dejó de ser el cuello de
botella: esa corrida tardó **~2h40 de reloj** (23 min ingesta + ~20 min vídeo + ~95 min los 50 shorts)
y el disco quedó al 97%. La decisión principal de este loop es *cuántos shorts caben hoy* — hoy por
**tiempo y disco** antes que por cuota.

⚠️ **Los reintentos cuentan.** `max_retries: 5` significa que un bloque que falla puede quemar 5
peticiones. Toda estimación de aquí asume cero reintentos: es un **suelo**, no una predicción.

---

## PASO 1: Medir el presupuesto (antes de tocar nada)

**No existe un contador exacto y hay que decirlo.** Lo que sí hay:

**a) Estimación local desde el log.** Cuenta lo ya gastado hoy en `pipeline.log`:

```bash
grep -c "Bloque [0-9]*/" pipeline.log        # bloques de historia generados
grep -c "OpenRouter: reintento" pipeline.log # reintentos (cada uno es una petición gastada)
```
Suma los shorts producidos hoy (`ls shorts_tiktok/*.mp4` con fecha de hoy) — 1 petición cada uno.

**b) Sonda definitiva.** Si la estimación deja duda, una sola petición mínima al modelo free resuelve:
un `429` con `free-models-per-day` significa que el día está agotado. Cuesta 1 petición y es la única
señal certera del **contador diario** (que no lo da ningún endpoint).

⚠️ **NO uses `/api/v1/key` para esto.** Devuelve `limit`/`limit_remaining`, que son el **tope de gasto
configurado en la clave**, NO el saldo ni el contador diario. Confundirlos ya llevó a creer que había
dinero cuando no lo había. El saldo real está en `/api/v1/credits` (`total_credits − total_usage`),
y tampoco es el contador de peticiones.

Reporta el presupuesto como lo que es: **estimado**, con su margen.

## PASO 2: Estado del pool y plan de la corrida

```bash
python main.py --config config.yaml --skip-ingest --dry-run   # ojo: gasta peticiones, úsalo solo si hace falta
```

Mejor sin gastar: lee `config.yaml` y mide el pool directamente (duración total de `pool/*.mp4` con
`ffprobe`). Reglas del pipeline: chunk de 20-39 min → se usa entero; ≥40 min → se corta en 30 min.
Producción solo mientras el pool ≥ 20 min.

Con eso calcula el **coste mínimo de la corrida**:

```
peticiones ≈ num_bloques + num_shorts        (+ 5-15 si escaneas competencia)
num_bloques  = max(2, ceil(target_words / 2000))
target_words = duracion_chunk_min × story.target_wpm
num_shorts   = duracion_chunk / (shorts.target_words / target_wpm × 60 / shorts.speed)
```

## PASO 3: Decidir el alcance — y decirlo antes de lanzar

Presenta el plan explícitamente:

```
presupuesto estimado: <n>/<tope verificado hoy> restantes (± margen)
coste de la corrida:  <n> peticiones  (historia <n> + shorts <n> + competencia <n>)
```

Reglas de decisión, en orden:

1. **La historia es prioritaria.** Si no caben ni los bloques de la historia, **no lances**: dilo y
   propón esperar al reset (día natural UTC).
2. **Los shorts se recortan, no se cancelan.** Si el presupuesto no da para todos, baja
   `shorts.generate_per_video` y dilo. Un vídeo con 4 shorts es mejor que una corrida muerta a mitad.
3. **Deja un colchón de ≥5 peticiones** para reintentos. Sin colchón, un solo bloque con problemas se
   come el margen y aborta la historia.
4. **La competencia va la última**, y solo si sobran ≥15. No produce vídeos.
5. Si el plan recorta algo, **pregunta a Diego antes de lanzar**. No decidas tú reducir su producción
   del día.

## PASO 4: Lanzar

```bash
python main.py                    # ingesta + producción completa
python main.py --skip-ingest      # solo produce del pool existente
```

**Nunca con `--no-shorts` "para ir rápido"**: oculta una clase entera de fallos y además es
precisamente lo que el presupuesto ya está gobernando de forma explícita.

Si la corrida muere con `free-models-per-day`, **no es un bug del pipeline**: anótalo, di en qué fase
murió y qué quedó a medias en `pool/` y `temp/`.

## PASO 5: Auditar la salida

Antes de dar la corrida por buena, lanza el agente **`output-audit`** sobre el vídeo generado y sus
artefactos. **No cierres la corrida con "terminó sin error"** — el demuxer `concat` estuvo roto desde
siempre terminando sin error.

Si tocaste código desde la última corrida, esto no basta: corre `/eval`.

## PASO 6: Reportar

```
🎬 Daily Run — <fecha>

presupuesto:  <n> gastadas (estimado) · quedaban <n>/<tope verificado> al empezar
pool:         <min> antes → <min> después
producido:    video_<NNN>_final.mp4  (<min>, ratio duracion/chunk <X>)
              <n> shorts
output-audit: <LIMPIO|RIESGO|BLOQUEANTE>  — <hallazgos>
competencia:  <escaneada | omitida por presupuesto>

pendiente:    <lo que quedó a medias, si algo>
```

Si `output-audit` da BLOQUEANTE, dilo arriba del todo y **no marques la corrida como buena**. Añade
una entrada a `.claude/incident-ledger.md` con la evidencia (solo el hecho — `/optimize` es el único
que promueve a regla).

---

## Notas operacionales

- **No publica nada.** Ni este skill ni el pipeline suben a YouTube.
- **No aplica las directrices de competencia al prompt** sin el OK explícito de Diego
  (`--apply-trends` modifica `prompts/reddit_story.txt`; es reversible con `remove_from_prompt`, pero
  sigue siendo su decisión).
- **El tope se resetea por día natural UTC**, igual que la cuota de la YouTube Data API.
- **La cuota de YouTube es aparte y son TRES cupos** (ver `QUOTA_BUCKET`): 100 llamadas/día de
  `search.list`, 100 de `videos.insert`, y 10.000 unidades para el resto (1 por lectura, 50 la
  miniatura). Un escaneo de 40 canales cuesta **4 búsquedas + 81 unidades**, y lo que ata son las
  búsquedas (100/día → ~25 escaneos), no las unidades. No compite con la de OpenRouter.
- **Si `pool/` está por debajo de 20 min**, no hay producción posible: la corrida es solo ingesta.
  Dilo y no gastes peticiones.
- **Limitación conocida:** `short_story.txt` no recibe las directrices de competencia, así que los
  shorts ignoran ese análisis. Está en los pendientes de `CLAUDE.md`.

## REGLAS

- **Nunca** lances sin haber estimado y **dicho** el coste en peticiones.
- **Nunca** presentes el presupuesto como exacto — no lo es, y fingir que lo es es peor que el margen.
- **Nunca** recortes la producción de Diego sin preguntarle.
- **Nunca** cierres la corrida sin auditar la salida.
- **Nunca** confundas `/api/v1/key` (tope de gasto de la clave) con el saldo o con el contador diario.
