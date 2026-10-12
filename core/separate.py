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


# Pistas del modelo de 6 fuentes de Demucs
STEMS_6 = ("vocals", "drums", "bass", "guitar", "piano", "other")


def separate_all_stems(audio: Path, out_dir: Path, model: str = "htdemucs_6s") -> dict[str, Path]:
    """Separa en voz, batería, bajo, guitarra, piano y otros. Devuelve {pista: wav}."""
    out_dir.mkdir(parents=True, exist_ok=True)
    stem_dir = out_dir / model / audio.stem
    paths = {name: stem_dir / f"{name}.wav" for name in STEMS_6}
    if all(p.is_file() and p.stat().st_mtime > audio.stat().st_mtime for p in paths.values()):
        print("      Pistas ya separadas: se reutilizan.")
        return paths

    cmd = [sys.executable, "-m", "demucs", "-n", model, "-o", str(out_dir), str(audio)]
    subprocess.run(cmd, check=True)
    return paths
