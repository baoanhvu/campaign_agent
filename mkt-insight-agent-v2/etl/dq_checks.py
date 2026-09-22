"""Data quality checks — 12 invariants. Writes results to ops.dq_results."""
from __future__ import annotations

import sys

from app.logging_ import setup_logging, get_logger

_log = get_logger("etl.dq_checks")

CHECKS = [
    ("DQ-01", "Tổng hồ sơ = 2687", "SELECT CASE WHEN COUNT(*) = 2687 THEN 'PASS' ELSE 'FAIL' END FROM raw.fact_loan"),
    ("DQ-02", "Hồ sơ bị từ chối = 1062", "SELECT CASE WHEN COUNT(*) FILTER (WHERE status='REJECTED') = 1062 THEN 'PASS' ELSE 'FAIL' END FROM raw.fact_loan"),
    ("DQ-03", "Không có dữ liệu ngoài tháng 8/2026", "SELECT CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END FROM raw.fact_loan WHERE date < '2026-08-01' OR date > '2026-08-31'"),
    ("DQ-04", "fact_loan không có campaign_id", "SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='raw' AND table_name='fact_loan' AND column_name='campaign_id') THEN 'PASS' ELSE 'FAIL' END"),
    ("DQ-05", "Mọi status trong enum", "SELECT CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END FROM raw.fact_loan WHERE status NOT IN ('PENDING','APPROVED','REJECTED','DISBURSED')"),
    ("DQ-06", "loan_amount >= 0 khi không NULL", "SELECT CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END FROM raw.fact_loan WHERE loan_amount < 0"),
    ("DQ-07", "tenure > 0 khi không NULL", "SELECT CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END FROM raw.fact_loan WHERE tenure <= 0"),
    ("DQ-08", "rate >= 0 khi không NULL", "SELECT CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END FROM raw.fact_loan WHERE rate < 0"),
    ("DQ-09", "Mỗi loan_id unique", "SELECT CASE WHEN COUNT(*) = COUNT(DISTINCT loan_id) THEN 'PASS' ELSE 'FAIL' END FROM raw.fact_loan"),
    ("DQ-10", "sub_channel không NULL", "SELECT CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END FROM raw.fact_loan WHERE sub_channel IS NULL"),
    ("DQ-11", "customer_id không NULL", "SELECT CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END FROM raw.fact_loan WHERE customer_id IS NULL"),
    ("DQ-12", "date không NULL", "SELECT CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END FROM raw.fact_loan WHERE date IS NULL"),
]


def main():
    setup_logging("info")
    from app.data.db import execute_ro, execute_admin

    results = []
    for check_id, desc, sql in CHECKS:
        try:
            _, rows = execute_ro(sql)
            status = rows[0].get(list(rows[0].keys())[0], "FAIL") if rows else "FAIL"
            level = "BLOCK" if status == "FAIL" and check_id in ("DQ-01", "DQ-04") else "WARN"
            results.append((check_id, desc, status, level))
            _log.info("%s %s: %s (%s)", check_id, status, desc, level)
        except Exception as exc:
            results.append((check_id, desc, "ERROR", "BLOCK"))
            _log.error("%s ERROR: %s — %s", check_id, exc, desc)

    try:
        for check_id, desc, status, level in results:
            execute_admin(
                "INSERT INTO ops.dq_results (check_id, description, status, level, created_at) VALUES (:cid, :desc, :st, :lvl, NOW())",
                {"cid": check_id, "desc": desc, "st": status, "lvl": level},
            )
    except Exception as exc:
        _log.warning("Failed to write DQ results: %s", exc)

    blocked = [r for r in results if r[3] == "BLOCK" and r[2] != "PASS"]
    if blocked:
        _log.error("%d DQ checks BLOCKED!", len(blocked))
        sys.exit(1)
    _log.info("DQ checks complete: %d passed, %d failed", len([r for r in results if r[2] == "PASS"]), len([r for r in results if r[2] != "PASS"]))


if __name__ == "__main__":
    main()
