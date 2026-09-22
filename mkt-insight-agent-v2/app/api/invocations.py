"""Invocations route — POST /invocations (non-streaming, SDK convention)."""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.agent.orchestrator import Orchestrator
from app.logging_ import get_logger

router = APIRouter()
_log = get_logger("api.invocations")


@router.post("/invocations")
async def invoke(request: Request):
    """Non-streaming gateway for Zalo/external APIs."""
    user_id = request.headers.get("X-GreenNode-AgentBase-User-Id", "anonymous")
    session_id = request.headers.get("X-GreenNode-AgentBase-Session-Id", "default")

    body = await request.json()
    message = body.get("message", "")
    history = body.get("history", [])

    try:
        orch = Orchestrator.from_env()
        result = orch.answer(message, history=history, user_id=user_id, session_id=session_id)
        return result.to_invocation_response()
    except Exception as exc:
        _log.error("Invocation failed: %s", exc)
        return JSONResponse(
            {"error": str(exc), "code": "INVOCATION_ERROR"},
            status_code=500,
        )
