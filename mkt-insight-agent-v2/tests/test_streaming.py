"""Test streaming verifier — block cutting and tag safety."""
import pytest
from app.contracts import EvidenceSet, Fact
from app.agent.streaming import StreamingVerifier


@pytest.fixture
def evidence():
    return EvidenceSet(facts=[
        Fact(fact_id="F1", columns=["romi"], rows=[{"romi": 1.31}], sql="SELECT ..."),
    ])


def test_never_cut_inside_tag(evidence):
    sv = StreamingVerifier(evidence)
    blocks = list(sv.feed("ROMI là {{F1.r1.romi}}\n\nKết thúc."))
    blocks.append(list(sv.finish()))
    for b in blocks:
        if b and hasattr(b[0] if isinstance(b, list) else b, 'md_raw'):
            block = b[0] if isinstance(b, list) else b
            assert "{{" not in (block.md or "")


def test_block_emitted_on_double_newline(evidence):
    sv = StreamingVerifier(evidence)
    blocks = list(sv.feed("Phần 1\n\nPhần 2\n\n"))
    assert len(blocks) >= 2


def test_unresolved_tag_blocks(evidence):
    sv = StreamingVerifier(evidence)
    blocks = list(sv.feed("Số là {{F99.r1.romi}}\n\n"))
    for b in blocks:
        assert not b.verified
