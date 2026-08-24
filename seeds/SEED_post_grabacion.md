> 🔵 ABIERTO.

# SEED — Lo que queda abierto tras la sesión del 18-ago-2026

> PASO 0 OBLIGATORIO: invoca /seed-review sobre este SEED antes de tocar nada.

**Contexto:** el 18-ago se desbloqueó y se arregló el pipeline para que produjera un vídeo con
veredicto limpio, de cara a grabar el vídeo de portafolio. Lo cerrado ese día está en
`sessions-log.md` v1.1 y v1.2. Esto es **lo que quedó sin cerrar**, ordenado por consecuencia real.

⚠️ **El repo se va a publicar en GitHub**: además del código, se lee. Un `.md` con un dato falso es
un defecto visible, no una nota interna.

---

## 🔴 P0 · El fix de [TRUNCA-02] apagó el detector de [TRUNCA-01] — y ese detector es el que cablea el botón de SUBIR

> Añadido por `/seed-review` (20-ago). **Lo destapó el agente CIEGO**, que no vio este SEED. El SEED
> daba [TRUNCA-02] por cerrado (§P1 ✅) apoyándose en `video_005`/`video_007` = *"sin defectos
> MEDIBLES"*. Esos dos veredictos **no prueban lo que el SEED cree que prueban**.

`scripts/audit_run.py:705` → `elif not _frac_trunc:` degrada la coherencia título/cuerpo a **AVISO**
cuando la historia no se truncó. La premisa escrita en el comentario es *"sin truncado la causa de
[TRUNCA-01] no puede haber ocurrido"*. **Es falsa**, y el fix del 19-ago la volvió dominante: al
hacer raro el truncado, mandó casi todo el tráfico por la rama que **no bloquea**.

Medido (salida real de `pipeline.log`, no informe):

```
6855: 20:58:57 [audit] AVISO coherencia titulo/cuerpo: el titulo promete
      <<...el testamento final la dejo sin nada>> pero solo el 25% de sus palabras
      de contenido reaparece en el cuerpo (raices ausentes: dejo, nada, testa)
6447: 20:12:30 [audit] AVISO ... video_005 ... 33% (raices ausentes: cambi, ocult)
output/video_005_audit.json -> {'ok': True, 'fallos': []}
output/video_007_audit.json -> {'ok': True, 'fallos': []}
```

`youtube_uploader.py:173` hace `"publicable": bool(auditoria.get("ok"))`: **los dos vídeos de la
grabación están marcados publicables con un AVISO de la clase que el gate existe para cazar.**

**Honestidad sobre la gravedad (medido a mano en `D:/YOUTUBE_media/temp/video_007_story.txt`, 589
palabras):** es un positivo **PARCIAL**, no limpio. El cuerpo **sí** narra un desenlace (sentencia,
devolución íntegra con intereses, la madre pierde la gestión de la herencia, administrador judicial)
— pero **no hay testamento en ninguna parte**, y "el testamento final" es justo el gancho que va a
la **miniatura** y a la **intro**. No es [COHER-01] puro (sinonimia) ni [TRUNCA-01] puro: es un
título que promete un MECANISMO que el cuerpo no usa. Antes de endurecer el check hay que decidir
qué de esto es defecto y qué es licencia narrativa — **es juicio de Diego, no de código** (§18).

**Y falla ABIERTO** (clase [GATE-04], ya cerrada una vez en este repo): `truncado_narrativo` devuelve
`(None, motivo, None)` si no encuentra `pipeline.log` o el tramo del stem → `not None` es `True` →
rama AVISO → **la coherencia no bloquea nunca sin log**. Comprobado en `audit_run.py:277+`.

**Arreglo:** desacoplar la coherencia de `_frac_trunc` y decidir su umbral con Diego. Ojo: el check
da False en 14 de 17 guiones reales, así que endurecerlo sin recalibrar **bloquea todo** — [COHER-01]
es real y sigue vivo. El default degenerado (sin log) debe caer del lado caro, no del barato (§16).

---

## 🟠 P0-bis · [ANCLA-07] es el único defecto que YA produjo un vídeo de 33,6 min no publicable

El SEED lo enterró en P3 como *"re-componer `video_003`"* (tarea de artefacto). **No lo es: es un bug
vivo del alineador** (`tts_engine`, rama de traslación `scale = s_dur/span`) que volverá a disparar
en la próxima producción larga. `output/video_003_audit.json` → `"ok": false`; 33 cues de 6203 en dos
rachas, peor tramo −1,640 s, 5,8 s de voz sin subtítulo. El 99,5 % del vídeo está sano.

---

## 🟠 P0-ter · El truncado por el medio sigue DESNUDO en el camino multi-bloque (el único que publica 30 min)

Convergen el ciego y un crítico, con el código en la mano: el fix de [TRUNCA-02] vive en
`_generar_historia_un_bloque` (`script_generator.py:1303-1332`), y `generate_story:1432` bifurca por
`target_words <= _UN_SOLO_BLOQUE_MAX_PALABRAS (=2000)`. Producción real = `chunk 1800 s x 196 wpm` →
`Generando historia de 6547 palabras en ~4 bloques` → **camino multi-bloque, truncado intacto en
`:1506`**, cuyo propio docstring declara *"comportamiento SIN CAMBIOS"*. Histórico: `pipeline.log:15`
→ `Truncando de 6979 a ~5345 palabras` (1634 cortadas por el medio).

**La verificación que el SEED cita como prueba de cierre es de régimen fixture**: `video_007` =
*"Historia de 623 palabras cabe en un solo bloque"*, vídeo de **3,9 min**. Es `produccion-loop.md` §C
literal. Propagar el guardia al gemelo multi-bloque.

---

## 🟡 P1 · El detector de pausas del auditor está ciego (era el P0 del SEED)

`scripts/audit_run.py:539` → `exceso = max(0, len(sil) - signos)`.

**El fondo se CONFIRMA con un argumento más fuerte que el del SEED:** en `video_011`/`video_012` los
silencios (55, 40) son **menos** que los signos (68, 69), así que aunque el 100 % de las pausas
cayera a mitad de sintagma (88 y 66 por 1000 = catástrofe), `exceso` seguiría dando 0. Y en el
**régimen de producción** el conteo sub-reporta **3,7x**: `video_003` → conteo `21 = 3,4/1000` (PASA)
vs posicional `79 = 12,7/1000` (FALLA), con 4 de 79 muestreadas contra el guion y todas mid-sintagma.

**Pero tres afirmaciones del SEED quedan REFUTADAS o matizadas — no las heredes:**
1. **La ceguera NO la provocó el fix del umbral 21.** `video_005/006/007` son del 14-ago, *anteriores*
   al umbral, ya traían 64/65/55 signos y ya daban `exceso=0` con pausas reales dentro. El fix
   ensanchó el margen; no lo abrió. *(Y "todo guion aceptado trae 60-70 signos" se sostiene sobre
   **n=2**: 009 dio 42 y 010 dio 36.)*
2. **1 de las 4 pausas que cita como evidencia es un falso positivo de su propio método.** Se
   reproducen `GASTADO 103,81 · PATRIMONIAL 127,90 · FORTUNA 189,15` (las tres reales), pero **`EN`
   145,57 no**: el silencio cae en la coma de `AÑO,` (*"me llama una vez al año, en Navidad"*) y solo
   se le cuelga a `EN` si se empareja por el FINAL del silencio. El SEED además ignora el
   `-itsoffset -0.10` de `video_composer.py:88`.
3. **Los "casos de resultado conocido" para calibrar (17 / 12,6 / 0) son la salida del propio
   instrumento nuevo** → calibración CIRCULAR, la firma nº1 de §D que este mismo SEED invoca. Ancla
   externa que SÍ existe en disco: el vídeo que **Diego rechazó de oído**
   (`data/evidence/video_001_subs_11ago.ass` + `audio_11ago.mp3`) → **20,9/1000**; `video_012`
   (limpio) → 0,0. El umbral se elige entre 0 y 20,9 **con Diego**; trasplantar el 12,0 del conteo es
   mover una constante entre instrumentos que no coinciden ([COMA-05]: umbral en hueco no observado).

**Receta correcta (el SEED se queda corto):** atribuir por `start <= s` (usar `ends` fabrica **26
falsos** en un vídeo que da 0), sumar el offset de +0,10 s o aceptar si **algún** cue en ±0,15 s
acaba en signo, reportar aparte los silencios de **intro** y de **cola**, y devolver `(None, None)`
en degenerados — hoy el `.ass` vacío/ausente y el audio ilegible **revientan con excepción**
(`IndexError` / `FileNotFoundError` / `TypeError`), que en `audita_video` se lleva por delante las
otras mediciones. `sil == []` es el caso mudo: 0 silencios = "OK 0,0", indistinguible de sano.

**Ventajas no nombradas por el SEED:** el método posicional no necesita `_clean_speech_for_tts`, así
que elimina un anacronismo real (hoy se auditan artefactos viejos recontando signos con la limpieza
de HOY), y **se puede medir en shorts** — que es su propio P2.2.

**Coste colateral, mayor de lo que dice:** la huella actual `1fee08e24b43` la llevan 10 veredictos, 3
en verde (`video_005`, `video_007`, `video_012`). Tocar `audit_run.py` los invalida y bloquea la
subida hasta re-auditar. Con ambos métodos `video_005` y `007` dan 0,0 y 0,0: el arreglo **no cambia
su veredicto de pausas**, pero hay que re-emitirlo. **Re-auditar UNA sola vez, al final.**

---

## ⛔ BLOQUEANTE OPERATIVO · no hay con qué producir

Ninguna de las dos verificaciones que este SEED necesita (multi-bloque, [ANCLA-07]) cabe hoy:

```
df -h /c   -> C: 476G  464G usados  12G libres  98%
ls pool/   -> pool_0002.mp4.CORRUPTO  (2,7 GB, 15-ago)   <- unico fichero
grep -rn CORRUPTO modules/ main.py -> sin resultados
```

`pool/` **no tiene gameplay usable** y ninguna línea del repo conoce la extensión `.CORRUPTO`: es un
renombrado a mano. Una corrida de 30 min pide ~12 GB y exige re-ingestar los 13,8 GB de `D:/`.
**Decisión de Diego antes de cualquier corrida larga.**

---

## 🟡 P2 · [TRUNCA-02] — cerrado SOLO en el camino de un bloque (ver P0-ter)

Estaba aquí como el único defecto vivo que llegaba al vídeo publicado. **Arreglado**: el camino de un
bloque **regenera** hasta 2 veces si el modelo se pasa de `_SOBREPASO_MAX_FACTOR` (1,2×) en vez de
recortar por el medio. Verificado en producción: `video_007` escribió 909 → regeneró → 718 → *"esta
historia no se truncó"* → `sin defectos MEDIBLES`. Detalle y A/B en el ledger.

**Lo que queda de esta clase, y no es poco:** si se agotan los reintentos se sigue truncando por el
medio (peor caso = comportamiento anterior). Y el arreglo de FONDO que el ledger nombra —**derivar el
título del cuerpo ya escrito**, en vez de prometer primero y narrar después— sigue sin hacer. Con él,
la clase entera desaparece por construcción en lugar de volverse improbable.

## 🟠 P2 · Huecos de medición que el gate NO cubre (los cazó el `output-audit`, no el gate)

1. **Repetición de ARGUMENTO entre shorts.** `OK títulos únicos: N/N` compara **cadenas exactas**:
   dos historias idénticas con títulos distintos pasan siempre. Así se coló `short_032` repitiendo
   a `short_017` [SHORTREP-01]. El fix de la ventana (`AVOID_VENTANA`) sube la probabilidad de que
   no pase, pero **es prompt, no un `if`** (§17): la garantía dura sería un check de argumento.
2. **`pausas_inventadas` se abstiene por debajo de 500 palabras** (`audit_run.py:529`), y un short
   son 130-190. **Nadie mide ese eje en shorts**, ni antes ni después del fix.
3. **`audita_shorts` no tiene check de coherencia título/cuerpo.** No lo repliques tal cual: el
   check falla por sinonimia en cuerpos cortos [COHER-01].
4. **`_validar_puntuacion` calcula el p90 por BLOQUE**, no sobre la concatenación
   (`script_generator.py:692`): en una historia multi-bloque, un bloque limpio y otro sucio se
   promedian hacia el aprobado. El fixture es de un bloque, así que **esto no se ha ejercido nunca**.

---

## 🟡 P3 · Defectos conocidos con dueño pendiente

| id | qué | dónde |
|---|---|---|
| **[ANCLA-07]** | `video_003` (producción, 33,6 min) NO publicable: 33 cues de 6203 en dos rachas (t=161 y t=166), peor tramo −1,640 s, 5,8 s de voz sin subtítulo. **El 99,5 % del vídeo está sano.** Sus artefactos están preservados en `D:/YOUTUBE_media/_preserve_video_003/` — re-componer necesita re-ingestar el chunk (~16 min) | `tts_engine` |
| **[SHORTDUR-01]** | shorts de **22,5-42,3 s** contra los 60-90 de la spec; el suelo que lo permite es `min_palabras_speech=80` (`shorts_generator.py:321`) contra `target_words: 200`. **Decisión de Diego**, no de código | `shorts_generator` |
| **[WOOSH-01]** | el "arreglo" del woosh es un no-op exacto (`max(0, 0.25−0.483) = 0`) en los DOS caminos | `video_composer`/`shorts_generator` |
| **intro** | el fundido de la tarjeta empieza **~0,2 s antes** de que el narrador acabe el título: `fade_start = max(title_end - 0.3, 3.0)` (`video_composer.py:98`). Verificado por fotogramas: a 8,70 s la tarjeta está atenuada con la voz aún diciendo "amiga". `CLAUDE.md` dice *"fade out cuando termina la frase"* | `video_composer.py:98` |
| **[SHORTVID-01] [APERTURA-01]** | abiertos desde el 14-ago | shorts |
| **audio** | la pista sale a 96 kHz desde una fuente de 24 kHz (`-af loudnorm` da 192 kHz y el AAC lo recorta; falta `-ar 48000`). 181 kbps mono para voz de banda 24 kHz: desperdicio, sin efecto audible | `video_composer.py:167` |

---

## 🟡 P4 · El repo como pieza de portafolio (se va a leer en GitHub)

- **`sessions-log.md` tiene 412 líneas y su propia cabecera fija el tope en 100.** El repo incumple
  su regla a la vista. Es el Paso 5 de `/optimize` (archivar en `docs/sessions-log-archive.md`).
- **~45 incidentes del 14-18 ago sin promover** a regla. `/optimize` es el único escritor de reglas.
- **`PORTAFOLIO/` contiene 4 HTML de OTROS proyectos** (`SEKURA`, `PUMPFUN-BOT`, `RESELLERMASTER`,
  `YOUTUBE-PIPELINE`) dentro del repo del pipeline. **Decisión de Diego**: si es intencionado, vale;
  si no, en GitHub se lee como residuo.
- **`CLAUDE.md` §"Estado del proyecto"** sigue listando como pendientes seeds ya ejecutadas
  (`SEED_1`, `SEED_2`, `SEED_5`) y describe la validación E2E con el estado de agosto.
- **Corregidos el 18-ago** (no volver a tocarlos): el aviso de `[ANCLA-01] SIGUE VIVO` (era falso y
  apuntaba a una línea que ya no existe), la ventana anti-repetición ("12" → `AVOID_VENTANA`), y la
  ruta del fixture `test_e2e/clip.mp4` → `test_e2e/input/clip.mp4` [DOC-02].
- **README.md creado el 18-ago.** Si cambian las cifras que cita, actualízalo: es lo primero que se
  lee. ⚠️ El 20-ago se corrigió el par `0,502 → 0,072`, que **cruzaba dos mediciones distintas** (el
  «después» del A/B era 0,146; el 0,072 es de otra corrida y otro régimen). Es la misma clase que
  obligó a rehacer el overlay de §9 del vídeo. **Cada cifra, con su medición.**


> **`/seed-review` (20-ago) — estado REAL verificado hoy; tres viñetas de arriba ya han caducado:**
> - ✅ **YA HECHO**: `PORTAFOLIO/` salió del repo en `460367d` (−5023 líneas) y está en
>   `.gitignore:23`. El clip de `D:/YOUTUBE_media/input/clip.mp4` ya no existe. `git status` está
>   **completamente limpio**, `.tint_index` incluido (commiteado en `dbf5805`), y `config.yaml:132`
>   tiene `target_duration_min: 1200`. **El checklist de después de grabar está cumplido entero.**
> - ❌ **PEOR de lo que dice**: `sessions-log.md` tiene **440** líneas, no 412 (tope 100 → 4,4x).
>   Ledger: **88 entradas, 76 pendientes, 10 promovidas**; último `/optimize` **10-ago** (10 días).
> - 🔴 **LO GRAVE QUE EL SEED NO NOMBRA — el `README.md` publica un transcript FABRICADO.**
>   El bloque `$ python scripts/audit_run.py --stem video_012` (líneas 35-43) **no es la salida de
>   ninguna corrida**: es un compuesto de tres. La corrida real de ese stem (`pipeline.log:5988`,
>   19:47:01) dice `1 palabras >0,5 s tarde`, `voz SIN subtítulo: 0.39s en 1 tramo(s)`,
>   `loudness: -15.4 LUFS` y **dos AVISOs** (pausas 2 · coherencia 25%). El README publica
>   `0 palabras`, `0.00s en 0 tramo(s)` y `-14.6 LUFS`: valores reales, pero de las corridas de las
>   20:12 y 20:58. En un repo cuya tesis es *"cada cifra con su medición"*, es el peor defecto
>   visible. `sessions-log.md:55` arrastra el mismo error.
>   Y `README.md:81` sigue cruzando regímenes: dice que el gate *"da hoy 0,072 s"* cuando el 0,072
>   es el **baseline del 10-ago ANTES del fix** (`data/eval/2026-08-10-BASELINE-fixture-3min.json`
>   → `0.0723`); hoy da **0,045** (`pipeline.log:5988`), cifra que el propio README imprime dos
>   párrafos antes. La corrección de `92c5642` arregló el par `0,502 → 0,146`, no este.
> - 🟠 **Un dato REFUTADO vive en 4 sitios, y uno es una REGLA promovida**:
>   `produccion-loop.md:129-131` publica como firma de §D que *"difflib global infló la media de
>   0,072 a 0,153 y volteó el sesgo"* — pero [INSTR-04] del ledger dice que **[INSTR-02] acusó a
>   `eval_sync.py` de un fallo que no tiene** (global y local dan resultados **idénticos**) y que el
>   0,072 era el baseline del fixture: **es él mismo un cruce de regímenes**. Repetido en
>   `CLAUDE.md:492`, `scripts/eval_sync.py:121-128` y `scripts/anchor_bench.py:218-222`. [DOC-01].
> - 🟠 **Más caducados en `CLAUDE.md` que los que el SEED nombra**: `:143` y `:449` dicen **7
>   pestañas** (son 8, falta *Subir*; repetido en `skills/run/SKILL.md:28` y `docs/video_guion.md`);
>   `:187` dice *"3 archivos por vídeo"* (son 5); §Estructura y `file-organization.md` **no listan
>   `modules/youtube_uploader.py` ni `scripts/`** (5 ficheros versionados) y el diagrama del pipeline
>   **no tiene fase de subida**, que existe desde el 11-ago.
> - 🟡 **`seeds/` como escaparate**: hay **16 seeds y solo 5** llevan marca ⛔/EJECUTADO, pero
>   `README.md:121-123` remite ahí para "lo que queda abierto". Un lector externo no distingue plan
>   de historial.
> - ✅ **Higiene de publicación: limpia.** 0 hits de `.env`, `client_secret`, `sk-or-`, `AIza` en
>   **todas** las revisiones. No hay nada que rotar. *(Los HTML de `PORTAFOLIO/` sí siguen en el
>   historial de git: decisión de Diego si importa.)*

---

## ✅ Checklist de después de grabar (si se tocó algo para la toma)

- [ ] `target_duration_min` de vuelta a **1200** — `git checkout -- config.yaml`, **nunca** desde
      ⚙️ Config ([CONFIG-01]: `yaml.safe_dump` borra los ~70 comentarios de calibración y el `.bak`
      se sobrescribe en el segundo guardado).
- [ ] Si se pulsó **✅ Aplicar** en la pestaña Competencia: pulsar **↩️ Quitar** y comprobar que
      `git diff prompts/reddit_story.txt` queda **vacío**.
- [ ] Borrar el clip copiado a `D:/YOUTUBE_media/input/clip.mp4` (el fixture original sigue en
      `test_e2e/input/`).
- [ ] `git status` limpio salvo `assets/.tint_index`, que rota en cada render.
- [ ] **No publicar** `video_003` ([ANCLA-07]) ni `short_032` ([SHORTREP-01], repite argumento).

---

## Fuera de alcance

La subida a YouTube (`SEED_2`), el análisis de competencia y cualquier cosa que no esté arriba.
**Entrada factual en `.claude/incident-ledger.md` por cada defecto REAL que aparezca. El retro no
escribe reglas: solo `/optimize` promueve.**
