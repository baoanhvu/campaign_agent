"""L2 — Numeric grounding (Proof-Carrying Numbers).

THE most important anti-hallucination layer. Numbers are emitted as tags
{{F1.r1.romi}}; this verifier checks every tag resolves to a real data cell,
and that no bare (ungrounded) numbers appear in the rendered text.
"""
from __future__ import annotations

import re
from typing import Any

from app.contracts import EvidenceSet, CheckResult, Severity

NUM_RE = re.compile(r"""
    (?<![\w.])                      # not preceded by word char or dot
    (?:                             # grouped alternative
      -?\d{1,3}(?:[.\s]\d{3})+      # 1.234.567 or 1 234 567 (vi-VN, ≥1 separator)
      (?:,\d+)?                     # decimal part with comma
      \s*(?:%|tỷ|triệu|nghìn|VND|đ)?  # Vietnamese unit
      | -?\d+(?:[.,]\d+)?%?         # plain number with optional decimal
    )
""", re.VERBOSE)

TAG_RE = re.compile(r"\{\{([^}]+)\}\}")

_UNIT_ALIASES = {
    "tỷ": 1_000_000_000,
    "triệu": 1_000_000,
    "nghìn": 1_000,
    "đ": 1,
}


def extract_evidence_refs(text: str) -> list[str]:
    return [m.group(1).strip() for m in TAG_RE.finditer(text)]


def parse_vi_number(raw: str) -> float | None:
    """Parse a Vietnamese or English format number to float.

    Vietnamese: dot=thousands, comma=decimal  → 392.498.488, 6,20
    English:    comma=thousands, dot=decimal   → 392,498,488, 6.20
    Also handles unit aliases (tỷ, triệu, nghìn) and % sign.
    """
    s = raw.strip().rstrip(",")
    unit_mult = 1.0
    for unit, mult in _UNIT_ALIASES.items():
        if s.endswith(unit):
            s = s[: -len(unit)].strip()
            unit_mult = float(mult)
            break
    s = s.replace("%", "").strip()
    if not s:
        return None
    has_dot = "." in s
    has_comma = "," in s
    if has_dot and has_comma:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif has_comma:
        parts = s.split(",")
        if len(parts) == 2 and len(parts[1]) <= 2:
            s = s.replace(",", ".")
        else:
            s = s.replace(",", "")
    elif has_dot:
        parts = s.split(".")
        if len(parts) > 2:
            s = s.replace(".", "")
    try:
        return float(s) * unit_mult
    except ValueError:
        return None


def find_bare_numbers(text: str) -> list[str]:
    """Find number literals that are NOT inside {{...}} tags."""
    masked = TAG_RE.sub("", text)
    return [m.group(0).strip() for m in NUM_RE.finditer(masked)]


def _is_allowlisted(value: float | None, cfg: dict) -> bool:
    if value is None:
        return True
    if value in (95, 90, 99, 80, 75, 50, 68, 0.95, 0.90, 0.99, 0.80, 0.75, 0.50):
        return True
    allowlist = cfg.get("allowlist", {})
    years = allowlist.get("years", {})
    if years and years.get("min", 2000) <= value <= years.get("max", 2100) and float(value).is_integer():
        return True
    ordinals = allowlist.get("ordinals", {})
    if ordinals and ordinals.get("min", 1) <= value <= ordinals.get("max", 10) and float(value).is_integer():
        return True
    literals = allowlist.get("literals", [0, 1, 2, 100])
    if value in literals:
        return True
    return False


def _matches_policy(value: float, ev: EvidenceSet, cfg: dict) -> bool:
    """Check if a bare number matches any evidence value within policy tolerance."""
    from decimal import Decimal
    policy = cfg.get("policy", {})
    tol = policy.get("vnd", {}).get("tol", 0.005)
    for fact in ev.facts:
        for row in fact.rows:
            for v in row.values():
                if isinstance(v, Decimal):
                    v = float(v)
                if isinstance(v, (int, float)) and v != 0:
                    if abs(value - v) / abs(v) <= tol:
                        return True
                    if abs(value - v) <= 1.0:
                        return True
    return False


def check_numeric_grounding(text: str, ev: EvidenceSet, cfg: dict) -> CheckResult:
    """L2: Verify every number traces to a real data cell."""
    refs = extract_evidence_refs(text)
    unresolved_tags = [ref for ref in refs if ev.resolve(ref) is None]

    rendered_text, _ = ev.substitute(text)
    bare_numbers: list[str] = []
    for raw in find_bare_numbers(rendered_text):
        value = parse_vi_number(raw)
        if _is_allowlisted(value, cfg):
            continue
        if value is not None and _matches_policy(value, ev, cfg):
            continue
        bare_numbers.append(raw)

    passed = not unresolved_tags and not bare_numbers
    total = len(refs) + len(bare_numbers)
    rate = len(refs) / total if total else 1.0
    return CheckResult(
        name="numeric_grounding",
        passed=passed,
        score=rate,
        details={"unresolved_tags": unresolved_tags, "bare_numbers": bare_numbers,
                 "resolved": len(refs) - len(unresolved_tags), "total_refs": len(refs)},
        severity=Severity.BLOCK,
    )
