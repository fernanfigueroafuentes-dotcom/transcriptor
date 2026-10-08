"""Orquesta el procesamiento completo de una canción."""
import json
import re
import shutil
from pathlib import Path

from . import chords as chords_mod
from . import lyrics as lyrics_mod
from . import separate as separate_mod
from .merge import to_chordpro


def _device() -> str:
    import torch
    return "cuda" if torch.cuda.is_available() else "cpu"


def _slug(name: str) -> str:
    return re.sub(r"[^\w-]+", "_", name).strip("_").lower()


def process(
    audio: Path,
    lyrics_file: Path | None = None,
    out_root: Path = Path("songs"),
    separate: bool = True,
    whisper_model: str = "large-v3",
    key: str | None = None,
    chord_engine: str = "btc",
) -> Path:
    """Procesa un audio y escribe chords.json, lyrics.json y song.chordpro.

    key: tonalidad conocida ('C', 'Am'...) para favorecer los acordes de la escala.
    Devuelve la carpeta de la canción.
    """
    audio = audio.resolve()
    song_dir = out_root / _slug(audio.stem)
    song_dir.mkdir(parents=True, exist_ok=True)

    # Copia del audio y metadatos para el visor web
    audio_copy = song_dir / f"audio{audio.suffix.lower()}"
    if not audio_copy.exists() or audio_copy.stat().st_size != audio.stat().st_size:
        shutil.copy2(audio, audio_copy)
    (song_dir / "meta.json").write_text(
        json.dumps({"title": audio.stem, "audio": audio_copy.name}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    device = _device()
    print(f"[info] dispositivo: {device}")

    # 1. Separación voz / instrumental
    if separate:
        print("[1/4] Separando voz e instrumental (Demucs)...")
        vocals, instrumental = separate_mod.separate_vocals(audio, song_dir / "stems")
    else:
        print("[1/4] Sin separación: se usa el audio completo.")
        vocals, instrumental = None, audio

    # 2. Acordes (sobre el instrumental si existe, para que la voz no confunda)
    print(f"[2/4] Detectando acordes (motor: {chord_engine})...")
    chord_list = chords_mod.detect_chords(instrumental, engine=chord_engine, key=key)
    (song_dir / "chords.json").write_text(
        json.dumps(chord_list, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # 3. Letra: transcripción de la voz, y alineación de la letra propia si la hay
    if vocals is None:
        print("[3/4] Sin pista de voz: no se puede transcribir la letra.")
        lines = []
    else:
        print(f"[3/4] Transcribiendo voz con Whisper ({whisper_model})...")
        words = lyrics_mod.transcribe_words(
            vocals, model_name=whisper_model, device=device,
            compute_type="int8_float16" if device == "cuda" else "int8",
        )
        if lyrics_file:
            print("      Alineando tu letra con el audio...")
            user_text = lyrics_file.read_text(encoding="utf-8")
            lines = lyrics_mod.align_user_lyrics(user_text, words)
        else:
            lines = lyrics_mod.lines_from_words(words)

    (song_dir / "lyrics.json").write_text(
        json.dumps(lines, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # 4. Fusión a ChordPro
    print("[4/4] Generando song.chordpro...")
    chordpro = to_chordpro(lines, chord_list, title=audio.stem)
    out_file = song_dir / "song.chordpro"
    out_file.write_text(chordpro, encoding="utf-8")

    print(f"Listo: {out_file}")
    return song_dir
