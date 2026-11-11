"""Aplicación FastAPI: handshake, WebSocket y endpoints de diagnóstico."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import secrets
import sys
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from . import __version__, protocol
from .automation import AutomationService, build_automation
from .config import Settings, get_settings
from .security import resolve_tokens, token_is_valid
from .session import AssistantSession
from .voice import build_gate, build_speech_renderer, build_transcriber

_LOG = logging.getLogger("jarvis.app")
HANDSHAKE_TIMEOUT = 10.0
SESSION_IDLE_TIMEOUT = 60.0
_STARTED_AT = time.monotonic()


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, str(level).upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )


def _bearer(header: str | None) -> str | None:
    if not header:
        return None
    value = header.strip()
    if value.lower().startswith("bearer "):
        return value[7:].strip()
    return value


def create_app(settings: Settings | None = None) -> FastAPI:
    cfg = settings or get_settings()
    _configure_logging(cfg.log_level)

    tokens = resolve_tokens(cfg)
    automation: AutomationService = build_automation(cfg)
    transcriber = build_transcriber(cfg)
    gate = build_gate(cfg)
    speech = build_speech_renderer()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        _LOG.info(
            "Jarvis %s escuchando en %s:%s (tls=%s, dry_run=%s, intents=%d, wol=%s)",
            __version__,
            cfg.host,
            cfg.port,
            cfg.tls_enabled,
            cfg.dry_run,
            len(automation.registry),
            ", ".join(automation.wol_names()) or "-",
        )
        yield
        _LOG.info("Servidor detenido")

    app = FastAPI(title="Jarvis Server", version=__version__, lifespan=lifespan)
    app.state.settings = cfg
    app.state.automation = automation

    def authorized(header: str | None) -> bool:
        return token_is_valid(_bearer(header), tokens)

    # ------------------------------------------------------------- HTTP
    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "version": __version__,
            "uptimeSeconds": int(time.monotonic() - _STARTED_AT),
        }

    @app.get("/v1/info")
    async def info(request: Request):
        if not authorized(request.headers.get("authorization")):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return {
            "version": __version__,
            "server": cfg.summary(),
            "capabilities": _capabilities(cfg, automation, transcriber.name, gate, speech.mode),
        }

    # ------------------------------------------------------------- WebSocket
    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket) -> None:
        await ws.accept()

        try:
            raw = await asyncio.wait_for(ws.receive_text(), timeout=HANDSHAKE_TIMEOUT)
        except TimeoutError:
            await ws.send_json(protocol.error("bad_request", "Handshake timeout", fatal=True))
            await ws.close(code=protocol.CLOSE_HANDSHAKE_TIMEOUT)
            return
        except WebSocketDisconnect:
            return

        try:
            hello = protocol.parse_client_message(raw)
        except protocol.ProtocolError as exc:
            await ws.send_json(protocol.error("bad_request", str(exc), fatal=True))
            await ws.close(code=protocol.CLOSE_BAD_HANDSHAKE)
            return

        if not isinstance(hello, protocol.Hello):
            await ws.send_json(
                protocol.error("bad_request", "El primer mensaje debe ser 'hello'.", fatal=True)
            )
            await ws.close(code=protocol.CLOSE_BAD_HANDSHAKE)
            return

        token = hello.token or ws.query_params.get("token")
        if not token_is_valid(token, tokens):
            _LOG.warning("Handshake rechazado desde %s", ws.client.host if ws.client else "?")
            await ws.send_json(protocol.error("unauthorized", "Token inválido.", fatal=True))
            await ws.close(code=protocol.CLOSE_UNAUTHORIZED)
            return

        if hello.protocol != protocol.PROTOCOL_VERSION:
            await ws.send_json(
                protocol.error(
                    "unsupported",
                    f"Protocolo {hello.protocol} no soportado (servidor: {protocol.PROTOCOL_VERSION}).",
                    fatal=True,
                )
            )
            await ws.close(code=protocol.CLOSE_BAD_HANDSHAKE)
            return

        session_id = secrets.token_hex(4)
        session = AssistantSession(
            ws,
            settings=cfg,
            automation=automation,
            transcriber=transcriber,
            gate=gate,
            speech=speech,
            session_id=session_id,
            device=hello.device,
        )

        await session.send(
            protocol.welcome(
                session_id=session_id,
                server={
                    "name": cfg.server_name,
                    "version": __version__,
                    "platform": sys.platform,
                },
                capabilities=_capabilities(cfg, automation, transcriber.name, gate, speech.mode),
                limits={
                    "maxUtteranceSeconds": cfg.max_utterance_seconds,
                    "utterancesPerMinute": cfg.utterances_per_minute,
                },
            )
        )
        await session.set_state("idle")
        device_name = hello.device.name if hello.device and hello.device.name else "dispositivo"
        _LOG.info("Sesión %s iniciada (%s)", session_id, device_name)

        try:
            while True:
                try:
                    message = await asyncio.wait_for(ws.receive(), timeout=SESSION_IDLE_TIMEOUT)
                except TimeoutError:
                    _LOG.info(
                        "Sesión %s sin actividad durante %.0f s; cerrando",
                        session_id,
                        SESSION_IDLE_TIMEOUT,
                    )
                    with contextlib.suppress(Exception):
                        await ws.close(code=protocol.CLOSE_HANDSHAKE_TIMEOUT)
                    break
                kind = message.get("type")
                if kind == "websocket.disconnect":
                    break
                if message.get("bytes") is not None:
                    await session.handle_audio(message["bytes"])
                    continue
                if message.get("text") is not None:
                    await session.handle(message["text"])
        except WebSocketDisconnect:
            pass
        except Exception:
            _LOG.exception("Error en la sesión %s", session_id)
            with contextlib.suppress(Exception):
                await ws.close(code=protocol.CLOSE_INTERNAL)
        finally:
            session.close()
            _LOG.info("Sesión %s finalizada", session_id)

    return app


def _capabilities(
    cfg: Settings,
    automation: AutomationService,
    transcriber_name: str,
    gate: Any,
    tts_mode: str,
) -> dict[str, Any]:
    return {
        "stt": transcriber_name != "none",
        "sttBackend": transcriber_name,
        "wakeWord": bool(getattr(gate, "requires_wake_word", False)),
        "tts": tts_mode,
        "dryRun": cfg.dry_run,
        "requireConfirmation": cfg.require_confirmation,
        "automation": automation.registry.names(),
        "wolTargets": automation.wol_names(),
    }


app = create_app()
