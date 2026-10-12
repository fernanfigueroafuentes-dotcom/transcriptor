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

## Transcripción de notas (solos y arreglos)

Además de acordes y letra, se pueden transcribir las **notas** (altura, inicio y duración) de cada
instrumento, para sacar solos y arreglos. Primero procesa la canción como siempre y luego:

```bash
python transcribe_notes.py light_as_a_feather
python transcribe_notes.py light_as_a_feather --stems guitar,piano --mono guitar
python transcribe_notes.py light_as_a_feather --stems other --force
```

- **Cómo funciona:** Demucs separa la canción en 6 pistas (voz, batería, bajo, guitarra, piano y otros) y
  Basic Pitch transcribe las notas de cada una. Genera `songs/<cancion>/notes.json` (lo lee el visor) y un
  archivo `midi/<pista>.mid` por pista. La batería no se transcribe.
- **`--mono`:** deja una sola nota a la vez; útil para el bajo (es el valor por defecto) o para un solo de
  una línea. Con las demás pistas se conservan las notas simultáneas.
- **Visor, botón «Piano roll»:** las notas de cada pista en colores, con su nombre, en una ventana de 8 a
  60 s que sigue al audio. Se pueden ocultar pistas, hacer clic para saltar a ese instante y, marcando **A y B**
  en el reproductor, **«Descargar tramo A–B»** da el MIDI solo de ese pasaje (por ejemplo, un solo).
- **Formato MIDI:** tempo fijo de 120 bpm con los tiempos reales del audio. No está cuantizado ni tiene
  compás: al importarlo en un editor de partituras o DAW hay que cuantizarlo allí.

**Instalación** (una vez). Basic Pitch se instala sin TensorFlow, usando su motor ONNX (`onnxruntime` ya
viene con las dependencias de la letra). Con `pip install basic-pitch` a secas se instalaría TensorFlow
(más de 500 MB) y se cambiarían versiones de otros paquetes:

```bash
pip install pretty_midi mir_eval resampy
pip install --no-deps basic-pitch
```

**Límites a tener en cuenta:**
- Basic Pitch es un modelo general: va bien con piano y líneas de una voz, y peor con mezclas densas,
  pasajes muy rápidos o instrumentos que suenan a la vez. Habrá notas de más, notas que faltan y octavas
  equivocadas; es un borrador para corregir de oído, no una partitura final.
- La separación en 6 pistas no es perfecta: la pista «guitarra» o «piano» puede contener otros instrumentos
  (por ejemplo, un piano eléctrico) y «otros» agrupa sintetizadores, vientos y cuerdas.
- Todavía no genera partitura ni tablatura.

### Afinar la transcripción

Las notas crudas del modelo se guardan en `notes_raw.json` y se depuran por instrumento (quita notas muy cortas o débiles, une notas partidas, elimina armónicos fantasma a la octava/doceava, limita la polifonía). Se puede reajustar al instante, sin repetir el modelo:

```bash
python transcribe_notes.py <id> --refine-only --strength 1.3   # más limpio (menos notas)
python transcribe_notes.py <id> --refine-only --strength 0.7   # conserva más notas
python transcribe_notes.py <id> --force --onset 0.6 --frame 0.35   # repetir el modelo con umbrales más estrictos
```

No hay una transcripción de referencia contra la que medir: ajusta de oído con el piano roll y el MIDI.

### Partitura y tablatura (Notas → Partitura)

Sobre las notas transcritas se puede fijar una **rejilla rítmica** y generar partitura:

1. En la vista *Notas* elige un tramo (A–B) y escribe el tempo (o pulsa *Sugerir*; muestra el ajuste junto al valor de azar).
2. Marca con *Aquí* dónde cae el tiempo 1 y comprueba con el metrónomo; ajusta compás y subdivisión (corcheas, semicorcheas, fusas).
3. *Generar partitura* dibuja la partitura en el navegador (OpenSheetMusicDisplay); *MusicXML* la descarga (MuseScore, Finale, Sibelius) y *MIDI cuantizado* exporta cada pista clavada en la rejilla. Guitarra y bajo pueden incluir pentagrama de tablatura.

Límites honestos:

- El tempo y el inicio los **confirmas tú**: el seguimiento automático de pulso no fue fiable con la canción de prueba.
- Rejilla fija: no hay tresillos, swing ni cambios de tempo/compás.
- La transcripción es un **borrador** (Basic Pitch): revísala. La tonalidad se estima y las digitaciones de la tablatura son una propuesta cómoda, no la única.
- Tramos de hasta 180 s.

Pruebas: `python -m unittest discover -s tests -v` (si tienes `music21`, además relee las partituras generadas).

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

### Tono y velocidad del audio

- **Tono − / +** transpone los acordes y, con la casilla **Audio** marcada, también el sonido
  (al intervalo más cercano: subir 7 semitonos suena como bajar 5, con los mismos acordes).
- **Velocidad** de 0.5× a 1.25× (pasos de 5 %) sin cambiar el tono.

Ambas cosas las hace Signalsmith Stretch (WASM, MIT) en el navegador, también con el mezclador
activo: los audios se aceleran o frenan sin conservar el tono y un único procesador corrige el
tono y aplica la transposición, lo que suena mejor que el estirado del navegador a 0.5–0.75×.
Con tono 0 y velocidad 1× el audio no pasa por el procesador. El procesador añade unos 120 ms
de retraso, que se compensan en el resaltado de la letra, el bucle y el metrónomo. Si el
navegador no admite AudioWorklet, la velocidad la hace el propio navegador y el tono del audio
no cambia (se avisa junto al botón).

### Corregir acordes

El botón **Editar acordes** activa el modo edición: un clic en un acorde abre un editor para

- cambiar el nombre (con validación y sugerencias), también **acordes con bajo** como `C/E`,
  `D/F#` o `Am7/G`; opcionalmente en **todas las veces** que aparece ese acorde;
- **dividirlo** o hacer que **empiece** en el punto donde está el audio, o **quitarlo**;
- con **＋ Acorde aquí** se añade uno en el momento actual. **Deshacer** (o Ctrl+Z) y
  **Restaurar originales** (dos clics) completan el modo.

Los nombres se escriben en el tono que se ve en pantalla y se guardan en el original. Las
correcciones van a `songs/<id>/chords.edit.json` (el `chords.json` detectado no se toca); si el
servidor es de solo lectura (Docker en el VPS, o `CHORD_EDITS=0`) se guardan en el navegador.
`deploy/push.ps1` sube las correcciones hechas en local junto con la canción.

Los diagramas entienden los acordes con bajo: en guitarra se buscan posiciones con esa nota
como la más grave y en piano el bajo va en la mano izquierda, con el acorde encima.

### Práctica: secciones, pausa entre vueltas y entrenador de velocidad

El botón **Práctica** (abajo, junto a Mezcla) abre:

- **Secciones**: guarda el bucle A–B actual con un nombre (Intro, Coro, Solo…) y vuelve a él
  desde la lista. Se guardan por canción en el navegador.
- **Ajustar A/B al compás**: con la rejilla definida (Notas → Partitura), las marcas A y B caen
  en la barra de compás más cercana.
- **Pausa entre vueltas**: 1–3 s para volver a colocar las manos, o **1 compás con cuenta**
  (clics del metrónomo, requiere rejilla) antes de cada repetición.
- **Entrenador**: empieza el bucle a una velocidad (p. ej. 70 %) y la sube un 5 o 10 % cada
  N vueltas hasta el objetivo; luego sigue repitiendo a esa velocidad.

La velocidad va de 50 % a 125 % en pasos de 5 %. Atajos: **A** / **B** marcan el bucle, **X** lo
quita, **Espacio** reproduce o pausa y **← →** saltan 5 s.

### Mezclador de pistas

El botón **Mezcla** (abajo, junto a ±5 s) abre un mezclador con las pistas separadas: silenciar (M),
escuchar solo (S) y volumen por pista, más atajos (*Sin voz*, *Sin guitarra*, *Sin bajo*, *Solo voz*).
Con todo en su punto neutro suena el audio original; en cuanto cambias algo suenan las pistas,
sincronizadas con el reproductor (bucle A–B, saltos y velocidad siguen funcionando). La mezcla se
recuerda por canción en el navegador.

Las pistas se comprimen a AAC (`songs/<id>/mix/*.m4a`, unos 5 MB por pista y por cada 4 min) al
procesar con `cli.py` o `transcribe_notes.py`. Para canciones ya procesadas:

```bash
python prepare_mix.py <id>          # usa las pistas que ya existan (6, o voz + acompañamiento)
python prepare_mix.py <id> --six    # separa antes en 6 pistas con Demucs
```

Requiere `ffmpeg` en el PATH donde se procesa. Límite conocido: en iPhone/iPad el volumen por pista
no se puede cambiar (iOS lo bloquea); silenciar y aislar sí funcionan.

### Diagramas de acordes

Se dibujan en SVG a partir del nombre del acorde (`web/static/chords.js`), así que sirven para cualquier
transposición y no necesitan imágenes.

**Catálogo (38 tipos):** tríadas (mayor, m, dim, aug), suspendidos (sus2, sus4, 7sus4, 9sus4), sextas (6, m6,
6/9, m6/9), séptimas (7, maj7, m7, m(maj7), dim7, m7♭5 semidisminuido, 7♭5, 7♯5, maj7♯5), novenas (add9,
madd9, 9, maj9, m9), alterados (7♭9, 7♯9, 7♯5♭9, 7♯5♯9, 7♭13, 7♯11, maj7♯11) y oncenas/trecenas (11, m11,
13, maj13, m13). Se reconocen también otras grafías: `Δ`, `M7`, `ø`, `°`, `+`, `-`, `min`, `sus`, `add2`…

- **Guitarra:** con las flechas `‹ 2/5 ›` de cada diagrama se recorren las digitaciones.
  - Mayor, menor, 7, m7 y maj7: la forma principal (abierta si existe) y las **cinco formas CAGED**
    (C, A, G, E, D), que se obtienen desplazando los acordes abiertos por el mástil.
  - Resto de tipos: la forma principal (acordes abiertos conocidos, o formas de Mi y de La) y formas
    **móviles generadas** con la raíz en la 6.ª, 5.ª y 4.ª cuerda, sin cuerdas al aire, con la raíz en el
    bajo, todas las notas imprescindibles (la quinta y a veces la 9.ª pueden omitirse), como mucho un hueco
    mudo, 4 trastes de ancho y 4 dedos. Salen digitaciones como `x-3-2-3-4-x` (7♯9), `x-3-2-4-3-x` (maj9) o
    `x-3-4-3-4-x` (m7♭5).
  - La raíz se marca en naranja y se indica el traste inicial (`4fr`) cuando el acorde está arriba del mástil.
- **Piano:** las flechas recorren las inversiones. En estado fundamental las notas van apiladas y las
  extensiones (9, 11, 13) una octava arriba; el teclado pasa a 3 octavas si hace falta. Cada diagrama
  nombra las notas.
- **Diccionario de acordes** (panel Diagramas, al final): eliges nota y tipo y ves cualquier acorde del
  catálogo con sus notas, digitaciones e inversiones, aunque no aparezca en la canción.
- La elección de digitación se guarda en el navegador por acorde; si transpones, el acorde cambia de nombre
  y vuelve a la primera opción.
- Los nombres que no se reconocen se dibujan como tríada aproximada (con `≈`).

**Qué detecta el modelo y qué no:** el detector (BTC) solo distingue 14 tipos: mayor, menor, dim, aug, 6, m6,
7, maj7, m7, m(maj7), dim7, m7♭5, sus2 y sus4. Las novenas, oncenas, trecenas, `add9`, 7sus4, 6/9 y los
acordes alterados **no se detectan**: solo se pueden consultar en el diccionario. Incluso entre los 14,
las séptimas se confunden a menudo con tríadas (ver Estado).

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
