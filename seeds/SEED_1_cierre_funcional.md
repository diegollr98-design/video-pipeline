# SEED 1 — Cierre funcional del pipeline (3 huecos pequeños)

> PASO 0 OBLIGATORIO: invoca /seed-review sobre este SEED antes de tocar nada.

## Contexto

`c:\Users\diego\Desktop\YOUTUBE` genera vídeos de YouTube sin intervención humana:
gameplay de Minecraft + historia narrada + subtítulos + intro + miniatura, más shorts
verticales. La cadena está validada de punta a punta con medición (ago 2026).

Quedan tres huecos funcionales, **independientes entre sí**. Este seed los cierra.
Lee `CLAUDE.md` antes de empezar: documenta cada decisión con la medición que la motivó.

**Son independientes: puedes repartirlos en agentes paralelos.** Los tres tocan ficheros
distintos salvo el dashboard, así que si van en paralelo, coordina las ediciones de
`dashboard.py` (bloques A y B lo tocan).

---

## Bloque A — Los shorts deben recibir las directrices de competencia

**El hueco:** `modules/trend_advisor.py::_prompt_path` devuelve solo
`paths.prompt_template` (`prompts/reddit_story.txt`). El prompt de shorts
(`prompts/short_story.txt`, en `paths.short_prompt`) **nunca recibe nada**, así que la
mitad de la salida del canal ignora todo el análisis de competencia.

**Qué hacer:** que `apply_to_prompt`, `remove_from_prompt` y `current_injection` operen
sobre **ambos** prompts.

**Trampas que ya costaron caro aquí:**

1. **Las llaves.** Los dos prompts se consumen con `str.format(target_words=, style=)`.
   El texto del LLM se inyecta con las llaves duplicadas (`{` → `{{`) o `generate_story`
   revienta con `KeyError` a mitad de una historia de 8 bloques. Ya está resuelto en
   `render_injection`; no lo rompas al generalizar.
2. **Los titulares de ejemplo NO valen para shorts.** `reddit_story.txt` pide títulos de
   **20-35 palabras** y `short_story.txt` pide **10-18**. El debate genera titulares de
   20-35. Inyectarlos tal cual en el prompt de shorts empeoraría los títulos.
   Decide: o inyectas solo las `directrices` en los shorts (más simple y seguro), o
   pides al modelo una tanda aparte de titulares cortos. Justifica la elección.
3. **Reversión byte a byte.** `remove_from_prompt` debe devolver AMBOS ficheros
   exactamente al original. Hay un test que lo comprobaba comparando longitudes; falló
   una vez por una línea en blanco perdida. Verifícalo en los dos ficheros.
4. **El ancla es la misma**: los dos prompts terminan en `Historia:` y la inyección va
   justo antes.

**Dashboard:** la pestaña 🔍 Competencia muestra si hay directrices aplicadas y permite
aplicar/quitar. Debe reflejar el estado de los dos prompts (p. ej. "aplicadas en vídeos
largos y shorts" / "solo en largos").

**Verificación exigida:** genera un short REAL con las directrices aplicadas y comprueba
que el título y el tema las siguen. No vale con que el fichero contenga el texto.

---

## Bloque B — El escaneo de competencia debe correr solo

**El hueco:** el usuario pidió "una lista de competidores que se vaya actualizando
constantemente". Hoy solo se actualiza cuando lanza `python main.py --scan-competition`
a mano o pulsa el botón del dashboard.

**Qué hacer:** dejarlo programado. Evalúa las opciones y elige con criterio:
- Programador de tareas de Windows (el usuario está en Windows 11).
- El skill `/schedule` de Claude Code, si encaja.
- Un modo demonio en el propio proyecto (probablemente peor: hay que mantenerlo vivo).

**Restricciones reales, no las ignores:**

- **Cuota de YouTube API**: 10.000 unidades/día. Un escaneo con descubrimiento gasta
  ~470; re-medir sin descubrir (`--no-discover`), ~120. El contador vive en
  `data/competitors.json` por día natural UTC.
- **Cuota de OpenRouter**: 1000 peticiones/día a modelos `:free`. El escaneo consume
  entre 5 y 15 (debate + clasificador de nicho), y **la producción de vídeos consume del
  mismo bote** (~34 por vídeo de 30 min). Si el escaneo programado se come el
  presupuesto, el usuario no puede producir. Decide la frecuencia con ese número delante.
- **NO debe aplicar las directrices solo.** El usuario decidió explícitamente que la
  inyección en el prompt exige su OK. El escaneo programado escanea y debate; aplicar
  sigue siendo manual.
- Si el usuario está produciendo un vídeo en ese momento, el escaneo no debería competir
  por la cuota. Piensa si hace falta un cerrojo o basta con elegir bien la hora.

**Verificación exigida:** que se dispare de verdad al menos una vez y deje el informe
actualizado en `data/`. No vale con dejar la tarea creada.

---

## Bloque C — `st.components.v1.html` está deprecado

**El hueco:** `dashboard.py` usa `st.components.v1.html` para el diagrama animado del
Roadmap (SVG con animaciones CSS y SMIL). Streamlit avisa de que se retira desde
**2026-06-01**; funciona todavía, pero es una bomba de relojería.

**Cuidado:** el aviso sugiere `st.iframe`, pero `st.iframe` toma una **URL**, no HTML.
El sustituto para HTML embebido puede ser `st.html`, que **no aísla en un iframe** — y
el diagrama depende de estilos y animaciones propios. Un cambio a ciegas puede romper la
animación o hacer que sus estilos se filtren al resto del dashboard.

**Qué hacer:** averigua la API correcta en la versión instalada (Streamlit 1.57),
migra y **comprueba visualmente** que el diagrama sigue animándose y que no altera el
resto de la página. Si no hay sustituto que preserve el aislamiento, dilo y deja el
código como está con un comentario que explique por qué.

---

## Reglas que valen para todo el seed

- **Verificar con ejecución real**, no leyendo el código. Los bugs de este repo pasan
  todos los checks estáticos: el demuxer `concat` estuvo roto desde siempre con exit
  code 0, y cuatro shorts idénticos se generaron sin un solo error en el log.
- El dashboard se prueba con `streamlit.testing.v1.AppTest`, que ejecuta el script de
  verdad y captura excepciones. Ojo: `st.stop()` dentro de una pestaña corta TODO el
  rerun y deja sin renderizar las siguientes.
- **NO borrar** `input/` (13 GB de gameplay), `data/` (221 canales acumulados) ni
  `test_e2e/clip.mp4` (el fixture del gate). Si un test necesita un `data/` limpio,
  muévelo y restáuralo: ya se borró una vez por un test y costó rehacer escaneos.
- Un E2E no necesita los 13 GB: clip de ~3 min a un `input_dir` propio y
  `target_duration_min` bajado. Receta en `CLAUDE.md`.
- Antes de cerrar, pasa el gate: `/eval`.
- Actualiza `CLAUDE.md` con lo que cambies y por qué, con el dato que lo respalda.

## Entregable

Por bloque: qué se cambió, la salida real de la verificación, y qué quedó sin resolver.
Si un bloque resulta ser mala idea al mirarlo de cerca, dilo y explica por qué — es una
respuesta válida.
