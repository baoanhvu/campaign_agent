"""Conversation management routes — list, create, delete, messages."""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Request, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.data.db import execute_ro, execute_admin
from app.logging_ import get_logger

router = APIRouter()
_log = get_logger("api.conversations")


class CreateConversation(BaseModel):
    session_id: str
    user_id: str
    first_message: str


class SaveMessage(BaseModel):
    role: str
    content: str


class UpdateTitle(BaseModel):
    title: str


@router.get("/conversations")
async def list_conversations(user_id: str = Query(...)):
    """List all conversations for a user, newest first."""
    try:
        _, rows = execute_ro("""
            SELECT session_id, title, created_at, updated_at
            FROM ops.conversations
            WHERE user_id = :uid
            ORDER BY updated_at DESC
            LIMIT 100
        """, {"uid": user_id})
        return {"conversations": rows}
    except Exception as exc:
        _log.error("list conversations failed: %s", exc)
        return JSONResponse({"error": str(exc)}, status_code=500)


@router.post("/conversations")
async def create_conversation(body: CreateConversation):
    """Create conversation immediately with fallback title.
    LLM title generated async in background."""
    fallback_title = body.first_message[:50]
    try:
        execute_admin("""
            INSERT INTO ops.conversations (session_id, user_id, title)
            VALUES (:sid, :uid, :title)
            ON CONFLICT (session_id) DO UPDATE SET updated_at = NOW()
        """, {"sid": body.session_id, "uid": body.user_id, "title": fallback_title})
    except Exception as exc:
        _log.error("create conversation failed: %s", exc)
        return JSONResponse({"error": str(exc)}, status_code=500)

    asyncio.create_task(_update_title_async(body.session_id, body.first_message))

    return {"session_id": body.session_id, "title": fallback_title}


@router.put("/conversations/{session_id}/title")
async def update_title(session_id: str, body: UpdateTitle):
    """Update conversation title."""
    try:
        execute_admin("""
            UPDATE ops.conversations SET title = :title, updated_at = NOW()
            WHERE session_id = :sid
        """, {"sid": session_id, "title": body.title})
        return {"status": "ok"}
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@router.delete("/conversations/{session_id}")
async def delete_conversation(session_id: str):
    """Delete a conversation and all its messages."""
    try:
        execute_admin("DELETE FROM ops.conversations WHERE session_id = :sid", {"sid": session_id})
        return {"status": "ok"}
    except Exception as exc:
        _log.error("delete conversation failed: %s", exc)
        return JSONResponse({"error": str(exc)}, status_code=500)


@router.get("/conversations/{session_id}/messages")
async def get_messages(session_id: str):
    """Get all messages for a conversation."""
    try:
        _, rows = execute_ro("""
            SELECT role, content, created_at
            FROM ops.chat_messages
            WHERE session_id = :sid
            ORDER BY created_at ASC
        """, {"sid": session_id})
        return {"messages": rows}
    except Exception as exc:
        _log.error("get messages failed: %s", exc)
        return JSONResponse({"error": str(exc)}, status_code=500)


@router.post("/conversations/{session_id}/messages")
async def save_message(session_id: str, body: SaveMessage):
    """Save a message to a conversation."""
    try:
        execute_admin("""
            INSERT INTO ops.chat_messages (session_id, role, content)
            VALUES (:sid, :role, :content)
        """, {"sid": session_id, "role": body.role, "content": body.content})
        execute_admin("""
            UPDATE ops.conversations SET updated_at = NOW() WHERE session_id = :sid
        """, {"sid": session_id})
        return {"status": "ok"}
    except Exception as exc:
        _log.error("save message failed: %s", exc)
        return JSONResponse({"error": str(exc)}, status_code=500)


async def _update_title_async(session_id: str, first_message: str) -> None:
    """Generate LLM title in background and update DB."""
    try:
        title = await _generate_title(first_message)
        execute_admin("""
            UPDATE ops.conversations SET title = :title WHERE session_id = :sid
        """, {"sid": session_id, "title": title})
    except Exception as exc:
        _log.debug("Background title update failed: %s", exc)


async def _generate_title(first_message: str) -> str:
    """Generate a short title from the first message using LLM."""
    try:
        from app.llm.client import get_client
        client = get_client()
        title = await client.chat(
            messages=[
                {"role": "system", "content": "Tóm tắt câu hỏi sau thành tiêu đề ngắn (tối đa 50 ký tự, tiếng Việt, không dấu câu). Chỉ trả tiêu đề, không giải thích."},
                {"role": "user", "content": first_message},
            ],
            temperature=0.0,
            max_tokens=30,
        )
        title = title.strip().strip('"').strip("'")[:50]
        if not title:
            title = first_message[:50]
        return title
    except Exception as exc:
        _log.warning("Title generation failed: %s", exc)
        return first_message[:50]
