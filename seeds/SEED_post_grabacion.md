# SEED — Lo que queda abierto tras la sesión del 18-ago-2026

> PASO 0 OBLIGATORIO: invoca /seed-review sobre este SEED antes de tocar nada.

**Contexto:** el 18-ago se desbloqueó y se arregló el pipeline para que produjera un vídeo con
veredicto limpio, de cara a grabar el vídeo de portafolio. Lo cerrado ese día está en
`sessions-log.md` v1.1 y v1.2. Esto es **lo que quedó sin cerrar**, ordenado por consecuencia real.

⚠️ **El repo se va a publicar en GitHub**: además del código, se lee. Un `.md` con un dato falso es
un defecto visible, no una nota interna.

---

## 🔴 P0 · El detector de pausas quedó CIEGO por mi propio arreglo

`scripts/audit_run.py:539` → `exceso = max(0, len(sil) - signos)`.

Es una **resta de conteos**, no una comprobación posicional. Al bajar `_PUNTUACION_P90_MAX` a 21
(que es lo que arregló las pausas), todo guion aceptado pasa a tener muchos más signos:

```
video_009 (antes del fix): palabras=714  signos=42  silencios=54  -> exceso=12   FALLA
video_010 (umbral 24):     palabras=665  signos=36  silencios=44  -> exceso=8    FALLA
video_011 (umbral 21):     palabras=621  signos=68  -> harian falta >68 silencios
video_012 (umbral 21):     palabras=602  signos=69  -> harian falta >69 silencios
```

Un vídeo de 3 min tiene 40-54 silencios. **`exceso` da 0 caigan donde caigan las pausas.** El
`OK pausas inventadas (acústico): 0.0` ya no aporta información, así que una regresión futura de
esto pasaría sin que nadie lo vea — que es exactamente la clase de fallo que este repo persigue.

Es la firma nº1 de `produccion-loop.md` §D (*"la variable manipulada en el denominador"*), y esta
vez la provocó el propio fix.

**Evidencia de que ya sub-reporta:** una medición POSICIONAL independiente (atribuir cada silencio
a la palabra que lo precede en el `.ass` y mirar si esa palabra acaba en signo) encuentra **4
pausas reales a mitad de sintagma en `video_005`** (`tras 'GASTADO'` t=103,81 · `tras 'PATRIMONIAL'`
t=127,90 · `tras 'EN'` t=145,57 · `tras 'FORTUNA'` t=189,16), donde el instrumento del repo dice 0.

**Arreglo:** sustituir la resta por el emparejado posicional. Calíbralo contra casos de resultado
conocido antes de fiarte: `video_009` → ~17/1000, `video_010` → ~12,6, `video_012` → 0.
**No es superficie sensible** (es el auditor), pero es un gate: pásale el conjunto vacío, el `.ass`
ausente y el audio ilegible (§16). Y recuerda que tocar `audit_run.py` **caduca todos los
veredictos** (`_HUELLA_FUENTES`): re-audita al final, una sola vez.

---

## ✅ P1 · [TRUNCA-02] — CERRADO el 19-ago

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
