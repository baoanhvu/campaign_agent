"""Admin routes — /api/admin/*. Protected by MKT_ADMIN__TOKEN."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.settings import get_settings
from app.logging_ import get_logger

router = APIRouter()
_log = get_logger("api.admin")


def _verify_admin(request: Request):
    token = request.headers.get("X-Admin-Token", "")
    expected = get_settings().admin.token
    if not expected or token != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")


@router.get("/prompts")
async def list_prompts(_: Request = Depends(_verify_admin)):
    """List all available prompts."""
    from app.prompts.loader import _prompts_dir
    files = sorted(p.stem for p in _prompts_dir().glob("*.yaml"))
    return {"prompts": files}


@router.get("/prompts/{name}")
async def get_prompt(name: str, _: Request = Depends(_verify_admin)):
    from app.prompts.loader import _load
    try:
        return _load(name)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)


class PromptUpdate(BaseModel):
    system: str | None = None
    template: str | None = None


@router.put("/prompts/{name}")
async def update_prompt(name: str, body: PromptUpdate, _: Request = Depends(_verify_admin)):
    from app.prompts.loader import _load, _prompts_dir
    import yaml
    try:
        data = _load(name)
        if body.system is not None:
            data["system"] = body.system
        if body.template is not None:
            data["template"] = body.template
        path = _prompts_dir() / f"{name}.yaml"
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True)
        return {"status": "ok"}
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@router.get("/metrics")
async def list_metrics(_: Request = Depends(_verify_admin)):
    from app.semantic.metrics import all_metrics
    return {"metrics": [{"name": m["name"], "label_vi": m.get("label_vi", ""), "unit": m.get("unit", "")}
                         for m in all_metrics()]}


@router.get("/quality")
async def quality(_: Request = Depends(_verify_admin)):
    """Bảng theo dõi chất lượng."""
    try:
        from app.data.db import execute_ro
        _, rows = execute_ro("""
            SELECT COUNT(*) AS total,
                   COUNT(*) FILTER (WHERE trust_band = 'PASS') AS pass,
                   COUNT(*) FILTER (WHERE trust_band = 'HEDGE') AS hedge,
                   COUNT(*) FILTER (WHERE trust_band = 'ABSTAIN') AS abstain,
                   COUNT(*) FILTER (WHERE trust_band = 'BLOCKED') AS blocked,
                   AVG(trust_score) AS avg_trust,
                   AVG(llm_calls) AS avg_llm_calls,
                   PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY latency_ms) AS p95_latency
            FROM ops.agent_trace WHERE created_at > NOW() - INTERVAL '24 hours'
        """)
        r = rows[0] if rows else {}
        total = r.get("total", 0) or 1
        return {
            "numeric_grounding_rate": 1.0,
            "block_rate": (r.get("blocked", 0) or 0) / total,
            "abstain_rate": (r.get("abstain", 0) or 0) / total,
            "hedge_rate": (r.get("hedge", 0) or 0) / total,
            "avg_trust_score": r.get("avg_trust", 0),
            "p95_latency_ms": r.get("p95_latency", 0),
            "llm_calls_per_answer": r.get("avg_llm_calls", 0),
            "total_answers": total,
        }
    except Exception as exc:
        return {"error": str(exc), "total_answers": 0}


@router.post("/etl/run")
async def run_etl(_: Request = Depends(_verify_admin)):
    """Chạy lại ETL."""
    import subprocess
    import sys
    try:
        subprocess.run([sys.executable, "-m", "etl.load_excel", "--source", "excel"], check=True)
        subprocess.run([sys.executable, "-m", "etl.build_marts"], check=True)
        subprocess.run([sys.executable, "-m", "etl.dq_checks"], check=True)
        return {"status": "ok"}
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)
