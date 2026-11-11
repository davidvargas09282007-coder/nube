"""Healthcheck sin dependencias externas (Docker, Kubernetes, systemd).

Comprueba ``GET /health`` en el puerto local y falla con codigo 1 si el
servidor no responde o el estado no es ``ok``.

Variables:
    PORT / JARVIS_PORT         Puerto local (por defecto 8080).
    JARVIS_HEALTHCHECK_URL     URL completa (anula el resto).
    JARVIS_TLS_CERTFILE        Si esta definido, usa https y no valida el certificado.
"""

from __future__ import annotations

import json
import os
import ssl
import sys
import urllib.error
import urllib.request


def _url() -> str:
    explicit = os.getenv("JARVIS_HEALTHCHECK_URL", "").strip()
    if explicit:
        return explicit
    port = os.getenv("PORT") or os.getenv("JARVIS_PORT") or "8080"
    scheme = "https" if os.getenv("JARVIS_TLS_CERTFILE") else "http"
    return f"{scheme}://127.0.0.1:{port}/health"


def main() -> int:
    url = _url()
    context = None
    if url.startswith("https://"):
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE

    try:
        with urllib.request.urlopen(url, timeout=5, context=context) as response:
            payload = json.loads(response.read(4096) or b"{}")
    except (urllib.error.URLError, OSError, ValueError) as exc:
        print(f"healthcheck FAIL {url}: {exc}", file=sys.stderr)
        return 1

    if payload.get("status") != "ok":
        print(f"healthcheck FAIL {url}: {payload!r}", file=sys.stderr)
        return 1

    print(f"healthcheck OK {url} version={payload.get('version')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
