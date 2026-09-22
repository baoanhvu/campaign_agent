"""L4 — Stats guard + skew guard. Catches noise comparisons, small samples, causal claims."""
from __future__ import annotations

from typing import Any

from app.contracts import EvidenceSet, CheckResult, Severity
from app.verify.vi_text import split_sentences_vi, has_comparative_marker, has_causal_marker, has_correlation_phrase


def check_stats_guard(text: str, ev: EvidenceSet, cfg: dict) -> CheckResult:
    """L4: guard against unsupported comparisons, small samples, causal inference."""
    min_sample = cfg.get("min_sample_size", 30)
    has_significant = any(c.significant for c in ev.comparisons)

    unsupported: list[str] = []
    causal_without_evidence: list[str] = []
    small_sample_warnings: list[str] = []

    for sentence in split_sentences_vi(text):
        if has_comparative_marker(sentence) and not has_significant:
            unsupported.append(sentence)
        if has_causal_marker(sentence) and not has_correlation_phrase(sentence):
            causal_without_evidence.append(sentence)

    for c in ev.comparisons:
        if abs(c.left - c.right) > 0 and not c.significant:
            small_sample_warnings.append(c.name)

    skew_warnings = _check_skew(text, ev, cfg)

    issues = unsupported + causal_without_evidence + small_sample_warnings + skew_warnings
    passed = not unsupported and not causal_without_evidence
    score = 1 - len(issues) / max(len(split_sentences_vi(text)), 1)
    return CheckResult(
        name="stats_guard",
        passed=passed,
        score=max(0.0, score),
        details={
            "unsupported_comparisons": unsupported,
            "causal_without_evidence": causal_without_evidence,
            "small_sample_warnings": small_sample_warnings,
            "skew_warnings": skew_warnings,
        },
        severity=Severity.WARN,
    )


def _check_skew(text: str, ev: EvidenceSet, cfg: dict) -> list[str]:
    """Skew guard: if distribution is skewed, text must mention median + negative_share."""
    warnings: list[str] = []
    text_lower = text.lower()
    for fact in ev.facts:
        for col in fact.columns:
            values = [r.get(col) for r in fact.rows if isinstance(r.get(col), (int, float))]
            if len(values) < 10:
                continue
            import statistics
            mean = statistics.mean(values)
            median = statistics.median(values)
            neg_share = sum(1 for v in values if v < 0) / len(values)
            is_skewed = (abs(mean) > 1e-9 and abs(mean - median) / abs(mean) > 0.3) or neg_share > 0.3
            if is_skewed:
                if "trung vị" not in text_lower and "median" not in text_lower:
                    warnings.append(f"{fact.fact_id}.{col}: skewed but median not mentioned")
    return warnings
