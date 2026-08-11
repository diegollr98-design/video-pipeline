"""Buscador de competencia y detector de virales (YouTube Data API v3).

Cubre los pasos 1 y 2 del roadmap de competencia:
  1. Lista de competidores que se actualiza sola (semillas + expansión por keywords).
  2. De esa lista, los últimos videos más virales según engagement/vistas.

El paso 3 (debatir qué atacar) vive en `trend_advisor.py`.

Presupuesto de cuota (la API v3 da 10.000 unidades/día gratis):
  - search.list        = 100 unidades  -> SOLO para descubrir canales nuevos
  - channels.list      =   1 unidad    (hasta 50 IDs por llamada)
  - playlistItems.list =   1 unidad    (hasta 50 videos por llamada)
  - videos.list        =   1 unidad    (hasta 50 IDs por llamada)

Por eso los videos recientes de cada canal NO se piden con search.list sino
leyendo su playlist de subidas: un escaneo de 40 canales cuesta ~90 unidades.
El gasto se contabiliza por día natural en el state y se corta antes de pasarse.
"""

import json
import logging
import math
import os
import re
import time
from datetime import datetime, timedelta, timezone

import requests

logger = logging.getLogger(__name__)

API_BASE = "https://www.googleapis.com/youtube/v3"

# Coste en unidades de cuota de cada endpoint que usamos.
QUOTA_COST = {
    "search": 100,
    "channels": 1,
    "playlistItems": 1,
    "videos": 1,
    # Subir un vídeo cuesta 1.600 de las 10.000 unidades diarias, y salen del
    # MISMO cupo que el análisis de competencia: 6 subidas al día agotan la
    # cuota entera. Vive en esta tabla, y no en el uploader, para que haya un
    # único contador — dos contadores distintos harían que el corte preventivo
    # de `QuotaMeter` dejara de proteger.
    "videosInsert": 1600,
}

# Marcadores de idioma. La API no rellena defaultAudioLanguage de forma fiable,
# así que el idioma se deduce del texto.
#
# OJO con las ambiguas: "me", "no", "y", "un", "son" son palabras españolas Y
# palabras (o fragmentos) ingleses. Con ellas dentro, el título real
# "a dream made me kiss my friend and now we're both g@y" contaba 2 aciertos
# ("me" y la "y" que el regex extrae de "g@y") y colaba un canal inglés en el
# puesto 2 del ranking. Aquí solo van palabras que en inglés no existen.
_SPANISH_STOPWORDS = {
    "que", "de", "la", "el", "los", "las", "mi", "por", "para", "con",
    "una", "pero", "se", "su", "sus", "al", "del", "en", "es", "está",
    "cuando", "porque", "como", "más", "mas", "todo", "toda", "muy",
    "desde", "hasta", "sobre", "entre", "aunque", "también", "así",
    "hijo", "hija", "madre", "padre", "esposa", "esposo", "marido", "mujer",
    "familia", "hermano", "hermana", "suegra", "suegro", "jefe", "abuela",
    "historia", "historias", "vida", "casa", "dijo", "años",
}

# Si aparecen estas, casi seguro NO es español. Sirven para desempatar.
_ENGLISH_MARKERS = {
    "the", "and", "my", "you", "your", "was", "were", "this", "that", "with",
    "from", "when", "what", "why", "how", "she", "he", "her", "his", "they",
    "story", "stories", "revenge", "family", "wife", "husband", "mother",
    "father", "son", "daughter", "boss", "did", "got", "made", "told",
}


# ----------------------------------------------------------------------------
# Errores
# ----------------------------------------------------------------------------

class QuotaExhausted(RuntimeError):
    """La cuota diaria de la API se agotó (local o del lado de Google)."""


class MissingApiKey(RuntimeError):
    """No hay YOUTUBE_API_KEY configurada."""


# ----------------------------------------------------------------------------
# Estado persistente (lista de competidores + contador de cuota)
# ----------------------------------------------------------------------------

def _data_dir(config):
    path = config.get("paths", {}).get("data_dir", "./data")
    os.makedirs(path, exist_ok=True)
    return path


def state_path(config):
    return os.path.join(_data_dir(config), "competitors.json")


def report_path(config):
    return os.path.join(_data_dir(config), "competition_report.json")


def load_state(config):
    """Carga el state persistente. Devuelve la estructura vacía si no existe."""
    path = state_path(config)
    if not os.path.isfile(path):
        return {"updated_at": None, "quota": {}, "competitors": {}}
    try:
        with open(path, "r", encoding="utf-8") as f:
            state = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"State de competencia ilegible ({e}); se reinicia")
        return {"updated_at": None, "quota": {}, "competitors": {}}

    state.setdefault("quota", {})
    state.setdefault("competitors", {})
    return state


def save_state(state, config):
    state["updated_at"] = _now().isoformat()
    with open(state_path(config), "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def load_report(config):
    path = report_path(config)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def save_report(report, config):
    with open(report_path(config), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)


# ----------------------------------------------------------------------------
# Cliente de la API + contador de cuota
# ----------------------------------------------------------------------------

def _now():
    return datetime.now(timezone.utc)


class QuotaMeter:
    """Contabiliza unidades gastadas por día natural (UTC) sobre el state."""

    def __init__(self, state, daily_limit):
        self.daily_limit = daily_limit
        self.today = _now().strftime("%Y-%m-%d")
        quota = state.get("quota", {})
        # Si el contador es de otro día, empieza de cero.
        self.spent = int(quota.get("units", 0)) if quota.get("date") == self.today else 0
        self.spent_this_run = 0
        self._state = state

    def remaining(self):
        return max(0, self.daily_limit - self.spent)

    def can_afford(self, endpoint):
        return QUOTA_COST[endpoint] <= self.remaining()

    def charge(self, endpoint):
        cost = QUOTA_COST[endpoint]
        if cost > self.remaining():
            raise QuotaExhausted(
                f"Cuota diaria agotada: {self.spent}/{self.daily_limit} unidades usadas hoy"
            )
        self.spent += cost
        self.spent_this_run += cost
        self._state["quota"] = {"date": self.today, "units": self.spent}


def get_api_key(config):
    key = os.environ.get("YOUTUBE_API_KEY") or config.get("competition", {}).get("api_key", "")
    if not key:
        raise MissingApiKey(
            "Falta la API key de YouTube. Añádela a .env:\n"
            "  YOUTUBE_API_KEY=AIza...\n"
            "Se crea gratis en https://console.cloud.google.com -> APIs y servicios "
            "-> habilita 'YouTube Data API v3' -> Credenciales -> Clave de API."
        )
    return key


def _api_get(endpoint, params, api_key, meter, max_retries=3):
    """GET a la API v3 cobrando cuota. Reintenta en errores transitorios."""
    meter.charge(endpoint)

    params = dict(params)
    params["key"] = api_key

    last_error = None
    for attempt in range(max_retries):
        try:
            resp = requests.get(f"{API_BASE}/{endpoint}", params=params, timeout=30)
        except requests.RequestException as e:
            last_error = e
            time.sleep(2 ** attempt)
            continue

        if resp.status_code == 200:
            return resp.json()

        if resp.status_code == 403 and "quota" in resp.text.lower():
            raise QuotaExhausted(
                "Google rechazó la petición por cuota agotada. "
                "Se reanuda mañana (la cuota se resetea a medianoche hora del Pacífico)."
            )

        # 5xx y 429 son transitorios; el resto es un error real de petición.
        if resp.status_code in (429, 500, 503):
            last_error = RuntimeError(f"{resp.status_code}: {resp.text[:200]}")
            time.sleep(2 ** attempt)
            continue

        raise RuntimeError(
            f"Error de la YouTube API ({endpoint}): {resp.status_code} — {resp.text[:300]}"
        )

    raise RuntimeError(f"La YouTube API no respondió tras {max_retries} intentos: {last_error}")


# ----------------------------------------------------------------------------
# Utilidades de parseo
# ----------------------------------------------------------------------------

_DURATION_RE = re.compile(
    r"P(?:(?P<days>\d+)D)?T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?"
)


def parse_duration(iso_duration):
    """ISO 8601 (PT1H2M3S) -> segundos. Devuelve 0 si no se puede parsear."""
    if not iso_duration:
        return 0
    m = _DURATION_RE.fullmatch(iso_duration)
    if not m:
        return 0
    parts = {k: int(v) for k, v in m.groupdict(default="0").items()}
    return parts["days"] * 86400 + parts["hours"] * 3600 + parts["minutes"] * 60 + parts["seconds"]


def parse_published(iso_datetime):
    """RFC3339 de la API -> datetime con tz. None si falla."""
    if not iso_datetime:
        return None
    try:
        return datetime.fromisoformat(iso_datetime.replace("Z", "+00:00"))
    except ValueError:
        return None


# Puntuación e ideogramas CJK: 【】〔〕｜＂（）《》「」, comillas de ancho completo,
# hanzi... Delatan las granjas de drama chino doblado al español, que compiten
# en otra liga (episodios recortados, no narración). Un canal español nunca los
# usa. Ejemplo real detectado: "Galán frío rechaza a todas...【Mi hijo del futuro】"
_CJK_MARKERS = re.compile(r"[　-〿＀-￯一-鿿㐀-䶿]")


def _has_cjk_markers(text):
    return bool(_CJK_MARKERS.search(text or ""))


# Primera persona: el nicho narra "mi suegra…", el drama doblado narra "ella…".
# Se guarda como COLUMNA INFORMATIVA, no como filtro: medido, da 0% en rBarra
# Historias (competidor real) y 75% en Gatito Giratorio (drama doblado).
_FIRST_PERSON = re.compile(
    r"\b(mi|mis|me|yo|mí|conmigo|nuestro|nuestra|nos)\b", re.IGNORECASE
)


def _looks_spanish(text):
    """¿El texto está en español? Heurística barata, sin dependencias.

    No basta con contar palabras españolas: hay que GANARLE al inglés. Se pide
    un mínimo de aciertos españoles Y que superen a los marcadores ingleses.
    Los caracteres exclusivos del español (ñ, tildes, ¿, ¡) valen como acierto
    fuerte porque el inglés no los usa nunca.
    """
    lowered = (text or "").lower()
    words = re.findall(r"[a-záéíóúüñ]+", lowered)
    if len(words) < 4:
        return False

    spanish = sum(1 for w in words if w in _SPANISH_STOPWORDS)
    english = sum(1 for w in words if w in _ENGLISH_MARKERS)

    # Señal fuerte: grafías imposibles en inglés.
    if re.search(r"[ñáéíóúü¿¡]", lowered):
        spanish += 2

    return spanish >= 2 and spanish > english


def _int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _median(values):
    values = sorted(v for v in values if v is not None)
    if not values:
        return 0.0
    mid = len(values) // 2
    if len(values) % 2:
        return float(values[mid])
    return (values[mid - 1] + values[mid]) / 2.0


def _chunks(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def channel_url(channel_id):
    return f"https://www.youtube.com/channel/{channel_id}"


def video_url(video_id):
    return f"https://www.youtube.com/watch?v={video_id}"


# ----------------------------------------------------------------------------
# Llamadas concretas a la API
# ----------------------------------------------------------------------------

def fetch_channels(channel_ids, api_key, meter):
    """channels.list en lotes de 50. Devuelve {channel_id: dict crudo}."""
    out = {}
    for batch in _chunks(list(channel_ids), 50):
        if not meter.can_afford("channels"):
            logger.warning("Cuota insuficiente: %d canales sin consultar", len(channel_ids) - len(out))
            break
        data = _api_get(
            "channels",
            {"part": "snippet,statistics,contentDetails", "id": ",".join(batch), "maxResults": 50},
            api_key, meter,
        )
        for item in data.get("items", []):
            out[item["id"]] = item
    return out


def resolve_handle(handle, api_key, meter):
    """@handle -> channelId usando channels.list?forHandle (1 unidad)."""
    handle = handle.lstrip("@")
    data = _api_get("channels", {"part": "id", "forHandle": handle}, api_key, meter)
    items = data.get("items", [])
    return items[0]["id"] if items else None


def resolve_seed(seed, api_key, meter):
    """Normaliza una semilla (ID, URL o @handle) a channelId.

    Acepta:
      UC...                              -> tal cual
      https://youtube.com/channel/UC...  -> extrae el ID
      https://youtube.com/@handle        -> resuelve el handle (1 unidad)
      @handle / handle                   -> resuelve el handle (1 unidad)
    """
    seed = (seed or "").strip()
    if not seed:
        return None

    if seed.startswith("UC") and len(seed) == 24:
        return seed

    m = re.search(r"/channel/(UC[\w-]{22})", seed)
    if m:
        return m.group(1)

    m = re.search(r"/@([\w.\-]+)", seed)
    if m:
        return resolve_handle(m.group(1), api_key, meter)

    if not seed.startswith("http"):
        return resolve_handle(seed, api_key, meter)

    logger.warning(f"Semilla no reconocida, se ignora: {seed}")
    return None


def search_channel_ids(keyword, api_key, meter, region, language, published_after, max_results=50):
    """search.list (100 unidades) -> IDs de canal que publican sobre `keyword`.

    Busca VIDEOS y no canales a propósito: nos interesa quién está publicando
    contenido del nicho ahora mismo, no quién tiene el canal mejor titulado.
    """
    params = {
        "part": "snippet",
        "q": keyword,
        "type": "video",
        "order": "viewCount",
        "maxResults": min(50, max_results),
        "publishedAfter": published_after,
    }
    if region:
        params["regionCode"] = region
    if language:
        params["relevanceLanguage"] = language

    data = _api_get("search", params, api_key, meter)

    found = {}
    for item in data.get("items", []):
        snippet = item.get("snippet", {})
        cid = snippet.get("channelId")
        if cid:
            found.setdefault(cid, snippet.get("channelTitle", ""))
    return found


def fetch_recent_video_ids(uploads_playlist, api_key, meter, limit):
    """playlistItems.list sobre la playlist de subidas (1 unidad por 50)."""
    ids = []
    page_token = None
    while len(ids) < limit:
        if not meter.can_afford("playlistItems"):
            break
        params = {
            "part": "contentDetails",
            "playlistId": uploads_playlist,
            "maxResults": min(50, limit - len(ids)),
        }
        if page_token:
            params["pageToken"] = page_token
        try:
            data = _api_get("playlistItems", params, api_key, meter)
        except RuntimeError as e:
            # Canal sin subidas públicas o playlist inaccesible: no es fatal.
            logger.warning(f"No se pudo leer la playlist {uploads_playlist}: {e}")
            break

        for item in data.get("items", []):
            vid = item.get("contentDetails", {}).get("videoId")
            if vid:
                ids.append(vid)

        page_token = data.get("nextPageToken")
        if not page_token:
            break
    return ids[:limit]


def fetch_videos(video_ids, api_key, meter):
    """videos.list en lotes de 50 -> lista de dicts crudos.

    `topicDetails` va incluido porque en la API v3 el coste es por MÉTODO, no
    por part: pedirlo sale gratis y es la única pista de metadatos que delata
    un canal de gameplay (ver `_has_gameplay_topic`).
    """
    out = []
    for batch in _chunks(list(video_ids), 50):
        if not meter.can_afford("videos"):
            logger.warning("Cuota insuficiente: %d videos sin consultar", len(video_ids) - len(out))
            break
        data = _api_get(
            "videos",
            {
                "part": "snippet,statistics,contentDetails,topicDetails",
                "id": ",".join(batch),
                "maxResults": 50,
            },
            api_key, meter,
        )
        out.extend(data.get("items", []))
    return out


# ----------------------------------------------------------------------------
# Normalización a nuestras estructuras
# ----------------------------------------------------------------------------

def build_channel_record(raw, source):
    """channels.list item -> registro de competidor."""
    snippet = raw.get("snippet", {})
    stats = raw.get("statistics", {})
    uploads = (
        raw.get("contentDetails", {})
        .get("relatedPlaylists", {})
        .get("uploads", "")
    )
    return {
        "channel_id": raw["id"],
        "title": snippet.get("title", ""),
        "description": snippet.get("description", "")[:500],
        "country": snippet.get("country", ""),
        "url": channel_url(raw["id"]),
        "uploads_playlist": uploads,
        "subscribers": _int(stats.get("subscriberCount")),
        "subscribers_hidden": bool(stats.get("hiddenSubscriberCount")),
        "total_views": _int(stats.get("viewCount")),
        "video_count": _int(stats.get("videoCount")),
        "source": source,
        "discovered_at": _now().isoformat(),
        "last_scanned": None,
        "status": "active",
        "reject_reason": "",
        "median_views": 0,
        "long_form_ratio": 0.0,
        "uploads_last_30d": 0,
        "gameplay_ratio": 0.0,
    }


# Palabras que delatan gameplay cuando aparecen en título/descripción/tags.
# MEDIDO: en 16 competidores reales, NINGUNO las usaba — el gameplay es fondo,
# no tema, así que nadie lo etiqueta. Se dejan porque cuestan cero y algún canal
# sí las pone, pero no sirven como filtro duro.
_GAMEPLAY_KEYWORDS = (
    "minecraft", "gameplay", "parkour", "subway surfer", "satisfying",
    "gta", "roblox", "fortnite", "gaming", "partida",
)


def _has_gameplay_topic(raw):
    """¿La API asocia este video con temática de videojuego?

    `topicDetails.topicCategories` son URLs de Wikipedia (Video_game_culture,
    Role-playing_video_game...). Es la ÚNICA señal de metadatos que distingue a
    un canal de historias-sobre-gameplay, y aun así es débil: en la medición
    real solo la emitía 1 de 16 canales, y solo en 2 de sus 8 videos. Por eso
    se usa como pista informativa (y filtro OPCIONAL), nunca como rechazo
    automático: como filtro duro tiraría competidores reales.
    """
    for topic in raw.get("topicDetails", {}).get("topicCategories", []):
        if "game" in topic.rsplit("/", 1)[-1].lower():
            return True

    snippet = raw.get("snippet", {})
    blob = " ".join(
        snippet.get("tags", [])
        + [snippet.get("title", ""), snippet.get("description", "")[:500]]
    ).lower()
    return any(kw in blob for kw in _GAMEPLAY_KEYWORDS)


def build_video_record(raw, channel_record):
    """videos.list item -> registro de video con métricas derivadas."""
    snippet = raw.get("snippet", {})
    stats = raw.get("statistics", {})

    views = _int(stats.get("viewCount"))
    likes = _int(stats.get("likeCount"))
    comments = _int(stats.get("commentCount"))

    published = parse_published(snippet.get("publishedAt"))
    age_hours = 0.0
    if published:
        age_hours = max(1.0, (_now() - published).total_seconds() / 3600.0)

    # engagement por visitas: lo que pidió el usuario como señal principal.
    engagement = (likes + comments) / views if views else 0.0

    return {
        "video_id": raw["id"],
        "url": video_url(raw["id"]),
        "title": snippet.get("title", ""),
        "channel_id": channel_record["channel_id"],
        "channel_title": channel_record["title"],
        "published_at": snippet.get("publishedAt", ""),
        "age_days": round(age_hours / 24.0, 1),
        "duration_sec": parse_duration(raw.get("contentDetails", {}).get("duration", "")),
        "views": views,
        "likes": likes,
        "comments": comments,
        # likeCount/commentCount desaparecen si el canal los oculta: lo marcamos
        # para no leer un engagement de 0 como "video malo".
        "metrics_partial": "likeCount" not in stats or "commentCount" not in stats,
        "engagement_rate": round(engagement, 5),
        "views_per_hour": round(views / age_hours, 2) if age_hours else 0.0,
        "age_hours": round(age_hours, 1),
        "gameplay_hint": _has_gameplay_topic(raw),
    }


# ----------------------------------------------------------------------------
# Scoring: percentiles dentro del corpus escaneado (sin constantes mágicas)
# ----------------------------------------------------------------------------

def _percentile_ranks(values):
    """Rango percentil 0..1 de cada valor, promediando empates.

    Se usan percentiles y no normalización absoluta para que el score se
    auto-calibre al nicho: lo que es "engagement alto" depende de con quién
    compites, no de un umbral inventado.
    """
    n = len(values)
    if n == 0:
        return []
    if n == 1:
        return [1.0]

    indexed = sorted(range(n), key=lambda i: values[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and values[indexed[j + 1]] == values[indexed[i]]:
            j += 1
        avg_rank = (i + j) / 2.0
        for k in range(i, j + 1):
            ranks[indexed[k]] = avg_rank / (n - 1)
        i = j + 1
    return ranks


def _saturating(value, cap):
    """0..1 conservando la MAGNITUD, saturando en `cap`. Curva logarítmica."""
    if value <= 0 or cap <= 0:
        return 0.0
    return min(1.0, math.log1p(value) / math.log1p(cap))


def score_videos(videos, weights, outlier_cap=5.0):
    """Añade a cada video sus componentes y el `viral_score` final (0-100).

    OJO: el outlier NO se puntúa por percentil como los otros tres, sino con una
    curva logarítmica saturada. Motivo, medido con datos de prueba: por
    percentil, un video a x11.7 de la media de su canal (2.4M vistas) quedaba
    POR DEBAJO de otro a x1.9, porque el percentil solo ordena y ambos caían en
    los dos primeros puestos (1.00 vs 0.95); la distancia real se perdía. El
    outlier ya viene normalizado contra el propio canal, así que su magnitud es
    comparable entre canales y hay que conservarla. Engagement, velocidad y
    frescura sí van por percentil: eso es lo que los auto-calibra al nicho.

    Componentes:
      outlier    -> vistas / mediana del canal. Es LA señal de viralidad: aísla
                    el video que rompe respecto a lo normal en ESE canal, sin
                    que los canales grandes barran a los pequeños.
      engagement -> (likes + comentarios) / vistas.
      velocity   -> vistas por hora desde su publicación.
      freshness  -> cuanto más reciente, mejor.
    """
    if not videos:
        return videos

    outlier = [v.get("outlier_ratio", 0.0) for v in videos]
    engagement = [v["engagement_rate"] for v in videos]
    velocity = [v["views_per_hour"] for v in videos]
    freshness = [-v["age_hours"] for v in videos]  # negado: menos edad = mejor

    p_out = [_saturating(o, outlier_cap) for o in outlier]
    p_eng = _percentile_ranks(engagement)
    p_vel = _percentile_ranks(velocity)
    p_fre = _percentile_ranks(freshness)

    w_out = float(weights.get("outlier", 0.40))
    w_eng = float(weights.get("engagement", 0.30))
    w_vel = float(weights.get("velocity", 0.20))
    w_fre = float(weights.get("freshness", 0.10))
    total_w = w_out + w_eng + w_vel + w_fre or 1.0

    for i, v in enumerate(videos):
        v["pct_outlier"] = round(p_out[i], 3)
        v["pct_engagement"] = round(p_eng[i], 3)
        v["pct_velocity"] = round(p_vel[i], 3)
        v["pct_freshness"] = round(p_fre[i], 3)
        v["viral_score"] = round(
            100.0 * (
                w_out * p_out[i] + w_eng * p_eng[i] + w_vel * p_vel[i] + w_fre * p_fre[i]
            ) / total_w,
            1,
        )
    return videos


# ----------------------------------------------------------------------------
# Cualificación de canales
# ----------------------------------------------------------------------------

def matches_list(record, names):
    """¿Está este canal en una lista de config (exclude_channels/always_include)?

    Acepta tanto el channelId (UC...) como el título exacto del canal, sin
    distinguir mayúsculas: pedirle al usuario que averigüe IDs para nombrar un
    canal que ve por su nombre en el informe sería absurdo.
    """
    if not names:
        return False
    return (
        record["channel_id"] in names
        or record["title"].strip().casefold() in {n.casefold() for n in names}
    )


# Alias histórico, más legible en los sitios donde se filtra por exclusión.
is_excluded = matches_list


def qualify_channel(record, rules):
    """¿Este canal es competencia nuestra? Devuelve (bool, motivo)."""
    min_subs = int(rules.get("min_subscribers", 5000))
    if not record["subscribers_hidden"] and record["subscribers"] < min_subs:
        return False, f"pocos suscriptores ({record['subscribers']:,} < {min_subs:,})"

    if not record["uploads_playlist"]:
        return False, "sin playlist de subidas pública"

    if rules.get("require_spanish", True):
        country = record.get("country", "")
        text = f"{record['title']} {record['description']}"
        allowed_countries = rules.get("countries", ["ES", "MX", "AR", "CO", "CL", "PE", "US", ""])
        if country and country not in allowed_countries:
            return False, f"país fuera del objetivo ({country})"

        # Sin texto suficiente NO se rechaza: se aplaza al filtro de contenido,
        # que juzga por los títulos de sus videos. MEDIDO: rechazaba de golpe a
        # rBarra Historias (124k subs) y Venganza En Solitario (58.9k), ambos
        # españoles, solo porque tenían la descripción del canal vacía y el
        # nombre no llega a las 4 palabras que pide el heurístico. Aplazar
        # cuesta 2 unidades de cuota por canal; equivocarse cuesta un competidor.
        if len(re.findall(r"[a-záéíóúüñ]+", text.lower())) < 6:
            return True, ""

        if not _looks_spanish(text) and country not in ("ES", "MX", "AR", "CO", "CL", "PE"):
            return False, "no parece contenido en español"

    return True, ""


def qualify_by_content(record, videos, rules):
    """Segundo filtro, ya con sus videos: ¿publica el formato que competimos?"""
    if not videos:
        return False, "sin videos recientes"

    max_age = int(rules.get("max_age_days", 60))
    recent = [v for v in videos if v["age_days"] <= max_age]
    if not recent:
        return False, f"sin subidas en {max_age} días"

    min_minutes = float(rules.get("min_video_minutes", 5))
    long_form = [v for v in videos if v["duration_sec"] >= min_minutes * 60]
    ratio = len(long_form) / len(videos)
    min_ratio = float(rules.get("min_long_form_ratio", 0.3))
    if ratio < min_ratio:
        return False, f"formato distinto (solo {ratio:.0%} de videos >{min_minutes:.0f} min)"

    if rules.get("require_spanish", True):
        spanish_titles = sum(1 for v in videos if _looks_spanish(v["title"]))
        if spanish_titles / len(videos) < 0.4:
            return False, "títulos mayoritariamente en otro idioma"

        cjk = sum(1 for v in videos if _has_cjk_markers(v["title"]))
        max_cjk = float(rules.get("max_cjk_title_ratio", 0.25))
        if cjk / len(videos) > max_cjk:
            return False, f"drama doblado (puntuación CJK en {cjk / len(videos):.0%} de títulos)"

    # Filtro de formato gameplay: OPCIONAL y desactivado por defecto a
    # propósito. Medido sobre 16 competidores reales, solo 1 emitía la señal,
    # así que activarlo descarta competencia legítima. Existe por si algún día
    # la señal mejora o se quiere una pasada muy estricta.
    if rules.get("require_gameplay", False):
        ratio = sum(1 for v in videos if v.get("gameplay_hint")) / len(videos)
        min_ratio = float(rules.get("min_gameplay_ratio", 0.2))
        if ratio < min_ratio:
            return False, f"sin señal de gameplay ({ratio:.0%} < {min_ratio:.0%})"

    return True, ""


# ----------------------------------------------------------------------------
# Escaneo completo
# ----------------------------------------------------------------------------

# Motivos de rechazo que NO cambian con el tiempo ni con los filtros: no
# merece la pena volver a gastar cuota en ellos. "fuera de nicho" entra aquí
# porque el veredicto del LLM ya está guardado (`llm_in_niche`) y no se vuelve a
# preguntar: sin esto, un cambio de filtros resucitaba las granjas de drama
# doblado y ya nadie las volvía a clasificar.
PERMANENT_REJECTS = (
    "país fuera del objetivo",
    "excluido en config.yaml",
    "fuera de nicho",
)


def revive_rejected(competitors, rules, state):
    """Devuelve a revisión los rechazos que pudieron quedar obsoletos.

    Dispara en dos casos:
      - Cambian los filtros de `discovery` (bajas min_subscribers, tocas el
        idioma...): los rechazos anteriores se emitieron con OTRAS reglas.
      - Han pasado `recheck_rejected_after_days` días: un canal pequeño crece.

    Los revividos se re-cualifican AQUÍ MISMO con los datos ya guardados, sin
    gastar una sola unidad de cuota; solo los que ahora pasan el filtro llegan
    a la fase de medición.
    """
    fingerprint = json.dumps(rules, sort_keys=True, default=str)
    rules_changed = state.get("rules_fingerprint") != fingerprint
    state["rules_fingerprint"] = fingerprint

    recheck_days = int(rules.get("recheck_rejected_after_days", 30))
    threshold = _now() - timedelta(days=recheck_days) if recheck_days > 0 else None

    revived = []
    for record in competitors.values():
        if record.get("status") != "rejected":
            continue
        if any(p in record.get("reject_reason", "") for p in PERMANENT_REJECTS):
            continue
        # Cinturón y tirantes: aunque el motivo se haya reescrito, un veredicto
        # negativo del clasificador manda.
        if record.get("llm_in_niche") is False:
            continue

        stale = False
        if threshold:
            stamp = parse_published(record.get("rejected_at") or record.get("discovered_at"))
            stale = stamp is not None and stamp < threshold

        if not (rules_changed or stale):
            continue

        ok, reason = qualify_channel(record, rules)
        if ok:
            record["status"] = "active"
            record["reject_reason"] = ""
            revived.append(record["title"])
        else:
            # Sigue sin pasar: se re-sella la fecha para no reconsiderarlo
            # otra vez hasta dentro de otros `recheck_rejected_after_days`.
            record["reject_reason"] = reason
            record["rejected_at"] = _now().isoformat()

    return revived, rules_changed


def _competition_config(config):
    """Config de competencia con valores por defecto sensatos."""
    comp = dict(config.get("competition", {}) or {})
    comp.setdefault("enabled", True)
    comp.setdefault("region", "ES")
    comp.setdefault("language", "es")
    comp.setdefault("seed_channels", [])
    comp.setdefault("exclude_channels", [])
    comp.setdefault("keywords", [])
    comp["discovery"] = {
        "max_searches_per_scan": 4,
        "max_competitors": 40,
        "videos_per_channel": 15,
        "min_subscribers": 5000,
        "max_age_days": 60,
        "min_video_minutes": 5,
        "min_long_form_ratio": 0.3,
        "require_spanish": True,
        "require_gameplay": False,
        "min_gameplay_ratio": 0.2,
        "recheck_rejected_after_days": 30,
        **(comp.get("discovery") or {}),
    }
    comp["scoring"] = {
        "weights": {"outlier": 0.40, "engagement": 0.30, "velocity": 0.20, "freshness": 0.10},
        "top_n": 12,
        "outlier_cap": 5.0,
        "min_views": 3000,
        "min_duration_min": 8,
        **(comp.get("scoring") or {}),
    }
    comp["quota"] = {"daily_limit": 10000, **(comp.get("quota") or {})}
    return comp


def scan(config, discover=True, progress=None):
    """Escaneo completo: descubre competidores, mide sus últimos videos, puntúa.

    `discover=False` salta las búsquedas (0 unidades de search.list) y solo
    re-mide los competidores ya conocidos — útil para refrescar barato.
    `progress` es un callable opcional (texto) para pintar avance en la UI.

    Devuelve el `report` (dict) y lo persiste junto al state actualizado.
    """
    def notify(msg):
        logger.info(msg)
        if progress:
            progress(msg)

    comp = _competition_config(config)
    rules = comp["discovery"]
    api_key = get_api_key(config)

    state = load_state(config)
    meter = QuotaMeter(state, int(comp["quota"]["daily_limit"]))
    competitors = state["competitors"]

    warnings = []
    published_after = (
        _now() - timedelta(days=int(rules["max_age_days"]))
    ).strftime("%Y-%m-%dT%H:%M:%SZ")

    excluded = {str(c).strip() for c in comp.get("exclude_channels", []) if str(c).strip()}
    always_include = {str(c).strip() for c in comp.get("always_include", []) if str(c).strip()}

    # Inicializados fuera del try: si la cuota se agota a mitad, el informe se
    # construye igualmente con lo que se llegó a recoger.
    keywords_used = []
    all_videos = []

    try:
        # --- 1. Semillas -----------------------------------------------------
        pending_new = {}  # channel_id -> source
        for seed in comp.get("seed_channels", []):
            try:
                cid = resolve_seed(seed, api_key, meter)
            except QuotaExhausted:
                raise
            except RuntimeError as e:
                warnings.append(f"Semilla '{seed}' no resuelta: {e}")
                continue
            if cid and cid not in competitors and cid not in excluded:
                pending_new[cid] = f"seed:{seed}"

        # --- 2. Expansión por keywords --------------------------------------
        if discover and len(_active(competitors)) < int(rules["max_competitors"]):
            keywords = list(comp.get("keywords") or [])
            max_searches = int(rules["max_searches_per_scan"])

            # Rotamos las keywords entre escaneos para no gastar siempre las
            # mismas 4 y quedarnos ciegos al resto de la lista.
            # Si editas la lista de keywords, el offset guardado apunta a otra
            # cosa: reordenar la lista dejaba fuera de la rotación justo las
            # keywords nuevas durante varios escaneos. Al cambiar la huella, se
            # reinicia y las nuevas entran en la siguiente corrida.
            fingerprint = str(len(keywords)) + "|" + "|".join(keywords)
            if state.get("keywords_fingerprint") != fingerprint:
                if state.get("keywords_fingerprint"):
                    logger.info("La lista de keywords cambió: se reinicia la rotación")
                state["keyword_offset"] = 0
                state["keywords_fingerprint"] = fingerprint

            offset = int(state.get("keyword_offset", 0))
            if keywords:
                rotated = keywords[offset % len(keywords):] + keywords[:offset % len(keywords)]
            else:
                rotated = []

            for kw in rotated[:max_searches]:
                if not meter.can_afford("search"):
                    warnings.append(
                        f"Cuota insuficiente para más búsquedas; keywords sin explorar: "
                        f"{', '.join(rotated[len(keywords_used):max_searches])}"
                    )
                    break
                notify(f"Buscando canales con «{kw}»…")
                try:
                    found = search_channel_ids(
                        kw, api_key, meter, comp["region"], comp["language"], published_after
                    )
                except QuotaExhausted:
                    raise
                except RuntimeError as e:
                    warnings.append(f"Búsqueda '{kw}' falló: {e}")
                    continue
                keywords_used.append(kw)
                for cid in found:
                    if cid not in competitors and cid not in excluded:
                        pending_new.setdefault(cid, f"keyword:{kw}")

            # El offset avanza SOLO por las búsquedas que de verdad se hicieron.
            # Avanzarlo por `max_searches` dejaba las keywords saltadas por falta
            # de cuota fuera de la rotación para siempre: nunca se exploraban.
            if keywords:
                state["keyword_offset"] = (offset + len(keywords_used)) % len(keywords)

        # --- 2b. Reconsiderar rechazos obsoletos (gratis, sin cuota) ---------
        revived, rules_changed = revive_rejected(competitors, rules, state)
        if rules_changed:
            logger.info("Los filtros de discovery cambiaron: se reconsideran los rechazos")
        if revived:
            msg = f"{len(revived)} canales vuelven a evaluarse: {', '.join(revived[:5])}"
            if len(revived) > 5:
                msg += f" (+{len(revived) - 5} más)"
            notify(msg)

        # --- 3. Cualificar canales nuevos -----------------------------------
        if pending_new:
            notify(f"Evaluando {len(pending_new)} canales nuevos…")
            raw_channels = fetch_channels(pending_new.keys(), api_key, meter)
            for cid, raw in raw_channels.items():
                record = build_channel_record(raw, pending_new[cid])
                if is_excluded(record, excluded):
                    ok, reason = False, "excluido en config.yaml"
                else:
                    ok, reason = qualify_channel(record, rules)
                if not ok:
                    record["status"] = "rejected"
                    record["reject_reason"] = reason
                    record["rejected_at"] = _now().isoformat()
                    logger.info(f"Descartado {record['title']}: {reason}")
                competitors[cid] = record

        # --- 4. Refrescar métricas de los canales activos --------------------
        # La exclusión se re-aplica a los ya guardados: si añades un canal a
        # exclude_channels después de haberlo descubierto, cae en el siguiente
        # escaneo sin tener que borrar data/competitors.json.
        for record in _active(competitors):
            if is_excluded(record, excluded):
                record["status"] = "rejected"
                record["reject_reason"] = "excluido en config.yaml"
                record["rejected_at"] = _now().isoformat()
                logger.info(f"Excluido {record['title']} (config)")

        # Invariante: un veredicto negativo del clasificador implica rechazado.
        # Se re-impone en cada corrida, no solo al clasificar. MEDIDO: al cambiar
        # los filtros, `revive_rejected` devolvía a activo un canal ya juzgado
        # fuera de nicho (qualify_channel no mira el veredicto del LLM), y como
        # ya tenía `llm_in_niche` nadie volvía a clasificarlo: Latidos-Teatro,
        # un minidrama chino, se quedó fijo en el puesto 8 del ranking.
        for record in _active(competitors):
            if record.get("llm_in_niche") is False and not matches_list(record, always_include):
                record["status"] = "rejected"
                record["reject_reason"] = (
                    f"fuera de nicho: {record.get('llm_reason', 'juicio del clasificador')}"
                )
                record["rejected_at"] = _now().isoformat()
                logger.info(f"Re-descartado {record['title']} (veredicto de nicho previo)")

        # Veto del usuario sobre el clasificador: `always_include` manda sobre
        # cualquier rechazo automático. El clasificador emite un JUICIO (p. ej.
        # descartó rBarra Historias, 124k subs y gameplay 100%, por considerarlo
        # compilaciones de AskReddit); quien decide si eso compite contigo eres tú.
        for record in competitors.values():
            if matches_list(record, always_include) and record["status"] != "active":
                record["status"] = "active"
                record["reject_reason"] = ""
                record["llm_in_niche"] = True
                record["llm_reason"] = "incluido a mano (always_include)"
                logger.info(f"Re-incluido {record['title']} por always_include")

        active = _active(competitors)
        # Los más antiguos sin escanear primero: si la cuota se corta, la
        # siguiente corrida cubre a los que se quedaron fuera.
        active.sort(key=lambda r: r.get("last_scanned") or "")
        limit = int(rules["max_competitors"])
        to_scan = active[:limit]
        if len(active) > limit:
            warnings.append(
                f"{len(active) - limit} competidores activos no escaneados en esta corrida "
                f"(límite max_competitors={limit}); entrarán en la siguiente."
            )

        # Medir un canal cuesta 2 llamadas (playlistItems + videos). Se exige la
        # cuota de AMBAS antes de empezar: entrar con 1 unidad suelta dejaba el
        # canal medio medido y lo hacía caer en el rechazo de más abajo.
        cost_per_channel = QUOTA_COST["playlistItems"] + QUOTA_COST["videos"]

        for i, record in enumerate(to_scan, 1):
            if meter.remaining() < cost_per_channel:
                warnings.append(
                    f"Cuota agotada tras {i - 1}/{len(to_scan)} canales; el resto se medirá mañana."
                )
                break

            notify(f"Midiendo {i}/{len(to_scan)}: {record['title']}")
            vids = fetch_recent_video_ids(
                record["uploads_playlist"], api_key, meter, int(rules["videos_per_channel"])
            )
            if not vids:
                record["last_scanned"] = _now().isoformat()
                continue

            raw_videos = fetch_videos(vids, api_key, meter)

            # Teníamos IDs pero no llegaron datos: es un fallo de cuota o de red,
            # NO un canal vacío. Se deja intacto (activo, sin last_scanned) para
            # que la próxima corrida lo re-evalúe. Sin esto, un corte de cuota
            # marcaba el canal como "sin videos recientes" de forma permanente y
            # la lista de competidores se vaciaba sola.
            if not raw_videos:
                warnings.append(
                    f"{record['title']}: no se pudieron leer sus videos (cuota o red); "
                    f"se re-evaluará en la próxima corrida."
                )
                continue

            channel_videos = [build_video_record(rv, record) for rv in raw_videos]

            ok, reason = qualify_by_content(record, channel_videos, rules)
            record["last_scanned"] = _now().isoformat()
            if not ok:
                record["status"] = "rejected"
                record["reject_reason"] = reason
                record["rejected_at"] = _now().isoformat()
                logger.info(f"Descartado {record['title']}: {reason}")
                continue

            # Mediana del canal: base para el factor outlier.
            median = _median([v["views"] for v in channel_videos])
            record["median_views"] = int(median)
            record["long_form_ratio"] = round(
                sum(1 for v in channel_videos if v["duration_sec"] >= rules["min_video_minutes"] * 60)
                / len(channel_videos), 2
            )
            record["uploads_last_30d"] = sum(1 for v in channel_videos if v["age_days"] <= 30)
            record["last_video_days"] = min(v["age_days"] for v in channel_videos)
            record["gameplay_ratio"] = round(
                sum(1 for v in channel_videos if v["gameplay_hint"]) / len(channel_videos), 2
            )
            record["first_person_ratio"] = round(
                sum(1 for v in channel_videos if _FIRST_PERSON.search(v["title"]))
                / len(channel_videos), 2
            )
            # Muestra para que el clasificador de nicho pueda juzgar sin gastar
            # otra llamada a la API.
            record["sample_titles"] = [v["title"] for v in channel_videos[:4]]

            for v in channel_videos:
                v["outlier_ratio"] = round(v["views"] / median, 2) if median else 0.0
            all_videos.extend(channel_videos)

    except QuotaExhausted as e:
        warnings.append(str(e))
        logger.warning(str(e))

    # --- 4b. Clasificación de nicho con el LLM (solo canales sin veredicto) ---
    if comp.get("classify_with_llm", True):
        sin_clasificar = [
            r for r in _active(competitors)
            if r.get("sample_titles")
            and "llm_in_niche" not in r
            and not matches_list(r, always_include)
        ]
        if sin_clasificar:
            # Import diferido: trend_advisor importa script_generator, y no se
            # quiere esa cadena cargada cuando solo se escanea sin clasificar.
            from modules.trend_advisor import classify_channels

            verdicts = classify_channels(sin_clasificar, config, progress=progress)
            fuera = 0
            for record in sin_clasificar:
                verdict = verdicts.get(record["channel_id"])
                if not verdict:
                    continue
                in_niche, motivo = verdict
                record["llm_in_niche"] = in_niche
                record["llm_reason"] = motivo
                if not in_niche:
                    record["status"] = "rejected"
                    record["reject_reason"] = f"fuera de nicho: {motivo}"
                    record["rejected_at"] = _now().isoformat()
                    fuera += 1
                    logger.info(f"Fuera de nicho {record['title']}: {motivo}")
            if fuera:
                notify(f"{fuera} canales descartados por nicho")
                # Sus videos salen del ranking: se midieron antes del veredicto.
                descartados_ids = {
                    r["channel_id"] for r in sin_clasificar if r.get("status") == "rejected"
                }
                all_videos = [v for v in all_videos if v["channel_id"] not in descartados_ids]

    # --- 5. Puntuar y ordenar ------------------------------------------------
    max_age = int(rules["max_age_days"])
    min_views = int(comp["scoring"].get("min_views", 3000))
    min_duration = float(comp["scoring"].get("min_duration_min", 8)) * 60

    # Suelo absoluto de vistas. MEDIDO en producción: un canal con mediana de 47
    # vistas colaba un video de 286 vistas en el puesto 4 del ranking, porque
    # x6.0 sobre una mediana ridícula es ruido estadístico, no viralidad. El
    # outlier solo significa algo por encima de un volumen mínimo.
    # El filtro de formato largo es por CANAL; sin este suelo por VÍDEO, un
    # corto de 2 minutos de un canal mayoritariamente largo se colaba en un
    # ranking pensado para producir vídeos de 20-40 min. Es otro producto.
    fresh = [
        v for v in all_videos
        if v["age_days"] <= max_age
        and v["views"] >= min_views
        and v["duration_sec"] >= min_duration
    ]
    descartados = len(all_videos) - len(fresh)
    if descartados:
        logger.info(
            f"{descartados} videos fuera del ranking (antigüedad, menos de {min_views:,} "
            f"vistas o menos de {min_duration / 60:.0f} min)"
        )
    score_videos(
        fresh,
        comp["scoring"]["weights"],
        outlier_cap=float(comp["scoring"].get("outlier_cap", 5.0)),
    )
    fresh.sort(key=lambda v: v["viral_score"], reverse=True)

    top_n = int(comp["scoring"]["top_n"])
    active_records = _active(competitors)
    active_records.sort(key=lambda r: r.get("median_views", 0), reverse=True)

    report = {
        "generated_at": _now().isoformat(),
        "quota_used_this_run": meter.spent_this_run,
        "quota_used_today": meter.spent,
        "quota_daily_limit": meter.daily_limit,
        "keywords_used": keywords_used if discover else [],
        "competitors_total": len(competitors),
        "competitors_active": len(active_records),
        "competitors": active_records,
        "videos_analyzed": len(fresh),
        "viral": fresh[:top_n],
        "warnings": warnings,
    }

    save_state(state, config)
    save_report(report, config)

    notify(
        f"Escaneo completo: {len(active_records)} competidores activos, "
        f"{len(fresh)} videos analizados, {meter.spent_this_run} unidades de cuota"
    )
    for w in warnings:
        logger.warning(f"Aviso: {w}")

    return report


def _active(competitors):
    return [r for r in competitors.values() if r.get("status") == "active"]
