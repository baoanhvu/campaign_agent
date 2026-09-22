"""Renderer — replaces {{fact_id}} tags with formatted numbers (vi-VN)."""
from __future__ import annotations

from app.contracts import EvidenceSet


def render(text: str, evidence: EvidenceSet) -> tuple[str, list[str]]:
    """Substitute all {{ref}} tags with formatted values. Returns (text, unresolved)."""
    return evidence.substitute(text)
