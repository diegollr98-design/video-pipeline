# SEED · Re-auditoría de seguridad ANTES de hacer público `video-pipeline`

> ✅ EJECUTADO (24-ago-2026). Su auditoría destapó el transcript fabricado del README
> —el defecto más grave de la tanda— y tres rondas de datos derivados caducados.

> PASO 0 OBLIGATORIO: invoca /seed-review sobre este SEED antes de tocar nada.

**Pegar al abrir una sesión FRESCA en `C:\Users\<usuario>\Desktop\YOUTUBE`.**
Escrito el 2026-08-24 por la sesión que preparó la publicación. Esa sesión **es parte
interesada**: hizo los cambios que aquí se auditan, así que su veredicto no vale como
control de sí mismo. Ese es exactamente el motivo de este seed.

---

## Objetivo upstream (manda sobre este SEED)

Diego busca trabajo. Su portafolio enlaza **12 veces** a `github.com/diegollr98-design`, y
este repo existe para que ese clic devuelva algo. Va a pasar de **privado a público**.

El objetivo de ESTA tarea no es "aprobar la publicación": es **que no se publique nada que
haga daño**. Daño aquí significa tres cosas distintas, y las tres cuentan:

1. **Un secreto o dato personal** que quede indexado para siempre.
2. **Una vulnerabilidad** que perjudique a Diego o a quien clone el repo y siga sus
   instrucciones.
3. **Una contradicción o falsedad** en el repo que un ingeniero use para concluir que el
   portafolio exagera. El repo vende rigor medido; publicar un fallo de rigor cuesta más
   que no publicar nada.

**Es irreversible.** GitHub indexa al instante; los forks y las cachés no se borran. Hoy el
repo está **privado, con 0 forks y 0 network**, así que todo se puede arreglar. Ese margen
desaparece en el momento del flip.

## Tu encargo, en tres fases y EN ESTE ORDEN

El orden importa. Si lees primero lo que ya se encontró, tu auditoría se convierte en
verificar una lista ajena y dejas de buscar donde nadie miró. **La §3 está al final a
propósito: no la leas hasta terminar la §2.**

### Fase 1 · Reconoce el terreno

```bash
cd C:\Users\<usuario>\Desktop\YOUTUBE
git log --oneline | head -20
git status --short
git ls-tree -r master --name-only | wc -l     # deben ser ~81
gh repo view diegollr98-design/video-pipeline --json visibility,defaultBranchRef,forkCount
```

> AVISO — CORREGIDO por `/seed-review` (24-ago-2026). La instrucción original decía *"audita el
> REMOTO, clona limpio"* y a la vez *"si el remoto va por detrás, dilo y para"*. Las dos a la vez
> son inejecutables: el remoto **va por detrás**, y el único commit que le falta es
> `d12c17f`, el fix entero de `[SEC-01]`. Verificado por los cuatro revisores y por el
> orquestador:
>
> ```
> $ git rev-list --left-right --count master...origin/master
> 1	0
> $ git log --oneline origin/master..master
> d12c17f fix [SEC-01]: auditoria de seguridad previa a publicar — 5 hallazgos cerrados
> $ git diff origin/master master -- .streamlit/config.toml
> +address = "127.0.0.1"             # el remoto NO la tiene: se ata a 0.0.0.0 SIN auth
> $ git show origin/master:.claude/incident-ledger.md | grep -c "SEC-01"
> 0                                  # la Fase 3 es inejecutable sobre el clon
> ```
>
> ⚠️ **CORRECCIÓN de Diego (mismo día), y es una lección de instrumento.** La primera versión de
> este aviso decía que `.streamlit/config.toml` **no existía** en el remoto. Es **FALSO**: existe
> (`git ls-tree origin/master .streamlit/` da el blob `4c9ef89`); lo que le falta es la línea
> `address`. El error no fue de razonamiento sino del instrumento: Git-for-Windows convierte
> `origin/master:.streamlit/config.toml` en `origin\master;.streamlit\config.toml` y `cat-file`
> devuelve "no existe" **sin avisar de nada**. Los comandos con `master:` no se manean (no hay
> barra antes de los dos puntos); los de `origin/master:` sí.
> **Usa `export MSYS_NO_PATHCONV=1` en toda esta auditoría**, o `git ls-tree` / `git diff A B --
> <path>` en vez de `rev:path`. Es `produccion-loop.md` §D en su forma pura: un instrumento roto
> no da error, da un veredicto falso con aspecto de evidencia.

**Audita `master` LOCAL en `d12c17f`**, que es lo que se va a publicar. Clonar el remoto
auditaría el estado **pre-fix**: reportarías como bloqueantes cinco fallos ya cerrados, sobre un
árbol que nadie va a publicar. Confirma antes que no hay nada sin commitear:

```bash
export MSYS_NO_PATHCONV=1   # OBLIGATORIO: ver la corrección de arriba
git status --short          # este SEED + yp.html, ambos sin trackear
git rev-parse master        # debe ser d12c17f
```

> ⚠️ **`yp.html` en la raíz: untracked y SIN ignorar** (199.504 B, creado por el agente ciego del
> `/seed-review` al descargar la página de portafolio; debió ir al scratchpad). **Queda fuera de
> la auditoría y no entra en ningún commit** — decisión de Diego, 24-ago. Ojo con `git add -A`,
> que la barrería dentro de un repo a punto de hacerse público. Es el modo de fallo nº3 de la
> Fase 2b cometido por la propia revisión.

**`git push` es precondición del FLIP, no de la auditoría.** El veredicto no se emite hasta que
`git rev-list --left-right --count master...origin/master` dé `0	0`, verificado en el mismo
minuto del cambio de visibilidad. Publicar desde el estado actual del remoto publicaría el path
traversal de `dashboard.py:362` y el bind a `0.0.0.0` **junto al README que enseña a arrancar el
dashboard**. El push lo pide Diego; tú no lo haces por tu cuenta.

### Fase 2 · Audita por tu cuenta, sin lista previa

Tres ejes. En cada uno, mide y cita `fichero:línea`. **Default escéptico: si no puedes
demostrar que algo es seguro, es un hallazgo.**

**A · Secretos y datos personales, en TODO el historial** (no solo en `HEAD`: al publicar se
publica la historia entera). Claves de proveedor, PEM, JWT, tokens; emails, teléfonos,
DNI/NIF, IBAN, nombres de terceros, URLs a contenido concreto de terceros; identificadores de
cuenta (Google Cloud, OAuth, Canva, Meta, OpenRouter); metadatos embebidos en cualquier
binario (EXIF, XMP, C2PA, ID3); rutas con nombre de usuario; UUIDs. Revisa también los
**mensajes de commit**, no solo el contenido de los ficheros.

> AÑADIDO por `/seed-review`. Este eje nombraba las clases a buscar y **ningún instrumento**, así
> que se cerraba en verde por construcción. Tres correcciones:
>
> - **El sub-eje de binarios está VACÍO y hay que decirlo así.** No hay un solo binario en todo
>   el historial (`git ls-tree -r master --name-only | grep -Ei '\.(png|jpg|mp3|mp4|ico)$'` da
>   vacío). Reporta **"0 binarios versionados"**, nunca *"metadatos limpios"*: examinar el
>   conjunto vacío y cantar verde es el default permisivo que `decision-making.md` §16 prohíbe.
> - **No hay gitleaks / trufflehog / exiftool en la máquina.** El barrido será tuyo, a mano,
>   sobre 366 blobs / ~9,9 MB. **Calíbralo antes de fiarte**: planta un `sk-or-v1-XXXX` en un
>   fichero temporal FUERA del repo y comprueba que tu propio regex lo caza. Un barrido con 0
>   hits y exit 0 es indistinguible de un repo limpio — le pasó a un revisor en esta misma
>   sesión, con una clase de caracteres mal cerrada que devolvió cero líneas sin error.
> - **Los metadatos de commit no viven en ningún blob**, así que un grep sobre ficheros los da
>   siempre limpios. Cúbrelos aparte: `git log --all --format='%an <%ae>' | sort | uniq -c`.

**B · Vulnerabilidades del código** (~13.000 LOC de Python). Calibra la severidad con el
modelo de amenaza real: es un pipeline **local y mono-usuario**, no un servicio expuesto.
Pero al publicarse, (i) cualquiera lee el código buscando fallos, (ii) cualquiera lo clona y
lo ejecuta, así que un fallo que dañe a quien clone cuenta igual. Mira al menos: ejecución de
comandos (el repo usa FFmpeg intensivamente), path traversal en nombres derivados de entrada
externa **o de la salida del LLM**, deserialización, manejo de credenciales en ejecución
(¿se imprimen en logs o en pantalla?, ¿con qué permisos se guardan?), red (timeouts, SSRF,
qué se envía a dónde), el dashboard de Streamlit (dirección de escucha, autenticación, si
ejecuta comandos construidos con entrada del usuario) y las dependencias.

> AÑADIDO por `/seed-review`. Tal como estaba escrito, este eje se cierra con tres greps
> (`shell=True`, `os.system|eval|exec`, `pickle|yaml.load`) que dan **0 ocurrencias** en 30
> segundos, y los ~13.000 LOC quedan "auditados" sin haber mirado nada. Exige evidencia:
>
> - Para cada uno de los **33 `subprocess.*`** del repo, demuestra que el argv es una **lista** y
>   di de dónde sale cada elemento. Ese es el entregable, no "0 `shell=True`".
> - Audita las **cadenas interpoladas dentro de `-filter_complex`**, que el grep no alcanza:
>   `video_composer.py:84,124,142` y `shorts_generator.py:505,549,564` escapan `\` y `:` de la
>   ruta del `.ass` pero **no `'`**, y la meten entre comillas simples. Severidad baja (la ruta
>   sale de `config.yaml`, no de un atacante), pero rompe a quien clone con un apóstrofo en su
>   usuario de Windows. **Es un par gemelo** (`video_composer` <-> `shorts_generator`, §11): mira
>   los dos.

**C · Coherencia y veracidad. <- ESTE ES EL EJE DOMINANTE, no el tercero.** El agente ciego
del `/seed-review`, que derivó el objetivo sin ver este SEED, llegó a esta conclusión: con **0
secretos** encontrados en los 366 blobs del historial, el modo de fallo caro ya no es una fuga
—es una **auto-refutación dentro del repo**, encontrada por el ingeniero al que Diego quiere
impresionar, que hace grep en vez de ojear. El repo son 5.694 líneas de prosa sobre su propio
rigor contra 13.410 de Python: **esa prosa es la prueba, y es la superficie que puede refutar la
tesis del portafolio.** Audítalo primero y con el presupuesto grande.

El repo publica cifras como prueba (`data/eval/*.json`, y el
README las cita). Comprueba que **cada cifra que el README afirma existe en el fichero que
dice** y vale lo que dice. Y que el repo no se contradice a sí mismo: `CLAUDE.md`,
`.claude/rules/*.md` y `.claude/incident-ledger.md` se publican a propósito — busca
afirmaciones caducadas presentadas como estado actual. Es la clase de fallo recurrente de
este proyecto y tiene id propio: `[DOC-01]`.

> AÑADIDO por `/seed-review`. El criterio *"cada cifra que el README afirma existe en el fichero
> que dice"* es vacuo donde no hay fichero: **de 16 líneas del README con cifras, solo 1-2
> enlazan un `data/eval/*.json` versionado**; el resto cita prosa o una salida de script cuyo
> artefacto (`temp/`, `.ass`) está gitignored. Aplicarlo al pie de la letra produce *"todas las
> cifras verificadas"* habiendo verificado una. Separa en (i) respaldadas por JSON versionado —
> verifícalas al dígito — y (ii) no verificables desde el repo publicado, y **di cuántas son de
> cada clase en el informe**.
>
> **Excepción al aislamiento de la §3** (solo para este eje): un dato externo caducado no se
> distingue de uno verdadero por consenso entre ficheros del repo — `transversal.md` T1. Si N
> ficheros dicen A y uno dice B, eso **no** hace ganar a A. Antes de juzgar el eje C, lee de
> `.claude/incident-ledger.md` **solo los datos externos corregidos** de `[QUOTA-02]`/`[QUOTA-02b]`
> (no sus arreglos ni sus verificaciones, que siguen en la Fase 3).

### Fase 2b · Los tres modos de fallo que hundieron a la sesión anterior

No son teoría: le pasaron los tres el mismo día. Protégete de ellos.

1. **Aceptar el informe de un agente sin verificarlo.** Un auditor afirmó que cierta línea
   era "un comentario, o sea prosa" cuando era una entrada de tabla que el código consulta en
   ejecución. La conclusión era buena y la razón falsa. **Corre tú el comando y pega la
   salida real.**
2. **Aceptar una corrección sin comprobar el lado correcto.** Un dato se verificó en el
   repo… cuando la afirmación en disputa era sobre cómo lo enmarcaba OTRO documento. Se
   revirtió una conclusión acertada por mirar la mitad equivocada del problema. **Antes de
   cambiar de postura, identifica dónde vive de verdad la afirmación.**
3. **Un arreglo que introduce su propio defecto.** Un cambio de configuración hecho por la
   mañana creó, esa misma tarde, una fuga de credenciales por otro camino. **Todo lo que se
   arregló en las últimas 24 h es sospechoso**, no está bendecido.

### Fase 3 · SOLO cuando termines la fase 2 — coteja

Ahora sí, abre `.claude/incident-ledger.md` y busca las entradas **`[SEC-01]`** y
**`[QUOTA-02]` / `[QUOTA-02b]`**. (Ojo: `[SEC-01]` **no existe** en `origin/master` — la añadió
el commit sin empujar. Cotéjala contra el ledger de `master` local, y comprueba que el ledger
llega al remoto antes del flip.) Describen lo que la sesión anterior encontró y arregló,
con las verificaciones que dice haber hecho.

Tu trabajo con ellas es doble:

- **¿Se te escapó algo que ellos vieron?** Si sí, tu método tiene un hueco: dilo.
- **¿Los arreglos aguantan de verdad?** No te fíes de la verificación que el ledger declara:
  **reprodúcela**. En particular, para cada arreglo pregunta las dos cosas que fallaron aquí
  antes (`decision-making.md` §17, 2.º corolario): (a) ¿el guardia se aplica en **todas** las
  rutas, o solo en la que se vio el fallo?, y (b) ¿inspecciona **todo** el objeto, o solo la
  parte donde ya se vio? Y la pregunta gemela de `§11`: **¿esto tiene gemelo?** — este repo
  tiene pares conocidos (`video_composer` ↔ `shorts_generator`, `video_cleaner` ↔
  `gameplay_pool`, historia larga ↔ short) y los fixes se han quedado a medias más de una vez.
- **¿El propio arreglo abrió algo?** Ver el modo de fallo nº 3 de arriba.

## Lo que la sesión anterior NO pudo verificar (dilo tú si lo consigues)

- Si el reparto de cuota de la YouTube API que Google documenta hoy coincide con el asignado
  **al proyecto concreto de Diego**. Está en su consola de Google Cloud y nadie ha mirado.
  Afecta a `config.competition.quota.limits`: hoy el error del contador cae del lado
  **permisivo**, y está declarado como tal en `config.yaml`.
- Si `prompts/reddit_story.txt` sigue produciendo lo mismo tras una reescritura de una línea:
  es superficie sensible y **no ha pasado por `/eval`**. No bloquea la publicación (no toca
  sincronismo), pero no está medido y hay que decirlo.
- Si el historial conserva juicios sobre canales de terceros identificados por nombre. **Sí
  los conserva** y es una decisión consciente de Diego.
  > CORREGIDO por `/seed-review`: la premisa *"`HEAD` está limpio"* es **FALSA**, y la magnitud
  > que se le describió a Diego se quedó corta. Medido:
  > - `config.yaml:159-164` nombra a **cuatro** canales reales en HEAD, bajo la cabecera
  >   `# ruido confirmado`, que es un juicio editorial que sobrevivió a `0428310`.
  > - El **gemelo no se propagó** (§11): `test_e2e/config.yaml:57-61` nombra a los mismos cuatro.
  > - **120 de 126 commits** llevan en `CLAUDE.md` a cinco canales nombrados como *"granjas de
  >   drama asiático doblado"*; no son "decenas de commits", es el 95% de la historia.
  > - El propio commit `0428310`, que borraba la nota, **la recita íntegra en su mensaje**
  >   (`"rBarra Historias (124k subs, gameplay 100%) - el modelo lo descarto por..."`). Neto:
  >   cero. Y un mensaje de commit es lo único que no se arregla editando un fichero.
  >
  > No lo cambies tú: **cuantifícalo y preséntaselo a Diego como decisión suya**. Un OK dado
  > sobre un alcance mal descrito no cubre el alcance real. Lo que HEAD nombra sí se puede
  > editar barato; el historial no.

## Lo que NO tienes que hacer

- **No hagas público el repo.** Lo decide Diego, y solo si te lo pide en ese mismo mensaje.
- **No compartas la URL** con nadie ni en ningún sitio.
- **No reescribas el historial** sin plantearlo antes: ya se hizo una purga deliberada y
  volver a tocarlo cambia todos los hashes otra vez (y hay referencias a hashes dentro de la
  documentación).
- **No juzgues el producto.** Que el proyecto genere contenido automático no es un hallazgo
  de seguridad.
- **No borres `pool/`, `input/`, `output/` ni `test_e2e/input/clip.mp4`.**

## Cómo se sabe que salió bien

Un informe que Diego pueda leer en cinco minutos y que termine en **una** de estas dos
frases, sin ambigüedad:

- **PUEDE PASARSE A PÚBLICO** — acompañado de, para cada eje, el comando que lo demuestra y
  su salida real. No "revisé y está bien": la salida.
- **NO PUEDE, por X** — con el hallazgo concreto, `fichero:línea`, cómo se explota o qué
  expone, y el arreglo mínimo.
- **PUEDE, PERO DIEGO DECIDE X PRIMERO** *(tercera salida, añadida por `/seed-review`)* — para
  lo que no es un fallo técnico sino una exposición cuyo remedio está vetado o es suyo: qué
  expone, a quién, en cuántos commits, y las opciones (dejarlo / editar HEAD / reescribir
  historial / repo nuevo sin historia), **sin recomendar una**. Sin esta salida, un hallazgo real
  cuyo arreglo mínimo está prohibido empuja mecánicamente hacia *PUEDE PASARSE A PÚBLICO*.
  Ordena además los hallazgos **por consecuencia**: cinco triviales y uno irreversible no pueden
  leerse igual en cinco minutos.

Y una lista explícita de **lo que no pudiste verificar**, que es tan parte del informe como
lo que sí. Un "todo limpio" sin límites declarados es la respuesta sospechosa.

## Contexto operativo mínimo

- Rama por defecto y única publicada: `master`. Repo: `diegollr98-design/video-pipeline`.
- `gh` está autenticado como `diegollr98-design`.
- El árbol de trabajo son ~17 GB, el 99,9 % ignorado (`output/`, `test_e2e/`,
  `shorts_tiktok/`, `pool/`). Lo versionado son ~81 ficheros / ~1,5 MB.
- `config.yaml` lleva rutas **relativas**; las reales de esta máquina viven en
  `config.local.yaml`, que está gitignored. Si necesitas correr el pipeline, ya funciona.
- Las reglas del repo (`CLAUDE.md`, `.claude/rules/*.md`) se auto-cargan. La que más aplica
  aquí es la de `produccion-loop.md` §A: **verificación por ejecución, nunca por informe.**
