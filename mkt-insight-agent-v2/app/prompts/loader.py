"""Prompt loader — loads YAML prompts from prompts/ dir. Hot-reload + versioning."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from app.logging_ import get_logger

_log = get_logger("prompts.loader")

_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_HOT_RELOAD = True


def _prompts_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "prompts"


def _load(name: str) -> dict[str, Any]:
    path = _prompts_dir() / f"{name}.yaml"
    if not path.exists():
        path = _prompts_dir() / f"{name}.yml"
    if not path.exists():
        from app.errors import PromptError
        raise PromptError(f"Prompt not found: {name}")
    mtime = path.stat().st_mtime
    cached = _CACHE.get(name)
    if cached and not _HOT_RELOAD:
        return cached[1]
    if cached and cached[0] == mtime:
        return cached[1]
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    _CACHE[name] = (mtime, data)
    return data


def render(name: str, variables: dict[str, Any] | None = None) -> str:
    """Load a prompt YAML and render its template with variables."""
    data = _load(name)
    template: str = data.get("template", "")
    version = data.get("version", "1.0.0")
    if variables:
        for key, val in variables.items():
            template = template.replace(f"{{{{{key}}}}}", str(val))
    return template


def get_system_message(name: str) -> str:
    """Get the system message portion of a prompt."""
    data = _load(name)
    return data.get("system", "")


def version(name: str) -> str:
    return _load(name).get("version", "1.0.0")
