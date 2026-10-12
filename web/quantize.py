"""Cuantización de notas a una rejilla de tempo fijo (solo biblioteca estándar).

La rejilla la define el usuario: un tempo (bpm), el instante t0 en que cae el primer tiempo de un
compás, el compás y cuántas divisiones hay por negra. Una nota [inicio_s, fin_s, altura, velocidad]
pasa a [inicio, duración, altura, velocidad] medidos en divisiones de la rejilla.

Se usa una rejilla fija a propósito: en piezas con tempo irregular un seguidor de pulso automático
no encaja con los ataques de las notas, y una partitura "automática" sería engañosa.
"""
import math

ALLOWED_SUBDIV = (2, 4, 8)          # corcheas, semicorcheas, fusas (sin tresillos por ahora)


def bar_divisions(meter, subdiv: int) -> int:
    """Divisiones por compás. 4/4 con subdiv 4 -> 16; 3/4 -> 12; 6/8 -> 12."""
    num, den = int(meter[0]), int(meter[1])
    if num < 1 or den not in (2, 4, 8, 16) or (num * 4) % den:
        raise ValueError(f"Compás no admitido: {num}/{den} (usa 4/4, 3/4, 2/4, 6/8, 12/8...)")
    return num * 4 // den * subdiv


def quantize(notes, bpm: float, t0: float, subdiv: int = 4, meter=(4, 4), start=None, end=None, pad=None):
    """Devuelve (notas_cuantizadas, relleno).

    `relleno` son las divisiones que se añaden al principio (siempre compases enteros) cuando hay
    notas antes de t0, p. ej. una anacrusa: así la barra de compás sigue cayendo donde debe.
    Al combinar varios instrumentos hay que darles el mismo `pad` (el mayor de todos) para que
    sigan alineados entre sí.
    """
    if bpm <= 0:
        raise ValueError("El tempo debe ser mayor que 0")
    if subdiv not in ALLOWED_SUBDIV:
        raise ValueError(f"subdiv debe ser uno de {ALLOWED_SUBDIV}")
    bar = bar_divisions(meter, subdiv)
    per_sec = bpm / 60.0 * subdiv

    out = []
    for s, e, pitch, vel in notes:
        if start is not None and e <= start:
            continue
        if end is not None and s >= end:
            continue
        if start is not None:
            s = max(s, start)
        if end is not None:
            e = min(e, end)
        a = round((s - t0) * per_sec)
        b = round((e - t0) * per_sec)
        out.append([a, max(1, b - a), int(pitch), int(vel)])

    # Misma altura: mismo ataque -> se queda la más fuerte; solape -> se acorta la anterior
    out.sort(key=lambda n: (n[2], n[0], -n[3]))
    clean = []
    for n in out:
        if clean and clean[-1][2] == n[2]:
            prev = clean[-1]
            if n[0] == prev[0]:
                continue
            if n[0] < prev[0] + prev[1]:
                prev[1] = n[0] - prev[0]
        clean.append(n)

    if not clean:
        return [], (pad or 0)
    if pad is None:
        first = min(n[0] for n in clean)
        pad = math.ceil(-first / bar) * bar if first < 0 else 0
    for n in clean:
        n[0] += pad
    clean.sort(key=lambda n: (n[0], -n[2]))
    return clean, pad


def grid_fit(notes, bpm: float, t0: float, subdiv: int = 4, tolerance: float = 0.03,
             start=None, end=None) -> dict:
    """Qué tan bien caen los ataques en la rejilla.

    `fraction` es la proporción de ataques a menos de `tolerance` s de una línea de la rejilla;
    `baseline` es lo que saldría con ataques repartidos al azar. Solo importa la diferencia.
    """
    per_sec = bpm / 60.0 * subdiv
    errors = []
    for s, e, _p, _v in notes:
        if (start is not None and s < start) or (end is not None and s >= end):
            continue
        x = (s - t0) * per_sec
        errors.append(abs(x - round(x)) / per_sec)
    if not errors:
        return {"onsets": 0, "fraction": 0.0, "baseline": 0.0, "median_error_ms": 0.0}
    errors.sort()
    return {
        "onsets": len(errors),
        "fraction": round(sum(1 for e in errors if e <= tolerance) / len(errors), 3),
        "baseline": round(min(1.0, 2 * tolerance * per_sec), 3),
        "median_error_ms": round(errors[len(errors) // 2] * 1000, 1),
    }
