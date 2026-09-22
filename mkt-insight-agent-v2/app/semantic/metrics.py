"""Metric catalog — loads config/semantic/metrics.yml.

53 metrics defined, 42 with reference (ground-truth) values for validation.
Each metric has: name, sql_template (with :bind params), unit, caveat_vi, reference.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

_METRICS: dict[str, dict[str, Any]] = {}


def _load() -> dict[str, dict[str, Any]]:
    global _METRICS
    if _METRICS:
        return _METRICS
    path = Path("config/semantic/metrics.yml")
    if not path.exists():
        path = Path(__file__).resolve().parents[2] / "config" / "semantic" / "metrics.yml"
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    for m in data.get("metrics", []):
        _METRICS[m["name"]] = m
    return _METRICS


def get_metric(name: str) -> dict[str, Any]:
    metrics = _load()
    if name not in metrics:
        from app.errors import UnknownMetricError
        raise UnknownMetricError(f"Unknown metric: {name}")
    return metrics[name]


def all_metrics() -> list[dict[str, Any]]:
    return list(_load().values())


def metrics_with_reference() -> list[dict[str, Any]]:
    return [m for m in all_metrics() if m.get("reference") is not None]


@lru_cache(maxsize=1)
def metric_names() -> frozenset[str]:
    return frozenset(_load().keys())
