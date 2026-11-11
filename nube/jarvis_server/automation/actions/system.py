"""Acciones sobre el sistema operativo: apps, energía, pantalla, información."""

from __future__ import annotations

import asyncio
import ctypes
import logging
import subprocess
import sys
import webbrowser
from datetime import datetime
from typing import Any

from ..registry import registry
from ..types import ActionContext, ActionResult

_LOG = logging.getLogger("jarvis.actions.system")

_IS_WINDOWS = sys.platform.startswith("win")
_IS_MAC = sys.platform == "darwin"


def _spawn(command: list[str]) -> None:
    subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=not _IS_WINDOWS,
    )


def _simulated(ctx: ActionContext) -> bool:
    return ctx.policy.dry_run


# --------------------------------------------------------------------------- URLs
@registry.intent(
    "system.open_url",
    patterns=[
        r"^(?:abre|abrir|navega\s+a|ve\s+a|entra\s+en|open|goto|go\s+to)\s+"
        r"(?:la\s+|el\s+)?(?:web\s+|pagina\s+|sitio\s+|url\s+)?"
        r"(?P<url>(?:https?://)?[a-z0-9-]+(?:\.[a-z0-9-]+)+(?::\d+)?(?:/\S*)?)$"
    ],
    description="Abre una dirección web en el navegador",
    examples=["abre github.com", "navega a https://miweb.dev"],
)
async def open_url(ctx: ActionContext, args: dict[str, Any]) -> ActionResult:
    raw = (args.get("url") or "").strip()
    if not raw:
        return ActionResult.failure("No he entendido la dirección.")
    url = raw if raw.startswith(("http://", "https://")) else f"https://{raw}"
    if _simulated(ctx):
        return ActionResult.success(f"(simulación) Abriría {url}.", url=url, dryRun=True)
    opened = await asyncio.to_thread(webbrowser.open, url)
    if not opened:
        return ActionResult.failure("No he podido abrir el navegador.")
    return ActionResult.success(f"Abriendo {raw}.", url=url)


# --------------------------------------------------------------------------- apps
@registry.intent(
    "system.open_app",
    patterns=[
        r"^(?:abre|abrir|lanza|lanzar|ejecuta|ejecutar|inicia|iniciar|open|launch|run)\s+"
        r"(?!el\s+archivo\b|la\s+carpeta\b|el\s+fichero\b|el\s+documento\b|la\s+url\b|"
        r"el\s+sitio\b|la\s+web\b|la\s+pagina\b)"
        r"(?:la\s+|el\s+|la\s+app\s+|el\s+programa\s+|app\s+|programa\s+)?"
        r"(?P<app>[a-z0-9][a-z0-9 ._+-]{1,39})$"
    ],
    description="Abre una aplicación de la lista permitida",
    examples=["abre chrome", "abre el programa notepad"],
)
async def open_app(ctx: ActionContext, args: dict[str, Any]) -> ActionResult:
    requested = " ".join((args.get("app") or "").lower().split())
    if not requested:
        return ActionResult.failure("¿Qué aplicación quieres que abra?")

    allowlist = ctx.settings.app_allowlist
    if not allowlist:
        return ActionResult.failure(
            "No hay aplicaciones permitidas. Añádelas en JARVIS_APP_ALLOWLIST, "
            "por ejemplo: chrome=chrome.exe,notepad=notepad.exe"
        )

    command = allowlist.get(requested)
    resolved_name = requested
    if command is None:
        for alias, candidate in allowlist.items():
            if requested in alias or alias in requested:
                command, resolved_name = candidate, alias
                break

    if command is None:
        options = ", ".join(sorted(allowlist))
        return ActionResult.failure(f"No conozco «{requested}». Puedo abrir: {options}.")

    if _simulated(ctx):
        return ActionResult.success(
            f"(simulación) Abriría {resolved_name}.", app=resolved_name, dryRun=True
        )

    try:
        _spawn([command])
    except OSError as exc:
        _LOG.warning("No se pudo lanzar %s: %s", command, exc)
        return ActionResult.failure(f"No he podido abrir {resolved_name}.")
    return ActionResult.success(f"Abriendo {resolved_name}.", app=resolved_name)


# --------------------------------------------------------------------------- energía
@registry.intent(
    "system.lock",
    patterns=[
        r"^(?:bloquea|bloquear|lock)\s+(?:el\s+|la\s+)?"
        r"(?:pc|equipo|ordenador|computadora|sesion|pantalla|screen|session)$",
        r"^(?:bloquea|bloquear)\s+(?:la\s+)?(?:pantalla|sesion)$",
    ],
    description="Bloquea la sesión del equipo",
    examples=["bloquea el equipo", "bloquear sesión"],
)
async def lock_screen(ctx: ActionContext, args: dict[str, Any]) -> ActionResult:
    if _simulated(ctx):
        return ActionResult.success("(simulación) Bloquearía la sesión.", dryRun=True)
    try:
        if _IS_WINDOWS:
            ctypes.windll.user32.LockWorkStation()
        elif _IS_MAC:
            _spawn(["pmset", "displaysleepnow"])
        else:
            _spawn(["loginctl", "lock-session"])
    except Exception:
        _LOG.exception("fallo bloqueando la sesión")
        return ActionResult.failure("No he podido bloquear la sesión.")
    return ActionResult.success("Equipo bloqueado.")


@registry.intent(
    "system.shutdown",
    patterns=[
        r"^(?:apaga|apagar|shutdown|power\s+off)\s*(?:el\s+|la\s+)?"
        r"(?:pc|equipo|ordenador|computadora|maquina|sistema)?$"
    ],
    destructive=True,
    description="Apaga el equipo (requiere confirmación)",
    examples=["apaga el equipo", "apagar"],
)
async def shutdown(ctx: ActionContext, args: dict[str, Any]) -> ActionResult:
    if _simulated(ctx):
        return ActionResult.success("(simulación) Apagaría el equipo.", dryRun=True)
    try:
        if _IS_WINDOWS:
            _spawn(["shutdown", "/s", "/t", "20", "/c", "Apagado solicitado por Jarvis"])
        elif _IS_MAC:
            _spawn(["osascript", "-e", 'tell app "System Events" to shut down'])
        else:
            _spawn(["systemctl", "poweroff"])
    except Exception:
        _LOG.exception("fallo apagando")
        return ActionResult.failure("No he podido apagar el equipo.")
    return ActionResult.success("Apagando el equipo en 20 segundos. Di «cancela el apagado» para abortar.")


@registry.intent(
    "system.restart",
    patterns=[
        r"^(?:reinicia|reiniciar|restart|reboot)\s*(?:el\s+|la\s+)?"
        r"(?:pc|equipo|ordenador|computadora|maquina|sistema)?$"
    ],
    destructive=True,
    description="Reinicia el equipo (requiere confirmación)",
    examples=["reinicia el equipo", "restart"],
)
async def restart(ctx: ActionContext, args: dict[str, Any]) -> ActionResult:
    if _simulated(ctx):
        return ActionResult.success("(simulación) Reiniciaría el equipo.", dryRun=True)
    try:
        if _IS_WINDOWS:
            _spawn(["shutdown", "/r", "/t", "20", "/c", "Reinicio solicitado por Jarvis"])
        elif _IS_MAC:
            _spawn(["osascript", "-e", 'tell app "System Events" to restart'])
        else:
            _spawn(["systemctl", "reboot"])
    except Exception:
        _LOG.exception("fallo reiniciando")
        return ActionResult.failure("No he podido reiniciar el equipo.")
    return ActionResult.success("Reiniciando el equipo en 20 segundos. Di «cancela el apagado» para abortar.")


@registry.intent(
    "system.cancel_shutdown",
    patterns=[
        r"^(?:cancela|cancelar|aborta|abortar|cancel)\s+(?:el\s+)?(?:apagado|reinicio|shutdown)$"
    ],
    description="Cancela un apagado o reinicio programado",
    examples=["cancela el apagado"],
)
async def cancel_shutdown(ctx: ActionContext, args: dict[str, Any]) -> ActionResult:
    if _IS_WINDOWS:
        if _simulated(ctx):
            return ActionResult.success("(simulación) Cancelaría el apagado.", dryRun=True)
        completed = await asyncio.to_thread(
            subprocess.run, ["shutdown", "/a"], capture_output=True, text=True
        )
        if completed.returncode != 0:
            return ActionResult.failure("No había ningún apagado pendiente.")
        return ActionResult.success("Apagado cancelado.")
    return ActionResult.failure("Cancelar apagados programados solo está implementado en Windows.")


# --------------------------------------------------------------------------- pantalla
@registry.intent(
    "system.screenshot",
    patterns=[
        r"^(?:haz\s+una\s+)?(?:captura|pantallazo|screenshot)(?:\s+de\s+(?:la\s+)?pantalla)?$",
        r"^(?:captura|guardar?)\s+(?:la\s+)?pantalla$",
    ],
    description="Guarda una captura de pantalla en la carpeta de notas",
    examples=["haz una captura de pantalla"],
)
async def screenshot(ctx: ActionContext, args: dict[str, Any]) -> ActionResult:
    target_dir = ctx.settings.notes_path
    path = target_dir / f"captura-{datetime.now():%Y%m%d-%H%M%S}.png"

    if _simulated(ctx):
        return ActionResult.success("(simulación) Guardaría una captura de pantalla.", dryRun=True)

    target_dir.mkdir(parents=True, exist_ok=True)
    try:
        if _IS_WINDOWS or _IS_MAC:
            from PIL import ImageGrab  # dependencia opcional: pillow

            await asyncio.to_thread(lambda: ImageGrab.grab().save(path))
        else:
            await asyncio.to_thread(
                subprocess.run, ["gnome-screenshot", "-f", str(path)], check=True
            )
    except ImportError:
        return ActionResult.failure("Falta Pillow para capturas. Instala: pip install pillow")
    except Exception:
        _LOG.exception("fallo en la captura")
        return ActionResult.failure("No he podido capturar la pantalla.")
    return ActionResult.success("Captura guardada.", path=str(path))


# --------------------------------------------------------------------------- info
@registry.intent(
    "system.info",
    patterns=[
        r"^(?:estado\s+del\s+sistema|informe\s+del\s+sistema|diagnostico|"
        r"como\s+estas|status|system\s+info|uso\s+de\s+cpu|cuanta\s+memoria)$"
    ],
    description="Informa de CPU, memoria y batería",
    examples=["estado del sistema", "cómo estás"],
)
async def system_info(ctx: ActionContext, args: dict[str, Any]) -> ActionResult:
    data: dict[str, Any] = {"platform": sys.platform}
    parts: list[str] = []

    try:
        import psutil  # dependencia opcional

        data["cpuPercent"] = psutil.cpu_percent(interval=0.2)
        memory = psutil.virtual_memory()
        data["memoryPercent"] = memory.percent
        parts.append(f"CPU al {data['cpuPercent']:.0f} por ciento")
        parts.append(f"memoria al {memory.percent:.0f} por ciento")
        if hasattr(psutil, "sensors_battery"):
            battery = psutil.sensors_battery()
            if battery is not None:
                data["batteryPercent"] = round(battery.percent)
                data["plugged"] = battery.power_plugged
                parts.append(f"batería al {battery.percent:.0f} por ciento")
    except Exception:
        _LOG.debug("psutil no disponible para system.info")

    uptime = await asyncio.to_thread(_uptime_minutes)
    if uptime is not None:
        data["uptimeMinutes"] = uptime

    speech = "Todo funcionando. " + (", ".join(parts) if parts else "Sin métricas disponibles.")
    return ActionResult.success(speech, **data)


def _uptime_minutes() -> int | None:
    try:
        import psutil

        return int((datetime.now().timestamp() - psutil.boot_time()) // 60)
    except Exception:
        return None


@registry.intent(
    "time.now",
    patterns=[
        r"^(?:que\s+hora\s+es|dime\s+la\s+hora|hora\s+actual|what\s+time\s+is\s+it)$"
    ],
    description="Dice la hora actual",
    examples=["qué hora es"],
)
async def tell_time(ctx: ActionContext, args: dict[str, Any]) -> ActionResult:
    now = datetime.now()
    return ActionResult.success(
        f"Son las {now.hour:02d}:{now.minute:02d}.",
        iso=now.isoformat(timespec="seconds"),
    )


# --------------------------------------------------------------------------- meta
@registry.intent(
    "assistant.help",
    patterns=[r"^(?:que\s+puedes\s+hacer|ayuda|help|comandos|que\s+sabes\s+hacer)$"],
    description="Explica las capacidades del asistente",
    examples=["qué puedes hacer", "ayuda"],
)
async def help_intent(ctx: ActionContext, args: dict[str, Any]) -> ActionResult:
    speech = (
        "Puedo abrir aplicaciones y webs, controlar el volumen y la reproducción, "
        "buscar y abrir archivos, tomar notas, bloquear, apagar o reiniciar el equipo "
        "y encender otros equipos con Wake on LAN."
    )
    return ActionResult.success(speech, intents=registry.names())


@registry.intent(
    "assistant.stop",
    patterns=[r"^(?:para|parate|detente|cancela|stop|silencio|callate)$"],
    description="Detiene la locución actual",
    examples=["para", "silencio"],
)
async def stop_intent(ctx: ActionContext, args: dict[str, Any]) -> ActionResult:
    return ActionResult.success("De acuerdo.", stopSpeech=True)
