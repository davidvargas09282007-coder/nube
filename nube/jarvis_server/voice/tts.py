"""Preparación de la locución.

En v1 la voz la pone el móvil con ``expo-speech``: es instantánea, respeta las voces del
sistema y evita transmitir audio de vuelta. El servidor solo limpia el texto para que suene
bien leído en alto (sin markdown, sin rutas largas, con longitud acotada).

Punto de extensión: implementar ``SpeechRenderer`` con Piper/Coqui para modo manos libres
sin depender del TTS del teléfono. El protocolo ya prevé ``speak`` y ``mode``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

_MARKDOWN = re.compile(r"[*_`#>|]+")
_PATHISH = re.compile(r"([A-Za-z]:\\[^\s]+|/[^\s]+)")
_SPACES = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class SpeechPlan:
    text: str
    mode: str = "client"
    audio_path: str | None = None


class SpeechRenderer(Protocol):
    mode: str

    def render(self, text: str) -> SpeechPlan: ...


def clean_for_speech(text: str, max_chars: int = 600) -> str:
    """Texto apto para TTS: sin markdown, sin rutas, sin espacios raros."""
    plain = _MARKDOWN.sub("", text or "")
    plain = _PATHISH.sub("un archivo", plain)
    plain = _SPACES.sub(" ", plain).strip()
    if len(plain) <= max_chars:
        return plain
    cut = plain[:max_chars].rsplit(" ", 1)[0]
    return f"{cut}…"


class ClientSpeechRenderer:
    """La app locuta; el servidor solo entrega texto limpio."""

    mode = "client"

    def render(self, text: str) -> SpeechPlan:
        return SpeechPlan(text=clean_for_speech(text), mode="client")


def build_speech_renderer() -> SpeechRenderer:
    return ClientSpeechRenderer()
