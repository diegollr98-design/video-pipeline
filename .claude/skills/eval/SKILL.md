---
name: eval
description: Gate del pipeline — corre la cadena entera contra el clip de test_e2e/ y MIDE la salida (sincronismo voz-subtítulo, pausas fuera de puntuación, variedad de shorts, ratio de duración). Es la única señal que autoriza cerrar un cambio en una superficie sensible.
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
---

# /eval — Gate del pipeline

La única defensa **con dientes** de este proyecto. `compileall` limpio no dice nada sobre si los
subtítulos van sincronizados; el pipeline "terminando sin error" tampoco — el demuxer `concat` estuvo
roto **desde siempre** terminando sin error.

> **Regla:** un cambio en una superficie sensible (alineación, limpieza de texto, ingesta, historia,
> composición, cuota — `produccion-loop.md` §B) **no se cierra** si `/eval` empeora respecto al
> baseline. **No es un aviso: es un no.**

---

## La métrica que manda: ERROR DE SINCRONISMO

**No optimices "el vídeo se generó".** Todos los bugs graves de este repo produjeron un vídeo completo:

- los subtítulos con **+0,435 s de sesgo** (por detrás de la voz) durante meses,
- los **4 shorts con la misma historia**,
- las historias con **0 comas** y pausas inventadas a mitad de frase.

Las tres salidas eran archivos MP4 perfectamente reproducibles. Lo que las delató fue **medir**.

**Objetivo: sesgo NEGATIVO** (el subtítulo delante de la voz — el offset de audio es −100 ms a
propósito) con media ≤ 0,20 s y máximo ≤ 0,30 s.

---

## El fixture — `test_e2e/`

Ya existe y no hay que construirlo: `test_e2e/clip.mp4` (clip corto real) + `test_e2e/config.yaml`
(mismo pipeline, `target_duration_min` bajado, rutas propias). **No hace falta procesar los 13 GB de
gameplay para validar la cadena** — eso es lo que hizo posible la validación E2E de ago 2026.

⚠️ `test_e2e/clip.mp4` **no se borra jamás**. Sin él no hay gate.

⚠️ El fixture debe tener contenido **no repetido**. Un texto que repite párrafos hace que el
emparejador de la medición enganche la copia equivocada y devuelva un número falso — con la firma
característica de un **valor idéntico entre repeticiones**.

---

## PASOS

### 1. Baseline
Lee el resultado del último `/eval` en `data/eval/`. Si no hay ninguno, **este run ES el baseline y hay
que decirlo** — un primer run no aprueba ni bloquea nada.

### 2. Correr la cadena entera

```bash
python main.py --config test_e2e/config.yaml
```

**Con shorts.** Nunca evalúes con `--no-shorts`: oculta una clase entera de fallos (los 4 shorts
idénticos vivieron ahí). Si el pool ya tiene material y solo quieres producir:
`python main.py --config test_e2e/config.yaml --skip-ingest`.

**Coste:** una corrida consume peticiones del tope de **50/día** de OpenRouter (≈ 1 bloque de historia
+ N shorts). Estima y **dilo antes de lanzar**. Si quedan pocas peticiones, avisa y pregunta.

Guarda el log completo. Los errores de FFmpeg se leen por el **final** de stderr — los primeros 500
caracteres son el banner de compilación.

### 3. Medir el sincronismo (la medición principal)

Contra una **transcripción independiente** del audio final, no contra los timestamps que produjo el
propio pipeline (eso sería auto-atestiguarse).

Usa `scripts/eval_sync.py`. **Si no existe, créalo** con esta especificación:

- transcribe el WAV final con `faster-whisper` (modelo `small`, español) → palabras con timestamp;
- lee el `.ass` generado → palabras con su `start`;
- empareja ambas secuencias con `difflib.SequenceMatcher` sobre el texto normalizado
  (minúsculas, sin puntuación, sin tildes);
- para cada palabra emparejada: `error = t_ass − t_whisper`;
- reporta **n emparejadas / n totales**, **|error| medio**, **|error| máximo** y el **sesgo con signo**;
- si `n_emparejadas / n_totales < 0.85`, **no des veredicto**: el emparejado falló y el número no
  significa nada.

### 4. Medir el resto

| Qué | Cómo | Umbral |
|---|---|---|
| **Pausas fuera de puntuación** | huecos > 0,35 s entre palabras consecutivas del `.ass`; comprueba si la palabra anterior termina en `,.;:!?` | **0** fuera de puntuación |
| **Comas de respiración** | cuenta comas del speech y palabras entre comas | ninguna frase > 12 palabras sin coma |
| **Variedad de shorts** | compara todos los `*_title.txt` de `test_e2e/shorts/` entre sí y con los de `shorts_tiktok/` | ningún par con el mismo argumento |
| **Offset de gameplay por short** | cada short arranca en un punto distinto | N offsets distintos |
| **Ratio de duración** | `ffprobe` del vídeo / duración del chunk | ≈ 1.0 (**sin validar aún** con `target_wpm: 195`) |
| **Geometría de subtítulos** | `PlayResX/Y` y `\pos()` del `.ass` | largo `1920x1080`+`(960,540)`; short `1080x1920`+`(540,960)` |
| **Intro** | fin de la frase del título vs inicio del fade; primer subtítulo después de la intro | sin solape |
| **Artefactos** | `_final.mp4` + `_thumbnail.jpg` + `_title.txt`; por short `.mp4` + `_title.txt` | todos presentes |
| **Peticiones OpenRouter** | cuéntalas en el log | reportar siempre |

### 5. Reportar

```
/eval — <fecha>
config=test_e2e/config.yaml  peticiones_openrouter=<n>  duracion_corrida=<min>

SINCRONISMO:        media=<X>s  max=<X>s  sesgo=<±X>s   (baseline: <...>)   <✅ MEJORA | 🔴 REGRESIÓN | = igual>
                    emparejadas=<n>/<n>  (<85% → medición inválida)
pausas fuera de puntuación:  <n>   (baseline: <n>)
variedad de shorts:          <n> títulos, <n> argumentos distintos
ratio duracion video/chunk:  <X>
geometría subtítulos:        largo <ok/mal>  short <ok/mal>
artefactos:                  <n>/<n>

VEREDICTO: <PASA | BLOQUEA>
```

**BLOQUEA** si: el sincronismo empeora respecto al baseline (media, máximo o signo del sesgo), hay
pausas fuera de puntuación, dos shorts comparten argumento, falta un artefacto, o la geometría de
subtítulos no cuadra.

### 6. Guardar

Escribe el resultado en `data/eval/<fecha>.json` — es el baseline del próximo run.
Si el veredicto es BLOQUEA, **añade una entrada a `.claude/incident-ledger.md`** con su clase y la
evidencia. Registrar el hecho, **no** escribir una regla: solo `/optimize` promueve.

---

## REGLAS

- **Nunca** dar PASA sin haber corrido la cadena entera. Un `--dry-run` valida la historia, no el vídeo.
- **Nunca** evaluar con `--no-shorts`.
- **Nunca** medir el sincronismo contra los timestamps del propio pipeline — hace falta una
  transcripción independiente, o no estás midiendo nada.
- **Nunca** dar veredicto si el emparejado cayó por debajo del 85%, ni si el número sale **idéntico**
  a una corrida anterior (firma de artefacto del test, no de sincronismo real).
- **Nunca** tocar `test_e2e/config.yaml` para que el gate apruebe. Si crees que un umbral está mal,
  pregúntale a Diego.
- Si la corrida muere por el **429 de `free-models-per-day`**, no es un fallo del cambio: dilo, no des
  veredicto, y anota cuántas peticiones quedaban.
