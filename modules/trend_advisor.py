"""Debate sobre qué atacar + inyección de tendencias en el prompt (paso 3).

`competitor_scout` produce datos fríos (quién compite y qué video suyo está
reventando). Aquí un LLM los debate: qué ángulo/tema/formato de título nos
conviene atacar y por qué, con la métrica delante.

La decisión NO se aplica sola: `apply_to_prompt` escribe entre marcadores en
`prompts/reddit_story.txt` Y `prompts/short_story.txt` (perfiles "largo" y
"short" respectivamente -- son bloques DISTINTOS, no el mismo texto pegado
dos veces) y solo se llama cuando el usuario da el OK desde el dashboard (o
pasa --apply-trends por CLI). `remove_from_prompt` lo revierte, también en
los dos.
"""

import json
import logging
import os
import re
import tempfile
from datetime import datetime, timezone

from modules.script_generator import _call_openrouter

logger = logging.getLogger(__name__)

# Marcadores del bloque auto-generado dentro del prompt de historias.
BEGIN_MARK = "=== INICIO TENDENCIAS AUTO (no editar a mano) ==="
END_MARK = "=== FIN TENDENCIAS AUTO ==="

# Secciones que se le exigen al LLM. Las dos últimas son el bloque pensado para
# SHORTS (título 10-18 palabras, sin instrucciones de duración/estructura de
# vídeo largo) -- ver `render_injection(perfil=...)` más abajo.
SECTIONS = (
    "ANALISIS", "VEREDICTO", "DIRECTRICES", "TITULARES",
    "DIRECTRICES_SHORT", "TITULARES_SHORT",
)


def advice_path(config):
    data_dir = config.get("paths", {}).get("data_dir", "./data")
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, "competition_advice.json")


def load_advice(config):
    path = advice_path(config)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def save_advice(advice, config):
    with open(advice_path(config), "w", encoding="utf-8") as f:
        json.dump(advice, f, ensure_ascii=False, indent=2)


# ----------------------------------------------------------------------------
# Clasificación de nicho (lo que los heurísticos no pueden decidir)
# ----------------------------------------------------------------------------

def build_classify_prompt(candidates):
    """Prompt para separar competencia real de canales de otro nicho."""
    bloques = []
    for i, c in enumerate(candidates, 1):
        titulos = "\n".join(f"     - {t[:110]}" for t in c.get("sample_titles", [])[:4])
        bloques.append(f"  {i}. {c['title']}\n{titulos}")

    return f"""Clasificas canales de YouTube en español para un canal de "historias de Reddit":
historias largas narradas en PRIMERA PERSONA (dramas familiares, traiciones, venganza,
justicia) con gameplay de fondo. Compiten por la misma audiencia.

SÍ es competencia:
- Historias/relatos narrados en primera persona, aunque no usen gameplay.
- Canales de venganza, karma, dramas familiares, subforos, Reddit.

NO es competencia (otro nicho):
- Drama asiático doblado o subtitulado, novelas por capítulos, "mini dramas".
- Películas, cortometrajes, series, recopilaciones de vídeo.
- Podcasts de terror o paranormal, creepypastas, misterio.
- Canales de música, infantiles, noticias o entretenimiento general.

CANALES A CLASIFICAR:
{chr(10).join(bloques)}

Devuelve EXACTAMENTE {len(candidates)} líneas, una por cada canal y en el mismo orden,
con este formato y nada más (sin encabezados, sin explicaciones, sin repetir títulos):
<número>|<SI o NO>|<motivo en menos de 8 palabras>

Ejemplo:
1|SI|historias de venganza en primera persona
2|NO|drama chino doblado por capítulos"""


def parse_classification(raw, candidates):
    """Parsea la respuesta del clasificador -> {channel_id: (bool, motivo)}."""
    verdicts = {}
    for line in raw.splitlines():
        parts = [p.strip() for p in line.strip().split("|")]
        if len(parts) < 2:
            continue
        try:
            idx = int(re.sub(r"\D", "", parts[0])) - 1
        except ValueError:
            continue
        if not (0 <= idx < len(candidates)):
            continue
        in_niche = parts[1].upper().startswith("S") or parts[1].upper().startswith("Y")
        # Se unen los trozos restantes: si el modelo mete un "|" en el motivo,
        # quedarse solo con parts[2] cortaba la frase por la mitad.
        reason = " ".join(parts[2:])[:120] if len(parts) > 2 else ""
        verdicts[candidates[idx]["channel_id"]] = (in_niche, reason)
    return verdicts


def classify_channels(candidates, config, progress=None):
    """Pregunta al modelo cuáles de estos canales son competencia de verdad.

    Se recurre al LLM porque los heurísticos NO bastan, y está medido: el ratio
    de primera persona en los títulos da 0% en un competidor real (con
    gameplay) y 25% en el líder del nicho, pero 75% en un canal de drama
    chino doblado. Cualquier umbral o mata competencia real o deja entrar
    esos canales de drama doblado.

    Devuelve {channel_id: (es_competencia, motivo)}. Si falla, devuelve {} y el
    escaneo continúa sin clasificar: nunca debe tumbar una corrida.
    """
    candidates = [c for c in candidates if c.get("sample_titles")]
    if not candidates:
        return {}

    if progress:
        progress(f"Clasificando {len(candidates)} canales por nicho…")

    classify_config = dict(config)
    classify_config["openrouter"] = {
        **config.get("openrouter", {}),
        "temperature": 0.1,  # es una clasificación, no una opinión
    }

    # Lotes PEQUEÑOS y varias pasadas. Medido: con 25 canales por lote el modelo
    # devolvió veredicto de 3 y se saltó 49; con 8 seguía omitiendo 24. En cada
    # pasada se reduce el lote a la mitad sobre los que faltan, hasta ir de uno
    # en uno. El coste es $0, así que compensa insistir antes que dejar canales
    # sin veredicto en silencio.
    batch = int(config.get("competition", {}).get("classify_batch_size", 8))
    passes = int(config.get("competition", {}).get("classify_passes", 3))

    verdicts = {}
    pending = list(candidates)

    for attempt in range(passes):
        if not pending:
            break
        size = max(1, batch // (2 ** attempt))
        if attempt:
            logger.info(f"Clasificación: pasada {attempt + 1} sobre {len(pending)} canales (lotes de {size})")

        for chunk in (pending[i:i + size] for i in range(0, len(pending), size)):
            prompt = build_classify_prompt(chunk)
            try:
                raw = _call_openrouter(
                    [{"role": "user", "content": prompt}], classify_config, max_tokens=2000
                )
            except Exception as e:
                logger.warning(f"La clasificación por nicho falló: {e}")
                continue
            verdicts.update(parse_classification(raw, chunk))

        pending = [c for c in pending if c["channel_id"] not in verdicts]

    if pending:
        logger.warning(
            f"{len(pending)} canales sin clasificar tras {passes} pasadas; siguen "
            f"activos y se reintentarán en el próximo escaneo: "
            f"{', '.join(c['title'] for c in pending[:4])}"
        )

    return verdicts


# ----------------------------------------------------------------------------
# Construcción del prompt de debate
# ----------------------------------------------------------------------------

def _format_viral_table(videos, limit=12):
    lines = []
    for i, v in enumerate(videos[:limit], 1):
        partial = " [métricas parciales]" if v.get("metrics_partial") else ""
        lines.append(
            f"{i}. \"{v['title']}\"\n"
            f"   canal: {v['channel_title']} | {v['views']:,} vistas | "
            f"engagement {v['engagement_rate'] * 100:.2f}% | "
            f"x{v.get('outlier_ratio', 0):.1f} sobre su media | "
            f"{v['views_per_hour']:.0f} vistas/h | hace {v['age_days']:.0f} días | "
            f"{v['duration_sec'] // 60:.0f} min | score {v['viral_score']}{partial}"
        )
    return "\n".join(lines)


def _format_competitor_table(channels, limit=15):
    lines = []
    for i, c in enumerate(channels[:limit], 1):
        subs = "oculto" if c.get("subscribers_hidden") else f"{c.get('subscribers', 0):,}"
        lines.append(
            f"{i}. {c['title']} — {subs} subs | mediana {c.get('median_views', 0):,} vistas/video | "
            f"{c.get('uploads_last_30d', 0)} subidas en 30d | "
            f"largo {c.get('long_form_ratio', 0):.0%}"
        )
    return "\n".join(lines)


def build_debate_prompt(report, config):
    """Prompt del debate: datos reales + reglas actuales de nuestro canal."""
    story_cfg = config.get("story", {})
    viral = report.get("viral", [])
    competitors = report.get("competitors", [])

    return f"""Eres un estratega de contenido de YouTube especializado en canales de historias
narradas en español (estilo subforos/Reddit: dramas familiares, traiciones, justicia).

Analizas la competencia REAL de nuestro canal con datos medidos hoy. Nuestro canal
publica videos de {story_cfg.get('target_duration_min', 1200) // 60}-{story_cfg.get('target_duration_max', 2400) // 60} minutos
con títulos largos (20-35 palabras) en estilo "{story_cfg.get('style', 'dramatic')}", más SHORTS
verticales de ~200 palabras (40-60 segundos) con títulos cortos (10-18 palabras). Son dos
formatos distintos y necesito directrices separadas para cada uno.

=== COMPETIDORES ACTIVOS ({len(competitors)}) ===
{_format_competitor_table(competitors) or "(ninguno)"}

=== SUS VIDEOS MÁS VIRALES AHORA ({len(viral)}) ===
{_format_viral_table(viral) or "(ninguno)"}

Cómo leer las métricas:
- "engagement" = (likes + comentarios) / vistas. Mide si el video conecta, no si es grande.
- "xN sobre su media" = vistas del video dividido por la mediana de ese canal. Es la señal
  de viralidad real: aísla el video que ROMPE respecto a lo normal en su propio canal.
- "score" combina esas señales: el outlier pesa por su magnitud real y el resto por
  percentil dentro de este mismo corpus.

TAREA: decide qué debemos atacar en nuestros próximos videos. Debate de verdad:
contrasta al menos dos opciones (por ejemplo, imitar al líder frente a explotar un nicho
donde un canal pequeño está reventando) y quédate con una, justificando con las cifras
de arriba. Si los datos no dan para una conclusión, dilo en vez de inventarla.

Responde EXACTAMENTE con estas seis secciones y nada más. NO escribas tu
razonamiento antes: la PRIMERA línea de tu respuesta debe ser "=== ANALISIS ===".

=== ANALISIS ===
Qué patrón ves en los virales: temas, tipo de conflicto, relación (suegra/jefe/hermano),
estructura del título, duración. Qué canal está creciendo y a costa de qué. Menciona
títulos concretos de la lista cuando afirmes algo.

=== VEREDICTO ===
Una decisión clara en 3-5 frases: qué ángulo atacamos y por qué gana a la alternativa
que descartas. Nombra el video o canal de referencia.

=== DIRECTRICES ===
De 4 a 7 instrucciones imperativas, concretas y accionables para el guionista que
escribe nuestras historias LARGAS (20-40 minutos): temas a priorizar, tipo de
conflicto, qué evitar, ritmo/estructura del vídeo largo. Una por línea, empezando
con "- ". Sin explicaciones, solo la instrucción.

=== TITULARES ===
5 títulos de ejemplo de 20-35 palabras siguiendo el veredicto, en Capitalización De
Título y cortados con "..." al final. Uno por línea, numerados.

=== DIRECTRICES_SHORT ===
De 3 a 5 instrucciones imperativas para el guionista de nuestros SHORTS/TikTok
(~200 palabras, 40-60 segundos, título de 10-18 palabras): mismo ángulo y tema que
el veredicto de arriba, pero SIN mencionar minutos, actos, setup, escalada ni
estructura de vídeo largo -- un short no tiene 5 minutos de contexto ni un clímax
en el minuto 20. Una por línea, empezando con "- ".

=== TITULARES_SHORT ===
5 títulos de ejemplo de 10-18 palabras (NO 20-35) siguiendo el mismo ángulo, en
Capitalización De Título. Uno por línea, numerados.

REGLAS: no uses llaves {{ }} en ninguna parte de tu respuesta. No añadas secciones extra.
No incluyas markdown de cabecera (#) ni negritas."""


# ----------------------------------------------------------------------------
# Parseo de la respuesta
# ----------------------------------------------------------------------------

def parse_debate(text):
    """Trocea la respuesta en {analisis, veredicto, directrices, titulares}.

    Tolerante: si el LLM se salta una sección, esa queda vacía y el resto sirve.
    """
    result = {s.lower(): "" for s in SECTIONS}
    current = None
    buffer = []

    for line in text.splitlines():
        stripped = line.strip().strip("=").strip()
        normalized = (
            stripped.upper()
            .replace("Á", "A").replace("É", "E").replace("Í", "I")
            .replace("Ó", "O").replace("Ú", "U")
        )
        if normalized in SECTIONS:
            if current:
                result[current] = "\n".join(buffer).strip()
            current = normalized.lower()
            buffer = []
            continue
        if current:
            buffer.append(line)

    if current:
        result[current] = "\n".join(buffer).strip()

    return result


def _as_list(block):
    """Extrae los ítems de un bloque en lista (guiones o numeración)."""
    items = []
    for line in block.splitlines():
        line = line.strip()
        if not line:
            continue
        for prefix in ("- ", "* ", "• "):
            if line.startswith(prefix):
                line = line[len(prefix):]
                break
        else:
            # "1. texto" / "1) texto"
            parts = line.split(" ", 1)
            if parts[0].rstrip(".)").isdigit() and len(parts) == 2:
                line = parts[1]
        line = line.strip()
        if line:
            items.append(line)
    return items


def debate(report, config, progress=None):
    """Llama al LLM con los datos del escaneo y devuelve el consejo estructurado."""
    if not report or not report.get("viral"):
        raise ValueError(
            "No hay videos virales en el informe. Ejecuta primero un escaneo de "
            "competencia con resultados."
        )

    if progress:
        progress("Debatiendo con el modelo qué atacar…")

    # Temperatura más baja que la de las historias: aquí queremos criterio
    # estable sobre datos, no creatividad.
    debate_config = dict(config)
    debate_config["openrouter"] = {
        **config.get("openrouter", {}),
        "temperature": config.get("competition", {}).get("debate_temperature", 0.4),
    }

    prompt = build_debate_prompt(report, config)

    # Se reintenta si la respuesta no trae lo esencial. MEDIDO: el modelo (que
    # razona) escribió su razonamiento en voz alta, agotó el presupuesto y
    # devolvió 448 caracteres sin ninguna sección. Antes eso se guardaba tal
    # cual y el dashboard mostraba un veredicto vacío sin explicar por qué.
    #
    # El bloque de SHORT (DIRECTRICES_SHORT/TITULARES_SHORT) se engancha al
    # MISMO mecanismo: si falta, se reintenta -- pero solo se RAISEA si nunca
    # llega lo esencial (veredicto+directrices). Si el bloque de short no
    # aparece tras agotar los `attempts` ya presupuestados, se usa el último
    # resultado esencial-completo y se deja el campo vacío (§17: no se
    # inventa; el consumidor -- `render_injection(perfil="short")` -- tiene su
    # propio fallback con dientes para ese caso). Esto NO gasta peticiones de
    # más: sigue acotado por `debate_retries` (default 3), igual que antes.
    attempts = int(config.get("competition", {}).get("debate_retries", 3))
    raw, sections = "", {}
    best_raw, best_sections = None, None
    for attempt in range(attempts):
        current = prompt
        if attempt:
            logger.warning(f"Debate mal formado o incompleto; reintento {attempt + 1}/{attempts}")
            current = (
                "TU RESPUESTA ANTERIOR NO SIRVIÓ: o te pusiste a razonar en voz alta, o te\n"
                "saltaste las secciones DIRECTRICES_SHORT / TITULARES_SHORT (el bloque para\n"
                "SHORTS, distinto del de vídeo largo). Escribe las SEIS secciones completas.\n"
                "Empieza YA con la línea '=== ANALISIS ===' y no escribas NADA antes.\n\n"
            ) + prompt
        raw = _call_openrouter(
            [{"role": "user", "content": current}], debate_config, max_tokens=4000
        )
        sections = parse_debate(raw)
        if sections["veredicto"].strip() and sections["directrices"].strip():
            best_raw, best_sections = raw, sections
            if sections["directrices_short"].strip():
                break  # lo esencial Y el bloque de short: no hace falta más
            continue  # lo esencial está; se insiste por el bloque de short
    else:
        if best_sections is None:
            raise RuntimeError(
                f"El modelo no devolvió un debate utilizable tras {attempts} intentos. "
                f"Última respuesta ({len(raw)} caracteres): {raw[:200]}"
            )
        logger.warning(
            f"El modelo nunca devolvió DIRECTRICES_SHORT/TITULARES_SHORT tras "
            f"{attempts} intentos; se guarda el debate SIN bloque de short "
            f"(render_injection(perfil='short') usa su fallback filtrado)."
        )
        raw, sections = best_raw, best_sections

    advice = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "based_on_report": report.get("generated_at"),
        "analisis": sections["analisis"],
        "veredicto": sections["veredicto"],
        "directrices": _as_list(sections["directrices"]),
        "titulares": _as_list(sections["titulares"]),
        "directrices_short": _as_list(sections["directrices_short"]),
        "titulares_short": _as_list(sections["titulares_short"]),
        "raw": raw,
        "sources": [
            {"title": v["title"], "url": v["url"], "channel": v["channel_title"],
             "views": v["views"], "viral_score": v["viral_score"]}
            for v in report["viral"][:10]
        ],
    }

    save_advice(advice, config)
    logger.info(
        f"Debate listo: {len(advice['directrices'])} directrices / "
        f"{len(advice['titulares'])} titulares (largo), "
        f"{len(advice['directrices_short'])} directrices / "
        f"{len(advice['titulares_short'])} titulares (short)"
    )
    return advice


# ----------------------------------------------------------------------------
# Inyección en el prompt de historias
# ----------------------------------------------------------------------------

# Directrices de FORMATO de vídeo largo que NO aplican a un short. Filtro
# EXPLÍCITO y determinista (§17: lo que importa se impone en código, no se
# pide) -- se usa SOLO como fallback cuando el advice no trae
# `directrices_short` (advice viejo, o el modelo nunca las devolvió pese a los
# reintentos de `debate`). Medido en A/B real de 19 generaciones
# (10 control / 9 con el bloque largo inyectado tal cual en el prompt de
# shorts): la directriz "Duración objetivo 32-38 min: 5 min setup, 20-25 min
# escalada, 5-8 min clímax, 2-3 min cierre." es ruido puro en un prompt de
# ~200 palabras / 40s. Palabras que delatan esa clase de directriz:
_FORMATO_LARGO_RE = re.compile(
    r"\bmin(?:uto)?s?\b|\bduraci[oó]n\b|\bacto(?:s)?\b|\bset ?up\b|"
    r"\bcl[ií]max\b|\bescalad[ao]\b",
    re.IGNORECASE,
)


def render_injection(advice, perfil="largo"):
    """Construye el bloque de texto que se inserta en un prompt.

    `perfil`:
    - "largo" (default, compatible con el uso previo): bloque para
      `reddit_story.txt` con `directrices`/`titulares` tal cual los devolvió
      el debate.
    - "short": bloque para `short_story.txt`. Usa `directrices_short` /
      `titulares_short` si el advice los trae (debate reciente). Si NO los
      trae -- advice viejo como `data/competition_advice.json` (5-ago), o el
      modelo nunca los devolvió -- cae a un FALLBACK con dientes: filtra
      DETERMINISTAMENTE las directrices largas que hablan de duración/actos/
      estructura (ver `_FORMATO_LARGO_RE`), NO inyecta los titulares largos
      (miden 19-23 palabras contra las 10-18 que exige `short_story.txt`), y
      añade una línea que ORDENA explícitamente la longitud del short en vez
      de esperar que el modelo la infiera del contexto (§17).

    CRÍTICO: el prompt se consume con str.format() en script_generator /
    shorts_generator, así que cualquier llave del texto generado por el LLM
    (en CUALQUIERA de los dos perfiles) rompería la generación con KeyError.
    Se duplican para que format() las devuelva como llaves literales.
    """
    if perfil not in ("largo", "short"):
        raise ValueError(f"perfil desconocido: {perfil!r} (usa 'largo' o 'short')")

    def esc(text):
        return text.replace("{", "{{").replace("}", "}}")

    lines = [
        BEGIN_MARK,
        f"TENDENCIAS DE LA COMPETENCIA (medidas el {advice['generated_at'][:10]}).",
        "Aplica estas directrices al elegir tema, conflicto y título:",
        "",
    ]

    if perfil == "largo":
        for d in advice.get("directrices", []):
            lines.append(f"- {esc(d)}")

        titulares = advice.get("titulares", [])
        if titulares:
            lines += ["", "Ejemplos de títulos alineados con lo que funciona ahora mismo:"]
            for t in titulares[:5]:
                lines.append(f'  "{esc(t)}"')

    else:  # perfil == "short"
        directrices_short = advice.get("directrices_short", [])
        if directrices_short:
            for d in directrices_short:
                lines.append(f"- {esc(d)}")
        else:
            # FALLBACK con dientes (ver docstring): filtra las directrices de
            # formato largo en vez de inyectarlas tal cual.
            for d in advice.get("directrices", []):
                if _FORMATO_LARGO_RE.search(d):
                    continue
                lines.append(f"- {esc(d)}")
            lines.append(
                "- Aplica el MISMO ángulo y tono de arriba, pero el título de "
                "ESTE short debe tener 10-18 palabras (NO 20-35): es un "
                "formato distinto, no una versión larga."
            )

        titulares_short = advice.get("titulares_short", [])
        if titulares_short:
            lines += ["", "Ejemplos de títulos alineados con lo que funciona ahora mismo:"]
            for t in titulares_short[:5]:
                lines.append(f'  "{esc(t)}"')
        # Sin fallback de titulares: los largos (20-35 palabras) contradicen
        # directamente la regla de 10-18 de `short_story.txt` -- es
        # exactamente el defecto medido en el A/B (2/9 títulos fuera de rango
        # cuando se inyectaba el bloque largo sin filtrar).

    lines.append(END_MARK)
    return "\n".join(lines)


# Perfiles recorridos por `apply_to_prompt`/`remove_from_prompt` cuando actúan
# "por defecto" (perfil=None) sobre los DOS prompts.
_PROMPT_PROFILES = ("largo", "short")


def _prompt_path(config):
    return config.get("paths", {}).get("prompt_template", "./prompts/reddit_story.txt")


def _path_for(config, perfil):
    """Ruta del prompt para ese perfil, o None si el config no la declara.

    Para "short" NO hay ruta por defecto, a propósito, y esto es asimétrico
    respecto a `_prompt_path` a sabiendas: `apply_to_prompt` **escribe** aquí.
    Un default a "./prompts/short_story.txt" hace que cualquier llamante que
    no declare `short_prompt` —un test, el config del gate, un script de
    medición— reescriba el prompt de PRODUCCIÓN sin haberlo nombrado nunca.
    No es hipotético: pasó durante la verificación de este mismo cambio. Un
    test que apuntaba `prompt_template` a una copia acabó inyectando dos
    bloques en `prompts/short_story.txt` de verdad, y solo se detectó porque
    el test comprobaba explícitamente que el fichero real seguía intacto.

    "largo" conserva su default histórico: ya existía antes de este cambio y
    los dos llamantes de producción (`main.py`, `dashboard.py`) pasan el
    config completo.
    """
    if perfil == "short":
        return (config.get("paths") or {}).get("short_prompt") or None
    return _prompt_path(config)


def _sin_ruta_declarada(prof, explicito):
    """Ruta no declarada: o revienta (si la pidieron a propósito) o se omite
    con log ruidoso. Nunca se inventa un destino de escritura (§13)."""
    msg = (
        f"config.paths.short_prompt no está declarado: NO se toca el prompt de "
        f"perfil {prof!r}. No se usa ninguna ruta por defecto a propósito, porque "
        f"escribiría en el prompt de producción sin que el config lo nombre."
    )
    if explicito:
        raise ValueError(msg)
    logger.warning(msg)


def _detect_newline(text):
    """Estilo de salto de línea que YA tiene el fichero: se PRESERVA, nunca se
    impone uno nuevo.

    D1 medido por el panel: escribiendo con open(path, "w", encoding="utf-8")
    SIN newline="", Python traduce cada "\\n" a os.linesep al escribir (en
    Windows, "\\r\\n"), aunque el fichero en disco fuera LF puro. Con eso el
    round-trip apply+remove NO era byte a byte: +77 bytes en
    reddit_story.txt, uno por cada línea del fichero (77 líneas). Detectando
    el estilo real aquí y leyendo/escribiendo siempre con newline="" (sin
    traducción en NINGUNA dirección) el round-trip queda exacto.
    """
    return "\r\n" if "\r\n" in text else "\n"


def _read_text(path):
    """Lee sin traducir saltos de línea, para poder reproducirlos byte a byte
    al escribir de vuelta (ver _detect_newline)."""
    with open(path, "r", encoding="utf-8", newline="") as f:
        return f.read()


def _atomic_write(path, text):
    """Escribe `text` en `path` de forma atómica: fichero temporal en el
    MISMO directorio + os.replace().

    D3 medido: `shorts_generator.py` abre el prompt una vez POR short y
    `script_generator.py` una vez por historia, y un `open(path, "w")`
    directo TRUNCA el fichero antes de volver a escribirlo — hay una ventana
    real en la que esa lectura concurrente se encuentra el prompt vacío o a
    medias. `os.replace()` sustituye el fichero de golpe (es atómico en el
    mismo volumen, tanto en POSIX como en Windows): no existe ese estado
    intermedio.

    newline="" también aquí, en simetría con `_read_text`: escribe EXACTAMENTE
    los bytes de saltos de línea que ya trae `text` (ver _detect_newline),
    sin que Python los reescriba a os.linesep.
    """
    directory = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".trend_advisor_tmp_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        os.replace(tmp_path, path)
    except Exception:
        # Nunca dejar el temporal huérfano ni tragarnos el error: regla del
        # repo, ningún fallback silencioso — log ruidoso + propagar.
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        logger.error(f"Escritura atómica de {path} fallida: {tmp_path} no se pudo mover")
        raise


def _write_backup(path, text):
    """Copia .bak ANTES de tocar el original, también atómica."""
    _atomic_write(path + ".bak", text)


def strip_injection(text):
    """Devuelve el prompt sin NINGÚN bloque auto-generado (idempotente).

    D2 medido por el panel, dos bugs reales:
    - Un BEGIN_MARK sin END_MARK (bloque truncado) hacía
      `return text[:start].rstrip() + "\\n"`: BORRABA todo lo que viniera
      después, incluida la línea final "Historia:" de la que depende el
      resto del prompt. Ahora un bloque corrupto NO se toca — se deja
      intacto y se avisa con logger.error (ruidoso, nunca un borrado en
      silencio).
    - Usaba `find` (solo el primer bloque). Si por lo que sea el prompt
      terminaba con dos bloques inyectados, el segundo sobrevivía. Ahora se
      recorre en bucle hasta que no quede ningún BEGIN_MARK bien formado.
    """
    nl = _detect_newline(text)
    result = text
    while True:
        start = result.find(BEGIN_MARK)
        if start == -1:
            return result

        end = result.find(END_MARK, start)
        if end == -1:
            logger.error(
                f"Bloque de tendencias truncado en el prompt: hay "
                f"{BEGIN_MARK!r} sin su {END_MARK!r} correspondiente. Se "
                f"deja el fichero SIN TOCAR para no perder contenido "
                f"legítimo (el ancla 'Historia:' incluida); revísalo a mano."
            )
            return result
        end += len(END_MARK)

        head = result[:start].rstrip()
        # rstrip()/lstrip() SIN argumento de caracteres tratan \r y \n como
        # el mismo tipo de whitespace, así que esto normaliza igual de bien
        # separadores LF (\n) que CRLF (\r\n) sin dejar un \r suelto.
        tail = result[end:].lstrip("\r\n")
        if not tail:
            result = head + nl
        else:
            # Línea en blanco entre head y tail: es la separación que había
            # ANTES de inyectar (medido en los dos prompts reales: siempre
            # hay una línea en blanco delante de "Historia:"), y sin ella
            # revertir no devolvía el prompt byte a byte.
            result = head + nl + nl + tail


def current_injection(config, perfil=None):
    """El bloque actualmente inyectado en un prompt, o None.

    Por defecto (`perfil=None`) mira el prompt de HISTORIAS LARGAS
    (`prompt_template`) -- comportamiento IDÉNTICO al de antes de este
    cambio, porque es lo que muestra hoy la pestaña Competencia del
    dashboard ("bloque inyectado en el prompt de historias"). Pasa
    `perfil="short"` para consultar `short_prompt` en su lugar.
    """
    path = _path_for(config, perfil or "largo")
    if path is None or not os.path.isfile(path):
        return None
    text = _read_text(path)
    start = text.find(BEGIN_MARK)
    if start == -1:
        return None
    end = text.find(END_MARK, start)
    return text[start:end + len(END_MARK)] if end != -1 else text[start:]


def _apply_single(advice, path, perfil, backup):
    """Aplica el bloque de tendencias de `perfil` a UN prompt concreto.

    Misma mecánica que la `apply_to_prompt` original (backup atómico +
    strip_injection idempotente + inserción antes de "Historia:"), ahora
    parametrizada por ruta y perfil para poder repetirla en los dos prompts.
    """
    text = _read_text(path)
    nl = _detect_newline(text)

    if backup:
        _write_backup(path, text)

    text = strip_injection(text)
    block = render_injection(advice, perfil=perfil)
    if nl != "\n":
        # render_injection construye el bloque con "\n" internamente; se
        # traduce al estilo real del fichero para que, tras insertarlo, el
        # fichero quede UNIFORME (necesario para que strip_injection lo
        # pueda revertir byte a byte más tarde).
        block = block.replace("\n", nl)

    anchor = nl + "Historia:"
    idx = text.rfind(anchor)
    if idx != -1:
        new_text = text[:idx].rstrip() + nl + nl + block + nl + text[idx:]
    else:
        new_text = text.rstrip() + nl + nl + block + nl

    _atomic_write(path, new_text)
    logger.info(f"Tendencias ({perfil}) inyectadas en {path}")
    return path


def apply_to_prompt(advice, config, backup=True, perfil=None):
    """Inserta (o reemplaza) el bloque de tendencias en el/los prompt(s).

    Por defecto (`perfil=None`) aplica en LOS DOS: `reddit_story.txt` con el
    bloque de vídeo largo y `short_story.txt` con el bloque específico de
    shorts (`render_injection(advice, perfil="short")` -- NO es el mismo
    texto, ver esa función). Esta es la firma que siguen llamando
    `main.py:213` (`apply_to_prompt(advice, config)`) y `dashboard.py:891`
    sin tocarlas: con `perfil=None` "lo razonable" pasó a ser cerrar el hueco
    de que los shorts nunca recibían directrices de competencia. Devuelve la
    LISTA de rutas tocadas.

    `perfil="largo"` o `perfil="short"` aplica SOLO a ese prompt y devuelve
    su ruta como `str` (firma/retorno idénticos a los de antes de este
    cambio para ese caso).

    Se coloca justo antes de la línea final "Historia:" de cada prompt, para
    que sea lo último que lee el modelo antes de escribir.
    """
    if not advice.get("directrices"):
        raise ValueError("El consejo no tiene directrices; no hay nada que inyectar.")

    perfiles = _PROMPT_PROFILES if perfil is None else (perfil,)
    if any(p not in _PROMPT_PROFILES for p in perfiles):
        raise ValueError(f"perfil desconocido: {perfil!r} (usa 'largo', 'short' o None)")

    applied = []
    for prof in perfiles:
        path = _path_for(config, prof)
        if path is None:
            _sin_ruta_declarada(prof, explicito=perfil is not None)
            continue
        if not os.path.isfile(path):
            logger.warning(
                f"Prompt de perfil {prof!r} no existe ({path!r}); se omite la inyección."
            )
            continue
        applied.append(_apply_single(advice, path, prof, backup))

    if not applied:
        raise FileNotFoundError(
            "Ningún prompt disponible para inyectar (revisa config.paths.prompt_template "
            "/ config.paths.short_prompt)."
        )

    return applied[0] if perfil is not None else applied


def _remove_single(path):
    """Quita el bloque de tendencias de UN prompt concreto. True si había algo.

    D2: hace `.bak` ANTES de escribir, igual que `_apply_single`. Antes solo
    `apply_to_prompt` respaldaba, y como `.bak` está en `.gitignore`, un fallo
    aquí no se podía recuperar ni desde git.
    """
    text = _read_text(path)
    if BEGIN_MARK not in text:
        return False

    new_text = strip_injection(text)
    if new_text == text:
        # Bloque corrupto: strip_injection ya no pudo quitar nada y lo
        # dejó tal cual (con su logger.error propio). No reescribir nada
        # sin necesidad — un os.replace() que no cambia contenido no aporta.
        return False

    _write_backup(path, text)
    _atomic_write(path, new_text)
    logger.info(f"Tendencias eliminadas de {path}")
    return True


def remove_from_prompt(config, perfil=None):
    """Quita el bloque de tendencias del prompt (o de los DOS, por defecto).

    Por defecto (`perfil=None`) revierte tanto `reddit_story.txt` como
    `short_story.txt` -- simétrico con el default nuevo de `apply_to_prompt`.
    Es la firma que sigue llamando `dashboard.py:898`
    (`remove_from_prompt(config)`) sin tocarla. `perfil="largo"` o
    `perfil="short"` revierte solo ese prompt.

    Devuelve True si se quitó algo de AL MENOS un prompt (para el caso de un
    solo perfil, idéntico al `bool` que devolvía la función original).
    """
    perfiles = _PROMPT_PROFILES if perfil is None else (perfil,)
    if any(p not in _PROMPT_PROFILES for p in perfiles):
        raise ValueError(f"perfil desconocido: {perfil!r} (usa 'largo', 'short' o None)")

    removed_any = False
    for prof in perfiles:
        path = _path_for(config, prof)
        if path is None:
            _sin_ruta_declarada(prof, explicito=perfil is not None)
            continue
        if not os.path.isfile(path):
            continue
        removed_any = _remove_single(path) or removed_any
    return removed_any
