"""Acción de encendido remoto por Wake-on-LAN."""

from __future__ import annotations

import logging
from typing import Any

from ..registry import registry
from ..types import ActionContext, ActionResult

_LOG = logging.getLogger("jarvis.actions.wol")


@registry.intent(
    "wol.wake",
    patterns=[
        r"^(?:enciende|encender|despierta|despertar|arranca|wake|wake\s+on\s+lan)"
        r"\s+(?:el\s+|la\s+|al\s+)?"
        r"(?:pc|equipo|ordenador|computadora|desktop|servidor|maquina)"
        r"(?:\s+(?:de|del|llamado|llamada)\s+(?P<target>[a-z0-9_-]{1,32}))?$",
        r"^(?:wake)\s+(?P<target>[a-z0-9_-]{1,32})$",
    ],
    description="Envía un magic packet a un equipo configurado",
    examples=["enciende el pc", "wake desktop"],
)
async def wake(ctx: ActionContext, args: dict[str, Any]) -> ActionResult:
    target = args.get("target")
    # El WoL no modifica el equipo local: se ejecuta incluso en modo simulación.
    try:
        woken = await ctx.wol.wake_async(target)
    except ValueError as exc:
        return ActionResult.failure(str(exc))
    except OSError as exc:
        _LOG.warning("No se pudo enviar el magic packet: %s", exc)
        return ActionResult.failure("No he podido enviar la señal de encendido a la red.")

    return ActionResult.success(
        f"Señal de encendido enviada a {woken.name}.",
        target=woken.describe(),
    )


__all__ = ["wake"]
