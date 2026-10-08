"""API y archivos estáticos del visor.

    GET /api/songs        lista de canciones procesadas
    GET /api/songs/{id}   letra con tiempos, acordes y URL del audio
    GET /media/{id}/audio audio original (con soporte de Range para saltar en el reproductor)
    GET /healthz          comprobación de salud (sin autenticación y sin datos)

Variables de entorno:
    SONGS_DIR        carpeta con las canciones (por defecto, ./songs)
    VIEWER_USER      usuario y contraseña de acceso (HTTP Basic). Si ambas están definidas,
    VIEWER_PASSWORD  TODAS las rutas, salvo /healthz, exigen autenticación.
    REQUIRE_AUTH=1   no arranca si faltan las credenciales (lo usa la imagen de Docker)
"""
import asyncio
import base64
import binascii
import json
import os
import re
import secrets
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

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
    return {
        "id": song_id,
        "title": meta.get("title") or song_id,
        "lines": _read_json(song_dir / "lyrics.json", []),
        "chords": _read_json(song_dir / "chords.json", []),
        "audio": f"/media/{song_id}/audio" if _audio_file(song_dir) else None,
    }


@app.get("/media/{song_id}/audio")
def get_audio(song_id: str):
    audio = _audio_file(_song_dir(song_id))
    if audio is None:
        raise HTTPException(404, "Esta canción no tiene audio")
    return FileResponse(audio)


# Debe ir al final: sirve index.html en "/"
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
