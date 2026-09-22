"""Verify config loader — loads config/verify.yaml."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


@lru_cache(maxsize=1)
def load_verify_config() -> dict[str, Any]:
    path = Path("config/verify.yaml")
    if not path.exists():
        path = Path(__file__).resolve().parents[2] / "config" / "verify.yaml"
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def markers() -> dict[str, list[str]]:
    cfg = load_verify_config()
    return {
        "comparative": cfg.get("comparative_markers_vi", []),
        "causal": cfg.get("causal_markers_vi", []),
    }
