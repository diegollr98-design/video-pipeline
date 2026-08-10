import argparse
import glob
import logging
import os
import re
import sys

from modules.utils import (
    load_dotenv, load_config, ensure_dirs, cleanup_temp,
    get_video_duration, calculate_target_words, check_dependencies,
)
from modules.script_generator import generate_story
from modules.tts_engine import run_tts
from modules.subtitle_builder import vtt_to_ass
from modules.video_composer import compose
from modules.video_cleaner import clean_gameplay
from modules.gameplay_pool import add_to_pool, take_chunk, get_pool_status
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


def generate_shorts_for_video(gameplay_path, video_num, config, chunk_duration=0):
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
    else:
        num_shorts = shorts_config.get("generate_per_video", 2)

    # Count existing shorts to avoid numbering collisions
    existing_shorts = sorted(
        glob.glob(os.path.join(config["paths"].get("shorts_dir", "./shorts_tiktok"), "short_*.mp4"))
    )
    short_num_base = len(existing_shorts) + 1

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
    target_min = config["story"]["target_duration_min"]
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

    while True:
        chunk_path, chunk_duration = take_chunk(config)
        if chunk_path is None:
            logger.info("No hay suficiente gameplay en el pool para otro video")
            break

        try:
            if produce_video(chunk_path, chunk_duration, video_num, config, args):
                success += 1

                # Phase 2b: Generate shorts from the same chunk
                if not args.dry_run and config.get("shorts", {}).get("enabled", False) and not args.no_shorts:
                    shorts_generated = generate_shorts_for_video(chunk_path, video_num, config, chunk_duration)
                    if shorts_generated > 0:
                        logger.info(f"Generados {shorts_generated} shorts para video {video_num}")

                video_num += 1
        except Exception as e:
            logger.error(f"Error produciendo video {video_num}: {e}")
        finally:
            # Cleanup chunk
            if os.path.exists(chunk_path):
                os.remove(chunk_path)

    logger.info(f"Pipeline finalizado: {success} videos producidos")

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


if __name__ == "__main__":
    main()
