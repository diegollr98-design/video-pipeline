# SEED E — Producción real y veredicto final (VA EL ÚLTIMO Y VA SOLO)

> PASO 0 OBLIGATORIO: invoca /seed-review sobre este SEED antes de tocar nada.

**Modelo de trabajo:** Opus 5 orquesta y audita, Sonnet 5 implementa (`CLAUDE.md` §ORQUESTACIÓN).
**Rama:** trabaja sobre el merge de A+B+C+D. **Nunca `git push`.**

## ⛔ Este track NO se paraleliza

Eres **la única sesión autorizada a ejecutar `main.py`**. Los otros cuatro tracks lo tienen
prohibido justo para que tú puedas correr sin colisiones. Las tres razones son físicas:

- `pipeline.log` es **ruta fija**: dos pipelines a la vez se pisan el log.
- `cleanup_temp` hace **`rmtree` de `temp/`**, que es compartido.
- `assets/.tint_index` es **read-modify-write sin lock** (la rotación de color de miniaturas).

**Antes de empezar: confirma con Diego que A, B, C y D están mergeados y parados.**

## Qué tienes que producir

1. **`/eval` verde con las constantes actuales.** Hoy `PALABRAS_FRASE_MAX = 30` y
   `target_wpm = 196`, y **ningún `/eval` cubre esa combinación**: el último verde fue con 12/187 y
   el rojo con 40/199. Sin esto, ningún cambio de superficie sensible está cerrado.
2. **Una corrida de producción real de ~30 min**, con shorts, `--keep-temp` obligatorio.
3. **`output-audit`** sobre esa salida, y el veredicto del auditor **firmado con su huella**.
4. **El juicio de Diego** sobre el vídeo: si engancha, si la voz suena natural, si la miniatura
   llama. Eso no lo sustituye ninguna capa automática.

## Preparación material (hazla ANTES de lanzar)

- **`pool/` está vacío** y el chunk de gameplay vive en `temp/chunk_1786444528.mp4` (3,5 GB) con un
  nombre que `take_chunk` **NO busca**. O lo renombras a `pool/pool_XXX.mp4` para reutilizarlo, o
  re-ingieres desde `input/` (~1 h de CPU). Decídelo con el disco en la mano.
- **Disco: 15 GB libres, una corrida larga pide ~12 de pico.** Cabe justo. `input/` (13,8 GB) es
  **intocable**; si necesitas espacio, lo liberable sin permiso es material derivado, y
  `output/video_001_final.mp4` (1,45 GB, la corrida defectuosa del 11-ago, con su guion y `.ass` ya
  duplicados en `data/evidence/`) **requiere el OK de Diego**.
- **Cuota:** una corrida de 30 min son ~55 peticiones de OpenRouter. Verifica el tope con
  `GET /api/v1/credits` antes de lanzar — **no lo leas de un `.md`** ([DOC-01]).
- **`--keep-temp` NO es opcional**: sin él `cleanup_temp` borra el `.ass` y el `_story.txt`, que son
  **exactamente** lo que el gate y el auditor miden ([GATE-01]).

## Lo que este track tiene que DEMOSTRAR a escala

El fixture son 3 min y la producción 30: hay defectos que **el gate no puede ver por construcción**.
Lo que hay que confirmar en el régimen real:

| Qué | Por qué el fixture no lo cubre |
|---|---|
| Sincronismo en la **cola** de la distribución | 3 min = ~28 ventanas de anclaje; 30 min = 200+. Ahí vivía [ANCLA-01] |
| **Basura del modelo** enterrada en el cuerpo | requiere una historia de 3+ bloques; el fixture genera 1-2 |
| **Ratio vídeo/chunk** y el truncado | a 3 min manda `_truncate_to_words` y tapa la velocidad real |
| **Variedad de los ~50 shorts** | con 4 shorts no se ve la repetición |
| La **ventana aplastada** que arregló el track A | hay que confirmar que el fix aguanta a escala |

## Trampas ya pagadas

1. **[GATE-03] El gate NO es determinista**: genera una historia nueva cada corrida, así que su
   comparación contra baseline **no distingue un cambio de código de otra tirada del modelo**. Para
   llamar regresión a algo hace falta un **A/B controlado** (misma entrada, dos códigos).
2. **[INSTR-05] La métrica acústica del auditor es un NETO** (`silencios − signos`): **cuenta, no
   localiza**. Puede dar 0 mientras el instrumento posicional marca pausas mal puestas. No la uses
   sola para decir "arreglado".
3. **Medir pausas sobre la alineación que juzgas es CIRCULAR**: usa `silencedetect` sobre el WAV.
4. **La mediana esconde el defecto local** ([ANCLA-01]: una zona con mediana −0,110 s contenía 40
   palabras a −7,4 s). Mira el **peor tramo**, no el promedio.
5. **`--no-shorts` oculta una clase entera de fallos** (los 4 shorts idénticos vivieron ahí).
6. **Un veredicto de auditoría CADUCA** si cambian los criterios: si alguien tocó `audit_run.py` o
   `eval_sync.py` en los tracks A-D, **todos los veredictos viejos dejan de valer**. Es a propósito.

## Criterio de aceptación

`/eval` **PASA** con las constantes actuales · una corrida de ~30 min con veredicto del auditor
**sin defectos MEDIBLES** y firmado con la huella vigente · `output-audit` sin hallazgos que el
orquestador pueda validar · y el **OK explícito de Diego** tras verlo.

Si algo sale rojo: **no se cierra**. Entrada factual en `.claude/incident-ledger.md` y actualiza
`.claude/rules/sessions-log.md`. **El retro no escribe reglas, solo `/optimize` promueve.**
