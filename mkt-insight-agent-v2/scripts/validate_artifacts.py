"""Validate artifacts — check config consistency, prompt versions, metric references."""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

from app.logging_ import setup_logging, get_logger

_log = get_logger("scripts.validate_artifacts")


def main():
    setup_logging("info")
    errors: list[str] = []

    # Check all playbooks reference valid metrics
    from app.semantic.metrics import metric_names
    valid_metrics = metric_names()

    playbook_dir = Path("config/playbooks")
    for pf in sorted(playbook_dir.glob("*.yml")):
        with open(pf, encoding="utf-8") as f:
            pb = yaml.safe_load(f) or {}
        for m in pb.get("metrics", []):
            name = m.get("name", "")
            if name not in valid_metrics:
                errors.append(f"{pf.name}: metric '{name}' not in metrics.yml")

    # Check verify.yaml weights sum to 1.0
    verify_path = Path("config/verify.yaml")
    with open(verify_path, encoding="utf-8") as f:
        verify = yaml.safe_load(f)
    total_w = sum(verify.get("weights", {}).values())
    if abs(total_w - 1.0) > 0.01:
        errors.append(f"verify.yaml: weights sum to {total_w}, expected 1.0")

    # Check all prompts exist
    prompts_dir = Path("prompts")
    expected = ["narrate_campaign", "narrate_persona", "narrate_actions",
                "judge_grounding", "route_intent"]
    for name in expected:
        if not (prompts_dir / f"{name}.yaml").exists():
            errors.append(f"Missing prompt: {name}.yaml")

    if errors:
        for e in errors:
            _log.error("VALIDATION ERROR: %s", e)
        sys.exit(1)
    _log.info("All artifacts valid.")


if __name__ == "__main__":
    main()
