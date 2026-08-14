# Sessions Log — YOUTUBE

Bitácora por hito. **Más reciente arriba.** Mantener ≤ 100 líneas: las entradas viejas se archivan en
`docs/sessions-log-archive.md` (fuera del contexto) vía `/optimize` Paso 5.

**Plantilla de entrada:**
```
## vX.Y — fecha — <título> <✅|🔴>
**Qué se hizo:** ...
**Incidentes:** [id] del ledger, si los hubo
**Verificación:** qué se EJECUTÓ y qué demostró (salida real, no "reportó que OK")
**Pendiente:** ...
```

---

## v1.0 — 2026-08-14 — Competencia: el subsistema no llegaba a los shorts… ni había llegado NUNCA a nada 🔶
**Qué se hizo:** `/seed-review` (1 ciego + 3 críticos) sobre `SEED_C_competencia.md`. El agente **ciego**
destapó lo que el SEED daba por sentado: `apply_to_prompt` **no se había ejecutado jamás** — no era "el
98% de los artefactos se queda fuera", era el **100%**. El SEED encuadraba el hueco como "replicar al
gemelo de shorts" un mecanismo que funcionaba; no funcionaba porque nadie lo había llamado. Veredicto
⛔ PARAR; Diego aprobó reordenar: **bugs → medir → decidir si inyectar**. Cerrado: round-trip byte a
byte [COMPET-02], `strip_injection` que destruía el prompt [COMPET-03], contabilidad de cuota
[QUOTA-01], perfil de directrices propio para shorts, y disparo programado del escaneo (nunca de la
producción: la subida está gateada por decisión de Diego, así que programarla no da autonomía).
**Incidentes:** [COMPET-01..04] [QUOTA-01] [INSTR-07] [PARALELO-01] · destapados por el `output-audit`
y **sin dueño**: [TRUNCA-01] [SHORTVID-01] [APERTURA-01] [GATE-05b].
**Verificación:** round-trip binario `5094→5171B (CRLF 0→77)` **→ idéntico**, en LF y en CRLF; sobre el
fichero real, quitar devuelve el sha256 exacto y el `git diff` son **18 inserciones, 0 borrados** (antes
habrían sido 40 líneas reescritas). Cuota: con un 404 inyectado, **401 unidades gastadas y 0
registradas → ahora persistidas**; carrera escaneo↔subidor reproducida, se perdían **1650** unidades y
el paso 4 del protocolo del SEED **decía CUADRA**. Escaneo real disparado **desde el Programador**:
304,6 s, código 0, cuota **0 → 457 (delta exacto)**, 221 → 232 canales; el `PYTHONUTF8=1` era necesario
de verdad (el log imprime `→` y `¿` bajo cp1252). Debate real: el guardia **reintentó 2 veces** antes de
devolver las secciones de short. A/B de shorts en **3 corridas, 55 generaciones**, instrumento calibrado
contra casos conocidos. `/eval`: medio 0,080 s / máx 0,430 / sesgo −0,068 / cobertura 98,6%, con
**control del instrumento exacto** (re-medir `video_006` reproduce su baseline al dígito).
**Lo que esto enseña:** (a) **el efecto que casi cierra el track no replicó** — el desplome del "dato
duro" daba p=0,014 en una corrida y p=1,00 en la réplica, porque el control osciló 0/10 → 6/12 → 2/12
con el prompt idéntico: recomendé "no aplicar" sobre una falsa alarma y la réplica lo corrigió; (b)
**el fix introdujo su propio defecto y lo cazó su test** [COMPET-04]: `_path_for` daba a "short" una
ruta por defecto y reescribió el prompt de PRODUCCIÓN desde un test; (c) mi instrumento del A/B
**emitió veredicto sobre el conjunto vacío con exit 0** [INSTR-07]; (d) el gate es **ciego a este
cambio por construcción** — `trend_advisor`/`competitor_scout` solo viven detrás de `main.py:405`.
**Pendiente:** **[TRUNCA-01] es lo más grave y no tiene dueño**: `video_007` promete en su TÍTULO
(y por tanto en la miniatura y la intro) *"el notario descubrió la coacción y anuló todo"* y **no lo
narra jamás** — 1688 palabras del cuerpo descartadas, `anul-` solo aparece dentro del título; el gate lo
aprobó porque ningún check lee el warning del truncado. Con él, [SHORTVID-01] y [APERTURA-01]. El
prompt LARGO sigue **sin inyectar** (nunca lo he medido); solo se aplicó al de shorts. El guardia de
título de short (acepta 8-45 donde el prompt pide 10-18) y el 75% de la historia larga que no ve las
directrices (`_generate_continuation`) siguen abiertos, en ficheros de otro track.

## v0.9 — 2026-08-14 — Caza de bugs: cinco borrados silenciosos y un gate que daba la nota perfecta ✅
**Qué se hizo:** `/seed-review` (1 ciego + 3 críticos) sobre `SEED_D_caza_bugs.md`. El panel **tumbó
el orden de prioridades del SEED** (sesgo del retrovisor: su clase nº1 ya estaba cerrada, la nº6 era
terreno muerto) y, sobre todo, su **tabla de propiedad de ficheros**: 4 de los 7 bugs verificados
vivían en ficheros que el SEED prohibía o **no asignaba a nadie** — `modules/script_generator.py`
(1434 LOC) no aparecía en ninguna fila, y ahí estaba el peor bug de la sesión. Es el mismo mecanismo
por el que [BASURA-03] se coló 24 h antes. Diego desbloqueó `tts_engine` + `script_generator`.
Arreglado: **[META-01]** la limpieza de auto-anotación se aplicaba a la CONCATENACIÓN de bloques y
cortaba hasta el final; **[LIMPIEZA-01]** `_clean_speech_for_tts` borraba párrafos del cuerpo y el em
dash fusionaba palabras; **[GATE-04]** el auditor fallaba ABIERTO por tres caminos; y tres defectos
del gemelo de shorts. Reportados sin tocar: **[DRYRUN-01]**, **[SHORTNUM-01]**, **[WOOSH-01]**.
**Incidentes:** [META-01] [LIMPIEZA-01] [GATE-04] [DRYRUN-01] [SHORTNUM-01] [WOOSH-01] [SEED-02].
**Verificación:** todo A/B offline (misma entrada, dos códigos), **0 peticiones a OpenRouter**.
[META-01] con el guion real de 5307 palabras y el marcador de `video_004`: marcador en el bloque 1 →
**1300 palabras (76% borrado)**, acabando a mitad de escena sin desenlace y con `_detectar_meta_cola`
dando **limpio** después; con el fix, 3900 y desenlace intacto. [LIMPIEZA-01]: 41 → 24 palabras y
`'padre— era'` → `'padreera'`. [GATE-04]: conjunto vacío `EXIT=0` "sin defectos MEDIBLES" → `EXIT=1`
"no se ha auditado NADA"; instrumentos con ffmpeg caído daban **0,0 pausas por 1000 = la nota
perfecta**. Shorts: un título solo-puntuación indexaba `-1` y tiraba **todos** los subtítulos
(0 → 40 diálogos); un cuerpo sin puntuación daba un short de **6 palabras**. **No regresión medida en
las cuatro superficies**: sha256 idéntico en los 5 guiones reales, 54/54 títulos de shorts idénticos,
y en el vídeo real de 26,5 min la ÚNICA diferencia de 25 líneas de auditoría es la que se arregla.
`pyflakes` sin `undefined name` en todo el repo.
**Lo que esto enseña:** (a) **el peor bug estaba en el fichero que el SEED no asignó a nadie**, y la
regla "si es de otro track, repórtalo" ya había producido ese mismo fallo el día anterior; (b) el
SEED afirmaba que los otros tracks corrían "ahora mismo" y era **falso al arrancar** —Diego ya había
corregido esa frase en B y C y se dejó la D— pero **se volvió cierto a media sesión**: el track C tomó
el árbol de trabajo, así que la verificación hay que repetirla, no heredarla; (c) un informe de
subagente atribuyó el arreglo al `else` nuevo del truncado, y el A/B demostró que ese `else` es casi
inalcanzable: lo que salva el caso es la re-validación de longitud.
**Cierre (misma sesión, tras liberarse el árbol):** se corrió el `/eval` COMPLETO con shorts
(`video_006`, 6 peticiones, 0 reintentos) y el `output-audit`. Sincronismo **mejor que el baseline** en
todo salvo el máximo (medio 0,0749 → **0,0474**; p95 0,15 → **0,12**; sesgo −0,048 → **−0,016**; pausas
fuera de puntuación 4 → **1**; máximo 0,39 → 0,46), geometría correcta en los dos formatos, 28 de 28
silencios acústicos en puntuación, intro sin solape, y **guion 614 → audio 614 → subtítulos 586+28: no
se pierde una palabra**. El máximo NO es atribuible a este track: se verificó que
`_clean_speech_for_tts` produce salida **byte a byte idéntica a HEAD** sobre ese guion, así que el
texto que llega al alineador es el mismo ([GATE-03]: el fixture genera historia nueva cada corrida).
**Pero el `output-audit` tumbó la salida**: **[TRUNC-01]** el truncado descartó 2032 palabras (frases
9-48 de 52, el 77% del cuerpo) y las tres entidades que el TÍTULO promete —que van a la miniatura y a
la intro— aparecen **0 veces** en el cuerpo narrado; **[TITULO-03]** 2 de los 4 shorts narraban una
frase descabezada en el segundo 3; **[SHORTDUR-01]** los shorts duran 34-41 s contra los 60-90 s de la
spec, con `config.yaml` de producción idéntico; **[GATE-05]** el auditor medía el DIRECTORIO y cantó un
fallo inexistente mientras daba en verde los dos reales. **Arreglados [TITULO-03] y [GATE-05]** con A/B
sobre artefactos reales (los 2 shorts rotos pasan a mayúscula, los 2 sanos byte a byte idénticos; el
falso positivo del gate desaparece y los huérfanos se nombran). **[TRUNC-01] y [SHORTDUR-01] siguen
ABIERTOS.**
**2.ª vuelta — verificar rindió MÁS que cazar, y la cuenta es demoledora:** Diego preguntó si convenía
lanzar Sonnets a atacar los bugs restantes o a verificar los ya arreglados. Se eligió verificar: dos
`bug-hunter` autocontenidos, sin el contexto del orquestador y con el encargo de REFUTAR. Destaparon
**seis defectos, y los seis los había introducido el trabajo de ESE MISMO DÍA** [AUDIT-02]: el
invariante de TTS abortaba en falso (comparaba con `!=`, y el propio cambio del em dash a espacio parte
un token) **llevándose el chunk del pool**, porque `take_chunk` corre ANTES del `try`; el filtro de
cabeceras estaba sin anclar (`\s*\d*` casa con NADA) y borraba párrafos que empezaran por *"Bloqueé"* o
*"Parte de mí"*, **con el invariante nuevo ciego por construcción**; y la línea de cobertura escrita
para que "no medido" no se leyera como "sano" imprimía `OK 2/2 shorts medidos (todos)` con **CERO**
medidos, dos líneas debajo de dos avisos que decían lo contrario. Más: `--shorts-stems ""` desactivaba
el acotamiento en silencio, el chequeo de arranque daba `OK` sin medir, y `peor_tramo` sin guardia en el
vídeo **mientras su gemelo de shorts sí la tenía**. Y en una 3.ª pasada, **[META-02]** el backstop de
metadatos toleraba borrar 840 palabras cuando el desenlace entero son 500 —permitía borrar 1,7 veces lo
que decía proteger— y `_limpiar_bloque` no tenía tope ninguno: el defecto no se había cerrado, se había
**movido** de la concatenación al bloque; **[FRAG-01]** la guarda de fragmento borraba hasta el 41% del
cuerpo de un short, y su "no regresión" era vacía porque **0 de 18 pares en disco llegan a la rama
nueva** (todos salen por el `return` temprano). Todos arreglados y medidos: umbral por bloque calibrado
contra el caso real de [BASURA-03] (22%), backstop atado a `_CIERRE_MIN_PALABRAS`, tope de 28 palabras
en el fragmento, invariante solo a la baja. 25 guiones reales sin cambios y la cadena completa con
**sha256 idéntico**.
**Pendiente:** **[TRUNC-01] lo cerró el track C** (`d21e6e0`, `8e522fa`: el prompt ORDENABA el
sobrepaso que luego se truncaba), y el gate ya lo detecta solo — sobre `video_006` canta `FALLA truncado
narrativo (77%)` y `FALLA coherencia título/cuerpo (0%)`, donde por la mañana daba verde. **Ya no queda
ningún defecto conocido que llegue al vídeo largo**, que es lo único que sube el uploader. Abiertos, los
tres solo de shorts: **[SHORTVID-01]**, **[APERTURA-01]** y **[SHORTDUR-01]** (este espera decisión de
Diego: 34-41 s reales contra 60-90 de la spec). **[WOOSH-01]**: el "arreglo" del woosh es un **no-op
exacto** —`max(0, 0.25−0.483) = 0`— y el gemelo largo da 0 igual, así que la desincronización sigue
intacta en los DOS caminos. Sin cubrir en [FRAG-01]: corte en abreviatura (`Sr.`) y dos frases
descabezadas seguidas. La **huella del auditor** cambió: los veredictos caducan y hay que re-auditar
antes de subir. **No publicar `video_006`** ni `short_006`/`short_008`. Falta el `client_secret.json` de
Diego y una producción real de 30 min. Los commits de este track están en `feat/competencia`.

## v0.8 — 2026-08-13/14 — El alineador repartía sobre la ventana entera de edge-tts ✅
**Qué se hizo:** `/seed-review` (1 ciego + 3 críticos) sobre `SEED_alineador_ventana_aplastada.md`.
La **causa raíz del SEED quedó CONFIRMADA cuatro veces** (el agente ciego llegó a la misma línea sin
verlo), pero el panel tumbó **3 de sus 5 criterios de aceptación** y la receta del tercer corpus.
Cambios: **[ANCLA-06]** la rama de reparto usa los **tramos de voz medidos** en vez de `s_dur`;
**[PARTIR-01]** `titulo_en_curso` sale del bucle de párrafos; **[BASURA-03]** el índice Markdown del
modelo se narraba (27% del vídeo) y los tres guardias lo daban por limpio; **[INSTR-06]**; tercer
corpus del banco congelado con su audio; `{stem}_story.txt` persistido en shorts.
**Incidentes:** [ANCLA-06] [BASURA-03] [INSTR-06] · cierra [PARTIR-01] y [LOOP-01].
**Verificación:** banco offline sobre **tres** corpus, con el control del instrumento en
0,0027-0,0047 s. Ventana del caso: **22 palabras >0,5 s tarde → 0**, y **0 pronto** (sin
sobrecorrección: `util=8` daba 0 tardías con 6,58 s de pantalla en blanco); p95 global +0,391 →
**+0,119**; 11-ago 2 ventanas rotas → 0; **0 ventanas que EMPEORAN** en los tres. Guarda dura: el fix
toca SOLO las ventanas de la rama (1 de 18 y 2 de 110), las otras **547 y 5261 palabras idénticas bit
a bit**. El camino `span<=0.05`, que ningún corpus con audio ejercía, pasa de **+1,063 s y 13 tardías
a +0,369 y 0**. Gemelo: 6 shorts reproducen su línea base, y con la rama **forzada** mejora
(0,339 → 0,260). [BASURA-03]: 604 → 472 palabras cortando en la última frase real, **0 falsos
positivos** en 5290 y 5334 palabras de historias buenas.
**Lo que esto enseña:** (a) **el criterio de aceptación obvio era de un solo lado y pasaba por
construcción** — un panel que solo hubiera validado el diagnóstico habría dado el visto bueno a un
fix que vacía la pantalla; (b) el mecanismo tenía **dos** componentes (cola de silencio + pausas
internas aplanadas) y el escalar solo cubría uno; (c) **el mapeo afín quedó refutado por medición**
(+7,6 s): el ritmo crudo de una ventana aplastada es basura, conservarlo conserva el error; (d) un
agente reconstruyó un corpus "histórico" **importando el módulo en caliente** con el fix de hoy
aplicado, y escribió esa conclusión falsa dentro del propio instrumento [INSTR-06].
**Gate (corrido después, 14-ago 10:39-10:57, ~7 peticiones + 3 reintentos):** `/eval` completo con
shorts sobre `video_005` → **PASA**. Contra el baseline del 12-ago: media **0,0877 → 0,075**, máximo
**7,52 → 0,390**, peor tramo −0,13 → **−0,100**, pausas fuera de puntuación **6 → 4**, sesgo −0,048
(delante, correcto), cobertura 99,3%, 0 palabras >0,5 s tarde. `output-audit`: **sin defectos
MEDIBLES**, con `voz SIN subtítulo 0,00 s` (el eje de riesgo del fix) y `auto-anotación en la cola:
ninguna` (el guardia de [BASURA-03] vivo en generación fresca). ⚠️ **Pero la corrida NO ejerció la
rama arreglada**: los 5 anclajes dan `0 repartidas sobre los tramos de voz medidos`. El gate prueba
**no-regresión**, no el fix; la prueba de [ANCLA-06] vive en el banco offline. Es [GATE-03] otra vez.
**Pendiente:** No hay producción larga nueva. Dentro de la ventana, `|err| max` queda en **0,443 s** contra el objetivo de 0,30 y
la mediana en +0,119 contra +0,10: no se ha tuneado la constante contra el propio instrumento
([SYNC-01]), se declara. La ventana pasa de 0,00 a **0,39 s** de voz sin subtítulo. El corpus del
10-ago **no es evaluable** para este fix (no se conservó su audio), y `data/evidence/` está
gitignored: el tercer corpus vive solo en disco.

## v0.7 — 2026-08-12 — Revisión del 12-ago: la palanca era la longitud de frase, no las comas ✅
**Qué se hizo:** `/seed-review` (1 ciego + 3 críticos) sobre `SEED_revision_12ago.md`. El panel **refutó
la evidencia principal del SEED**: el "primer veredicto limpio del auditor" se emitió a las 16:43 con un
auditor reescrito a las 17:13 y un guardia de las 17:30 — y el dashboard seguía ofreciendo ese vídeo
para **subir a YouTube**. Cambios: veredictos firmados con la **huella del auditor** [AUDIT-01];
**partidor de frases en código** (`_ensure_breathing_periods`), que es la palanca dominante;
`_ensure_title_at_start` arreglado (mutilaba la 1.ª frase y **borraba frases legítimas**);
auditor cortando por **pausas medidas acústicamente** en vez de por densidad de comas [COMA-04];
`target_wpm` 160 → **187**; `_strip_trailing_metadata` [BASURA-02]; y el cue de fin de frase que se iba
mientras la voz seguía sonando [SUBT-01].
**Incidentes:** [AUDIT-01] [COMA-04] [BASURA-02] [SUBT-01] [LLM-01].
**Verificación:** A/B acústico controlado con edge-tts sobre el guion REAL de 26 min (misma entrada, dos
códigos): frase mediana **48 → 15**, pausas sin ningún signo detrás **86 → 47**, wpm 201,4 → 187,3;
barrido de `cada` en 12/18/25 antes de fijar la constante. `target_wpm` recalibrado sobre el AUDIO y
**después** del partidor (n=2: 187,3 y 188,0). `/eval` completo con shorts: **pausas inventadas 0,0 por
1000**, ratio 0,779 → **0,949**, 6/6 títulos únicos — y marcó `FALLA` en voz sin subtítulo (1,60 s), que
era **efecto de mi propio partidor** y se cerró a **0,00 s** con starts intactos, 0 solapes y fin del
título Δ 0,0000 s.
**Lo que esto enseña:** (a) **dos instrumentos propios mintieron y la calibración los cazó** — el
emparejador por reloj de habla daba 8% de acierto y sus números (103 → 170) eran basura plausible; con
Whisper independiente (98-100%) el diagnóstico cambia: las pausas largas caen TODAS en punto y el
defecto real son respiraciones cortas; (b) **[COMA-03] ya había medido el día anterior** que las comas
eran la palanca débil, y el fix del 12-ago las atacó igualmente: el ledger existía y no se consultó;
(c) el guardia de comas juzgaba el guion **crudo**, que el pipeline reescribe aguas abajo.
**Pendiente:** **no hay vídeo largo nuevo** — todo se midió sintetizando el guion real, no produciendo.
"Cuesta de entender" sigue sin verificarse con el oído de Diego. Disco: 659 MB liberados, **15 GB
libres** (una corrida larga pide ~12). `input/` son 13,8 GB y mover a D: sigue aplazado.

## v0.6 — 2026-08-12 — El vídeo del 11-ago no era un problema de comas: era 3 defectos que nadie medía ✅
**Qué se hizo:** `/seed-review` (1 ciego + 3 críticos) **reordenó el SEED**: refutó que las comas
explicaran wpm y ratio (la voz articula igual; 90% del delta es silencio, y del silencio 63% son
PUNTOS), que el objetivo de 8,5 comas/100 fuera alcanzable (techo real **5,59**) y que el 10-ago
tuviera ratio 1,00 (**0,894**). Y destapó tres defectos que el SEED no nombraba, dos peores que las
comas. Cerrados: **[CIERRE-01]** la historia se quedaba sin final por DOS caminos (el `while` salía sin
pedir el desenlace — 1 de 3 corridas — y `_truncate_to_words` decapitaba el epílogo); **[ANCLA-05]**
ventana con el interior FABRICADO por stable-ts (26 de 29 palabras con duración idéntica + 2 huecos
inventados de los que el cierre retenía 0,80 s cada uno); **[GATE-02]** el auditor era ciego POR
CONSTRUCCIÓN a la cobertura y ahora **corta** la cola de subida; **[TITULO-01]** el eco del título
parafraseado; **[TITULO-02]** título corto para el campo de 100 caracteres de YouTube; miniatura
(`thumbnails.set`), `--max-shorts`, y un guardia de puntuación tras el juicio de Diego.
**Incidentes:** [CIERRE-01] [ANCLA-05] [GATE-02] [GATE-03] [TITULO-01] [TITULO-02] [MAIN-01]
[REVIEW-01] [COMA-03].
**Verificación:** Corrida real de 45 min: **veredicto del auditor sin defectos MEDIBLES, el primero
limpio**. El bug de [CIERRE-01] **se reprodujo a escala** y el `if` lo paró. Voz sin subtítulo
8,3 → **0,76 s**; racha aplastada 28 → **2**; anclaje sobre las DOS producciones con `anchor_bench`:
palabras desincronizadas 204 → 9 y 73 → 0, **0 ventanas empeoran**, fin del título Δ 0,0000 s.
**Lo que esto enseña:** (a) **un mock no ve que el modelo no responda lo que se le pide** — tres
fallos pasaron los tests de los subagentes y solo salieron contra la API real: `max_tokens=200`,
`Another option: "..."` camino del título de YouTube, y un `NameError` que compilaba limpio; (b) el
gate **no es determinista** [GATE-03] y su comparación relativa necesita un A/B controlado; (c) dos de
los tres hallazgos "de bulto" del propio review comparaban contra la **referencia equivocada** (un
umbral de otro formato, un binario de otro commit).
**Pendiente:** `seeds/SEED_revision_12ago.md` — 9 cambios en una sesión, diseñados y auditados por el
mismo, y el **mismo error de clase dos veces el mismo día** (`NameError` fuera de alcance). Diego pidió
revisarlos con seed fresco. Abierto: **longitud de frase** (la palanca dominante según el A/B del repo,
sin tocar: mediana 48-59 palabras contra 13 de la corrida buena), el **salto de 1645 palabras** que
introduce el truncado, el ratio 0,793, y **disco en 7,6 GB** (la corrida larga necesita ~12).

## v0.4 — 2026-08-10 — `/optimize`: 4 clases del ledger promovidas a regla ✅
**Qué se hizo:** Primer `/optimize` desde el 05-ago (9 commits de por medio). Promovidas 4 clases:
**instrumento no calibrado** (SYNC-01+INSTR-01+INSTR-02, n=3) → `produccion-loop.md` §D regla madre;
**régimen de validación equivocado** (ANCLA-01+BASURA-01+WPM-01, n=3) → `produccion-loop.md` §C "el
techo del gate"; **fix no propagado al gemelo** (PATH-02+LOG-02, n=2) → `decision-making.md` §11 con
tabla de pares + grep obligatorio; **guardia existente pero no aplicado** (GUARD-01+BASURA-01) → §17
2.º corolario. `SEED_4_validar_cambios.md` marcada ⛔ SUPERADA (era la v1 que un panel tumbó y seguía
ejecutable). Tablas de barrido movidas a `docs/mediciones-frases.md`; v0.1 archivada.
**Incidentes:** ninguno nuevo — sesión de config.
**Verificación:** [DOC-01] seguía **VIVO en 6 ficheros** (`decision-making`, `change-loop`,
`file-organization`, `produccion-loop`, `engineer`, `daily-run`, `run`) meses después de corregirse en
`CLAUDE.md`: `grep -rn "tope de 50"` → 0 falsos restantes tras el fix. `decision-making.md:7` afirmaba
"no se auto-carga" siendo falso (los 5 rules están en contexto): corregido. Modelo de producción
verificado VIVO contra `GET /api/v1/models` (399 modelos; `nvidia/nemotron-3-ultra-550b-a55b:free`
presente, `google/gemini-2.0-flash-001` ausente). `CLAUDE.md` decía "cadena completa y validada" y
listaba la producción de 30 min como pendiente **cuando ya se había corrido y salido no publicable**.
**Pendiente:** [ANCLA-01] **sigue vivo** en `tts_engine.py:458` — `SEED_sincronismo_produccion.md` es
ahora la seed nº 0 (bloqueante). Contexto auto-cargado: **935 → 1009 líneas** (+74 neto: ~+95 de
reglas nuevas, −21 de compresión). El `/optimize` de hoy **no ahorró tokens, los gastó**: es el precio
de 4 promociones. El próximo debería ser de poda.

## v0.5 — 2026-08-11 — Anclaje cerrado tras 3 versiones, subida a YouTube, y una causa aguas arriba 🔶
**Qué se hizo:** El anclaje pasó por **tres versiones y dos la tumbó la medición**: (1) la del SEED,
refutada aritméticamente; (2) la propia, que arreglaba el vídeo largo y **rompía 3 de 16 shorts**;
(3) la actual, que distingue **ancla corrupta** (outlier aislado) de **deriva del alineador**
(residuos crecientes en ventanas seguidas) y trata la **ventana aplastada** (>330 wpm). Además:
subida a YouTube completa (privado · solo el largo · cola con OK en el dashboard), auditor de
corrida `scripts/audit_run.py`, techo de bitrate, loudness a −14 LUFS, dedup de bloques, guarda de
aperturas en títulos de shorts, y `components.html` deprecado fuera.
**Incidentes:** [DEDUP-01] [ANCLA-02] [ANCLA-03] [ANCLA-04] [COMA-02] [INSTR-04].
**Verificación:** contra transcripción independiente en **las dos** producciones reales — 10-ago:
209 palabras / 60,7 s desincronizadas → **15 / 5,9 s**, p95 1,010 → 0,283; 11-ago: peor ventana
**7,43 → 1,45 s**; solapes 2 → 0 en ambas. `/eval` con shorts: media 0,0723 → **0,043**, máx 0,400 →
0,320, pausas 1 → 0 → **PASA**. Loudness −22,2 → −14,8 LUFS y bitrate 11,4 → 7,8 Mbps, ambos medidos
por ejecución. Dashboard verificado con `AppTest`: 0 excepciones, 8 pestañas.
**Lo que esto enseña:** (a) la **mediana esconde el defecto local** — una zona con mediana −0,110 s
contenía 40 palabras a −7,4 s, y el mismo error se cometió dos veces; (b) un fix puede dar verde en
el vídeo largo y romper el gemelo; (c) cuando Whisper y edge-tts discrepan 5 s, lo decide un
instrumento que no dependa de Whisper (`silencedetect`) — y tenía razón edge-tts.
**Pendiente:** `seeds/SEED_comas_y_cierre.md`. La causa aguas arriba: el modelo entregó una historia
con **10 comas** (0,2/100) frente a 448, y de ahí salen encadenados 101 pausas inventadas, 202 wpm y
ratio 0,79. **`target_wpm` NO es calibrable** (n=3: 160,6 / 177,2 / 202,3). La corrida de validación
a escala quedó SIN hacer, y la subida espera a que Diego cree el `client_secret.json`.

## v0.4 — 2026-08-10 — ANCLA-01 arreglado y medido; dos premisas del SEED refutadas ✅
**Qué se hizo:** `/seed-review` (TIER PANEL: 1 ciego + 3 críticos) sobre `SEED_sincronismo_produccion.md`
tumbó dos cosas del plan: (a) su fix del anclaje estaba **refutado aritméticamente** —el paso 1.ª→2.ª
palabra no predice el error, con inversión de rango (paso 2,11→err 1,07; paso 1,98→err **1,48**)— y
(b) su bloque A partía de una premisa falsa. Además el ciego destapó un defecto que el SEED no
nombraba. Se arregló el anclaje (offset = **mediana de residuos del vecindario** + cierre de
silencios inventados dentro de la ventana + guarda de orden), el dedup de bloques, y se le dio al
gate la métrica que le faltaba.
**Incidentes:** [DEDUP-01] [ANCLA-02] [INSTR-04] del ledger.
**Verificación:** Banco offline sobre la producción real (214 ventanas, contra transcripción
independiente), con **control del instrumento**: reproduce el `.ass` publicado desde las palabras
crudas con 0,005 s de media / 0,010 s de máximo. Anclaje viejo → nuevo: palabras desincronizadas
**204 → 20**, vídeo afectado **60,3 s → 7,2 s**, p95 **1,010 → 0,286 s**, sesgo **+0,005 → −0,040 s**,
solapes **2 → 0**; las dos ventanas de 94 y 95 palabras pasan de **+1,05 s a −0,065 s**. Invariantes
comprobados: fin del título **Δ 0,0000 s** (la intro no se mueve), 5290 palabras conservadas, orden
monótono. `/eval` con shorts (5 peticiones): media **0,0723 → 0,043**, máx **0,400 → 0,320**, sesgo
−0,0669 → −0,0173 (sigue delante), cobertura 94,6% → 98,1%, pausas fuera de puntuación **1 → 0**
→ **PASA**. Medido por primera vez el **gemelo**: `short_009` da media 0,026 s, máx 0,300 s, sesgo
−0,011 s, 0 palabras >0,5 s tarde.
**Lo que esto enseña:** el emparejador `difflib` **global y el local dan resultados idénticos**
(5062 pares, 0,153 s, +0,003 s) y coinciden con las transcripciones frescas en las 6 zonas: [INSTR-02]
acusó al instrumento de un fallo que era ANCLA-01. Comparar un número de producción con el baseline
del fixture de 3 min es comparar dos regímenes. `data/eval/2026-08-10-produccion-real.json` **no
estaba mal** y se conserva intacto.
**Pendiente:** (1) corrida larga de validación — **aplazada por disco** (~7,3 GB con 16 libres; nada
borrado, decisión de Diego). (2) `output-audit` sobre la salida del gate. (3) `target_wpm`: dejar en
160 (seis corridas dan 152-162; el 177 es el outlier contaminado). (4) Variedad de los 50 shorts: es
juicio de Diego (50/50 empiezan por "Mi ‹alguien›"). (5) `short_story.txt` sigue sin directrices.

## v0.3 — 2026-08-10 — Primera producción real de 30 min: destapó un vídeo no publicable 🔴
**Qué se hizo:** Corrida completa a escala real (33,4 min de gameplay → vídeo de 29,85 min + 50
shorts, 53 peticiones, ~2h40). Antes: baseline de `/eval` fijado sobre el fixture de 3 min y
`--keep-temp` añadido porque `cleanup_temp` borraba el `.ass` que el gate mide.
**Incidentes:** [BASURA-01] [ANCLA-01] [INSTR-02] (+ los 6 de v0.2).
**Verificación:** El vídeo resultante **NO es publicable**: (a) basura del modelo narrada y
subtitulada en el minuto 15:38-15:47 (`temp/video_001_subs.ass:2756` → `ONEAN`, `0230`, `0207-`);
(b) 4 ventanas de anclaje con frases enteras ~1 s por detrás de la voz, confirmado con
transcripciones frescas de 40 s (1000-1040 s: **+1,050 s**, 90 de 125 palabras >0,5 s; control
300-340 s: **−0,110 s**). Causa raíz localizada por `bug-hunter` y validada por ejecución:
`tts_engine.py:458` traslada la ventana entera usando UNA sola palabra. (a) arreglado con
`_detectar_basura` (0 falsos positivos sobre ~12.700 palabras de español real); (b) **fix
propuesto, NO aplicado**.
**Lo que esto enseña:** `/eval` sobre 3 min (12 ventanas de anclaje) dio verde a este vídeo. La
producción real tiene 214 ventanas. **El gate no puede ver esta clase de fallo.**
**Pendiente:** `seeds/SEED_sincronismo_produccion.md` — arreglar el emparejado global de
`eval_sync` (dio 3 falsos positivos hoy), aplicar y verificar el fix del anclaje, `target_wpm`
177 (n=2), variedad de los 50 shorts, y decidir qué hacer con un gate que no cubre producción.

## v0.2 — 2026-08-10 — SEED de validación: revisado, reescrito y ejecutado ✅
**Qué se hizo:** El `SEED_validar_cambios.md` pedía barrer 6 parámetros con 6 agentes en paralelo.
`/seed-review` (TIER PANEL: 1 agente ciego + 3 críticos) lo tumbó: 4 de 6 bloques no tenían
instrumento válido, el paralelismo corrompía las mediciones (`pipeline.log` es ruta fija,
`cleanup_temp` hace `rmtree` del temp compartido) y "no aplicar cambios" era incompatible con
barrer constantes de módulo. Diego validó los hallazgos, dio el OK a la reescritura y añadió dos
enmiendas (separar el knob de wpm; conservar la verificación por fotogramas como gate del bloque A).
SEED reescrito a v2 y ejecutado **en serie**: 4 defectos arreglados, bloque B auditado, medidor del
gate escrito.
**Incidentes:** [PATH-02] [LOG-02] [GUARD-01] [COMA-01] [WPM-01] [DOC-01] [SYNC-01] del ledger.
**Verificación:** concat multi-fichero reproducido ANTES (`FALLO: Error concatenating`) y DESPUÉS
(`OK duration=2.000000`), más integración con 3 trozos de gameplay real → chunk de 152,6 s con
**desvío 0,00 s**. Validador contra 50 títulos reales del log: 3/3 casos de control legítimos
pasaron de rechazados a aceptados, verdaderos positivos siguen cazados. Comas auditadas sobre
7.399 palabras generadas + property test con **0 violaciones del invariante en 1.248
comprobaciones**; TTS real con `silencedetect` calibrado a −35 dB (instrumento no circular):
sin comas 26 silencios/10 signos, con comas 31/22. Cuota verificada con `GET /api/v1/credits`
→ 10 créditos, **1000 peticiones/día** (`CLAUDE.md` decía 50 y estaba desactualizado).
**Pendiente:** (1) baseline de `/eval` — `scripts/eval_sync.py` ya existe, falta la corrida que
fija la línea base. (2) Producción real de 30 min de punta a punta. (3) `short_story.txt` sigue sin
recibir las directrices de competencia. (4) Bloques A/E/F declarados NO medibles con el
instrumental actual (referí circular, proxy que no discrimina, supervivencia de la muestra):
lo accionable es que el próximo escaneo persista el corpus `fresh`.

<!-- entradas anteriores archivadas en docs/sessions-log-archive.md (v0.1) -->
