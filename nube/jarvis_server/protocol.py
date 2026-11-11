"""Contrato WebSocket v1.

La especificación legible está en ``docs/PROTOCOL.md``. Este módulo es el espejo ejecutable:
modelos Pydantic para lo que entra y un constructor uniforme para lo que sale.
"""

from __future__ import annotations

import time
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

PROTOCOL_VERSION = 1
MAX_MESSAGE_BYTES = 1024 * 1024
MAX_AUDIO_FRAME_BYTES = 64 * 1024

CLOSE_UNAUTHORIZED = 4401
CLOSE_BAD_HANDSHAKE = 4400
CLOSE_HANDSHAKE_TIMEOUT = 4408
CLOSE_RATE_LIMITED = 4429
CLOSE_INTERNAL = 1011


class AudioFormat(BaseModel):
    model_config = ConfigDict(extra="ignore")

    codec: Literal["pcm_s16le", "pcm16"] = "pcm_s16le"
    sampleRate: int = 16000
    channels: Literal[1] = 1


class DeviceInfo(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = ""
    name: str = ""
    platform: str = ""
    appVersion: str = ""


class Hello(BaseModel):
    type: Literal["hello"]
    protocol: int = PROTOCOL_VERSION
    token: str | None = None
    device: DeviceInfo | None = None


class TextCommand(BaseModel):
    type: Literal["text"]
    id: str = Field(max_length=64)
    text: str = Field(min_length=1, max_length=2000)


class AudioStart(BaseModel):
    type: Literal["audio.start"]
    id: str = Field(max_length=64)
    format: AudioFormat = Field(default_factory=AudioFormat)


class AudioEnd(BaseModel):
    type: Literal["audio.end"]
    id: str = Field(max_length=64)


class AudioCancel(BaseModel):
    type: Literal["audio.cancel"]
    id: str = Field(max_length=64)


class Confirm(BaseModel):
    type: Literal["confirm"]
    id: str = Field(max_length=64)
    approved: bool = False


class WolRequest(BaseModel):
    type: Literal["wol"]
    target: str | None = None


class Ping(BaseModel):
    type: Literal["ping"]
    t: int | None = None


ClientMessage = Annotated[
    Hello | TextCommand | AudioStart | AudioEnd | AudioCancel | Confirm | WolRequest | Ping,
    Field(discriminator="type"),
]

_CLIENT_ADAPTER: TypeAdapter[Any] = TypeAdapter(ClientMessage)


class ProtocolError(ValueError):
    """Mensaje de cliente mal formado o tipo desconocido."""


def parse_client_message(raw: str | bytes) -> ClientMessage:
    try:
        return _CLIENT_ADAPTER.validate_json(raw)
    except ValidationError as exc:
        first = exc.errors()[0] if exc.errors() else {}
        location = ".".join(str(p) for p in first.get("loc", ())) or "mensaje"
        raise ProtocolError(f"{location}: {first.get('msg', 'inválido')}") from exc


def event(kind: str, **payload: Any) -> dict[str, Any]:
    """Evento de servidor con sello temporal."""
    return {"type": kind, "ts": int(time.time() * 1000), **payload}


def state(value: Literal["idle", "listening", "thinking", "speaking"], reason: str = "") -> dict[str, Any]:
    body = event("state", state=value)
    if reason:
        body["reason"] = reason
    return body


def error(code: str, message: str, *, fatal: bool = False) -> dict[str, Any]:
    return event("error", code=code, message=message, fatal=fatal)


def log(message: str, level: str = "info") -> dict[str, Any]:
    return event("log", level=level, message=message)


def reply(
    utterance_id: str,
    text: str,
    *,
    action: str | None = None,
    ok: bool = True,
    data: dict[str, Any] | None = None,
    speak: bool = True,
) -> dict[str, Any]:
    body: dict[str, Any] = event("reply", utteranceId=utterance_id, text=text, speak=speak, ok=ok)
    if action:
        body["action"] = action
    if data:
        body["data"] = data
    return body


def welcome(
    *,
    session_id: str,
    server: dict[str, Any],
    capabilities: dict[str, Any],
    limits: dict[str, Any],
    sample_rate: int = 16000,
) -> dict[str, Any]:
    return event(
        "welcome",
        protocol=PROTOCOL_VERSION,
        sessionId=session_id,
        server=server,
        capabilities=capabilities,
        audio={"input": {"codec": "pcm_s16le", "sampleRate": sample_rate, "channels": 1, "frameHint": 2048}},
        limits=limits,
    )
