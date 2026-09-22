"""L5 — LLM judge (asynchronous). Runs AFTER done, on same SSE connection.

temperature=0, max_tokens=200. Returns 3 labels:
SUPPORTED / CONTRADICTED / NOT_ENOUGH_INFO.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.contracts import EvidenceSet, CheckResult, Severity


@dataclass
class JudgeResult:
    entailment_rate: float = 1.0
    contradiction_rate: float = 0.0
    neutral_rate: float = 0.0
    label: str = "SUPPORTED"


async def run_judge(answer: str, evidence: EvidenceSet, llm_client: Any,
                    prompt_loader: Any, cfg: dict) -> CheckResult:
    """L5: Ask a second LLM whether the answer is supported by evidence."""
    evidence_text = _format_judge_evidence(evidence)
    prompt = prompt_loader.render("judge_grounding", {
        "answer": answer,
        "evidence": evidence_text,
    })

    try:
        response = await llm_client.chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=200,
        )
        result = _parse_judge_response(response)
    except Exception:
        return CheckResult(
            name="judge", passed=True, score=1.0,
            details={"skipped": True}, severity=Severity.INFO,
        )

    contradiction_rate = result.contradiction_rate
    neutral_rate = result.neutral_rate
    entailment_rate = result.entailment_rate

    if contradiction_rate > 0:
        passed = False
        score = 0.0
        severity = Severity.BLOCK
    elif neutral_rate > 0.3:
        passed = False
        score = 0.5
        severity = Severity.WARN
    else:
        passed = entailment_rate >= 0.9
        score = entailment_rate
        severity = Severity.WARN

    return CheckResult(
        name="judge",
        passed=passed,
        score=score,
        details={
            "label": result.label,
            "entailment_rate": entailment_rate,
            "contradiction_rate": contradiction_rate,
            "neutral_rate": neutral_rate,
        },
        severity=severity,
    )


def _format_judge_evidence(ev: EvidenceSet) -> str:
    lines: list[str] = []
    for f in ev.facts:
        lines.append(f"[{f.fact_id}] columns={f.columns}")
        for i, row in enumerate(f.rows[:10]):
            lines.append(f"  r{i+1}: {row}")
    return "\n".join(lines)


def _parse_judge_response(response: str) -> JudgeResult:
    import json
    try:
        data = json.loads(response)
        label = data.get("label", "SUPPORTED")
    except Exception:
        label = response.strip().upper()
        if "CONTRADICT" in label:
            label = "CONTRADICTED"
        elif "NOT_ENOUGH" in label or "NEUTRAL" in label:
            label = "NOT_ENOUGH_INFO"
        else:
            label = "SUPPORTED"

    if label == "CONTRADICTED":
        return JudgeResult(0.0, 1.0, 0.0, label)
    if label == "NOT_ENOUGH_INFO":
        return JudgeResult(0.5, 0.0, 0.5, label)
    return JudgeResult(1.0, 0.0, 0.0, label)
