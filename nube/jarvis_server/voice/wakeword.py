"""Puerta de activación por palabra clave.

Tres implementaciones intercambiables:

* ``AlwaysOnGate`` — el móvil decide cuándo hablar (push-to-talk o VAD en el dispositivo).
* ``EnergyGate`` — descarta silencio puro (RMS) antes de gastar CPU en STT.
* ``OpenWakeWordGate`` — detección local de "hey jarvis" con openWakeWord (opcional).
"""

from __future__ import annotations

import logging
import math
import unicodedata
from typing import Protocol

from ..config import Settings

_LOG = logging.getLogger("jarvis.wakeword")
SAMPLE_RATE = 16000


def rms_level(pcm: bytes) -> float:
    """RMS normalizado [0, 1] de PCM16LE. Suficiente como VAD de energía."""
    if len(pcm) < 2:
        return 0.0
    usable = pcm[: len(pcm) - (len(pcm) % 2)]
    total = 0
    count = 0
    for i in range(0, len(usable), 2):
        sample = int.from_bytes(usable[i : i + 2], "little", signed=True)
        total += sample * sample
        count += 1
    if not count:
        return 0.0
    return min(1.0, math.sqrt(total / count) / 32768.0)


def fold(text: str) -> str:
    """minúsculas sin acentos, para comparar palabras clave."""
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(c for c in normalized if not unicodedata.combining(c)).lower().strip()


class ActivationGate(Protocol):
    requires_wake_word: bool

    def should_activate(self, pcm: bytes, sample_rate: int = SAMPLE_RATE) -> bool: ...


class AlwaysOnGate:
    requires_wake_word = False

    def should_activate(self, pcm: bytes, sample_rate: int = SAMPLE_RATE) -> bool:
        return True


class EnergyGate:
    """Rechaza locuciones por debajo del umbral de energía."""

    requires_wake_word = False

    def __init__(self, threshold: float = 0.008) -> None:
        self._threshold = max(0.0, threshold)

    def should_activate(self, pcm: bytes, sample_rate: int = SAMPLE_RATE) -> bool:
        return rms_level(pcm) >= self._threshold


class OpenWakeWordGate:
    """Detección local de palabra clave; nunca envía audio a la red."""

    requires_wake_word = True
    DEFAULT_MODEL = "hey_jarvis_v0.1"

    def __init__(self, threshold: float = 0.55, model_name: str = DEFAULT_MODEL) -> None:
        self._threshold = threshold
        self._model_name = model_name
        self._model = None

    def _ensure_model(self):
        if self._model is not None:
            return self._model
        from pathlib import Path

        import openwakeword
        from openwakeword import utils as openwakeword_utils
        from openwakeword.model import Model

        _LOG.info("Cargando openWakeWord (%s)", self._model_name)
        models_dir = Path(openwakeword.__file__).resolve().parent / "resources" / "models"
        model_path = models_dir / f"{self._model_name}.onnx"
        if not model_path.exists():
            # El wheel no incluye los modelos: se descargan una sola vez.
            _LOG.info("Descargando modelos de openWakeWord (solo la primera vez)...")
            openwakeword_utils.download_models(model_names=[self._model_name])
        if not model_path.exists():
            raise FileNotFoundError(f"No se encontró el modelo de wake word {self._model_name!r}")

        self._model = Model(wakeword_models=[str(model_path)], inference_framework="onnx")
        return self._model

    def should_activate(self, pcm: bytes, sample_rate: int = SAMPLE_RATE) -> bool:
        if len(pcm) < 2:
            return False
        import numpy as np

        usable = pcm[: len(pcm) - (len(pcm) % 2)]
        audio = np.frombuffer(usable, dtype="<i2")
        try:
            model = self._ensure_model()
            scores = model.predict(audio)
        except Exception as exc:  # el modelo no debe tumbar la sesión
            _LOG.warning("openWakeWord falló (%s); se activa por defecto", exc)
            return True
        best = max(scores.values()) if scores else 0.0
        _LOG.debug("openWakeWord score=%.3f", best)
        return float(best) >= self._threshold


def strip_wake_word(text: str, phrases: tuple[str, ...]) -> str:
    """Elimina el prefijo de activación ("oye jarvis, …") del texto transcrito."""
    cleaned = text.strip()
    if not cleaned:
        return cleaned
    normalized_phrases = {fold(p) for p in phrases if p.strip()}
    words = cleaned.split()
    for size in (3, 2, 1):
        if len(words) <= size:
            continue
        head = fold(" ".join(words[:size])).strip(" ,.!¡¿?;:-")
        if head in normalized_phrases:
            return " ".join(words[size:]).lstrip(" ,.!¡¿?;:-")
    return cleaned


def contains_wake_word(text: str, phrases: tuple[str, ...]) -> bool:
    normalized = fold(text)
    return any(fold(p) in normalized for p in phrases if p.strip())


def build_gate(settings: Settings) -> ActivationGate:
    if not settings.wake_word_enabled:
        _LOG.info("Palabra clave desactivada: activación directa (PTT/VAD del móvil).")
        return EnergyGate(settings.energy_gate_rms)

    try:
        import openwakeword  # noqa: F401
    except Exception:
        _LOG.warning(
            "openWakeWord no instalado; se usará la puerta de energía. "
            "Instala con: pip install -e \".[voice]\""
        )
        return EnergyGate(settings.energy_gate_rms)

    return OpenWakeWordGate(settings.wake_word_threshold, settings.wake_word_model)
