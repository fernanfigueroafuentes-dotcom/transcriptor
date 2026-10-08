"""Fusión de acordes y letra en formato ChordPro."""

# Tolerancia (s) para decidir si un acorde va antes de una palabra
CHORD_TOLERANCE = 0.15
# Un pasaje sin letra de al menos esta duración (s) se escribe como línea instrumental
INSTRUMENTAL_MIN = 3.0


def _instrumental_before(pending: list[dict], first_word_start: float) -> list[dict]:
    """Saca de `pending` los acordes que suenan por completo antes de la línea, si el
    pasaje dura al menos INSTRUMENTAL_MIN; si no, los deja para pegarlos a las palabras."""
    lead = []
    for chord in pending:
        if chord["end"] > first_word_start - CHORD_TOLERANCE:
            break
        lead.append(chord)
    if lead and first_word_start - lead[0]["start"] >= INSTRUMENTAL_MIN:
        del pending[:len(lead)]
        return lead
    return []


def to_chordpro(lines: list[dict], chords: list[dict], title: str = "") -> str:
    """Coloca cada acorde encima de la palabra que empieza en su mismo momento.

    Los pasajes largos sin letra (intro, solos) salen como líneas de acordes
    marcadas como Instrumental, antes de la línea de letra que los sigue.
    """
    out = []
    if title:
        out.append(f"{{title: {title}}}")
        out.append("")

    pending = list(chords)  # se consumen en orden de tiempo

    for line in lines:
        starts = [t["start"] for t in line["tokens"] if t["start"] is not None]
        if starts:
            lead = _instrumental_before(pending, starts[0])
            if lead:
                out.append("{comment: Instrumental}")
                out.append(" ".join(f"[{c['chord']}]" for c in lead))
                out.append("")

        parts = []
        for tok in line["tokens"]:
            start = tok["start"]
            labels = []
            while pending and start is not None and pending[0]["start"] <= start + CHORD_TOLERANCE:
                labels.append(f"[{pending.pop(0)['chord']}]")
            parts.append("".join(labels) + tok["word"])
        if parts:
            out.append(" ".join(parts))
        out.append("")

    # Acordes que quedaron sin palabra (intro, outro, pasajes instrumentales)
    if pending:
        out.append("# Acordes sin letra:")
        out.append(" ".join(f"[{c['chord']}]" for c in pending))

    return "\n".join(out).rstrip() + "\n"
