# `nube/` — backend Jarvis listo para producción

Paquete **autocontenido** para desplegar el servidor Jarvis en cualquier nube y mantenerlo
siempre activo. Incluye el código del servidor, las dependencias fijadas y las configuraciones
de las plataformas más habituales.

> El backend es **Python**, así que el equivalente a `package.json` son
> **`pyproject.toml`** (metadatos/paquete) y **`requirements.txt`** (dependencias de la imagen).

---

## Contenido

| Archivo | Para qué sirve |
|---|---|
| `jarvis_server/` | Código del servidor (copia sincronizada de `../server/jarvis_server`) |
| `requirements.txt` | Dependencias de producción (núcleo, versiones fijadas) |
| `requirements-voice.txt` | STT + wake word opcionales (imagen más grande) |
| `pyproject.toml` | Empaquetado del proyecto y comando `jarvis-server` |
| `Dockerfile` | Imagen Python 3.12-slim, usuario sin privilegios, `HEALTHCHECK` |
| `docker-compose.yml` + `Caddyfile` | VPS con TLS automático (Let's Encrypt) |
| `nginx/jarvis.conf` | Alternativa a Caddy para VPS |
| `systemd/jarvis.service` | Servicio del sistema con endurecimiento |
| `render.yaml` | Blueprint de Render (disco persistente incluido) |
| `fly.toml` | Fly.io con volumen y `min_machines_running = 1` |
| `railway.json` + `Procfile` | Railway (build por Dockerfile) |
| `scripts/start.sh` | Arranque robusto: exige token, respeta `$PORT`, proxy headers |
| `scripts/healthcheck.py` | Healthcheck sin dependencias (Docker/K8s/systemd) |
| `scripts/sync.ps1` / `sync.sh` | Sincronizan el código desde `server/` (o comprueban drift) |
| `.env.example` | Plantilla de todas las variables |
| `.dockerignore`, `.gitignore`, `.gitattributes` | Higiene del build y del repositorio |

---

## 1. Arranque rápido (Docker Compose en tu máquina o VPS)

```bash
cd nube
cp .env.example .env
# Genera un token y pégalo en JARVIS_AUTH_TOKEN
python -c "import secrets; print(secrets.token_urlsafe(32))"

docker compose up -d --build
docker compose ps          # jarvis debe aparecer "healthy"
docker compose logs -f jarvis
```

- Healthcheck: `https://<tu-dominio-o-localhost>/health`
- WebSocket: `wss://<tu-dominio-o-localhost>/ws`
- Con `JARVIS_DOMAIN=localhost` Caddy usa su CA interna: el móvil mostrará un aviso de
  certificado. En un VPS, apunta un dominio real a la IP y Caddy emite Let's Encrypt solo.

Sin proxy (pruebas locales):

```bash
docker build -t jarvis-server .
docker run --rm -p 8080:8080 --env-file .env -v jarvis-data:/data jarvis-server
# ws://localhost:8080/ws
```

## 2. Despliegue en Render (recomendado para empezar)

1. Sube el repositorio a GitHub.
2. **New → Blueprint** y elige el repo. Render solo busca `render.yaml` en la **raíz** del
   repositorio: copia `nube/render.yaml` a la raíz (o crea el servicio a mano apuntando al
   `Dockerfile` de `nube/`).
3. Aprueba el servicio: `JARVIS_AUTH_TOKEN` se genera automáticamente.
4. Copia el token desde **Environment** y la URL `https://jarvis-server.onrender.com`.

- El WebSocket queda en `wss://jarvis-server.onrender.com/ws`.
- `render.yaml` monta un disco de 1 GB en `/data` y usa plan `starter` (el plan free **no**
  tiene disco y se suspende por inactividad).
- **Escalado:** deja **1 instancia**. El estado de las sesiones vive en memoria; varias
  réplicas romperían las confirmaciones y el flujo de audio.

## 3. Despliegue en Fly.io

```bash
cd nube
fly launch --no-deploy                # cambia `app` en fly.toml si el nombre está ocupado
fly volumes create jarvis_data --size 1 --region mad
fly secrets set JARVIS_AUTH_TOKEN="$(python -c 'import secrets;print(secrets.token_urlsafe(32))')"
fly deploy
fly logs
```

- URL: `https://<app>.fly.dev` → WS en `wss://<app>.fly.dev/ws`.
- `auto_stop_machines = false` y `min_machines_running = 1` lo mantienen encendido.
- El volumen `jarvis_data` se monta en `/data`.

## 4. Despliegue en Railway

1. **New Project → Deploy from GitHub repo**.
2. En la configuración del servicio, pon **Root Directory = `nube`**. Railway detecta el
   `Dockerfile` (`railway.json` fija builder y healthcheck).
3. En **Variables** define `JARVIS_AUTH_TOKEN` y las claves de `.env.example`.
4. Añade un **Volume** montado en `/data` para persistencia.
5. Genera el dominio público → `wss://<dominio>/ws`.

## 5. VPS con systemd + nginx (control total)

```bash
# Como root, una sola vez
useradd --system --create-home --home-dir /opt/jarvis jarvis
mkdir -p /opt/jarvis /etc/jarvis /var/lib/jarvis
# Copia el contenido de nube/ a /opt/jarvis y crea el venv:
cd /opt/jarvis
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install --no-deps .

# Configuración y secreto
cp .env.example /etc/jarvis/jarvis.env   # edita JARVIS_AUTH_TOKEN, JARVIS_ALLOWED_ROOTS...
chown -R jarvis:jarvis /opt/jarvis /var/lib/jarvis
chmod 600 /etc/jarvis/jarvis.env

# Servicio
cp systemd/jarvis.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now jarvis
systemctl status jarvis
```

Después publica el puerto 8080 con TLS:

- **Caddy** (más simple): instala Caddy y usa el `Caddyfile` cambiando `reverse_proxy jarvis:8080`
  por `reverse_proxy 127.0.0.1:8080`.
- **nginx**: copia `nginx/jarvis.conf`, ajusta dominio y certificados y
  `certbot --nginx -d jarvis.example.com`.

---

## Conectar la app móvil

En **Ajustes** de la app:

| Dato | Valor |
|---|---|
| URL | `wss://<tu-dominio>/ws` (o `ws://IP:8080/ws` sin TLS) |
| Token | el valor de `JARVIS_AUTH_TOKEN` |

Comprueba primero desde el navegador: `https://<tu-dominio>/health` debe devolver
`{"status":"ok",...}`. `/v1/info` exige `Authorization: Bearer <token>`.

Prueba de extremo a extremo desde el repo:

```bash
python server/tools/ws_probe.py --url wss://<tu-dominio>/ws --token <token> --text "qué hora es"
```

---

## Variables imprescindibles

| Variable | Producción | Notas |
|---|---|---|
| `JARVIS_AUTH_TOKEN` | **obligatoria** | `start.sh` no arranca sin ella (salvo anónimo explícito) |
| `JARVIS_HOST` | `0.0.0.0` | dentro del contenedor |
| `JARVIS_PORT` | `8080` | `start.sh` la toma de `$PORT` si la plataforma lo inyecta |
| `JARVIS_DRY_RUN` | `true` | cámbialo a `false` solo cuando confíes en las acciones |
| `JARVIS_REQUIRE_CONFIRMATION` | `true` | confirmación para acciones destructivas |
| `JARVIS_ALLOWED_ROOTS` | `/data` | perímetro de ficheros |
| `JARVIS_NOTES_DIR` | `/data/Jarvis` | notas del asistente |
| `JARVIS_STT_BACKEND` | `none` | `faster-whisper` solo si instalaste la voz |
| `HF_HOME` | `/data/hf` | caché de modelos en el volumen |

Resto de claves documentadas en `.env.example`.

---

## Voz en la nube (opcional)

```bash
docker build --build-arg INSTALL_VOICE=true -t jarvis-server:voice .
```

- Añade ~600 MB y requiere `libgomp1`/`libsndfile1` (ya incluidos en el build con voz).
- Pon `JARVIS_STT_BACKEND=faster-whisper` y `JARVIS_STT_MODEL=tiny` (el `small` necesita más
  CPU/RAM y tarda varios segundos por frase).
- El modelo se descarga en el primer uso dentro de `HF_HOME=/data/hf`; con volumen persiste.
- **Wake word:** en el servidor no aporta nada (el audio ya llega segmentado desde el móvil) y
  openWakeWord escribe modelos en `site-packages`; con el contenedor `read_only: true` fallaría.
  Déjala desactivada o quita `read_only` del compose.
- Alternativa recomendada: **transcribir en el teléfono** (o enviar texto) y dejar la nube en
  modo texto. Menos coste, menos latencia y menos superficie de ataque.

## Automatización y Wake-on-LAN desde la nube

Importante: las acciones se ejecutan **en el contenedor/cloud**, no en tu PC de casa.

- `system.*`, `files.*`, `media.*` operan sobre `/data` y el propio contenedor. Los comandos de
  sistema (`shutdown`, `open_app`) no tienen sentido o están bloqueados por el propio sistema.
- **WoL:** un magic packet enviado desde la nube va a la LAN de la nube, no a la tuya. Opciones:
  1. **Servidor local** en casa (`../server/`) para controlar el PC y la nube solo como relay.
  2. **VPN** (Tailscale/WireGuard) entre la nube y la LAN doméstica.
  3. `tools/wol_relay.py` del repo, ejecutado en una Raspberry/PC de la LAN, autenticado con HMAC.
- El paquete `nube/` está pensado para disponibilidad 24/7 y acceso remoto; para control real del
  PC, mantén también el servidor local o monta la VPN.

## Seguridad

- [x] Token obligatorio y comparación en tiempo constante (`secrets.compare_digest`).
- [x] Contenedor sin root (`uid 10001`), `read_only`, `cap_drop: ALL`, `no-new-privileges`.
- [x] TLS terminado por Caddy/nginx/Render/Fly; usa siempre `wss://` fuera de localhost.
- [x] `dry_run` y confirmación activos por defecto.
- [x] Perímetro de ficheros limitado a `/data`.
- [ ] Rota el token si alguna vez se filtró (estuvo en un `.env` de desarrollo).
- [ ] No publiques `/v1/info` sin token (ya lo exige) ni desactives la autenticación.
- [ ] Vigila los logs: no contienen el token, pero sí nombres de ficheros y comandos.

## Mantener el código sincronizado

`nube/jarvis_server` es una copia. Tras cambiar `server/jarvis_server`:

```powershell
.\nube\scripts\sync.ps1          # copia
.\nube\scripts\sync.ps1 -Check   # CI: falla si hay drift
```

```bash
./nube/scripts/sync.sh
./nube/scripts/sync.sh --check
```

## Problemas típicos

| Síntoma | Causa / solución |
|---|---|
| `ERROR: JARVIS_AUTH_TOKEN no esta definido` | Define el secreto en la plataforma |
| El servicio reinicia en bucle | Revisa `docker compose logs jarvis`; suele ser una variable mal formada |
| WebSocket se corta a los ~60 s | El proxy no reenvía `Upgrade` o tiene timeout bajo; usa el `Caddyfile`/`nginx.conf` incluidos |
| `502` en Render/Fly | El contenedor no escucha en `$PORT`; `start.sh` ya lo resuelve, revisa logs |
| El móvil no conecta en LAN | Firewall del PC/VPS y que la URL use la IP correcta |
| `stt` desactivado | `JARVIS_STT_BACKEND=none` o falta `requirements-voice.txt` |
| Sin persistencia tras redeploy | Falta el volumen montado en `/data` |

---

Licencia MIT. El contrato de red está en [`../docs/PROTOCOL.md`](../docs/PROTOCOL.md) y el diseño
en [`../docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md).
