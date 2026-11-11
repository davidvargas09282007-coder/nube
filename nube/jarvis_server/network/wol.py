"""Wake-on-LAN: construcción del magic packet y envío UDP broadcast."""

from __future__ import annotations

import asyncio
import logging
import re
import socket
import time
from collections.abc import Iterable
from dataclasses import dataclass

_LOG = logging.getLogger("jarvis.wol")

DEFAULT_BROADCAST = "255.255.255.255"
DEFAULT_PORT = 9
_MAC_RE = re.compile(r"^[0-9A-Fa-f]{2}([:-]?[0-9A-Fa-f]{2}){5}$")


class WolError(ValueError):
    """MAC o especificación de objetivo inválida."""


def normalize_mac(mac: str) -> str:
    """Acepta ``aabbccddeeff``, ``AA-BB-CC-DD-EE-FF`` o ``AA:BB:...``; devuelve con ``:``."""
    if not mac or not _MAC_RE.match(mac.strip()):
        raise WolError(f"MAC inválida: {mac!r} (se esperan 6 octetos hexadecimales)")
    digits = re.sub(r"[^0-9A-Fa-f]", "", mac)
    return ":".join(digits[i : i + 2] for i in range(0, 12, 2)).upper()


def build_magic_packet(mac: str) -> bytes:
    """6 bytes 0xFF + la MAC repetida 16 veces (102 bytes)."""
    payload = bytes.fromhex(normalize_mac(mac).replace(":", ""))
    return b"\xff" * 6 + payload * 16


@dataclass(frozen=True, slots=True)
class WolTarget:
    name: str
    mac: str
    broadcast: str = DEFAULT_BROADCAST
    port: int = DEFAULT_PORT

    @property
    def packet(self) -> bytes:
        return build_magic_packet(self.mac)

    def describe(self) -> dict[str, object]:
        return {"name": self.name, "mac": self.mac, "broadcast": self.broadcast, "port": self.port}


def parse_target(
    spec: str,
    *,
    default_broadcast: str = DEFAULT_BROADCAST,
    default_port: int = DEFAULT_PORT,
) -> WolTarget:
    """Formato: ``nombre=AA:BB:CC:DD:EE:FF@192.168.1.255:9``.

    El nombre y el sufijo ``@host:puerto`` son opcionales.
    """
    raw = (spec or "").strip()
    if not raw:
        raise WolError("Especificación de objetivo vacía")

    name, rest = (raw.split("=", 1) if "=" in raw else ("", raw))
    host, port = default_broadcast, default_port

    if "@" in rest:
        mac_part, host_part = rest.split("@", 1)
        if host_part.count(":") == 1:
            maybe_host, maybe_port = host_part.rsplit(":", 1)
            if maybe_port.isdigit():
                host, port = maybe_host, int(maybe_port)
            else:
                host = host_part
        else:
            host = host_part
    else:
        mac_part = rest

    mac = normalize_mac(mac_part)
    return WolTarget(name=(name.strip() or mac), mac=mac, broadcast=host.strip(), port=port)


def subnet_broadcast(ip: str) -> str:
    """Asume /24, que cubre el 99 % de las redes domésticas."""
    parts = (ip or "").split(".")
    if len(parts) != 4 or not all(p.isdigit() for p in parts):
        raise WolError(f"IPv4 inválida: {ip!r}")
    return ".".join([*parts[:3], "255"])


def send_magic_packet(target: WolTarget, *, repeat: int = 3, interval: float = 0.05) -> None:
    """Envía el paquete varias veces (las NIC a veces pierden el primero)."""
    packet = target.packet
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.bind(("", 0))
        for _ in range(max(1, repeat)):
            sock.sendto(packet, (target.broadcast, target.port))
            time.sleep(interval)
    _LOG.info("WoL enviado a %s (%s) vía %s:%s", target.name, target.mac, target.broadcast, target.port)


class WakeOnLanService:
    """Objetivos configurados (``JARVIS_WOL_TARGETS``) listos para despertar."""

    def __init__(self, targets: Iterable[WolTarget], *, repeat: int = 3) -> None:
        self._targets: dict[str, WolTarget] = {t.name.lower(): t for t in targets}
        self._repeat = max(1, repeat)

    @classmethod
    def from_specs(
        cls,
        specs: Iterable[str],
        *,
        default_broadcast: str = DEFAULT_BROADCAST,
        default_port: int = DEFAULT_PORT,
        repeat: int = 3,
    ) -> WakeOnLanService:
        parsed = []
        for spec in specs:
            try:
                parsed.append(parse_target(spec, default_broadcast=default_broadcast, default_port=default_port))
            except WolError as exc:
                _LOG.warning("Objetivo WoL ignorado (%s): %s", spec, exc)
        return cls(parsed, repeat=repeat)

    @property
    def targets(self) -> list[WolTarget]:
        return list(self._targets.values())

    @property
    def names(self) -> list[str]:
        return [t.name for t in self._targets.values()]

    def get(self, name: str | None = None) -> WolTarget:
        if not self._targets:
            raise WolError("No hay objetivos WoL configurados (JARVIS_WOL_TARGETS)")
        if name:
            target = self._targets.get(name.strip().lower())
            if target is None:
                raise WolError(
                    f"Objetivo desconocido: {name!r}. Disponibles: {', '.join(self.names)}"
                )
            return target
        if len(self._targets) == 1:
            return next(iter(self._targets.values()))
        raise WolError(f"Especifica el objetivo: {', '.join(self.names)}")

    def wake(self, name: str | None = None) -> WolTarget:
        target = self.get(name)
        send_magic_packet(target, repeat=self._repeat)
        return target

    async def wake_async(self, name: str | None = None) -> WolTarget:
        return await asyncio.to_thread(self.wake, name)
