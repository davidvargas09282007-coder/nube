"""Registro de intenciones y *matching* determinista.

Cada intención declara uno o más patrones regulares sobre texto normalizado (minúsculas,
sin acentos, sin signos de apertura). Se elige el patrón que cubre más caracteres, lo que
resuelve de forma predecible los solapamientos entre comandos parecidos.

Ventajas frente a un LLM: latencia < 5 ms, comportamiento auditable y cero alucinaciones.
El punto de extensión para lenguaje natural libre es ``AutomationService.execute``: si no
hay match, se puede delegar en un modelo local sin cambiar el resto del sistema.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from .types import ActionHandler

_TRAILING = re.compile(r"[\s?!.,;:]+$")
_LEADING = re.compile(r"^[¡¿\s]+")
_SPACES = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Minúsculas, sin acentos, espacios colapsados, sin signos de apertura/cierre."""
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    value = _SPACES.sub(" ", stripped.lower()).strip()
    value = _LEADING.sub("", value)
    return _TRAILING.sub("", value)


@dataclass(frozen=True, slots=True)
class Intent:
    name: str
    handler: ActionHandler
    patterns: tuple[re.Pattern[str], ...]
    destructive: bool = False
    description: str = ""
    examples: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class IntentMatch:
    intent: Intent
    args: dict[str, Any]
    matched: str
    confidence: float


class IntentRegistry:
    def __init__(self) -> None:
        self._intents: dict[str, Intent] = {}

    def intent(
        self,
        name: str,
        patterns: Iterable[str],
        *,
        destructive: bool = False,
        description: str = "",
        examples: Iterable[str] = (),
    ) -> Callable[[ActionHandler], ActionHandler]:
        compiled = tuple(re.compile(p, re.IGNORECASE) for p in patterns)
        if not compiled:
            raise ValueError(f"La intención {name} no tiene patrones")

        def decorator(func: ActionHandler) -> ActionHandler:
            if name in self._intents:
                raise ValueError(f"Intención duplicada: {name}")
            self._intents[name] = Intent(
                name=name,
                handler=func,
                patterns=compiled,
                destructive=destructive,
                description=description,
                examples=tuple(examples),
            )
            return func

        return decorator

    # --- consulta --------------------------------------------------------
    def get(self, name: str) -> Intent | None:
        return self._intents.get(name)

    def names(self) -> list[str]:
        return list(self._intents)

    def __len__(self) -> int:
        return len(self._intents)

    def describe(self) -> list[dict[str, Any]]:
        return [
            {
                "name": intent.name,
                "description": intent.description,
                "destructive": intent.destructive,
                "examples": list(intent.examples),
            }
            for intent in self._intents.values()
        ]

    def match(self, text: str) -> IntentMatch | None:
        normalized = normalize(text)
        if not normalized:
            return None

        best: tuple[Intent, dict[str, Any], str] | None = None
        best_score = 0
        for intent in self._intents.values():
            for pattern in intent.patterns:
                found = pattern.search(normalized)
                if not found:
                    continue
                score = len(found.group(0))
                if score > best_score:
                    best_score = score
                    args = {k: v for k, v in found.groupdict().items() if v is not None}
                    best = (intent, args, found.group(0))

        if best is None:
            return None

        intent, args, matched = best
        confidence = round(min(1.0, max(0.5, best_score / max(1, len(normalized)))), 2)
        return IntentMatch(intent=intent, args=args, matched=matched, confidence=confidence)


registry = IntentRegistry()


def build_registry() -> IntentRegistry:
    """Importa los módulos de acciones para que se registren sus decoradores."""
    from . import actions  # noqa: F401  (efecto secundario: registro)

    return registry
