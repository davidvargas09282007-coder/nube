"""Política de seguridad para acciones sobre el sistema de archivos.

Regla de oro: *ningún handler toca una ruta que no haya pasado por ``resolve()``*, y toda
ruta resuelta debe estar dentro de una raíz permitida. La resolución canónica elimina ``..``
y symlinks, de modo que no se puede escapar del perímetro con trucos de ruta.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from ..config import Settings

_LOG = logging.getLogger("jarvis.safety")


class SafetyError(PermissionError):
    """Ruta o acción bloqueada por política."""


@dataclass(frozen=True, slots=True)
class SafetyPolicy:
    allowed_roots: tuple[Path, ...]
    blocked_extensions: frozenset[str]
    dry_run: bool = True
    require_confirmation: bool = True

    @classmethod
    def from_settings(cls, settings: Settings) -> SafetyPolicy:
        roots = tuple(settings.allowed_roots)
        _LOG.info("Raíces permitidas: %s", ", ".join(str(r) for r in roots))
        if settings.dry_run:
            _LOG.warning("Modo simulación activo: las acciones no tendrán efecto real.")
        return cls(
            allowed_roots=roots,
            blocked_extensions=settings.blocked_extensions,
            dry_run=settings.dry_run,
            require_confirmation=settings.require_confirmation,
        )

    # --- rutas -----------------------------------------------------------
    def is_within_allowed(self, path: Path) -> bool:
        try:
            resolved = path.resolve()
        except OSError:
            return False
        return any(self._is_inside(resolved, root) for root in self.allowed_roots)

    @staticmethod
    def _is_inside(candidate: Path, root: Path) -> bool:
        try:
            candidate.relative_to(root)
        except ValueError:
            return False
        return True

    def resolve(self, raw: str | Path, *, must_exist: bool = False) -> Path:
        """Normaliza y valida. Relativas se interpretan desde la primera raíz permitida."""
        candidate = Path(str(raw)).expanduser()
        if not candidate.is_absolute():
            candidate = self.allowed_roots[0] / candidate
        resolved = candidate.resolve()
        if not self.is_within_allowed(resolved):
            raise SafetyError(
                f"«{resolved.name}» está fuera de las carpetas permitidas. "
                f"Permitidas: {', '.join(r.name for r in self.allowed_roots)}."
            )
        if must_exist and not resolved.exists():
            raise SafetyError(f"No existe «{resolved.name}».")
        return resolved

    def assert_openable(self, path: Path) -> None:
        if path.suffix.lower() in self.blocked_extensions:
            raise SafetyError(f"Por seguridad no abro archivos «{path.suffix}».")


    def needs_confirmation(self) -> bool:
        return self.require_confirmation

    def describe(self) -> dict[str, object]:
        return {
            "dryRun": self.dry_run,
            "requireConfirmation": self.require_confirmation,
            "allowedRoots": [str(r) for r in self.allowed_roots],
            "blockedExtensions": sorted(self.blocked_extensions),
        }
