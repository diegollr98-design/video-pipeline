# SEED 3 — Producción real de 30 minutos (validación de volumen)

> PASO 0 OBLIGATORIO: invoca /seed-review sobre este SEED antes de tocar nada.

## Contexto

`c:\Users\diego\Desktop\YOUTUBE` tiene la cadena de producción **validada de punta a
punta**, pero solo con clips de 3 minutos. Lo que falta es demostrar que aguanta el
volumen real: un vídeo de 30 minutos con sus ~30 shorts.

Esto **no es una tarea de programación**: es una corrida de validación. Si aparece un
bug, se arregla; pero el objetivo es medir, no refactorizar.

**Ejecuta este seed DESPUÉS de SEED 1 y SEED 2**, para que valide el estado final.

Lee `CLAUDE.md` antes de empezar: contiene las mediciones de referencia con las que
comparar.

## Por qué importa

Todo lo medido hasta hoy se hizo con clips de 3 min y ~600 palabras. A escala de 30 min
cambian cosas que no se han probado nunca:

- **La historia pasa a generarse en ~4-6 bloques** encadenados en vez de 1. El
  encadenado (`_generate_continuation`) apenas se ha ejercitado.
- **El troceo de edge-tts entra en juego.** `Communicate` parte el texto cada 4096 bytes;
  un vídeo de 30 min son ~27 KB, o sea ~7 trozos. Con clips cortos era 1 solo y esta ruta
  no se ha visto en producción. Se arregló para que los cortes caigan en salto de línea
  y no a mitad de frase — **hay que confirmarlo a esta escala**.
- **~30 shorts en cadena.** La lista anti-repetición se limita a los 12 últimos títulos;
  con 5 shorts la similitud media bajó de 0,48 a 0,01, pero a partir del 13 empieza a
  olvidar. Sin medir.
- **El presupuesto de peticiones.** ~4-6 bloques + ~30 shorts ≈ 34-36 peticiones a
  OpenRouter, de 1000 diarias. Más el rate-limit del proveedor
  (`Worker local total request limit reached (32/32)`), que ya saltó con clips cortos.
- **La ingesta de verdad.** `input/` tiene un fichero de 13 GB (33 min, 720p60) sin
  procesar. El `video_cleaner` y la recodificación a pool nunca se han corrido sobre él.

## Qué medir (y con qué comparar)

| Métrica | Cómo | Referencia actual |
|---|---|---|
| Aprovechamiento del gameplay | duración vídeo / duración chunk | 96-104% (con `target_wpm: 195`) |
| Sincronía voz-subtítulo | transcribir el audio del MP4 final y comparar con los fotogramas | error medio ~0,15s, máx ~0,25s |
| Pausas fuera de puntuación | huecos > 0,25s que no caen tras signo | 0 |
| Variedad de shorts | similitud léxica entre títulos, por pares | media 0,01 / peor 0,11 con N=5 |
| Shorts rotos | duración < 10s o título con razonamiento del modelo | 0 |
| Peticiones a OpenRouter | contarlas durante la corrida | presupuesto: 1000/día |
| Tiempo total de la corrida | reloj | sin referencia — es el dato nuevo |

Existen dos herramientas ya hechas: el skill **`/eval`** (gate que mide la cadena) y el
agente **`output-audit`** (adversarial, intenta demostrar que el vídeo está roto midiendo
sus artefactos). **Úsalos**; no reinventes las mediciones.

## Cómo correrlo

1. Comprueba el presupuesto ANTES de empezar. El skill `/daily-run` existe justamente
   para eso: mide las peticiones disponibles y decide cuántos shorts caben.
2. Ingesta el fichero real de `input/`. Es largo (13 GB, recodificación completa):
   lánzalo en segundo plano y no lo interrumpas.
3. Produce con la config real (`config.yaml`, no la de `test_e2e/`).
4. Mide todo lo de la tabla sobre la salida real.
5. Pasa `output-audit` sobre el vídeo generado.

## Trampas conocidas

- **No corras con `--no-shorts` para ir más rápido.** Oculta una clase entera de fallos:
  así se escaparon los cuatro shorts idénticos y el short de 4,5 segundos.
- **No uses texto repetido como fixture de sincronismo.** Un test que repetía el mismo
  párrafo dio 2,525s de error falso, idéntico en 3 de 5 corridas: el emparejador engancha
  la copia equivocada. Mide sobre el contenido real del vídeo.
- **Comprobar que los ficheros existen no es validar.** En este repo hubo un vídeo
  completo, reproducible y con exit code 0 cuyos subtítulos iban 1,5s por detrás de la voz.
- **El gameplay original no se toca.** `input/` son horas de grabación irrepetibles.
  La ingesta lo consume hacia `pool/`; asegúrate de entender qué mueve y qué copia
  ANTES de lanzarla. Si tienes dudas, haz la primera pasada sobre una copia.

## Si algo falla

Arregla lo que impida terminar la corrida, con la disciplina del repo: medir la causa
raíz antes de tocar, y verificar por ejecución. Lo que sea mejora y no bloqueo, anótalo
y déjalo para después: el objetivo de este seed es la validación de volumen.

## Entregable

Un informe con la tabla de métricas rellena, comparada con las referencias, y el
veredicto: **el pipeline aguanta 30 minutos / no aguanta por X**. Si aguanta, actualiza
`CLAUDE.md` marcando el hito y `.claude/rules/sessions-log.md` con la entrada
correspondiente. Si aparecen incidentes, añádelos a `.claude/incident-ledger.md`.
