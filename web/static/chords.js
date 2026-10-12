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

  // Catálogo de calidades:
  //   [sufijo, intervalos (semitonos desde la raíz), opcionales, grupo, nombre, extensiones]
  // - opcionales: notas que la guitarra puede omitir (p. ej. la quinta justa).
  // - extensiones: intervalos que en el piano se tocan una octava más arriba (9, 11, 13...).
  const CATALOG = [
    ["", [0, 4, 7], [], "Tríadas", "mayor", []],
    ["m", [0, 3, 7], [], "Tríadas", "menor", []],
    ["dim", [0, 3, 6], [], "Tríadas", "disminuido", []],
    ["aug", [0, 4, 8], [], "Tríadas", "aumentado", []],
    ["sus2", [0, 2, 7], [], "Suspendidos", "suspendido 2", []],
    ["sus4", [0, 5, 7], [], "Suspendidos", "suspendido 4", []],
    ["7sus4", [0, 5, 7, 10], [7], "Suspendidos", "7 suspendido 4", []],
    ["9sus4", [0, 2, 5, 7, 10], [7], "Suspendidos", "9 suspendido 4", [2]],
    ["6", [0, 4, 7, 9], [7], "Sextas", "sexta", []],
    ["m6", [0, 3, 7, 9], [7], "Sextas", "menor sexta", []],
    ["6/9", [0, 2, 4, 7, 9], [7], "Sextas", "sexta con novena", [2]],
    ["m6/9", [0, 2, 3, 7, 9], [7], "Sextas", "menor sexta con novena", [2]],
    ["7", [0, 4, 7, 10], [7], "Séptimas", "dominante 7", []],
    ["maj7", [0, 4, 7, 11], [7], "Séptimas", "mayor 7", []],
    ["m7", [0, 3, 7, 10], [7], "Séptimas", "menor 7", []],
    ["m(maj7)", [0, 3, 7, 11], [7], "Séptimas", "menor con 7 mayor", []],
    ["dim7", [0, 3, 6, 9], [], "Séptimas", "disminuido 7", []],
    ["m7b5", [0, 3, 6, 10], [], "Séptimas", "semidisminuido (m7♭5)", []],
    ["7b5", [0, 4, 6, 10], [], "Séptimas", "7♭5", []],
    ["7#5", [0, 4, 8, 10], [], "Séptimas", "7♯5 (aumentado 7)", []],
    ["maj7#5", [0, 4, 8, 11], [], "Séptimas", "mayor 7♯5", []],
    ["add9", [0, 2, 4, 7], [7], "Novenas", "con novena añadida", [2]],
    ["madd9", [0, 2, 3, 7], [7], "Novenas", "menor con novena añadida", [2]],
    ["9", [0, 2, 4, 7, 10], [7], "Novenas", "dominante 9", [2]],
    ["maj9", [0, 2, 4, 7, 11], [7], "Novenas", "mayor 9", [2]],
    ["m9", [0, 2, 3, 7, 10], [7], "Novenas", "menor 9", [2]],
    ["7b9", [0, 1, 4, 7, 10], [7], "Alterados", "7♭9", [1]],
    ["7#9", [0, 3, 4, 7, 10], [7], "Alterados", "7♯9", [3]],
    ["7#5b9", [0, 1, 4, 8, 10], [], "Alterados", "7♯5♭9", [1]],
    ["7#5#9", [0, 3, 4, 8, 10], [], "Alterados", "7♯5♯9", [3]],
    ["7b13", [0, 4, 7, 8, 10], [7], "Alterados", "7♭13", [8]],
    ["7#11", [0, 4, 6, 7, 10], [7], "Alterados", "7♯11", [6]],
    ["maj7#11", [0, 4, 6, 7, 11], [7], "Alterados", "mayor 7♯11", [6]],
    ["11", [0, 2, 4, 5, 7, 10], [7, 4, 2], "Oncenas y trecenas", "dominante 11", [2, 5]],
    ["m11", [0, 2, 3, 5, 7, 10], [7, 2], "Oncenas y trecenas", "menor 11", [2, 5]],
    ["13", [0, 2, 4, 7, 9, 10], [7, 2], "Oncenas y trecenas", "dominante 13", [2, 9]],
    ["maj13", [0, 2, 4, 7, 9, 11], [7, 2], "Oncenas y trecenas", "mayor 13", [2, 9]],
    ["m13", [0, 2, 3, 7, 9, 10], [7, 2], "Oncenas y trecenas", "menor 13", [2, 9]],
  ];
  const META = Object.fromEntries(CATALOG.map(([suffix, intervals, optional, , , up]) => [suffix, { intervals, optional, up }]));
  const QUALITY_LIST = CATALOG.map(([suffix, , , group, label]) => ({ suffix, group, label }));

  // Otras formas de escribir la misma calidad -> sufijo canónico
  const ALIASES = {
    min: "m", "-": "m", mi: "m", maj: "", M: "", major: "", minor: "m",
    M7: "maj7", Maj7: "maj7", "Δ": "maj7", "Δ7": "maj7", "△": "maj7",
    min7: "m7", "-7": "m7", mi7: "m7", min6: "m6", "-6": "m6",
    "°": "dim", o: "dim", "°7": "dim7", o7: "dim7",
    "ø": "m7b5", "ø7": "m7b5", hdim: "m7b5", hdim7: "m7b5", "m7-5": "m7b5",
    minmaj7: "m(maj7)", mM7: "m(maj7)", mMaj7: "m(maj7)", "m#7": "m(maj7)",
    "+": "aug", "+7": "7#5", aug7: "7#5", "7+5": "7#5", "7-5": "7b5", "7-9": "7b9", "7+9": "7#9", "7+11": "7#11",
    sus: "sus4", "7sus": "7sus4", "9sus": "9sus4", add2: "add9", "69": "6/9", "6add9": "6/9", "m69": "m6/9",
    M9: "maj9", Maj9: "maj9", min9: "m9", min11: "m11", M13: "maj13", Maj13: "maj13", min13: "m13",
  };
  const has = (obj, key) => Object.prototype.hasOwnProperty.call(obj, key);

  const OPEN_STRINGS = [40, 45, 50, 55, 59, 64]; // E2 A2 D3 G3 B3 E4 (de grave a aguda)

  const noteName = (pc, useFlats) => (useFlats ? FLAT : SHARP)[((pc % 12) + 12) % 12];

  /** 'Ebm7b5' -> { name, rootPc, quality, intervals, optional, up, pcs, approx } o null. */
  function parse(name) {
    const text = String(name || "").replace(/♯/g, "#").replace(/♭/g, "b");
    const m = /^([A-G])([#b]?)(.*)$/.exec(text);
    if (!m) return null;
    let rootPc = SHARP.indexOf(m[1] + m[2]);
    if (rootPc < 0) rootPc = FLAT.indexOf(m[1] + m[2]);
    if (rootPc < 0) return null;
    let quality = m[3].trim();
    let approx = false;
    if (has(META, quality)) {
      // canónica
    } else if (has(ALIASES, quality)) {
      quality = ALIASES[quality];
    } else {
      approx = true;                                   // calidad desconocida: tríada aproximada
      quality = /^m(?!aj)/.test(quality) ? "m" : "";
    }
    const { intervals, optional, up } = META[quality];
    return {
      name, rootPc, quality, intervals, approx, up,
      optional: new Set(optional.map((i) => (rootPc + i) % 12)),
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

  // ---------- Formas móviles generadas para cualquier calidad ----------
  // Para cada calidad y cuerda de la raíz (6.ª, 5.ª o 4.ª) se buscan digitaciones compactas
  // sin cuerdas al aire: la raíz es el bajo, entran todas las notas imprescindibles
  // (las "opcionales" pueden omitirse), como mucho un hueco mudo, ancho de 4 trastes y
  // 4 dedos. La forma se guarda como desplazamientos respecto al traste de la raíz y se
  // traslada a cualquier tono.
  const REF_FRET = 7;
  const movableCache = new Map();

  function movableShapes(quality, rootString) {
    const key = quality + "|" + rootString;
    if (movableCache.has(key)) return movableCache.get(key);

    const meta = META[quality];
    const refRoot = (OPEN_STRINGS[rootString] + REF_FRET) % 12;
    const pcs = new Set(meta.intervals.map((i) => (refRoot + i) % 12));
    const optional = new Set(meta.optional.map((i) => (refRoot + i) % 12));
    const required = [...pcs].filter((pc) => !optional.has(pc));
    const minPlayed = meta.intervals.length >= 4 ? 4 : 3;

    const frets = new Array(6).fill(-1);
    frets[rootString] = REF_FRET;
    const options = [];
    for (let i = rootString + 1; i < 6; i++) {
      const o = [-1];
      for (let f = REF_FRET - 2; f <= REF_FRET + 3; f++) {
        if (pcs.has((OPEN_STRINGS[i] + f) % 12)) o.push(f);
      }
      options[i] = o;
    }

    const bySignature = new Map();   // mejor forma por conjunto de cuerdas tocadas
    function evaluate() {
      const played = [];
      for (let i = rootString; i < 6; i++) if (frets[i] >= 0) played.push(i);
      if (played.length < minPlayed) return;
      const holes = played[played.length - 1] - rootString + 1 - played.length;
      if (holes > 1) return;
      const notes = new Set(played.map((i) => (OPEN_STRINGS[i] + frets[i]) % 12));
      for (const pc of required) if (!notes.has(pc)) return;

      const used = played.map((i) => frets[i]);
      const fmin = Math.min(...used);
      const fmax = Math.max(...used);
      if (fmax - fmin > 3) return;

      // Dedos: una cejilla (2+ cuerdas al traste más bajo, sin mudas dentro) cuenta como uno
      const atMin = played.filter((i) => frets[i] === fmin);
      let fingers = played.length;
      if (atMin.length >= 2) {
        const from = atMin[0];
        const to = atMin[atMin.length - 1];
        let mutedInside = false;
        for (let i = from + 1; i < to; i++) if (frets[i] < 0) mutedInside = true;
        if (!mutedInside) fingers = 1 + played.filter((i) => frets[i] > fmin).length;
      }
      if (fingers > 4) return;

      const score = (fmax - fmin) * 3 + holes * 3 + fingers + Math.abs(played.length - 5) * 1.5;
      const sig = played.join("");
      const prev = bySignature.get(sig);
      if (!prev || score < prev.score) {
        bySignature.set(sig, {
          score,
          offsets: frets.map((f) => (f < 0 ? null : f - REF_FRET)),
        });
      }
    }
    const rec = (i) => {
      if (i === 6) { evaluate(); return; }
      for (const f of options[i]) { frets[i] = f; rec(i + 1); }
    };
    rec(rootString + 1);

    // Las 3 mejores formas con distinto conjunto de cuerdas
    const best = [...bySignature.values()].sort((a, b) => a.score - b.score).slice(0, 3);
    movableCache.set(key, best);
    return best;
  }

  /** Formas móviles trasladadas a la raíz del acorde. */
  function movableVoicings(info) {
    const out = [];
    for (let s = 0; s < 3; s++) {
      for (const shape of movableShapes(info.quality, s)) {
        const offs = shape.offsets.filter((o) => o !== null);
        let root = (((info.rootPc - OPEN_STRINGS[s]) % 12) + 12) % 12;   // traste de la raíz
        if (root + Math.min(...offs) < 1) root += 12;                    // sin cuerdas al aire
        if (root + Math.max(...offs) > 17) continue;
        const frets = shape.offsets.map((o) => (o === null ? -1 : root + o));

        const fretted = frets.map((f, i) => (f > 0 ? i : -1)).filter((i) => i >= 0);
        const fmin = Math.min(...fretted.map((i) => frets[i]));
        const atMin = fretted.filter((i) => frets[i] === fmin);
        let barre = null;
        if (atMin.length >= 3) {
          const from = atMin[0];
          const to = atMin[atMin.length - 1];
          const mutedInside = frets.some((f, i) => i > from && i < to && f < 0);
          if (!mutedInside) barre = { fret: fmin, from, to };
        }
        out.push({ frets, barre, shape: `Raíz en la ${6 - s}.ª cuerda` });
      }
    }
    return out.sort((a, b) => positionOf(a.frets) - positionOf(b.frets));
  }

  function voicing(info) {
    const key = info.rootPc + "|" + info.quality;
    if (!cache.has(key)) {
      cache.set(
        key,
        openVoicing(info) || templateVoicing(info) || movableVoicings(info)[0] || searchVoicing(info),
      );
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
      push(primary, same ? same.shape : primary.shape || "Estándar");
    }
    caged.sort((a, b) => positionOf(a.frets) - positionOf(b.frets)).forEach((c) => push(c, c.shape));
    // Las calidades fuera de CAGED añaden las formas móviles generadas
    if (!CAGED[info.quality]) movableVoicings(info).forEach((v) => push(v, v.shape));
    listCache.set(key, out);
    return out;
  }

  // ---------- Piano: inversiones ----------
  const PIANO_MAX = 35;      // último semitono del teclado (3 octavas desde un Do)

  /**
   * Una entrada por inversión que quepa en el teclado. En estado fundamental las notas
   * van apiladas de grave a aguda y las extensiones (9, 11, 13...) una octava arriba, como
   * se tocan en la práctica. Cada inversión sube una octava la nota más grave.
   */
  function pianoVoicings(info) {
    const raised = new Set(info.up);
    const base = info.intervals
      .map((iv) => info.rootPc + iv + (raised.has(iv) ? 12 : 0))
      .sort((a, b) => a - b);
    const out = [];
    for (let inv = 0; inv < base.length; inv++) {
      const notes = base.map((n, k) => (k < inv ? n + 12 : n)).sort((a, b) => a - b);
      if (notes[notes.length - 1] > PIANO_MAX) break;
      out.push({
        notes,                                       // posiciones en semitonos desde un Do
        rootIndex: notes.findIndex((n) => n % 12 === info.rootPc),
        bassPc: notes[0] % 12,
        label: inv === 0 ? "Fundamental" : `${inv}.ª inversión`,
      });
    }
    return out;
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

  /** Teclado de 2 octavas (3 si el acorde las necesita) con las notas de la inversión elegida. */
  function pianoSVG(info, useFlats, inversion = 0) {
    const W = 15, H = 58, BW = 9, BH = 36;
    const WHITE_PC = [0, 2, 4, 5, 7, 9, 11];
    const BLACK = { 1: 1, 3: 2, 6: 4, 8: 5, 10: 6 };  // pc -> índice de la blanca a su derecha

    const list = pianoVoicings(info);
    const pv = list[inversion] || list[0];
    const semitones = pv.notes;
    const octaves = Math.max(2, Math.ceil((Math.max(...semitones) + 1) / 12));
    const whites = 7 * octaves;
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
    for (let o = 0; o < octaves; o++) {
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

  return { parse, voicing, voicings, pianoVoicings, guitarSVG, pianoSVG, noteName, QUALITY_LIST };
})();
