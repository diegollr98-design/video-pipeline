# Loop de Cambios — YOUTUBE

**Protocolo obligatorio.** Cada vez que Diego proponga un **cambio, añadido o feature** que implique
tocar código, prompts o config, ANTES de diseñar el plan o tocar nada: anúncialo en una línea
(*"esto activa el Loop de Cambios"*), recomienda correrlo o saltarlo según §B de
`produccion-loop.md`, y espera su OK.

Para retoques triviales de **una sola superficie no sensible**, basta con anunciar que se salta el
ritual pesado y proceder. Nunca al revés: nunca el ritual pesado sin avisar, ni saltarlo en algo que
cruce una costura sensible.

---

## A. Antes de escribir código

1. **¿Qué superficie toca?** (`produccion-loop.md` §B). La respuesta decide toda la ceremonia.
2. **Lee el archivo end-to-end y `grep` el símbolo y sus call sites.** La doc se desactualiza; el
   código es la verdad. `CLAUDE.md` es excelente pero describe agosto de 2026, no necesariamente hoy.
3. **Enumera los invariantes que viven en varios sitios** (`produccion-loop.md` §B) antes de fasear.
   Tocar uno dispara revisar todos — incluida siempre la pregunta *"¿esto tiene gemelo en shorts?"*.
4. **Debate como máximo 2 rondas** (`decision-making.md` §6). El que debate **lee el código real**, no
   discute en abstracto.

## B. Antes de dar un cambio por cerrado

1. `git diff` — lee cada hunk. (`git commit -m "pre-fix ..."` **antes** de editar.)
2. `PYTHONUTF8=1 python -m compileall -q modules main.py dashboard.py dashboard_runner.py` limpio.
3. **Superficie sensible → `/eval`.** Compara con el baseline. Si empeora, el cambio no se cierra:
   no es un aviso, es un no.
4. **Si tocaste algo que los shorts comparten → genera shorts.** Correr con `--no-shorts` oculta una
   clase entera de fallos (precedente: los 4 shorts con la misma historia).
5. **Si tocaste `_call_openrouter`, los prompts o `shorts_generator` → recalcula y reporta las
   peticiones por vídeo**, aunque nadie lo pregunte. El tope diario es real, pero **su valor se
   verifica con la API, no se lee de un `.md`** (`decision-making.md` §15).
6. **Superficie sensible → pásalo por `output-audit`.** El self-review es el modo de fallo documentado.
7. `git commit -m "fix ..."`.

## C. Verde local ≠ funciona

`compileall` limpio, el dashboard arranca y el pipeline "termina sin error" son perfectamente
compatibles con una salida rota — el demuxer `concat` estuvo roto **desde siempre** con todo en verde
(`decision-making.md` §19). Reglas:

1. Verifica sobre **el caso que el módulo existe para cubrir** (una grabación CON pausas, no el clip
   que es 95% gameplay y toma el atajo de `-ss/-to`).
2. **Un gate nuevo es superficie nueva:** pásale el conjunto vacío, el dato ausente y el valor
   desconocido antes de cantar victoria (`decision-making.md` §16).
3. **Ningún fallback silencioso** puede tragarse un error (`decision-making.md` §13).

## D. Retro

Al cerrar una corrida que **tocó superficie sensible o cazó un defecto** (no en retoques triviales),
añade **una entrada factual** a `.claude/incident-ledger.md`: qué pasó, evidencia real, clase, id.
**El retro no edita reglas** — solo `/optimize` promueve (`produccion-loop.md` §E).

Y actualiza `.claude/rules/sessions-log.md` si el hito lo merece.

## Reglas de oro que este loop NO sustituye

- **Nunca `git push` sin que Diego lo pida en ese mismo mensaje.**
- **Nunca borrar `pool/` ni `input/`** — es gameplay grabado que no se recupera.
- **Gate con Diego tras cada hito** — entrega el checklist "cómo probarlo" y PARA hasta su OK.
- **Ancla en el plan de Diego** (`decision-making.md` §1).
