# Mediciones de longitud de frase y comas (ago 2026)

Datos crudos de los barridos que justifican `_ensure_breathing_commas` y la decisión de **no** partir
las frases largas. Las **conclusiones** viven en `CLAUDE.md`; aquí están las tablas que las sostienen,
para no pagarlas en el contexto de cada sesión (`file-organization.md`: referencia voluminosa → `docs/`).

## A. Variantes de escritura vs pausas de edge-tts

Mismo contenido, cuatro formas de escribirlo. "Pausas inesperadas" = silencios que NO caen en un signo
de puntuación, medidos con `ffmpeg silencedetect`.

| Variante | Pausas inesperadas | Ventana de anclaje | pal/min |
|---|---|---|---|
| Frase larga (49 pal) SIN comas | 2 | 50 palabras | 207 |
| Frase larga CON comas | 0 | 50 palabras | 204 |
| Frases cortas (12-16 pal) | 0 | 12 palabras | **172** |
| **Frases medias (20-25 pal) + comas** | **0** | **22 palabras** | **198** |

Lectura: las frases cortas también eliminan las pausas inventadas, pero la pausa en punto es de
**1,1-1,3 s** frente a 0,3-0,6 s en coma → narración entrecortada y **19% más de duración**
(~4 min de silencio extra en un vídeo de 30 min). Ganador: **15-25 palabras con una coma cada 8-12**.

## B. Distribución real de longitud de frase

Muestra de 10 historias generadas (417 frases, 16.048 palabras):

| Longitud | % frases | % palabras |
|---|---|---|
| ≤25 palabras | 18,0% | 9,3% |
| 26-40 | 44,1% | 37,5% |
| 41-60 | 28,3% | 35,2% |
| 61-100 | 9,4% | 17,4% |
| >100 | 0,2% | 0,7% |

Mediana 36 palabras, percentil 90 en 60, máximo observado 105. Una frase de >100 palabras sale
~1 vez cada 10 historias.

Lectura: **no hay que partirlas.** Con contenido real, una frase de 95 palabras da 0,19-0,21 s de error
máximo de sincronismo (estable en 3 repeticiones), igual o mejor que una de 25 — el anclaje por
traslación aguanta ventanas largas. Y con `_ensure_breathing_commas` activo, 0 de 10 historias salieron
sin comas (antes 2 de 4), así que el problema real de las frases largas —las pausas inventadas— ya está
resuelto aguas abajo.

## C. El prompt no consigue las comas (por eso se imponen en código)

4 generaciones con la regla puesta en el prompt: **167, 129, 0 y 0 comas**, con frases de 19 a 67
palabras de media y máximos de 116. El prompt ORIGINAL oscilaba igual (20, 139, 163). No es una
regresión de la regla: el modelo alterna entre dos modos (frases largas con comas / frases medias sin
ninguna) y **ninguno cumple**. Ver `decision-making.md` §17.
