"""L6 — Trust Score computation + final decision.

Combines L0–L5 results into a TrustScore with band: PASS/HEDGE/ABSTAIN/BLOCKED.
"""
from __future__ import annotations

from typing import Any

from app.contracts import CheckResult, TrustScore, Band, Severity, EvidenceSet
from app.verify.config import load_verify_config


def compute_trust(checks: dict[str, CheckResult], cfg: dict | None = None) -> TrustScore:
    """L6: Aggregate all check results into a TrustScore."""
    if cfg is None:
        cfg = load_verify_config()
    w = cfg.get("weights", {})
    t = cfg.get("thresholds", {})
    total_w = sum(w.values()) or 1.0

    hard_fail = [c for c in checks.values()
                 if c.severity == Severity.BLOCK and not c.passed]
    if hard_fail:
        return TrustScore(
            value=0.0,
            band=Band.BLOCKED,
            reasons=[c.name for c in hard_fail],
            components=checks,
        )

    def _score(name: str, default: float = 1.0) -> float:
        c = checks.get(name)
        return c.score if c else default

    value = (
        w.get("schema", 0.15) * _score("sql_validation")
        + w.get("numeric", 0.25) * _score("numeric_grounding")
        + w.get("entity", 0.10) * _score("entity_grounding")
        + w.get("stats", 0.20) * _score("stats_guard")
        + w.get("judge", 0.20) * _score("judge")
        + w.get("consistency", 0.10) * _score("self_consistency")
    ) / total_w

    t_high = t.get("t_high", 0.85)
    t_low = t.get("t_low", 0.60)

    if value >= t_high:
        band = Band.PASS
    elif value >= t_low:
        band = Band.HEDGE
    else:
        band = Band.ABSTAIN

    reasons: list[str] = []
    for name, c in checks.items():
        if not c.passed and c.severity == Severity.WARN:
            reasons.append(name)

    return TrustScore(value=value, band=band, reasons=reasons, components=checks)


def run_sync_checks(text: str, evidence: EvidenceSet, catalog: Any,
                    cfg: dict | None = None) -> dict[str, CheckResult]:
    """Run all deterministic (non-LLM) checks: L0(skip), L2, L3, L4, consistency(skip).

    L0 sql_validation and self_consistency are added as skipped checks so their
    weights are transparently represented in the trust score. They become active
    when freeform SQL or multi-sample consistency is available.
    """
    from app.verify.numeric import check_numeric_grounding
    from app.verify.entity import check_entity_grounding
    from app.verify.stats_guard import check_stats_guard

    if cfg is None:
        cfg = load_verify_config()
    numeric_cfg = cfg.get("numeric", {})

    checks: dict[str, CheckResult] = {}
    checks["sql_validation"] = CheckResult(
        name="sql_validation", passed=True, score=1.0,
        details={"skipped": "template_sql_bypass"}, severity=Severity.INFO,
    )
    checks["numeric_grounding"] = check_numeric_grounding(text, evidence, numeric_cfg)
    checks["entity_grounding"] = check_entity_grounding(text, evidence, catalog, cfg)
    checks["stats_guard"] = check_stats_guard(text, evidence, cfg)
    checks["self_consistency"] = CheckResult(
        name="self_consistency", passed=True, score=1.0,
        details={"skipped": "single_sample"}, severity=Severity.INFO,
    )
    return checks
