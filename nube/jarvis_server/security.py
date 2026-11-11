"""Autenticación por token y firmas HMAC para el relay WoL."""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import time

from .config import Settings

_LOG = logging.getLogger("jarvis.security")
_EPHEMERAL_TOKEN: str | None = None


def generate_token(num_bytes: int = 32) -> str:
    return secrets.token_urlsafe(num_bytes)


def resolve_tokens(settings: Settings) -> tuple[str, ...]:
    """Devuelve los tokens aceptados.

    Si no hay token configurado se genera uno efímero por proceso y se imprime una sola
    vez. Esto evita servidores abiertos por descuido sin obligar a configurar nada en dev.
    """
    global _EPHEMERAL_TOKEN

    configured = settings.auth_token_plain
    if configured:
        tokens = tuple(part.strip() for part in configured.split(",") if part.strip())
        if tokens:
            return tokens

    if settings.allow_anonymous:
        _LOG.warning("JARVIS_ALLOW_ANONYMOUS activo: cualquiera en la red puede controlar el equipo.")
        return ()

    if _EPHEMERAL_TOKEN is None:
        _EPHEMERAL_TOKEN = generate_token()
        banner = "=" * 68
        print(banner, flush=True)
        print(" JARVIS: no hay JARVIS_AUTH_TOKEN configurado.", flush=True)
        print(" Token efímero de esta sesión (cópialo en la app):", flush=True)
        print(f"   {_EPHEMERAL_TOKEN}", flush=True)
        print(" Se invalida al reiniciar el servidor.", flush=True)
        print(banner, flush=True)
    return (_EPHEMERAL_TOKEN,)


def token_is_valid(token: str | None, accepted: tuple[str, ...]) -> bool:
    if not accepted:
        return True
    if not token:
        return False
    candidate = token.strip()
    return any(hmac.compare_digest(candidate, expected) for expected in accepted)


def sign_payload(secret: str, body: bytes, timestamp: str | None = None) -> tuple[str, str]:
    """Firma ``timestamp.body`` y devuelve ``(timestamp, signature_hex)``."""
    ts = timestamp or str(int(time.time()))
    message = ts.encode("utf-8") + b"." + body
    signature = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
    return ts, signature


def verify_signature(
    secret: str,
    body: bytes,
    timestamp: str | None,
    signature: str | None,
    max_skew_seconds: int = 60,
) -> bool:
    if not secret or not timestamp or not signature:
        return False
    try:
        ts = int(timestamp)
    except (TypeError, ValueError):
        return False
    if abs(time.time() - ts) > max_skew_seconds:
        return False
    expected_ts, expected_sig = sign_payload(secret, body, timestamp)
    if expected_ts != timestamp:
        return False
    return hmac.compare_digest(expected_sig, signature.strip().lower())
