"""Uso desde terminal:

    python cli.py cancion.mp3
    python cli.py cancion.mp3 --lyrics letra.txt
    python cli.py cancion.mp3 --no-separate
    python cli.py cancion.mp3 --key C
"""
import argparse
from pathlib import Path

from core.pipeline import process


def main() -> None:
    parser = argparse.ArgumentParser(description="Acordes y letra a partir de un audio.")
    parser.add_argument("audio", type=Path, help="Archivo de audio (mp3, wav, flac...)")
    parser.add_argument("--lyrics", type=Path, default=None,
                        help="Archivo .txt con tu letra para alinearla al audio")
    parser.add_argument("--no-separate", action="store_true",
                        help="No separar voz (más rápido; la letra no se transcribe)")
    parser.add_argument("--model", default="large-v3",
                        help="Modelo Whisper: large-v3, medium, small... (default: large-v3)")
    parser.add_argument("--out", type=Path, default=Path("songs"),
                        help="Carpeta de salida (default: songs)")
    parser.add_argument("--engine", choices=["btc", "template"], default="btc",
                        help="Motor de acordes: btc (modelo preentrenado, default) o template")
    parser.add_argument("--key", default=None,
                        help="Tonalidad conocida (C, Am, F#m, Bb...). Solo con --engine template")
    args = parser.parse_args()

    process(
        audio=args.audio,
        lyrics_file=args.lyrics,
        out_root=args.out,
        separate=not args.no_separate,
        whisper_model=args.model,
        key=args.key,
        chord_engine=args.engine,
    )


if __name__ == "__main__":
    main()
