"""Transcripción de notas (altura, inicio y duración) de las pistas de una canción.

Flujo: audio de la canción -> Demucs de 6 pistas -> Basic Pitch (motor ONNX) por pista ->
notas crudas (notes_raw.json) -> depuración por instrumento (refine) -> notes.json (para el visor)
y un archivo .mid por pista.

Una nota es [inicio_s, fin_s, altura_midi, velocidad]. Basic Pitch es un modelo de uso general:
funciona bien con instrumentos de una sola voz y con piano, y peor con mezclas densas. Como las
notas crudas se guardan, la depuración se puede reajustar al instante (--refine-only) sin repetir
el modelo.
"""
import json
from pathlib import Path

from web.midi import write_midi

from .mix import prepare_mix
from .separate import STEMS_6, separate_all_stems

# Rango de frecuencias (Hz) razonable por pista: descarta notas imposibles para ese instrumento
FREQ_RANGE = {
    "bass": (30.0, 450.0),
    "guitar": (75.0, 1400.0),
    "piano": (27.0, 4200.0),
    "other": (60.0, 2200.0),
    "vocals": (80.0, 1100.0),
}
# Programa MIDI por pista, para que el archivo suene con un timbre parecido
PROGRAM = {"bass": 33, "guitar": 27, "piano": 0, "other": 80, "vocals": 52}
TRANSCRIBIBLES = tuple(s for s in STEMS_6 if s != "drums")    # la batería no tiene alturas

# Perfil de depuración por pista (se aplica sobre las notas crudas del modelo)
PROFILES = {
    "bass":   {"min_dur": 0.08, "min_vel": 30, "merge_gap": 0.06, "ghosts": True, "max_poly": 1},
    "guitar": {"min_dur": 0.07, "min_vel": 25, "merge_gap": 0.05, "ghosts": True, "max_poly": 6},
    "piano":  {"min_dur": 0.06, "min_vel": 20, "merge_gap": 0.04, "ghosts": True, "max_poly": 10},
    "other":  {"min_dur": 0.08, "min_vel": 30, "merge_gap": 0.05, "ghosts": True, "max_poly": 6},
    "vocals": {"min_dur": 0.10, "min_vel": 30, "merge_gap": 0.08, "ghosts": False, "max_poly": 1},
}
GHOST_INTERVALS = (12, 19, 24)      # octava, doceava y doble octava sobre una nota más fuerte


def to_monophonic(notes, same_onset: float = 0.03):
    """Deja una sola nota a la vez, como en un solo de una línea.

    Si dos notas empiezan casi a la vez se queda la más fuerte; si una empieza antes de que
    acabe la anterior, la anterior se acorta.
    """
    out = []
    for note in sorted(notes, key=lambda n: (n[0], -n[3])):
        if out and note[0] - out[-1][0] < same_onset:
            continue                                  # mismo ataque: ya está la más fuerte
        if out and note[0] < out[-1][1]:
            out[-1][1] = note[0]                      # la anterior termina donde empieza esta
        out.append(list(note))
    return [n for n in out if n[1] - n[0] >= 0.04]


def _merge_split_notes(notes, gap):
    """Une notas de la misma altura separadas por un hueco mínimo (una nota partida en dos)."""
    notes = sorted(notes, key=lambda n: (n[2], n[0]))
    merged = []
    for n in notes:
        prev = merged[-1] if merged and merged[-1][2] == n[2] else None
        if prev and n[0] - prev[1] <= gap:
            prev[1] = max(prev[1], n[1])
            prev[3] = max(prev[3], n[3])
        else:
            merged.append(n)
    return merged


def _drop_ghosts(notes):
    """Quita armónicos: una nota a 12/19/24 semitonos sobre otra mucho más fuerte que suena a la vez."""
    notes = sorted(notes, key=lambda n: n[0])
    keep = []
    for i, n in enumerate(notes):
        ghost = False
        for m in notes[max(0, i - 40):i + 40]:                  # vecinos en el tiempo
            if m is n or abs(m[0] - n[0]) > 0.05:
                continue
            if (n[2] - m[2]) in GHOST_INTERVALS and m[3] >= n[3] * 1.5 and m[1] >= n[1] - 0.05:
                ghost = True
                break
        if not ghost:
            keep.append(n)
    return keep


def _limit_polyphony(notes, max_poly):
    """Como mucho `max_poly` notas a la vez: si hay más, se queda la más fuerte."""
    notes = sorted(notes, key=lambda n: (n[0], -n[3]))
    out, active = [], []
    for n in notes:
        active = [a for a in active if a[1] > n[0]]
        if len(active) >= max_poly:
            weakest = min(active, key=lambda a: a[3])
            if weakest[3] >= n[3]:
                continue
            weakest[1] = n[0]
            active.remove(weakest)
        active.append(n)
        out.append(n)
    return [n for n in out if n[1] - n[0] >= 0.03]


def refine(notes, stem: str, strength: float = 1.0):
    """Depura las notas crudas: quita ruido y arregla la fragmentación típica de Basic Pitch.

    1. Descarta notas muy cortas o muy débiles.
    2. Une notas de la misma altura separadas por un hueco mínimo.
    3. Quita armónicos fantasma (octavas/doceavas de una nota mucho más fuerte y simultánea).
    4. Limita la polifonía simultánea.
    `strength` escala los umbrales (>1 depura más, <1 conserva más notas).
    """
    prof = PROFILES.get(stem, PROFILES["other"])
    if not notes:
        return []
    vels = sorted(n[3] for n in notes)
    floor = min(60, max(prof["min_vel"], vels[len(vels) // 10])) * strength    # tampoco el 10 % más débil
    notes = [list(n) for n in notes if n[1] - n[0] >= prof["min_dur"] * strength and n[3] >= floor]
    notes = _merge_split_notes(notes, prof["merge_gap"])
    if prof["ghosts"]:
        notes = _drop_ghosts(notes)
    notes = to_monophonic(notes) if prof["max_poly"] == 1 else _limit_polyphony(notes, prof["max_poly"])
    notes.sort(key=lambda n: (n[0], n[2]))
    return [[round(n[0], 3), round(n[1], 3), n[2], n[3]] for n in notes]


def transcribe_stem(wav: Path, stem: str, onset_threshold: float = 0.5, frame_threshold: float = 0.3,
                    min_note_ms: float = 60.0) -> list[list]:
    """Notas crudas de una pista de audio: [[inicio, fin, altura, velocidad], ...] (sin depurar)."""
    from basic_pitch.inference import predict

    low, high = FREQ_RANGE.get(stem, (None, None))
    _, _, events = predict(
        str(wav),
        onset_threshold=onset_threshold,
        frame_threshold=frame_threshold,
        minimum_note_length=min_note_ms,
        minimum_frequency=low,
        maximum_frequency=high,
        melodia_trick=True,
    )
    notes = [
        [round(float(start), 3), round(float(end), 3), int(pitch), max(1, min(127, int(round(amp * 127))))]
        for start, end, pitch, amp, *_ in events
    ]
    notes.sort(key=lambda n: (n[0], n[2]))
    return notes


def _song_audio(song_dir: Path) -> Path:
    meta_file = song_dir / "meta.json"
    name = None
    if meta_file.is_file():
        name = json.loads(meta_file.read_text(encoding="utf-8-sig")).get("audio")
    candidates = [song_dir / name] if name else []
    candidates += sorted(song_dir.glob("audio.*"))
    for path in candidates:
        if path.is_file():
            return path
    raise FileNotFoundError(f"No encuentro el audio de {song_dir} (se espera audio.mp3, audio.m4a...)")


def transcribe_song(song_dir: Path, stems=("guitar", "piano", "bass", "other"),
                    mono_stems=("bass",), force: bool = False, strength: float = 1.0,
                    refine_only: bool = False, onset_threshold: float = 0.5,
                    frame_threshold: float = 0.3) -> dict:
    """Transcribe las pistas pedidas y las guarda en notes.json (+ notes_raw.json) y midi/<pista>.mid."""
    song_dir = Path(song_dir)
    for stem in stems:
        if stem not in TRANSCRIBIBLES:
            raise ValueError(f"Pista no válida: {stem!r} (usa: {', '.join(TRANSCRIBIBLES)})")

    raw_file = song_dir / "notes_raw.json"
    raw = json.loads(raw_file.read_text(encoding="utf-8")) if raw_file.is_file() else {}
    wavs = {}
    if not refine_only:
        audio = _song_audio(song_dir)
        print(f"[1/2] Separando en instrumentos (Demucs 6 pistas) a partir de {audio.name}...")
        wavs = separate_all_stems(audio, song_dir / "stems6")
        prepare_mix(song_dir)

    notes_file = song_dir / "notes.json"
    data = {"version": 1, "model": "basic-pitch 0.4.0 (ONNX)", "stems": {}}
    if notes_file.is_file():
        data = json.loads(notes_file.read_text(encoding="utf-8"))
        data.setdefault("stems", {})

    midi_dir = song_dir / "midi"
    midi_dir.mkdir(exist_ok=True)
    for i, stem in enumerate(stems, 1):
        if refine_only:
            if stem not in raw:
                print(f"[2/2] {stem}: no hay notas crudas guardadas; transcríbela primero (sin --refine-only)")
                continue
        elif stem in data["stems"] and stem in raw and not force:
            print(f"[2/2] {stem}: ya transcrita (usa --force para repetir o --refine-only para reajustar)")
            continue
        else:
            print(f"[2/2] ({i}/{len(stems)}) Transcribiendo {stem}...")
            raw[stem] = transcribe_stem(wavs[stem], stem, onset_threshold=onset_threshold,
                                        frame_threshold=frame_threshold)
        mono = stem in mono_stems
        notes = refine(raw[stem], stem, strength)
        if mono:
            notes = to_monophonic(notes)
        data["stems"][stem] = {"mono": mono, "notes": notes}
        (midi_dir / f"{stem}.mid").write_bytes(write_midi(notes, name=stem, program=PROGRAM.get(stem, 0)))
        print(f"      {len(raw[stem])} crudas -> {len(notes)} tras depurar")

    raw_file.write_text(json.dumps(raw, separators=(",", ":")), encoding="utf-8")
    data["refined"] = {"strength": strength}
    notes_file.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    print(f"Listo: {notes_file}")
    return data
