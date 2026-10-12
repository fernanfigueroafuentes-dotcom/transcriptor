"""Escritor mínimo de archivos MIDI (formato 0), solo con la biblioteca estándar.

Lo usan el servidor (para descargar el MIDI de un tramo) y core/notes.py (al transcribir),
así que no depende de pretty_midi ni de nada que haya que instalar en la imagen de Docker.

Una nota es una lista [inicio_s, fin_s, altura_midi, velocidad]. Con 480 ticks por negra y
120 bpm, un segundo son 960 ticks: las notas caen exactamente en su tiempo real del audio.
"""
import struct

TICKS_PER_QUARTER = 480
TEMPO_BPM = 120
TICKS_PER_SECOND = TICKS_PER_QUARTER * TEMPO_BPM // 60   # 960


def _vlq(value: int) -> bytes:
    """Cantidad de longitud variable de MIDI."""
    value = max(0, int(value))
    out = [value & 0x7F]
    value >>= 7
    while value:
        out.append((value & 0x7F) | 0x80)
        value >>= 7
    return bytes(reversed(out))


def cut_notes(notes, start=None, end=None):
    """Recorta las notas al tramo [start, end] y las desplaza para que empiece en 0."""
    if start is None and end is None:
        return [list(n) for n in notes]
    a = 0.0 if start is None else float(start)
    b = float("inf") if end is None else float(end)
    out = []
    for s, e, pitch, vel in notes:
        if e <= a or s >= b:
            continue
        out.append([max(s, a) - a, min(e, b) - a, pitch, vel])
    return out


def write_midi_grid(notes, subdiv: int, bpm: float, meter=(4, 4), name: str = "", program: int = 0) -> bytes:
    """MIDI con el tempo y el compás de una rejilla (notas cuantizadas, en divisiones).

    Cada nota es [inicio, duración, altura, velocidad] medidos en divisiones; con `subdiv` divisiones
    por negra, un editor de partituras o un DAW las verá clavadas en su compás.
    """
    ticks_per_div = TICKS_PER_QUARTER // subdiv
    events = []
    for start, dur, pitch, vel in notes:
        on = int(start) * ticks_per_div
        events.append((on, 1, bytes([0x90, max(0, min(127, int(pitch))), max(1, min(127, int(vel)))])))
        events.append((on + max(1, int(dur)) * ticks_per_div, 0, bytes([0x80, max(0, min(127, int(pitch))), 0])))
    events.sort(key=lambda ev: (ev[0], ev[1]))

    track = bytearray()
    if name:
        label = name.encode("utf-8")[:60]
        track += _vlq(0) + b"\xff\x03" + _vlq(len(label)) + label
    track += _vlq(0) + b"\xff\x51\x03" + int(round(60_000_000 / bpm)).to_bytes(3, "big")
    track += _vlq(0) + b"\xff\x58\x04" + bytes([int(meter[0]), int(meter[1]).bit_length() - 1, 24, 8])
    track += _vlq(0) + bytes([0xC0, max(0, min(127, int(program)))])
    last = 0
    for tick, _, data in events:
        track += _vlq(tick - last) + data
        last = tick
    track += _vlq(0) + b"\xff\x2f\x00"

    header = b"MThd" + struct.pack(">IHHH", 6, 0, 1, TICKS_PER_QUARTER)
    return header + b"MTrk" + struct.pack(">I", len(track)) + bytes(track)


def write_midi(notes, name: str = "", program: int = 0) -> bytes:
    """Devuelve los bytes de un archivo MIDI con las notas dadas."""
    events = []                                   # (tick, orden, bytes); note_off antes que note_on
    for s, e, pitch, vel in notes:
        pitch = max(0, min(127, int(pitch)))
        vel = max(1, min(127, int(vel)))
        on = int(round(s * TICKS_PER_SECOND))
        off = max(on + 1, int(round(e * TICKS_PER_SECOND)))
        events.append((on, 1, bytes([0x90, pitch, vel])))
        events.append((off, 0, bytes([0x80, pitch, 0])))
    events.sort(key=lambda ev: (ev[0], ev[1]))

    track = bytearray()
    if name:
        label = name.encode("utf-8")[:60]
        track += _vlq(0) + b"\xff\x03" + _vlq(len(label)) + label
    track += _vlq(0) + b"\xff\x51\x03" + (60_000_000 // TEMPO_BPM).to_bytes(3, "big")
    track += _vlq(0) + bytes([0xC0, max(0, min(127, int(program)))])
    last = 0
    for tick, _, data in events:
        track += _vlq(tick - last) + data
        last = tick
    track += _vlq(0) + b"\xff\x2f\x00"

    header = b"MThd" + struct.pack(">IHHH", 6, 0, 1, TICKS_PER_QUARTER)
    return header + b"MTrk" + struct.pack(">I", len(track)) + bytes(track)
