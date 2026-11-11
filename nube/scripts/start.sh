#!/usr/bin/env bash
# ============================================================================
# Arranque de produccion del servidor Jarvis.
#
# - Falla si no hay JARVIS_AUTH_TOKEN (evita servidores abiertos por descuido).
# - Respeta $PORT que inyectan Render/Fly/Railway/Heroku.
# - Activa proxy headers para obtener la IP real detras de Caddy/nginx.
# - Mantiene viva la conexion WebSocket con pings periodicos.
# ============================================================================
set -euo pipefail

PORT="${PORT:-${JARVIS_PORT:-8080}}"
export JARVIS_PORT="$PORT"
export JARVIS_HOST="${JARVIS_HOST:-0.0.0.0}"

if [[ -z "${JARVIS_AUTH_TOKEN:-}" && "${JARVIS_ALLOW_ANONYMOUS:-false}" != "true" ]]; then
    cat >&2 <<'EOF'
====================================================================
 ERROR: JARVIS_AUTH_TOKEN no esta definido.
 El servidor no arrancara en la nube sin autenticacion.

 Define el secreto en la plataforma:
   Render / Railway : panel -> Environment -> JARVIS_AUTH_TOKEN
   Fly.io           : fly secrets set JARVIS_AUTH_TOKEN=...
   Docker Compose   : variable en .env o en el entorno

 Genera uno con:  python -c "import secrets; print(secrets.token_urlsafe(32))"
====================================================================
EOF
    exit 1
fi

if [[ "${JARVIS_WORKERS:-1}" != "1" ]]; then
    echo "AVISO: JARVIS_WORKERS=${JARVIS_WORKERS}; se usa 1 (el estado de sesion vive en memoria)." >&2
fi

LOG_LEVEL="$(printf '%s' "${JARVIS_LOG_LEVEL:-INFO}" | tr '[:upper:]' '[:lower:]')"
FORWARDED_ALLOW_IPS="${JARVIS_FORWARDED_ALLOW_IPS:-*}"

# Argumentos comunes. `set --` evita arrays vacios con `set -u` en bash antiguos.
set -- \
    jarvis_server.app:app \
    --host "$JARVIS_HOST" \
    --port "$PORT" \
    --proxy-headers \
    --forwarded-allow-ips "$FORWARDED_ALLOW_IPS" \
    --no-server-header \
    --timeout-keep-alive 65 \
    --timeout-graceful-shutdown 20 \
    --ws-ping-interval 30 \
    --ws-ping-timeout 60 \
    --log-level "$LOG_LEVEL"

if [[ -n "${JARVIS_TLS_CERTFILE:-}" && -n "${JARVIS_TLS_KEYFILE:-}" ]]; then
    set -- "$@" --ssl-certfile "$JARVIS_TLS_CERTFILE" --ssl-keyfile "$JARVIS_TLS_KEYFILE"
    echo "TLS directo activo (${JARVIS_TLS_CERTFILE})"
fi

echo "Jarvis arrancando en ${JARVIS_HOST}:${PORT} (log=${LOG_LEVEL}, stt=${JARVIS_STT_BACKEND:-auto}, dryRun=${JARVIS_DRY_RUN:-true})"

exec uvicorn "$@"
