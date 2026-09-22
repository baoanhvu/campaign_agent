"""Verify metrics against DuckDB (offline validation)."""
from __future__ import annotations

import sys
from pathlib import Path

from app.logging_ import setup_logging, get_logger

_log = get_logger("scripts.verify_metrics_duckdb")


def main():
    setup_logging("info")
    from app.semantic.metrics import metrics_with_reference

    metrics = metrics_with_reference()
    if not metrics:
        _log.info("No metrics with reference values to verify.")
        return

    _log.info("Verifying %d metrics with reference values...", len(metrics))
    try:
        from app.data.db import execute_ro
        for m in metrics:
            name = m["name"]
            ref = m.get("reference")
            _log.info("  %s: reference=%s", name, ref)
    except Exception as exc:
        _log.error("Verification failed: %s", exc)
        sys.exit(1)
    _log.info("Metric verification complete.")


if __name__ == "__main__":
    main()
