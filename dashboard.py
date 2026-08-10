"""Dashboard Streamlit que ENVUELVE el pipeline de automatización de YouTube.

El dashboard lanza el pipeline como SUBPROCESO (ver dashboard_runner.py), nunca
importando las funciones de fase; de los módulos solo se usan funciones READ-ONLY
(load_config, get_pool_status, check_dependencies). Pestañas:
  📊 Estado      — pool, conteos, dependencias, API keys (solo lectura)
  🎬 Operar      — elegir/subir gameplay y lanzar una corrida
  📡 Progreso    — log en vivo, fase actual, detener
  🖼️ Resultados  — galería de videos/shorts, abrir en local
  🔍 Competencia — escaneo de rivales, virales, debate e inyección al prompt
  ⚙️ Config      — editor de campos curados de config.yaml (con backup .bak)

Excepción a la regla del subproceso: el escaneo de competencia SÍ corre en
proceso. Ninguna de las razones que obligan al subproceso (logging global
duplicado, caché de Whisper, objeto `args`) aplica a competitor_scout, y correr
en proceso permite pintar el avance real con st.status.
"""

import glob
import os
import shutil
from datetime import datetime, timezone

import streamlit as st
import streamlit.components.v1 as components
import yaml

import dashboard_runner as runner

# Imports READ-ONLY permitidos (no funciones de fase).
from modules.utils import load_dotenv, load_config, check_dependencies
from modules.gameplay_pool import get_pool_status
from modules import competitor_scout, trend_advisor

# Diagrama "vivo" del Roadmap: SVG animado (partículas que fluyen por las
# conexiones + hub que pulsa). Se embebe con components.html (iframe) para que
# las animaciones CSS/SMIL funcionen.
_ROADMAP_SVG = """
<!doctype html><html><head><meta charset='utf-8'><style>
*{margin:0;padding:0;box-sizing:border-box}
html,body{height:100%}
body{background:#0a0a0f;font-family:'Inter','Segoe UI',system-ui,sans-serif;
overflow:hidden;display:flex;align-items:center;justify-content:center}
svg{width:100%;height:100%;display:block}
.flow{stroke-dasharray:5 9;animation:m 1s linear infinite}
.flowd{stroke-dasharray:2 7;animation:m 1.3s linear infinite}
@keyframes m{to{stroke-dashoffset:-14}}
.pulse{animation:p 2.6s ease-in-out infinite}
@keyframes p{0%,100%{opacity:.5}50%{opacity:1}}
.glow{filter:drop-shadow(0 0 5px currentColor)}
.t{font-size:13.5px;font-weight:700;fill:#f0f0f5}
.s{font-size:9.5px;fill:#9aa0b4}
.hub{font-size:14px;font-weight:800;fill:#fff}
.hubs{font-size:10px;fill:#ffd9b3}
.stp{font-size:9px;fill:#dfe3ee}
.el{font-size:9.5px;font-weight:600}
.leg{font-size:11px;fill:#9aa0b4}
</style></head><body>
<svg viewBox="0 0 1080 470" preserveAspectRatio="xMidYMid meet" xmlns="http://www.w3.org/2000/svg">
<defs><marker id="a" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6"
orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#c8c8d4"/></marker></defs>

<!-- ===== FLUJO PRINCIPAL (izq -> der) ===== -->

<!-- ENTRADA -> OPERAR (verde) -->
<path d="M195,192 L228,192" fill="none" stroke="#2ec27e" stroke-width="2.2" opacity="0.75" class="flow" marker-end="url(#a)"/>
<circle r="3.4" fill="#2ec27e" class="glow" color="#2ec27e"><animateMotion dur="2.2s" begin="0s" repeatCount="indefinite" path="M195,192 L228,192"/></circle>

<!-- OPERAR -> PIPELINE (azul, Play) -->
<path d="M397,192 L436,192" fill="none" stroke="#5b9dff" stroke-width="2.2" opacity="0.75" class="flow" marker-end="url(#a)"/>
<circle r="3.6" fill="#5b9dff" class="glow" color="#5b9dff"><animateMotion dur="2.0s" begin="0s" repeatCount="indefinite" path="M397,192 L436,192"/></circle>
<text x="416" y="180" text-anchor="middle" class="el" fill="#5b9dff">▶ Play</text>

<!-- PIPELINE -> RESULTADOS (verde, entrega) -->
<path d="M650,192 L688,192" fill="none" stroke="#2ec27e" stroke-width="2.2" opacity="0.75" class="flow" marker-end="url(#a)"/>
<circle r="3.6" fill="#2ec27e" class="glow" color="#2ec27e"><animateMotion dur="2.2s" begin="0s" repeatCount="indefinite" path="M650,192 L688,192"/></circle>
<text x="669" y="180" text-anchor="middle" class="el" fill="#2ec27e">entrega</text>

<!-- RESULTADOS -> YOUTUBE (teal, subes) -->
<path d="M855,192 L893,192" fill="none" stroke="#4ec9b0" stroke-width="2.2" opacity="0.75" class="flow" marker-end="url(#a)"/>
<circle r="3.4" fill="#4ec9b0" class="glow" color="#4ec9b0"><animateMotion dur="2.2s" begin="0s" repeatCount="indefinite" path="M855,192 L893,192"/></circle>
<text x="874" y="180" text-anchor="middle" class="el" fill="#4ec9b0">subes</text>

<!-- ===== RAMALES ===== -->

<!-- PIPELINE -> PROGRESO (abajo, ambar, en vivo) -->
<path d="M545,256 L545,298" fill="none" stroke="#f5a623" stroke-width="2.2" opacity="0.75" class="flow" marker-end="url(#a)"/>
<circle r="3.4" fill="#f5a623" class="glow" color="#f5a623"><animateMotion dur="2.0s" begin="0s" repeatCount="indefinite" path="M545,256 L545,298"/></circle>
<text x="558" y="282" class="el" fill="#f5a623">en vivo</text>

<!-- ESTADO -> OPERAR (arriba, gris, revisas antes) -->
<path d="M314,106 L314,148" fill="none" stroke="#9aa0b4" stroke-width="1.8" opacity="0.6" class="flowd" marker-end="url(#a)"/>
<circle r="2.8" fill="#9aa0b4" class="glow" color="#9aa0b4"><animateMotion dur="2.6s" begin="0s" repeatCount="indefinite" path="M314,106 L314,148"/></circle>
<text x="326" y="132" class="el" fill="#9aa0b4">revisas antes</text>

<!-- CONFIG -> PIPELINE (arriba, morado, afina) -->
<path d="M545,92 L545,128" fill="none" stroke="#c08bdb" stroke-width="1.8" opacity="0.65" class="flowd" marker-end="url(#a)"/>
<circle r="2.8" fill="#c08bdb" class="glow" color="#c08bdb"><animateMotion dur="2.6s" begin="0s" repeatCount="indefinite" path="M545,92 L545,128"/></circle>
<text x="558" y="114" class="el" fill="#c08bdb">afina</text>

<!-- ===== NODOS ===== -->

<!-- ENTRADA -->
<rect x="30" y="150" width="165" height="84" rx="12" fill="rgba(255,255,255,0.03)" stroke="#6b7280" stroke-width="1.8"/>
<text x="112" y="184" text-anchor="middle" class="t">🎮 ENTRADA</text>
<text x="112" y="202" text-anchor="middle" class="s">gameplay bruto</text>
<text x="112" y="217" text-anchor="middle" class="s">(carpeta input/)</text>

<!-- OPERAR -->
<rect x="232" y="150" width="165" height="84" rx="12" fill="rgba(255,255,255,0.03)" stroke="#5b9dff" stroke-width="1.8"/>
<text x="314" y="187" text-anchor="middle" class="t">🎬 OPERAR</text>
<text x="314" y="206" text-anchor="middle" class="s">eliges archivo + Play</text>

<!-- PIPELINE (hub) -->
<rect x="440" y="130" width="210" height="124" rx="16" fill="rgba(255,138,61,0.08)" stroke="#ff8a3d" stroke-width="2" class="pulse glow" color="#ff8a3d"/>
<text x="545" y="158" text-anchor="middle" class="hub">⚙️ EL PIPELINE</text>
<text x="545" y="177" text-anchor="middle" class="hubs">trabaja solo (main.py):</text>
<text x="545" y="201" text-anchor="middle" class="stp">limpia → escribe historia → voz</text>
<text x="545" y="220" text-anchor="middle" class="stp">→ subtítulos → video → shorts</text>

<!-- RESULTADOS -->
<rect x="690" y="150" width="165" height="84" rx="12" fill="rgba(255,255,255,0.03)" stroke="#2ec27e" stroke-width="1.8"/>
<text x="772" y="184" text-anchor="middle" class="t">🖼️ RESULTADOS</text>
<text x="772" y="202" text-anchor="middle" class="s">recoges lo</text>
<text x="772" y="217" text-anchor="middle" class="s">terminado</text>

<!-- YOUTUBE -->
<rect x="895" y="150" width="160" height="84" rx="12" fill="rgba(255,255,255,0.03)" stroke="#ff5c5c" stroke-width="1.8"/>
<text x="975" y="187" text-anchor="middle" class="t">▶️ YOUTUBE</text>
<text x="975" y="206" text-anchor="middle" class="s">lo subes y listo</text>

<!-- ESTADO (apoyo, arriba) -->
<rect x="232" y="28" width="165" height="76" rx="12" fill="rgba(255,255,255,0.03)" stroke="#4ec9b0" stroke-width="1.6"/>
<text x="314" y="60" text-anchor="middle" class="t">📊 ESTADO</text>
<text x="314" y="78" text-anchor="middle" class="s">¿hay material? ¿listo?</text>

<!-- CONFIG (apoyo, arriba) -->
<rect x="440" y="14" width="210" height="76" rx="12" fill="rgba(255,255,255,0.03)" stroke="#c08bdb" stroke-width="1.6"/>
<text x="545" y="46" text-anchor="middle" class="t">⚙️ CONFIG</text>
<text x="545" y="64" text-anchor="middle" class="s">voces · estilo · calidad</text>

<!-- PROGRESO (apoyo, abajo) -->
<rect x="440" y="300" width="210" height="82" rx="12" fill="rgba(255,255,255,0.03)" stroke="#f5a623" stroke-width="1.6"/>
<text x="545" y="334" text-anchor="middle" class="t">📡 PROGRESO</text>
<text x="545" y="353" text-anchor="middle" class="s">lo ves avanzar</text>
<text x="545" y="368" text-anchor="middle" class="s">en tiempo real</text>

<!-- ===== LEYENDA ===== -->
<g transform="translate(40,410)">
<circle cx="4" cy="0" r="5" fill="#2ec27e"/><text x="16" y="4" class="leg">el pipeline trabaja solo (automático)</text>
<circle cx="4" cy="22" r="5" fill="#5b9dff"/><text x="16" y="26" class="leg">tú lanzas la corrida (Operar)</text>
<circle cx="4" cy="44" r="5" fill="#9aa0b4"/><text x="16" y="48" class="leg">Estado revisas · Config afinas · Progreso observas</text>
</g>
</svg></body></html>
"""

st.set_page_config(page_title="YouTube Automation", layout="wide")

load_dotenv()
config = load_config("config.yaml")

# Aquí vivirá el handle de la corrida activa (dashboard_runner.launch_run).
st.session_state.setdefault("run", None)

(
    tab_roadmap, tab_estado, tab_operar, tab_progreso,
    tab_resultados, tab_competencia, tab_config,
) = st.tabs(
    ["🗺️ Roadmap", "📊 Estado", "🎬 Operar", "📡 Progreso",
     "🖼️ Resultados", "🔍 Competencia", "⚙️ Config"]
)

with tab_roadmap:
    st.subheader("🗺️ Cómo funciona todo, en simple")
    st.markdown(
        "Esta herramienta convierte **un video largo de gameplay en bruto** en "
        "**videos de YouTube + shorts listos para subir**, casi sin que tengas que "
        "hacer nada. Cada pestaña es un paso de ese viaje. Aquí te explico cómo "
        "encajan y qué hace cada parte."
    )

    st.markdown("### El viaje completo de un video")
    components.html(_ROADMAP_SVG, height=470, scrolling=False)

    st.info(
        "💡 En una frase: en **Operar** das Play → el **pipeline** hace todo el "
        "trabajo → lo ves en **Progreso** → lo recoges en **Resultados**. "
        "**Estado** y **Config** son apoyo que usas cuando quieras."
    )

    st.divider()
    st.markdown("### Qué hace cada pestaña (y cada sección)")

    with st.expander("📊 Estado — tu tablero antes de empezar"):
        st.markdown(
            "Una foto rápida de si todo está listo para producir. No hace nada, "
            "solo informa.\n\n"
            "- **🎮 Pool de gameplay** — El *pool* es una cola de gameplay ya "
            "limpio (sin pausas ni escritorio) esperando a convertirse en video. "
            "La barra te dice si hay suficiente: se necesitan **al menos ~20 min** "
            "acumulados para producir un video.\n"
            "- **📁 Archivos** — Cuántos videos en bruto tienes en `input/`, "
            "cuántos videos ya produjiste y cuántos shorts.\n"
            "- **🔧 Dependencias** — Si **FFmpeg** está instalado (es el programa "
            "que corta y monta el video). Si falta, nada puede generarse.\n"
            "- **🔑 API Key** — La llave de la IA que escribe las historias. Si no "
            "está, no se pueden generar guiones."
        )

    with st.expander("🎬 Operar — el botón de arranque"):
        st.markdown(
            "Aquí eliges qué procesar y le das Play. Es el único sitio donde "
            "lanzas trabajo.\n\n"
            "- **¿Qué quieres hacer?** — *Procesar un archivo nuevo* (parte de un "
            "gameplay en bruto) o *Producir del pool existente* (usa gameplay que "
            "ya estaba limpio y guardado, sin volver a ingerir nada).\n"
            "- **Fuente** — *Seleccionar de input/*: eliges un archivo que ya "
            "pusiste en la carpeta `input/` (lo normal para los archivos grandes "
            "de ~13 GB). *Subir clip de prueba*: arrastras un archivo pequeño "
            "desde el navegador (solo para pruebas).\n"
            "- **Opciones** — *Estilo* (dramático, terror, etc.) marca el tono de "
            "la historia. *Generar shorts* decide si además se crean los verticales. "
            "*Dry-run* es un modo de prueba: solo escribe la historia, sin gastar "
            "tiempo en audio ni video (útil para ver si el guion te gusta).\n"
            "- **Comando + 🚀 Ejecutar** — Te muestro la orden exacta que se va a "
            "lanzar (transparencia total) y el botón que la arranca."
        )

    with st.expander("📡 Progreso — la ventana al motor"):
        st.markdown(
            "Mientras el pipeline trabaja (puede tardar minutos), aquí ves qué "
            "está haciendo, en tiempo real.\n\n"
            "- **Estado de la corrida** — 🟢 ejecutando, ✅ terminado (con cuántos "
            "videos salieron), ⚠️ terminó sin producir nada, o ❌ error.\n"
            "- **Fase actual** — En qué paso va: ingestando, escribiendo historia, "
            "poniendo voz, montando video o generando shorts.\n"
            "- **Log en vivo** — El detalle técnico línea a línea, por si algo "
            "falla y quieres ver qué pasó.\n"
            "- **⏹️ Detener** — Corta la corrida ahora mismo (también apaga los "
            "procesos de edición que estén corriendo por debajo)."
        )

    with st.expander("🖼️ Resultados — la bandeja de salida"):
        st.markdown(
            "Donde recoges lo ya terminado para subirlo a YouTube.\n\n"
            "- **🎬 Videos largos** — Cada tarjeta tiene la miniatura, el título "
            "generado, y botones para *abrir el video* en tu reproductor o *abrir "
            "la carpeta*. Puedes descargar la miniatura y el título (el video no se "
            "descarga porque pesa mucho; se abre directo en tu PC).\n"
            "- **📱 Shorts** — Lista de verticales con su título y botón para "
            "abrirlos. La *previsualización* solo se carga cuando activas su "
            "interruptor (así no se ralentiza aunque haya decenas de shorts)."
        )

    with st.expander("🔍 Competencia — qué está funcionando ahí fuera"):
        st.markdown(
            "Mira los canales que compiten contigo, detecta cuáles de sus videos "
            "están reventando ahora mismo y decide qué copiar. No toca nada sin "
            "que tú lo apruebes.\n\n"
            "- **Escanear** — Busca canales del nicho en YouTube y mide sus "
            "últimos videos. La lista de competidores **se guarda y crece** con "
            "cada escaneo; no empieza de cero cada vez.\n"
            "- **🔥 Virales** — Sus videos ordenados por un *score*. Lo importante "
            "no es que tengan muchas vistas, sino que tengan **muchas más de lo "
            "normal en ese canal** (columna *xN*): eso es lo que indica que el "
            "tema ha pegado, no que el canal sea grande.\n"
            "- **🧠 Debate** — La IA mira esos datos y decide qué ángulo atacar, "
            "argumentando con las cifras y descartando alternativas.\n"
            "- **✅ Aplicar** — Mete esas directrices en el prompt que escribe las "
            "historias. A partir de ahí, los videos nuevos las siguen. Se puede "
            "quitar en un clic.\n\n"
            "*Consume cuota de la API de YouTube (10.000 unidades gratis al día). "
            "Un escaneo típico gasta ~500, así que puedes escanear varias veces "
            "al día sin problema.*"
        )

    with st.expander("⚙️ Config — los ajustes"):
        st.markdown(
            "Cambias cómo se ven y suenan los videos, sin tocar archivos a mano.\n\n"
            "- **🎙️ TTS** — Las voces (hombre/mujer) y el modelo que sincroniza los "
            "subtítulos con la voz.\n"
            "- **💬 Subtítulos** — Fuente, tamaño, grosor del borde y si van en "
            "MAYÚSCULAS.\n"
            "- **📖 Historia** — Estilo por defecto, ritmo de narración y cuánto "
            "gameplay se usa por video.\n"
            "- **📱 Shorts** — Si se generan, cuántas palabras, velocidad y cuántos "
            "por video.\n"
            "- **🎞️ Video** — Calidad y códec de salida (cómo de comprimido queda).\n"
            "- **💾 Guardar** — Escribe los cambios y guarda una copia de seguridad "
            "(`.bak`) de la versión anterior por si te arrepientes."
        )

    st.divider()
    st.markdown("### Un par de decisiones que quizá te sorprendan")
    st.markdown(
        "- **¿Por qué un “pool”?** El gameplay en bruto puede ser corto o tener "
        "pausas. El pool acumula trozos limpios hasta que hay suficiente (~20 min) "
        "para un video completo, y guarda lo que sobra para la próxima vez.\n"
        "- **¿Por qué los shorts van acelerados x1.5?** Para que entren más "
        "historia en menos segundos sin que la voz suene rara (se acelera "
        "preservando el tono).\n"
        "- **¿Por qué se ‘abre en local’ en vez de descargar?** Los videos pesan "
        "cientos de MB o GB; abrirlos directamente en tu PC es instantáneo, "
        "descargarlos por el navegador sería lento."
    )
    st.success(
        "¿Algo de esto no te cuadra o lo harías distinto? Dímelo y lo ajustamos. 🙌"
    )

with tab_estado:
    if st.button("🔄 Actualizar", key="estado_refresh"):
        st.rerun()

    # ------------------------------------------------------------------
    # 1. POOL DE GAMEPLAY
    # ------------------------------------------------------------------
    st.subheader("🎮 Pool de gameplay")

    target_min_seg = config["story"]["target_duration_min"]
    try:
        pool = get_pool_status(config)
    except Exception as e:
        pool = []
        st.warning(f"No se pudo leer el pool: {e}")

    pool_files = len(pool)
    pool_total_seg = sum(dur for _, dur in pool)
    pool_total_min = pool_total_seg / 60

    col_a, col_b = st.columns(2)
    col_a.metric("Archivos en el pool", pool_files)
    col_b.metric("Minutos totales", f"{pool_total_min:.1f}")

    progress = min(1.0, pool_total_seg / target_min_seg) if target_min_seg else 0.0
    st.progress(progress)

    if pool_total_seg >= target_min_seg:
        st.success("✅ Hay material suficiente para producir")
    else:
        faltan_min = (target_min_seg - pool_total_seg) / 60
        st.info(f"Faltan {faltan_min:.1f} min para poder producir un video")

    st.divider()

    # ------------------------------------------------------------------
    # 2. CONTEO DE ARCHIVOS
    # ------------------------------------------------------------------
    st.subheader("📁 Archivos")

    input_files = glob.glob(os.path.join(config["paths"]["input_dir"], "*.mp4"))
    input_bytes = 0
    for f in input_files:
        try:
            input_bytes += os.path.getsize(f)
        except OSError:
            pass
    input_gb = input_bytes / (1024 ** 3)

    produced = glob.glob(
        os.path.join(config["paths"]["output_dir"], "video_*_final.mp4")
    )
    shorts = glob.glob(os.path.join(config["paths"]["shorts_dir"], "short_*.mp4"))

    col1, col2, col3 = st.columns(3)
    col1.metric("Entrada (.mp4)", len(input_files), f"{input_gb:.2f} GB")
    col2.metric("Videos producidos", len(produced))
    col3.metric("Shorts", len(shorts))

    st.divider()

    # ------------------------------------------------------------------
    # 3. DEPENDENCIAS
    # ------------------------------------------------------------------
    st.subheader("🔧 Dependencias")

    try:
        missing = check_dependencies()
    except Exception as e:
        missing = None
        st.warning(f"No se pudieron comprobar las dependencias: {e}")

    if missing == []:
        st.success("FFmpeg / FFprobe: OK")
    elif missing:
        st.error("Faltan ejecutables: " + ", ".join(missing))

    st.divider()

    # ------------------------------------------------------------------
    # 4. API KEY
    # ------------------------------------------------------------------
    st.subheader("🔑 API Keys")

    api_key = os.environ.get("OPENROUTER_API_KEY")
    if api_key:
        masked = api_key[:6] + "…"
        st.success(f"OPENROUTER_API_KEY: configurada ({masked})")
    else:
        st.error("Falta OPENROUTER_API_KEY en .env")

    yt_key = os.environ.get("YOUTUBE_API_KEY")
    if yt_key:
        st.success(f"YOUTUBE_API_KEY: configurada ({yt_key[:6]}…)")
    else:
        st.warning(
            "Falta YOUTUBE_API_KEY en .env — solo afecta a la pestaña "
            "🔍 Competencia; el resto del pipeline funciona sin ella."
        )

with tab_operar:
    st.subheader("🎬 Operar el pipeline")

    # ------------------------------------------------------------------
    # A. GUARDA DE CORRIDA ACTIVA
    # ------------------------------------------------------------------
    run_active = (
        st.session_state["run"] is not None
        and runner.is_running(st.session_state["run"])
    )
    if run_active:
        st.warning("Ya hay una corrida en curso. Ve a la pestaña 📡 Progreso.")

    # ------------------------------------------------------------------
    # B. MODO
    # ------------------------------------------------------------------
    modo = st.radio(
        "¿Qué quieres hacer?",
        [
            "Procesar un archivo de gameplay nuevo",
            "Producir del pool existente (sin ingestar)",
        ],
        key="operar_modo",
    )

    video_path = None

    if modo == "Procesar un archivo de gameplay nuevo":
        fuente = st.radio(
            "Fuente",
            [
                "Seleccionar de input/",
                "Subir clip de prueba (solo archivos pequeños)",
            ],
            key="operar_fuente",
        )

        if fuente == "Seleccionar de input/":
            input_dir = config["paths"]["input_dir"]
            mp4s = sorted(glob.glob(os.path.join(input_dir, "*.mp4")))
            if not mp4s:
                st.info(
                    f"No hay archivos .mp4 en {input_dir}. "
                    "Arrastra tu gameplay a esa carpeta."
                )
            else:
                elegido = st.selectbox(
                    "Archivo de gameplay",
                    mp4s,
                    format_func=os.path.basename,
                    key="operar_input_select",
                )
                video_path = elegido

        else:  # Subir clip de prueba
            st.warning(
                "⚠️ Este uploader es solo para clips PEQUEÑOS de prueba. "
                "Para los archivos reales (~13 GB) usa la opción "
                "«Seleccionar de input/» arrastrando el archivo a la carpeta "
                "input/."
            )
            uploaded = st.file_uploader(
                "Subir clip .mp4", type=["mp4"], key="operar_uploader"
            )
            if uploaded is not None:
                input_dir = config["paths"]["input_dir"]
                os.makedirs(input_dir, exist_ok=True)
                dest = os.path.join(input_dir, uploaded.name)
                if os.path.exists(dest):
                    st.warning(
                        f"Ya existe «{uploaded.name}» en input/. "
                        "Se sobrescribirá al guardar."
                    )
                with open(dest, "wb") as f:
                    f.write(uploaded.getbuffer())
                st.success(f"Guardado en {dest}")
                video_path = dest

    # ------------------------------------------------------------------
    # C. OPCIONES COMUNES
    # ------------------------------------------------------------------
    st.divider()
    st.markdown("**Opciones**")

    estilos = ["dramatic", "funny", "horror", "wholesome"]
    try:
        estilo_idx = estilos.index(config["story"]["style"])
    except (ValueError, KeyError):
        estilo_idx = 0
    estilo = st.selectbox(
        "Estilo", estilos, index=estilo_idx, key="operar_estilo"
    )

    generar_shorts = st.checkbox(
        "Generar shorts",
        value=config["shorts"]["enabled"],
        key="operar_shorts",
    )
    dry_run = st.checkbox(
        "Dry-run (solo historia, sin audio ni video)",
        value=False,
        key="operar_dryrun",
    )

    # ------------------------------------------------------------------
    # D. PREVISUALIZACIÓN + LANZAR
    # ------------------------------------------------------------------
    es_modo_archivo = modo == "Procesar un archivo de gameplay nuevo"

    options = {
        "video_path": video_path if es_modo_archivo else None,
        "style": estilo,
        "dry_run": dry_run,
        "skip_ingest": not es_modo_archivo,
        "no_shorts": not generar_shorts,
    }

    st.divider()
    st.markdown("**Comando que se ejecutará**")
    st.code(" ".join(runner.build_command(options)), language="bash")

    if st.button(
        "🚀 Ejecutar pipeline", disabled=run_active, key="operar_ejecutar"
    ):
        if es_modo_archivo and not options["video_path"]:
            st.error(
                "No has seleccionado ni subido ningún archivo de gameplay."
            )
        else:
            st.session_state["run"] = runner.launch_run(options)
            st.success(
                f"Corrida lanzada (PID {st.session_state['run']['pid']}). "
                "Ve a la pestaña 📡 Progreso para seguir el avance."
            )

with tab_progreso:
    st.subheader("📡 Progreso de la corrida")

    if st.session_state["run"] is None:
        st.info("No hay ninguna corrida. Lánzala desde la pestaña 🎬 Operar.")
    else:
        # Auto-refresco dinámico: solo refresca mientras la corrida vive.
        # Cuando ya terminó, interval=None -> el fragmento no se re-ejecuta solo.
        activo = runner.is_running(st.session_state["run"])
        interval = 2 if activo else None

        def _render_progreso():
            handle = st.session_state["run"]

            # b) FASE ACTUAL (la leemos antes para evaluar el estado real)
            log_text = runner.read_log(handle)

            # a) ESTADO (orden importa: vivo -> detenido -> resultado real)
            if runner.is_running(handle):
                st.success(f"🟢 Ejecutando…  (PID {handle['pid']})")
            elif handle.get("stopped"):
                st.warning("⏹️ Detenido por el usuario")
            else:
                code = runner.exit_code(handle)
                n = runner.produced_count(log_text)
                # main.py captura los errores por-video y SIEMPRE sale 0 salvo
                # fallo de dependencias / arranque. Por eso el éxito real se mide
                # por el conteo de "Pipeline finalizado: N videos", no por el code.
                if code != 0:
                    st.error(f"❌ Terminado con error (código {code})")
                elif n is None:
                    st.warning("⚠️ Terminó sin línea de cierre del pipeline (revisa el log)")
                elif n == 0:
                    st.warning("⚠️ Terminó sin producir videos (pool insuficiente o fallos — revisa el log)")
                else:
                    st.success(f"✅ Terminado: {n} video(s) producido(s)")
            st.markdown(f"**Fase actual:** {runner.current_phase(log_text)}")

            # c) LOG EN VIVO (tail de las últimas ~200 líneas)
            st.markdown("**Log en vivo**")
            if log_text:
                tail = "\n".join(log_text.splitlines()[-200:])
                st.code(tail, language="log")
            else:
                st.caption("Aún sin salida…")

            # d) BOTÓN DETENER (solo mientras sigue vivo)
            if runner.is_running(handle):
                if st.button("⏹️ Detener corrida", key="progreso_stop"):
                    runner.stop_run(handle)
                    handle["stopped"] = True
                    st.rerun()

        st.fragment(run_every=interval)(_render_progreso)()

with tab_resultados:
    if st.button("🔄 Actualizar", key="resultados_refresh"):
        st.rerun()

    output_dir = config["paths"]["output_dir"]
    shorts_dir = config["paths"]["shorts_dir"]

    def _abrir(path):
        """Abre un archivo o carpeta en el sistema (Windows). READ-ONLY."""
        try:
            os.startfile(os.path.abspath(path))  # noqa: S606 (Windows-only)
        except Exception as e:
            st.error(f"No se pudo abrir «{path}»: {e}")

    def _size_mb(path):
        try:
            return os.path.getsize(path) / (1024 ** 2)
        except OSError:
            return None

    # ------------------------------------------------------------------
    # SECCIÓN A — VIDEOS LARGOS
    # ------------------------------------------------------------------
    st.subheader("🎬 Videos largos")

    videos = sorted(glob.glob(os.path.join(output_dir, "video_*_final.mp4")))
    if not videos:
        st.info("Aún no hay videos producidos.")
    else:
        for idx, video in enumerate(videos):
            base = os.path.basename(video)
            stem = base[: -len("_final.mp4")]  # "video_NNN"
            thumb = os.path.join(output_dir, f"{stem}_thumbnail.jpg")
            title_file = os.path.join(output_dir, f"{stem}_title.txt")

            with st.container(border=True):
                col_izq, col_der = st.columns([1, 2])

                with col_izq:
                    if os.path.exists(thumb):
                        st.image(thumb, width="stretch")
                    else:
                        st.caption("(sin miniatura)")

                with col_der:
                    titulo = None
                    if os.path.exists(title_file):
                        try:
                            with open(title_file, "r", encoding="utf-8") as fh:
                                titulo = fh.read().strip()
                        except OSError:
                            titulo = None
                    st.markdown(f"**{titulo or base}**")

                    mb = _size_mb(video)
                    if mb is not None:
                        st.caption(f"{base} — {mb:.1f} MB")
                    else:
                        st.caption(base)

                    bcol1, bcol2 = st.columns(2)
                    if bcol1.button(
                        "▶️ Abrir video", key=f"video_open_{idx}"
                    ):
                        _abrir(video)
                    if bcol2.button(
                        "📂 Abrir carpeta", key=f"video_folder_{idx}"
                    ):
                        _abrir(output_dir)

                    if os.path.exists(thumb):
                        try:
                            with open(thumb, "rb") as fh:
                                st.download_button(
                                    "⬇️ Miniatura",
                                    data=fh.read(),
                                    file_name=f"{stem}_thumbnail.jpg",
                                    mime="image/jpeg",
                                    key=f"video_thumb_dl_{idx}",
                                )
                        except OSError:
                            pass

                    if os.path.exists(title_file) and titulo is not None:
                        st.download_button(
                            "⬇️ Título .txt",
                            data=titulo,
                            file_name=f"{stem}_title.txt",
                            key=f"video_title_dl_{idx}",
                        )

    st.divider()

    # ------------------------------------------------------------------
    # SECCIÓN B — SHORTS
    # ------------------------------------------------------------------
    st.subheader("📱 Shorts")

    shorts_list = sorted(glob.glob(os.path.join(shorts_dir, "short_*.mp4")))
    if not shorts_list:
        st.info("Aún no hay shorts.")
    else:
        if st.button("📂 Abrir carpeta de shorts", key="shorts_folder"):
            _abrir(shorts_dir)

        cols = st.columns(3)
        for idx, short in enumerate(shorts_list):
            base = os.path.basename(short)
            stem = base[: -len(".mp4")]  # "short_NNN"
            title_file = os.path.join(shorts_dir, f"{stem}_title.txt")

            titulo = None
            if os.path.exists(title_file):
                try:
                    with open(title_file, "r", encoding="utf-8") as fh:
                        titulo = fh.read().strip()
                except OSError:
                    titulo = None

            with cols[idx % 3]:
                with st.container(border=True):
                    st.markdown(f"**{titulo or base}**")
                    st.caption(base)
                    if st.button("▶️ Abrir", key=f"short_open_{idx}"):
                        _abrir(short)
                    # Preview BAJO DEMANDA: st.video solo se instancia cuando el
                    # usuario activa el toggle. Un st.expander NO difiere su cuerpo
                    # (el colapso es solo frontend) -> con muchos shorts cargaría
                    # un elemento de video por cada uno en cada render.
                    if st.toggle("👁️ Previsualizar", key=f"short_prev_{idx}"):
                        st.video(short)

def _render_competencia():
    """Cuerpo de la pestaña Competencia.

    Va en una función y no inline como el resto de pestañas porque necesita
    salidas tempranas (sin API key, sin informe). `st.stop()` cortaría TODO el
    rerun y dejaría sin renderizar las pestañas siguientes; `return` no.
    """
    st.subheader("🔍 Competencia")
    st.caption(
        "Descubre quién compite contigo, mide qué videos suyos están reventando "
        "ahora y decide qué atacar. Nada se aplica a tus historias sin tu OK."
    )

    comp_cfg = config.get("competition", {}) or {}

    # ------------------------------------------------------------------
    # A. GUARDA: API KEY
    # ------------------------------------------------------------------
    if not os.environ.get("YOUTUBE_API_KEY"):
        st.error("Falta `YOUTUBE_API_KEY` en el archivo `.env`.")
        with st.expander("Cómo conseguirla (gratis, 5 minutos)", expanded=True):
            st.markdown(
                "1. Entra en [Google Cloud Console](https://console.cloud.google.com) "
                "y crea un proyecto (o usa uno existente).\n"
                "2. **APIs y servicios → Biblioteca** → busca **YouTube Data API v3** "
                "→ *Habilitar*.\n"
                "3. **APIs y servicios → Credenciales → Crear credenciales → "
                "Clave de API**. Copia la clave (empieza por `AIza…`).\n"
                "4. Añade esta línea al archivo `.env` del proyecto:\n"
                "```\nYOUTUBE_API_KEY=AIza...\n```\n"
                "5. Reinicia el dashboard.\n\n"
                "La cuota gratuita es de **10.000 unidades al día**; un escaneo "
                "completo gasta unas 500."
            )
        return

    # ------------------------------------------------------------------
    # B. LANZAR ESCANEO
    # ------------------------------------------------------------------
    # El escaneo corre EN PROCESO (a diferencia del pipeline, que va como
    # subproceso): no toca logging global, no cachea modelos y dura segundos,
    # así que ninguna de las razones que obligan al subproceso aplica aquí.
    col_scan1, col_scan2, col_scan3 = st.columns([1.2, 1.2, 2])

    do_scan = col_scan1.button(
        "🔎 Escanear competencia", type="primary", key="comp_scan",
        help="Busca canales nuevos + mide los ya conocidos (~500 unidades de cuota)",
    )
    do_remeasure = col_scan2.button(
        "♻️ Solo re-medir", key="comp_remeasure",
        help="No busca canales nuevos; solo actualiza métricas de los conocidos (~90 unidades)",
    )

    state_comp = competitor_scout.load_state(config)
    quota_today = state_comp.get("quota", {})
    if quota_today.get("date") == datetime.now(timezone.utc).strftime("%Y-%m-%d"):
        used = int(quota_today.get("units", 0))
        limit = int((comp_cfg.get("quota") or {}).get("daily_limit", 10000))
        col_scan3.progress(
            min(1.0, used / limit) if limit else 0.0,
            text=f"Cuota de hoy: {used:,} / {limit:,} unidades",
        )

    if do_scan or do_remeasure:
        with st.status("Escaneando la competencia…", expanded=True) as status:
            try:
                competitor_scout.scan(
                    config,
                    discover=bool(do_scan),
                    progress=lambda msg: status.write(msg),
                )
                status.update(label="Escaneo completado", state="complete")
            except competitor_scout.MissingApiKey as e:
                status.update(label="Falta la API key", state="error")
                st.error(str(e))
            except Exception as e:
                status.update(label="El escaneo falló", state="error")
                st.error(f"Error escaneando: {e}")
        st.rerun()

    report = competitor_scout.load_report(config)

    if not report:
        st.info("Todavía no has escaneado. Pulsa **🔎 Escanear competencia** para empezar.")
        return

    # ------------------------------------------------------------------
    # C. RESUMEN DEL ÚLTIMO ESCANEO
    # ------------------------------------------------------------------
    st.divider()
    generated = report.get("generated_at", "")[:16].replace("T", " ")
    st.caption(f"Último escaneo: {generated} UTC")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Competidores activos", report.get("competitors_active", 0))
    m2.metric("Videos analizados", report.get("videos_analyzed", 0))
    m3.metric("Virales detectados", len(report.get("viral", [])))
    m4.metric("Cuota usada (corrida)", report.get("quota_used_this_run", 0))

    for w in report.get("warnings", []):
        st.warning(w)

    # ------------------------------------------------------------------
    # D. VIRALES
    # ------------------------------------------------------------------
    st.subheader("🔥 Videos virales de la competencia")
    st.caption(
        "Ordenados por *score*. **xN** = vistas respecto a la mediana de su propio "
        "canal: es la señal de que el TEMA pegó, no de que el canal sea grande."
    )

    viral_rows = [
        {
            "Score": v["viral_score"],
            "Título": v["title"],
            "Canal": v["channel_title"],
            "Vistas": v["views"],
            "xN": v.get("outlier_ratio", 0.0),
            "Engagement": v["engagement_rate"],
            "Vistas/h": v["views_per_hour"],
            "Días": v["age_days"],
            "Min": round(v["duration_sec"] / 60),
            "Ver": v["url"],
        }
        for v in report.get("viral", [])
    ]

    if viral_rows:
        st.dataframe(
            viral_rows,
            width="stretch",
            hide_index=True,
            column_config={
                "Score": st.column_config.ProgressColumn(
                    "Score", min_value=0, max_value=100, format="%.0f"
                ),
                "Vistas": st.column_config.NumberColumn("Vistas", format="%d"),
                "xN": st.column_config.NumberColumn(
                    "xN", format="%.1fx", help="Vistas / mediana del canal"
                ),
                "Engagement": st.column_config.NumberColumn(
                    "Engag.", format="%.2f%%",
                    help="(likes + comentarios) / vistas",
                ),
                "Vistas/h": st.column_config.NumberColumn("Vistas/h", format="%.0f"),
                "Ver": st.column_config.LinkColumn("Ver", display_text="▶"),
            },
        )
        if any(v.get("metrics_partial") for v in report.get("viral", [])):
            st.caption(
                "⚠️ Algún canal oculta likes o comentarios: su engagement sale más "
                "bajo de lo real."
            )
    else:
        st.info("No se detectaron virales en la ventana temporal configurada.")

    # ------------------------------------------------------------------
    # E. COMPETIDORES
    # ------------------------------------------------------------------
    with st.expander(f"📋 Lista de competidores ({report.get('competitors_active', 0)})"):
        comp_rows = [
            {
                "Canal": c["title"],
                "Subs": "oculto" if c.get("subscribers_hidden") else f"{c.get('subscribers', 0):,}",
                "Mediana vistas": c.get("median_views", 0),
                "Subidas 30d": c.get("uploads_last_30d", 0),
                "% largo": c.get("long_form_ratio", 0.0),
                "🎮": c.get("gameplay_ratio", 0.0),
                "1ª pers.": c.get("first_person_ratio", 0.0),
                "Nicho": c.get("llm_reason", "") if "llm_in_niche" in c else "sin clasificar",
                "Origen": c.get("source", ""),
                "Ir": c["url"],
            }
            for c in report.get("competitors", [])
        ]
        if comp_rows:
            st.dataframe(
                comp_rows,
                width="stretch",
                hide_index=True,
                column_config={
                    "Mediana vistas": st.column_config.NumberColumn(format="%d"),
                    "% largo": st.column_config.NumberColumn(format="%.0f%%"),
                    "🎮": st.column_config.NumberColumn(
                        "🎮", format="%.0f%%",
                        help="Señal de gameplay en los metadatos. OJO: casi siempre 0% "
                             "aunque el canal use gameplay — YouTube no etiqueta el vídeo "
                             "de fondo. Sirve como pista, no como veredicto.",
                    ),
                    "1ª pers.": st.column_config.NumberColumn(
                        "1ª pers.", format="%.0f%%",
                        help="Títulos en primera persona ('mi suegra…'). Tu nicho narra en "
                             "primera persona; el drama doblado, en tercera. Es una pista: "
                             "hay competidores reales con 0% y ruido con 75%.",
                    ),
                    "Nicho": st.column_config.TextColumn(
                        "Nicho", help="Por qué el modelo considera que este canal compite contigo.",
                    ),
                    "Ir": st.column_config.LinkColumn("Ir", display_text="↗"),
                },
            )
            st.caption(
                "¿Ves un canal que no compite contigo? Añádelo a "
                "`competition.exclude_channels` en config.yaml (vale el nombre tal cual) "
                "y desaparecerá en el siguiente escaneo."
            )
        else:
            st.info(
                "Ningún canal superó los filtros. Baja `min_subscribers` en "
                "config.yaml o añade canales semilla en `competition.seed_channels`."
            )

    # ------------------------------------------------------------------
    # F. DEBATE
    # ------------------------------------------------------------------
    st.divider()
    st.subheader("🧠 Qué atacar")

    if st.button("💬 Debatir con los datos actuales", key="comp_debate",
                 disabled=not report.get("viral")):
        with st.spinner("El modelo está debatiendo…"):
            try:
                trend_advisor.debate(report, config)
            except Exception as e:
                st.error(f"El debate falló: {e}")
        st.rerun()

    advice = trend_advisor.load_advice(config)

    if not advice:
        st.info("Pulsa **💬 Debatir** para que el modelo decida el ángulo a atacar.")
    else:
        stale = advice.get("based_on_report") != report.get("generated_at")
        if stale:
            st.warning(
                "Este veredicto se hizo con un escaneo anterior. Vuelve a debatir "
                "para usar los datos recién medidos."
            )

        if advice.get("veredicto"):
            st.success(f"**Veredicto** — {advice['veredicto']}")

        if advice.get("analisis"):
            with st.expander("📊 Análisis completo"):
                st.markdown(advice["analisis"])

        if advice.get("directrices"):
            st.markdown("**Directrices para el guionista:**")
            for d in advice["directrices"]:
                st.markdown(f"- {d}")

        if advice.get("titulares"):
            with st.expander("✍️ Títulos de ejemplo alineados con el veredicto"):
                for t in advice["titulares"]:
                    st.markdown(f'- "{t}"')

        # --------------------------------------------------------------
        # G. APLICAR / REVERTIR
        # --------------------------------------------------------------
        st.divider()
        injected = trend_advisor.current_injection(config)

        if injected:
            st.info("✅ Hay directrices aplicadas al prompt de historias.")
            with st.expander("Ver el bloque inyectado"):
                st.code(injected, language="text")
        else:
            st.caption("El prompt de historias todavía no tiene directrices aplicadas.")

        col_ap1, col_ap2 = st.columns(2)
        if col_ap1.button(
            "✅ Aplicar al prompt de historias", type="primary", key="comp_apply",
            disabled=not advice.get("directrices"),
        ):
            try:
                path = trend_advisor.apply_to_prompt(advice, config)
                st.success(f"Directrices inyectadas en {path} (backup en {path}.bak)")
                st.rerun()
            except Exception as e:
                st.error(f"No se pudo aplicar: {e}")

        if col_ap2.button("↩️ Quitar del prompt", key="comp_remove", disabled=not injected):
            if trend_advisor.remove_from_prompt(config):
                st.success("Directrices eliminadas del prompt")
                st.rerun()


with tab_competencia:
    _render_competencia()

with tab_config:
    st.subheader("⚙️ Configuración curada")

    # Re-cargamos FRESCO del disco (la global `config` pudo quedar obsoleta
    # tras un guardado previo en este mismo rerun).
    cfg = load_config("config.yaml")

    st.caption(
        "Editor de campos curados. Al guardar se vuelca el config completo "
        "(se preservan todas las claves), pero **se eliminan los comentarios "
        "del YAML**. El backup .bak conserva la versión previa."
    )

    # ------------------------------------------------------------------
    # TTS
    # ------------------------------------------------------------------
    st.subheader("🎙️ TTS")
    col_t1, col_t2 = st.columns(2)
    tts_voice_male = col_t1.text_input(
        "Voz hombre", value=cfg["tts"]["voice_male"], key="cfg_voice_male"
    )
    tts_voice_female = col_t2.text_input(
        "Voz mujer", value=cfg["tts"]["voice_female"], key="cfg_voice_female"
    )
    whisper_opts = ["tiny", "base", "small", "medium"]
    try:
        whisper_idx = whisper_opts.index(cfg["tts"]["whisper_model"])
    except (ValueError, KeyError):
        whisper_idx = 0
    tts_whisper_model = st.selectbox(
        "Modelo Whisper (forced alignment)",
        whisper_opts,
        index=whisper_idx,
        key="cfg_whisper_model",
    )

    st.divider()

    # ------------------------------------------------------------------
    # SUBTÍTULOS
    # ------------------------------------------------------------------
    st.subheader("💬 Subtítulos")
    col_s1, col_s2 = st.columns(2)
    sub_font_name = col_s1.text_input(
        "Fuente", value=cfg["subtitles"]["font_name"], key="cfg_font_name"
    )
    sub_font_size = col_s2.number_input(
        "Tamaño de fuente",
        min_value=10,
        max_value=400,
        step=1,
        value=int(cfg["subtitles"]["font_size"]),
        key="cfg_font_size",
    )
    col_s3, col_s4 = st.columns(2)
    sub_outline_width = col_s3.number_input(
        "Grosor del contorno",
        min_value=0,
        max_value=30,
        step=1,
        value=int(cfg["subtitles"]["outline_width"]),
        key="cfg_outline_width",
    )
    sub_uppercase = col_s4.checkbox(
        "MAYÚSCULAS",
        value=bool(cfg["subtitles"]["uppercase"]),
        key="cfg_uppercase",
    )

    st.divider()

    # ------------------------------------------------------------------
    # HISTORIA
    # ------------------------------------------------------------------
    st.subheader("📖 Historia")
    story_styles = ["dramatic", "funny", "horror", "wholesome"]
    try:
        story_style_idx = story_styles.index(cfg["story"]["style"])
    except (ValueError, KeyError):
        story_style_idx = 0
    story_style = st.selectbox(
        "Estilo", story_styles, index=story_style_idx, key="cfg_story_style"
    )
    col_h1, col_h2 = st.columns(2)
    story_target_wpm = col_h1.number_input(
        "Palabras por minuto (WPM)",
        min_value=80,
        max_value=250,
        step=5,
        value=int(cfg["story"]["target_wpm"]),
        key="cfg_target_wpm",
    )
    story_chunk_size = col_h2.number_input(
        "Tamaño de chunk (segundos)",
        min_value=60,
        step=60,
        value=int(cfg["story"]["chunk_size"]),
        key="cfg_chunk_size",
    )
    col_h3, col_h4 = st.columns(2)
    story_target_duration_min = col_h3.number_input(
        "Duración mínima para producir (segundos)",
        min_value=60,
        step=60,
        value=int(cfg["story"]["target_duration_min"]),
        key="cfg_target_duration_min",
    )
    story_target_duration_max = col_h4.number_input(
        "Duración máxima antes de cortar (segundos)",
        min_value=60,
        step=60,
        value=int(cfg["story"]["target_duration_max"]),
        key="cfg_target_duration_max",
    )

    st.divider()

    # ------------------------------------------------------------------
    # SHORTS
    # ------------------------------------------------------------------
    st.subheader("📱 Shorts")
    shorts_enabled = st.checkbox(
        "Generar shorts",
        value=bool(cfg["shorts"]["enabled"]),
        key="cfg_shorts_enabled",
    )
    col_sh1, col_sh2, col_sh3, col_sh4 = st.columns(4)
    shorts_target_words = col_sh1.number_input(
        "Palabras objetivo",
        min_value=50,
        max_value=500,
        step=10,
        value=int(cfg["shorts"]["target_words"]),
        key="cfg_shorts_target_words",
    )
    shorts_speed = col_sh2.number_input(
        "Velocidad",
        min_value=1.0,
        max_value=2.5,
        step=0.1,
        format="%.1f",
        value=float(cfg["shorts"]["speed"]),
        key="cfg_shorts_speed",
    )
    shorts_narration_wpm = col_sh3.number_input(
        "Ritmo narración (wpm)",
        min_value=100,
        max_value=280,
        step=5,
        value=int(cfg["shorts"].get("narration_wpm", 200)),
        key="cfg_shorts_narration_wpm",
        help="Velocidad real de narración de un texto corto. Dimensiona cuántos "
             "shorts caben en el chunk, y por tanto cuántas peticiones se gastan. "
             "Es independiente de story.target_wpm (historias largas, ~160 wpm).",
    )
    shorts_generate_per_video = col_sh4.number_input(
        "Shorts por video",
        min_value=1,
        max_value=20,
        step=1,
        value=int(cfg["shorts"]["generate_per_video"]),
        key="cfg_shorts_generate_per_video",
        help="Solo se usa como fallback si no se puede calcular el número a "
             "partir de la duración del chunk.",
    )

    st.divider()

    # ------------------------------------------------------------------
    # VIDEO
    # ------------------------------------------------------------------
    st.subheader("🎞️ Video")
    codec_opts = ["h264_nvenc", "libx264"]
    if cfg["video"]["output_codec"] not in codec_opts:
        codec_opts = [cfg["video"]["output_codec"]] + codec_opts
    video_output_codec = st.selectbox(
        "Códec de salida",
        codec_opts,
        index=codec_opts.index(cfg["video"]["output_codec"]),
        key="cfg_output_codec",
    )
    col_v1, col_v2 = st.columns(2)
    video_preset = col_v1.text_input(
        "Preset (nvenc p1..p7 / libx264 medium…)",
        value=cfg["video"]["preset"],
        key="cfg_preset",
    )
    video_crf = col_v2.number_input(
        "CRF / CQ",
        min_value=0,
        max_value=51,
        step=1,
        value=int(cfg["video"]["crf"]),
        key="cfg_crf",
    )

    st.divider()

    # ------------------------------------------------------------------
    # GUARDAR
    # ------------------------------------------------------------------
    if st.button("💾 Guardar config", key="cfg_guardar"):
        # 1. Volcar widgets -> cfg (solo claves curadas; el resto intacto).
        cfg["tts"]["voice_male"] = tts_voice_male
        cfg["tts"]["voice_female"] = tts_voice_female
        cfg["tts"]["whisper_model"] = tts_whisper_model

        cfg["subtitles"]["font_name"] = sub_font_name
        cfg["subtitles"]["font_size"] = int(sub_font_size)
        cfg["subtitles"]["outline_width"] = int(sub_outline_width)
        cfg["subtitles"]["uppercase"] = bool(sub_uppercase)

        cfg["story"]["style"] = story_style
        cfg["story"]["target_wpm"] = int(story_target_wpm)
        cfg["story"]["target_duration_min"] = int(story_target_duration_min)
        cfg["story"]["target_duration_max"] = int(story_target_duration_max)
        cfg["story"]["chunk_size"] = int(story_chunk_size)

        cfg["shorts"]["enabled"] = bool(shorts_enabled)
        cfg["shorts"]["target_words"] = int(shorts_target_words)
        cfg["shorts"]["speed"] = float(shorts_speed)
        cfg["shorts"]["narration_wpm"] = int(shorts_narration_wpm)
        cfg["shorts"]["generate_per_video"] = int(shorts_generate_per_video)

        cfg["video"]["output_codec"] = video_output_codec
        cfg["video"]["preset"] = video_preset
        cfg["video"]["crf"] = int(video_crf)

        # 2. Backup antes de sobrescribir.
        shutil.copy2("config.yaml", "config.yaml.bak")

        # 3. Volcado COMPLETO del dict (preserva todas las claves; pierde
        #    solo los comentarios del YAML).
        with open("config.yaml", "w", encoding="utf-8") as f:
            yaml.safe_dump(cfg, f, sort_keys=False, allow_unicode=True)

        # 4. + 5. Confirmación y aviso.
        st.success("Guardado. Backup en config.yaml.bak.")
        st.info(
            "Nota: guardar elimina los comentarios del YAML. "
            "El backup .bak conserva la versión previa."
        )

        # 6. Recargar el resto de la app con el config nuevo.
        st.rerun()
