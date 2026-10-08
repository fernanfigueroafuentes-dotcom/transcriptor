# Despliegue del visor en el VPS

Se despliega **solo el visor web** (FastAPI, sin IA ni GPU). El procesamiento con Demucs, BTC y Whisper
se sigue haciendo en tu PC; al servidor solo suben la app y los resultados de cada canción.

```
tu PC (GPU)                              VPS
cli.py → songs/<cancion>/        push.ps1        /opt/transcriptor/app     (Dockerfile + web/)
  audio, chords.json, ...      ─────────────►    /opt/transcriptor/songs   (sin stems/, solo lectura)
                                                 contenedor "viewer" ← proxy inverso con HTTPS
```

## 0. Seguridad: léelo antes

- **La app exige usuario y contraseña** (HTTP Basic) en todas las rutas salvo `/healthz`, y el contenedor
  **no arranca** si no están definidas. Esto es deliberado: servirás audio y letras de canciones con
  derechos de autor; sin acceso restringido, publicarlas en internet equivale a distribuirlas.
- **HTTP Basic solo es seguro sobre HTTPS.** Sin HTTPS la contraseña viaja en claro. Usa un dominio con TLS
  (OpenShip puede emitirlo, o Caddy/Traefik) y no expongas el puerto 8000 directamente.
- **Usa una contraseña larga y única** para el visor:
  `python -c "import secrets; print(secrets.token_urlsafe(24))"`
- **La contraseña de root del servidor se compartió en un chat.** Considérala comprometida y cámbiala.
  Antes de hacerlo, comprueba si OpenShip usa esa credencial para conectarse al servidor: si es así, cámbiala
  desde OpenShip (o actualiza la credencial allí), o dejarás de poder administrarlo desde su panel.
- Recomendado: entrar por **clave SSH** y desactivar el acceso por contraseña de root (paso 1).

## 1. Clave SSH (una vez, desde tu PC)

```powershell
# Si ya tienes ~\.ssh\id_ed25519, sáltate la primera línea
ssh-keygen -t ed25519 -C "transcriptor"
type $env:USERPROFILE\.ssh\id_ed25519.pub | ssh root@IP_DEL_SERVIDOR "mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"
ssh root@IP_DEL_SERVIDOR "echo conexión por clave OK"   # ya no debe pedir contraseña
```

Solo cuando eso funcione, y si OpenShip no depende de la contraseña, puedes poner
`PasswordAuthentication no` en `/etc/ssh/sshd_config` y reiniciar `sshd`. Mantén una sesión abierta mientras
lo pruebas para no quedarte fuera.

## 2. Subir la app y las canciones (desde tu PC)

El script no guarda credenciales: `ssh` pide la contraseña o usa tu clave.

```powershell
cd <carpeta-del-proyecto>
.\deploy\push.ps1 -Server root@IP_DEL_SERVIDOR -DryRun   # muestra qué subiría, sin conectarse
.\deploy\push.ps1 -Server root@IP_DEL_SERVIDOR           # sube app y canciones
```

Sube a `/opt/transcriptor/app` (Dockerfile, `docker-compose.yml`, `web/`) y a `/opt/transcriptor/songs`
(canciones **sin** `stems/`, que pesan mucho y el visor no usa).

## 3. Levantarlo en el servidor

```bash
cd /opt/transcriptor/app
cp .env.example .env
nano .env        # VIEWER_USER, VIEWER_PASSWORD y SONGS_PATH=/opt/transcriptor/songs
chmod 600 .env
docker compose up -d --build
docker compose ps          # debe quedar "healthy"
```

El `docker-compose.yml` publica el puerto solo en `127.0.0.1:8000` del servidor, el contenedor corre sin
privilegios, con sistema de archivos de solo lectura y las canciones montadas en solo lectura.

## 4. Dominio y HTTPS

**Con OpenShip** (plataforma en beta: los nombres exactos de menús pueden variar, consulta su documentación):
crea una aplicación desde el `docker-compose.yml` o el `Dockerfile` de `/opt/transcriptor/app`, con
puerto interno `8000`; define `VIEWER_USER` y `VIEWER_PASSWORD` como variables de entorno (secretas);
monta `/opt/transcriptor/songs` en `/data/songs` y asocia un dominio con TLS. Si el proxy de OpenShip
enruta por la red de Docker, quita el bloque `ports:` del compose.

**Sin OpenShip**, un proxy inverso mínimo con Caddy (HTTPS automático con Let's Encrypt, el dominio debe
apuntar a la IP del servidor):

```
visor.tudominio.com {
    reverse_proxy 127.0.0.1:8000
}
```

El proxy debe **dejar pasar las cabeceras `Range`** (los saltos del reproductor las necesitan) y no
reescribir `Authorization`.

## 5. Comprobar

```bash
curl -s -o /dev/null -w "%{http_code}\n" https://visor.tudominio.com/api/songs                   # 401
curl -s -o /dev/null -w "%{http_code}\n" https://visor.tudominio.com/healthz                     # 200
curl -s -o /dev/null -w "%{http_code}\n" -u USUARIO:CONTRASEÑA https://visor.tudominio.com/api/songs   # 200
```

## 6. Día a día

- **Canción nueva:** procésala en tu PC con `cli.py` y ejecuta `.\deploy\push.ps1 -Server root@IP -SkipApp`.
  El visor lee la carpeta en cada petición: no hace falta reiniciar nada.
- **Cambios en el visor:** `.\deploy\push.ps1 -Server root@IP -SkipSongs` y en el servidor
  `cd /opt/transcriptor/app && docker compose up -d --build`.
- **Quitar una canción:** bórrala en `/opt/transcriptor/songs/<id>/`.

## Si algo falla

| Síntoma | Causa probable |
|---|---|
| El contenedor sale al arrancar con `REQUIRE_AUTH=1 pero faltan...` | Faltan `VIEWER_USER` / `VIEWER_PASSWORD` en `.env` o en las variables de OpenShip |
| Siempre 401 aunque la contraseña sea correcta | Un proxy está quitando la cabecera `Authorization`; o hay caracteres especiales sin comillas en `.env` |
| La lista de canciones sale vacía | Ruta de `SONGS_PATH` incorrecta, o los archivos no son legibles (`chmod -R a+rX /opt/transcriptor/songs`) |
| El audio suena pero no se puede saltar | El proxy no deja pasar `Range` o está comprimiendo/guardando en caché la respuesta de audio |
| No carga en `http://` | Normal si el navegador o el proxy fuerzan HTTPS; usa el dominio con TLS |

## Qué NO va al servidor

El código de procesamiento (`core/`, `cli.py`), los modelos (`third_party/`), el entorno `.venv`, las pistas
separadas (`stems/`) y tu `.env` local. Están excluidos por `.dockerignore`, `.gitignore` y `push.ps1`.
