"""Pruebas de MIDI, cuantización, tablatura y partitura MusicXML (solo biblioteca estándar).

    python -m unittest discover -s tests -v

Si music21 está instalado, además se comprueba que lea las partituras generadas.
"""
import collections
import io
import random
import struct
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from web import tab as tablib  # noqa: E402
from web.midi import TICKS_PER_SECOND, cut_notes, write_midi, write_midi_grid  # noqa: E402
from web.musicxml import build_score, duration_table, split_duration  # noqa: E402
from web.quantize import bar_divisions, grid_fit, quantize  # noqa: E402

try:
    import music21  # noqa: F401
    HAS_MUSIC21 = True
except ImportError:                                           # pragma: no cover
    HAS_MUSIC21 = False


# ---------- Lectores mínimos, independientes del código que se prueba ----------
def _vlq(data, pos):
    value = 0
    while True:
        byte = data[pos]
        pos += 1
        value = (value << 7) | (byte & 0x7F)
        if not byte & 0x80:
            return value, pos


def parse_midi(data: bytes) -> dict:
    assert data[:4] == b"MThd", "falta la cabecera MThd"
    _fmt, _ntrk, division = struct.unpack(">HHH", data[8:14])
    assert data[14:18] == b"MTrk", "falta la pista MTrk"
    length = struct.unpack(">I", data[18:22])[0]
    pos, end = 22, 22 + length
    assert end == len(data), "la longitud de la pista no coincide con el archivo"
    tick, tempo, timesig, name, open_notes, notes = 0, None, None, "", {}, []
    ended = False
    while pos < end:
        delta, pos = _vlq(data, pos)
        tick += delta
        status = data[pos]
        if status == 0xFF:
            kind = data[pos + 1]
            size, p2 = _vlq(data, pos + 2)
            payload = data[p2:p2 + size]
            pos = p2 + size
            if kind == 0x51:
                tempo = int.from_bytes(payload, "big")
            elif kind == 0x58:
                timesig = (payload[0], 2 ** payload[1])
            elif kind == 0x03:
                name = payload.decode("utf-8")
            elif kind == 0x2F:
                ended = True
        elif status & 0xF0 == 0x90:
            open_notes.setdefault(data[pos + 1], []).append((tick, data[pos + 2]))
            pos += 3
        elif status & 0xF0 == 0x80:
            start, vel = open_notes[data[pos + 1]].pop(0)
            notes.append([start, tick, data[pos + 1], vel])
            pos += 3
        elif status & 0xF0 == 0xC0:
            pos += 2
        else:
            raise ValueError(f"evento MIDI no esperado: {status:#x}")
    assert ended, "falta el fin de pista"
    assert not any(open_notes.values()), "notas sin apagar"
    return {"division": division, "tempo": tempo, "timesig": timesig, "name": name, "notes": sorted(notes)}


_PITCH = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def read_score(xml: str, bar_len: int):
    """Notas de los pentagramas normales como (inicio, duración, altura), con las ligaduras unidas.

    Devuelve (notas, problemas, raíz): problemas incluye ligaduras sin inicio/cierre y compases
    cuyas voces no suman exactamente bar_len.
    """
    root = ET.fromstring(xml.encode("utf-8"))
    notes, problems = [], []
    for part in root.findall("part"):
        tab_staves = {c.get("number") for c in part.iter("clef") if c.findtext("sign") == "TAB"}
        open_ties = {}
        offset = 0
        for measure in part.findall("measure"):
            cursor = last_start = 0
            voice_sums = collections.Counter()
            for el in measure:
                if el.tag == "backup":
                    cursor -= int(el.findtext("duration"))
                elif el.tag == "note":
                    dur = int(el.findtext("duration"))
                    chord = el.find("chord") is not None
                    if not chord:
                        last_start = cursor
                        cursor += dur
                        voice_sums[el.findtext("voice")] += dur
                    if el.find("rest") is not None or (el.findtext("staff") or "1") in tab_staves:
                        continue
                    pitch = (_PITCH[el.findtext("pitch/step")] + int(el.findtext("pitch/alter") or 0)
                             + 12 * (int(el.findtext("pitch/octave")) + 1))
                    ties = {t.get("type") for t in el.findall("tie")}
                    key = (el.findtext("staff"), el.findtext("voice"), pitch)
                    start = offset + last_start
                    if "stop" in ties:
                        if key not in open_ties:
                            problems.append(f"ligadura sin inicio: {key} en {start}")
                            continue
                        s, d = open_ties.pop(key)
                        d += dur
                        if "start" in ties:
                            open_ties[key] = (s, d)
                        else:
                            notes.append((s, d, pitch))
                    elif "start" in ties:
                        open_ties[key] = (start, dur)
                    else:
                        notes.append((start, dur, pitch))
            for voice, total in voice_sums.items():
                if total != bar_len:
                    problems.append(f"compás {measure.get('number')} voz {voice}: {total} != {bar_len}")
            offset += bar_len
        problems += [f"ligadura sin cierre: {k}" for k in open_ties]
    return sorted(notes), problems, root


def tab_mismatches(root, tuning_by_part) -> int:
    """Notas de la tablatura cuya cuerda y traste no dan la altura escrita."""
    bad = 0
    for part, tuning in zip(root.findall("part"), tuning_by_part):
        if tuning is None:
            continue
        for note in part.iter("note"):
            tech = note.find("notations/technical")
            if tech is None or note.find("pitch") is None:
                continue
            pitch = (_PITCH[note.findtext("pitch/step")] + int(note.findtext("pitch/alter") or 0)
                     + 12 * (int(note.findtext("pitch/octave")) + 1))
            string, fret = int(tech.findtext("string")), int(tech.findtext("fret"))
            if not (0 <= fret <= 22) or tuning[len(tuning) - string] + fret != pitch:
                bad += 1
    return bad


# ---------- MIDI ----------
class MidiTests(unittest.TestCase):
    def test_tiempo_real_ida_y_vuelta(self):
        notes = [[0.0, 0.5, 60, 90], [0.5, 1.25, 64, 100], [1.0, 2.0, 67, 70], [3.123, 3.5, 36, 127]]
        midi = parse_midi(write_midi(notes, name="piano", program=0))
        self.assertEqual(midi["division"], 480)
        self.assertEqual(midi["name"], "piano")
        self.assertEqual(len(midi["notes"]), len(notes))
        for (a, b, p, v), (start, end, pitch, vel) in zip(sorted(notes), midi["notes"]):
            self.assertLessEqual(abs(start - a * TICKS_PER_SECOND), 1)
            self.assertLessEqual(abs(end - b * TICKS_PER_SECOND), 1)
            self.assertEqual((pitch, vel), (p, v))

    def test_notas_muy_cortas_y_extremos(self):
        midi = parse_midi(write_midi([[10.0, 10.0, 127, 1], [0, 0.001, 0, 127]]))
        self.assertTrue(all(end > start for start, end, _p, _v in midi["notes"]))
        self.assertEqual(parse_midi(write_midi([]))["notes"], [])
        self.assertEqual(len(parse_midi(write_midi([[i * 0.1, i * 0.1 + 0.08, 40 + i % 48, 80] for i in range(3000)]))["notes"]), 3000)

    def test_recorte_de_tramo(self):
        notes = [[0.0, 0.5, 60, 90], [0.5, 1.25, 64, 100], [1.0, 2.0, 67, 70], [3.123, 3.5, 36, 127]]
        cut = cut_notes(notes, 0.75, 2.5)
        self.assertEqual([n[2] for n in cut], [64, 67])
        self.assertEqual(cut[0][:2], [0.0, 0.5])             # empieza en 0 y se acorta al tramo
        self.assertEqual(len(cut_notes(notes)), 4)

    def test_midi_cuantizado_lleva_tempo_compas_y_rejilla(self):
        midi = parse_midi(write_midi_grid([[0, 4, 60, 80], [6, 2, 62, 90], [16, 8, 64, 70]], 4, 136, (6, 8), name="x"))
        self.assertEqual(midi["tempo"], round(60_000_000 / 136))
        self.assertEqual(midi["timesig"], (6, 8))
        self.assertEqual([(s, e) for s, e, _p, _v in midi["notes"]], [(0, 480), (720, 960), (1920, 2880)])


# ---------- Depuración de notas ----------
class RefineTests(unittest.TestCase):
    def test_une_notas_partidas_y_quita_ruido(self):
        from core.notes import refine
        raw = [[0.0, 0.30, 60, 80], [0.32, 0.60, 60, 70],      # una nota partida en dos
               [1.0, 1.02, 64, 80],                              # demasiado corta
               [2.0, 2.5, 67, 3]] + [[3 + i, 3.5 + i, 50, 90] for i in range(12)]   # una muy débil entre notas fuertes
        out = refine(raw, "guitar")
        self.assertIn([0.0, 0.6, 60, 80], out)
        self.assertFalse([n for n in out if n[2] in (64, 67)])

    def test_quita_armonico_fantasma_pero_no_octavas_reales_desfasadas(self):
        from core.notes import refine
        raw = [[0, 1, 48, 100], [0.0, 0.9, 60, 40], [2.0, 3.0, 48, 100], [2.5, 3.0, 60, 90]]
        out = refine(raw, "piano")
        self.assertFalse([n for n in out if n[2] == 60 and n[0] == 0.0])      # simultánea y débil: fantasma
        self.assertTrue([n for n in out if n[2] == 60 and n[0] == 2.5])       # entra después y fuerte: real

    def test_polifonia_limitada_y_bajo_monofonico(self):
        from core.notes import refine
        chord = [[0, 1, 40 + i, 50 + i] for i in range(12)]
        self.assertLessEqual(len(refine(chord, "guitar")), 6)
        self.assertEqual(len(refine(chord, "bass")), 1)
        self.assertEqual(refine([], "guitar"), [])


# ---------- Cuantización ----------
class QuantizeTests(unittest.TestCase):
    def test_posiciones_en_la_rejilla(self):
        # 120 bpm, semicorcheas: una división dura 0,125 s
        q, pad = quantize([[1.0, 1.5, 60, 80], [1.5, 1.6, 62, 80]], 120, 1.0)
        self.assertEqual(pad, 0)
        self.assertEqual([n[:3] for n in q], [[0, 4, 60], [4, 1, 62]])

    def test_anacrusa_se_rellena_con_compases_enteros(self):
        q, pad = quantize([[0.9, 1.0, 60, 80], [1.0, 1.5, 62, 80]], 120, 1.0, meter=(4, 4))
        self.assertEqual(pad, 16)                              # un compás de 16 divisiones
        self.assertEqual([n[0] for n in q], [15, 16])          # la barra de compás sigue en 16

    def test_pistas_distintas_con_el_mismo_relleno(self):
        a, pad_a = quantize([[0.8, 1.0, 60, 80]], 120, 1.0)
        b, pad_b = quantize([[1.0, 1.5, 62, 80]], 120, 1.0)
        c, _ = quantize([[1.0, 1.5, 62, 80]], 120, 1.0, pad=max(pad_a, pad_b))
        self.assertEqual((pad_a, pad_b), (16, 0))
        self.assertEqual(c[0][0], 16)

    def test_misma_altura_no_se_solapa(self):
        q, _ = quantize([[0.0, 1.0, 60, 80], [0.5, 1.5, 60, 90], [0.5, 0.9, 60, 50]], 120, 0.0)
        self.assertEqual(len(q), 2)
        self.assertLessEqual(q[0][0] + q[0][1], q[1][0])

    def test_tramo_y_validaciones(self):
        q, _ = quantize([[0.0, 1.0, 60, 80], [5.0, 6.0, 62, 80], [20.0, 21.0, 64, 80]], 120, 5.0, start=4.0, end=10.0)
        self.assertEqual([n[2] for n in q], [60, 62][1:] or [62])
        with self.assertRaises(ValueError):
            quantize([[0, 1, 60, 80]], 0, 0)
        with self.assertRaises(ValueError):
            quantize([[0, 1, 60, 80]], 120, 0, subdiv=3)
        with self.assertRaises(ValueError):
            bar_divisions((7, 8), 4)                            # medias negras: no admitido
        self.assertEqual((bar_divisions((4, 4), 4), bar_divisions((3, 4), 2), bar_divisions((6, 8), 4)), (16, 6, 12))

    def test_ajuste_distingue_rejilla_real_del_azar(self):
        on_grid = [[0.5 * i + 0.125 * (i % 4), 0.5 * i + 0.2, 60, 80] for i in range(120)]
        fit = grid_fit(on_grid, 120, 0.0, 4)
        self.assertGreater(fit["fraction"], 0.95)
        rng = random.Random(1)
        noise = [[rng.uniform(0, 60), 61, 60, 80] for _ in range(400)]
        fit = grid_fit(noise, 120, 0.0, 4)
        self.assertLess(abs(fit["fraction"] - fit["baseline"]), 0.1)      # sin patrón: ≈ azar


# ---------- Figuras ----------
class SplitDurationTests(unittest.TestCase):
    def test_suma_exacta_y_figuras_validas(self):
        for divisions in (2, 4, 8):
            table = duration_table(divisions)
            for pos in range(4 * divisions):
                for dur in range(1, 4 * divisions - pos + 1):
                    pieces = split_duration(pos, dur, table)
                    self.assertEqual(sum(pieces), dur)
                    self.assertTrue(all(p in table for p in pieces), (divisions, pos, dur, pieces))

    def test_casos_legibles(self):
        t4 = duration_table(4)
        self.assertEqual(split_duration(4, 12, t4), [4, 8])       # 2.ª negra: negra + blanca, no puntillos raros
        self.assertEqual(split_duration(0, 6, t4), [6])           # negra con puntillo en el primer tiempo
        self.assertEqual(split_duration(2, 6, t4), [2, 4])        # en contratiempo: corchea + negra
        self.assertEqual(split_duration(0, 16, t4), [16])         # compás entero = redonda


# ---------- Tablatura ----------
class TabTests(unittest.TestCase):
    def test_cada_nota_en_una_cuerda_distinta_y_con_la_altura_correcta(self):
        rng = random.Random(3)
        groups = []
        for _ in range(60):
            base = rng.randint(40, 70)
            groups.append(sorted(rng.sample(range(base, base + 8), rng.randint(1, 3))))
        result = tablib.assign(groups, tablib.GUITAR, 22)
        for pitches, row in zip(groups, result):
            strings = [s for s, _f in (r for r in row if r)]
            self.assertEqual(len(strings), len(set(strings)))
            for pitch, placed in zip(pitches, row):
                if placed is None:                      # p. ej. mi y fa graves: ambos solo caben en la 6.ª cuerda
                    self.assertGreater(len(pitches), 1)
                    continue
                self.assertEqual(tablib.GUITAR[placed[0]] + placed[1], pitch)
            if len(pitches) == 1:
                self.assertIsNotNone(row[0])

    def test_mas_notas_que_cuerdas_no_rompe(self):
        row = tablib.assign([[40, 45, 50, 55, 59, 64, 69, 74]], tablib.GUITAR, 22)[0]
        self.assertEqual(sum(1 for r in row if r is not None), 6)

    def test_el_bajo_se_lleva_a_su_rango(self):
        self.assertEqual(tablib.clamp_pitch(20, tablib.BASS, 20) % 12, 20 % 12)
        self.assertGreaterEqual(tablib.clamp_pitch(20, tablib.BASS, 20), tablib.BASS[0])
        self.assertLessEqual(tablib.clamp_pitch(120, tablib.GUITAR, 22), tablib.GUITAR[-1] + 22)


# ---------- Partitura ----------
MONO = [[0, 4, 64, 80], [4, 2, 66, 80], [6, 2, 67, 80], [8, 6, 69, 80], [14, 2, 71, 80], [16, 4, 72, 80],
        [24, 2, 70, 80], [28, 8, 60, 80], [40, 4, 52, 80], [44, 12, 55, 80]]          # incluye una nota que cruza la barra
PIANO = [[0, 16, 36, 90], [0, 4, 60, 80], [0, 4, 64, 80], [0, 4, 67, 80], [4, 4, 62, 80], [4, 4, 65, 80],
         [4, 4, 69, 80], [8, 8, 72, 80], [16, 16, 43, 90], [16, 6, 76, 80], [22, 2, 74, 80], [24, 8, 72, 80]]
BASS = [[0, 4, 28, 90], [4, 2, 33, 90], [8, 4, 38, 90], [12, 4, 40, 90], [16, 8, 43, 90]]


class ScoreTests(unittest.TestCase):
    def check_score(self, parts, bpm=120, meter=(4, 4), subdiv=4, tab=True):
        xml, info = build_score(parts, bpm, meter, subdiv, title="prueba", with_tab=tab)
        bar_len = bar_divisions(meter, subdiv)
        got, problems, root = read_score(xml, bar_len)
        self.assertEqual(problems, [])
        written = sorted((s, d, p) for (_i, s, d, p) in info["written"])
        self.assertEqual(collections.Counter(got), collections.Counter(written),
                         sorted(set(got) ^ set(written), key=str)[:5])
        tunings = [tablib.TUNINGS.get(p["stem"]) for p in parts]
        self.assertEqual(tab_mismatches(root, tunings) if tab else 0, 0)
        if HAS_MUSIC21:
            from music21 import converter
            self.assertGreaterEqual(len(converter.parse(xml, format="musicxml").parts), len(parts))
        return xml, info

    def test_guitarra_con_tablatura(self):
        _xml, info = self.check_score([{"stem": "guitar", "name": "Guitarra", "notes": MONO}])
        self.assertEqual(info["dropped_notes"], 0)
        self.assertEqual(info["parts"][0]["staves"], 2)

    def test_piano_usa_dos_pentagramas(self):
        _xml, info = self.check_score([{"stem": "piano", "name": "Piano", "notes": PIANO}])
        self.assertEqual(info["parts"][0]["staves"], 2)

    def test_bajo_y_varios_instrumentos(self):
        self.check_score([{"stem": "bass", "name": "Bajo", "notes": BASS}])
        self.check_score([{"stem": "guitar", "name": "G", "notes": MONO}, {"stem": "piano", "name": "P", "notes": PIANO},
                          {"stem": "bass", "name": "B", "notes": BASS}])

    def test_otros_compases_y_rejillas(self):
        melody = [[0, 2, 60, 80], [2, 2, 62, 80], [4, 4, 64, 80], [8, 6, 65, 80], [14, 10, 67, 80]]
        self.check_score([{"stem": "other", "name": "O", "notes": melody}], meter=(3, 4), subdiv=2)
        self.check_score([{"stem": "other", "name": "O", "notes": [[0, 3, 60, 80], [3, 3, 62, 80], [6, 6, 64, 80]]}], meter=(6, 8))
        self.check_score([{"stem": "other", "name": "O", "notes": [[0, 1, 60, 80], [1, 3, 62, 80], [4, 8, 64, 80]]}], subdiv=8)
        self.check_score([{"stem": "guitar", "name": "G", "notes": MONO}], tab=False)

    def test_sin_notas_o_rejilla_invalida(self):
        with self.assertRaises(ValueError):
            build_score([{"stem": "guitar", "name": "G", "notes": []}], 120)
        with self.assertRaises(ValueError):
            build_score([{"stem": "guitar", "name": "G", "notes": MONO}], 120, subdiv=3)

    def test_tonalidad_estimada(self):
        scale = [[i * 4, 4, p, 80] for i, p in enumerate([62, 64, 66, 67, 69, 71, 73, 74])]       # Re mayor
        _xml, info = build_score([{"stem": "other", "name": "O", "notes": scale}], 120)
        self.assertEqual((info["fifths"], info["mode"]), (2, "major"))

    def test_datos_aleatorios(self):
        rng = random.Random(7)
        for trial in range(80):
            subdiv = rng.choice((2, 4, 8))
            meter = rng.choice(((4, 4), (3, 4), (6, 8), (2, 4)))
            bar = bar_divisions(meter, subdiv)
            stem = rng.choice(("guitar", "piano", "bass", "other"))
            lo, hi = {"guitar": (40, 80), "piano": (30, 96), "bass": (28, 60), "other": (50, 90)}[stem]
            notes, t = [], 0
            for _ in range(rng.randint(5, 45)):
                start = t + rng.choice((0, 0, subdiv // 2 or 1, subdiv, subdiv * 2))
                dur = rng.choice((1, 2, 3, subdiv, subdiv * 2, subdiv * 3, subdiv * 4, bar // 2 or 1, bar + 1))
                notes.append([start, max(1, dur), rng.randint(lo, hi), rng.randint(40, 120)])
                t = start + rng.choice((1, subdiv // 2 or 1, subdiv, subdiv * 2))
                if rng.random() < 0.15:
                    notes.append([start, max(1, dur), notes[-1][2] + rng.choice((3, 4, 7)), 80])
            notes.sort(key=lambda n: (n[2], n[0], -n[3]))                 # como quantize(): sin solapes de la misma altura
            cleaned = []
            for n in notes:
                if cleaned and cleaned[-1][2] == n[2]:
                    if n[0] == cleaned[-1][0]:
                        continue
                    if n[0] < cleaned[-1][0] + cleaned[-1][1]:
                        cleaned[-1][1] = n[0] - cleaned[-1][0]
                cleaned.append(n)
            with self.subTest(trial=trial, stem=stem, meter=meter, subdiv=subdiv):
                xml, info = build_score([{"stem": stem, "name": stem, "notes": cleaned}], rng.choice((60, 90, 140)),
                                        meter, subdiv, with_tab=rng.random() < 0.7)
                got, problems, root = read_score(xml, bar)
                self.assertEqual(problems, [])
                written = sorted((s, d, p) for (_i, s, d, p) in info["written"])
                self.assertEqual(collections.Counter(got), collections.Counter(written))
                if info["parts"][0]["tab"]:
                    self.assertEqual(tab_mismatches(root, [tablib.TUNINGS.get(stem)]), 0)
                asked = {(s, p) for s, _d, p, _v in cleaned}
                if stem not in ("guitar", "bass"):                          # (la tablatura cambia de octava)
                    self.assertTrue(all((s, p) in asked for _i, s, _d, p in info["written"]))


if __name__ == "__main__":
    unittest.main()
