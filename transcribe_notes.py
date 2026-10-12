"""Transcribe las notas de los instrumentos de una canción ya procesada.

    python transcribe_notes.py light_as_a_feather
    python transcribe_notes.py light_as_a_feather --stems guitar,piano --mono guitar
    python transcribe_notes.py light_as_a_feather --stems other --force

Pistas disponibles: guitar, piano, bass, other (sintetizadores, vientos, cuerdas...) y vocals.
Genera songs/<cancion>/notes.json (para el visor) y songs/<cancion>/midi/<pista>.mid.
--mono deja una sola nota a la vez (útil para solos de una línea).
"""
import argparse
from pathlib import Path

from core.notes import TRANSCRIBIBLES, transcribe_song


def main() -> None:
    parser = argparse.ArgumentParser(description="Transcripción de notas por instrumento.")
    parser.add_argument("song", help="Id de la canción (carpeta dentro de songs/) o ruta a su carpeta")
    parser.add_argument("--stems", default="guitar,piano,bass,other",
                        help=f"Pistas a transcribir, separadas por comas ({', '.join(TRANSCRIBIBLES)})")
    parser.add_argument("--mono", default="bass",
                        help="Pistas de una sola voz (una nota a la vez), separadas por comas")
    parser.add_argument("--songs-dir", type=Path, default=Path("songs"))
    parser.add_argument("--force", action="store_true", help="Repetir pistas ya transcritas")
    parser.add_argument("--strength", type=float, default=1.0,
                        help="Dureza de la depuración: >1 quita más ruido, <1 conserva más notas (def. 1)")
    parser.add_argument("--refine-only", action="store_true",
                        help="Reaplicar solo la depuración a las notas crudas guardadas (rápido, sin el modelo)")
    parser.add_argument("--onset", type=float, default=0.5, help="Umbral de ataque del modelo (0-1; def. 0.5)")
    parser.add_argument("--frame", type=float, default=0.3, help="Umbral de nota sostenida del modelo (0-1; def. 0.3)")
    args = parser.parse_args()

    song_dir = Path(args.song)
    if not song_dir.is_dir():
        song_dir = args.songs_dir / args.song
    if not song_dir.is_dir():
        raise SystemExit(f"No existe la canción: {args.song}")

    split = lambda text: tuple(s.strip() for s in text.split(",") if s.strip())  # noqa: E731
    transcribe_song(song_dir, stems=split(args.stems), mono_stems=split(args.mono), force=args.force,
                    strength=args.strength, refine_only=args.refine_only,
                    onset_threshold=args.onset, frame_threshold=args.frame)


if __name__ == "__main__":
    main()
