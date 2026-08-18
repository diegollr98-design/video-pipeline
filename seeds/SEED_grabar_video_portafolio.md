> ## ⚠️ EJECUTADO Y CORREGIDO EL 2026-08-18 — NO LO VUELVAS A EJECUTAR TAL CUAL
>
> `/seed-review` TIER PANEL (1 agente **ciego** + 3 críticos). Veredicto: **✏️ CON EDICIONES**.
> Sus cinco diagnósticos (U0, U1, U1b, U2, U3) quedaron **CONFIRMADOS por ejecución** — el agente
> ciego, sin ver este SEED, llegó a los cinco por su cuenta. Lo que el panel tumbó fue su **plan**:
>
> 1. **Premisa FALSA que sostenía su análisis de [ANCLA-07]** — *"ningún beat filma la cola de subida
>    ni el veredicto"*. §10 del guion (5:10, **★ del corte hero**) es literalmente *"Tab 📤 Subir …
>    el plano es el veredicto del auditor junto al vídeo"*. Ver [SEED-03] del ledger.
> 2. **Su paso 0 destruía su propio mejor plano.** `_HUELLA_FUENTES` incluye `audit_run.py`: tocarlo
>    caduca los veredictos. Se arregló y **se re-auditó `video_003`** para devolverle uno válido.
> 3. **Arreglar U0 NO pone verde el clímax.** La corrida real que se grabaría hoy termina con **dos**
>    FALLA: `cierre narrativo` (falso, ya arreglado) **y** `coherencia título/cuerpo 29%`
>    ([TRUNCA-02], **verdadero**). El SEED lo clasificó como *"riesgo bajo, plano de ~5 s"*.
> 4. **U1b es evitable y dañino.** Su plan B (*"grabar §2 después de §4"*) está roto: `take_chunk`
>    **borra** del pool lo que consume. Y pre-ingestar duplica el chunk (191→382 s, 9 shorts, ~1h20).
>    **§2 se graba con el pool vacío**: su propia caption ya narra el déficit.
> 5. **Su paso 4 rompe `config.yaml`** — guardar desde ⚙️ Config borra los ~70 comentarios de
>    calibración, y el `.bak` se sobrescribe en el segundo guardado. Ver [CONFIG-01].
>
> **Huecos que el SEED no vio:** §6 filma un expander que no existe · §4 2:05 tiene un **segundo**
> overlay de WPM falso · ningún clip disponible tiene pausas, así que el caption ★ de 1:45 filmaría
> `Frames gameplay: 20/20` · la corrida de §4 borra `D:/temp` ([GATE-08]).
>
> **Datos suyos que resultaron falsos:** `HEAD bb341eb` (son 4 commits atrás) · *"653 palabras"* (el
> chunk real son 191 s → **623**) · *"~7 peticiones, 2 bloques + 5 shorts"* (real: **5**, 1 bloque +
> 4 shorts — se contradice con su propio U0) · *"150 → 195 → 160 → 187 → 196"* (real, verificado en
> `git log -G`: **195 → 160 → 187 → 199 → 196**; el 150 nunca estuvo en `config.yaml`).
>
> **Lo hecho:** [GATE-06] arreglado y medido A/B · `video_003` re-auditado · artefactos preservados en
> `D:/YOUTUBE_media/_preserve_video_003/` · clip copiado a `D:/YOUTUBE_media/input/` · **el guion del
> portafolio corregido en 15 sitios**. Lo que queda es grabar: ver el checklist de la sesión.

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

### U1b · §2 filmaría lo CONTRARIO de lo que narra: el pool está VACÍO
El beat de 0:45 se para en *"🎮 Pool de gameplay … el mensaje **✅ Hay material suficiente para
producir**"*. Medido ahora mismo con el código del dashboard:
```
archivos en el pool: 0      minutos totales: 0.0      minimo para producir: 20 min
-> el dashboard dira: "NO hay material suficiente"
```
El pool se vació con las corridas del 15-ago (la última consumió `pool_0001` y la recodificación
truncada `pool_0002` quedó apartada como `.CORRUPTO`, fuera del glob `*.mp4`).

**Y hay un conflicto de ORDEN que el pre-flight no contempla:** §2 quiere un pool ya lleno, pero lo
que lo llena es la ingesta… que es justo lo que graba §4. Si se filma en orden, §2 sale vacío.
**Secuencia correcta:**
1. copiar el clip a `D:/YOUTUBE_media/input/` (U1);
2. bajar `target_duration_min` de 1200 a **150** en ⚙️ Config (200 s de clip ≥ 150 s → "hay
   material"; con 1200 seguiría diciendo que no aunque el pool tenga el clip);
3. **ingestar una vez ANTES de grabar**, para que §2 tenga qué enseñar;
4. grabar §2 … y luego §4, cuya corrida en vivo ingesta otra copia.
Alternativa: grabar §2 **después** de §4 y montarlo en su sitio.

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
- §8 (CLÍMAX, 4:20) graba `/eval` sobre `test_e2e/`, **no** el auditor sobre producción, así que
  [ANCLA-07] no sale ahí. ⚠️ Pero **§8 tiene su propio problema, y es U0**: ese `/eval` cantaría el
  falso negativo de [GATE-06]. El PASA de `data/eval/2026-08-14-postfix-ancla06.json` corrió con
  "~2 bloques", **antes** de que `8e522fa` quitara el suelo: no representa lo de hoy.
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
1. **U1 + U1b** — copiar el clip a `D:/YOUTUBE_media/input/`, bajar `target_duration_min` a 150 e
   **ingestar una vez** para que §2 tenga pool que enseñar. Corregir esas líneas del pre-flight. *(15 min)*
2. **U3** — actualizar las cifras del guion o marcarlas como "se lee de la toma". *(5 min)*
3. **U2** — decisión de Diego sobre el beat de WPM. *(su llamada; no la ejecutes solo)*
4. **Ensayo en seco del pre-flight entero** antes de encender la cámara: bajar
   `target_duration_min` de 1200 a 150 en ⚙️ Config, comprobar que el clip aparece en el desplegable
   de 🎬 Operar, y **restaurar 1200 al terminar** — el propio guion lo marca con ⚠️: es superficie
   sensible y dejarla en 150 cambia la producción real en silencio.
5. Solo si Diego lo pide: [ANCLA-07].

---

## ✅ Verificado sano (no lo vuelvas a comprobar, no gastes tiempo)
- **El dashboard arranca limpio**: `AppTest` → **0 excepciones**, **8 pestañas** (el guion dice 8: correcto).
- Los 3 `st.error` que aparecen son los veredictos de los vídeos y viven **todos en 📤 Subir**, que el
  guion NO graba. 🖼️ Resultados está limpio.
- **§6 Competencia tiene datos**: `competitors.json` (380 KB), `competition_report.json`,
  `competition_advice.json`. La tabla y el veredicto se pueden filmar.
- **§5 tiene sus artefactos**: 3 miniaturas + 3 títulos en `output/`.

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
