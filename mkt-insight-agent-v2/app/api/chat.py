"""Chat route — GET /api/chat (SSE via EventSource) + POST /api/chat."""
from __future__ import annotations

import json

from fastapi import APIRouter, Request, Query
from sse_starlette.sse import EventSourceResponse

from app.agent.orchestrator import Orchestrator
from app.logging_ import get_logger

router = APIRouter()
_log = get_logger("api.chat")


def _make_stream(question: str, history: list, user_id: str, session_id: str):
    orch = Orchestrator.from_env()

    async def event_generator():
        try:
            async for event in orch.answer_stream(
                question, history=history, user_id=user_id, session_id=session_id
            ):
                yield {"event": event["event"], "data": json.dumps(event["data"], ensure_ascii=False, default=str)}
        except Exception as exc:
            _log.error("Chat stream error: %s", exc)
            yield {"event": "error", "data": json.dumps(
                {"code": "STREAMING_ERROR", "message": str(exc), "retryable": False},
                ensure_ascii=False)}

    return EventSourceResponse(
        event_generator(),
        ping=15,
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.get("/chat")
async def chat_get(
    request: Request,
    message: str = Query(...),
    user_id: str = Query(default=""),
    session_id: str = Query(default=""),
):
    """GET /api/chat?message=... — SSE streaming via EventSource."""
    if not user_id:
        user_id = "user-" + str(id(request))
    if not session_id:
        session_id = "session-" + str(id(request))
    return _make_stream(message, [], user_id, session_id)


@router.post("/chat")
async def chat_post(request: Request):
    """POST /api/chat — SSE streaming via fetch."""
    user_id = request.headers.get("X-GreenNode-AgentBase-User-Id", "")
    session_id = request.headers.get("X-GreenNode-AgentBase-Session-Id", "")
    body = await request.json()
    question = body.get("message", "")
    history = body.get("history", [])
    return _make_stream(question, history, user_id, session_id)
