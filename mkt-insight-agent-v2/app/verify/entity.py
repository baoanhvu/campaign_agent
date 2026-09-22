"""L3 — Entity grounding. Detects fabricated names of campaigns/channels/segments."""
from __future__ import annotations

from typing import Any

from app.contracts import EvidenceSet, CheckResult, Severity
from app.verify.vi_text import extract_proper_nouns_vi


def check_entity_grounding(text: str, ev: EvidenceSet, catalog: Any, cfg: dict) -> CheckResult:
    """L3: every proper noun in the text must exist in evidence or catalog."""
    known = ev.all_string_values()
    if hasattr(catalog, "all_dimension_values"):
        known = known | catalog.all_dimension_values()
    elif isinstance(catalog, set):
        known = known | catalog

    mentioned = extract_proper_nouns_vi(text)
    threshold = 0.92
    unknown: list[str] = []
    for m in mentioned:
        if not _is_known(m, known, threshold):
            unknown.append(m)

    missing_caveats = _check_caveats(text, ev)

    passed = not unknown
    score = 1 - len(unknown) / max(len(mentioned), 1)
    details: dict[str, Any] = {"unknown_entities": unknown}
    if missing_caveats:
        details["missing_caveats"] = missing_caveats
    return CheckResult(
        name="entity_grounding",
        passed=passed,
        score=score,
        details=details,
        severity=Severity.WARN,
    )


def _is_known(value: str, known: set[str], threshold: float) -> bool:
    if value in known:
        return True
    for k in known:
        if value in k or k in value:
            return True
    from difflib import get_close_matches
    matches = get_close_matches(value, list(known), n=1, cutoff=threshold)
    return len(matches) > 0


def _check_caveats(text: str, ev: EvidenceSet) -> list[str]:
    """If evidence has caveats that the text doesn't mention, flag them."""
    missing: list[str] = []
    for caveat in ev.all_caveats():
        key_word = caveat.split("—")[0].split(",")[0].strip()[:20]
        if key_word and key_word.lower() not in text.lower():
            missing.append(caveat)
    return missing
