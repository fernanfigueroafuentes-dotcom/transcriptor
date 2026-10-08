"""Separación voz / instrumental con Demucs."""
import subprocess
import sys
from pathlib import Path


def separate_vocals(audio: Path, out_dir: Path, model: str = "htdemucs") -> tuple[Path, Path]:
    """Separa la voz del resto. Devuelve (vocals.wav, no_vocals.wav)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    stem_dir = out_dir / model / audio.stem
    vocals, rest = stem_dir / "vocals.wav", stem_dir / "no_vocals.wav"
    if (
        vocals.is_file() and rest.is_file()
        and min(vocals.stat().st_mtime, rest.stat().st_mtime) > audio.stat().st_mtime
    ):
        print("      Separación ya existente: se reutiliza.")
        return vocals, rest

    cmd = [
        sys.executable, "-m", "demucs",
        "--two-stems", "vocals",
        "-n", model,
        "-o", str(out_dir),
        str(audio),
    ]
    subprocess.run(cmd, check=True)
    return vocals, rest
