"""Eval runner — runs golden set and reports pass/fail."""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import yaml

from app.logging_ import setup_logging, get_logger

_log = get_logger("evals.run_eval")


async def run_single(question: str, expected_intent: str, traps: list[str]):
    from app.agent.orchestrator import Orchestrator
    orch = Orchestrator.from_env()
    result = orch.answer(question)
    passed = True
    if expected_intent and result.intent.value != expected_intent:
        passed = False
    if result.trust.band.value == "BLOCKED":
        passed = False
    return {"question": question, "passed": passed, "intent": result.intent.value,
            "trust": result.trust.value, "band": result.trust.band.value}


async def run_eval(split: str = "dev", profile: str = "test"):
    setup_logging("info")
    golden_path = Path(__file__).parent / "golden" / "qa_set.yaml"
    with open(golden_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    cases = [c for c in data.get("cases", []) if c.get("split", "dev") == split]
    _log.info("Running %d cases (split=%s)", len(cases), split)

    results = []
    for case in cases:
        r = await run_single(case["question"], case.get("expected_intent", ""), case.get("traps", []))
        results.append(r)
        _log.info("[%s] %s — intent=%s trust=%.3f", "PASS" if r["passed"] else "FAIL", r["question"][:50], r["intent"], r["trust"])

    passed = sum(1 for r in results if r["passed"])
    total = len(results)
    _log.info("Results: %d/%d passed (%.1f%%)", passed, total, 100 * passed / total if total else 0)
    return passed == total


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", default="dev")
    parser.add_argument("--profile", default="test")
    args = parser.parse_args()
    ok = asyncio.run(run_eval(args.split, args.profile))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
