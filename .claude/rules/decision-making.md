# Reglas de Decisión — YOUTUBE

> Agnóstico de dominio. Portado de `Resellermaster`/`escoltaeliteapp` (donde estas reglas se ganaron
> a base de incidentes) y **re-anclado a los episodios REALES de este repo**, que están documentados
> en `CLAUDE.md` §"Decisiones técnicas críticas". Ninguna cita de aquí es hipotética.
>
> Este archivo **no se auto-carga**: léelo cuando la situación lo pida (lo dice `CLAUDE.md`).

---

## 1. Ancla en el plan de Diego, no en la cultura del repo
Los defaults conservadores (diff mínimo, "validar antes de actuar", no over-engineer) son para
situaciones **ambiguas** — no son overrides de un plan explícito. Si Diego declaró un plan, el trabajo
que implica **se hace**; ayúdale a ejecutarlo, no le ofrezcas la alternativa más barata como
contra-recomendación.

## 2. "¿Seguro?" / repetir / "no colaboras" = PARA y reanaliza
Si pushea, repite algo o duda de tu respuesta, ha detectado algo que se te escapó. Reanaliza desde SU
marco, sin defender tu posición previa.

## 3. No añadas fricción a propuestas correctas
Si su propuesta es buena, ejecútala. Los caveats defensivos cuestan tiempo y no protegen de nada.

## 4. Verifica con datos/código REALES y con la herramienta CORRECTA
Lee el código, no la doc — la doc se desactualiza. Y si un resultado sale 0 o contraintuitivo,
**sospecha de la herramienta antes de concluir**. Precedente medido aquí: los errores de FFmpeg se
registraban con los primeros 500 caracteres de stderr, que son el **banner de compilación** — el error
real quedaba fuera del log y el diagnóstico se hacía a ciegas.

## 5. Verifica el código antes de preguntar a Diego
Si la respuesta está en un archivo, léela. Preguntar lo que se puede leer es gastarle tiempo.

## 6. Anti-loop
Máximo **2 rondas** de debate sobre una misma decisión (aplica también a un debate entre agentes, no
solo al código). Tercera ronda → decide, dilo, y sigue.

## 7. Challenge-the-premise — valida el enfoque antes de optimizarlo
Antes de afinar parámetros, comprueba que el mecanismo es el correcto. Precedente aquí: durante meses
se afinaron los subtítulos asumiendo que el reparto proporcional dentro de la ventana de
`SentenceBoundary` era correcto. No lo era — la ventana **tila el audio entero, silencios incluidos**,
y ningún ajuste de parámetros iba a arreglar eso. El fix fue cambiar de mecanismo (traslación en vez de
reparto), no de constante: error medio 0.502s → 0.146s.

## 8. Implementar > debatir, según reversibilidad
Un cambio reversible y barato: hazlo y mídelo. Un cambio caro o irreversible (borra pool/, gasta cuota
de la API de YouTube, consume peticiones del tope diario de OpenRouter): plantéalo antes.

## 9. Escala honestamente
Si algo no funciona o no lo sabes, dilo con la evidencia. No lo maquilles ni compenses con hedging.

## 10. No especules sin datos
Nada de "esto debería mejorar la calidad". O lo mides o no lo afirmas.

## 11. Bug en un path → revisa los paths ANÁLOGOS
Y las **etapas** análogas del flujo, no solo las funciones que se parecen. Aquí el flujo es
`ingesta → pool → historia → TTS → alineación → subtítulos → composición → miniatura → shorts`.
Precedente vivo: `video_composer` y `shorts_generator` comparten intro animada, woosh, subtítulos y
alineación, pero con PlayRes, posición y velocidad distintas — un fix en uno casi siempre tiene gemelo
en el otro, y el de shorts es el que nadie mira.

## 12. Defensas con dientes — no basta con avisar
Una comprobación que solo imprime un warning no defiende de nada, porque el pipeline es autónomo y
nadie lee el log en tiempo real. O corta, o marca el output de forma visible, o no es una defensa.

## 13. Nunca fallback silencioso
`except Exception: pass`, un valor por defecto que se traga un error, o un segmento que falla y aun así
se añade a la lista — todos convierten un fallo en invisible. Log ruidoso + propagar + marcar la salida.
Precedente: un segmento que fallaba al extraerse se añadía igualmente a `concat_list.txt` y reventaba el
concat entero con un error incomprensible.

## 14. Mentalidad proactiva
Si al arreglar algo ves otra cosa rota en el camino, dilo (y arréglala si es del mismo alcance). No la
dejes para que la encuentre una corrida de producción de 40 minutos.

## 15. El coste es ciudadano de primera clase
Aquí el coste **no es dinero, es cuota**: el tope de **50 peticiones/día** de los modelos `:free` de
OpenRouter y las **10.000 unidades/día** de la YouTube Data API. Un cambio que sube las peticiones por
vídeo es un cambio de arquitectura disfrazado: dilo y recalcula, aunque nadie lo pregunte.

## 16. Prueba el CASO DE FALLO — el default tiene que caer del lado barato
Un gate nuevo es superficie nueva. Antes de darlo por bueno, pásale sus valores degenerados: el
conjunto **vacío**, el dato **ausente**, el valor **desconocido**. Y desconfía de tus propios tests
verdes si todos comparten un fixture que fija el caso feliz — eso es un punto ciego, no cobertura.
Precedente medido aquí: un fixture de sincronismo construido **repitiendo el mismo párrafo 4 veces**
daba 2,525s de error, idéntico en 3 de 5 repeticiones. No era desfase: el emparejador enganchaba la
copia equivocada. **Un valor idéntico entre corridas es la firma de un artefacto del test.**

## 17. Una garantía prometida en PROSA no está garantizada hasta que un `if` la fuerza
Es la regla más cara de este repo y ya tiene **tres** episodios:
- **Las comas.** Pedirlas en el prompt no funcionó: 4 generaciones dieron 167, 129, **0 y 0** comas. Se
  impusieron en código (`_ensure_breathing_commas`).
- **El título.** "Empieza el speech con el título" tampoco se sostenía en el prompt →
  `_ensure_title_at_start` lo fuerza.
- **La variedad de los shorts.** El prompt decía "la historia debe ser DISTINTA a cualquier otra" y el
  modelo **no podía saber cuáles eran las otras**: los 4 shorts salieron con el mismo argumento. Se
  arregló pasándole los títulos ya generados (`avoid`).

Corolario: **un comentario que afirma una garantía no la implementa.** Si lees `# esto nunca puede
pasar`, ve a comprobar qué lo impide.

## 18. Un juicio que el modelo NO puede dar se vuelve determinista o hueco
Cuando una decisión exige algo que el LLM no puede aportar de forma fiable, no le pidas su mejor
intento: conviértela en una regla determinista sobre una señal que controlas, o déjala fuera. El
"mejor intento" en esos campos produce **ruido plausible**, que es peor que un hueco porque nadie lo
detecta. (Es lo mismo que §17 visto desde el lado del modelo.)

## 19. Verde local ≠ funciona — y mide DÓNDE está el problema antes de optimizar
`python -m compileall` limpio, el dashboard arranca y el pipeline "termina sin error" son compatibles
con una salida rota. Precedente definitivo: el demuxer `concat` **nunca funcionó** (resolvía las rutas
relativas respecto al directorio del fichero de lista, no del cwd) y nadie lo notó porque la única
corrida real que existía era >95% gameplay y tomaba el atajo de `-ss/-to`. Cualquier grabación con
pausas —el caso para el que existe el módulo— abortaba la ingesta entera.

Consecuencias duras:
1. Un cambio en una superficie sensible (`produccion-loop.md` §B) **no se cierra sin `/eval`**.
2. Correr con `--no-shorts` **oculta una clase entera de fallos**. Si tocaste algo que los shorts
   comparten, tienes que generarlos.
3. Verifica sobre el caso que el módulo existe para cubrir, no sobre el caso fácil que pasa siempre.
