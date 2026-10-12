"""Partitura MusicXML a partir de notas cuantizadas (solo biblioteca estándar).

Entrada: partes [{"stem", "name", "notes": [[inicio, duración, altura, velocidad], ...]}] con las
notas ya cuantizadas (ver quantize.py), el tempo, el compás y las divisiones por negra.

Qué hace: estima la tonalidad, reparte las notas en pentagramas y voces, divide en compases con
ligaduras, rellena con silencios y escribe las alteraciones como las pondría un editor de
partituras. El piano usa dos pentagramas; la guitarra y el bajo llevan además un pentagrama de
tablatura con cuerda y traste.
"""
import math
from xml.sax.saxutils import escape

from . import tab as tablib
from .quantize import ALLOWED_SUBDIV, bar_divisions

# Nombre de las notas (sostenidos o bemoles según la tonalidad)
_SHARP = {0: ("C", 0), 1: ("C", 1), 2: ("D", 0), 3: ("D", 1), 4: ("E", 0), 5: ("F", 0),
          6: ("F", 1), 7: ("G", 0), 8: ("G", 1), 9: ("A", 0), 10: ("A", 1), 11: ("B", 0)}
_FLAT = {0: ("C", 0), 1: ("D", -1), 2: ("D", 0), 3: ("E", -1), 4: ("E", 0), 5: ("F", 0),
         6: ("G", -1), 7: ("G", 0), 8: ("A", -1), 9: ("A", 0), 10: ("B", -1), 11: ("B", 0)}
_SHARP_ORDER, _FLAT_ORDER = "FCGDAEB", "BEADGCF"
_MAJOR_FIFTHS = [0, -5, 2, -3, 4, -1, 6, 1, -4, 3, -2, 5]       # tónica mayor (0 = Do) -> alteraciones
_KRUMHANSL_MAJOR = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
_KRUMHANSL_MINOR = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]
_ACCIDENTAL = {1: "sharp", -1: "flat", 0: "natural"}
MAX_VOICES = 4                   # voces por pentagrama; las notas que no caben se descartan


# ---------- Tonalidad y escritura de notas ----------
def _pearson(a, b):
    ma, mb = sum(a) / len(a), sum(b) / len(b)
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    den = math.sqrt(sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b))
    return num / den if den else 0.0


def estimate_key(notes):
    """Tonalidad por el perfil de Krumhansl, ponderada por duración. Devuelve (alteraciones, modo)."""
    hist = [0.0] * 12
    for _s, dur, pitch, _v in notes:
        hist[pitch % 12] += dur
    if not any(hist):
        return 0, "major"
    best = None
    for tonic in range(12):
        for mode, profile in (("major", _KRUMHANSL_MAJOR), ("minor", _KRUMHANSL_MINOR)):
            r = _pearson(hist, [profile[(pc - tonic) % 12] for pc in range(12)])
            if best is None or r > best[0]:
                best = (r, tonic, mode)
    _r, tonic, mode = best
    major_pc = tonic if mode == "major" else (tonic + 3) % 12
    return _MAJOR_FIFTHS[major_pc], mode


def _key_alter(step: str, fifths: int) -> int:
    if fifths > 0 and step in _SHARP_ORDER[:fifths]:
        return 1
    if fifths < 0 and step in _FLAT_ORDER[:-fifths]:
        return -1
    return 0


def _spell(pitch: int, fifths: int):
    step, alter = (_SHARP if fifths >= 0 else _FLAT)[pitch % 12]
    return step, alter, pitch // 12 - 1


# ---------- Duraciones ----------
def duration_table(divisions: int) -> dict:
    """{divisiones: (tipo, puntillos)} de las figuras que caben exactamente en la rejilla."""
    table = {}
    names = [(4 * divisions, "whole"), (2 * divisions, "half"), (divisions, "quarter")]
    if divisions % 2 == 0:
        names.append((divisions // 2, "eighth"))
    if divisions % 4 == 0:
        names.append((divisions // 4, "16th"))
    if divisions % 8 == 0:
        names.append((divisions // 8, "32nd"))
    for base, name in names:
        table[base] = (name, 0)
        if base % 2 == 0:
            table[base * 3 // 2] = (name, 1)
    return table


def split_duration(pos: int, dur: int, table: dict) -> list:
    """Parte una duración en figuras alineadas con el compás (p. ej. 12 desde la 2.ª negra = 4 + 8)."""
    sizes = sorted(table, reverse=True)
    pieces = []
    while dur > 0:
        chosen = 1
        for d in sizes:
            if d > dur:
                continue
            _name, dots = table[d]
            base = d if not dots else d * 2 // 3
            aligned = pos % (2 * base) == 0 if dots else pos % d == 0
            if aligned:
                chosen = d
                break
        pieces.append(chosen)
        pos += chosen
        dur -= chosen
    return pieces


# ---------- Eventos y voces ----------
def make_events(notes):
    """Agrupa notas con el mismo ataque en acordes; las duraciones que difieren en 1 se igualan."""
    by_start = {}
    for start, dur, pitch, _vel in notes:
        by_start.setdefault(start, []).append((dur, pitch))
    events = []
    for start in sorted(by_start):
        group = sorted(by_start[start])
        clusters, current = [], [group[0]]
        for item in group[1:]:
            if item[0] - current[-1][0] <= 1:
                current.append(item)
            else:
                clusters.append(current)
                current = [item]
        clusters.append(current)
        for cluster in clusters:
            events.append({
                "start": start,
                "dur": max(d for d, _p in cluster),
                "pitches": sorted({p for _d, p in cluster}),
            })
    return events


def assign_voices(events, max_voices=MAX_VOICES, close_gap=1):
    """Reparte los eventos en voces sin solapes. Devuelve (voces, eventos_descartados)."""
    voices, dropped = [], []
    for ev in sorted(events, key=lambda e: (e["start"], -max(e["pitches"]))):
        best, best_gap = None, None
        for v in voices:
            last = v[-1]
            if last["start"] + last["dur"] <= ev["start"]:
                gap = abs(sum(last["pitches"]) / len(last["pitches"]) - sum(ev["pitches"]) / len(ev["pitches"]))
                if best is None or gap < best_gap:
                    best, best_gap = v, gap
        if best is not None:
            best.append(ev)
        elif len(voices) < max_voices:
            voices.append([ev])
        else:
            dropped.append(ev)
    for v in voices:                                  # cierra huecos de una división (evita silencios de semicorchea)
        for a, b in zip(v, v[1:]):
            gap = b["start"] - (a["start"] + a["dur"])
            if 0 < gap <= close_gap:
                a["dur"] += gap
    return voices, dropped


def _render_voice(voice, bar_len, bars, table):
    """Una lista de elementos (notas y silencios) por compás, con ligaduras en las barras."""
    measures = [[] for _ in range(bars)]
    for ev in voice:
        s, e = ev["start"], ev["start"] + ev["dur"]
        m = s // bar_len
        while s < e:
            seg_end = min(e, (m + 1) * bar_len)
            pos = s - m * bar_len
            pieces = split_duration(pos, seg_end - s, table)
            for k, d in enumerate(pieces):
                measures[m].append({
                    "kind": "note", "start": pos, "dur": d, "event": ev,
                    "tie_stop": k > 0 or s > ev["start"],
                    "tie_start": k < len(pieces) - 1 or seg_end < e,
                })
                pos += d
            s, m = seg_end, m + 1
    for m in range(bars):
        items = sorted(measures[m], key=lambda it: it["start"])
        if not items:
            measures[m] = [{"kind": "measure_rest", "start": 0, "dur": bar_len}]
            continue
        filled, pos = [], 0
        for it in items:
            if it["start"] > pos:
                filled += _rests(pos, it["start"] - pos, table)
            filled.append(it)
            pos = it["start"] + it["dur"]
        if pos < bar_len:
            filled += _rests(pos, bar_len - pos, table)
        measures[m] = filled
    return measures


def _rests(pos, dur, table):
    out = []
    for d in split_duration(pos, dur, table):
        out.append({"kind": "rest", "start": pos, "dur": d})
        pos += d
    return out


# ---------- Diseño de pentagramas por instrumento ----------
def _layout(stem, notes, with_tab):
    """Pentagramas de la parte: lista de dicts con clave, rango de alturas y, si procede, tablatura."""
    if stem == "guitar":
        return {"staves": [{"clef": ("G", 2, -1)}], "tab": "guitar" if with_tab else None}
    if stem == "bass":
        return {"staves": [{"clef": ("F", 4, 0)}], "tab": "bass" if with_tab else None}
    grand = stem == "piano"
    if stem == "other" and notes:
        grand = sum(1 for n in notes if n[2] < 60) / len(notes) > 0.15
    if grand:
        return {"staves": [{"clef": ("G", 2, 0), "min": 60}, {"clef": ("F", 4, 0), "max": 59}], "tab": None}
    return {"staves": [{"clef": ("G", 2, 0)}], "tab": None}


def _tuning_xml(number, tuning):
    out = [f'<staff-details number="{number}"><staff-lines>{len(tuning)}</staff-lines>']
    for line, pitch in enumerate(tuning, 1):
        step, alter, octave = _spell(pitch, 0)
        alter_xml = f"<tuning-alter>{alter}</tuning-alter>" if alter else ""
        out.append(f'<staff-tuning line="{line}"><tuning-step>{step}</tuning-step>{alter_xml}'
                   f"<tuning-octave>{octave}</tuning-octave></staff-tuning>")
    out.append("</staff-details>")
    return "".join(out)


# ---------- Emisión de MusicXML ----------
def _note_xml(pitch, dur, name_dots, voice_no, staff_no, *, fifths, chord, tie_start, tie_stop,
              accidental, stem, technical):
    type_name, dots = name_dots
    step, alter, octave = _spell(pitch, fifths)
    x = ["<note>"]
    if chord:
        x.append("<chord/>")
    x.append(f"<pitch><step>{step}</step>" + (f"<alter>{alter}</alter>" if alter else "")
             + f"<octave>{octave}</octave></pitch>")
    x.append(f"<duration>{dur}</duration>")
    if tie_stop:
        x.append('<tie type="stop"/>')
    if tie_start:
        x.append('<tie type="start"/>')
    x.append(f"<voice>{voice_no}</voice><type>{type_name}</type>" + "<dot/>" * dots)
    if accidental:
        x.append(f"<accidental>{accidental}</accidental>")
    if stem:
        x.append(f"<stem>{stem}</stem>")
    x.append(f"<staff>{staff_no}</staff>")
    notations = ""
    if tie_stop:
        notations += '<tied type="stop"/>'
    if tie_start:
        notations += '<tied type="start"/>'
    if technical:
        notations += f"<technical><string>{technical[0]}</string><fret>{technical[1]}</fret></technical>"
    if notations:
        x.append(f"<notations>{notations}</notations>")
    x.append("</note>")
    return "".join(x)


def _rest_xml(item, table, voice_no, staff_no, bar_len):
    if item["kind"] == "measure_rest":
        return (f'<note><rest measure="yes"/><duration>{bar_len}</duration>'
                f"<voice>{voice_no}</voice><staff>{staff_no}</staff></note>")
    type_name, dots = table[item["dur"]]
    return (f"<note><rest/><duration>{item['dur']}</duration><voice>{voice_no}</voice>"
            f"<type>{type_name}</type>" + "<dot/>" * dots + f"<staff>{staff_no}</staff></note>")


def build_score(parts, bpm, meter=(4, 4), subdiv=4, title="", with_tab=True):
    """Devuelve (xml, info). `info` resume lo escrito y lo descartado (y `written`, para comprobar)."""
    if subdiv not in ALLOWED_SUBDIV:
        raise ValueError(f"subdiv debe ser uno de {ALLOWED_SUBDIV}")
    bar_len = bar_divisions(meter, subdiv)
    table = duration_table(subdiv)
    all_notes = [n for p in parts for n in p["notes"]]
    if not all_notes:
        raise ValueError("No hay notas para la partitura")
    bars = max(1, math.ceil(max(n[0] + n[1] for n in all_notes) / bar_len))
    fifths, mode = estimate_key(all_notes)

    info = {"bars": bars, "fifths": fifths, "mode": mode, "dropped_notes": 0, "clamped_notes": 0,
            "parts": [], "written": []}
    part_list, part_xml = [], []
    for p_idx, part in enumerate(parts, 1):
        notes = [list(n) for n in part["notes"]]
        layout = _layout(part["stem"], notes, with_tab)
        tab_name = layout["tab"]
        if tab_name:                                       # la tablatura exige notas tocables
            tuning, max_fret = tablib.TUNINGS[tab_name], tablib.MAX_FRET[tab_name]
            for n in notes:
                new = tablib.clamp_pitch(n[2], tuning, max_fret)
                if new != n[2]:
                    info["clamped_notes"] += 1
                    n[2] = new

        staves = layout["staves"]
        staff_voices = []                                  # por pentagrama: lista de voces renderizadas
        all_events = []
        for st in staves:
            sub = [n for n in notes if n[2] >= st.get("min", -1) and n[2] <= st.get("max", 999)]
            voices, dropped = assign_voices(make_events(sub))
            info["dropped_notes"] += sum(len(e["pitches"]) for e in dropped)
            staff_voices.append(voices)
            for v in voices:
                all_events.extend(v)

        if tab_name:                                       # cuerda y traste de todos los instantes
            by_start = {}
            for ev in all_events:
                by_start.setdefault(ev["start"], []).append(ev)
            starts = sorted(by_start)
            groups = [[p for ev in by_start[s] for p in ev["pitches"]] for s in starts]
            result = tablib.assign(groups, tablib.TUNINGS[tab_name], tablib.MAX_FRET[tab_name])
            for s, row in zip(starts, result):
                k = 0
                for ev in by_start[s]:
                    ev["tabs"] = row[k:k + len(ev["pitches"])]
                    k += len(ev["pitches"])

        n_std = len(staves)
        staff_total = n_std + (1 if tab_name else 0)
        rendered = []        # (staff_no, voice_no, measures, tab?)
        voice_counter = 0
        for si, voices in enumerate(staff_voices):
            for vi, voice in enumerate(voices):
                voice_counter += 1
                rendered.append((si + 1, voice_counter, vi, _render_voice(voice, bar_len, bars, table), False,
                                 len(voices)))
            if not voices:                                  # pentagrama vacío: compases de silencio
                voice_counter += 1
                rendered.append((si + 1, voice_counter, 0,
                                 [[{"kind": "measure_rest", "start": 0, "dur": bar_len}] for _ in range(bars)],
                                 False, 1))
        if tab_name:                                        # la tablatura repite el ritmo del pentagrama 1
            for staff_no, _vno, vi, measures, _is_tab, nvoices in list(rendered):
                if staff_no == 1:
                    voice_counter += 1
                    rendered.append((n_std + 1, voice_counter, vi, measures, True, nvoices))

        for staff_voices_list in staff_voices:
            for voice in staff_voices_list:
                for ev in voice:
                    for pitch in ev["pitches"]:
                        info["written"].append((p_idx, ev["start"], ev["dur"], pitch))

        pid = f"P{p_idx}"
        part_list.append(f'<score-part id="{pid}"><part-name>{escape(part["name"])}</part-name></score-part>')
        out = [f'<part id="{pid}">']
        for m in range(bars):
            out.append(f'<measure number="{m + 1}">')
            if m == 0:
                out.append(f"<attributes><divisions>{subdiv}</divisions>"
                           f"<key><fifths>{fifths}</fifths><mode>{mode}</mode></key>"
                           f"<time><beats>{meter[0]}</beats><beat-type>{meter[1]}</beat-type></time>")
                if staff_total > 1:
                    out.append(f"<staves>{staff_total}</staves>")
                for si, st in enumerate(staves, 1):
                    sign, line, octave = st["clef"]
                    oc = f"<clef-octave-change>{octave}</clef-octave-change>" if octave else ""
                    out.append(f'<clef number="{si}"><sign>{sign}</sign><line>{line}</line>{oc}</clef>')
                if tab_name:
                    tuning = tablib.TUNINGS[tab_name]
                    out.append(f'<clef number="{staff_total}"><sign>TAB</sign><line>5</line></clef>')
                    out.append(_tuning_xml(staff_total, tuning))
                out.append("</attributes>")
                if p_idx == 1:
                    out.append(f'<direction placement="above"><direction-type><metronome><beat-unit>quarter</beat-unit>'
                               f'<per-minute>{bpm:g}</per-minute></metronome></direction-type>'
                               f'<sound tempo="{bpm:g}"/></direction>')
            accidental_state = {}
            for idx, (staff_no, voice_no, vi, measures, is_tab, nvoices) in enumerate(rendered):
                if idx > 0:
                    out.append(f"<backup><duration>{bar_len}</duration></backup>")
                stem = None
                if not is_tab and nvoices > 1:
                    stem = "up" if vi % 2 == 0 else "down"
                for item in measures[m]:
                    if item["kind"] != "note":
                        out.append(_rest_xml(item, table, voice_no, staff_no, bar_len))
                        continue
                    ev = item["event"]
                    name_dots = table[item["dur"]]
                    order = sorted(range(len(ev["pitches"])), key=lambda i: ev["pitches"][i])
                    for k, i in enumerate(order):
                        pitch = ev["pitches"][i]
                        accidental = None
                        technical = None
                        if is_tab:
                            t = ev.get("tabs", [None] * len(ev["pitches"]))[i]
                            if t is not None:
                                technical = (len(tablib.TUNINGS[tab_name]) - t[0], t[1])
                        else:
                            step, alter, octave = _spell(pitch, fifths)
                            key = (staff_no, step, octave)
                            current = accidental_state.get(key, _key_alter(step, fifths))
                            if alter != current and not item["tie_stop"]:
                                accidental = _ACCIDENTAL[alter]
                            if not item["tie_stop"]:
                                accidental_state[key] = alter
                        out.append(_note_xml(pitch, item["dur"], name_dots, voice_no, staff_no, fifths=fifths,
                                             chord=k > 0, tie_start=item["tie_start"], tie_stop=item["tie_stop"],
                                             accidental=accidental, stem=stem, technical=technical))
            out.append("</measure>")
        out.append("</part>")
        part_xml.append("".join(out))
        info["parts"].append({"stem": part["stem"], "staves": staff_total, "tab": bool(tab_name)})

    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n'
           '<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 3.1 Partwise//EN" '
           '"http://www.musicxml.org/dtds/partwise.dtd">\n'
           '<score-partwise version="3.1">'
           f"<work><work-title>{escape(title or 'Transcripción')}</work-title></work>"
           "<identification><encoding><software>Transcriptor</software></encoding></identification>"
           f'<part-list>{"".join(part_list)}</part-list>{"".join(part_xml)}</score-partwise>')
    return xml, info
