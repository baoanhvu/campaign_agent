"""Core type definitions and protocols for the Marketing Insight Agent.

Design principle: LLM never computes a number. Every number comes from SQL.
Numbers are emitted as tags {{F1.r1.romi}} and resolved against EvidenceSet.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol


class Severity(str, Enum):
    BLOCK = "BLOCK"
    WARN = "WARN"
    INFO = "INFO"


class Band(str, Enum):
    PASS = "PASS"
    HEDGE = "HEDGE"
    ABSTAIN = "ABSTAIN"
    BLOCKED = "BLOCKED"


class Intent(str, Enum):
    CAMPAIGN_OVERVIEW = "campaign_overview"
    CAMPAIGN_DIAGNOSIS = "campaign_diagnosis"
    FUNNEL_ANALYSIS = "funnel_analysis"
    CUSTOMER_PERSONA = "customer_persona"
    SEGMENT_DEEP_DIVE = "segment_deep_dive"
    CLV_ACTIONS = "clv_actions"
    RISK_FRAUD = "risk_fraud"
    DATA_QUESTION = "data_question"
    FREEFORM = "freeform"
    OUT_OF_SCOPE = "out_of_scope"


@dataclass(frozen=True)
class MetricRequest:
    metric: str
    filters: dict[str, Any] = field(default_factory=dict)
    alias: str | None = None


@dataclass
class Fact:
    fact_id: str
    columns: list[str]
    rows: list[dict[str, Any]]
    sql: str
    metric: str | None = None
    caveats: list[str] = field(default_factory=list)

    def resolve(self, ref: str) -> Any:
        """Resolve a reference like 'F1.r1.romi' or 'F1.romi' to a cell value."""
        parts = ref.split(".")
        if parts[0] != self.fact_id:
            return None
        rest = parts[1:]
        row_idx: int | None = None
        col: str | None = None
        if len(rest) == 2:
            r = rest[0]
            if r.startswith("r") and r[1:].isdigit():
                row_idx = int(r[1:]) - 1
            col = rest[1]
        elif len(rest) == 1:
            col = rest[0]
        if col is None or col not in self.columns:
            return None
        if row_idx is not None:
            if 0 <= row_idx < len(self.rows):
                return self.rows[row_idx].get(col)
            return None
        if len(self.rows) == 1:
            return self.rows[0].get(col)
        return [r.get(col) for r in self.rows]

@dataclass
class Comparison:
    name: str
    left: float
    right: float
    significant: bool = False
    p_value: float | None = None
    effect_size: float | None = None
    method: str | None = None


@dataclass
class EvidenceSet:
    facts: list[Fact] = field(default_factory=list)
    comparisons: list[Comparison] = field(default_factory=list)
    actions: list[dict[str, Any]] = field(default_factory=list)
    data_version: str = ""

    def by_id(self, fact_id: str) -> Fact | None:
        for f in self.facts:
            if f.fact_id == fact_id:
                return f
        return None

    def resolve(self, ref: str) -> Any:
        fid = ref.split(".")[0]
        f = self.by_id(fid)
        return f.resolve(ref) if f else None

    def substitute(self, text: str) -> tuple[str, list[str]]:
        """Replace {{ref}} tags with formatted values. Returns (text, unresolved)."""
        import re
        unresolved: list[str] = []
        pattern = re.compile(r"\{\{([^}]+)\}\}")

        def _repl(m: re.Match) -> str:
            ref = m.group(1).strip()
            val = self.resolve(ref)
            if val is None:
                unresolved.append(ref)
                return "—"
            return _format_value(val)

        return pattern.sub(_repl, text), unresolved

    def all_string_values(self) -> set[str]:
        vals: set[str] = set()
        for f in self.facts:
            for r in f.rows:
                for v in r.values():
                    if isinstance(v, str):
                        vals.add(v)
        return vals

    def all_caveats(self) -> list[str]:
        out: list[str] = []
        for f in self.facts:
            out.extend(f.caveats)
        return out


def _format_value(v: Any) -> str:
    if v is None:
        return "—"
    from decimal import Decimal
    if isinstance(v, Decimal):
        v = float(v)
    if isinstance(v, float):
        if v == int(v):
            return f"{int(v):,}"
        return f"{v:,.2f}"
    if isinstance(v, int):
        return f"{v:,}"
    return str(v)


@dataclass
class CheckResult:
    name: str
    passed: bool
    score: float
    details: dict[str, Any] = field(default_factory=dict)
    severity: Severity = Severity.WARN


@dataclass
class TrustScore:
    value: float
    band: Band
    reasons: list[str] = field(default_factory=list)
    components: dict[str, CheckResult] = field(default_factory=dict)


@dataclass
class PlannedSection:
    title: str
    metrics: list[MetricRequest]
    narrator_prompt: str = "narrate_campaign"
    charts: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class RouteResult:
    intent: Intent
    entities: dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0


@dataclass
class AnswerResult:
    answer_markdown: str
    evidence: EvidenceSet
    trust: TrustScore
    trace_id: str
    intent: Intent
    latency_ms: int
    llm_calls: int
    decision: str = "ANSWERED"

    def to_invocation_response(self) -> dict[str, Any]:
        return {
            "answer_markdown": self.answer_markdown,
            "evidence": {
                "facts": [
                    {"fact_id": f.fact_id, "columns": f.columns, "rows": f.rows, "sql": f.sql}
                    for f in self.evidence.facts
                ],
                "data_version": self.evidence.data_version,
            },
            "trust": {"value": self.trust.value, "band": self.trust.band.value,
                      "reasons": self.trust.reasons},
            "trace_id": self.trace_id,
            "intent": self.intent.value,
            "latency_ms": self.latency_ms,
            "llm_calls": self.llm_calls,
            "decision": self.decision,
        }


class BlockEvent:
    __slots__ = ("seq", "md", "md_raw", "verified", "reason", "numbers")

    def __init__(self, seq: int, md: str | None, md_raw: str, verified: bool,
                 reason: str | None = None, numbers: dict[str, int] | None = None):
        self.seq = seq
        self.md = md
        self.md_raw = md_raw
        self.verified = verified
        self.reason = reason
        self.numbers = numbers or {"ok": 0, "total": 0}


class Verifier(Protocol):
    def check(self, text: str, evidence: EvidenceSet, cfg: Any) -> CheckResult: ...
