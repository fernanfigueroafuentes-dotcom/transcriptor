"use strict";
/* Teoría de acordes y diagramas SVG para guitarra y piano.
 *
 * Los diagramas se calculan a partir del nombre del acorde, así que sirven para
 * cualquier transposición. La digitación de guitarra se busca por fuerza bruta:
 * entre todas las combinaciones playables se elige la más cómoda (raíz en el bajo,
 * posición baja, cuerdas al aire y pocos dedos).
 */
const ChordDiagrams = (() => {
  const SHARP = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
  const FLAT = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"];

  // Calidad -> intervalos (semitonos desde la raíz)
  const QUALITIES = {
    "": [0, 4, 7], m: [0, 3, 7],
    "7": [0, 4, 7, 10], maj7: [0, 4, 7, 11], m7: [0, 3, 7, 10],
    dim: [0, 3, 6], dim7: [0, 3, 6, 9], m7b5: [0, 3, 6, 10], aug: [0, 4, 8],
    sus2: [0, 2, 7], sus4: [0, 5, 7],
    "6": [0, 4, 7, 9], m6: [0, 3, 7, 9], "m(maj7)": [0, 3, 7, 11],
  };
  const OPEN_STRINGS = [40, 45, 50, 55, 59, 64]; // E2 A2 D3 G3 B3 E4 (de grave a aguda)

  const noteName = (pc, useFlats) => (useFlats ? FLAT : SHARP)[((pc % 12) + 12) % 12];

  /** 'Ebm' -> { name, rootPc, quality, intervals, pcs, approx } o null si no se reconoce. */
  function parse(name) {
    const m = /^([A-G])([#b]?)(.*)$/.exec(name || "");
    if (!m) return null;
    let rootPc = SHARP.indexOf(m[1] + m[2]);
    if (rootPc < 0) rootPc = FLAT.indexOf(m[1] + m[2]);
    if (rootPc < 0) return null;
    let quality = m[3];
    let approx = false;
    if (!Object.prototype.hasOwnProperty.call(QUALITIES, quality)) {
      approx = true;                                   // calidad desconocida: tríada aproximada
      quality = /^m(?!aj)/.test(quality) ? "m" : "";
    }
    const intervals = QUALITIES[quality];
    return {
      name, rootPc, quality, intervals, approx,
      pcs: new Set(intervals.map((i) => (rootPc + i) % 12)),
    };
  }

  // ---------- Digitación de guitarra ----------
  const cache = new Map();

  // Digitaciones abiertas estándar (cuerdas de grave a aguda; x = muda)
  const OPEN = {
    C: "x32010", D: "xx0232", E: "022100", G: "320003", A: "x02220",
    Am: "x02210", Dm: "xx0231", Em: "022000",
    C7: "x32310", D7: "xx0212", E7: "020100", G7: "320001", A7: "x02020", B7: "x21202",
    Am7: "x02010", Dm7: "xx0211", Em7: "020000",
    Cmaj7: "x32000", Dmaj7: "xx0222", Emaj7: "021100", Fmaj7: "xx3210", Gmaj7: "320002", Amaj7: "x02120",
    Asus2: "x02200", Asus4: "x02230", Dsus2: "xx0230", Dsus4: "xx0233", Esus4: "022200",
  };

  // Formas móviles: cada cifra es el desplazamiento respecto al traste de la raíz.
  // Forma de Mi: raíz en la cuerda 6. Forma de La: raíz en la cuerda 5.
  const E_SHAPES = {
    "": "022100", m: "022000", "7": "020100", m7: "020000", maj7: "021100",
    sus4: "022200", "6": "022120", m6: "022020", aug: "032110",
  };
  const A_SHAPES = {
    "": "x02220", m: "x02210", "7": "x02020", m7: "x02010", maj7: "x02120",
    sus4: "x02230", sus2: "x02200", "6": "x02222", m6: "x02212",
    dim: "x0121x", m7b5: "x0101x", dim7: "x01212", aug: "x0322x", "m(maj7)": "x02110",
  };
  const toFrets = (s) => [...s].map((c) => (c === "x" ? -1 : Number(c)));

  function openVoicing(info) {
    const shape = OPEN[SHARP[info.rootPc] + info.quality];
    return shape ? { frets: toFrets(shape), barre: null, fingers: 0 } : null;
  }

  /** Forma de Mi o de La desplazada hasta la raíz; gana la de posición más baja. */
  function templateVoicing(info) {
    const candidates = [];
    const eShape = E_SHAPES[info.quality];
    const aShape = A_SHAPES[info.quality];
    if (eShape) candidates.push({ f: (info.rootPc - 4 + 12) % 12, offsets: toFrets(eShape) });
    if (aShape) candidates.push({ f: (info.rootPc - 9 + 12) % 12, offsets: toFrets(aShape) });
    if (!candidates.length) return null;
    candidates.sort((a, b) => a.f - b.f);
    const { f, offsets } = candidates[0];
    const frets = offsets.map((o) => (o < 0 ? -1 : o + f));

    let barre = null;
    if (f >= 1) {                       // cejilla si hay 4+ cuerdas de ancho a la altura de la raíz
      const atRoot = offsets.map((o, i) => (o === 0 ? i : -1)).filter((i) => i >= 0);
      if (atRoot.length >= 2 && atRoot[atRoot.length - 1] - atRoot[0] >= 3) {
        barre = { fret: f, from: atRoot[0], to: atRoot[atRoot.length - 1] };
      }
    }
    return { frets, barre, fingers: 0 };
  }

  function voicing(info) {
    const key = info.rootPc + "|" + info.quality;
    if (!cache.has(key)) {
      cache.set(key, openVoicing(info) || templateVoicing(info) || searchVoicing(info));
    }
    return cache.get(key);
  }

  // ---------- Todas las posiciones: formas CAGED ----------
  // Acorde abierto de cada forma: [letra, raíz (pc), trastes]. Al subir k trastes, todas las
  // notas suben k semitonos: las cuerdas al aire pasan a ser la cejilla y se obtiene el mismo
  // acorde en otra zona del mástil.
  const CAGED = {
    "": [["C", 0, "x32010"], ["A", 9, "x02220"], ["G", 7, "320003"], ["E", 4, "022100"], ["D", 2, "xx0232"]],
    m: [["C", 0, "x31013"], ["A", 9, "x02210"], ["G", 7, "310033"], ["E", 4, "022000"], ["D", 2, "xx0231"]],
    "7": [["C", 0, "x32310"], ["A", 9, "x02020"], ["G", 7, "320001"], ["E", 4, "020100"], ["D", 2, "xx0212"]],
    m7: [["C", 0, "x31313"], ["A", 9, "x02010"], ["G", 7, "310031"], ["E", 4, "020000"], ["D", 2, "xx0211"]],
    maj7: [["C", 0, "x32000"], ["A", 9, "x02120"], ["G", 7, "320002"], ["E", 4, "021100"], ["D", 2, "xx0222"]],
  };

  const positionOf = (frets) => {
    const fretted = frets.filter((f) => f > 0);
    return fretted.length ? Math.min(...fretted) : 0;
  };

  function cagedVoicings(info) {
    return (CAGED[info.quality] || []).map(([letter, openRoot, text]) => {
      const k = (info.rootPc - openRoot + 12) % 12;
      const open = toFrets(text);
      const frets = open.map((f) => (f < 0 ? -1 : f + k));
      let barre = null;
      if (k > 0) {
        const opens = open.map((f, i) => (f === 0 ? i : -1)).filter((i) => i >= 0);
        if (opens.length >= 2) barre = { fret: k, from: opens[0], to: opens[opens.length - 1] };
      }
      return { frets, barre, shape: `Forma ${letter}` };
    });
  }

  const listCache = new Map();

  /** Todas las digitaciones útiles: la principal primero y el resto de menor a mayor posición. */
  function voicings(info) {
    const key = info.rootPc + "|" + info.quality;
    if (listCache.has(key)) return listCache.get(key);
    const caged = cagedVoicings(info);
    const primary = voicing(info);
    const out = [];
    const seen = new Set();
    const push = (v, shape) => {
      if (!v) return;
      const id = v.frets.join(",");
      if (seen.has(id)) return;
      seen.add(id);
      const pos = positionOf(v.frets);
      const where = v.frets.includes(0) ? "abierta" : `traste ${pos}`;
      out.push({ frets: v.frets, barre: v.barre, pos, label: `${shape} · ${where}` });
    };
    if (primary) {
      const same = caged.find((c) => c.frets.join(",") === primary.frets.join(","));
      push(primary, same ? same.shape : "Estándar");
    }
    caged.sort((a, b) => positionOf(a.frets) - positionOf(b.frets)).forEach((c) => push(c, c.shape));
    listCache.set(key, out);
    return out;
  }

  // ---------- Piano: inversiones ----------
  /** Una entrada por inversión (fundamental, 1.ª, 2.ª y 3.ª si hay séptima). */
  function pianoVoicings(info) {
    const chordPcs = info.intervals.map((i) => (info.rootPc + i) % 12);
    return chordPcs.map((_, inv) => {
      const order = [...chordPcs.slice(inv), ...chordPcs.slice(0, inv)];   // de grave a aguda
      const notes = [order[0]];
      for (let j = 1; j < order.length; j++) {
        let q = order[j];
        while (q <= notes[j - 1]) q += 12;
        notes.push(q);
      }
      return {
        notes,                                       // posiciones en semitonos desde un Do (0..22)
        rootIndex: order.indexOf(info.rootPc),
        bassPc: order[0],
        label: inv === 0 ? "Fundamental" : `${inv}.ª inversión`,
      };
    });
  }

  function searchVoicing(info) {
    const { rootPc, pcs, intervals } = info;
    const required = new Set(pcs);
    if (intervals.length >= 4) required.delete((rootPc + 7) % 12); // la quinta justa es opcional
    let best = null;
    let bestScore = Infinity;
    const frets = new Array(6);

    function evaluate() {
      const played = [];
      for (let i = 0; i < 6; i++) if (frets[i] >= 0) played.push(i);
      if (played.length < 4) return;
      if (played[played.length - 1] - played[0] + 1 !== played.length) return; // sin huecos mudos

      const notes = new Set(played.map((i) => (OPEN_STRINGS[i] + frets[i]) % 12));
      for (const pc of required) if (!notes.has(pc)) return;

      const bassPc = (OPEN_STRINGS[played[0]] + frets[played[0]]) % 12;
      const fretted = played.filter((i) => frets[i] > 0);
      const fmin = fretted.length ? Math.min(...fretted.map((i) => frets[i])) : 0;
      const fmax = fretted.length ? Math.max(...fretted.map((i) => frets[i])) : 0;
      if (fmax - fmin > 3) return;

      // Cejilla: 4 o más cuerdas seguidas desde el traste más bajo, sin cuerdas al aire dentro
      let barre = null;
      let fingers = fretted.length;
      const atMin = fretted.filter((i) => frets[i] === fmin);
      if (atMin.length >= 2) {
        const from = atMin[0];
        const to = atMin[atMin.length - 1];
        const openInside = played.some((i) => i > from && i < to && frets[i] === 0);
        if (to - from >= 3 && !openInside) {
          barre = { fret: fmin, from, to };
          fingers = 1 + fretted.filter((i) => frets[i] > fmin).length;
        }
      }
      if (fingers > 4) return;

      // Cejilla "fallida": el traste más bajo se repite en dos cuerdas con otras notas más
      // altas entre ellas y sin cejilla. Obligaría a usar dos dedos en el mismo traste
      // cruzados por otros dedos; en esos casos lo normal es hacer cejilla.
      let failedBarre = 0;
      if (!barre) {
        for (let a = 0; a < atMin.length - 1 && !failedBarre; a++) {
          for (let k = atMin[a] + 1; k < atMin[a + 1]; k++) {
            if (frets[k] > fmin) { failedBarre = 10; break; }
          }
        }
      }

      const opens = played.filter((i) => frets[i] === 0).length;
      const score =
        (bassPc !== rootPc ? 200 : 0) +      // inversión: solo si no hay otra opción
        (6 - played.length) * 4 +            // cuerdas mudas
        fmin * 3 +                           // posición alta
        (barre ? 5 : 0) +
        fingers * 2 -
        opens * 2 +                          // cuerdas al aire: más cómodo
        (fmax - fmin) +
        (fmax - fmin === 3 ? 10 : 0) +       // estiramiento de 4 trastes
        failedBarre;
      if (score < bestScore) {
        bestScore = score;
        best = { frets: frets.slice(), barre, fingers };
      }
    }

    for (let base = 1; base <= 10; base++) {
      const options = OPEN_STRINGS.map((open) => {
        const o = [-1];
        if (pcs.has(open % 12)) o.push(0);
        for (let f = base; f <= base + 3; f++) if (pcs.has((open + f) % 12)) o.push(f);
        return o;
      });
      const rec = (s) => {
        if (s === 6) { evaluate(); return; }
        for (const f of options[s]) { frets[s] = f; rec(s + 1); }
      };
      rec(0);
    }
    return best;
  }

  // ---------- SVG ----------
  const NS = "http://www.w3.org/2000/svg";
  function svg(tag, attrs, text) {
    const e = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs || {})) e.setAttribute(k, String(v));
    if (text != null) e.textContent = text;
    return e;
  }

  /** Diagrama de mástil. `v` viene de voicing(); devuelve un <svg>. */
  function guitarSVG(v, rootPc, name) {
    const sx = (i) => 18 + i * 11.5;     // x de la cuerda i (0 = la más grave)
    const top = 26, rh = 14, rows = 5;
    const root = svg("svg", {
      viewBox: "0 0 84 106", class: "dgm guitar", role: "img",
      "aria-label": `Guitarra, ${name}: ` + v.frets.map((f) => (f < 0 ? "x" : f)).join(" "),
    });

    const fretted = v.frets.filter((f) => f > 0);
    const fmin = fretted.length ? Math.min(...fretted) : 1;
    const fmax = fretted.length ? Math.max(...fretted) : 1;
    const base = fmax <= 5 ? 1 : fmin;   // desde qué traste se dibuja

    for (let r = 0; r <= rows; r++) {
      root.append(svg("line", { class: "ln", x1: sx(0), x2: sx(5), y1: top + r * rh, y2: top + r * rh }));
    }
    for (let i = 0; i < 6; i++) {
      root.append(svg("line", { class: "ln", x1: sx(i), x2: sx(i), y1: top, y2: top + rows * rh }));
    }
    if (base === 1) {
      root.append(svg("rect", { class: "nut", x: sx(0) - 0.5, y: top - 3, width: sx(5) - sx(0) + 1, height: 3.5 }));
    } else {
      root.append(svg("text", { class: "fretnum", x: 2, y: top + rh / 2 + 3.5 }, base + "fr"));
    }

    const isRoot = (i, f) => (OPEN_STRINGS[i] + f) % 12 === rootPc;
    const rowY = (f) => top + (f - base) * rh + rh / 2;

    v.frets.forEach((f, i) => {
      if (f < 0) {
        root.append(svg("path", {
          class: "mute",
          d: `M${sx(i) - 3} 11 L${sx(i) + 3} 17 M${sx(i) + 3} 11 L${sx(i) - 3} 17`,
        }));
      } else if (f === 0) {
        root.append(svg("circle", { class: "open" + (isRoot(i, 0) ? " root" : ""), cx: sx(i), cy: 14, r: 3 }));
      }
    });
    if (v.barre) {
      root.append(svg("rect", {
        class: "dot", x: sx(v.barre.from) - 5, y: rowY(v.barre.fret) - 4.5,
        width: sx(v.barre.to) - sx(v.barre.from) + 10, height: 9, rx: 4.5,
      }));
    }
    v.frets.forEach((f, i) => {
      if (f <= 0) return;
      const underBarre = v.barre && f === v.barre.fret && i >= v.barre.from && i <= v.barre.to;
      if (underBarre && !isRoot(i, f)) return;
      root.append(svg("circle", {
        class: "dot" + (isRoot(i, f) ? " root" : ""), cx: sx(i), cy: rowY(f), r: 4.6,
      }));
    });
    return root;
  }

  /** Teclado de dos octavas con las notas del acorde (en estado fundamental). */
  function pianoSVG(info, useFlats, inversion = 0) {
    const W = 15, H = 58, BW = 9, BH = 36, whites = 14;
    const WHITE_PC = [0, 2, 4, 5, 7, 9, 11];
    const BLACK = { 1: 1, 3: 2, 6: 4, 8: 5, 10: 6 };  // pc -> índice de la blanca a su derecha

    const list = pianoVoicings(info);
    const pv = list[inversion] || list[0];
    const semitones = pv.notes;                                       // 0..22
    const pressed = new Map(semitones.map((s, k) => [s, k === pv.rootIndex ? "root" : "on"]));
    const names = semitones.map((s) => noteName(s, useFlats));

    const root = svg("svg", {
      viewBox: `0 0 ${W * whites} ${H + 1}`, class: "dgm piano", role: "img",
      "aria-label": `Piano, ${info.name}, ${pv.label}: ${names.join(" ")}`,
    });

    for (let w = 0; w < whites; w++) {
      const semi = Math.floor(w / 7) * 12 + WHITE_PC[w % 7];
      const st = pressed.get(semi);
      root.append(svg("rect", { class: "wk" + (st ? " " + st : ""), x: w * W, y: 0, width: W, height: H, rx: 1.5 }));
      if (st) {
        root.append(svg("text", { class: "kl", x: w * W + W / 2, y: H - 5, "text-anchor": "middle" }, noteName(semi, useFlats)));
      }
    }
    for (let o = 0; o < 2; o++) {
      for (const [pcStr, right] of Object.entries(BLACK)) {
        const semi = o * 12 + Number(pcStr);
        const st = pressed.get(semi);
        const x = (o * 7 + right) * W - BW / 2;
        root.append(svg("rect", { class: "bk" + (st ? " " + st : ""), x, y: 0, width: BW, height: BH, rx: 1.2 }));
        if (st) {
          root.append(svg("text", { class: "kl blk", x: x + BW / 2, y: BH - 5, "text-anchor": "middle" }, noteName(semi, useFlats)));
        }
      }
    }
    return root;
  }

  return { parse, voicing, voicings, pianoVoicings, guitarSVG, pianoSVG, noteName };
})();
