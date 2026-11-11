"""Pipeline de una sesión: audio → STT → intención → acción → respuesta."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections import deque
from dataclasses import dataclass
from typing import Any

from fastapi import WebSocket

from . import protocol
from .automation import ActionResult, AutomationService
from .automation.registry import Intent
from .config import Settings
from .voice import ActivationGate, SpeechRenderer, Transcriber, strip_wake_word

_LOG = logging.getLogger("jarvis.session")
SAMPLE_RATE = 16000
MIN_AUDIO_BYTES = int(SAMPLE_RATE * 2 * 0.25)  # 250 ms
CONFIRM_TTL_SECONDS = 120.0


@dataclass(slots=True)
class PendingConfirmation:
    utterance_id: str
    intent: Intent
    args: dict[str, Any]
    created_at: float


def speech_seconds(text: str) -> float:
    """Estimación generosa de duración de la locución (≈16 caracteres/s)."""
    return max(1.2, min(9.0, len(text) / 16.0))


class AssistantSession:
    def __init__(
        self,
        websocket: WebSocket,
        *,
        settings: Settings,
        automation: AutomationService,
        transcriber: Transcriber,
        gate: ActivationGate,
        speech: SpeechRenderer,
        session_id: str,
        device: protocol.DeviceInfo | None = None,
    ) -> None:
        self._ws = websocket
        self._settings = settings
        self._automation = automation
        self._transcriber = transcriber
        self._gate = gate
        self._speech = speech
        self.session_id = session_id
        self.device = device

        self._audio_id: str | None = None
        self._audio = bytearray()
        self._pending: PendingConfirmation | None = None
        self._state = "idle"
        self._tasks: set[asyncio.Task[Any]] = set()
        self._recent: deque[float] = deque()
        self._closed = False

    # ------------------------------------------------------------------ envío
    @property
    def closed(self) -> bool:
        return self._closed

    async def send(self, payload: dict[str, Any]) -> None:
        if self._closed:
            return
        try:
            await self._ws.send_json(payload)
        except Exception:
            self._closed = True

    async def set_state(self, value: str, reason: str = "") -> None:
        if value == self._state and not reason:
            return
        self._state = value
        await self.send(protocol.state(value, reason))  # type: ignore[arg-type]

    async def _error(self, code: str, message: str, *, fatal: bool = False) -> None:
        await self.send(protocol.error(code, message, fatal=fatal))

    def _spawn(self, coro) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def close(self) -> None:
        self._closed = True
        for task in list(self._tasks):
            task.cancel()
        self._tasks.clear()

    # ------------------------------------------------------------------ entrada
    def _rate_ok(self) -> bool:
        now = time.monotonic()
        while self._recent and now - self._recent[0] > 60.0:
            self._recent.popleft()
        if len(self._recent) >= self._settings.utterances_per_minute:
            return False
        self._recent.append(now)
        return True

    def _context(self):
        return self._automation.context(self.session_id)

    async def handle(self, raw: str | bytes) -> None:
        try:
            message = protocol.parse_client_message(raw)
        except protocol.ProtocolError as exc:
            await self._error("bad_request", str(exc))
            return

        if isinstance(message, protocol.TextCommand):
            await self._on_text(message)
        elif isinstance(message, protocol.AudioStart):
            await self._on_audio_start(message)
        elif isinstance(message, protocol.AudioEnd):
            await self._on_audio_end(message)
        elif isinstance(message, protocol.AudioCancel):
            await self._on_audio_cancel(message)
        elif isinstance(message, protocol.Confirm):
            await self._on_confirm(message)
        elif isinstance(message, protocol.WolRequest):
            await self._on_wol(message)
        elif isinstance(message, protocol.Ping):
            await self.send(protocol.event("pong", t=message.t))
        elif isinstance(message, protocol.Hello):
            await self.send(protocol.log("Handshake ya completado."))
        else:
            await self.send(protocol.log(f"Mensaje ignorado: {type(message).__name__}"))

    async def handle_audio(self, data: bytes) -> None:
        if not data:
            return
        if len(data) > protocol.MAX_AUDIO_FRAME_BYTES:
            await self._error("bad_format", "Frame de audio demasiado grande.")
            return
        if self._audio_id is None:
            await self.send(protocol.log("Audio recibido sin audio.start; descartado."))
            return

        self._audio.extend(data)
        max_bytes = int(self._settings.max_utterance_seconds * SAMPLE_RATE * 2)
        if len(self._audio) >= max_bytes:
            _LOG.info("Locución %s alcanzó el máximo; se cierra automáticamente", self._audio_id)
            await self._finish_audio(auto=True)

    async def _on_text(self, message: protocol.TextCommand) -> None:
        if not self._rate_ok():
            await self._error("rate_limited", "Demasiadas peticiones; espera un momento.")
            return
        _LOG.info("[%s] comando de texto: %s", self.session_id, message.text)
        await self._run_command(message.id, message.text)

    async def _on_audio_start(self, message: protocol.AudioStart) -> None:
        if self._audio_id is not None:
            await self._error(
                "bad_request",
                f"Ya hay una locución abierta ({self._audio_id}); envíala o cancélala.",
            )
            return
        if message.format.sampleRate != SAMPLE_RATE or message.format.channels != 1:
            await self._error(
                "bad_format",
                f"Formato no soportado: {message.format.sampleRate} Hz / "
                f"{message.format.channels} canales. Usa pcm_s16le mono 16000 Hz.",
            )
            return
        self._audio_id = message.id
        self._audio = bytearray()
        await self.set_state("listening")

    async def _on_audio_end(self, message: protocol.AudioEnd) -> None:
        if self._audio_id is None:
            await self.send(protocol.log("audio.end sin locución activa."))
            return
        if message.id != self._audio_id:
            await self.send(
                protocol.log(f"audio.end de {message.id!r} no coincide con {self._audio_id!r}; se cierra igual.")
            )
        await self._finish_audio(auto=False)

    async def _on_audio_cancel(self, message: protocol.AudioCancel) -> None:
        if self._audio_id is not None:
            _LOG.info("[%s] locución %s cancelada", self.session_id, self._audio_id)
        self._audio_id = None
        self._audio = bytearray()
        await self.set_state("idle", "cancelled")

    async def _finish_audio(self, *, auto: bool) -> None:
        utterance_id = self._audio_id or "unknown"
        audio = bytes(self._audio)
        self._audio_id = None
        self._audio = bytearray()

        if len(audio) < MIN_AUDIO_BYTES:
            await self.send(protocol.log("Audio demasiado corto; ignorado."))
            await self.set_state("idle")
            return
        if not self._rate_ok():
            await self._error("rate_limited", "Demasiadas locuciones por minuto.")
            await self.set_state("idle")
            return

        self._spawn(self._process_audio(utterance_id, audio))
        if auto:
            await self.send(protocol.log("Locución cerrada automáticamente por duración."))

    # ------------------------------------------------------------------ pipeline
    async def _process_audio(self, utterance_id: str, audio: bytes) -> None:
        await self.set_state("thinking", "stt")
        try:
            activation = await asyncio.to_thread(self._gate.should_activate, audio, SAMPLE_RATE)
            transcript = await asyncio.to_thread(self._transcriber.transcribe, audio, SAMPLE_RATE)
        except Exception:
            _LOG.exception("fallo en el pipeline de voz")
            await self._error("stt_failed", "El motor de voz falló. Revisa el registro del servidor.")
            await self.set_state("idle")
            return

        text = (transcript.text or "").strip()
        await self.send(
            protocol.event(
                "asr.final",
                utteranceId=utterance_id,
                text=text,
                language=transcript.language,
                durationMs=transcript.duration_ms,
                activation=bool(activation),
            )
        )

        requires_wake = getattr(self._gate, "requires_wake_word", False)
        if requires_wake and not activation:
            await self.send(protocol.log("Sin palabra de activación; locución ignorada."))
            await self.set_state("idle")
            return

        if not text:
            await self._error("no_speech", "No he podido entender el audio.")
            await self.set_state("idle")
            return

        cleaned = strip_wake_word(text, self._settings.wake_word_phrases) or text
        _LOG.info("[%s] %s", self.session_id, cleaned)
        await self._run_command(utterance_id, cleaned)

    async def _run_command(self, utterance_id: str, text: str) -> None:
        match = self._automation.registry.match(text)
        if match is None:
            await self.send(
                protocol.event(
                    "intent",
                    utteranceId=utterance_id,
                    name="assistant.unknown",
                    args={},
                    confidence=0.0,
                )
            )
            result = ActionResult.failure(
                "No he entendido ese comando. Di «ayuda» para ver qué puedo hacer."
            )
            await self._deliver(utterance_id, result, action=None)
            return

        await self.send(
            protocol.event(
                "intent",
                utteranceId=utterance_id,
                name=match.intent.name,
                args=match.args,
                confidence=match.confidence,
            )
        )

        if self._automation.needs_confirmation(match.intent):
            prompt = self._automation.confirmation_prompt(match.intent, match.args)
            self._pending = PendingConfirmation(
                utterance_id=utterance_id,
                intent=match.intent,
                args=match.args,
                created_at=time.monotonic(),
            )
            await self.send(
                protocol.event(
                    "confirm.request",
                    utteranceId=utterance_id,
                    name=match.intent.name,
                    prompt=prompt,
                    dryRun=self._automation.policy.dry_run,
                )
            )
            await self.set_state("idle", "awaiting_confirmation")
            return

        result = await self._automation.execute(match.intent, match.args, self._context())
        await self._deliver(utterance_id, result, action=match.intent.name)

    async def _on_confirm(self, message: protocol.Confirm) -> None:
        pending = self._pending
        if pending is None or time.monotonic() - pending.created_at > CONFIRM_TTL_SECONDS:
            self._pending = None
            await self._error("bad_request", "No hay ninguna acción pendiente de confirmar.")
            return
        if message.id != pending.utterance_id:
            await self._error(
                "bad_request",
                f"La confirmación no corresponde a la acción pendiente ({pending.utterance_id}).",
            )
            return

        self._pending = None

        if not message.approved:
            _LOG.info("[%s] confirmación rechazada: %s", self.session_id, pending.intent.name)
            await self.send(
                protocol.reply(
                    pending.utterance_id,
                    "Cancelado.",
                    action=pending.intent.name,
                    ok=False,
                )
            )
            await self.set_state("idle")
            return

        _LOG.info("[%s] confirmación aceptada: %s", self.session_id, pending.intent.name)
        result = await self._automation.execute(pending.intent, pending.args, self._context())
        await self._deliver(pending.utterance_id, result, action=pending.intent.name)

    async def _on_wol(self, message: protocol.WolRequest) -> None:
        try:
            target = await self._automation.wake(message.target)
        except ValueError as exc:
            await self._error("bad_request", str(exc))
            return
        await self.send(
            protocol.reply(
                f"wol-{int(time.time())}",
                f"Señal de encendido enviada a {target.name}.",
                action="wol.wake",
                ok=True,
                data={"target": target.describe()},
            )
        )

    async def _deliver(self, utterance_id: str, result: ActionResult, action: str | None) -> None:
        if result.needs_confirmation:
            await self.send(
                protocol.event(
                    "confirm.request",
                    utteranceId=utterance_id,
                    name=action,
                    prompt=result.prompt or result.speech,
                )
            )
            await self.set_state("idle")
            return

        plan = self._speech.render(result.speech)
        await self.send(
            protocol.reply(
                utterance_id,
                plan.text,
                action=action,
                ok=result.ok,
                data=result.data or None,
            )
        )
        if not result.ok:
            await self.set_state("idle")
            return

        await self.set_state("speaking")
        self._schedule_idle(speech_seconds(plan.text))

    def _schedule_idle(self, delay: float) -> None:
        async def reset() -> None:
            await asyncio.sleep(delay)
            if self._state == "speaking":
                await self.set_state("idle")

        self._spawn(reset())

    def expire_pending(self) -> None:
        self._pending = None


def close_session(session: AssistantSession) -> None:
    with contextlib.suppress(Exception):
        session.close()
