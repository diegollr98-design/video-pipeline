# SEED — Arreglar el ALINEADOR, no seguir moviendo la constante

> PASO 0 OBLIGATORIO: invoca /seed-review sobre este SEED antes de tocar nada.

## Por qué existe, sin adornos

La sesión anterior movió `PALABRAS_FRASE_MAX` **tres veces en una tarde** (12 → 40 → 30) y en cada
una descubrió que la métrica con la que había elegido la anterior estaba incompleta. Eso no es
calibrar: es dar tumbos. Diego lo cortó — *"¿y si miramos qué sucede desde sesión fresca por
contexto? No creo que sea tan difícil hacerlo bien"* — y tenía razón en las dos mitades.

**El diagnóstico honesto de la sesión que escribe esto:** estaba moviendo un parámetro para
**esquivar** un bug en vez de arreglarlo. `cada=30` no cura nada; tiene suerte con dónde caen los
cortes. Es el fallo de *challenge-the-premise* (`decision-making.md` §7): afinar constantes cuando
el mecanismo es el equivocado.

**No repitas el barrido de la constante. El trabajo es el alineador.**

---

## EL BUG, con su evidencia

En la corrida del gate de ayer, el propio log lo nombra:

```
Ancla descartada en t=110.14s (57 palabras): residuo -4.742s frente a -0.143s del vecindario
Ventana aplastada en t=110.14s: 57 palabras en 10.32s (331 wpm). Se reparte.
```

57 palabras en 10,32 s son **331 wpm**: físicamente imposible de pronunciar (la voz articula a
236-242 wpm, medido). O sea: **el alineador comprime una ventana entera contra la realidad del
audio**, y el tratamiento actual (repartir) no la deja bien.

Su efecto en el gate, medido: `peor tramo +0,610 s en t=115,81 s`, **28 palabras >0,5 s tarde**, y
el **sesgo se vuelve POSITIVO** (+0,002), o sea el subtítulo por detrás de la voz — que es el pecado
original de este repo.

### La prueba de que la constante NO es la causa

A/B controlado (mismo texto, cuatro ajustes del partidor, contra transcripción independiente de
Whisper, cobertura 95,7-95,9%):

| `cada` | \|err\| medio | p95 | peor tramo | >0,5 s tarde |
|---|---|---|---|---|
| 12 | 0,177 | 0,280 | −0,213 | 6 |
| 20 | 0,196 | 0,496 | **+0,421** | **22** |
| 30 | 0,164 | **0,200** | −0,198 | **0** |
| 40 | 0,191 | 0,484 | **+0,415** | **22** |

**No es monótono.** Si la longitud de frase causara el desfase, esto sería una escalera. 30 es mejor
que 12, y 20 falla igual que 40. Lo que ocurre es que unos cortes parten la zona patológica y otros
no. **Con n=1 historia estos números no ordenan la constante: solo dicen dónde cae la patología.**

## QUÉ HAY QUE HACER

1. **Reproducir la ventana aplastada de forma determinista.** Los artefactos están en disco:
   `test_e2e/temp/video_004_*` (la corrida roja) y `test_e2e/temp/video_003_*` (la verde). El
   detector vive en `tts_engine` (`ANCLA_WPM_MAX = 330`) y su tratamiento es "repartir".
2. **Entender por qué el reparto no basta** en este caso. Ojo: la clase ya tiene tres episodios
   ([ANCLA-03] [ANCLA-04] [ANCLA-05]) y en dos de ellos el fix inicial rompió el gemelo de shorts o
   trató el modo contrario. Lee esas entradas del ledger ANTES de proponer nada.
3. **Arreglarlo y medirlo con el banco que ya existe**: `scripts/anchor_bench.py` corre sobre las
   DOS producciones reales y compara ventana a ventana. El criterio de aceptación que usó [ANCLA-05]
   fue *"0 ventanas empeoran"*, y es el correcto.
4. Solo DESPUÉS, si hiciera falta, volver a mirar `PALABRAS_FRASE_MAX`.

## ESTADO DEL REPO (verificado al escribir esto)

| Cosa | Estado |
|---|---|
| `PALABRAS_FRASE_MAX` | **30** · `target_wpm` **196** (n=2: 197,0 y 195,7; dispersión 0,6%) |
| `/eval` con estas constantes | **NO se ha corrido.** El último verde fue con 12/187; el rojo, con 40/199 |
| Commits | 13 sin pushear. **No hay remoto configurado** (`git remote -v` vacío) |
| Disco | 15 GB libres; una corrida larga pide ~12. `input/` son 13,8 GB (intocable) |
| `pool/` de producción | **vacío**; el chunk vive en `temp/chunk_1786444528.mp4` con un nombre que `take_chunk` NO busca |
| Cuota OpenRouter | 1000/día (10 créditos, verificado por API). **Vuelve a verificarlo, no lo leas de aquí** |

### Lo que la sesión anterior SÍ cerró (no lo rehagas)
Veredicto de auditoría que **caduca** con la huella del auditor [AUDIT-01] · partidor de frases en
código · guardia del título que mutilaba la 1.ª frase y borraba frases legítimas · auditor cortando
por **pausas medidas acústicamente** en vez de por densidad de comas [COMA-04] · `_strip_trailing_metadata`
[BASURA-02] · cue de fin de frase que se iba mientras la voz seguía sonando [SUBT-01] · el `200 con
content=null` que mataba el vídeo con UNA petición [LLM-01].

## TRAMPAS YA PAGADAS (no las repitas)

1. **[INSTR-05] La métrica acústica del auditor es un NETO** (`silencios − signos`) y por eso **no
   localiza**: da 0 mientras el instrumento posicional marca 6 pausas fuera de sitio. Si la usas para
   decir "arreglado", te estás engañando.
2. **[GATE-03] El gate NO es determinista**: genera una historia nueva cada corrida. Para llamar
   regresión a algo hace falta A/B controlado (mismo texto, dos códigos).
3. **La variable que manipulas no puede estar dentro del instrumento con el que eliges.** Así se
   eligió `cada=12`: minimizando `silencios − signos`, y meter puntos **añade signos**. Es [SYNC-01]
   otra vez.
4. **Calibra el emparejador antes de creerle.** El de reloj de habla dio **8% de acierto** sobre
   26 min y sus números eran basura plausible; con Whisper independiente sobre tramos de 420 s,
   98-100%.
5. `target_wpm` depende de `PALABRAS_FRASE_MAX`: si tocas una, **re-mide la otra sobre el AUDIO**.
6. Un fix del alineador puede dar verde en el vídeo largo y **romper los shorts** ([ANCLA-03]).

## LO QUE NO ES TRABAJO DE ESTA SESIÓN

El juicio de si la narración "se entiende" es de Diego. Ya eligió de oído entre cinco versiones
(`output/comparacion_ab/`) y declaró **no distinguir** entre frases de mediana 26, 32 y 43. Eso está
zanjado: no vuelvas a pedirle que escuche variantes de longitud de frase.
