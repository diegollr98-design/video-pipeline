# SEED — Arreglar lo que destapó la primera producción real de 30 min

> PASO 0 OBLIGATORIO: invoca /seed-review sobre este SEED antes de tocar nada.

## Por qué existe este SEED

El 10-ago-2026 se corrió por primera vez el pipeline a escala real (33,4 min de gameplay).
Produjo `output/video_001_final.mp4` (29,85 min): **un vídeo completo, reproducible y NO
publicable**. Tiene basura del modelo en pantalla y cuatro tramos con el subtítulo un segundo
por detrás de la voz.

Nada de eso lo vio el gate `/eval`, que corre sobre un clip de 3 min y dio verde
(media 0,072 s, sesgo −0,067 s). **Esa es la lección central de este traspaso: el fixture de
3 minutos no puede ver esta clase de fallo**, porque el bug vive en las ventanas de anclaje y
a 3 min solo hay 12 ventanas frente a las 214 de producción.

Contexto completo: `.claude/incident-ledger.md`, entradas `BASURA-01`, `ANCLA-01`, `INSTR-02`
(y las seis anteriores del mismo día). `CLAUDE.md` y `sessions-log.md` v0.2 describen la sesión
que las generó — trátalos como testimonio de esa sesión, no como verdad revelada.

---

## ESTADO EXACTO DEL REPO (verificado al escribir esto)

| Cosa | Estado |
|---|---|
| `pool/` | **VACÍO** — `take_chunk` lo consumió. Otra corrida larga exige re-ingerir (~23 min) |
| `input/` | `2026-01-27 21-29-26.mp4`, 13,8 GB, **2013,5 s = 33,6 min**. Es 100% gameplay, 1 segmento |
| `output/` | `video_001_final.mp4` (29,85 min, 3,19 GB) + thumbnail + title. **NO publicable** |
| `shorts_tiktok/` | 50 shorts + sus 50 títulos, de la misma corrida |
| `temp/` | **307 ficheros CONSERVADOS** con `--keep-temp`. Aquí está toda la evidencia: `video_001_subs.ass`, `video_001_story.txt`, `video_001_audio.mp3`, `video_001_audio_mixed.mp3` y los `short_*` |
| `data/eval/` | `2026-08-10.json` (baseline del fixture de 3 min) y `2026-08-10-produccion-real.json` (la corrida larga, **con números inflados**, ver bloque A) |
| **Disco** | **16 GB libres de 476 (97% lleno)**. Es la restricción más dura de esta sesión |
| Cuota OpenRouter | 10 créditos, **1000 peticiones/día**. Los modelos `:free` NO consumen saldo (verificado: `total_usage` no se movió en 58 peticiones). Verifica siempre con `GET /api/v1/credits`, nunca con `/api/v1/key` |
| Coste de una corrida larga | **53 peticiones** (3 bloques + 50 shorts) y **~2h40** de reloj (23 min ingesta + ~20 min vídeo + ~95 min los 50 shorts) |

**Transcripción de Whisper ya cacheada** del vídeo largo, para no repetir 10 min de CPU:
`C:/Users/diego/AppData/Local/Temp/claude/c--Users-diego-Desktop-YOUTUBE/bb100709-e783-45de-9c7e-850a85d1fe08/scratchpad/whisper_video001.json`
(lista JSON de `[palabra, start_segundos]`). Si ya no existe, se regenera con `scripts/eval_sync.py`.

---

## ORDEN OBLIGATORIO

Los bloques **no son independientes**. El A arregla el instrumento con el que se valida el B.
Hacer B primero significa medir el fix con una regla torcida. **En serie, y en este orden.**

---

### BLOQUE A — Arreglar el medidor ANTES de medir nada (0 peticiones)

`scripts/eval_sync.py` empareja ASS contra Whisper con **`difflib` global sobre 5000+ palabras**.
En zonas donde el texto se repite —estas historias enumeran hechos ya narrados— engancha la
ocurrencia equivocada y **fabrica retraso que no existe**. Medido:

| zona | lo que dijo el emparejado global | transcripción fresca de 40 s |
|---|---|---|
| 1245-1285 s | desfase | **−0,080 s** (sana) |
| 1585-1625 s | +1,1 s | **−0,080 s** (sana) |
| 605-645 s | racimo | **−0,080 s**, solo 1 palabra de 79 real |
| **1000-1040 s** | +1,05 s | **+1,050 s, 90 de 125 palabras >0,5 s** (REAL) |
| control 300-340 s | — | **−0,110 s** (sana) |

Inflaba la media global de 0,072 a **0,153 s** y volteaba el sesgo de −0,067 a +0,003 s.
Ese es el número que hay en `data/eval/2026-08-10-produccion-real.json`: **está mal, no lo uses
de baseline**.

**Qué hacer:** emparejado **local por ventanas** (p. ej. anclar por bloques de ~60-100 palabras,
o emparejar dentro de cada frase). Criterio de aceptación, medible sin gastar cuota:
- sobre `output/video_001_final.mp4` + `temp/video_001_subs.ass`, las zonas 300-340, 605-645,
  1245-1285 y 1585-1625 deben salir **sanas** (mediana ≈ −0,08 a −0,11 s);
- la zona **1000-1040 debe seguir saliendo rota** (≈ +1,05 s). Si el nuevo emparejado la
  "arregla", lo que has hecho es cegar el medidor, no arreglarlo.
- Vuelve a escribir el JSON de la corrida larga con los números corregidos.

⚠️ Whisper coloca la primera palabra de cada fragmento en `t=0` local: **descarta los primeros
3 s** de cualquier fragmento que transcribas por trozos.

---

### BLOQUE B — El desfase de ~1 s (causa raíz YA localizada y validada)

**No hay que diagnosticar: hay que arreglar y verificar.** Un `bug-hunter` lo localizó y el
orquestador lo validó por ejecución.

**Causa raíz:** `modules/tts_engine.py:458` calcula la traslación de toda la ventana de anclaje
con **una sola palabra**: `offset = s_start - w_first`. Si `stable-ts` mete esa primera palabra
**dentro del silencio anterior**, ese silencio se convierte en retraso **rígido** para las hasta
~95 palabras de la ventana. Huella: `albaceazgo` es una de solo **2 palabras en 5290** que tocan
el clamp `end = min(w.end, w.start+1.5)` de `tts_engine.py:273`.

**Descartado por medición** (no lo repitas): edge-tts y su troceo a 4096 bytes (214/214 anclas
coinciden a ±0,5 ms, mismo tamaño en bytes, la compensación CBR de edge-tts 7.2.8 no deriva);
la composición (el MP4 son los onsets del mp3 **menos 0,100 s exactos**, sin desviación);
`subtitle_builder` (ASS vs SRT, máx 9 ms).

**No es deriva:** son **4 ventanas discretas** (~4-5% de las palabras). Detector estructural sin
Whisper — paso de la 1.ª a la 2.ª palabra de cada ventana, n=210: mediana 0,140 s, p90 0,360,
p95 0,540. Solo se salen estas:

```
2.109 s  'testamento,'  t= 688.45   94 palabras
1.983 s  'El'           t= 606.48    6 palabras
1.699 s  'albaceazgo'   t=1005.40   95 palabras
1.481 s  'La'           t=1591.99    4 palabras
0.959 s  'Javier,'      t= 149.10   56 palabras   (limítrofe; puede ser pausa legítima)
```

**Fix propuesto** (en `_validate_and_fix_alignment`, antes de calcular `w_first`): si el paso de
la 1.ª a la 2.ª palabra supera un umbral, adelantar el resto de la ventana ese exceso.
`PASO_MAX_ANCLA = 0.55` toca también la limítrofe; `1.20` toca solo las cuatro catastróficas y
deja ~0,8 s de residuo. **Decide con medición, no por gusto.** La asimetría juega a favor:
pasarse adelanta el subtítulo, y adelantado es el lado correcto por diseño (`-itsoffset -0.10`).

Complemento de 1 línea en `tts_engine.py:273`, que hoy solo acota el `end` —justo el campo que el
anclaje **no** usa—: `start = max(w.start, w.end - 1.5)`.

**GEMELO EN SHORTS — revísalo (regla 11).** `shorts_generator.py:295` llama a `run_tts`, o sea a
la misma función. Un short son ~200 palabras = 1-3 ventanas; si la mala es la única, **el short
entero** queda detrás, y el error sobrevive al `/1.5` como ~0,7 s. No se pudo aislar en los
`temp/short_*_subs.srt` porque ahí no están los `SentenceBoundary`: hay que capturarlos.

**Verificación (esto es lo caro y no se puede saltar):**
1. Barato y primero: el **detector estructural** sobre el nuevo `.ass` — 0 ventanas por encima
   del umbral.
2. Concluyente: fragmentos frescos de 40 s en 605-645, 685-725, 1000-1040 y 1585-1600. La zona
   1000-1040 debe bajar de **+1,06 s a ≈ −0,1 s**.
3. **El fixture de 3 min NO vale para esto.** Verificar de verdad exige otra corrida larga:
   53 peticiones y ~2h40. Presupuéstalo antes de empezar.

---

### BLOQUE C — `target_wpm`: de 160 a ~177 (0 peticiones para decidirlo)

Medido en la corrida real: 5290 palabras / 29,85 min = **177,2 wpm**. Con `target_wpm: 160` el
ratio vídeo/chunk salió **0,893** → 3,6 min de gameplay desperdiciados.

Historial de este knob, que es una lección en sí mismo:
- `150` → calibrado a ojo
- `195` → calibrado sobre clips de **3 min** (régimen equivocado: ahí manda `_truncate_to_words`)
- `160` → recalibrado el 10-ago sobre `pipeline.log` con **n=1** en el régimen largo (160,6 wpm)
- ahora hay **n=2**: 160,6 y 177,2

**No lo cambies otra vez sobre n=2 sin pensarlo.** La pregunta honesta es si la velocidad depende
del contenido (comas, longitud de frase) más que de una constante. Si lo subes, comprueba que el
modelo sigue entregando el 99% del objetivo: en esta corrida pidió 5345 y entregó 5290, pero hay
precedentes de 37-55% de cumplimiento en textos largos.

Y **reporta el efecto en cuota**: `target_wpm` ya NO dimensiona los shorts (se separó en
`shorts.narration_wpm`), pero cambia el número de bloques de historia.

---

### BLOQUE D — Variedad de los 50 shorts (0 peticiones, todo en disco)

Hay **50 títulos reales** en `shorts_tiktok/*_title.txt` de una sola tanda, generados con la
ventana anti-repetición ampliada de 12 a 40. Es la primera vez que existe una cadena tan larga.

**Ojo con la métrica:** la similitud léxica de títulos con `difflib` **no discrimina** — medido:
shorts buenos 0,376 de media, "misma historia reescrita con otras palabras" **0,542**, shorts
rotos con el mismo argumento 0,808-0,906. Es decir, el proxy solapa. Si vas a dictaminar
variedad, necesitas otra señal (¿parentesco + objeto en disputa + desenlace, extraídos por LLM?)
o el juicio de Diego leyendo los 50 títulos.

Pregunta concreta que sí se puede responder: **¿se degrada a partir del short 40**, cuando los
primeros empiezan a salir de la ventana?

---

### BLOQUE E — El gate no puede ver lo que rompe la producción

`/eval` corre sobre 3 min / 12 ventanas de anclaje y dio verde a un vídeo que a escala real está
roto. Cualquier arreglo del bloque B es invisible para él.

Opciones a evaluar (no está decidido cuál):
- un **segundo fixture largo** (¿10-15 min?) que dé suficientes ventanas sin costar 2h40;
- añadir al gate el **detector estructural** del bloque B (paso 1.ª→2.ª palabra), que cuesta 0 y
  caza exactamente esta clase de fallo sin necesidad de audio;
- aceptar que hay una clase de fallo que solo se ve en producción y definir cada cuánto se corre.

⚠️ `.claude/skills/eval/SKILL.md` dice **"nunca toques `test_e2e/config.yaml` para que el gate
apruebe"**. Sigue vigente. Cambiar el fixture para AMPLIAR cobertura es otra cosa, pero dilo
explícitamente y que lo apruebe Diego.

---

### BLOQUE F — Pendiente heredado (aplazado a propósito)

`prompts/short_story.txt` **no recibe** las directrices de competencia; solo se inyectan en
`reddit_story.txt`. Los shorts ignoran el análisis de competencia. Aplazado por Diego el
10-ago-2026; sigue abierto.

---

## REGLAS DE ESTA SESIÓN

- **En serie.** `pipeline.log` es ruta fija (`main.py:30`), `cleanup_temp` hace `rmtree` del temp
  compartido (`utils.py:76`) y `assets/.tint_index` es read-modify-write sin lock. Dos corridas a
  la vez se corrompen en silencio.
- **`--keep-temp` es obligatorio** en cualquier corrida que vayas a medir. Sin él se borra el
  `.ass` y el `_story.txt`, que son justo lo que se mide.
- **Prohibido `python main.py` sin `--config`** si no quieres ingerir los 13,8 GB otra vez.
- **Intocables:** `input/`, `test_e2e/clip.mp4`, `test_e2e/output/`, `test_e2e/shorts/`,
  `data/`. Nada está en git (`.gitignore`) y un borrado es permanente.
- **`temp/` de hoy es evidencia**, no basura: contiene el `.ass` y el guion del vídeo roto. Si
  necesitas espacio, muévelo, no lo borres.
- **Disco al 97%.** Antes de una corrida larga, libera: los 50 shorts (~2,5 GB), el
  `video_001_final.mp4` (3,19 GB) y `temp/` (varios GB) son candidatos **con el OK de Diego**.
- `git commit -m "pre-fix ..."` antes de editar. Y **no uses `git add -A`**: en la sesión anterior
  se coló `PORTAFOLIO/*.html`. Añade por ruta explícita. `docs/video_guion.md` está modificado de
  antes y no es de este trabajo.
- **Verificación por EJECUCIÓN.** Pega la salida real del comando.

## TRAMPAS DE MEDICIÓN YA PAGADAS (no las repitas)

En una sola sesión, tres instrumentos propios dieron números falsos. Los tres eran plausibles y
ninguno se había contrastado contra un caso conocido antes de usarlo:

1. **`exceso = nº silencios − nº signos de puntuación`** para comparar dos versiones del inserter
   de comas: mete la variable manipulada en el denominador. Dijo "5 vs 10" donde los silencios
   crudos eran 30 vs 31.
2. **Hueco entre subtítulos como `siguiente.start − previa.start`**: eso es la DURACIÓN de la
   palabra, no el silencio. Reportó 73 pausas fuera de puntuación donde había 1.
3. **`difflib` global sobre 5000 palabras** (bloque A): fabrica retraso donde el texto se repite.

**Regla que sale de ahí: antes de usar una métrica para juzgar, pásala por un caso cuyo resultado
ya conoces.** Y desconfía de un número que cambia justo en la dirección que esperabas.

Además, las de siempre: fixture con texto repetido = medición falsa; `--no-shorts` oculta una
clase entera de fallos; `--dry-run` valida la historia, no la cadena.

## ENTREGABLE

Por bloque: qué se cambió, la **salida real** del antes/después, y qué quedó sin resolver.
Entrada factual en `.claude/incident-ledger.md` por cada defecto nuevo — **el retro no escribe
reglas, solo `/optimize` promueve**. Y el gasto de peticiones por vídeo recalculado si tocaste
algo que lo mueva.

"No concluyente" es una respuesta válida y preferible a inventar una recomendación.
