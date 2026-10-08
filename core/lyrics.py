"""Letra: transcripción de la voz con WhisperX y alineación de una letra propia."""
import difflib
import re
from pathlib import Path


def normalize(token: str) -> str:
    return re.sub(r"[^\w]", "", token.lower())


def transcribe_words(
    vocals: Path,
    model_name: str = "large-v3",
    device: str = "cuda",
    compute_type: str = "int8_float16",
    batch_size: int = 8,
) -> list[dict]:
    """Transcribe la voz y devuelve palabras con tiempos: [{'word', 'start', 'end'}]."""
    import gc

    import torch
    import whisperx
    from faster_whisper import WhisperModel

    audio = whisperx.load_audio(str(vocals))

    # Se usa faster-whisper directo (con su VAD Silero) en lugar de whisperx.load_model,
    # que carga un detector pyannote rechazado por torch.load(weights_only=True).
    model = WhisperModel(model_name, device=device, compute_type=compute_type)
    segments_iter, info = model.transcribe(
        audio,
        beam_size=5,
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=500),
        condition_on_previous_text=False,
    )
    segments = [
        {"text": s.text.strip(), "start": s.start, "end": s.end} for s in segments_iter
    ]
    print(f"      idioma detectado: {info.language}")
    del model
    gc.collect()
    if device == "cuda":
        torch.cuda.empty_cache()

    align_model, metadata = whisperx.load_align_model(
        language_code=info.language, device=device
    )
    aligned = whisperx.align(
        segments, align_model, metadata, audio, device,
        return_char_alignments=False,
    )

    words = []
    for segment in aligned["segments"]:
        for w in segment.get("words", []):
            if "start" in w and "end" in w:
                words.append({
                    "word": w["word"].strip(),
                    "start": float(w["start"]),
                    "end": float(w["end"]),
                })
    return words


def lines_from_words(words: list[dict], gap: float = 0.5, max_words: int = 10) -> list[dict]:
    """Agrupa palabras transcritas en líneas: corta en pausas o al llegar a max_words."""
    lines: list[dict] = []
    current: list[dict] = []
    prev_end = None
    for w in words:
        pause = prev_end is not None and w["start"] - prev_end > gap
        if current and (pause or len(current) >= max_words):
            lines.append(_make_line(current))
            current = []
        current.append({"word": w["word"], "start": w["start"]})
        prev_end = w["end"]
    if current:
        lines.append(_make_line(current))
    return lines


def _make_line(tokens: list[dict]) -> dict:
    return {"text": " ".join(t["word"] for t in tokens), "tokens": tokens}


def align_user_lyrics(user_text: str, words: list[dict]) -> list[dict]:
    """Asigna tiempos a una letra propia usando las palabras transcritas como ancla.

    Las palabras que no coinciden con la transcripción reciben un tiempo
    interpolado entre las palabras ancladas vecinas.
    """
    lines = [l.strip() for l in user_text.splitlines() if l.strip()]

    tokens: list[tuple[int, str]] = []  # (índice de línea, palabra)
    for i, line in enumerate(lines):
        for tok in line.split():
            tokens.append((i, tok))

    user_norm = [normalize(t) for _, t in tokens]
    asr_norm = [normalize(w["word"]) for w in words]

    times: list[float | None] = [None] * len(tokens)
    matcher = difflib.SequenceMatcher(None, user_norm, asr_norm, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal" or (tag == "replace" and (i2 - i1) == (j2 - j1)):
            for k in range(i2 - i1):
                times[i1 + k] = words[j1 + k]["start"]

    _interpolate_missing(times)

    result = []
    for i, line in enumerate(lines):
        line_tokens = [
            {"word": t, "start": times[idx]}
            for idx, (line_idx, t) in enumerate(tokens)
            if line_idx == i
        ]
        result.append({"text": line, "tokens": line_tokens})
    return result


def _interpolate_missing(times: list[float | None]) -> None:
    n = len(times)
    known = [i for i, t in enumerate(times) if t is not None]
    if not known:
        for i in range(n):
            times[i] = 0.0
        return
    for i in range(n):
        if times[i] is not None:
            continue
        prev_idx = max((k for k in known if k < i), default=None)
        next_idx = min((k for k in known if k > i), default=None)
        if prev_idx is None:
            times[i] = times[next_idx]
        elif next_idx is None:
            times[i] = times[prev_idx]
        else:
            t0, t1 = times[prev_idx], times[next_idx]
            frac = (i - prev_idx) / (next_idx - prev_idx)
            times[i] = t0 + (t1 - t0) * frac
