# ruff: noqa: I001  -- el orden de importación es intencional (prioridad de registro)
"""Handlers de automatización.

Importar este paquete registra todas las intenciones en el registro global. El orden de
importación importa en caso de empate de longitud de patrón: primero los comandos más
específicos (archivos), luego los generales (sistema).
"""

from . import files, media, wol, system

__all__ = ["files", "media", "system", "wol"]
