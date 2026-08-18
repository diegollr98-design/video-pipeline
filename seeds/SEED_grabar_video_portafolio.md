# SEED — Desbloquear la grabación del vídeo de YOUTUBE PIPELINE (portafolio)

> PASO 0 OBLIGATORIO: invoca /seed-review sobre este SEED antes de tocar nada.

**Objetivo del usuario, literal:** *"Hoy quiero grabar ya el vídeo para el guion de mi portafolio."*
Todo lo que no sirva a eso HOY es ruido. **No abras ciclos de fix largos.**

**Guion a grabar:** `C:\Users\diego\Desktop\portafolio\.tmp\guiones\YOUTUBE-PIPELINE-guion-video.md`
(325 líneas, 11 bloques, 5:28). Su pre-flight son las líneas 73-125.
**Repo que se graba:** `C:\Users\diego\Desktop\YOUTUBE` (rama `feat/competencia`, HEAD `bb341eb`).

---

## 🔴 U0 · [GATE-06] dispara un FALSO NEGATIVO justo en el CLÍMAX (§8)

**Es lo más urgente de todo el seed.** Cadena verificada:
```
§4 graba el clip de 200 s -> 653 palabras (a target_wpm=196)
num_blocks = max(1, (653+1999)//2000) = 1   -> UN bloque
audit_run.cierre_narrativo() decide si hay desenlace BUSCANDO EN pipeline.log
que se pidiera el bloque de cierre. El camino de un bloque escribe el
desenlace DENTRO de la misma llamada y no emite esa linea.
   -> "FALLA cierre narrativo" sobre un video que SI tiene final
```
El suelo de 2 bloques lo quito **`8e522fa` (fix de [TRUNCA-01], 14-ago)**, DESPUES del ultimo `/eval`
verde — que corrio con "~2 bloques". **Ese verde no representa lo que pasaria hoy en camara.**

**Por que importa tanto:** el §8 es el CLIMAX y graba `/eval` **ejecutandose en camara**, con el
caption *"Si un cambio empeora el baseline, no se cierra. No es un aviso: es un no."* Filmarias el
gate cantando un fallo falso en el beat que argumenta que el gate no miente.

**Arreglo (pocas lineas):** que `cierre_narrativo()` reconozca el desenlace **escrito en linea**, en
vez de depender de una linea de log que el camino nuevo ya no emite. Es la misma clase que [GATE-05b]:
la capacidad cambia en un sitio y el check que la observa se queda anclado a la senal vieja.

**Verificado que NO aparece en §5:** la tarjeta de Resultados vive en `tab_resultados`
(`dashboard.py:484`) y el badge rojo del veredicto se pinta en `tab_subir` (`dashboard.py:903`), que
el guion no graba. Resultados es seguro.

### U0b · [TRUNCA-02] — riesgo bajo pero real en la misma toma
En produccion real no se manifiesta (80% de coherencia titulo/cuerpo); **lo fabrica el fixture de
3 min**, que es justo el que usa §4. El video producido en camara puede prometer en el titulo algo que
no narra, y §5 filma el titulo completo en la tarjeta. Plano de ~5 s: riesgo bajo, pero no es cero.

---

## 🟠 U1-U3 · el pre-flight del guion ya NO funciona

Tres desajustes entre lo que el guion manda y lo que el repo es HOY. **Los tres se arreglan en
minutos, y sin ellos la toma de §4 no arranca o graba un dato falso.** Verificados por ejecución.

### U1 · La corrida en vivo de §4 NO arrancaría (bloqueante duro)
El pre-flight dice: *"Copia `test_e2e/input/clip.mp4` → `input/`"*. Pero el 15-ago `input/` cambió de
disco:
```
config.yaml:   input_dir: "D:/YOUTUBE_media/input"
C:\...\YOUTUBE\input\    -> 0 ficheros (vacío)
D:\YOUTUBE_media\input\  -> 1 fichero (la grabación de 12,91 GB)
```
Copiar a `input/` como dice el guion **deja el clip donde el pipeline ya no mira**: el desplegable de
🎬 Operar no lo listaría y §4 no se puede grabar.
**Arreglo:** copiar a `D:/YOUTUBE_media/input/` y corregir esa línea del pre-flight.
⚠️ `temp_dir` también se movió (`D:/YOUTUBE_media/temp`). Motivo en [DISCO-01]: la ingesta escribe una
copia del vídeo a tamaño completo y pide **~17 GB**, no los ~12 que decía la doc.

### U2 · §7 grabaría un número que CONTRADICE su propio caption
El beat de 4:05 se para en *"Palabras por minuto (WPM): **160**"*, con el caption
`195 → 160 wpm · recalibrado` y un párrafo entero: *"este número es mi favorito porque estuvo mal"*.
```
config.yaml:128   target_wpm: 196     <- lo que saldrá EN PANTALLA
```
La pestaña ⚙️ Config lee `config.yaml`, así que **en cámara se verá 196 mientras la voz dice 160**.
La historia del beat es real ([WPM-01]) pero se quedó a mitad: el valor pasó por
**150 → 195 → 160 → 187 → 196**, y el último salto fue al meter el partidor de frases
(`sessions-log` v0.7: recalibrado sobre el AUDIO, n=2 → 187,3 y 188,0).

**Decisión de Diego, no del ejecutor:** (a) reescribir el beat con la historia completa —que es MÁS
fuerte: el número se movió cuatro veces y cada movimiento tuvo una medición detrás—, o (b) elegir otro
mando para ese beat. **NO bajes `target_wpm` a 160 para que cuadre con el guion**: es superficie
sensible, y sería maquillar la realidad para la cámara — justo lo contrario de lo que el vídeo predica.

### U3 · §5 dice "14/14 shorts" y hoy hay 54
```
shorts_tiktok/ -> 54 ficheros .mp4     (el guion dice "hoy son 14/14")
output/        -> 3 vídeos: 1,45 / 1,47 / 1,87 GB   (26,4 · 26,5 · 33,6 min)
```
El caption ya avisa `[se lee de la toma]`, así que **no es fatal** — pero el texto del beat dice 14 y
el pre-flight dice *"2026-08-11: 1 vídeo + 14 shorts"*.
⚠️ Y la bandeja enseña ahora **TRES** tarjetas de vídeo, no una: el pre-flight solo contemplaba dos.

---

## 🟡 [ANCLA-07]: NO te bloquea para grabar, pero decide qué haces con él

**El vídeo de producción más reciente está marcado NO PUBLICABLE por el propio auditor:**
```
output/video_003_audit.json -> ok:false
  peor tramo -1.640s en t=161.94s
  5.8s de voz sin subtítulo (peor 1.48s en t=162.2s)
  racha de 20 palabras ilegibles
```
Medido sobre el `.ass`: **33 cues de 6203 (0,5%)**, en dos rachas (`t=161,04` con 20 palabras y
`t=166,78` con 8) más huecos de 3,82 s y 2,48 s. **El 99,5% del vídeo está sano.**

**Por qué NO bloquea la grabación** (compruébalo en el careo de cierre, no lo des por hecho):
- §5 (3:06) manda abrir el vídeo y ver fotograma a fotograma **un punto con voz**. Vale cualquiera de
  los 33,5 min sanos. **Evita t=161-173.**
- §8 (CLÍMAX, 4:20) graba `/eval` sobre `test_e2e/`, **no** el auditor sobre producción. El último
  `/eval` (`data/eval/2026-08-14-postfix-ancla06.json`) dio **PASA**.
- Ningún beat filma la cola de subida ni el veredicto de producción.

**Pero hay un problema de VERDAD que Diego debe decidir**, y es del tipo que su propio portfolio
presume de no cometer: el vídeo afirma que el pipeline entrega vídeo publicable, y hoy **ninguno de
los tres tiene veredicto verde válido**:
```
video_001: sin auditar (no existe el veredicto)
video_002: veredicto CADUCADO (emitido sin huella de auditor) -> [AUDIT-01]
video_003: rojo por [ANCLA-07]
```
Y **`video_002` no se puede re-auditar**: sus artefactos (`.ass`, `_story.txt`) ya no están en disco.
Solo `video_003` los conserva, en `D:/YOUTUBE_media/temp/`.

Opciones, de más barata a más cara:
1. **Grabar igual**, evitando la zona rota y sin filmar veredictos de producción. Coste 0. Riesgo: el
   vídeo del portfolio enseña un pipeline cuyo último output está en rojo si alguien lo audita después.
2. **Arreglar [ANCLA-07] y re-componer `video_003`.** Los artefactos están, pero **el chunk de gameplay
   se borró al terminar bien**, así que hay que re-ingestar (~16 min) antes de componer.
3. **Corrida nueva completa** (~2h40, ~55 peticiones). Solo si sobra el día.

---

## 📋 Camino crítico sugerido (ordenado por coste, no por importancia)

0. **U0** — [GATE-06], para que el clímax no grabe un falso negativo. *(pocas líneas)*
1. **U1** — copiar el clip a `D:/YOUTUBE_media/input/` y corregir el pre-flight. *(5 min)*
2. **U3** — actualizar las cifras del guion o marcarlas como "se lee de la toma". *(5 min)*
3. **U2** — decisión de Diego sobre el beat de WPM. *(su llamada; no la ejecutes solo)*
4. **Ensayo en seco del pre-flight entero** antes de encender la cámara: bajar
   `target_duration_min` de 1200 a 150 en ⚙️ Config, comprobar que el clip aparece en el desplegable
   de 🎬 Operar, y **restaurar 1200 al terminar** — el propio guion lo marca con ⚠️: es superficie
   sensible y dejarla en 150 cambia la producción real en silencio.
5. Solo si Diego lo pide: [ANCLA-07].

---

## ⚠️ Trampas ya pagadas — no las repitas

1. **No bajes `target_wpm` para que cuadre con el guion.** El guion se ajusta a la realidad, no al
   revés. Toda la tesis del vídeo es que las cosas se miden, no se maquillan.
2. **La ruta del fixture es `test_e2e/input/clip.mp4`**, con `input/` en medio. La lista de "nunca
   borrar" decía `test_e2e/clip.mp4` —que NO existe— en 4 sitios; corregidos 3, y `CLAUDE.md:49`
   sigue mal por ser conjunto inmutable [DOC-02].
3. **El presupuesto de la toma son ~7 peticiones** (2 bloques + 5 shorts sobre el clip de 200 s) de
   1000/día. **Verifica el tope con `GET /api/v1/credits`**, nunca leyéndolo de un `.md` [DOC-01].
   El proveedor del modelo se cayó el 15-ago (504/404) y tumbó una corrida entera: si pasa en cámara,
   **corta y re-toma**. Ya hay cadena de modelos de reserva [MODELO-01], pero se ve en el log.
4. **Antes de asignar un id nuevo en el ledger**, `grep -oE "^- \[PREFIJO-[0-9]+\]"` y coge el
   siguiente: tres sesiones paralelas ya colisionaron uno [LEDGER-01].
5. **Un `git checkout` se lleva el trabajo sin commitear de otras sesiones** [PARALELO-01].
   Comprueba `git status` antes de cambiar de rama.

## Fuera de alcance
`/optimize` (36 incidentes del 14-15 ago sin promover, `sessions-log.md` en 224 líneas con tope de
100), la subida a YouTube, y cualquier fix de pipeline que no desbloquee la grabación de hoy.

Entrada factual en `.claude/incident-ledger.md` por cada defecto REAL que aparezca.
**El retro no escribe reglas, solo `/optimize` promueve.**
