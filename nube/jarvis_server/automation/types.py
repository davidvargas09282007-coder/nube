"""Tipos compartidos por el motor de automatización."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..config import Settings
    from ..network.wol import WakeOnLanService
    from .safety import SafetyPolicy


@dataclass(slots=True)
class ActionResult:
    """Resultado de un handler. ``speech`` es lo que el asistente dice."""

    ok: bool
    speech: str
    data: dict[str, Any] = field(default_factory=dict)
    needs_confirmation: bool = False
    prompt: str = ""

    @classmethod
    def success(cls, speech: str, **data: Any) -> ActionResult:
        return cls(ok=True, speech=speech, data=data)

    @classmethod
    def failure(cls, speech: str, **data: Any) -> ActionResult:
        return cls(ok=False, speech=speech, data=data)

    @classmethod
    def confirmation(cls, prompt: str, **data: Any) -> ActionResult:
        return cls(ok=False, speech=prompt, data=data, needs_confirmation=True, prompt=prompt)


@dataclass(slots=True)
class ActionContext:
    """Todo lo que un handler necesita, sin acceso a la conexión WebSocket."""

    settings: Settings
    policy: SafetyPolicy
    wol: WakeOnLanService
    session_id: str = ""
    language: str = "es"


ActionHandler = Callable[[ActionContext, dict[str, Any]], Awaitable[ActionResult]]
