"""Reconocimiento de acordes con librosa: chroma CQT + plantillas de acordes.

No requiere compilar nada (madmom sí). Reconoce tríadas y séptimas
(mayor, menor, de dominante y maj7/m7). Las extensiones (9, 11, 13) y
las alteraciones se pierden, pero sirve para cifrado básico.
"""
from pathlib import Path

import librosa
import numpy as np

SR = 22050
HOP = 2048
NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# (sufijo del nombre, intervalos desde la raíz en semitonos)
QUALITIES = [
    ("", (0, 4, 7)),           # mayor
    ("m", (0, 3, 7)),          # menor
    ("7", (0, 4, 7, 10)),      # dominante
    ("maj7", (0, 4, 7, 11)),   # mayor con séptima mayor
    ("m7", (0, 3, 7, 10)),     # menor con séptima menor
]


def _build_templates() -> tuple[np.ndarray, list[str]]:
    """Plantillas normalizadas (5 calidades x 12 raíces) y sus nombres."""
    templates, names = [], []
    for suffix, intervals in QUALITIES:
        for root in range(12):
            vec = np.zeros(12)
            for interval in intervals:
                vec[(root + interval) % 12] = 1.0
            templates.append(vec / np.linalg.norm(vec))
            names.append(NOTE_NAMES[root] + suffix)
    return np.array(templates), names


TEMPLATES, CHORD_NAMES = _build_templates()


MAJOR_SCALE = (0, 2, 4, 5, 7, 9, 11)
MINOR_SCALE = (0, 2, 3, 5, 7, 8, 10)
FLAT_TO_SHARP = {"Db": "C#", "Eb": "D#", "Gb": "F#", "Ab": "G#", "Bb": "A#"}


def _parse_key(key: str) -> tuple[int, bool]:
    """'C' -> (0, False), 'Am' -> (9, True), 'Bb' -> (10, False)."""
    name = key.strip()
    minor = name.endswith("m")
    root_name = name[:-1] if minor else name
    root_name = FLAT_TO_SHARP.get(root_name, root_name)
    if root_name not in NOTE_NAMES:
        raise ValueError(f"Tonalidad no válida: {key!r} (ejemplos: C, Am, F#m, Bb)")
    return NOTE_NAMES.index(root_name), minor


def _diatonic_chords(key: str) -> set[str]:
    """Nombres de acordes que pertenecen a la tonalidad (triadas y séptimas simples)."""
    tonic, minor = _parse_key(key)
    scale = [(tonic + i) % 12 for i in (MINOR_SCALE if minor else MAJOR_SCALE)]
    names = set()
    for degree in range(7):
        root = scale[degree]
        third = (scale[(degree + 2) % 7] - root) % 12
        fifth = (scale[(degree + 4) % 7] - root) % 12
        seventh = (scale[(degree + 6) % 7] - root) % 12
        if third == 4 and fifth == 7:
            triad, sevenths = "", {10: "7", 11: "maj7"}
        elif third == 3 and fifth == 7:
            triad, sevenths = "m", {10: "m7"}
        else:
            continue  # disminuido: no se reconoce en las plantillas
        names.add(NOTE_NAMES[root] + triad)
        if seventh in sevenths:
            names.add(NOTE_NAMES[root] + sevenths[seventh])
    return names


def _viterbi(scores: np.ndarray, stay_prob: float, temperature: float) -> np.ndarray:
    """Secuencia de estados más probable para cada frame.

    scores: (estados, frames) con similitud entre 0 y 1.
    stay_prob: probabilidad de seguir en el mismo acorde de un frame al siguiente.
    temperature: qué tanto pesa la similitud frente a la penalización por cambiar.
    """
    n_states, n_frames = scores.shape
    log_emit = temperature * scores

    log_switch = np.log((1 - stay_prob) / (n_states - 1))
    trans = np.full((n_states, n_states), log_switch)
    np.fill_diagonal(trans, np.log(stay_prob))

    dp = np.zeros((n_states, n_frames))
    back = np.zeros((n_states, n_frames), dtype=int)
    dp[:, 0] = log_emit[:, 0]
    for t in range(1, n_frames):
        candidates = dp[:, t - 1][:, None] + trans  # (desde, hasta)
        back[:, t] = candidates.argmax(axis=0)
        dp[:, t] = candidates.max(axis=0) + log_emit[:, t]

    path = np.zeros(n_frames, dtype=int)
    path[-1] = dp[:, -1].argmax()
    for t in range(n_frames - 1, 0, -1):
        path[t - 1] = back[path[t], t]
    return path


def detect_chords_template(
    audio: Path,
    key: str | None = None,
    key_bonus: float = 0.1,
    min_duration: float = 0.3,
    stay_prob: float = 0.9,
    temperature: float = 20.0,
    silence_ratio: float = 0.02,
    max_gap: float = 0.2,
) -> list[dict]:
    """Devuelve [{'start', 'end', 'chord'}] con la secuencia más probable.

    key: tonalidad conocida ('C', 'Am', 'F#m'...). Si se da, los acordes de la
         escala reciben un bono de similitud (key_bonus).
    stay_prob: qué tan estable es el acorde de un frame al siguiente (Viterbi).
    temperature: peso de la similitud con las plantillas frente a los cambios.
    silence_ratio: frames con RMS menor a esta fracción del máximo se ignoran.
    max_gap: pausa (s) máxima entre dos segmentos del mismo acorde para fusionarlos.
    """
    y, sr = librosa.load(str(audio), sr=SR, mono=True)

    chroma = librosa.feature.chroma_cqt(y=y, sr=sr, hop_length=HOP)
    rms = librosa.feature.rms(y=y, hop_length=HOP)[0]
    n = min(chroma.shape[1], len(rms))
    chroma, rms = chroma[:, :n], rms[:n]

    # Normalizar cada frame: solo importa la proporción entre notas, no el volumen
    norm = chroma / (np.linalg.norm(chroma, axis=0, keepdims=True) + 1e-9)

    scores = TEMPLATES @ norm  # (60, frames)
    if key is not None:
        diatonic = np.array([name in _diatonic_chords(key) for name in CHORD_NAMES], dtype=float)
        scores = scores + key_bonus * diatonic[:, None]
    labels = _viterbi(scores, stay_prob=stay_prob, temperature=temperature)

    silent = rms < silence_ratio * rms.max()
    frame_dur = HOP / sr

    # Segmentos por frame; los silencios quedan con chord=None
    chords: list[dict] = []
    for i in range(n):
        name = None if silent[i] else CHORD_NAMES[labels[i]]
        t0 = i * frame_dur
        t1 = t0 + frame_dur
        if chords and chords[-1]["chord"] == name:
            chords[-1]["end"] = t1
        else:
            chords.append({"start": t0, "end": t1, "chord": name})

    # Fusionar el mismo acorde cuando lo separa solo una pausa corta
    voiced = [c for c in chords if c["chord"] is not None]
    merged: list[dict] = []
    for c in voiced:
        if (
            merged
            and merged[-1]["chord"] == c["chord"]
            and c["start"] - merged[-1]["end"] <= max_gap
        ):
            merged[-1]["end"] = c["end"]
        else:
            merged.append(dict(c))

    return [c for c in merged if (c["end"] - c["start"]) >= min_duration]


def detect_chords(audio: Path, engine: str = "btc", key: str | None = None) -> list[dict]:
    """Detecta acordes con el motor elegido.

    engine: 'btc' (modelo preentrenado, recomendado) o 'template' (plantillas
            con librosa, sin descargas; admite key).
    key: solo la usa el motor 'template'.
    """
    if engine == "btc":
        if key is not None:
            print("      [aviso] --key solo se usa con el motor 'template'; BTC la ignora.")
        from .chords_btc import detect_chords_btc
        return detect_chords_btc(audio)
    if engine == "template":
        return detect_chords_template(audio, key=key)
    raise ValueError(f"Motor de acordes desconocido: {engine!r} (usa 'btc' o 'template')")
