"""Streaming verifier — verifies markdown blocks as they stream.

Gathers tokens into complete markdown blocks, cuts at safe boundaries,
never cuts inside {{...}} tags. Repairs tags, substitutes, checks L2+L3
per block, then emits BlockEvent (verified=true/false).
"""
from __future__ import annotations

import re
from typing import Any, Iterator

from app.contracts import EvidenceSet, BlockEvent
from app.verify.numeric import check_numeric_grounding, parse_vi_number
from app.verify.entity import check_entity_grounding
from app.verify.config import load_verify_config

FLUSH_ON = ("\n\n", "\n### ", "\n## ", "\n# ", "\n- ", "\n* ", "\n1. ")

_REPAIR_RE = re.compile(r"\{\{(F\d+)_(\d+)(\.[^}]+)\}\}")
_BARE_NUM_RE = re.compile(
    r"(?<![\w{}])"
    r"(-?\d{1,3}(?:[.,]\d{3})+(?:[.,]\d{1,2})?|-?\d+(?:[.,]\d+)?)"
    r"(?![\w}])"
)

_PCT_ALLOWLIST = frozenset({95, 90, 99, 80, 75})


def _build_evidence_index(ev: EvidenceSet) -> list[tuple[float, str]]:
    """Build (value, tag) pairs from all evidence facts."""
    pairs: list[tuple[float, str]] = []
    for fact in ev.facts:
        for row_idx, row in enumerate(fact.rows):
            for col in fact.columns:
                val = row.get(col)
                if val is None:
                    continue
                try:
                    num = float(val)
                    tag = f"{{{{{fact.fact_id}.r{row_idx + 1}.{col}}}}}"
                    pairs.append((num, tag))
                except (ValueError, TypeError):
                    pass
    return pairs


def _auto_tag_numbers(text: str, ev: EvidenceSet, tol: float = 0.02) -> str:
    """Replace bare numbers in text with {{fact_id}} tags from evidence.

    Scans for numbers, matches against evidence values within tolerance,
    and replaces with the corresponding tag. Skips numbers inside {{...}}.

    Disambiguation: if multiple evidence values are within tolerance,
    skip auto-tagging rather than risk mis-tagging (false confidence).
    """
    pairs = _build_evidence_index(ev)
    if not pairs:
        return text

    masked = re.sub(r"\{\{[^}]+\}\}", "", text)

    def _replace(m: re.Match) -> str:
        raw = m.group(1)
        val = parse_vi_number(raw)
        if val is None:
            return m.group(0)

        if val in (0, 1, 2, 100) or (2000 <= val <= 2100):
            return m.group(0)
        if val in _PCT_ALLOWLIST:
            return m.group(0)

        candidates: list[tuple[float, str]] = []
        for ev_val, tag in pairs:
            if ev_val == 0:
                continue
            diff = abs(val - ev_val) / max(abs(ev_val), 1.0)
            if diff < tol:
                candidates.append((diff, tag))

        if not candidates:
            return m.group(0)
        if len(candidates) == 1:
            return candidates[0][1]
        candidates.sort()
        if candidates[0][0] < candidates[1][0] * 0.5:
            return candidates[0][1]
        return m.group(0)

    result = _BARE_NUM_RE.sub(_replace, text)
    return result


def _repair_tags(text: str, ev: EvidenceSet) -> str:
    """Repair hallucinated fact_ids like {{F2_1.r1.romi}} → {{F2.r1.romi}}."""
    def _try_repair(m: re.Match) -> str:
        original = m.group(1) + "_" + m.group(2) + m.group(3)
        repaired = m.group(1) + m.group(3)
        if ev.resolve(original) is not None:
            return m.group(0)
        if ev.resolve(repaired) is not None:
            return "{{" + repaired + "}}"
        return m.group(0)
    return _REPAIR_RE.sub(_try_repair, text)


class StreamingVerifier:
    """Gom token → khối markdown → thay thẻ → kiểm chứng → phát ra."""

    def __init__(self, evidence: EvidenceSet, catalog: Any = None,
                 max_block_chars: int = 600):
        self.evidence = evidence
        self.catalog = catalog
        self.max_block_chars = max_block_chars
        self._buf = ""
        self._seq = 0
        self._cfg = load_verify_config()
        self._numeric_cfg = self._cfg.get("numeric", {})

    def feed(self, token: str) -> Iterator[BlockEvent]:
        self._buf += token
        while (cut := self._find_safe_cut()) is not None:
            yield self._emit(self._buf[:cut])
            self._buf = self._buf[cut:]

    def finish(self) -> Iterator[BlockEvent]:
        if self._buf.strip():
            yield self._emit(self._buf)
        self._buf = ""

    def _find_safe_cut(self) -> int | None:
        if self._has_open_tag():
            open_at = self._buf.rfind("{{")
            region = self._buf[:open_at]
        else:
            region = self._buf
        best = -1
        for m in FLUSH_ON:
            pos = region.find(m)
            if pos >= 0:
                cut = pos + len(m)
                if best < 0 or cut < best:
                    best = cut
        if best > 0:
            return best
        if len(region) > self.max_block_chars:
            space = region.rfind(" ", 0, self.max_block_chars)
            return space if space > 0 else None
        return None

    def _has_open_tag(self) -> bool:
        o, c = self._buf.rfind("{{"), self._buf.rfind("}}")
        return o > c

    def _emit(self, raw: str) -> BlockEvent:
        tagged = _auto_tag_numbers(raw, self.evidence)
        repaired = _repair_tags(tagged, self.evidence)
        md, unresolved = self.evidence.substitute(repaired)
        num = check_numeric_grounding(md, self.evidence, self._numeric_cfg)
        ent = check_entity_grounding(md, self.evidence, self.catalog, self._cfg)
        ok = not unresolved and num.passed and ent.passed
        self._seq += 1
        reason = None
        if not ok:
            if unresolved:
                reason = f"Thẻ chưa phân giải: {unresolved[:3]}"
            elif not num.passed:
                reason = "Số chưa đối chiếu"
            elif not ent.passed:
                reason = "Thực thể không có trong dữ liệu"
        return BlockEvent(
            seq=self._seq,
            md=md if ok else None,
            md_raw=md,
            verified=ok,
            reason=reason,
            numbers={"ok": num.details.get("resolved", 0),
                     "total": num.details.get("total_refs", 0)},
        )
