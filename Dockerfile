# Visor web de acordes y letra (solo lectura; el procesamiento con GPU se hace en tu PC).
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    SONGS_DIR=/data/songs \
    PORT=8000 \
    REQUIRE_AUTH=1

WORKDIR /app

COPY requirements-web.txt .
RUN pip install -r requirements-web.txt

COPY web ./web

# Usuario sin privilegios; las canciones se montan como volumen en /data/songs
RUN useradd --system --uid 10001 --no-create-home viewer \
    && mkdir -p /data/songs \
    && chown -R viewer /data
USER viewer

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/healthz' % os.environ.get('PORT', '8000'))" || exit 1

# REQUIRE_AUTH=1: el contenedor no arranca sin VIEWER_USER y VIEWER_PASSWORD
CMD ["sh", "-c", "exec uvicorn web.app:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
