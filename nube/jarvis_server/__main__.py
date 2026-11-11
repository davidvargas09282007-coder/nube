"""Punto de entrada: ``python -m jarvis_server``."""

from __future__ import annotations

import argparse
import contextlib
import sys
import webbrowser
from collections.abc import Iterable
from typing import IO

import uvicorn

from . import __version__
from .config import get_settings


def _configure_stdio(streams: Iterable[IO[str]] | None = None) -> None:
    """Fuerza UTF-8 tolerante: evita UnicodeEncodeError en Windows (cp1252).

    Solo afecta a la salida de consola/redirección: p. ej. ``→`` o ``…`` fallan al
    redirigir la salida con la configuración regional de Windows.
    """
    for stream in streams if streams is not None else (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        with contextlib.suppress(AttributeError, ValueError, OSError):
            reconfigure(encoding="utf-8", errors="replace")


def build_parser() -> argparse.ArgumentParser:
    settings = get_settings()
    parser = argparse.ArgumentParser(
        prog="jarvis-server",
        description="Servidor del asistente de voz Jarvis.",
    )
    parser.add_argument("--host", default=settings.host, help="Interfaz de escucha (por defecto 0.0.0.0)")
    parser.add_argument("--port", type=int, default=settings.port, help="Puerto (por defecto 8765)")
    parser.add_argument("--reload", action="store_true", help="Recarga automática (solo desarrollo)")
    parser.add_argument("--no-tls", action="store_true", help="Ignora los certificados configurados")
    parser.add_argument("--log-level", default=settings.log_level.lower(), help="DEBUG, INFO, WARNING...")
    parser.add_argument("--open", action="store_true", help="Abre /health en el navegador al arrancar")
    return parser


def main(argv: list[str] | None = None) -> int:
    _configure_stdio()
    args = build_parser().parse_args(argv)
    settings = get_settings()

    use_tls = settings.tls_enabled and not args.no_tls
    scheme = "https" if use_tls else "http"

    print(f"Jarvis {__version__} -> {scheme}://{args.host}:{args.port}")
    print(f"  health : {scheme}://127.0.0.1:{args.port}/health")
    print(f"  ws     : {'wss' if use_tls else 'ws'}://127.0.0.1:{args.port}/ws")

    if args.open:
        webbrowser.open(f"{scheme}://127.0.0.1:{args.port}/health")

    uvicorn.run(
        "jarvis_server.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level=args.log_level,
        ssl_certfile=settings.tls_certfile if use_tls else None,
        ssl_keyfile=settings.tls_keyfile if use_tls else None,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
