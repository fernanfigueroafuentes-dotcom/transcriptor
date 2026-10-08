"""Reconocimiento de acordes con BTC (Bi-directional Transformer for Chord Recognition, ISMIR 2019).

Modelo y pesos: https://huggingface.co/puar-playground/btc-chord (MIT), basado en
https://github.com/jayg996/BTC-ISMIR19. Los archivos están en third_party/btc_chord,
fijados a la revisión d436f2f664f5107cd987774279b8ce171846e376. No se usa
trust_remote_code: solo se importan las clases del modelo (btc_src) y los pesos
se cargan con weights_only=True, permitiendo únicamente los tipos de numpy
que contiene el checkpoint.

El vocabulario grande (170 acordes) incluye séptimas, dim, aug, sus y sextas.
"""
import _codecs
import importlib
import sys
import warnings
from functools import lru_cache
from pathlib import Path

import librosa
import numpy as np
import torch

BTC_DIR = Path(__file__).resolve().parent.parent / "third_party" / "btc_chord"
CHECKPOINT = "btc_model_large_voca.pt"
TARGET_PEAK = 0.9  # nivel de pico al que se normaliza el audio de entrada
NON_CHORD = [168, 169]  # índices de 'X' y 'N' en el vocabulario grande

# Hiperparámetros del modelo original (run_config.yaml)
MODEL_CFG = dict(
    feature_size=144, timestep=108,
    input_dropout=0.2, layer_dropout=0.2, attention_dropout=0.2, relu_dropout=0.2,
    num_layers=8, num_heads=4, hidden_size=128,
    total_key_depth=128, total_value_depth=128, filter_size=128,
    loss="ce", probs_out=False, num_chords=170,
)
FEATURE_CFG = dict(sr_target=22050, inst_len=10.0, n_bins=144, bins_per_octave=24, hop_length=2048)
TIMESTEP = MODEL_CFG["timestep"]

# Calidades de BTC (notación Harte) -> sufijo de cifrado
QUALITY_SUFFIX = {
    "maj": "", "min": "m", "7": "7", "maj7": "maj7", "min7": "m7",
    "dim": "dim", "dim7": "dim7", "hdim7": "m7b5", "aug": "aug",
    "sus2": "sus2", "sus4": "sus4", "maj6": "6", "min6": "m6", "minmaj7": "m(maj7)",
}


def _to_name(label: str) -> str | None:
    """'C:min' -> 'Cm', 'A#:maj7' -> 'A#maj7', 'C' -> 'C', 'N'/'X' -> None."""
    if label in ("N", "X"):
        return None
    root, _, quality = label.partition(":")
    return root + QUALITY_SUFFIX.get(quality, quality)


@lru_cache(maxsize=2)
def _load(device: str):
    if not (BTC_DIR / CHECKPOINT).is_file():
        raise FileNotFoundError(f"Falta el modelo BTC en {BTC_DIR}")
    if str(BTC_DIR) not in sys.path:
        sys.path.insert(0, str(BTC_DIR))
    BTC_model = importlib.import_module("btc_src.btc_model").BTC_model
    features = importlib.import_module("btc_src.features")

    model = BTC_model(config=MODEL_CFG).to(device)
    allowed = [
        np.core.multiarray.scalar, np.dtype, _codecs.encode,
        np.dtypes.Float64DType, np.dtypes.Float32DType,
    ]
    with torch.serialization.safe_globals(allowed):
        ckpt = torch.load(str(BTC_DIR / CHECKPOINT), map_location=device, weights_only=True)
    model.load_state_dict(ckpt["model"])
    model.eval()
    return model, features, ckpt["mean"], ckpt["std"], features.idx2voca_chord()


@torch.no_grad()
def detect_chords_btc(
    audio: Path,
    min_duration: float = 0.5,
    max_gap: float = 0.6,
    silence_ratio: float = 0.02,
    device: str | None = None,
) -> list[dict]:
    """Devuelve [{'start', 'end', 'chord'}] con acordes de BTC.

    silence_ratio: frames con RMS menor a esta fracción del máximo cuentan como silencio.
    """
    device = device or ("cuda" if torch.cuda.is_available() else "cpu")
    model, features, mean, std, idx_to_chord = _load(device)

    # BTC se entrenó con música masterizada: una grabación baja se lee como silencio.
    # Normalizar el pico a un nivel típico antes de calcular el CQT.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # librosa avisa al caer a audioread con m4a
        wav, _ = librosa.load(str(audio), sr=FEATURE_CFG["sr_target"], mono=True)
    peak = float(np.abs(wav).max())
    if peak > 0:
        wav = wav * (TARGET_PEAK / peak)

    feat = features.audio_to_features(wav, **FEATURE_CFG)  # [n_bins, T]
    feat = ((feat.T - mean) / std).astype(np.float32)             # [T, n_bins]
    n_frames = feat.shape[0]
    feat = np.pad(feat, ((0, (-n_frames) % TIMESTEP), (0, 0)))

    x = torch.from_numpy(feat).unsqueeze(0).to(device)
    preds = []
    for t in range(feat.shape[0] // TIMESTEP):
        attn_out, _ = model.self_attn_layers(x[:, TIMESTEP * t:TIMESTEP * (t + 1), :])
        logits = model.output_layer.output_projection(attn_out)  # [1, TIMESTEP, 170]
        logits[..., NON_CHORD] = -torch.inf  # 'N' y 'X' solo se deciden por silencio real
        preds.append(logits.argmax(dim=-1).squeeze(0).cpu().numpy())
    labels = np.concatenate(preds)[:n_frames]

    # Silencio real: frames con energía muy baja respecto al máximo del audio
    rms = librosa.feature.rms(y=wav, hop_length=FEATURE_CFG["hop_length"])[0]
    silent_below = silence_ratio * rms.max()

    time_unit = FEATURE_CFG["inst_len"] / TIMESTEP
    frames_per_rms = FEATURE_CFG["hop_length"] / FEATURE_CFG["sr_target"]
    segments: list[dict] = []
    for i, idx in enumerate(labels):
        t0 = i * time_unit
        rms_idx = min(int(t0 / frames_per_rms), len(rms) - 1)
        silent = rms[rms_idx] < silent_below
        name = None if silent else _to_name(idx_to_chord[int(idx)])
        if segments and segments[-1]["chord"] == name:
            segments[-1]["end"] = t0 + time_unit
        else:
            segments.append({"start": t0, "end": t0 + time_unit, "chord": name})

    # Quitar silencios y segmentos demasiado cortos (parpadeos), y luego fusionar
    # el mismo acorde que quedó separado por el hueco que dejaron.
    voiced = [
        s for s in segments
        if s["chord"] is not None and (s["end"] - s["start"]) >= min_duration
    ]
    merged: list[dict] = []
    for seg in voiced:
        if (
            merged
            and merged[-1]["chord"] == seg["chord"]
            and seg["start"] - merged[-1]["end"] <= max_gap
        ):
            merged[-1]["end"] = seg["end"]
        else:
            merged.append(dict(seg))
    return merged
