"""Subida a YouTube — el último paso para que el pipeline sea autónomo.

DECISIONES TOMADAS POR DIEGO (11-ago-2026), que son las que dan forma a esto:
  1. Se sube en **privado**. Nadie lo publica salvo él, desde YouTube Studio.
  2. Se sube **solo el vídeo largo**. Los ~50 shorts NO: 51 subidas x 1.600 =
     81.600 unidades frente a las 10.000 diarias.
  3. Se dispara desde una **cola con su OK** en el dashboard, no automáticamente
     al terminar la corrida. El modo de fallo de este proyecto es un vídeo que
     PARECE terminado, así que su ojo sigue en el bucle.

La cuota se carga al MISMO contador que el análisis de competencia
(`QuotaMeter` sobre `data/competitors.json`): son el mismo cupo de 10.000/día.

Autenticación: OAuth de aplicación de escritorio. Hace falta un
`client_secret.json` descargado de Google Cloud Console (ver `credentials_help`).
El consentimiento se da UNA vez en el navegador; después se guarda un token
renovable en `data/youtube_token.json`.
"""
import json
import logging
import os
import time

import requests

from modules.competitor_scout import (
    QUOTA_COST, QuotaMeter, QuotaExhausted, load_state, save_state, _data_dir,
)

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
CHUNK = 8 * 1024 * 1024  # 8 MB por trozo; un video de 30 min son ~3,4 GB

CATEGORIA_ENTRETENIMIENTO = "24"


class FaltaCredencial(Exception):
    pass


class SubidaFallida(Exception):
    pass


def credentials_help(config):
    return (
        "Falta el fichero de credenciales OAuth. Para crearlo:\n"
        "  1. https://console.cloud.google.com/ -> crea un proyecto\n"
        "  2. APIs y servicios -> Habilitar -> 'YouTube Data API v3'\n"
        "  3. Pantalla de consentimiento OAuth -> Externa -> añádete como usuario de prueba\n"
        "  4. Credenciales -> Crear -> ID de cliente de OAuth -> **Aplicación de escritorio**\n"
        f"  5. Descarga el JSON y guárdalo en: {client_secret_path(config)}\n"
        "El token se genera solo la primera vez que subas, desde el dashboard."
    )


def client_secret_path(config):
    return os.path.join(_data_dir(config), "client_secret.json")


def token_path(config):
    return os.path.join(_data_dir(config), "youtube_token.json")


# ---------------------------------------------------------------- OAuth
def _credenciales(config, permitir_navegador=True):
    """Devuelve credenciales válidas, refrescándolas si hace falta."""
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request

    tp = token_path(config)
    creds = None
    if os.path.exists(tp):
        creds = Credentials.from_authorized_user_file(tp, SCOPES)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        logger.info("Token de YouTube caducado: renovando")
        creds.refresh(Request())
        _guardar_token(creds, tp)
        return creds

    if not permitir_navegador:
        raise FaltaCredencial(
            "No hay token de YouTube válido y no se puede abrir el navegador aquí.")

    cs = client_secret_path(config)
    if not os.path.exists(cs):
        raise FaltaCredencial(credentials_help(config))

    from google_auth_oauthlib.flow import InstalledAppFlow
    flow = InstalledAppFlow.from_client_secrets_file(cs, SCOPES)
    # Abre el navegador y escucha en localhost. Es la única parte que exige
    # una persona delante, y solo la primera vez.
    creds = flow.run_local_server(port=0, prompt="consent")
    _guardar_token(creds, tp)
    return creds


def _guardar_token(creds, path):
    with open(path, "w", encoding="utf-8") as f:
        f.write(creds.to_json())
    logger.info(f"Token de YouTube guardado en {path}")


def hay_token(config):
    return os.path.exists(token_path(config))


# ---------------------------------------------------------------- estado local
def marca_path(video_path):
    """Fichero que marca un vídeo como YA SUBIDO.

    Vive junto al vídeo para que la marca sobreviva a cualquier limpieza de
    `data/`, y para que la cola del dashboard no dependa de un índice central
    que se pueda desincronizar del disco.
    """
    return os.path.splitext(video_path)[0] + "_uploaded.json"


def ya_subido(video_path):
    return os.path.exists(marca_path(video_path))


def lee_marca(video_path):
    try:
        with open(marca_path(video_path), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def pendientes(config):
    """Vídeos de output/ que aún no se han subido, con su título y miniatura."""
    out_dir = config["paths"]["output_dir"]
    if not os.path.isdir(out_dir):
        return []
    items = []
    for nombre in sorted(os.listdir(out_dir)):
        if not nombre.endswith("_final.mp4"):
            continue
        ruta = os.path.join(out_dir, nombre)
        stem = nombre[: -len("_final.mp4")]
        titulo_txt = os.path.join(out_dir, f"{stem}_title.txt")
        thumb = os.path.join(out_dir, f"{stem}_thumbnail.jpg")
        titulo = ""
        if os.path.exists(titulo_txt):
            with open(titulo_txt, encoding="utf-8") as f:
                titulo = f.read().strip()
        items.append({
            "video": ruta,
            "stem": stem,
            "titulo": titulo,
            "thumbnail": thumb if os.path.exists(thumb) else None,
            "tam_mb": round(os.path.getsize(ruta) / 1024 / 1024, 1),
            "subido": ya_subido(ruta),
            "marca": lee_marca(ruta),
        })
    return items


# ---------------------------------------------------------------- cuota
def puede_subir(config):
    """(bool, mensaje). Comprueba la cuota ANTES de empezar a subir 3 GB.

    Cortar a mitad de una subida de 3,4 GB por un 403 de cuota es tirar 10
    minutos de red, así que se pregunta antes.
    """
    state = load_state(config)
    limite = ((config.get("competition") or {}).get("quota") or {}).get(
        "daily_limit", 10000)
    meter = QuotaMeter(state, limite)
    coste = QUOTA_COST["videosInsert"]
    if coste > meter.remaining():
        return False, (
            f"Cuota de YouTube insuficiente: quedan {meter.remaining()} unidades "
            f"de {limite} y una subida cuesta {coste}. Se restablece a medianoche UTC."
        )
    return True, f"Quedan {meter.remaining()} unidades; la subida gastará {coste}."


def _cobra_cuota(config):
    state = load_state(config)
    limite = ((config.get("competition") or {}).get("quota") or {}).get(
        "daily_limit", 10000)
    meter = QuotaMeter(state, limite)
    meter.charge("videosInsert")       # lanza QuotaExhausted si no cabe
    save_state(state, config)
    return meter.spent, limite


# ---------------------------------------------------------------- subida
def _descripcion_por_defecto(titulo, config):
    plantilla = config.get("youtube", {}).get("description_template")
    if plantilla:
        return plantilla.format(titulo=titulo)
    return (
        f"{titulo}\n\n"
        "Historias narradas sobre gameplay de Minecraft.\n"
        "#historias #reddit #minecraft"
    )


def subir_video(video_path, config, titulo=None, descripcion=None, tags=None,
                privacidad=None, progreso=None):
    """Sube UN vídeo a YouTube en privado. Devuelve el dict de la marca.

    `progreso`: callback opcional (subidos_bytes, total_bytes) para el dashboard.
    """
    if not os.path.exists(video_path):
        raise SubidaFallida(f"No existe el vídeo: {video_path}")
    if ya_subido(video_path):
        raise SubidaFallida(
            f"Ese vídeo ya se subió el {lee_marca(video_path).get('fecha')} "
            f"(id {lee_marca(video_path).get('video_id')}). Borra "
            f"{os.path.basename(marca_path(video_path))} si quieres repetirlo.")

    ok, motivo = puede_subir(config)
    if not ok:
        raise QuotaExhausted(motivo)

    ycfg = config.get("youtube", {})
    if titulo is None:
        stem = os.path.basename(video_path)[: -len("_final.mp4")]
        tpath = os.path.join(os.path.dirname(video_path), f"{stem}_title.txt")
        titulo = open(tpath, encoding="utf-8").read().strip() if os.path.exists(tpath) else stem
    # YouTube corta a 100 caracteres; los títulos de este pipeline son de 20-35
    # palabras y se pasan SIEMPRE, así que se recorta por palabra y el título
    # completo va al principio de la descripción para no perderlo.
    titulo_completo = titulo
    if len(titulo) > 100:
        recorte = []
        for p in titulo.split():
            if len(" ".join(recorte + [p])) > 97:
                break
            recorte.append(p)
        titulo = " ".join(recorte) + "..."
        logger.warning(f"Título recortado a 100 caracteres para YouTube: {titulo}")

    if descripcion is None:
        descripcion = _descripcion_por_defecto(titulo_completo, config)
    if tags is None:
        tags = ycfg.get("tags", ["historias", "reddit", "minecraft", "relatos"])
    if privacidad is None:
        privacidad = ycfg.get("privacy_status", "private")

    creds = _credenciales(config)
    metadatos = {
        "snippet": {
            "title": titulo,
            "description": descripcion,
            "tags": tags,
            "categoryId": ycfg.get("category_id", CATEGORIA_ENTRETENIMIENTO),
            "defaultLanguage": "es",
            "defaultAudioLanguage": "es",
        },
        "status": {
            "privacyStatus": privacidad,
            "selfDeclaredMadeForKids": False,
        },
    }

    total = os.path.getsize(video_path)
    sesion = requests.Session()
    cabeceras = {
        "Authorization": f"Bearer {creds.token}",
        "X-Upload-Content-Length": str(total),
        "X-Upload-Content-Type": "video/mp4",
    }
    r = sesion.post(
        UPLOAD_URL,
        params={"uploadType": "resumable", "part": "snippet,status"},
        headers=cabeceras, json=metadatos, timeout=60,
    )
    if r.status_code != 200 or "location" not in {k.lower(): v for k, v in r.headers.items()}:
        raise SubidaFallida(
            f"YouTube rechazó el inicio de subida ({r.status_code}): {r.text[-500:]}")
    destino = {k.lower(): v for k, v in r.headers.items()}["location"]

    # La cuota se cobra en cuanto YouTube acepta la sesión: el gasto es real
    # aunque los bytes fallen a mitad, así que se apunta ya y no al final.
    gastado, limite = _cobra_cuota(config)
    logger.info(f"Subida iniciada; cuota de YouTube {gastado}/{limite} unidades hoy")

    subidos = 0
    with open(video_path, "rb") as f:
        while subidos < total:
            trozo = f.read(CHUNK)
            if not trozo:
                break
            fin = subidos + len(trozo) - 1
            resp = _sube_trozo(sesion, destino, trozo, subidos, fin, total)
            if resp.status_code in (200, 201):
                datos = resp.json()
                marca = {
                    "video_id": datos.get("id"),
                    "url": f"https://youtu.be/{datos.get('id')}",
                    "titulo": titulo,
                    "titulo_completo": titulo_completo,
                    "privacidad": privacidad,
                    "fecha": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "bytes": total,
                    "cuota_youtube_gastada_hoy": gastado,
                }
                with open(marca_path(video_path), "w", encoding="utf-8") as m:
                    json.dump(marca, m, ensure_ascii=False, indent=2)
                logger.info(f"Vídeo subido: {marca['url']} ({privacidad})")
                return marca
            if resp.status_code == 308:
                rango = resp.headers.get("Range")
                # YouTube dice hasta dónde recibió. Fiarse del contador local en
                # vez de su Range es lo que corrompe una subida reanudada.
                subidos = int(rango.split("-")[1]) + 1 if rango else subidos + len(trozo)
                f.seek(subidos)
                if progreso:
                    progreso(subidos, total)
                continue
            raise SubidaFallida(
                f"Fallo subiendo el trozo {subidos}-{fin} ({resp.status_code}): "
                f"{resp.text[-500:]}")

    raise SubidaFallida("La subida terminó sin que YouTube devolviera el vídeo")


def _sube_trozo(sesion, destino, trozo, ini, fin, total, intentos=4):
    """Sube un trozo con reintentos. 5xx y 308 son normales en resumable."""
    espera = 2
    ultimo = None
    for intento in range(intentos):
        try:
            resp = sesion.put(
                destino, data=trozo,
                headers={"Content-Length": str(len(trozo)),
                         "Content-Range": f"bytes {ini}-{fin}/{total}"},
                timeout=300,
            )
            if resp.status_code < 500:
                return resp
            ultimo = f"{resp.status_code}: {resp.text[-200:]}"
        except requests.RequestException as e:
            ultimo = str(e)
        logger.warning(
            f"Trozo {ini}-{fin} falló ({ultimo}); reintento "
            f"{intento + 2}/{intentos} en {espera}s")
        time.sleep(espera)
        espera *= 2
    raise SubidaFallida(f"El trozo {ini}-{fin} falló tras {intentos} intentos: {ultimo}")
