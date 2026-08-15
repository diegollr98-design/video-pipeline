import argparse
import glob
import logging
import os
import re
import sys

from modules.utils import (
    load_dotenv, load_config, ensure_dirs, cleanup_temp,
    calculate_target_words, check_dependencies,
)
from modules.script_generator import generate_story, generar_titulo_youtube
from modules.tts_engine import run_tts
from modules.subtitle_builder import vtt_to_ass
from modules.video_composer import compose
from modules.video_cleaner import clean_gameplay
from modules.gameplay_pool import (add_to_pool, take_chunk, get_pool_status,
                                   devolver_al_pool)
from modules.thumbnail_generator import generate_thumbnail, generate_title_card
from modules.shorts_generator import generate_short
from modules import competitor_scout, trend_advisor


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("pipeline.log", encoding="utf-8"),
        ],
    )


def ingest_videos(video_paths, config):
    """Phase 1: Clean input videos and add to gameplay pool."""
    logger = logging.getLogger(__name__)
    added = 0

    for video_path in video_paths:
        stem = os.path.splitext(os.path.basename(video_path))[0]
        temp_dir = config["paths"]["temp_dir"]
        clean_path = os.path.join(temp_dir, f"{stem}_clean.mp4")

        logger.info(f"--- Ingesting: {os.path.basename(video_path)} ---")

        try:
            # Clean gameplay (remove pause, desktop, menus)
            gameplay_path = clean_gameplay(video_path, clean_path, config)

            # Add to pool (hardlink if original, ffmpeg copy if cleaned)
            is_original = (gameplay_path == video_path)
            add_to_pool(gameplay_path, config, is_original=is_original)
            added += 1

            # Cleanup temp clean file if it was created
            if not is_original and os.path.exists(clean_path):
                os.remove(clean_path)

        except Exception as e:
            logger.error(f"Error ingesting {video_path}: {e}")
            continue

    logger.info(f"Ingestados {added}/{len(video_paths)} videos al pool")
    return added


def generate_shorts_for_video(gameplay_path, video_num, config, chunk_duration=0, max_shorts=0):
    """Generate YouTube Shorts/TikToks from a gameplay clip."""
    logger = logging.getLogger(__name__)

    if not config.get("shorts", {}).get("enabled", False):
        return 0

    shorts_config = config["shorts"]
    speed = shorts_config.get("speed", 1.5)

    # Calculate how many shorts fit in the gameplay chunk.
    #
    # Usa shorts.narration_wpm, NO story.target_wpm: son dos ritmos distintos
    # (textos cortos ~200 wpm, historias largas ~160) y compartir la clave hacía
    # que recalibrar la historia larga cambiase en silencio cuántos shorts se
    # generan. Ese acoplamiento ya costó un +30% de peticiones sin reportar
    # cuando target_wpm pasó de 150 a 195 (33 -> 43 shorts por vídeo de 30 min).
    target_words = shorts_config.get("target_words", 200)
    wpm = shorts_config.get("narration_wpm", 200)
    short_audio_dur = (target_words / wpm) * 60  # seconds at 1x TTS speed
    short_real_dur = short_audio_dur / speed      # actual short duration after speed-up

    if chunk_duration > 0 and short_real_dur > 0:
        num_shorts = max(1, int(chunk_duration / short_real_dur))
        logger.info(
            f"Shorts: {chunk_duration:.0f}s gameplay / {short_real_dur:.0f}s por short "
            f"= {num_shorts} shorts (= {num_shorts} peticiones de OpenRouter)"
        )
        # Tope explicito para las corridas de VALIDACION. `generate_per_video`
        # de config.yaml NO sirve para esto: solo se usa cuando no hay duracion
        # de chunk, asi que un chunk de 33 min pide 50 shorts pase lo que pase.
        # Con 2,2 min de reloj por short medidos, esos 50 son ~1h50 de las 2h30
        # de la corrida y ~50 de sus ~56 peticiones: el 73% del reloj y el 85%
        # de la cuota para ejercitar un gemelo que con 3-5 ya queda medido.
        tope = max_shorts or 0
        if tope and num_shorts > tope:
            logger.warning(
                f"Shorts LIMITADOS a {tope} por --max-shorts (salian {num_shorts}). "
                f"Se ahorran {num_shorts - tope} peticiones y ~{(num_shorts - tope) * 2.2:.0f} "
                f"min de reloj. El gameplay sobrante NO se usa en esta corrida."
            )
            num_shorts = tope
    else:
        num_shorts = shorts_config.get("generate_per_video", 2)

    # [SHORTNUM-01] Numeración por el MÁXIMO, no por el conteo. `len(...) + 1`
    # colisiona en cuanto hay un hueco —un short borrado a mano, o uno que falló
    # a mitad más abajo— y la tanda siguiente SOBRESCRIBE en silencio shorts ya
    # producidos, mp4 y `_title.txt`. Medido: con `short_001, 003, 004` en disco,
    # `len+1` da 4 y regenera encima de `short_004`.
    # Es el idioma que ya usan sus dos hermanos: `main.py` para los vídeos y
    # `dashboard_runner.py` para los logs.
    existing_shorts = glob.glob(
        os.path.join(config["paths"].get("shorts_dir", "./shorts_tiktok"), "short_*.mp4")
    )
    nums_shorts = []
    for p in existing_shorts:
        try:
            nums_shorts.append(int(os.path.basename(p)[: -len(".mp4")].split("_")[1]))
        except (IndexError, ValueError):
            pass
    short_num_base = (max(nums_shorts) + 1) if nums_shorts else 1

    # Títulos ya generados en esta tanda. Se le pasan al modelo para que no
    # repita la historia: sin esto los shorts salían todos iguales, porque cada
    # uno es una llamada independiente con el mismo prompt.
    titulos_previos = []

    # Se arrastran también los títulos de shorts anteriores que sigan en disco,
    # para que dos corridas seguidas no produzcan lo mismo.
    shorts_dir = config["paths"].get("shorts_dir", "./shorts_tiktok")
    for path in sorted(glob.glob(os.path.join(shorts_dir, "short_*_title.txt")))[-8:]:
        try:
            with open(path, "r", encoding="utf-8") as f:
                titulo = f.read().strip()
            if titulo:
                titulos_previos.append(titulo)
        except OSError:
            pass

    generated = 0
    for i in range(num_shorts):
        try:
            short_num = short_num_base + i
            style = config["story"]["style"]
            offset = i * short_real_dur

            logger.info(f"--- Generando short {short_num} para video {video_num} (offset={offset:.0f}s) ---")
            titulo = generate_short(gameplay_path, short_num, config, style=style,
                                    speed=speed, offset=offset, avoid=titulos_previos)
            if titulo:
                titulos_previos.append(titulo)
            generated += 1
        except Exception as e:
            logger.error(f"Error generando short {short_num}: {e}")
            continue

    return generated


def run_competition_scan(config, args):
    """Fase 3: escanea la competencia, debate qué atacar y (opcional) lo aplica.

    No produce videos: es una corrida independiente pensada para lanzarse desde
    el dashboard o programada. Devuelve 0 si todo fue bien, 1 si falló.
    """
    logger = logging.getLogger(__name__)

    if not config.get("competition", {}).get("enabled", True):
        logger.error("El análisis de competencia está desactivado en config.yaml")
        return 1

    logger.info("=== Fase 3: Análisis de competencia ===")

    try:
        report = competitor_scout.scan(config, discover=not args.no_discover)
    except competitor_scout.MissingApiKey as e:
        logger.error(str(e))
        return 1
    except Exception as e:
        logger.error(f"Error escaneando la competencia: {e}")
        return 1

    logger.info(
        f"Competidores activos: {report['competitors_active']} | "
        f"videos analizados: {report['videos_analyzed']} | "
        f"cuota usada: {report['quota_used_this_run']} unidades "
        f"({report['quota_used_today']}/{report['quota_daily_limit']} hoy)"
    )

    if not report["viral"]:
        logger.warning(
            "El escaneo no encontró videos virales. Revisa las keywords o añade "
            "canales semilla en config.yaml (competition.seed_channels)."
        )
        return 1

    logger.info("--- Top virales ---")
    for i, v in enumerate(report["viral"][:5], 1):
        logger.info(
            f"{i}. [{v['viral_score']}] {v['title'][:70]} "
            f"({v['channel_title']}, {v['views']:,} vistas, x{v.get('outlier_ratio', 0):.1f})"
        )

    try:
        advice = trend_advisor.debate(report, config)
    except Exception as e:
        logger.error(f"Error en el debate: {e}")
        return 1

    print("\n=== VEREDICTO ===")
    print(advice["veredicto"] or "(el modelo no devolvió veredicto)")
    print("\n=== DIRECTRICES ===")
    for d in advice["directrices"]:
        print(f"- {d}")

    if args.apply_trends:
        trend_advisor.apply_to_prompt(advice, config)
        logger.info("Directrices aplicadas al prompt de historias")
    else:
        logger.info(
            "Ejecuta con --apply-trends (o pulsa Aplicar en el dashboard) para "
            "inyectar estas directrices en el prompt de historias."
        )

    return 0


def produce_video(chunk_path, chunk_duration, video_num, config, args):
    """Phase 2: Generate one complete video from a gameplay chunk."""
    logger = logging.getLogger(__name__)
    temp_dir = config["paths"]["temp_dir"]
    stem = f"video_{video_num:03d}"

    logger.info(f"=== Produciendo {stem} ({chunk_duration:.0f}s / {chunk_duration/60:.1f}min) ===")

    # 1. Calculate target words for this duration
    target_words = calculate_target_words(chunk_duration, config)
    logger.info(f"Duración: {chunk_duration:.0f}s -> objetivo: {target_words} palabras")

    # 2. Generate story
    style = args.style or config["story"]["style"]
    title, story = generate_story(target_words, style, config)

    story_path = os.path.join(temp_dir, f"{stem}_story.txt")
    with open(story_path, "w", encoding="utf-8") as f:
        f.write(story)

    title_path = os.path.join(temp_dir, f"{stem}_title.txt")
    with open(title_path, "w", encoding="utf-8") as f:
        f.write(title)

    logger.info(f"Título: {title}")
    logger.info(f"Historia: {len(story.split())} palabras")

    if args.dry_run:
        logger.info("Modo dry-run: saltando TTS y composición")
        print(f"\n--- TÍTULO ---\n{title}\n")
        print(f"--- Historia ({len(story.split())} palabras) ---\n")
        print(story)
        return True

    # 2b. Título CORTO para el campo de título de YouTube (≤100 caracteres).
    # El título LARGO de arriba no cambia: sigue siendo el que se narra, el
    # de la intro (title_end_time se calcula sobre él más abajo) y el de la
    # miniatura. Este es un fichero NUEVO, no un reemplazo de `_title.txt`.
    titulo_yt = generar_titulo_youtube(title, config)
    titulo_yt_path = os.path.join(config["paths"]["output_dir"], f"{stem}_title_yt.txt")
    with open(titulo_yt_path, "w", encoding="utf-8") as f:
        f.write(titulo_yt)
    logger.info(f"Título YouTube ({len(titulo_yt)} caracteres): {titulo_yt}")

    # 3. TTS (auto-detects gender from story, selects male/female voice)
    audio_path = os.path.join(temp_dir, f"{stem}_audio.mp3")
    vtt_path = os.path.join(temp_dir, f"{stem}_subs.vtt")
    audio_duration, aligned_words = run_tts(story, audio_path, vtt_path, config)

    # Calculate when the title sentence ends in the audio
    # Match title words against aligned words to find exact end time
    title_clean = re.sub(r'[.!?,;:\-\"\']', '', title.lower()).split()
    title_word_count = len(title_clean)
    title_end_time = 0
    if aligned_words and title_word_count > 0 and title_word_count < len(aligned_words):
        title_end_time = aligned_words[title_word_count - 1]["end"]
    logger.info(f"Titulo ({title_word_count} palabras) termina en: {title_end_time:.1f}s")

    # 4. Build styled subtitles (skip during intro)
    ass_path = os.path.join(temp_dir, f"{stem}_subs.ass")
    vtt_to_ass(vtt_path, ass_path, config, skip_until=title_end_time)

    # 5. Generate title card for intro animation
    title_card_path = os.path.join(temp_dir, f"{stem}_titlecard.png")
    generate_title_card(title, title_card_path, config)

    # 6. Compose final video (with intro overlay + woosh + synced fade)
    output_path = os.path.join(config["paths"]["output_dir"], f"{stem}_final.mp4")
    compose(chunk_path, audio_path, ass_path, output_path, config, title_card_path, title_end_time)

    # 7. Generate thumbnail
    thumb_path = os.path.join(config["paths"]["output_dir"], f"{stem}_thumbnail.jpg")
    generate_thumbnail(chunk_path, title, thumb_path, config)

    # Also save title next to output for easy reference
    output_title = os.path.join(config["paths"]["output_dir"], f"{stem}_title.txt")
    with open(output_title, "w", encoding="utf-8") as f:
        f.write(title)

    logger.info(f"=== Completado: {output_path} ===\n")
    return True


def _auditar_salida(config, args, chunk_dur, stems=None):
    """Corre `scripts/audit_run.py` y deja su veredicto junto a cada vídeo.

    Como SUBPROCESO a propósito: el auditor carga whisper para transcribir de
    forma independiente, y una excepción suya no puede llevarse por delante una
    corrida de 2 h. Si falla, el vídeo se queda SIN veredicto, y sin veredicto
    el dashboard no lo ofrece para subir: el default cae del lado barato.
    """
    import subprocess

    # `logger` es local a cada funcion en este modulo (no hay uno de modulo).
    logger = logging.getLogger(__name__)

    # TODO el cuerpo va dentro del try: la primera version dejaba fuera el
    # armado del comando y un NameError se llevo por delante la corrida entera
    # justo despues de "Pipeline finalizado". Marcar, no matar significa que
    # NADA de aqui puede propagar.
    try:
        cmd = [sys.executable, os.path.join("scripts", "audit_run.py"),
               "--output", config["paths"]["output_dir"],
               "--temp", config["paths"]["temp_dir"],
               "--shorts", str(args.audit_shorts)]
        shorts_dir = (config.get("paths") or {}).get("shorts_dir")
        if shorts_dir:
            cmd += ["--shorts-dir", shorts_dir]
        if chunk_dur:
            cmd += ["--chunk-dur", f"{chunk_dur:.1f}"]
        # Solo lo producido en ESTA corrida. Sin esto el auditor re-transcribe
        # con whisper todos los videos acumulados en output/, que en produccion
        # son de 30 min cada uno: minutos de reloj por cada video viejo, cada
        # vez, para reescribir un veredicto que ya existia.
        if stems:
            cmd += ["--stem", ",".join(stems)]

        logger.info(f"Auditando la salida: {' '.join(cmd[1:])}")
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=3600,
                           encoding="utf-8", errors="replace")
        for linea in (r.stdout or "").splitlines():
            logger.info(f"[audit] {linea}")
        if r.returncode != 0:
            # El auditor devuelve 1 cuando encuentra defectos: eso NO es un
            # error del auditor, es su trabajo.
            logger.warning("[audit] la salida tiene defectos MEDIBLES: revisa el "
                           "veredicto antes de publicar")
        if r.stderr:
            logger.warning(f"[audit] stderr: {r.stderr[-800:]}")
    except subprocess.TimeoutExpired:
        logger.error("[audit] la auditoria excedio 1 h y se corto. Los videos sin "
                     "veredicto NO entran en la cola de subida.")
    except Exception as e:
        # Marcar, no matar: la corrida ya está hecha y no se tira por esto.
        logger.error(f"[audit] no se pudo auditar ({type(e).__name__}: {e}). Los "
                     f"videos sin veredicto NO entran en la cola de subida.")


def main():
    parser = argparse.ArgumentParser(description="YouTube Automation - Reddit Stories Pipeline")
    parser.add_argument("--video", help="Procesar un video específico en vez de todos en input/")
    parser.add_argument("--voice", help="Override de voz TTS (ej: es-ES-AlvaroNeural)")
    parser.add_argument("--style", help="Override de estilo (dramatic/funny/horror/wholesome)")
    parser.add_argument("--dry-run", action="store_true", help="Solo genera historia, sin audio ni video")
    parser.add_argument("--config", default="config.yaml", help="Ruta al archivo de configuración")
    parser.add_argument("--skip-ingest", action="store_true", help="No ingestar nuevos videos, solo producir del pool")
    parser.add_argument("--keep-temp", action="store_true",
                        help="No borrar temp/ al terminar. Necesario para /eval: el .ass y el "
                             "_story.txt son lo que se mide, y cleanup_temp los destruía")
    parser.add_argument("--no-shorts", action="store_true",
                        help="Desactiva la generación de shorts en esta corrida")
    parser.add_argument("--max-shorts", type=int, default=0,
                        help="Tope de shorts por video (0 = sin tope). Para corridas de "
                             "VALIDACION: con 3-5 se mide el gemelo igual y se ahorra el "
                             "85%% de la cuota y el 73%% del reloj")
    parser.add_argument("--no-audit", action="store_true",
                        help="No auditar la salida al terminar. OJO: sin veredicto, "
                             "el dashboard NO ofrece el vídeo para subir")
    parser.add_argument("--audit-shorts", type=int, default=2,
                        help="cuántos shorts mide la auditoría de sincronismo (0 = ninguno)")
    parser.add_argument("--scan-competition", action="store_true",
                        help="Solo analiza la competencia (no produce videos) y debate qué atacar")
    parser.add_argument("--no-discover", action="store_true",
                        help="Con --scan-competition: no busca canales nuevos, solo re-mide los conocidos (0 unidades de búsqueda)")
    parser.add_argument("--apply-trends", action="store_true",
                        help="Con --scan-competition: inyecta las directrices en el prompt de historias")
    args = parser.parse_args()

    setup_logging()
    logger = logging.getLogger(__name__)

    load_dotenv()

    # Load config
    config = load_config(args.config)
    ensure_dirs(config)
    os.makedirs(config["paths"]["pool_dir"], exist_ok=True)

    # === PHASE 3 (independiente): análisis de competencia ===
    # No necesita FFmpeg ni gameplay, así que va antes del chequeo de dependencias.
    if args.scan_competition:
        sys.exit(run_competition_scan(config, args))

    # Check dependencies
    if not args.dry_run:
        missing = check_dependencies()
        if missing:
            logger.error(f"Dependencias faltantes: {', '.join(missing)}")
            logger.error("Instala las dependencias necesarias antes de continuar.")
            sys.exit(1)

    # === PHASE 1: Ingest new videos into pool ===
    if not args.skip_ingest:
        if args.video:
            if not os.path.exists(args.video):
                logger.error(f"Video no encontrado: {args.video}")
                sys.exit(1)
            input_videos = [args.video]
        else:
            input_videos = sorted(glob.glob(os.path.join(config["paths"]["input_dir"], "*.mp4")))

        if input_videos:
            logger.info(f"=== Fase 1: Ingestando {len(input_videos)} videos ===")
            ingest_videos(input_videos, config)
        else:
            logger.info("No hay videos nuevos en input/")

    # Show pool status
    pool = get_pool_status(config)
    total_pool = sum(d for _, d in pool)
    logger.info(f"Pool: {len(pool)} archivos, {total_pool:.0f}s ({total_pool/60:.1f} min)")

    # === PHASE 2: Produce videos from pool ===
    video_num = 1
    success = 0

    # Find next video number based on existing outputs
    existing = glob.glob(os.path.join(config["paths"]["output_dir"], "video_*_final.mp4"))
    if existing:
        nums = []
        for f in existing:
            base = os.path.splitext(os.path.basename(f))[0]
            try:
                nums.append(int(base.split("_")[1]))
            except (IndexError, ValueError):
                pass
        if nums:
            video_num = max(nums) + 1

    ultimo_chunk_dur = None
    stems_producidos = []
    # Cuántas veces se TOMÓ un chunk y se intentó producir. Distingue "no había
    # gameplay que procesar" (0 vídeos legítimo) de "lo intenté y fallé"
    # (0 vídeos = fallo). Sin esta distinción no se puede devolver un código de
    # salida honesto: ver el comentario del `return` al final de la función.
    intentos = 0
    while True:
        # [DRYRUN-01] `take_chunk` CONSUME el pool: borra del disco los ficheros
        # que selecciona. En dry-run no se produce ningún vídeo, así que hacerlo
        # destruía horas de gameplay a cambio de nada — y `--dry-run` está
        # documentado como "solo genera historia sin video". Con el flag, calcula
        # la misma duración sin tocar el disco.
        chunk_path, chunk_duration = take_chunk(config, dry_run=args.dry_run)
        if chunk_path is None:
            logger.info("No hay suficiente gameplay en el pool para otro video")
            break
        ultimo_chunk_dur = chunk_duration
        intentos += 1

        ok_video = False
        try:
            if produce_video(chunk_path, chunk_duration, video_num, config, args):
                ok_video = True
                success += 1
                stems_producidos.append(f"video_{video_num:03d}")

                # Phase 2b: Generate shorts from the same chunk
                if not args.dry_run and config.get("shorts", {}).get("enabled", False) and not args.no_shorts:
                    shorts_generated = generate_shorts_for_video(
                        chunk_path, video_num, config, chunk_duration,
                        max_shorts=getattr(args, 'max_shorts', 0))
                    if shorts_generated > 0:
                        logger.info(f"Generados {shorts_generated} shorts para video {video_num}")

                video_num += 1
        except Exception as e:
            # `exc_info=True` NO es cosmético: sin la traza, un
            # "'NoneType' object has no attribute 'strip'" no dice en qué línea
            # murió, y averiguarlo costó una investigación entera con repro
            # monkeypatcheado. Es la misma clase que registrar los primeros 500
            # caracteres de stderr de FFmpeg (que son el banner de compilación)
            # y diagnosticar a ciegas.
            logger.error(f"Error produciendo video {video_num}: {e}", exc_info=True)
        finally:
            # Cleanup chunk. En dry-run `chunk_path` es `DRY_RUN_CHUNK`, que no
            # existe en disco a propósito: este borrado no encuentra nada.
            if os.path.exists(chunk_path):
                if ok_video or args.dry_run:
                    os.remove(chunk_path)
                else:
                    # [CHUNK-01] El chunk se saca del pool ANTES de generar la
                    # historia, así que un fallo aguas abajo lo borraba y se
                    # llevaba por delante toda la ingesta. Medido el 15-ago-2026:
                    # 13.207 MB analizados frame a frame y recodificados a 3.522
                    # MB, ~16 min de reloj, tirados porque el proveedor del
                    # modelo devolvía 504. El gameplay original se salvó de pura
                    # suerte (seguía en `input/`); con un `input/` ya consumido se
                    # habría destruido.
                    #
                    # Devolverlo al pool es lo correcto: el pool ES la cola de
                    # trabajo pendiente y el chunk ya tiene su formato. La
                    # siguiente corrida lo retoma sin re-ingestar nada.
                    try:
                        destino = devolver_al_pool(chunk_path, config)
                        logger.warning(
                            f"El video fallo: el chunk vuelve al pool como "
                            f"{os.path.basename(destino)} en vez de borrarse "
                            f"({chunk_duration/60:.1f} min de gameplay ya ingestado "
                            f"que NO hay que volver a procesar)"
                        )
                    except Exception as e:
                        # Si no se puede devolver, se dice y se CONSERVA en temp:
                        # perder el chunk en silencio es justo lo que se viene a
                        # evitar (§13).
                        logger.error(
                            f"No se pudo devolver el chunk al pool ({e}). Se "
                            f"CONSERVA en {chunk_path} para no perder la ingesta.",
                            exc_info=True)

        if args.dry_run:
            # OBLIGATORIO, no cosmético: en dry-run el pool no se consume, así
            # que `take_chunk` devolvería el MISMO chunk en cada vuelta y el
            # `while True` no terminaría nunca.
            logger.info("Modo dry-run: una sola historia, el pool queda intacto")
            break

    logger.info(f"Pipeline finalizado: {success} videos producidos")

    # AUDITORÍA de la salida, ANTES de cleanup_temp (que borra el .ass y el
    # _story.txt que son justo lo que se mide). Escribe el veredicto junto a
    # cada vídeo; el dashboard no ofrece para subir lo que no esté en verde.
    #
    # MARCAR, NO MATAR: si el auditor peta, la corrida no se pierde — pero el
    # vídeo se queda sin veredicto y por tanto FUERA de la cola de subida, que
    # es el lado barato del error (§16).
    if success and not args.dry_run and not args.no_audit:
        _auditar_salida(config, args, ultimo_chunk_dur, stems_producidos)

    # Show remaining pool
    pool = get_pool_status(config)
    total_pool = sum(d for _, d in pool)
    if total_pool > 0:
        logger.info(f"Sobrante en pool: {total_pool:.0f}s ({total_pool/60:.1f} min) — se usará en la próxima ejecución")

    # Cleanup temp (but not pool!)
    #
    # --keep-temp existe porque el gate /eval MIDE sobre estos artefactos: el
    # .ass es la entrada de scripts/eval_sync.py y el _story.txt es lo único que
    # permite auditar las comas a posteriori. Borrarlos al terminar dejaba al
    # gate sin nada que medir, y ninguna corrida de producción era auditable.
    if args.keep_temp:
        logger.info(f"Temporales CONSERVADOS en {config['paths']['temp_dir']} (--keep-temp)")
    elif not args.dry_run and success > 0:
        cleanup_temp(config)
        logger.info("Archivos temporales limpiados")

    # CÓDIGO DE SALIDA HONESTO. `main()` no devolvía nada, así que el proceso
    # salía SIEMPRE con 0 — incluida la corrida del 15-ago-2026, que tomó un
    # chunk de 33,4 min, se comió 16 min de ingesta y recodificación por GPU, y
    # murió con `0 videos producidos` porque el proveedor del modelo devolvía
    # 504/404. Exit 0 = "todo bien" para `daily-run`, para un cron y para
    # cualquier script que encadene. Es la misma clase que [GATE-04] en el
    # auditor: fallar ABIERTO, o sea dar la nota perfecta por no haber hecho nada.
    #
    # 0 vídeos NO siempre es un fallo: con el pool vacío no hay nada que
    # producir y eso es una corrida legítima. Lo que distingue un caso del otro
    # es si se llegó a INTENTAR.
    if intentos and not success:
        logger.error(
            f"Se intentaron {intentos} video(s) y no se produjo NINGUNO. "
            f"La corrida ha FALLADO (salida 1): no la trates como exitosa."
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
