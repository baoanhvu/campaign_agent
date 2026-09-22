"""Narrator — EvidenceSet → prompt → LLM stream tokens.

LLM only writes WORDS, never NUMBERS. Numbers emitted as tags: {{F1.r1.romi}}.
Inserts fact_id list reminder BEFORE evidence in user message.
"""
from __future__ import annotations

from typing import Any, AsyncIterator

from app.contracts import EvidenceSet, PlannedSection
from app.prompts.loader import get_system_message, render
from app.logging_ import get_logger

_log = get_logger("agent.narrator")


def build_messages(prompt_name: str, evidence: EvidenceSet,
                   sections: list[PlannedSection], question: str) -> list[dict[str, str]]:
    """Build the chat messages with system + user (reminder + evidence + question)."""
    system = get_system_message(prompt_name)
    fact_ids = [f.fact_id for f in evidence.facts]
    entity_names = sorted(evidence.all_string_values())[:20]

    tag_list = _build_tag_list(evidence)
    reminder = _build_reminder(fact_ids, entity_names, tag_list)
    evidence_text = _format_evidence(evidence)
    section_titles = "\n".join(f"- {s.title}" for s in sections if s.title)

    user = f"""{reminder}

EVIDENCE (dữ liệu thật, dùng thẻ {{fact_id.row.col}} để tham chiếu):
{evidence_text}

CÂU HỎI: {question}

{"CẤU TRÚC trả lời (theo từng phần):" if section_titles else ""}
{section_titles}

VIẾT CÂU TRẢ LỜI:"""

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _build_tag_list(ev: EvidenceSet) -> str:
    """List all available tags explicitly."""
    lines: list[str] = []
    for fact in ev.facts:
        for row_idx, row in enumerate(fact.rows):
            for col in fact.columns:
                val = row.get(col)
                if val is not None and not isinstance(val, str):
                    lines.append(f"  {{{{{fact.fact_id}.r{row_idx + 1}.{col}}}}}")
    return "\n".join(lines[:60])


def _build_reminder(fact_ids: list[str], entity_names: list[str], tag_list: str = "") -> str:
    ids_str = ", ".join(fact_ids) if fact_ids else "(không có)"
    entities_str = ", ".join(entity_names) if entity_names else "(không có)"
    tags_section = f"\n\nDANH SÁCH THẺ PHÉP DÙNG (copy chính xác, không đổi tên cột):\n{tag_list}" if tag_list else ""
    return f"""DANH SÁCH fact_id PHÉP DÙNG (chỉ những cái này, không thêm số thứ tự):
  {ids_str}
{tags_section}

TUYỆT ĐỐI KHÔNG:
  - Viết chữ số trực tiếp (sai: 'ROMI 6,20' | đúng: 'ROMI {{{{F1.r1.romi}}}}')
  - Dùng fact_id không có trong danh sách (sai: 'F2_1' | đúng: 'F2')
  - Đổi tên cột (sai: 'F3.r1.neg_ratio' | đúng: 'F7.r1.negative_share')
  - Ghép thêm hậu tố (sai: 'F1b', 'F2_1' | đúng: 'F1', 'F2')
  - Đặt tên thực thể khác EVIDENCE (sai: 'Zalo ZNS' | đúng: tên nguyên văn)
  - Nhắc đến "Fact", "F1", "F2", fact ID, hay tên kỹ thuật trong câu trả lời
    (sai: 'Dựa trên Fact F6' | đúng: 'Dữ liệu cho thấy')

NGUYÊN TẮC THỐNG KÊ:
  - Có thể so sánh "A cao hơn/thấp hơn B" dựa trên số liệu. Dùng "có vẻ" nếu không có significant.
  - Có thể suy luận nhân quả khi có logic kinh doanh. Tránh khẳng định tuyệt đối.
  - Nếu phân phối lệch, nên kèm trung vị. Không bắt buộc mọi lúc.
  - Được phép diễn giải, đánh giá, đề xuất — đây là phân tích kinh doanh.

Tên thực thể có trong dữ liệu (phải dùng nguyên văn):
  {entities_str}"""


def _format_evidence(ev: EvidenceSet) -> str:
    lines: list[str] = []
    for f in ev.facts:
        lines.append(f"\n[{f.fact_id}] (metric={f.metric or '?'})")
        lines.append(f"  columns: {f.columns}")
        for i, row in enumerate(f.rows[:15]):
            lines.append(f"  r{i+1}: {row}")
        if len(f.rows) > 15:
            lines.append(f"  ... ({len(f.rows)} rows total)")
        if f.caveats:
            for c in f.caveats:
                lines.append(f"  caveat: {c}")
    for c in ev.comparisons:
        lines.append(f"\n[comparison] {c.name}: {c.left} vs {c.right} "
                     f"significant={c.significant} p={c.p_value}")
    return "\n".join(lines)


async def narrate_stream(prompt_name: str, evidence: EvidenceSet,
                         sections: list[PlannedSection], question: str,
                         llm_client: Any) -> AsyncIterator[str]:
    """Stream LLM tokens for the narrative."""
    messages = build_messages(prompt_name, evidence, sections, question)
    async for token in llm_client.stream(messages, temperature=0.0, max_tokens=2048):
        yield token


async def narrate(prompt_name: str, evidence: EvidenceSet,
                  sections: list[PlannedSection], question: str,
                  llm_client: Any) -> str:
    """Non-streaming narrative (for /invocations)."""
    messages = build_messages(prompt_name, evidence, sections, question)
    return await llm_client.chat(messages, temperature=0.0, max_tokens=2048)
