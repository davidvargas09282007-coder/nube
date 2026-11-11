"""Acciones sobre archivos, siempre dentro del perímetro de ``SafetyPolicy``."""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from ..registry import registry
from ..safety import SafetyError
from ..types import ActionContext, ActionResult

_LOG = logging.getLogger("jarvis.actions.files")

_IS_WINDOWS = sys.platform.startswith("win")
_IS_MAC = sys.platform == "darwin"
_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "AppData", "$RECYCLE.BIN"}


def _open_path(path: Path) -> None:
    if _IS_WINDOWS:
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif _IS_MAC:
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


def _search(roots: tuple[Path, ...], needle: str, limit: int, blocked: frozenset[str], max_depth: int = 6) -> list[Path]:
    results: list[Path] = []
    lowered = needle.lower()
    for root in roots:
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            current = Path(dirpath)
            try:
                depth = len(current.relative_to(root).parts)
            except ValueError:
                continue
            if depth >= max_depth:
                dirnames[:] = []
            dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in _SKIP_DIRS]
            for filename in filenames:
                if lowered not in filename.lower():
                    continue
                candidate = current / filename
                if candidate.suffix.lower() in blocked:
                    continue
                results.append(candidate)
                if len(results) >= limit:
                    return results
    return results


@registry.intent(
    "files.search",
    patterns=[
        r"^(?:busca|buscar|encuentra|encontrar|find|search)\s+"
        r"(?:archivos?\s+|ficheros?\s+|el\s+archivo\s+|un\s+archivo\s+)?"
        r"(?:que\s+contenga\s+|llamad[oa]\s+|que\s+se\s+llame\s+)?"
        r"(?P<query>[a-z0-9][a-z0-9 ._-]{1,60})$"
    ],
    description="Busca archivos por nombre en las carpetas permitidas",
    examples=["busca informe", "busca archivos que contenga factura"],
)
async def search_files(ctx: ActionContext, args: dict[str, Any]) -> ActionResult:
    query = " ".join((args.get("query") or "").split()).strip()
    if not query:
        return ActionResult.failure("¿Qué nombre quieres que busque?")

    found = await asyncio.to_thread(
        _search,
        tuple(ctx.policy.allowed_roots),
        query,
        ctx.settings.max_file_results,
        ctx.policy.blocked_extensions,
    )
    if not found:
        return ActionResult.failure(f"No he encontrado archivos con «{query}».")

    first = found[0]
    speech = f"He encontrado {len(found)} coincidencias. La primera es {first.name}."
    return ActionResult.success(speech, query=query, files=[str(p) for p in found])


@registry.intent(
    "files.list",
    patterns=[
        r"^(?:lista|listar|muestra|muestrame|list)\s+(?:los\s+|las\s+)?(?:archivos|ficheros|contenido)"
        r"(?:\s+(?:de|en|del)\s+(?P<path>.+))?$",
        r"^(?:que\s+hay\s+en)\s+(?P<path>.+)$",
    ],
    description="Lista el contenido de una carpeta permitida",
    examples=["lista archivos de Descargas"],
)
async def list_files(ctx: ActionContext, args: dict[str, Any]) -> ActionResult:
    raw = args.get("path") or str(ctx.policy.allowed_roots[0])
    try:
        folder = ctx.policy.resolve(raw, must_exist=True)
    except SafetyError as exc:
        return ActionResult.failure(str(exc))
    if not folder.is_dir():
        return ActionResult.failure("Eso no es una carpeta.")

    entries = await asyncio.to_thread(lambda: sorted(folder.iterdir(), key=lambda p: p.name.lower()))
    names = [entry.name for entry in entries[:20]]
    if not names:
        return ActionResult.success(f"«{folder.name}» está vacía.", path=str(folder), entries=[])
    return ActionResult.success(
        f"«{folder.name}» tiene {len(entries)} elementos. Los primeros: {', '.join(names[:5])}.",
        path=str(folder),
        entries=names,
    )


@registry.intent(
    "files.open",
    patterns=[
        r"^(?:abre|abrir|open)\s+(?:el\s+|la\s+)?"
        r"(?:archivo|fichero|documento|carpeta|directorio)\s+(?P<path>.+)$"
    ],
    description="Abre un archivo o carpeta permitidos",
    examples=["abre el archivo notas.txt", "abre la carpeta Documentos"],
)
async def open_file(ctx: ActionContext, args: dict[str, Any]) -> ActionResult:
    try:
        target = ctx.policy.resolve(args.get("path", ""), must_exist=True)
        ctx.policy.assert_openable(target)
    except SafetyError as exc:
        return ActionResult.failure(str(exc))

    if ctx.policy.dry_run:
        return ActionResult.success(f"(simulación) Abriría {target.name}.", path=str(target), dryRun=True)
    try:
        await asyncio.to_thread(_open_path, target)
    except Exception:
        _LOG.exception("fallo abriendo %s", target)
        return ActionResult.failure(f"No he podido abrir {target.name}.")
    return ActionResult.success(f"Abriendo {target.name}.", path=str(target))


@registry.intent(
    "files.recent",
    patterns=[
        r"^(?:que\s+)?(?:archivos|ficheros|documentos)\s+(?:he\s+)?"
        r"(?:modificado|cambiado|tocado|recientes?)(?:\s+hoy|\s+recientemente)?$",
        r"^(?:muestra|dime)\s+(?:los\s+)?(?:archivos\s+)?recientes$",
    ],
    description="Muestra los archivos modificados en las últimas 24 h",
    examples=["qué archivos he modificado hoy"],
)
async def recent_files(ctx: ActionContext, args: dict[str, Any]) -> ActionResult:
    cutoff = datetime.now() - timedelta(hours=24)

    def collect() -> list[Path]:
        recent: list[Path] = []
        for root in ctx.policy.allowed_roots:
            for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
                dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in _SKIP_DIRS]
                for filename in filenames:
                    candidate = Path(dirpath) / filename
                    if candidate.suffix.lower() in ctx.policy.blocked_extensions:
                        continue
                    try:
                        if datetime.fromtimestamp(candidate.stat().st_mtime) >= cutoff:
                            recent.append(candidate)
                    except OSError:
                        continue
        recent.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return recent[:10]

    recent = await asyncio.to_thread(collect)
    if not recent:
        return ActionResult.success("No hay archivos modificados en las últimas 24 horas.", files=[])
    names = ", ".join(p.name for p in recent[:5])
    return ActionResult.success(
        f"Has tocado {len(recent)} archivos recientemente: {names}.",
        files=[str(p) for p in recent],
    )


@registry.intent(
    "files.create_folder",
    patterns=[
        r"^(?:crea|crear|create)\s+(?:una\s+|la\s+)?(?:carpeta|directorio|folder)\s+"
        r"(?:llamada\s+|con\s+nombre\s+)?(?P<path>.+)$"
    ],
    description="Crea una carpeta dentro del perímetro",
    examples=["crea una carpeta llamada Proyectos"],
)
async def create_folder(ctx: ActionContext, args: dict[str, Any]) -> ActionResult:
    try:
        folder = ctx.policy.resolve(args.get("path", ""))
    except SafetyError as exc:
        return ActionResult.failure(str(exc))
    if folder.exists():
        return ActionResult.failure(f"«{folder.name}» ya existe.")
    if ctx.policy.dry_run:
        return ActionResult.success(f"(simulación) Crearía la carpeta {folder.name}.", path=str(folder), dryRun=True)
    try:
        await asyncio.to_thread(folder.mkdir, parents=True)
    except OSError as exc:
        _LOG.warning("mkdir falló: %s", exc)
        return ActionResult.failure("No he podido crear la carpeta.")
    return ActionResult.success(f"Carpeta {folder.name} creada.", path=str(folder))


@registry.intent(
    "files.note",
    patterns=[
        r"^(?:toma\s+nota|apunta|anota|recuerda|note)[\s:]+(?P<text>.+)$"
    ],
    description="Añade una nota a la libreta de Jarvis",
    examples=["toma nota: comprar cables HDMI"],
)
async def write_note(ctx: ActionContext, args: dict[str, Any]) -> ActionResult:
    content = (args.get("text") or "").strip()
    if len(content) < 2:
        return ActionResult.failure("La nota está vacía.")

    notes_dir = ctx.settings.notes_path
    note_file = notes_dir / "notas.md"
    if ctx.policy.dry_run:
        return ActionResult.success("(simulación) Habría guardado la nota.", path=str(note_file), dryRun=True)

    def append() -> None:
        notes_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        with note_file.open("a", encoding="utf-8") as handle:
            handle.write(f"- [{stamp}] {content}\n")

    try:
        await asyncio.to_thread(append)
    except OSError:
        _LOG.exception("no se pudo escribir la nota")
        return ActionResult.failure("No he podido guardar la nota.")
    return ActionResult.success("Nota guardada.", path=str(note_file))


@registry.intent(
    "files.delete",
    patterns=[
        r"^(?:borra|borrar|elimina|eliminar|delete|rm)\s+(?:el\s+|la\s+)?"
        r"(?:archivo|fichero|documento|carpeta|directorio)?\s*(?P<path>[a-z0-9][a-z0-9 ._/\\-]{1,120})$"
    ],
    destructive=True,
    description="Borra un archivo o carpeta vacía (requiere confirmación)",
    examples=["borra el archivo viejo.txt"],
)
async def delete_path(ctx: ActionContext, args: dict[str, Any]) -> ActionResult:
    try:
        target = ctx.policy.resolve(args.get("path", ""), must_exist=True)
    except SafetyError as exc:
        return ActionResult.failure(str(exc))

    protected = {root for root in ctx.policy.allowed_roots}
    if target in protected:
        return ActionResult.failure("No puedo borrar una carpeta raíz permitida.")
    if target.is_dir() and any(target.iterdir()):
        return ActionResult.failure("La carpeta no está vacía; bórrala manualmente por seguridad.")

    label = "carpeta" if target.is_dir() else "archivo"
    if ctx.policy.dry_run:
        return ActionResult.success(
            f"(simulación) Borraría el {label} {target.name}.", path=str(target), dryRun=True
        )
    try:
        await asyncio.to_thread(target.rmdir if target.is_dir() else target.unlink)
    except OSError:
        _LOG.exception("no se pudo borrar %s", target)
        return ActionResult.failure(f"No he podido borrar el {label}.")
    return ActionResult.success(f"{label.capitalize()} {target.name} borrado.", path=str(target))
