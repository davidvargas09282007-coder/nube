"""Procesamiento de voz local."""

from .stt import (
    SAMPLE_RATE,
    FasterWhisperTranscriber,
    NullTranscriber,
    Transcriber,
    Transcript,
    build_transcriber,
)
from .tts import ClientSpeechRenderer, SpeechPlan, SpeechRenderer, build_speech_renderer, clean_for_speech
from .wakeword import (
    ActivationGate,
    AlwaysOnGate,
    EnergyGate,
    OpenWakeWordGate,
    build_gate,
    contains_wake_word,
    rms_level,
    strip_wake_word,
)

__all__ = [
    "SAMPLE_RATE",
    "ActivationGate",
    "AlwaysOnGate",
    "ClientSpeechRenderer",
    "EnergyGate",
    "FasterWhisperTranscriber",
    "NullTranscriber",
    "OpenWakeWordGate",
    "SpeechPlan",
    "SpeechRenderer",
    "Transcriber",
    "Transcript",
    "build_gate",
    "build_speech_renderer",
    "build_transcriber",
    "clean_for_speech",
    "contains_wake_word",
    "rms_level",
    "strip_wake_word",
]
