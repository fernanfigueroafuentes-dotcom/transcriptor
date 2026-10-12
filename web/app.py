"""API y archivos estáticos del visor.

    GET /api/songs        lista de canciones procesadas
    GET /api/songs/{id}   letra con tiempos, acordes y URL del audio
    PUT /api/songs/{id}/chords     guarda los acordes corregidos (chords.edit.json; el original no se toca)
    DELETE /api/songs/{id}/chords  vuelve a los acordes detectados
    GET /media/{id}/audio audio original (con soporte de Range para saltar en el reproductor)
    GET /media/{id}/mix/{pista}.m4a  pista separada comprimida, para el mezclador
    GET /healthz          comprobación de salud (sin autenticación y sin datos)

Variables de entorno:
    SONGS_DIR        carpeta con las canciones (por defecto, ./songs)
    VIEWER_USER      usuario y contraseña de acceso (HTTP Basic). Si ambas están definidas,
    VIEWER_PASSWORD  TODAS las rutas, salvo /healthz, exigen autenticación.
    REQUIRE_AUTH=1   no arranca si faltan las credenciales (lo usa la imagen de Docker)
    CHORD_EDITS=0    impide guardar correcciones de acordes en el servidor (también si la carpeta
                     de canciones es de solo lectura; el visor las guarda entonces en el navegador)
"""
import asyncio
import base64
import binascii
import json
import os
import re
import secrets
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .midi import cut_notes, write_midi, write_midi_grid
from .musicxml import build_score
from .quantize import ALLOWED_SUBDIV, bar_divisions, grid_fit, quantize

ROOT = Path(__file__).resolve().parent.parent
SONGS_DIR = Path(os.environ.get("SONGS_DIR") or ROOT / "songs")
STATIC_DIR = Path(__file__).resolve().parent / "static"

ID_RE = re.compile(r"^[\w\-]+$")
AUDIO_EXTS = (".mp3", ".m4a", ".wav", ".flac", ".ogg", ".opus", ".aac")

AUTH_USER = os.environ.get("VIEWER_USER", "")
AUTH_PASSWORD = os.environ.get("VIEWER_PASSWORD", "")
AUTH_ENABLED = bool(AUTH_USER and AUTH_PASSWORD)
if os.environ.get("REQUIRE_AUTH") == "1" and not AUTH_ENABLED:
    raise RuntimeError("REQUIRE_AUTH=1 pero faltan VIEWER_USER y VIEWER_PASSWORD")

app = FastAPI(title="Transcriptor", docs_url=None, redoc_url=None, openapi_url=None)


def _credentials_ok(header: str) -> bool:
    """Valida la cabecera Authorization: Basic ... sin revelar por tiempo qué campo falló."""
    if not header.lower().startswith("basic "):
        return False
    try:
        decoded = base64.b64decode(header[6:].strip(), validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return False
    user, _, password = decoded.partition(":")
    user_ok = secrets.compare_digest(user.encode(), AUTH_USER.encode())
    password_ok = secrets.compare_digest(password.encode(), AUTH_PASSWORD.encode())
    return user_ok and password_ok


@app.middleware("http")
async def protect(request: Request, call_next):
    if AUTH_ENABLED and request.url.path != "/healthz":
        if not _credentials_ok(request.headers.get("authorization", "")):
            await asyncio.sleep(1)       # frena la fuerza bruta
            return Response(
                "Autenticación requerida", status_code=401,
                headers={"WWW-Authenticate": 'Basic realm="Transcriptor", charset="UTF-8"'},
            )
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    path = request.url.path
    if (path == "/" or path.endswith((".html", ".js", ".css"))) and not path.startswith("/vendor/"):
        # El visor cambia con cada versión: que el navegador pregunte siempre (304 si no cambió)
        response.headers.setdefault("Cache-Control", "no-cache")
    return response


@app.get("/healthz")
def healthz():
    return {"ok": True}


def _song_dir(song_id: str) -> Path:
    """Valida el id y devuelve la carpeta de la canción (sin salir de SONGS_DIR)."""
    if not ID_RE.match(song_id):
        raise HTTPException(404, "Canción no encontrada")
    path = (SONGS_DIR / song_id).resolve()
    if path.parent != SONGS_DIR.resolve() or not path.is_dir():
        raise HTTPException(404, "Canción no encontrada")
    return path


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))  # tolera BOM
    except (OSError, ValueError):
        return default


def _audio_file(song_dir: Path) -> Path | None:
    meta = _read_json(song_dir / "meta.json", {})
    name = meta.get("audio")
    if name and (song_dir / name).is_file() and (song_dir / name).suffix.lower() in AUDIO_EXTS:
        return song_dir / name
    for ext in AUDIO_EXTS:
        candidate = song_dir / f"audio{ext}"
        if candidate.is_file():
            return candidate
    return None


def _is_song(path: Path) -> bool:
    return path.is_dir() and (path / "lyrics.json").is_file() and (path / "chords.json").is_file()


@app.get("/api/songs")
def list_songs():
    songs = []
    if SONGS_DIR.is_dir():
        for path in sorted(SONGS_DIR.iterdir(), key=lambda p: p.name):
            if _is_song(path) and ID_RE.match(path.name):
                meta = _read_json(path / "meta.json", {})
                songs.append({
                    "id": path.name,
                    "title": meta.get("title") or path.name,
                    "has_audio": _audio_file(path) is not None,
                })
    return songs


@app.get("/api/songs/{song_id}")
def get_song(song_id: str):
    song_dir = _song_dir(song_id)
    if not _is_song(song_dir):
        raise HTTPException(404, "Canción incompleta")
    meta = _read_json(song_dir / "meta.json", {})
    edited = _read_json(song_dir / CHORD_EDIT_FILE, None)
    edited = edited if isinstance(edited, list) else None
    return {
        "id": song_id,
        "title": meta.get("title") or song_id,
        "lines": _read_json(song_dir / "lyrics.json", []),
        "chords": edited if edited is not None else _read_json(song_dir / "chords.json", []),
        "chords_edited": edited is not None,
        "can_edit": _can_write(song_dir),
        "audio": f"/media/{song_id}/audio" if _audio_file(song_dir) else None,
        "note_stems": sorted(_read_json(song_dir / "notes.json", {}).get("stems", {})),
        "mix": _mix_stems(song_id, song_dir),
    }


# ---------- Corrección de acordes ----------
CHORD_EDIT_FILE = "chords.edit.json"
CHORD_NAME_RE = re.compile(r"^[A-G][#b♯♭]?[\w#♯♭+\-°øΔ△()/]{0,18}$")
MAX_CHORDS = 5000
MAX_BODY = 1_000_000


def _can_write(song_dir: Path) -> bool:
    return os.environ.get("CHORD_EDITS", "1") != "0" and os.access(song_dir, os.W_OK)


def _is_time(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= 86_400


def _clean_chords(items) -> list[dict]:
    """Valida la lista enviada por el visor: [{start, end, chord}], ordenada y sin solapes."""
    if not isinstance(items, list) or len(items) > MAX_CHORDS:
        raise HTTPException(422, f"Se espera una lista de hasta {MAX_CHORDS} acordes")
    out = []
    for item in items:
        if not isinstance(item, dict):
            raise HTTPException(422, "Cada acorde debe ser un objeto {start, end, chord}")
        start, end, chord = item.get("start"), item.get("end"), item.get("chord")
        if not (_is_time(start) and _is_time(end)) or end <= start:
            raise HTTPException(422, "Tiempos de acorde no válidos")
        if not isinstance(chord, str) or not CHORD_NAME_RE.match(chord.strip()):
            raise HTTPException(422, f"Nombre de acorde no válido: {str(chord)[:24]!r}")
        out.append({"start": round(float(start), 3), "end": round(float(end), 3), "chord": chord.strip()})
    out.sort(key=lambda c: c["start"])
    for a, b in zip(out, out[1:]):
        a["end"] = min(a["end"], b["start"])
    return [c for c in out if c["end"] - c["start"] >= 0.01]


@app.put("/api/songs/{song_id}/chords")
async def put_chords(song_id: str, request: Request):
    song_dir = _song_dir(song_id)
    if not _is_song(song_dir):
        raise HTTPException(404, "Canción incompleta")
    # Solo JSON: junto con PUT, obliga a una petición "preflight" que el navegador no permite
    # desde otros sitios (no hay CORS), así que una web ajena no puede cambiar los acordes.
    if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
        raise HTTPException(415, "Se espera JSON")
    body = await request.body()
    if len(body) > MAX_BODY:
        raise HTTPException(413, "Demasiados datos")
    try:
        data = json.loads(body)
    except ValueError:
        raise HTTPException(422, "JSON no válido") from None
    chords = _clean_chords(data.get("chords") if isinstance(data, dict) else None)
    if not _can_write(song_dir):
        raise HTTPException(409, "El servidor no permite guardar cambios (carpeta de solo lectura)")
    target = song_dir / CHORD_EDIT_FILE
    tmp = target.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(chords, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(target)
    except OSError:
        raise HTTPException(409, "No se pudo guardar en el servidor") from None
    return {"ok": True, "count": len(chords)}


@app.delete("/api/songs/{song_id}/chords")
def delete_chords(song_id: str):
    song_dir = _song_dir(song_id)
    target = song_dir / CHORD_EDIT_FILE
    if target.is_file():
        if not _can_write(song_dir):
            raise HTTPException(409, "El servidor no permite guardar cambios (carpeta de solo lectura)")
        try:
            target.unlink()
        except OSError:
            raise HTTPException(409, "No se pudo borrar en el servidor") from None
    return {"ok": True}


MIX_STEM_RE = re.compile(r"^[a-z_]+$")


def _mix_stems(song_id: str, song_dir: Path) -> list[dict]:
    """Pistas del mezclador que existen de verdad en disco (mix/mix.json + mix/<pista>.m4a)."""
    index = _read_json(song_dir / "mix" / "mix.json", {})
    out = []
    for stem in index.get("stems", []):
        sid = str(stem.get("id", ""))
        if MIX_STEM_RE.match(sid) and (song_dir / "mix" / f"{sid}.m4a").is_file():
            out.append({"id": sid, "label": str(stem.get("label") or sid), "url": f"/media/{song_id}/mix/{sid}.m4a"})
    return out


# Pistas con notas transcritas y programa MIDI para que el archivo suene con un timbre parecido
NOTE_PROGRAMS = {"vocals": 52, "bass": 33, "guitar": 27, "piano": 0, "other": 80}


@app.get("/api/songs/{song_id}/notes")
def get_notes(song_id: str):
    """Notas transcritas por pista: {"stems": {pista: {"mono": bool, "notes": [[ini, fin, altura, vel]]}}}."""
    data = _read_json(_song_dir(song_id) / "notes.json", None)
    if not data or not data.get("stems"):
        raise HTTPException(404, "Esta canción no tiene notas transcritas")
    return data


@app.get("/media/{song_id}/midi/{stem}.mid")
def get_midi(
    song_id: str,
    stem: str,
    start: float | None = Query(None, ge=0, le=36000),
    end: float | None = Query(None, ge=0, le=36000),
):
    """MIDI de una pista, entero o recortado al tramo [start, end] (en segundos)."""
    if stem not in NOTE_PROGRAMS:
        raise HTTPException(404, "Pista no válida")
    if start is not None and end is not None and end <= start:
        raise HTTPException(400, "El final del tramo debe ser mayor que el inicio")
    entry = _read_json(_song_dir(song_id) / "notes.json", {}).get("stems", {}).get(stem)
    if not entry:
        raise HTTPException(404, "Esa pista no está transcrita")
    notes = cut_notes(entry["notes"], start, end)
    if not notes:
        raise HTTPException(404, "No hay notas de esta pista en ese tramo")
    body = write_midi(notes, name=stem, program=NOTE_PROGRAMS[stem])
    tramo = f"-{start:.0f}s-{end:.0f}s" if start is not None and end is not None else ""
    return Response(
        body, media_type="audio/midi",
        headers={"Content-Disposition": f'attachment; filename="{song_id}-{stem}{tramo}.mid"'},
    )


STEM_LABELS = {"vocals": "Voz", "bass": "Bajo", "guitar": "Guitarra", "piano": "Piano", "other": "Otros"}
MAX_REGION_SECONDS = 180
METER_RE = re.compile(r"^(\d{1,2})/(2|4|8|16)$")


def _grid_request(song_id: str, stems: str, start: float, end: float, meter: str, subdiv: int):
    """Valida lo común a partitura y MIDI cuantizado. Devuelve ({pista: notas}, (num, den))."""
    data = _read_json(_song_dir(song_id) / "notes.json", {}).get("stems", {})
    if not data:
        raise HTTPException(404, "Esta canción no tiene notas transcritas")
    names = [s for s in stems.split(",") if s] or sorted(data)
    for name in names:
        if name not in data or name not in NOTE_PROGRAMS:
            raise HTTPException(404, f"La pista {name!r} no está transcrita")
    if end <= start:
        raise HTTPException(400, "El final del tramo debe ser mayor que el inicio")
    if end - start > MAX_REGION_SECONDS:
        raise HTTPException(400, f"El tramo no puede durar más de {MAX_REGION_SECONDS} s")
    match = METER_RE.match(meter)
    if not match:
        raise HTTPException(400, "Compás no válido (ejemplos: 4/4, 3/4, 6/8)")
    time_sig = (int(match.group(1)), int(match.group(2)))
    if subdiv not in ALLOWED_SUBDIV:
        raise HTTPException(400, f"subdiv debe ser uno de {list(ALLOWED_SUBDIV)}")
    try:
        bar_divisions(time_sig, subdiv)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {name: data[name]["notes"] for name in names}, time_sig


def _quantize_all(by_stem, bpm, offset, subdiv, time_sig, start, end):
    """Cuantiza todas las pistas con el mismo relleno inicial para que sigan alineadas."""
    pad = max(quantize(notes, bpm, offset, subdiv, time_sig, start, end)[1] for notes in by_stem.values())
    return {stem: quantize(notes, bpm, offset, subdiv, time_sig, start, end, pad=pad)[0]
            for stem, notes in by_stem.items()}


def _mmss(seconds: float) -> str:
    seconds = int(seconds)
    return f"{seconds // 60}:{seconds % 60:02d}"


@app.get("/media/{song_id}/score.musicxml")
def get_score(
    song_id: str,
    start: float = Query(..., ge=0, le=36000),
    end: float = Query(..., ge=0, le=36000),
    bpm: float = Query(..., ge=30, le=300),
    offset: float = Query(..., ge=-100, le=36000),
    stems: str = Query("", max_length=60),
    meter: str = Query("4/4", max_length=6),
    subdiv: int = Query(4),
    tab: int = Query(1, ge=0, le=1),
    download: int = Query(0, ge=0, le=1),
):
    """Partitura MusicXML de un tramo, con la rejilla que indica el usuario.

    `offset` es el instante (s) en que cae el primer tiempo de un compás; `bpm` el tempo fijo.
    """
    by_stem, time_sig = _grid_request(song_id, stems, start, end, meter, subdiv)
    quantized = _quantize_all(by_stem, bpm, offset, subdiv, time_sig, start, end)
    parts = [{"stem": stem, "name": STEM_LABELS.get(stem, stem), "notes": notes}
             for stem, notes in quantized.items() if notes]
    if not parts:
        raise HTTPException(404, "No hay notas en ese tramo")
    meta = _read_json(_song_dir(song_id) / "meta.json", {})
    title = f"{meta.get('title') or song_id} ({_mmss(start)}–{_mmss(end)})"
    try:
        xml, info = build_score(parts, bpm, time_sig, subdiv, title=title, with_tab=bool(tab))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    fit = grid_fit([n for notes in by_stem.values() for n in notes], bpm, offset, subdiv, start=start, end=end)
    headers = {
        "X-Score-Bars": str(info["bars"]),
        "X-Score-Key": f"{info['fifths']}:{info['mode']}",
        "X-Score-Dropped": str(info["dropped_notes"]),
        "X-Score-Clamped": str(info["clamped_notes"]),
        "X-Score-Fit": str(fit["fraction"]),
        "X-Score-Baseline": str(fit["baseline"]),
        "X-Score-Onsets": str(fit["onsets"]),
        "Access-Control-Expose-Headers": "X-Score-Bars, X-Score-Key, X-Score-Dropped, X-Score-Clamped, "
                                         "X-Score-Fit, X-Score-Baseline, X-Score-Onsets",
    }
    if download:
        headers["Content-Disposition"] = f'attachment; filename="{song_id}-{start:.0f}s-{end:.0f}s.musicxml"'
    return Response(xml, media_type="application/vnd.recordare.musicxml+xml", headers=headers)


@app.get("/media/{song_id}/grid/{stem}.mid")
def get_grid_midi(
    song_id: str,
    stem: str,
    start: float = Query(..., ge=0, le=36000),
    end: float = Query(..., ge=0, le=36000),
    bpm: float = Query(..., ge=30, le=300),
    offset: float = Query(..., ge=-100, le=36000),
    meter: str = Query("4/4", max_length=6),
    subdiv: int = Query(4),
):
    """MIDI cuantizado de una pista: con el tempo y el compás de la rejilla, listo para un editor."""
    by_stem, time_sig = _grid_request(song_id, stem, start, end, meter, subdiv)
    notes = quantize(by_stem[stem], bpm, offset, subdiv, time_sig, start, end)[0]
    if not notes:
        raise HTTPException(404, "No hay notas de esta pista en ese tramo")
    body = write_midi_grid(notes, subdiv, bpm, time_sig, name=stem, program=NOTE_PROGRAMS[stem])
    return Response(
        body, media_type="audio/midi",
        headers={"Content-Disposition": f'attachment; filename="{song_id}-{stem}-{start:.0f}s-{end:.0f}s-cuantizado.mid"'},
    )


@app.get("/media/{song_id}/audio")
def get_audio(song_id: str):
    audio = _audio_file(_song_dir(song_id))
    if audio is None:
        raise HTTPException(404, "Esta canción no tiene audio")
    return FileResponse(audio)


@app.get("/media/{song_id}/mix/{stem}.m4a")
def get_mix_stem(song_id: str, stem: str):
    if not MIX_STEM_RE.match(stem):
        raise HTTPException(404, "Pista no encontrada")
    path = _song_dir(song_id) / "mix" / f"{stem}.m4a"
    if not path.is_file():
        raise HTTPException(404, "Pista no encontrada")
    return FileResponse(path, media_type="audio/mp4")


# Debe ir al final: sirve index.html en "/"
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
