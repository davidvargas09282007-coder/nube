"""Control multimedia y de volumen con las teclas de medios del sistema."""

from __future__ import annotations

import asyncio
import logging
import subprocess
import sys
from typing import Any

from ..registry import registry
from ..types import ActionContext, ActionResult

_LOG = logging.getLogger("jarvis.actions.media")

_IS_WINDOWS = sys.platform.startswith("win")
_IS_MAC = sys.platform == "darwin"

# Códigos de tecla virtual de Windows (VK_VOLUME_*, VK_MEDIA_*)
_VK = {
    "mute": 173,
    "down": 174,
    "up": 175,
    "next": 176,
    "prev": 177,
    "play_pause": 179,
}


def _windows_key(code: int, times: int = 1) -> None:
    action = f"(New-Object -ComObject WScript.Shell).SendKeys([char]{code})"
    script = "; ".join([action] * max(1, times))
    subprocess.Popen(
        ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", script],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _mac_osascript(script: str) -> None:
    subprocess.Popen(
        ["osascript", "-e", script],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _linux_amixer(*args: str) -> bool:
    try:
        subprocess.run(["amixer", "-q", *args], check=True, capture_output=True)
        return True
    except Exception:
        return False


def _key(kind: str) -> bool:
    """Pulsa una tecla de medios. Devuelve ``False`` si no hay backend."""
    if _IS_WINDOWS:
        _windows_key(_VK[kind])
        return True
    if _IS_MAC:
        scripts = {
            "play_pause": 'tell application "Music" to playpause',
            "next": 'tell application "Music" to next track',
            "prev": 'tell application "Music" to previous track',
            "mute": "set volume with output muted",
            "up": "set volume output volume ((output volume of (get volume settings)) + 6)",
            "down": "set volume output volume ((output volume of (get volume settings)) - 6)",
        }
        _mac_osascript(scripts[kind])
        return True
    commands = {
        "play_pause": ("playerctl", "play-pause"),
        "next": ("playerctl", "next"),
        "prev": ("playerctl", "previous"),
        "mute": ("amixer", "-q", "sset", "Master", "toggle"),
        "up": ("amixer", "-q", "sset", "Master", "5%+"),
        "down": ("amixer", "-q", "sset", "Master", "5%-"),
    }
    try:
        subprocess.run(commands[kind], check=True, capture_output=True)
        return True
    except Exception:
        return False


def _set_absolute_volume(level: int) -> bool:
    level = max(0, min(100, level))
    if _IS_MAC:
        _mac_osascript(f"set volume output volume {level}")
        return True
    if not _IS_WINDOWS:
        return _linux_amixer("sset", "Master", f"{level}%")
    return False  # Windows requiere pycaw; se usa ajuste relativo


async def _perform(func, *args) -> bool:
    return await asyncio.to_thread(func, *args)


# --------------------------------------------------------------------------- intents
@registry.intent(
    "media.play_pause",
    patterns=[
        r"^(?:pausa|pausar|pause|reanuda|reanudar|resume|play|reproduce|continua)"
        r"(?:\s+(?:la\s+)?(?:musica|video|cancion|reproduccion))?$"
    ],
    description="Pausa o reanuda la reproducción",
    examples=["pausa la música", "reanuda"],
)
async def play_pause(ctx: ActionContext, args: dict[str, Any]) -> ActionResult:
    if ctx.policy.dry_run:
        return ActionResult.success("(simulación) Pausaría o reanudaría la reproducción.", dryRun=True)
    if not await _perform(_key, "play_pause"):
        return ActionResult.failure("No encuentro un reproductor compatible.")
    return ActionResult.success("Hecho.")


@registry.intent(
    "media.next",
    patterns=[r"^(?:siguiente(?:\s+cancion)?|pasa(?:\s+(?:la\s+)?cancion)?|next(?:\s+track)?)$"],
    description="Pasa a la siguiente canción",
    examples=["siguiente canción"],
)
async def next_track(ctx: ActionContext, args: dict[str, Any]) -> ActionResult:
    if ctx.policy.dry_run:
        return ActionResult.success("(simulación) Cambiaría de canción.", dryRun=True)
    if not await _perform(_key, "next"):
        return ActionResult.failure("No encuentro un reproductor compatible.")
    return ActionResult.success("Siguiente canción.")


@registry.intent(
    "media.previous",
    patterns=[r"^(?:anterior(?:\s+cancion)?|cancion\s+anterior|previous|prev)$"],
    description="Vuelve a la canción anterior",
    examples=["canción anterior"],
)
async def previous_track(ctx: ActionContext, args: dict[str, Any]) -> ActionResult:
    if ctx.policy.dry_run:
        return ActionResult.success("(simulación) Volvería a la canción anterior.", dryRun=True)
    if not await _perform(_key, "prev"):
        return ActionResult.failure("No encuentro un reproductor compatible.")
    return ActionResult.success("Canción anterior.")


@registry.intent(
    "media.mute",
    patterns=[
        r"^(?:silencia|silenciar|mutea|mute|quita\s+el\s+sonido|activa\s+el\s+silencio)$"
    ],
    description="Silencia o restaura el sonido",
    examples=["silencia", "quita el sonido"],
)
async def mute(ctx: ActionContext, args: dict[str, Any]) -> ActionResult:
    if ctx.policy.dry_run:
        return ActionResult.success("(simulación) Silenciaría el equipo.", dryRun=True)
    if not await _perform(_key, "mute"):
        return ActionResult.failure("No he podido cambiar el silencio.")
    return ActionResult.success("Silencio alternado.")


@registry.intent(
    "media.volume",
    patterns=[
        r"^(?P<direction>sube|subir|aumenta|aumentar|baja|bajar|reduce|reducir|pon|poner|set)"
        r"\s+(?:el\s+|la\s+)?volumen(?:\s+(?:a|al)\s+(?P<level>\d{1,3}))?$",
        r"^volumen\s+(?P<direction2>arriba|abajo)$",
    ],
    description="Sube, baja o fija el volumen",
    examples=["sube el volumen", "pon el volumen a 40"],
)
async def volume(ctx: ActionContext, args: dict[str, Any]) -> ActionResult:
    direction = (args.get("direction") or args.get("direction2") or "").lower()
    raw_level = args.get("level")

    if ctx.policy.dry_run:
        target = f" al {raw_level} por ciento" if raw_level else ""
        return ActionResult.success(f"(simulación) Ajustaría el volumen{target}.", dryRun=True)

    if raw_level is not None:
        level = max(0, min(100, int(raw_level)))
        if await _perform(_set_absolute_volume, level):
            return ActionResult.success(f"Volumen al {level} por ciento.", volume=level)
        return ActionResult.failure(
            "Puedo subir o bajar el volumen, pero no fijar un nivel exacto en este sistema."
        )

    going_up = direction.startswith(("sube", "sub", "aumenta", "aum", "arriba"))
    if await _perform(_key, "up" if going_up else "down"):
        return ActionResult.success("Volumen más alto." if going_up else "Volumen más bajo.")
    return ActionResult.failure("No he podido cambiar el volumen.")
