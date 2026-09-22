"""Orchestrator — coordinates the full end-to-end agent flow.

ROUTE → RECALL → PLAN → COMPUTE → NARRATE → STREAMING VERIFY → VERIFY → REMEMBER → DONE + JUDGE

Budget: ≤ 2 LLM calls for chat, 0 for dashboard.
"""
from __future__ import annotations

import time
import uuid
from typing import Any, AsyncIterator

from app.contracts import (
    AnswerResult, EvidenceSet, Fact, Intent, PlannedSection,
    TrustScore, Band,
)
from app.agent.router import route
from app.agent.planner import plan
from app.agent.playbooks import narrator_prompt_name
from app.agent.narrator import narrate, narrate_stream
from app.agent.renderer import render
from app.semantic.compiler import compile_metric
from app.data.db import execute_ro
from app.verify.pipeline import run_sync_checks, compute_trust
from app.verify.config import load_verify_config
from app.telemetry.trace import trace_answer
from app.errors import AgentError
from app.logging_ import get_logger

_log = get_logger("agent.orchestrator")


class Orchestrator:
    def __init__(self, llm_client: Any = None, catalog: Any = None):
        self._llm = llm_client
        self._catalog = catalog
        self._cfg = load_verify_config()

    @classmethod
    def from_env(cls) -> "Orchestrator":
        from app.llm.client import get_client
        try:
            llm = get_client()
        except Exception as exc:
            _log.warning("LLM client init failed: %s", exc)
            llm = None
        return cls(llm_client=llm)

    def answer(self, question: str, history: list | None = None,
               user_id: str = "", session_id: str = "") -> AnswerResult:
        """Non-streaming answer for /invocations. Runs async internally."""
        import asyncio
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is None:
            return asyncio.run(self._answer_async(question, history, user_id, session_id))
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, self._answer_async(question, history, user_id, session_id)).result()

    async def _answer_async(self, question: str, history: list | None = None,
                            user_id: str = "", session_id: str = "") -> AnswerResult:
        t0 = time.monotonic()
        trace_id = str(uuid.uuid4())
        llm_calls = 0

        try:
            route_result = route(question)
            if route_result.intent == Intent.OUT_OF_SCOPE:
                return _out_of_scope(question, trace_id, t0)

            sections = plan(route_result.intent, route_result.entities)
            evidence = self._build_evidence(sections, trace_id)

            prompt_name = narrator_prompt_name(route_result.intent)
            if self._llm is None:
                answer_md = _degraded_answer(evidence, sections)
            else:
                answer_md = await narrate(prompt_name, evidence, sections, question, self._llm)
                llm_calls += 1

            from app.agent.streaming import _auto_tag_numbers
            answer_md = _auto_tag_numbers(answer_md, evidence)
            rendered, _ = render(answer_md, evidence)
            checks = run_sync_checks(rendered, evidence, self._catalog, self._cfg)
            trust = compute_trust(checks, self._cfg)

            if trust.band == Band.BLOCKED and self._llm is not None and llm_calls < 2:
                _log.warning("Attempt 1 BLOCKED (reasons=%s), regenerating", trust.reasons)
                answer_md = await narrate(prompt_name, evidence, sections, question, self._llm)
                llm_calls += 1
                answer_md = _auto_tag_numbers(answer_md, evidence)
                rendered, _ = render(answer_md, evidence)
                checks = run_sync_checks(rendered, evidence, self._catalog, self._cfg)
                trust = compute_trust(checks, self._cfg)

            if trust.band == Band.BLOCKED:
                _log.warning("Attempt 2 still BLOCKED (reasons=%s), falling back to ABSTAIN", trust.reasons)
                rendered = _degraded_answer(evidence, sections)
                trust = TrustScore(
                    value=0.0, band=Band.ABSTAIN,
                    reasons=["max_regen_exceeded"] + trust.reasons,
                    components=trust.components,
                )

            latency = int((time.monotonic() - t0) * 1000)
            trace_answer(trace_id, question, route_result.intent, trust, llm_calls, latency)

            return AnswerResult(
                answer_markdown=rendered, evidence=evidence, trust=trust,
                trace_id=trace_id, intent=route_result.intent,
                latency_ms=latency, llm_calls=llm_calls,
                decision="ANSWERED" if trust.band != Band.ABSTAIN else "ABSTAINED",
            )
        except AgentError:
            raise
        except Exception as exc:
            _log.error("Orchestrator failed: %s", exc)
            raise AgentError(f"Agent error: {exc}") from exc

    async def answer_stream(self, question: str, history: list | None = None,
                            user_id: str = "", session_id: str = ""
                            ) -> AsyncIterator[dict[str, Any]]:
        """Streaming answer for /api/chat SSE."""
        t0 = time.monotonic()
        trace_id = str(uuid.uuid4())
        llm_calls = 0

        route_result = route(question)
        if route_result.intent == Intent.OUT_OF_SCOPE:
            yield {"event": "done", "data": {"trace_id": trace_id, "decision": "OUT_OF_SCOPE"}}
            return

        yield {"event": "stage", "data": {"stage": "routing", "label": "Đang xác định loại phân tích", "progress": 0.1}}

        sections = plan(route_result.intent, route_result.entities)
        yield {"event": "plan", "data": {"metrics": [m.metric for s in sections for m in s.metrics],
                                          "filters": route_result.entities}}

        yield {"event": "stage", "data": {"stage": "computing", "label": "Đang truy vấn dữ liệu", "progress": 0.3}}
        evidence = self._build_evidence(sections, trace_id)

        for f in evidence.facts:
            yield {"event": "table", "data": {"fact_id": f.fact_id, "columns": f.columns,
                                               "rows": f.rows[:50], "sql": f.sql}}

        yield {"event": "evidence", "data": {"facts": [f.fact_id for f in evidence.facts],
                                              "data_version": evidence.data_version,
                                              "tag_map": _build_tag_map(evidence)}}

        if self._llm is None:
            yield {"event": "warning", "data": {"level": "warn", "code": "DEGRADED_MODE",
                                                   "message": "Mô hình tạm không phản hồi — hiển thị số liệu dạng rút gọn"}}
            answer_md = _degraded_answer(evidence, sections)
            yield {"event": "block", "data": {"seq": 1, "md": answer_md, "verified": True,
                                                "numbers": {"ok": 0, "total": 0}}}
        else:
            prompt_name = narrator_prompt_name(route_result.intent)
            from app.agent.streaming import _auto_tag_numbers

            yield {"event": "stage", "data": {"stage": "narrating", "label": "Đang viết phân tích", "progress": 0.5}}

            full_text = ""
            async for token in narrate_stream(prompt_name, evidence, sections, question, self._llm):
                full_text += token
                yield {"event": "token", "data": {"text": token}}
            llm_calls += 1

            full_text = _auto_tag_numbers(full_text, evidence)
            rendered, _ = render(full_text, evidence)
            yield {"event": "rendered", "data": {"text": rendered}}
            yield {"event": "stage", "data": {"stage": "verifying", "label": "Đang đối chiếu số liệu", "progress": 0.8}}
            checks = run_sync_checks(rendered, evidence, self._catalog, self._cfg)
            trust = compute_trust(checks, self._cfg)

            if trust.band == Band.BLOCKED:
                trust = TrustScore(
                    value=max(trust.value, 0.5), band=Band.HEDGE,
                    reasons=trust.reasons, components=trust.components,
                )

            yield {"event": "verified", "data": {"trust": trust.value, "band": trust.band.value,
                                                  "checks": {k: {"passed": v.passed, "score": v.score}
                                                             for k, v in checks.items()}}}

            decision = "ANSWERED" if trust.band != Band.ABSTAIN else "ABSTAINED"
            latency = int((time.monotonic() - t0) * 1000)
            yield {"event": "done", "data": {"trace_id": trace_id, "decision": decision,
                                              "latency_ms": latency, "llm_calls": llm_calls}}

            if trust.band != Band.ABSTAIN:
                yield {"event": "stage", "data": {"stage": "judging", "label": "Đang kiểm tra lại bằng mô hình", "progress": 0.9}}
                judge_result = await self._run_judge(rendered, evidence)
                if judge_result:
                    yield {"event": "judge", "data": judge_result}
                    llm_calls += 1

            trace_answer(trace_id, question, route_result.intent, trust, llm_calls, latency)
            return

        rendered, _ = render(_degraded_answer(evidence, sections), evidence)
        checks = run_sync_checks(rendered, evidence, self._catalog, self._cfg)
        trust = compute_trust(checks, self._cfg)
        latency = int((time.monotonic() - t0) * 1000)
        yield {"event": "verified", "data": {"trust": trust.value, "band": trust.band.value,
                                              "checks": {k: {"passed": v.passed, "score": v.score}
                                                         for k, v in checks.items()}}}
        yield {"event": "done", "data": {"trace_id": trace_id, "decision": "ANSWERED",
                                          "latency_ms": latency, "llm_calls": 0}}
        trace_answer(trace_id, question, route_result.intent, trust, 0, latency)

    def _build_evidence(self, sections: list[PlannedSection], trace_id: str) -> EvidenceSet:
        """COMPUTE: MetricRequest → SQL → DB → Fact → EvidenceSet. Skip failed metrics."""
        facts: list[Fact] = []
        for i, section in enumerate(sections):
            for j, req in enumerate(section.metrics):
                fact_id = f"F{len(facts) + 1}"
                try:
                    sql, params = compile_metric(req)
                    columns, rows = execute_ro(sql, params)
                    metric_def = _get_metric_def(req.metric)
                    caveats = metric_def.get("caveat_vi", []) if metric_def else []
                    if isinstance(caveats, str):
                        caveats = [caveats]
                    facts.append(Fact(
                        fact_id=fact_id, columns=columns, rows=rows, sql=sql,
                        metric=req.metric, caveats=caveats,
                    ))
                except Exception as exc:
                    _log.warning("Metric %s skipped: %s", req.metric, exc)
        return EvidenceSet(facts=facts, data_version="1.0.0")

    async def _run_judge(self, answer: str, evidence: EvidenceSet) -> dict[str, Any] | None:
        if self._llm is None:
            return None
        try:
            from app.verify.judge import run_judge
            from app.prompts.loader import render
            class _PL:
                def render(self, name, vars): return render(name, vars)
            result = await run_judge(answer, evidence, self._llm, _PL(), self._cfg)
            return {"entailment_rate": result.details.get("entailment_rate", 1.0),
                    "contradiction_rate": result.details.get("contradiction_rate", 0.0),
                    "trust": result.score}
        except Exception as exc:
            _log.warning("Judge failed: %s", exc)
            return None


def _get_metric_def(name: str) -> dict[str, Any] | None:
    try:
        from app.semantic.metrics import get_metric
        return get_metric(name)
    except Exception:
        return None


def _degraded_answer(evidence: EvidenceSet, sections: list[PlannedSection]) -> str:
    """Fallback when LLM unavailable — template-based answer from evidence."""
    lines: list[str] = []
    for f in evidence.facts:
        lines.append(f"### {f.fact_id} — {f.metric or ''}")
        if f.rows:
            header = " | ".join(f.columns)
            sep = " | ".join("---" for _ in f.columns)
            lines.append(f"| {header} |")
            lines.append(f"| {sep} |")
            for row in f.rows[:10]:
                lines.append("| " + " | ".join(str(row.get(c, "—")) for c in f.columns) + " |")
        lines.append("")
    return "\n".join(lines)


def _out_of_scope(question: str, trace_id: str, t0: float) -> AnswerResult:
    latency = int((time.monotonic() - t0) * 1000)
    return AnswerResult(
        answer_markdown="Câu hỏi ngoài phạm vi. Tôi chỉ trả lời về chiến dịch marketing, khách hàng và khoản vay.",
        evidence=EvidenceSet(), trust=TrustScore(value=1.0, band=Band.ABSTAIN, reasons=["out_of_scope"]),
        trace_id=trace_id, intent=Intent.OUT_OF_SCOPE, latency_ms=latency, llm_calls=0,
        decision="OUT_OF_SCOPE",
    )


def _build_tag_map(ev: EvidenceSet) -> dict[str, str]:
    """Build flat {tag: formatted_value} map for frontend substitution."""
    from app.contracts import _format_value
    tag_map: dict[str, str] = {}
    for fact in ev.facts:
        for row_idx, row in enumerate(fact.rows):
            for col in fact.columns:
                val = row.get(col)
                if val is None:
                    continue
                tag = f"{fact.fact_id}.r{row_idx + 1}.{col}"
                tag_map[tag] = _format_value(val)
    return tag_map
