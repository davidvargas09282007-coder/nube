#!/usr/bin/env bash
# Sincroniza nube/jarvis_server con server/jarvis_server (fuente de verdad).
#
#   ./scripts/sync.sh          copia (espejo) el codigo
#   ./scripts/sync.sh --check  solo comprueba diferencias; exit 1 si hay drift
set -euo pipefail

NUBE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="$(cd "$NUBE_ROOT/.." && pwd)"
SOURCE="$REPO_ROOT/server/jarvis_server"
TARGET="$NUBE_ROOT/jarvis_server"
CHECK=false

if [[ "${1:-}" == "--check" ]]; then
    CHECK=true
fi

if [[ ! -d "$SOURCE" ]]; then
    echo "ERROR: no existe $SOURCE" >&2
    exit 1
fi

if $CHECK; then
    if diff -r -x '__pycache__' -x '*.pyc' "$SOURCE" "$TARGET"; then
        echo "OK: nube/jarvis_server esta sincronizado con server/jarvis_server"
        exit 0
    fi
    echo "DRIFT: ejecuta ./scripts/sync.sh para actualizar nube/jarvis_server" >&2
    exit 1
fi

mkdir -p "$TARGET"
if command -v rsync >/dev/null 2>&1; then
    rsync -a --delete --exclude '__pycache__' --exclude '*.pyc' "$SOURCE/" "$TARGET/"
else
    rm -rf "$TARGET"
    mkdir -p "$TARGET"
    cp -a "$SOURCE/." "$TARGET/"
    find "$TARGET" -type d -name '__pycache__' -prune -exec rm -rf {} +
    find "$TARGET" -name '*.pyc' -delete
fi

echo "Sincronizado: server/jarvis_server -> nube/jarvis_server"
