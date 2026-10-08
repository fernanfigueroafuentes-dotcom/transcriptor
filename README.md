# Transcriptor de acordes y letra (Fase 0)

Uso personal. Toma un audio local y genera:

- `chords.json`: acordes con tiempos
- `lyrics.json`: letra con tiempos por palabra
- `song.chordpro`: letra con acordes encima

## Requisitos

- Windows 11, GPU NVIDIA (RTX 5060)
- Python 3.11 (probado con 3.11.9)
- ffmpeg en el PATH (`ffmpeg -version` debe funcionar)

## Instalación

```bash
python -m venv .venv
.venv\Scripts\activate

# 1) PyTorch 2.8.0 con CUDA 12.8 (la RTX 5060 necesita cu128; 2.11 rompe whisperx)
pip install torch==2.8.0 torchaudio==2.8.0 --index-url https://download.pytorch.org/whl/cu128

# 2) Dependencias
pip install -r requirements.txt
```

Verifica la GPU:

```bash
python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```

## Uso

```bash
# Solo acordes y letra transcrita de la voz
python cli.py mi_cancion.mp3

# Con tu letra (recomendado: mucho más preciso)
python cli.py mi_cancion.mp3 --lyrics letra.txt

# Más rápido, sin letra
python cli.py mi_cancion.mp3 --no-separate

# Modelo más liviano si la VRAM se queda corta (8 GB)
python cli.py mi_cancion.mp3 --model medium
```

Los resultados quedan en `songs/<nombre_cancion>/`.

## Notas

- `letra.txt` es tu propia copia de la letra. Solo se usa para calcular tiempos; no se publica nada.
- La alineación de tu letra depende de que la transcripción de la voz sea razonable. Si una línea no coincide, sus tiempos se interpolan.
- Los acordes se detectan sobre el instrumental cuando hay separación.
- Los pasajes sin letra (intro, solos) aparecen al final como "Acordes sin letra".

## Motores de acordes

- `--engine btc` (por defecto): modelo preentrenado BTC (Bi-directional Transformer for Chord Recognition, ISMIR 2019), con vocabulario de 170 acordes. Corre en la GPU. Ignora `--key`.
- `--engine template`: plantillas de acordes con librosa. No necesita modelo descargado y admite `--key C`, pero es mucho menos fiable con audio real.

El modelo BTC vive en `third_party/btc_chord/`: pesos y código (licencia MIT) de
[puar-playground/btc-chord](https://huggingface.co/puar-playground/btc-chord), revisión
`d436f2f664f5107cd987774279b8ce171846e376`, basado en [jayg996/BTC-ISMIR19](https://github.com/jayg996/BTC-ISMIR19).
No se usa `trust_remote_code`: se importa solo el código del modelo (revisado) y los pesos se cargan
con `weights_only=True`. Para volver a descargarlo:

```bash
python -c "from huggingface_hub import snapshot_download; snapshot_download('puar-playground/btc-chord', revision='d436f2f664f5107cd987774279b8ce171846e376', local_dir='third_party/btc_chord')"
```

Antes de procesar, el audio se normaliza en volumen: BTC se entrenó con música masterizada y una grabación
baja se interpreta como silencio.

## Visor web

```bash
python serve.py            # abre http://127.0.0.1:8000
python serve.py --port 9000 --no-browser
```

Muestra la letra con los acordes encima, sincronizada con el audio:

- Resalta la fila, la palabra y el acorde actuales, con seguimiento automático de la letra.
- Línea de tiempo con todos los acordes (clic o arrastre para saltar) y acorde actual en grande.
- Clic en una palabra o un acorde para saltar a ese punto. Espacio: reproducir/pausar. Flechas: ±5 s.
- Transposición en semitonos, con alternancia entre sostenidos y bemoles.
- Velocidad de 0.5× a 1.25× conservando el tono, y bucle A-B para practicar un pasaje.
- Se adapta al celular y al modo oscuro.
- Botón **Diagramas**: panel con el acorde que suena ahora y una tarjeta por cada acorde de la canción (ordenados por tiempo total), en **guitarra**, **piano** o ambos. Clic en una tarjeta para saltar a la próxima vez que suena. Los diagramas siguen la transposición y la alternancia ♯/♭.

### Diagramas de acordes

Se dibujan en SVG a partir del nombre del acorde (`web/static/chords.js`), así que sirven para cualquier
transposición y no necesitan imágenes.

- **Guitarra:** para los acordes con digitación abierta conocida (C, D, E, G, A, Am, Dm, Em, séptimas, sus…)
  se usa una tabla de formas estándar. Para el resto, formas móviles de **Mi** y de **La** con cejilla,
  en la posición más baja (por ejemplo F = `133211`, B = `x24442`, F#m = `244222`). Para calidades poco
  comunes (dim, m7b5, aug…) hay formas de La y, como último recurso, una búsqueda de digitaciones playables.
  La raíz se marca en naranja y se indica el traste inicial (`4fr`) cuando el acorde está arriba del mástil.
- **Piano:** dos octavas con las notas del acorde en estado fundamental y su nombre sobre cada tecla.
- Los nombres que el detector no reconoce se dibujan como tríada aproximada (con `≈`).
- **Todas las posiciones:** con las flechas `‹ 2/5 ›` de cada diagrama se recorren las digitaciones.
  Para mayor, menor, 7, m7 y maj7 son las **cinco formas CAGED** (C, A, G, E, D): se obtienen desplazando
  los acordes abiertos por el mástil, así que el mismo acorde sale en cinco zonas, de grave a aguda. La
  principal va primera. Los demás tipos de acorde (sus, dim, aug, 6…) tienen una sola digitación.
- **Piano:** las flechas recorren las inversiones (fundamental, 1.ª, 2.ª y 3.ª si hay séptima) con la
  nota del bajo.
- La elección se guarda en el navegador por acorde; si transpones, el acorde cambia de nombre y vuelve
  a la primera opción.
- Las séptimas que el detector no distingue aparecen como tríadas (ver Estado).

`cli.py` guarda una copia del audio (`audio.mp3`, etc.) y un `meta.json` con el título en la carpeta de cada
canción; el visor los usa. Para una canción procesada antes de esa versión, copia el audio a su carpeta
como `audio.<extensión>`.

### Despliegue en un servidor

El procesamiento (Demucs, BTC, Whisper) necesita GPU y se hace en tu PC; el visor corre en cualquier
máquina. La guía completa está en **[deploy/DEPLOY.md](deploy/DEPLOY.md)**: imagen de Docker
(`Dockerfile`, `docker-compose.yml`), script de subida (`deploy/push.ps1`) y notas para OpenShip.

- Con `VIEWER_USER` y `VIEWER_PASSWORD` definidos, **todas** las rutas (salvo `/healthz`) piden usuario y
  contraseña (HTTP Basic, solo seguro sobre HTTPS). La imagen de Docker no arranca sin ellas.
- `serve.py` solo escucha en `127.0.0.1`; con `--host 0.0.0.0` exige las mismas variables.
- Servir audio y letras con derechos desde un servidor público es distribuirlos: mantenlo detrás de la
  contraseña (o de una VPN).

## Estado

- Probado con un clip real de 7 s (2-5-1 en Do): BTC da `G Dm G C`, con las raíces correctas. No distingue las séptimas (Dm7, G7, Cmaj7 salen como tríadas) y añade un G inicial de menos de un segundo.
- Probado con una canción completa de unos 3:45: separación de voz, acordes con BTC, transcripción en español con Whisper large-v3 y alineación por palabra funcionan de punta a punta. Falta contrastar acordes y letra con la canción real; la letra de Whisper sobre voz cantada puede tener errores (usa `--lyrics` con tu propia copia para mejorarla).
- El visor se probó en el navegador integrado (escritorio y tamaño de celular): sincronización, transposición, bemoles, bucle, velocidad, saltos y reproducción real. No se probó en Safari, Firefox ni en un celular real.
