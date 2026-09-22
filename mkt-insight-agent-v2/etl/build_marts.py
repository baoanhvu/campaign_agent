"""Build data marts: raw.* → mart.*"""
from __future__ import annotations

import sys
from pathlib import Path

from app.logging_ import setup_logging, get_logger

_log = get_logger("etl.build_marts")


def main():
    setup_logging("info")
    from app.data.db import execute_admin

    ddl_path = Path(__file__).parent / "sql" / "marts.sql"
    if not ddl_path.exists():
        _log.error("Marts SQL not found: %s", ddl_path)
        sys.exit(1)

    sql = ddl_path.read_text(encoding="utf-8")
    statements = [s.strip() for s in sql.split(";") if s.strip()]
    for stmt in statements:
        try:
            execute_admin(stmt)
            _log.info("Executed: %s...", stmt[:60])
        except Exception as exc:
            _log.warning("Statement failed: %s", exc)
    _log.info("Marts build complete.")


if __name__ == "__main__":
    main()
