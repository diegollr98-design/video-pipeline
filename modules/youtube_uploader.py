"""Subida a YouTube — el último paso para que el pipeline sea autónomo.

DECISIONES TOMADAS POR DIEGO (11-ago-2026), que son las que dan forma a esto:
  1. Se sube en **privado**. Nadie lo publica salvo él, desde YouTube Studio.
  2. Se sube **solo el vídeo largo**. Los ~50 shorts NO: 51 subidas x 1.600 =
     81.600 unidades frente a las 10.000 diarias.
  3. Se dispara desde una **cola con su OK** en el dashboard, no automáticamente
     al terminar la corrida. El modo de fallo de este proyecto es un vídeo que
     PARECE terminado, así que su ojo sigue en el bucle.

La cuota se carga al MISMO contador que el análisis de competencia
(`QuotaMeter` sobre `data/competitors.json`): comparten los cupos diarios.
Ojo: `videos.insert` NO sale del bote de 10.000 unidades, tiene su propio cupo
de 100 llamadas/dia (ver QUOTA_BUCKET en competitor_scout.py).

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
    QUOTA_COST, QuotaMeter, QuotaExhausted, meter_from_config,
    load_state, save_state, _data_dir,
)
from modules.utils import huella_auditor

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
THUMBNAIL_URL = "https://www.googleapis.com/upload/youtube/v3/thumbnails/set"
CHUNK = 8 * 1024 * 1024  # 8 MB por trozo; un video de 30 min son ~3,4 GB
THUMBNAIL_MAX_BYTES = 2 * 1024 * 1024  # límite DURO de YouTube (dato externo: verificar si cambia)

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
    # El fichero lleva un refresh_token de larga vida: con el se puede publicar
    # en el canal. Se crea con permisos restrictivos ANTES de escribir nada,
    # para no dejar ni una ventana con el token en un fichero 0644 (en un clon
    # Linux/macOS ese es el default y lo lee cualquier usuario de la maquina).
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(creds.to_json())
    try:
        os.chmod(path, 0o600)          # por si el fichero ya existia
    except OSError as e:
        # §13: nada de fallback mudo. En Windows chmod es casi un no-op, pero
        # si falla en un POSIX hay que enterarse.
        logger.warning(f"No se pudieron restringir los permisos de {path}: {e}")
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
        titulo_yt_bruto = _lee_titulo_txt(titulo_corto_path(ruta)) or None
        titulo_pub, _titulo_largo_resuelto, fuente_titulo = resuelve_titulo_publicable(ruta)
        auditoria = lee_veredicto(ruta)
        items.append({
            "video": ruta,
            "stem": stem,
            "titulo": titulo,
            "titulo_yt": titulo_yt_bruto,
            "titulo_publicado": titulo_pub,
            "titulo_publicado_fuente": fuente_titulo,
            "thumbnail": thumb if os.path.exists(thumb) else None,
            "tam_mb": round(os.path.getsize(ruta) / 1024 / 1024, 1),
            "subido": ya_subido(ruta),
            "marca": lee_marca(ruta),
            "auditoria": auditoria,
            "publicable": bool(auditoria.get("ok")),
        })
    return items


def lee_veredicto(video):
    """Veredicto de `scripts/audit_run.py` para este vídeo.

    Sin fichero, `ok` es False: un vídeo NO auditado no es un vídeo sano, es un
    vídeo desconocido, y el default tiene que caer del lado barato (§16). Es
    justo lo que fallaba antes — el aviso se imprimía en un log que nadie lee
    mientras el vídeo seguía ofreciéndose para publicar.
    """
    ruta = video[: -len("_final.mp4")] + "_audit.json"
    if not os.path.exists(ruta):
        return {"ok": False, "medido": False,
                "fallos": ["sin auditar: no existe el veredicto"]}
    try:
        with open(ruta, encoding="utf-8") as f:
            d = json.load(f)
        d.setdefault("ok", False)
        d.setdefault("fallos", [])
        # Un veredicto CADUCA si los criterios cambiaron desde que se emitió.
        # `video_002_audit.json` decía ok:true con un auditor 47 min más viejo
        # que la comprobación que lo habría tumbado, y el botón de subir seguía
        # activo. Un verde de otro auditor es un desconocido, no un sano (§16).
        actual = huella_auditor()
        if d.get("auditor") != actual:
            emitida = d.get("auditor") or "sin huella (anterior a este control)"
            return {"ok": False, "medido": False, "fecha": d.get("fecha"),
                    "caducado": True,
                    "fallos": [f"veredicto CADUCADO: se emitió con otro auditor "
                               f"({emitida}, ahora {actual}). Re-audita el vídeo."]}
        return d
    except Exception as e:
        return {"ok": False, "medido": False,
                "fallos": [f"veredicto ilegible ({type(e).__name__})"]}


# ---------------------------------------------------------------- título
# Contrato fijado con el otro agente (11-ago-2026), no se renegocia aquí:
#   <stem>_title.txt     -> título LARGO (28-38 palabras). El de siempre: se
#                            narra, va a la intro y a la miniatura.
#   <stem>_title_yt.txt  -> título CORTO para el campo de YouTube (<=100
#                            caracteres). NUEVO. Puede no existir (vídeos
#                            viejos, o si aún no ha corrido el otro agente).
def titulo_largo_path(video_path):
    stem = os.path.basename(video_path)[: -len("_final.mp4")]
    return os.path.join(os.path.dirname(video_path), f"{stem}_title.txt")


def titulo_corto_path(video_path):
    stem = os.path.basename(video_path)[: -len("_final.mp4")]
    return os.path.join(os.path.dirname(video_path), f"{stem}_title_yt.txt")


def _lee_titulo_txt(path):
    if not path or not os.path.exists(path):
        return ""
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except Exception as e:
        logger.warning(f"No se pudo leer {path}: {e}")
        return ""


def _recorta_a_100(titulo):
    """Recorta por palabras a <=100 caracteres. Devuelve (titulo, fue_recortado).

    YouTube corta el campo de título en 100. Se recorta por palabra completa
    (nunca a mitad) y se marca con '...' para que sea visible que se cortó.
    """
    if len(titulo) <= 100:
        return titulo, False
    recorte = []
    for p in titulo.split():
        if len(" ".join(recorte + [p])) > 97:
            break
        recorte.append(p)
    return " ".join(recorte) + "...", True


def resuelve_titulo_publicable(video_path):
    """Título que REALMENTE se publica en el campo de YouTube, y de dónde sale.

    Devuelve (titulo_para_youtube, titulo_largo, fuente).
      - fuente == "corto":            _title_yt.txt existe, cabe en 100 tal cual.
      - fuente == "corto_recortado":  _title_yt.txt existe pero superaba 100
                                       (contrato roto aguas arriba) -> se recorta
                                       igual, nunca se confía en que el otro
                                       módulo cumplió su propio límite.
      - fuente == "largo":            no hay título corto y el largo YA cabía
                                       en 100 (caso raro, pero no se asume que
                                       no pase).
      - fuente == "largo_recortado":  no hay título corto -> comportamiento de
                                       siempre: el largo recortado por palabras.

    El título LARGO se devuelve siempre íntegro (sin recortar): es el que va al
    principio de la descripción, exista o no el corto.
    """
    stem = os.path.basename(video_path)[: -len("_final.mp4")]
    titulo_largo = _lee_titulo_txt(titulo_largo_path(video_path)) or stem

    corto_bruto = _lee_titulo_txt(titulo_corto_path(video_path))
    if corto_bruto:
        titulo, recortado = _recorta_a_100(corto_bruto)
        fuente = "corto_recortado" if recortado else "corto"
        return titulo, titulo_largo, fuente

    titulo, recortado = _recorta_a_100(titulo_largo)
    fuente = "largo_recortado" if recortado else "largo"
    return titulo, titulo_largo, fuente


# ---------------------------------------------------------------- cuota
def puede_subir(config):
    """(bool, mensaje). Comprueba la cuota ANTES de empezar a subir 3 GB.

    Cortar a mitad de una subida de 3,4 GB por un 403 de cuota es tirar 10
    minutos de red, así que se pregunta antes.
    """
    state = load_state(config)
    meter = meter_from_config(state, config)
    # `videos.insert` NO sale del bote de unidades: tiene su propio cupo de
    # llamadas al dia. Preguntar por `remaining()` (que es el de unidades)
    # respondia sobre el cupo equivocado.
    if not meter.can_afford("videosInsert"):
        return False, (
            f"Cupo de subidas de YouTube agotado: {meter.spent['upload']}/"
            f"{meter.limits['upload']} subidas hoy. Se restablece a medianoche UTC."
        )
    # La miniatura va aparte y esa SI sale del bote de unidades.
    if not meter.can_afford("thumbnailsSet"):
        return False, (
            f"Quedan subidas ({meter.remaining('upload')}) pero no unidades para la "
            f"miniatura: {meter.spent['units']}/{meter.limits['units']} usadas hoy."
        )
    return True, (
        f"Quedan {meter.remaining('upload')} subidas de {meter.limits['upload']} hoy; "
        f"la miniatura gastará {QUOTA_COST['thumbnailsSet']} unidades."
    )


def _cobra_cuota(config):
    state = load_state(config)
    meter = meter_from_config(state, config)
    meter.charge("videosInsert")       # lanza QuotaExhausted si no cabe
    save_state(state, config)
    return meter.resumen(), meter.limits


def thumbnail_path_for(video_path):
    """Ruta de la miniatura que genera `thumbnail_generator.py` para este vídeo.

    Mismo patrón que usa `pendientes()` más abajo — un solo sitio decide el
    nombre del fichero, para que ambos no se desincronicen.
    """
    stem = os.path.basename(video_path)[: -len("_final.mp4")]
    return os.path.join(os.path.dirname(video_path), f"{stem}_thumbnail.jpg")


def _cobra_cuota_miniatura(config):
    state = load_state(config)
    meter = meter_from_config(state, config)
    meter.charge("thumbnailsSet")      # lanza QuotaExhausted si no cabe
    save_state(state, config)
    return meter.resumen(), meter.limits


def subir_miniatura(video_id, thumbnail_path, config, creds=None):
    """Sube la miniatura de un vídeo YA subido a YouTube.

    Regla dura de este cambio: el vídeo de 1,5+ GB ya está arriba y una
    subida de 3 GB no se repite por culpa de un JPEG. Por eso esta función
    NUNCA lanza — devuelve un string de estado ("ok" / "sin miniatura" /
    "fallo: <motivo>") para que el caller lo escriba en la marca. Marcar,
    no matar (§13 de `decision-making.md`: nada de fallback silencioso —
    aquí el "log ruidoso + propagar" se cumple devolviendo el motivo, no
    tragándoselo).
    """
    if not thumbnail_path or not os.path.exists(thumbnail_path):
        logger.warning(
            f"Sin miniatura que subir para el vídeo {video_id}: "
            f"no existe {thumbnail_path}")
        return "sin miniatura"

    try:
        tam = os.path.getsize(thumbnail_path)
    except OSError as e:
        logger.error(f"No se pudo leer el tamaño de {thumbnail_path}: {e}")
        return f"fallo: no se pudo leer el fichero ({type(e).__name__}: {e})"

    if tam > THUMBNAIL_MAX_BYTES:
        motivo = (f"miniatura de {tam / 1024 / 1024:.2f} MB supera el límite "
                   f"de YouTube de 2 MB ({thumbnail_path})")
        logger.error(motivo)
        return f"fallo: {motivo}"

    try:
        if creds is None:
            creds = _credenciales(config)
    except FaltaCredencial as e:
        logger.error(
            f"Sin credenciales para subir la miniatura del vídeo {video_id}: {e}")
        return f"fallo: sin credenciales ({e})"

    try:
        with open(thumbnail_path, "rb") as f:
            datos = f.read()
    except OSError as e:
        logger.error(f"No se pudo leer {thumbnail_path}: {e}")
        return f"fallo: no se pudo leer el fichero ({type(e).__name__}: {e})"

    try:
        gastado, cupos = _cobra_cuota_miniatura(config)
    except QuotaExhausted as e:
        logger.error(f"Sin cuota de YouTube para la miniatura de {video_id}: {e}")
        return f"fallo: {e}"

    try:
        r = requests.post(
            THUMBNAIL_URL,
            params={"videoId": video_id, "uploadType": "media"},
            headers={
                "Authorization": f"Bearer {creds.token}",
                "Content-Type": "image/jpeg",
                "Content-Length": str(len(datos)),
            },
            data=datos,
            timeout=60,
        )
    except requests.RequestException as e:
        logger.error(f"Fallo de red subiendo la miniatura de {video_id}: {e}")
        return f"fallo: red ({type(e).__name__}: {e})"

    if r.status_code not in (200, 201):
        motivo = f"YouTube rechazó la miniatura ({r.status_code}): {r.text[-500:]}"
        logger.error(motivo)
        return f"fallo: {motivo}"

    logger.info(
        f"Miniatura subida para el vídeo {video_id}; cuota -> {gastado}")
    return "ok"


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
        # Título CORTO (<=100) si `_title_yt.txt` existe y no está vacío; si no,
        # el comportamiento de siempre: el título LARGO recortado por palabras.
        # El largo va SIEMPRE íntegro al principio de la descripción.
        titulo, titulo_completo, fuente_titulo = resuelve_titulo_publicable(video_path)
        if fuente_titulo == "corto":
            logger.info(f"Título corto para YouTube ({len(titulo)} car.): {titulo}")
        elif fuente_titulo == "corto_recortado":
            logger.warning(
                f"_title_yt.txt superaba 100 caracteres (contrato roto aguas "
                f"arriba); recortado igual: {titulo}")
        elif fuente_titulo == "largo_recortado":
            logger.warning(f"Sin título corto: título largo recortado a 100 "
                           f"caracteres para YouTube: {titulo}")
        else:  # "largo"
            logger.info(f"Sin título corto, pero el largo ya cabía ({len(titulo)} car.)")
    else:
        # Título pasado explícitamente por el caller: se recorta igual si hace
        # falta, nunca se confía en que quien lo pasó cumplió el límite.
        titulo_completo = titulo
        titulo, recortado = _recorta_a_100(titulo)
        if recortado:
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
    gastado, cupos = _cobra_cuota(config)
    logger.info(f"Subida iniciada; cuota de YouTube -> {gastado}")

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
                video_id = datos.get("id")

                # El vídeo YA está arriba. Si esto falla, NO se propaga: se
                # marca en la propia marca de subida y se sigue (§13 — marcar,
                # no matar, una subida de 3 GB no se repite por un JPEG).
                thumb_path = thumbnail_path_for(video_path)
                estado_thumb = subir_miniatura(video_id, thumb_path, config, creds=creds)
                if estado_thumb == "ok":
                    logger.info(f"Miniatura OK para {video_id}")
                elif estado_thumb == "sin miniatura":
                    logger.warning(f"Vídeo {video_id} subido sin miniatura propia (usará la de YouTube)")
                else:
                    logger.error(f"Miniatura de {video_id} NO subida: {estado_thumb}")

                marca = {
                    "video_id": video_id,
                    "url": f"https://youtu.be/{video_id}",
                    "titulo": titulo,
                    "titulo_completo": titulo_completo,
                    "privacidad": privacidad,
                    "fecha": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "bytes": total,
                    "cuota_youtube_gastada_hoy": gastado,
                    "thumbnail": estado_thumb,
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
