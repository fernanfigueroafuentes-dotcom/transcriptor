"""Inicia el visor web:

    python serve.py
    python serve.py --port 9000 --no-browser

Por defecto solo escucha en 127.0.0.1 (tu equipo). Para escuchar en otra interfaz
(--host 0.0.0.0) hay que definir VIEWER_USER y VIEWER_PASSWORD: sin ellas no arranca.
"""
import argparse
import os
import sys
import threading
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import uvicorn  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Visor web de acordes y letra.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-browser", action="store_true", help="No abrir el navegador")
    args = parser.parse_args()

    if args.host not in ("127.0.0.1", "localhost", "::1") and not (
        os.environ.get("VIEWER_USER") and os.environ.get("VIEWER_PASSWORD")
    ):
        sys.exit("Para escuchar fuera de localhost define VIEWER_USER y VIEWER_PASSWORD.")

    if not args.no_browser:
        url = f"http://{'127.0.0.1' if args.host == '0.0.0.0' else args.host}:{args.port}"
        threading.Timer(1.0, webbrowser.open, args=(url,)).start()

    uvicorn.run("web.app:app", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
