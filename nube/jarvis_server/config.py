"""Configuración del servidor Jarvis.

Todos los valores se pueden fijar por entorno con prefijo ``JARVIS_`` o en ``server/.env``.
Los valores por defecto son deliberadamente conservadores: ``dry_run`` activo y
confirmación obligatoria para acciones destructivas.
"""

from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_BLOCKED_EXTENSIONS = (
    ".exe,.bat,.cmd,.ps1,.psm1,.sh,.dll,.msi,.vbs,.js,.jar,.scr,.com,.reg"
)
DEFAULT_WAKE_PHRASES = "jarvis,oye jarvis,hey jarvis,ok jarvis,hola jarvis"

# pydantic-settings entrega los valores de entorno con la clave del alias
# (``JARVIS_ALLOWED_ROOTS``), mientras que los kwargs de los tests usan el
# nombre interno (``allowed_roots_raw``). El validador de abajo unifica ambos
# para que un kwarg explícito siempre gane, sin importar el orden de las fuentes.
_ALIAS_TO_FIELD = {
    "JARVIS_ALLOWED_ROOTS": "allowed_roots_raw",
    "JARVIS_ALLOWED_ROOTS_RAW": "allowed_roots_raw",
    "JARVIS_BLOCKED_EXTENSIONS": "blocked_extensions_raw",
    "JARVIS_BLOCKED_EXTENSIONS_RAW": "blocked_extensions_raw",
    "JARVIS_APP_ALLOWLIST": "app_allowlist_raw",
    "JARVIS_APP_ALLOWLIST_RAW": "app_allowlist_raw",
    "JARVIS_WAKE_WORD_PHRASES": "wake_word_phrases_raw",
    "JARVIS_WAKE_WORD_PHRASES_RAW": "wake_word_phrases_raw",
    "JARVIS_WOL_TARGETS": "wol_targets_raw",
    "JARVIS_WOL_TARGETS_RAW": "wol_targets_raw",
}


def _split(raw: str) -> list[str]:
    """Acepta listas separadas por coma o punto y coma."""
    return [p.strip() for p in raw.replace(";", ",").split(",") if p.strip()]


def _default_roots() -> list[Path]:
    home = Path.home()
    candidates = (home / "Documents", home / "Downloads", home / "Desktop", home / "Documentos")
    roots = [p.resolve() for p in candidates if p.is_dir()]
    return roots or [home.resolve()]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="JARVIS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
    )

    # --- red y seguridad -------------------------------------------------
    server_name: str = "Jarvis-Desktop"
    host: str = "0.0.0.0"
    port: int = 8765
    auth_token: SecretStr | None = None
    allow_anonymous: bool = False
    tls_certfile: str | None = None
    tls_keyfile: str | None = None

    # --- automatización --------------------------------------------------
    dry_run: bool = True
    require_confirmation: bool = True
    # Los alias aceptan tanto el nombre documentado (JARVIS_ALLOWED_ROOTS) como el
    # histórico con sufijo _RAW. `populate_by_name` mantiene compatibles los kwargs
    # usados por los tests.
    allowed_roots_raw: str = Field(
        default="",
        validation_alias=AliasChoices("JARVIS_ALLOWED_ROOTS", "JARVIS_ALLOWED_ROOTS_RAW"),
    )
    blocked_extensions_raw: str = Field(
        default=DEFAULT_BLOCKED_EXTENSIONS,
        validation_alias=AliasChoices(
            "JARVIS_BLOCKED_EXTENSIONS", "JARVIS_BLOCKED_EXTENSIONS_RAW"
        ),
    )
    max_file_results: int = 20
    app_allowlist_raw: str = Field(
        default="",
        validation_alias=AliasChoices("JARVIS_APP_ALLOWLIST", "JARVIS_APP_ALLOWLIST_RAW"),
    )

    # --- voz -------------------------------------------------------------
    stt_backend: str = "auto"  # auto | faster-whisper | none
    stt_model: str = "small"
    stt_language: str = "es"
    stt_compute_type: str = "int8"
    stt_device: str = "cpu"
    wake_word_enabled: bool = False
    wake_word_phrases_raw: str = Field(
        default=DEFAULT_WAKE_PHRASES,
        validation_alias=AliasChoices("JARVIS_WAKE_WORD_PHRASES", "JARVIS_WAKE_WORD_PHRASES_RAW"),
    )
    wake_word_threshold: float = 0.55
    wake_word_model: str = "hey_jarvis_v0.1"
    energy_gate_rms: float = 0.008

    # --- sesión ----------------------------------------------------------
    max_utterance_seconds: float = 30.0
    utterances_per_minute: int = 20
    notes_dir: str = ""

    # --- red local -------------------------------------------------------
    wol_targets_raw: str = Field(
        default="",
        validation_alias=AliasChoices("JARVIS_WOL_TARGETS", "JARVIS_WOL_TARGETS_RAW"),
    )
    wol_port: int = 9
    wol_broadcast: str = "255.255.255.255"
    wol_repeat: int = 3

    log_level: str = "INFO"

    @model_validator(mode="before")
    @classmethod
    def _canonicalise_alias_keys(cls, values: object) -> object:
        """Traduce los alias de entorno al nombre del campo y respeta los kwargs."""
        if not isinstance(values, dict):
            return values
        data = dict(values)
        for alias, field in _ALIAS_TO_FIELD.items():
            if alias in data:
                value = data.pop(alias)
                data.setdefault(field, value)
        return data

    # --- derivados -------------------------------------------------------
    @property
    def auth_token_plain(self) -> str | None:
        if self.auth_token is None:
            return None
        value = self.auth_token.get_secret_value().strip()
        return value or None

    @property
    def tls_enabled(self) -> bool:
        return bool(self.tls_certfile and self.tls_keyfile)

    @property
    def allowed_roots(self) -> list[Path]:
        raw = _split(self.allowed_roots_raw)
        roots = [Path(p).expanduser().resolve() for p in raw] if raw else _default_roots()
        return roots

    @property
    def blocked_extensions(self) -> frozenset[str]:
        return frozenset(ext.lower() if ext.startswith(".") else f".{ext.lower()}"
                         for ext in _split(self.blocked_extensions_raw))

    @property
    def wake_word_phrases(self) -> tuple[str, ...]:
        return tuple(p.lower() for p in _split(self.wake_word_phrases_raw))

    @property
    def app_allowlist(self) -> dict[str, str]:
        """``"chrome=chrome.exe,notepad=notepad.exe"`` → ``{"chrome": "chrome.exe"}``."""
        table: dict[str, str] = {}
        for entry in _split(self.app_allowlist_raw):
            if "=" not in entry:
                continue
            alias, command = entry.split("=", 1)
            if alias.strip() and command.strip():
                table[alias.strip().lower()] = command.strip()
        return table

    @property
    def wol_target_specs(self) -> list[str]:
        return _split(self.wol_targets_raw)

    @property
    def notes_path(self) -> Path:
        if self.notes_dir:
            return Path(self.notes_dir).expanduser().resolve()
        return (self.allowed_roots[0] / "Jarvis").resolve()

    def summary(self) -> dict[str, object]:
        """Vista segura para ``/v1/info`` (nunca incluye el token)."""
        return {
            "name": self.server_name,
            "platform": sys.platform,
            "tls": self.tls_enabled,
            "dryRun": self.dry_run,
            "requireConfirmation": self.require_confirmation,
            "allowedRoots": [str(p) for p in self.allowed_roots],
            "wakeWord": self.wake_word_enabled,
            "sttBackend": self.stt_backend,
            "wolTargets": [s.split("=", 1)[0] for s in self.wol_target_specs if "=" in s],
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
