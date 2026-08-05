# Organización de Archivos — YOUTUBE

Cualquier archivo nuevo va a su carpeta. Si no existe, créala. **Nunca dejar archivos sueltos en la raíz.**

```
main.py                   ← orquestador + CLI (fases; sin lógica de dominio pesada)
dashboard.py              ← dashboard Streamlit (SOLO renderiza)
dashboard_runner.py       ← lanza el pipeline como SUBPROCESO (funciones puras, sin Streamlit)
config.yaml               ← toda la configuración de producción
.env                      ← OPENROUTER_API_KEY, YOUTUBE_API_KEY (gitignored, NUNCA se lee ni se commitea)
modules/
  utils.py                ← COSTURA: load_config, FFmpeg/ffprobe, dotenv, duración
  script_generator.py     ← COSTURA LLM: _call_openrouter es el ÚNICO punto de llamada a OpenRouter
  tts_engine.py           ← TTS + forced alignment + limpieza de texto
  subtitle_builder.py     ← SRT → ASS
  video_composer.py       ← FFmpeg: intro + woosh + subs + offset (vídeo largo)
  shorts_generator.py     ← el GEMELO vertical: 9:16, x1.5, micro-historias
  video_cleaner.py        ← hotbar detection
  gameplay_pool.py        ← cola, recodificación, chunks
  thumbnail_generator.py  ← miniatura + title card
  competitor_scout.py     ← YouTube Data API (cuota)
  trend_advisor.py        ← debate LLM + inyección/reversión en el prompt
prompts/                  ← reddit_story.txt, short_story.txt
assets/                   ← plantilla 3.png, woosh, .tint_index
seeds/                    ← seeds de handoff a sesión fresca (PASO 0: /seed-review)
test_e2e/                 ← FIXTURE del gate: clip corto + config propia. Es lo que corre /eval
data/                     ← state de competencia, informes, baselines de /eval (gitignored)
input/ pool/ temp/ output/ shorts_tiktok/   ← media (gitignored, NUNCA se borran a la ligera)
.claude/
  rules/                  ← instrucciones modulares (este archivo)
  agents/                 ← engineer, bug-hunter, output-audit
  skills/                 ← /eval, /run, /daily-run
  incident-ledger.md      ← ledger append-only; solo /optimize promueve a regla
```

**Reglas:**
- **Toda llamada a OpenRouter pasa por `_call_openrouter`** (`script_generator.py`). Es la costura donde
  viven los reintentos, el guardia del 200-sin-`choices` y el `max_tokens`. Nada la saltea — si se
  saltea, el conteo de peticiones contra el tope de 50/día deja de significar nada.
- **Toda ruta de FFmpeg/ffprobe pasa por `utils.py`.** Y toda ruta que se escriba en un fichero de
  lista de `concat` es **absoluta** (el demuxer las resuelve respecto al directorio del fichero).
- `dashboard.py` **solo renderiza**; el pipeline se lanza como **subproceso** vía `dashboard_runner.py`,
  nunca importando funciones de fase.
- `input/`, `pool/`, `output/`, `shorts_tiktok/` **no se commitean y no se borran sin permiso** — son
  horas de grabación y de render.
- `test_e2e/` es la excepción útil: es el fixture del gate. Su `clip.mp4` (1,5 GB) no se commitea, pero
  **no se borra jamás** — sin él no hay `/eval`.
- Secretos solo en `.env`. `Read(.env*)` está en el `deny` de `settings.json`.
- Referencia voluminosa (tablas de medición, barridos) → `docs/`, no en `CLAUDE.md`.
