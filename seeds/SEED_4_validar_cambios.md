# SEED — Validar en paralelo que los últimos cambios son óptimos

> PASO 0 OBLIGATORIO: invoca /seed-review sobre este SEED antes de tocar nada.

## Qué es esto

El pipeline de `c:\Users\diego\Desktop\YOUTUBE` recibió en agosto de 2026 una tanda de
cambios que arreglaron fallos reales, **medidos**. Todos funcionan. Lo que NO está
comprobado es si los **parámetros y decisiones de diseño elegidos son los mejores
posibles**: se eligieron con 1-2 mediciones cada uno, a veces con muestras pequeñas.

Tu trabajo NO es comprobar que funcionan (ya se hizo). Es **retarlos con datos**:
probar alternativas, barrer parámetros y decir con números si hay algo mejor.

Lee `CLAUDE.md` antes de empezar: contiene la medición que motivó cada cambio y los
valores obtenidos. Es tu línea base; tu trabajo es superarla o confirmarla.

## Cómo ejecutarlo

**Lanza los agentes EN PARALELO, uno por bloque.** Son independientes: cada uno toca
una dimensión distinta y ninguno depende del resultado de otro. Cada agente debe:

1. Medir la línea base actual con su propio experimento (no fiarse del número de CLAUDE.md).
2. Probar al menos 2 alternativas al valor/diseño actual.
3. Devolver una tabla con números y un veredicto: **mantener / cambiar a X / no concluyente**.
4. NO aplicar cambios al repo. Solo medir y reportar. El cambio lo decide el usuario al final.

## Presupuesto y reglas que TODOS deben respetar

- **OpenRouter**: 1000 peticiones/día a modelos `:free` (hay 10 créditos comprados).
  Es un presupuesto COMPARTIDO entre todos los agentes. Que cada uno declare cuántas
  llamadas va a hacer antes de empezar y no pase de ~120.
- **NO usar texto repetido como fixture de sincronismo.** Un test que repetía el mismo
  párrafo 4 veces dio 2,525s de error falso, idéntico en 3 de 5 corridas. El emparejador
  engancha la copia equivocada. Los fixtures deben tener contenido no repetido.
  (Documentado en CLAUDE.md, sección "Trampa al medir sincronismo".)
- **NO borrar `data/`** (estado de competencia acumulado, 221 canales) ni `input/`
  (13 GB de gameplay del usuario). Si un experimento necesita un `data/` limpio, muévelo
  y restáuralo. Un test lo borró una vez y costó rehacer varios escaneos.
- **Un E2E NO necesita los 13 GB**: extraer un clip de ~3 min con ffmpeg a un `input_dir`
  propio + config con `target_duration_min` bajado. Receta en CLAUDE.md.
- **Verificar con ejecución real**, no leyendo el código ni con tests simulados.
  Si mides sincronía, transcribe el audio del vídeo FINAL y compara con los fotogramas.
- Trabaja en `test_e2e/` o en un directorio temporal propio, nunca en `output/`.

## Bloques (uno por agente)

### A. Anclaje de subtítulos: ¿traslación es lo óptimo?
`modules/tts_engine.py::_validate_and_fix_alignment` pasó de repartir las palabras
proporcionalmente por caracteres a **trasladar** los tiempos de Whisper anclando el
inicio de cada frase. Línea base declarada: error medio 0,146s, máximo 0,248s, sesgo −0,146s.

Retar: ¿hay algo mejor que la traslación pura? Prueba al menos:
- traslación (actual)
- mapa afín (estirar al ancho de la ventana) — se descartó, confirma por qué
- traslación + anclaje adicional en cada coma detectada
- usar los tiempos de Whisper crudos sin ninguna ancla

Mide error medio, máximo y **sesgo** (el signo importa: el diseño quiere que la voz
vaya ligeramente ANTES que el subtítulo) sobre varios textos distintos y no repetidos.
Comprueba también si el `-itsoffset -0.10` de `video_composer` sigue siendo el valor
adecuado dado el sesgo que ahora tiene el anclaje.

### B. Inserción de comas: ¿umbrales y conectores correctos?
`modules/tts_engine.py::_ensure_breathing_commas` inserta comas de respiración porque
el modelo no obedece cuando se le pide (medido: 167, 129, 0 y 0 comas en 4 generaciones).
Usa `PALABRAS_RESPIRO = 10` y `PALABRAS_LIMITE = 16` y dos listas de conectores.

Retar:
- Barre los umbrales (p. ej. 6/10, 8/14, 10/16, 12/20) y mide **pausas inesperadas**
  (huecos > 0,25s que NO caen tras puntuación) con TTS real.
- ¿Alguna coma insertada es gramaticalmente incorrecta en español? Revisa una muestra
  grande de inserciones reales. Es el riesgo principal de este enfoque.
- Revisa la lista `_CONECTORES_SEGUROS`: tiene entradas duplicadas ("aunque" repetido
  varias veces). Comprueba si falta alguno importante o sobra alguno peligroso.
- **INVARIANTE que no se puede romper**: no debe cambiar el número de palabras
  (`main.py` lo usa para calcular cuándo acaba el título y arrancar la intro).

### C. `target_wpm`: ¿195 es el número correcto?
Se subió de 150 a 195 porque la voz habla a ~200 ppm y se desperdiciaba el 31% del
gameplay. Dos corridas dieron 96% y 104% de aprovechamiento.

Retar:
- Mide la velocidad real (palabras/minuto del audio generado) sobre >=10 historias y
  distintos estilos (`dramatic`, `horror`, `funny`, `wholesome`) y ambas voces.
  ¿Es estable o depende del estilo?
- ¿Cuál es el valor que minimiza |duración_vídeo − duración_chunk|?
- Ojo al efecto de las comas insertadas (bloque B): añaden pausas y bajan las ppm.
  Si B cambia los umbrales, C debería recalcularse.
- Comprueba qué pasa si el audio sale MÁS LARGO que el gameplay (debería repetirlo con
  `loop_gameplay`) y si el corte queda bien.

### D. Validación de la salida del LLM: ¿falsos positivos?
`modules/script_generator.py::_validar_salida` descarta generaciones donde el modelo
suelta su razonamiento (caso real: título "The user wants a viral micro-story script...").
Comprueba longitud de título, marcadores de razonamiento, que parezca español y tamaño del speech.

Retar:
- Genera >=30 historias reales y cuenta: cuántas se descartan y **cuántas se descartan
  siendo válidas** (falso positivo = historia buena tirada a la basura, cuesta una
  petición y tiempo). Revisa a mano las descartadas.
- ¿Con qué frecuencia aparece de verdad el razonamiento? Si es <1%, ¿compensan 3 reintentos?
- ¿Los umbrales (título 12-45 palabras en largos, 8-45 en shorts; speech >=200 / >=80)
  son correctos? ¿Descartan títulos legítimos de 20-35 palabras?

### E. Anti-repetición de shorts: ¿aguanta 30 shorts?
`modules/shorts_generator.py::_build_avoid_block` pasa los títulos ya generados. Medido
con 5 shorts: similitud media 0,48 -> 0,01. Pero limita la lista a los **12 últimos**.

Retar:
- Un vídeo de 30 min genera ~30 shorts. Mide la similitud con N=30 en cadena.
  ¿Se degrada al pasar de 12 (cuando empieza a olvidar los primeros)?
- ¿El límite de 12 es el correcto, o conviene resumir temas en vez de listar títulos?
- Mide también el coste: cuánto crece el prompt y si eso afecta a la calidad o al rate limit.
- Comprueba que arrastrar títulos de corridas ANTERIORES desde disco funciona
  (`generate_shorts_for_video` lee `shorts_dir`).

### F. Análisis de competencia: ¿los umbrales filtran bien?
`config.yaml` sección `competition`. Valores elegidos con una muestra: `outlier_cap: 5.0`,
`min_views: 3000`, `min_duration_min: 8`, pesos 0.40/0.30/0.20/0.10, `min_subscribers: 5000`.

Retar, usando el `data/competition_report.json` y `data/competitors.json` REALES (solo
lectura, o copia):
- ¿El ranking cambia mucho al mover los pesos? ¿Es estable o frágil?
- ¿`min_views: 3000` deja fuera competencia legítima pequeña, o hace falta subirlo?
- ¿El clasificador por LLM tiene falsos positivos/negativos? Revisa a mano los 28-31
  canales activos y los rechazados por "fuera de nicho".
- Recuerda el nicho REAL: historias de Reddit en primera persona **con gameplay de fondo**.

## Entregable

Un informe único con una sección por bloque. Cada sección: tabla de resultados,
veredicto (**mantener / cambiar a X / no concluyente**) y, si propone cambio, el diff
exacto. Al final, una lista ordenada por impacto de los cambios recomendados.

Si un bloque no llega a conclusión con los datos obtenidos, dilo. Es una respuesta
válida y preferible a inventar una recomendación.
