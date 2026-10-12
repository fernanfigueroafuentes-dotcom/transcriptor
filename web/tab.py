"""Asignación de cuerda y traste para tablatura (solo biblioteca estándar).

Para cada instante se buscan las formas posibles de tocar sus notas en cuerdas distintas (con un
ancho de mano limitado) y, entre todos los instantes, se elige el camino que menos mueve la mano
(programación dinámica). Las cuerdas se numeran de la más grave (0) a la más aguda.
"""

GUITAR = (40, 45, 50, 55, 59, 64)      # E2 A2 D3 G3 B3 E4
BASS = (28, 33, 38, 43)                # E1 A1 D2 G2 (bajo de 4 cuerdas)
MAX_FRET = {"guitar": 22, "bass": 20}
TUNINGS = {"guitar": GUITAR, "bass": BASS}


def clamp_pitch(pitch: int, tuning, max_fret: int) -> int:
    """Lleva la nota (por octavas) al rango que el instrumento puede tocar."""
    low, high = tuning[0], tuning[-1] + max_fret
    while pitch < low:
        pitch += 12
    while pitch > high:
        pitch -= 12
    return pitch


def _candidates(pitches, tuning, max_fret, max_span, limit=14):
    """Formas de tocar un grupo de notas simultáneas, cada una en una cuerda distinta."""
    order = sorted(range(len(pitches)), key=lambda i: -pitches[i])      # de la más aguda a la más grave
    found = []

    def rec(k, below, assign):
        if len(found) >= 600:
            return
        if k == len(order):
            fretted = [f for _s, f in assign.values() if f > 0]
            if not fretted or max(fretted) - min(fretted) <= max_span:
                found.append(dict(assign))
            return
        i = order[k]
        for s in range(min(below, len(tuning)) - 1, -1, -1):             # cuerdas que no cruzan a la anterior
            f = pitches[i] - tuning[s]
            if 0 <= f <= max_fret:
                assign[i] = (s, f)
                rec(k + 1, s, assign)
                del assign[i]

    rec(0, len(tuning), {})
    scored = []
    for assign in found:
        frets = [f for _s, f in assign.values()]
        fretted = [f for f in frets if f > 0]
        span = (max(fretted) - min(fretted)) if fretted else 0
        opens = sum(1 for f in frets if f == 0)
        cost = 0.12 * (sum(frets) / len(frets)) + 0.5 * span - 0.4 * opens
        pos = sum(fretted) / len(fretted) if fretted else None
        scored.append((cost, pos, assign))
    scored.sort(key=lambda c: c[0])
    return scored[:limit]


def assign(groups, tuning, max_fret, max_span=4):
    """groups: lista de listas de alturas (notas simultáneas, ya dentro del rango del instrumento).

    Devuelve, para cada grupo, una lista de (cuerda, traste) en el mismo orden que las alturas, o
    None en las notas que no caben (más notas que cuerdas).
    """
    per_group = []
    for pitches in groups:
        keep = sorted(range(len(pitches)), key=lambda i: -pitches[i])[:len(tuning)]
        sub = [pitches[i] for i in keep]
        cands = _candidates(sub, tuning, max_fret, max_span) or _candidates(sub, tuning, max_fret, 99)
        per_group.append((keep, cands))

    # Programación dinámica: coste = coste propio + movimiento de la mano respecto al instante anterior
    best = []
    prev_costs, prev_pos = None, None
    for keep, cands in per_group:
        if not cands:
            best.append(None)
            continue
        costs, backs = [], []
        for cost, pos, _a in cands:
            if prev_costs is None:
                costs.append(cost)
                backs.append(-1)
                continue
            options = []
            for j, pc in enumerate(prev_costs):
                pp = prev_pos[j]
                move = abs(pos - pp) if (pos is not None and pp is not None) else 0.0
                options.append(pc + cost + move + (3.0 if move > 7 else 0.0))
            j = min(range(len(options)), key=options.__getitem__)
            costs.append(options[j])
            backs.append(j)
        best.append((keep, cands, backs))
        prev_costs, prev_pos = costs, [c[1] for c in cands]

    # Recuperar el camino de menor coste
    valid = [i for i, b in enumerate(best) if b is not None]
    choice = {}
    if valid:
        # el coste acumulado del último grupo válido está en prev_costs
        j = min(range(len(prev_costs)), key=prev_costs.__getitem__)
        for i in reversed(valid):
            keep, cands, backs = best[i]
            choice[i] = j
            j = backs[j] if backs[j] >= 0 else 0
    out = []
    for i, pitches in enumerate(groups):
        if best[i] is None:
            out.append([None] * len(pitches))
            continue
        keep, cands, _b = best[i]
        assign_map = cands[choice[i]][2]
        row = [None] * len(pitches)
        for local, original in enumerate(keep):
            row[original] = assign_map.get(local)
        out.append(row)
    return out
