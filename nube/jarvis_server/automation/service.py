"""Ejecutor de automatizaciones: intención → política → handler."""

from __future__ import annotations

import logging
from typing import Any

from ..config import Settings
from ..network.wol import WakeOnLanService
from .registry import Intent, IntentRegistry, build_registry
from .safety import SafetyError, SafetyPolicy
from .types import ActionContext, ActionResult

_LOG = logging.getLogger("jarvis.automation")

_CONFIRM_LABELS = {
    "system.shutdown": "apagar el equipo",
    "system.restart": "reiniciar el equipo",
    "files.delete": "borrar",
}


class AutomationService:
    def __init__(
        self,
        settings: Settings,
        registry: IntentRegistry,
        policy: SafetyPolicy,
        wol: WakeOnLanService,
    ) -> None:
        self._settings = settings
        self._registry = registry
        self._policy = policy
        self._wol = wol

    @property
    def policy(self) -> SafetyPolicy:
        return self._policy

    @property
    def registry(self) -> IntentRegistry:
        return self._registry

    def describe(self) -> dict[str, Any]:
        return {
            "intents": self._registry.describe(),
            "policy": self._policy.describe(),
            "wolTargets": self._wol.names,
        }

    def wol_names(self) -> list[str]:
        return self._wol.names

    async def wake(self, name: str | None = None):
        """Enciende un objetivo WoL configurado (no pasa por ``dry_run``)."""
        return await self._wol.wake_async(name)

    def context(self, session_id: str = "") -> ActionContext:
        return ActionContext(
            settings=self._settings,
            policy=self._policy,
            wol=self._wol,
            session_id=session_id,
        )

    def needs_confirmation(self, intent: Intent) -> bool:
        return intent.destructive and self._policy.require_confirmation

    def confirmation_prompt(self, intent: Intent, args: dict[str, Any]) -> str:
        label = _CONFIRM_LABELS.get(intent.name, intent.description or intent.name)
        target = args.get("path") or args.get("target") or ""
        suffix = f" «{target}»" if target else ""
        when = " (modo simulación)" if self._policy.dry_run else ""
        return f"¿Confirmas que quieres {label}{suffix}?{when}"

    async def execute(
        self,
        intent: Intent,
        args: dict[str, Any],
        ctx: ActionContext,
    ) -> ActionResult:
        _LOG.info(
            "acción=%s args=%s dry_run=%s session=%s",
            intent.name,
            args,
            self._policy.dry_run,
            ctx.session_id or "-",
        )
        try:
            result = await intent.handler(ctx, args)
        except SafetyError as exc:
            _LOG.warning("bloqueada %s: %s", intent.name, exc)
            return ActionResult.failure(str(exc))
        except Exception:
            _LOG.exception("fallo ejecutando %s", intent.name)
            return ActionResult.failure("No he podido completar la acción. Revisa el registro del servidor.")

        _LOG.info("resultado=%s ok=%s", intent.name, result.ok)
        return result


def build_automation(settings: Settings) -> AutomationService:
    policy = SafetyPolicy.from_settings(settings)
    wol = WakeOnLanService.from_specs(
        settings.wol_target_specs,
        default_broadcast=settings.wol_broadcast,
        default_port=settings.wol_port,
        repeat=settings.wol_repeat,
    )
    return AutomationService(
        settings=settings,
        registry=build_registry(),
        policy=policy,
        wol=wol,
    )
