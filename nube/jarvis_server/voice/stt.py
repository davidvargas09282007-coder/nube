"""Reconocimiento de voz local con ``faster-whisper``.

La carga del modelo es perezosa: el servidor arranca sin dependencias pesadas y solo
importa ``faster_whisper`` la primera vez que llega audio. Si no está instalado se usa
``NullTranscriber`` y el asistente sigue funcionando en modo texto.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Protocol

from ..config import Settings

_LOG = logging.getLogger("jarvis.stt")
SAMPLE_RATE = 16000


@dataclass(frozen=True, slots=True)
class Transcript:
    text: str
    language: str | None = None
    duration_ms: int = 0


def _duration_ms(pcm: bytes, sample_rate: int) -> int:
    return int((len(pcm) / 2) / max(1, sample_rate) * 1000)


class Transcriber(Protocol):
    name: str

    def transcribe(self, pcm: bytes, sample_rate: int = SAMPLE_RATE) -> Transcript: ...


class NullTranscriber:
    """Sin motor de voz: devuelve vacío (el cliente usará comandos de texto)."""

    name = "none"

    def transcribe(self, pcm: bytes, sample_rate: int = SAMPLE_RATE) -> Transcript:
        _LOG.debug("NullTranscriber: %d bytes de audio descartados", len(pcm))
        return Transcript(text="", duration_ms=_duration_ms(pcm, sample_rate))


class FasterWhisperTranscriber:
    """STT local. Adecuado para CPU con ``compute_type="int8"``."""

    name = "faster-whisper"

    def __init__(
        self,
        model_size: str = "small",
        *,
        device: str = "cpu",
        compute_type: str = "int8",
        language: str | None = "es",
        beam_size: int = 1,
    ) -> None:
        self._model_size = model_size
        self._device = device
        self._compute_type = compute_type
        self._language = language or None
        self._beam_size = beam_size
        self._model = None
        self._lock = threading.Lock()

    def _ensure_model(self):
        if self._model is not None:
            return self._model
        from faster_whisper import WhisperModel  # import perezoso

        _LOG.info(
            "Cargando faster-whisper model=%s device=%s compute=%s",
            self._model_size,
            self._device,
            self._compute_type,
        )
        self._model = WhisperModel(
            self._model_size,
            device=self._device,
            compute_type=self._compute_type,
        )
        return self._model

    def warmup(self) -> None:
        with self._lock:
            self._ensure_model()

    def transcribe(self, pcm: bytes, sample_rate: int = SAMPLE_RATE) -> Transcript:
        if len(pcm) < 2:
            return Transcript(text="")

        import numpy as np  # dependencia de faster-whisper

        usable = pcm[: len(pcm) - (len(pcm) % 2)]
        audio = np.frombuffer(usable, dtype="<i2").astype("float32") / 32768.0
        duration = _duration_ms(usable, sample_rate)

        with self._lock:
            model = self._ensure_model()
            segments, info = model.transcribe(
                audio,
                language=self._language,
                beam_size=self._beam_size,
                vad_filter=True,
                condition_on_previous_text=False,
            )
            text = " ".join(segment.text.strip() for segment in segments).strip()

        language = getattr(info, "language", None) or self._language
        if text:
            _LOG.info("STT (%.0f ms): %s", duration, text)
        else:
            _LOG.debug("STT sin texto para %d ms de audio", duration)
        return Transcript(text=text, language=language, duration_ms=duration)


def build_transcriber(settings: Settings) -> Transcriber:
    backend = (settings.stt_backend or "auto").strip().lower()
    if backend == "none":
        _LOG.warning("STT desactivado por configuración: modo texto.")
        return NullTranscriber()

    try:
        import faster_whisper  # noqa: F401
    except Exception:  # ImportError o binarios incompatibles
        _LOG.warning(
            "faster-whisper no disponible. Instala con: pip install -e \".[voice]\". "
            "El asistente funcionará solo con comandos de texto."
        )
        return NullTranscriber()

    return FasterWhisperTranscriber(
        settings.stt_model,
        device=settings.stt_device,
        compute_type=settings.stt_compute_type,
        language=settings.stt_language,
    )
