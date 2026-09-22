"""Playbook definitions — loaded from config/playbooks/*.yml.

Playbooks map Intent → metric list + narrator prompt + chart config.
This replaces LLM free-form planning, saving 1-2 LLM calls.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from app.contracts import Intent

_INTENT_TO_FILE: dict[Intent, str] = {
    Intent.CAMPAIGN_OVERVIEW: "campaign_overview",
    Intent.CAMPAIGN_DIAGNOSIS: "campaign_diagnosis",
    Intent.FUNNEL_ANALYSIS: "funnel_analysis",
    Intent.CUSTOMER_PERSONA: "customer_persona",
    Intent.SEGMENT_DEEP_DIVE: "segment_deep_dive",
    Intent.CLV_ACTIONS: "clv_actions",
    Intent.RISK_FRAUD: "risk_fraud",
    Intent.DATA_QUESTION: "data_question",
    Intent.FREEFORM: "freeform",
}


@lru_cache(maxsize=16)
def get_playbook(intent: Intent) -> dict[str, Any]:
    name = _INTENT_TO_FILE.get(intent, "freeform")
    path = Path("config/playbooks") / f"{name}.yml"
    if not path.exists():
        path = Path(__file__).resolve().parents[2] / "config" / "playbooks" / f"{name}.yml"
    if not path.exists():
        return {"metrics": [], "narrator_prompt": "narrate_campaign", "charts": []}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def narrator_prompt_name(intent: Intent) -> str:
    return get_playbook(intent).get("narrator_prompt", "narrate_campaign")
