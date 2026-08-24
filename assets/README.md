# `assets/` — qué va aquí y por qué falta

Dos de los archivos que el pipeline usa **no se distribuyen con el repositorio**:
son material de terceros y la licencia MIT de este proyecto no puede cubrirlos
(ver `LICENSE`). Siguen haciendo falta para que la salida quede completa, así que
aquí está qué son y cómo reponerlos.

El pipeline **corre igualmente sin ellos**: avisa por log y sigue. Lo que pierdes
es la plantilla de la miniatura/intro y el sonido de la intro.

## `3.png` — plantilla de miniatura e intro (1280×720, PNG con transparencia)

Tarjeta estilo publicación de foro que se superpone al gameplay: sobre ella se
dibuja el título en mayúsculas. Es también la que entra deslizándose en la intro
animada del vídeo.

No se incluye porque la composición original lleva marcas de terceros (mascota de
Reddit, iconos de premios de Reddit, insignia de verificado estilo X/Twitter).

**Para reponerla:** cualquier PNG de 1280×720 con fondo transparente en la zona
donde debe ir el texto sirve. El código no asume nada del diseño más allá del
tamaño; `modules/thumbnail_generator.py` la superpone al frame de gameplay y
escribe el título encima.

**Si prefieres una equivalente sin marcas de terceros**, componla tú: un
rectángulo redondeado claro sobre fondo transparente, con espacio libre en el
centro, es funcionalmente idéntico.

## `stereogenicstudio-swish-swoosh-woosh-sfx-27-357164.mp3` — *woosh* de la intro

Efecto de sonido que acompaña la llegada de la tarjeta al centro de la pantalla.
El código espera que el **pico** del efecto caiga alrededor de los 0,25 s
(`WOOSH_PEAK` en `modules/video_composer.py` y `modules/shorts_generator.py`), y
sincroniza el resto a partir de ahí.

Es un efecto de banco de sonido de stock: su licencia permite usarlo, no
redistribuir el archivo suelto.

**Para reponerlo:** cualquier *whoosh*/*swish* corto (< 1 s) sirve. Descarga uno
con licencia CC0 o equivalente, déjalo en esta carpeta y ajusta la constante
`WOOSH_PATH` si le pones otro nombre. Si su pico no está en 0,25 s, ajusta
`WOOSH_PEAK` en los dos módulos — son gemelos y ambos lo usan.

## Lo que sí se versiona

- `roadmap.html` — la vista de roadmap que embebe el dashboard.
- `.tint_index` — contador de rotación de color de las miniaturas (ángulo áureo),
  para que dos miniaturas seguidas nunca salgan del mismo color.
