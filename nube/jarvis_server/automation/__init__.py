"""Motor de automatización del asistente."""

from .registry import Intent, IntentMatch, IntentRegistry, build_registry, normalize, registry
from .safety import SafetyError, SafetyPolicy
from .service import AutomationService, build_automation
from .types import ActionContext, ActionResult

__all__ = [
    "ActionContext",
    "ActionResult",
    "AutomationService",
    "Intent",
    "IntentMatch",
    "IntentRegistry",
    "SafetyError",
    "SafetyPolicy",
    "build_automation",
    "build_registry",
    "normalize",
    "registry",
]
