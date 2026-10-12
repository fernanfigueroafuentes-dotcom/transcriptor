"""Prepara las pistas comprimidas del mezclador de una canción ya procesada.

    python prepare_mix.py light_as_a_feather
    python prepare_mix.py junior_h_-_mientras_duermes --six    # separa antes en 6 pistas (Demucs)

Usa las 6 pistas (voz, batería, bajo, guitarra, piano, otros) si ya existen; si no, voz +
acompañamiento. Crea songs/<canción>/mix/*.m4a (requiere ffmpeg).
"""
import argparse
from pathlib import Path

from core.mix import prepare_mix


def main() -> None:
    parser = argparse.ArgumentParser(description="Pistas comprimidas para el mezclador del visor.")
    parser.add_argument("song", help="Id de la canción (carpeta dentro de songs/) o ruta a su carpeta")
    parser.add_argument("--six", action="store_true", help="Separar antes en 6 pistas si no existen (usa la GPU)")
    parser.add_argument("--force", action="store_true", help="Volver a comprimir aunque ya existan")
    parser.add_argument("--songs-dir", type=Path, default=Path("songs"))
    args = parser.parse_args()

    song_dir = Path(args.song)
    if not song_dir.is_dir():
        song_dir = args.songs_dir / args.song
    if not song_dir.is_dir():
        raise SystemExit(f"No existe la canción: {args.song}")
    if args.six:
        from core.notes import _song_audio
        from core.separate import separate_all_stems
        print("Separando en 6 pistas (Demucs)...")
        separate_all_stems(_song_audio(song_dir), song_dir / "stems6")
    if prepare_mix(song_dir, force=args.force) is None:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
