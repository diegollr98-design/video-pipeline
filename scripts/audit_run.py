"""Auditoría de UNA corrida completa: ¿es publicable esta salida?

El modo de fallo de este proyecto no es que el pipeline pete, sino que entregue
un vídeo que PARECE terminado. Este script mide de golpe todo lo que se puede
medir de una corrida, para que el ojo de Diego se gaste solo en lo que no es
medible (si la historia engancha, si la voz suena natural).

Cada comprobación existe porque un defecto REAL se coló por ahí:
  sincronismo por tramos  -> [ANCLA-01] 60 s de vídeo a +1,05 s de la voz que
                             la media global (0,153 s) daba por bueno
  basura del modelo       -> [BASURA-01] 'ONEAN 0230 0207-' narrado y subtitulado
  párrafos repetidos      -> [DEDUP-01] 83 palabras narradas dos veces
  aperturas de títulos    -> 50/50 shorts empezaban por "Mi <alguien>"
  loudness                -> YouTube normaliza a -14 LUFS y SOLO BAJA: un vídeo
                             a -21 suena 7 dB por debajo de la competencia
  ratio de duración       -> gameplay desperdiciado o repetido

Uso:
  python scripts/audit_run.py                    # audita output/ y shorts_tiktok/
  python scripts/audit_run.py --shorts 3         # mide el sincronismo de 3 shorts
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.eval_sync import (  # noqa: E402
    lee_ass, extrae_audio, transcribe, empareja, peor_tramo,
    pausas_fuera_de_puntuacion,
)

OK, MAL, AVISO = "  OK  ", " FALLA", " AVISO"


def _ffprobe(path, campos, stream=False):
    sel = ["-select_streams", "v:0"] if stream else []
    ent = f"stream={campos}" if stream else f"format={campos}"
    r = subprocess.run(
        ["ffprobe", "-v", "error", *sel, "-show_entries", ent,
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True)
    return r.stdout.split()


def loudness(path):
    """LUFS integrados, medidos con ebur128 (el estándar que usa YouTube)."""
    r = subprocess.run(
        ["ffmpeg", "-nostdin", "-i", path, "-af", "ebur128=framelog=quiet", "-f", "null", "-"],
        capture_output=True, text=True)
    m = re.findall(r"I:\s+(-?\d+\.\d+)\s+LUFS", r.stderr)
    p = re.findall(r"Peak:\s+(-?\d+\.\d+)\s+dBFS", r.stderr)
    return (float(m[-1]) if m else None), (float(p[-1]) if p else None)


def ngramas_repetidos(texto, n=12):
    w = texto.split()
    vistos, dups = {}, []
    for i in range(len(w) - n):
        k = " ".join(x.lower() for x in w[i:i + n])
        if k in vistos:
            dups.append((vistos[k], i))
        else:
            vistos[k] = i
    if not dups:
        return 0, 0
    a, b = dups[0]
    largo = 0
    while a + largo < len(w) and b + largo < len(w) and w[a + largo].lower() == w[b + largo].lower():
        largo += 1
    return len(dups), largo


def audita_video(video, ass, story, chunk_dur=None, model="small"):
    print(f"\n=== VÍDEO LARGO: {os.path.basename(video)} ===")
    fallos = []

    # --- sincronismo contra transcripción INDEPENDIENTE
    ass_words = lee_ass(ass)
    wav = extrae_audio(video)
    pares = empareja(ass_words, transcribe(wav, model))
    cob = len(pares) / max(1, len(ass_words))
    if cob < 0.85:
        print(f"{AVISO} emparejado {cob:.1%} < 85%: la medición NO vale")
        return ["medición inválida"]
    errs = [e for *_, e in pares]
    abs_e = sorted(abs(e) for e in errs)
    p95 = abs_e[int(0.95 * (len(abs_e) - 1))]
    tarde = sum(1 for e in errs if e > 0.5)
    pt = peor_tramo(pares)
    med = sum(abs_e) / len(abs_e)
    sesgo = sum(errs) / len(errs)

    est = OK if abs(pt["mediana"]) <= 0.35 else MAL
    if est == MAL:
        fallos.append(f"peor tramo {pt['mediana']:+.3f}s en t={pt['t']}s")
    print(f"{est} sincronismo: medio {med:.3f}s  p95 {p95:.3f}s  sesgo {sesgo:+.3f}s  "
          f"PEOR TRAMO {pt['mediana']:+.3f}s en t={pt['t']}s  ({tarde} palabras >0,5 s tarde)")
    if sesgo > 0:
        print(f"{AVISO} sesgo POSITIVO: el subtítulo va por detrás de la voz (se busca negativo)")

    pausas = pausas_fuera_de_puntuacion(ass)
    print(f"{OK if not pausas else AVISO} pausas fuera de puntuación: {len(pausas)}")

    # --- basura del modelo y párrafos repetidos, sobre el guion real
    if story and os.path.exists(story):
        texto = open(story, encoding="utf-8").read()
        try:
            from modules.script_generator import _detectar_basura
            hay, motivo = _detectar_basura(texto)
            print(f"{MAL if hay else OK} basura del modelo: "
                  f"{motivo if hay else 'ninguna'}")
            if hay:
                fallos.append(f"basura del modelo: {motivo}")
        except Exception as e:
            print(f"{AVISO} no se pudo comprobar la basura: {e}")
        n_dup, largo = ngramas_repetidos(texto)
        print(f"{MAL if n_dup else OK} párrafos repetidos: {n_dup} n-gramas de 12 "
              f"(tramo más largo: {largo} palabras)")
        if n_dup:
            fallos.append(f"{largo} palabras narradas dos veces")

    # --- artefactos, duración y peso
    dur = float(_ffprobe(video, "duration")[0])
    size_gb = os.path.getsize(video) / 1024**3
    br = float(_ffprobe(video, "bit_rate")[0]) / 1e6
    w, h = _ffprobe(video, "width,height", stream=True)[:2]
    print(f"{OK} vídeo: {dur/60:.2f} min  {w}x{h}  {br:.1f} Mbps  {size_gb:.2f} GB")
    if chunk_dur:
        ratio = dur / chunk_dur
        est = OK if 0.9 <= ratio <= 1.1 else AVISO
        print(f"{est} ratio vídeo/chunk: {ratio:.3f}  "
              f"({'gameplay repetido' if ratio > 1.1 else 'gameplay desperdiciado' if ratio < 0.9 else 'ajustado'})")

    i, tp = loudness(video)
    if i is not None:
        est = OK if i >= -16 else AVISO
        pico = f", pico {tp:.1f} dBFS" if tp is not None else ""
        print(f"{est} loudness: {i:.1f} LUFS{pico}. YouTube normaliza "
              f"a -14 y SOLO BAJA: por debajo suena más flojo que la competencia")

    ass_txt = open(ass, encoding="utf-8").read()
    geo = "1920" in ass_txt.split("PlayResY")[0] and "pos(960,540)" in ass_txt
    print(f"{OK if geo else MAL} geometría: PlayRes 1920x1080 + pos(960,540)")
    if not geo:
        fallos.append("geometría de subtítulos incorrecta")
    return fallos


def audita_shorts(shorts_dir, temp_dir, n_medir=0, model="small"):
    print(f"\n=== SHORTS: {shorts_dir} ===")
    fallos = []
    titulos_f = sorted(glob.glob(os.path.join(shorts_dir, "*_title.txt")))
    mp4s = sorted(glob.glob(os.path.join(shorts_dir, "*.mp4")))
    print(f"{OK} artefactos: {len(mp4s)} mp4 y {len(titulos_f)} títulos")
    if len(mp4s) != len(titulos_f):
        fallos.append("faltan artefactos de shorts")

    titulos = [open(f, encoding="utf-8").read().strip() for f in titulos_f]
    if titulos:
        unicos = len(set(titulos))
        print(f"{OK if unicos == len(titulos) else MAL} títulos únicos: {unicos}/{len(titulos)}")
        aperturas = [t.split()[0].lower() for t in titulos if t.split()]
        distintas = len(set(aperturas))
        racha = maxracha = 1
        for a, b in zip(aperturas, aperturas[1:]):
            racha = racha + 1 if a == b else 1
            maxracha = max(maxracha, racha)
        est = OK if maxracha <= 6 else AVISO
        print(f"{est} aperturas: {distintas} palabras iniciales distintas, "
              f"racha máxima {maxracha} títulos seguidos con la misma")

    # sincronismo de una muestra de shorts (el gemelo que nadie mira)
    for mp4 in mp4s[:n_medir]:
        stem = os.path.splitext(os.path.basename(mp4))[0]
        ass = os.path.join(temp_dir, f"{stem}_subs.ass")
        if not os.path.exists(ass):
            # Nunca en silencio: un short que no se mide parece un short sano.
            print(f"{AVISO} {stem}: sin {os.path.basename(ass)}, NO se ha medido "
                  f"su sincronismo")
            continue
        aw = lee_ass(ass)
        pares = empareja(aw, transcribe(extrae_audio(mp4), model))
        if len(pares) / max(1, len(aw)) < 0.85:
            print(f"{AVISO} {stem}: emparejado bajo, sin veredicto")
            continue
        pt = peor_tramo(pares)
        errs = [e for *_, e in pares]
        med = sum(abs(e) for e in errs) / len(errs)
        est = OK if pt and abs(pt["mediana"]) <= 0.35 else MAL
        detalle = f"  peor tramo {pt['mediana']:+.3f}s" if pt else " (sin tramo medible)"
        print(f"{est} {stem}: medio {med:.3f}s{detalle}")
        if est == MAL:
            fallos.append(f"{stem} desincronizado")
    return fallos


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--output", default="./output")
    ap.add_argument("--shorts-dir", default="./shorts_tiktok")
    ap.add_argument("--temp", default="./temp")
    ap.add_argument("--shorts", type=int, default=2,
                    help="cuántos shorts medir de sincronismo (0 = ninguno)")
    ap.add_argument("--chunk-dur", type=float, help="duración del chunk, para el ratio")
    ap.add_argument("--model", default="small")
    args = ap.parse_args()

    fallos = []
    for video in sorted(glob.glob(os.path.join(args.output, "*_final.mp4"))):
        stem = os.path.basename(video)[: -len("_final.mp4")]
        ass = os.path.join(args.temp, f"{stem}_subs.ass")
        story = os.path.join(args.temp, f"{stem}_story.txt")
        if not os.path.exists(ass):
            print(f"{AVISO} sin .ass para {stem}: ¿corriste sin --keep-temp?")
            continue
        fallos += audita_video(video, ass, story, args.chunk_dur, args.model)

    fallos += audita_shorts(args.shorts_dir, args.temp, args.shorts, args.model)

    print("\n" + "=" * 62)
    if fallos:
        print(f"VEREDICTO: NO PUBLICABLE — {len(fallos)} problema(s)")
        for f in fallos:
            print(f"  - {f}")
        return 1
    print("VEREDICTO: sin defectos MEDIBLES.")
    print("Ojo: esto NO dice que sea bueno. Si la historia engancha, si la voz")
    print("suena natural y si la miniatura llama, eso lo juzga Diego.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
