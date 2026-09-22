"""Trace — records ops.agent_trace for every answer.

Three mandatory columns: prompt_version, model_name, profile.
"""
from __future__ import annotations

from typing import Any

from app.contracts import Intent, TrustScore
from app.logging_ import get_logger

_log = get_logger("telemetry.trace")


def trace_answer(trace_id: str, question: str, intent: Intent,
                 trust: TrustScore, llm_calls: int, latency_ms: int) -> None:
    """Write a trace record to ops.agent_trace."""
    from app.settings import get_settings
    s = get_settings()

    checks_data = {
        name: {"passed": c.passed, "score": c.score}
        for name, c in trust.components.items()
    }
    block_reason = ", ".join(trust.reasons) if trust.reasons else None

    try:
        from app.data.db import execute_trace
        execute_trace(
            """INSERT INTO ops.agent_trace
               (trace_id, question, intent, decision, trust_score,
                checks, block_reason, prompt_version, model_name, profile,
                llm_calls, latency_ms, created_at)
               VALUES (CAST(:trace_id AS uuid), :question, :intent, :decision, :trust_score,
                CAST(:checks AS jsonb), :block_reason, :prompt_version, :model_name, :profile,
                :llm_calls, :latency_ms, NOW())""",
            {
                "trace_id": trace_id,
                "question": question[:500],
                "intent": intent.value,
                "decision": "ANSWERED" if trust.band.value != "BLOCKED" else "BLOCKED",
                "trust_score": trust.value,
                "checks": str(checks_data),
                "block_reason": block_reason,
                "prompt_version": _safe_prompt_version(),
                "model_name": s.llm.model,
                "profile": s.profile,
                "llm_calls": llm_calls,
                "latency_ms": latency_ms,
            },
        )
    except Exception as exc:
        _log.debug("Trace write skipped: %s", exc)

    _log.info("trace_id=%s intent=%s band=%s trust=%.3f llm=%d latency=%dms",
              trace_id, intent.value, trust.band.value, trust.value, llm_calls, latency_ms)


def _safe_prompt_version() -> str:
    try:
        from app.prompts.loader import version as prompt_version
        return prompt_version("narrate_campaign")
    except Exception:
        return "unknown"


def get_trace(trace_id: str) -> dict[str, Any] | None:
    """Retrieve a trace record by ID."""
    try:
        from app.data.db import execute_ro
        _, rows = execute_ro(
            "SELECT * FROM ops.agent_trace WHERE trace_id = CAST(:tid AS uuid) LIMIT 1",
            {"tid": trace_id},
        )
        return rows[0] if rows else None
    except Exception as exc:
        _log.warning("Trace read failed: %s", exc)
        return None
