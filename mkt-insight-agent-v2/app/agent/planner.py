"""Planner — Playbook + entities → PlannedSection[].

Each section → MetricRequest (metric + filter). Metric list is FIXED in YAML,
NOT chosen by LLM (saves 1-2 LLM calls, R1).
"""
from __future__ import annotations

from typing import Any

from app.contracts import Intent, MetricRequest, PlannedSection
from app.agent.playbooks import get_playbook


def plan(intent: Intent, entities: dict[str, Any]) -> list[PlannedSection]:
    """Turn an intent + extracted entities into planned sections with metric requests."""
    playbook = get_playbook(intent)
    sections_cfg = playbook.get("sections", [])
    if not sections_cfg:
        metrics_cfg = playbook.get("metrics", [])
        return [PlannedSection(
            title=playbook.get("title", "Phân tích"),
            metrics=[_to_metric_request(m, entities) for m in metrics_cfg],
            narrator_prompt=playbook.get("narrator_prompt", "narrate_campaign"),
            charts=playbook.get("charts", []),
        )]

    sections: list[PlannedSection] = []
    for sec in sections_cfg:
        metrics = [_to_metric_request(m, entities) for m in sec.get("metrics", [])]
        sections.append(PlannedSection(
            title=sec.get("title", ""),
            metrics=metrics,
            narrator_prompt=sec.get("narrator_prompt", playbook.get("narrator_prompt", "narrate_campaign")),
            charts=sec.get("charts", []),
        ))
    return sections


def _to_metric_request(metric_cfg: dict[str, Any], entities: dict[str, Any]) -> MetricRequest:
    filters: dict[str, Any] = {}
    for key, val in metric_cfg.get("filters", {}).items():
        filters[key] = val
    for key, val in entities.items():
        if key == "campaign_name" and isinstance(val, list) and val:
            filters["campaign_name"] = val[0]
        elif key == "dates" and isinstance(val, list) and val:
            pass
    return MetricRequest(
        metric=metric_cfg["name"],
        filters=filters,
        alias=metric_cfg.get("alias"),
    )
