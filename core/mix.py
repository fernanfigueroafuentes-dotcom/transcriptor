"""Pistas comprimidas para el mezclador del visor.

Demucs deja WAV enormes (≈110 MB por pista en una canción de 4 min). Para el mezclador se
convierten a AAC (.m4a, ≈5 MB por pista), que todos los navegadores reproducen y que se pueden
subir al servidor sin problema:

    songs/<canción>/mix/<pista>.m4a   y   songs/<canción>/mix/mix.json

Se usan las 6 pistas (htdemucs_6s) si existen; si no, voz + acompañamiento (htdemucs, 2 pistas).
Necesita ffmpeg en el PATH (solo donde se procesa; el visor solo sirve los .m4a).
"""
import json
import shutil
import subprocess
from pathlib import Path

from .separate import STEMS_6

MIX_DIR = "mix"
BITRATE = "128k"
# Orden y nombre de las pistas en el mezclador
LABELS = {
    "vocals": "Voz", "drums": "Batería", "bass": "Bajo", "guitar": "Guitarra",
    "piano": "Piano", "other": "Otros", "accompaniment": "Acompañamiento",
}


def find_stems(song_dir: Path) -> tuple[str, dict[str, Path]]:
    """Busca las pistas separadas de una canción. Devuelve (origen, {pista: wav})."""
    for folder in sorted((song_dir / "stems6").glob("*/*")):
        paths = {name: folder / f"{name}.wav" for name in STEMS_6}
        if all(p.is_file() for p in paths.values()):
            return "htdemucs_6s", paths
    for folder in sorted((song_dir / "stems").glob("*/*")):
        vocals, rest = folder / "vocals.wav", folder / "no_vocals.wav"
        if vocals.is_file() and rest.is_file():
            return "htdemucs", {"vocals": vocals, "accompaniment": rest}
    return "", {}


def _encode(wav: Path, out: Path) -> None:
    tmp = out.with_suffix(".tmp.m4a")
    subprocess.run(
        ["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", str(wav),
         "-vn", "-c:a", "aac", "-b:a", BITRATE, "-movflags", "+faststart", str(tmp)],
        check=True,
    )
    tmp.replace(out)


def prepare_mix(song_dir: Path, force: bool = False) -> dict | None:
    """Crea mix/<pista>.m4a y mix/mix.json. Devuelve el índice, o None si no hay pistas separadas."""
    song_dir = Path(song_dir)
    source, wavs = find_stems(song_dir)
    if not wavs:
        print("      Mezclador: no hay pistas separadas (ejecuta transcribe_notes.py o cli.py sin --no-separate).")
        return None
    if shutil.which("ffmpeg") is None:
        print("      Mezclador: falta ffmpeg en el PATH; no se crean las pistas comprimidas.")
        return None

    out_dir = song_dir / MIX_DIR
    index_file = out_dir / "mix.json"
    old = json.loads(index_file.read_text(encoding="utf-8")) if index_file.is_file() else {}
    if old.get("source") == "htdemucs_6s" and source != "htdemucs_6s":
        return old                                        # ya hay una mezcla de 6 pistas, mejor
    out_dir.mkdir(exist_ok=True)
    if old.get("source") and old.get("source") != source:
        for leftover in out_dir.glob("*.m4a"):            # p. ej. de 2 a 6 pistas
            leftover.unlink()

    stems = []
    for name in sorted(wavs, key=lambda s: list(LABELS).index(s)):
        out = out_dir / f"{name}.m4a"
        if force or not out.is_file() or out.stat().st_mtime < wavs[name].stat().st_mtime:
            print(f"      Mezclador: comprimiendo {name}...")
            _encode(wavs[name], out)
        stems.append({"id": name, "label": LABELS[name]})

    index = {"version": 1, "source": source, "stems": stems}
    index_file.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    size = sum((out_dir / f"{s['id']}.m4a").stat().st_size for s in stems) / 1e6
    print(f"      Mezclador listo: {len(stems)} pistas, {size:.0f} MB en {out_dir}")
    return index
