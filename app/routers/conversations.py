"""Conversations (chat) + code analysis. Error contract: {"error": "..."}."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.errors import ApiError, err_body
from app.models import Conversation, Message
from app.schemas import UUID_RE, AnalyzeCodeBody, SendMessageBody, TitleBody
from app.security import get_current_user
from app.serializers import conversation_json
from app.services import codebox_ai, conversation_service

log = logging.getLogger("codebox.conversations")
router = APIRouter(tags=["conversations"])


def conversation_id_param(conversationId: str) -> str:
    """Path-param validation; runs AFTER auth because it is listed after get_current_user."""
    if not UUID_RE.match(conversationId):
        raise ApiError(400, err_body("conversationId must be a valid UUID"))
    return conversationId


async def _owned(db: AsyncSession, conversation_id: str, user_id: int) -> Conversation | None:
    """Ownership check: a user can only ever touch their own conversations."""
    return (
        await db.execute(select(Conversation).where(Conversation.id == conversation_id, Conversation.user_id == user_id))
    ).scalar_one_or_none()


@router.get("/check_authentication")
async def check_authentication(user: dict = Depends(get_current_user)):
    return {"authenticated": True, "user": user}


@router.get("/latest_conversation")
async def latest_conversation(user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_session)):
    try:
        conv = (
            await db.execute(select(Conversation).where(Conversation.user_id == user["id"]).order_by(Conversation.created_at.desc()).limit(1))
        ).scalar_one_or_none()
        if conv:
            return {"conversationId": conv.id}
        return JSONResponse(err_body("No conversations found"), status_code=404)
    except Exception:  # noqa: BLE001
        log.exception("latest_conversation failed")
        return JSONResponse(err_body("Internal server error"), status_code=500)


@router.post("/start_conversation")
async def start_conversation(user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_session)):
    conv = await conversation_service.start_conversation(db, user["id"])
    return {"conversationId": conv.id}


@router.post("/send_message")
async def send_message(body: SendMessageBody, user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_session)):
    if not await _owned(db, body.conversationId, user["id"]):
        return JSONResponse(err_body("Conversation not found"), status_code=404)
    bot_response = await conversation_service.send_message(db, body.conversationId, body.message, "user")
    conv = await db.get(Conversation, body.conversationId)
    await db.refresh(conv)
    return {"response": bot_response, "title": conv.title if conv else None}


@router.get("/getAllConversationIDs")
async def get_all_conversation_ids(
    page: str | None = Query(None), limit: str | None = Query(None),
    user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_session),
):
    """Paginated list. Lenient like the original: bad/zero values fall back to defaults (page 1, 50 per page)."""

    def to_int(value: str | None, default: int) -> int:
        try:
            n = int(value) if value is not None else 0
        except ValueError:
            n = 0
        return n if n >= 1 else default

    page_n = to_int(page, 1)
    limit_n = min(to_int(limit, 50), 100)  # validator intended max 100; the Node code never enforced it
    rows = (
        await db.execute(
            select(Conversation).where(Conversation.user_id == user["id"])
            .order_by(Conversation.is_pinned.desc(), Conversation.created_at.desc())
            .offset((page_n - 1) * limit_n).limit(limit_n)
        )
    ).scalars().all()
    return [{"id": c.id, "title": c.title, "createdAt": conversation_json(c)["createdAt"], "isPinned": c.is_pinned} for c in rows]


@router.get("/get_conversation/{conversationId}")
async def get_conversation(
    user: dict = Depends(get_current_user), conversation_id: str = Depends(conversation_id_param), db: AsyncSession = Depends(get_session)
):
    conv = await _owned(db, conversation_id, user["id"])
    if not conv:
        return JSONResponse(err_body("Conversation not found"), status_code=404)
    messages = (await db.execute(select(Message).where(Message.conversation_id == conv.id).order_by(Message.created_at.asc(), Message.id.asc()))).scalars().all()
    return {"conversation": conversation_json(conv, list(messages))}


@router.delete("/conversation/{conversationId}")
async def delete_conversation(
    user: dict = Depends(get_current_user), conversation_id: str = Depends(conversation_id_param), db: AsyncSession = Depends(get_session)
):
    try:
        if not await _owned(db, conversation_id, user["id"]):
            return JSONResponse(err_body("Conversation not found"), status_code=404)
        await conversation_service.delete_conversation_by_id(db, conversation_id)
        return {"success": True, "message": "Conversation deleted"}
    except Exception:  # noqa: BLE001
        log.exception("delete_conversation failed")
        return JSONResponse({"success": False, "message": "Server error"}, status_code=500)


@router.patch("/conversation/{conversationId}/pin")
async def toggle_pin(
    user: dict = Depends(get_current_user), conversation_id: str = Depends(conversation_id_param), db: AsyncSession = Depends(get_session)
):
    try:
        conv = await _owned(db, conversation_id, user["id"])
        if not conv:
            return JSONResponse(err_body("Conversation not found"), status_code=404)
        conv.is_pinned = not conv.is_pinned
        await db.commit()
        return {"isPinned": conv.is_pinned}
    except Exception:  # noqa: BLE001
        log.exception("toggle_pin failed")
        return JSONResponse(err_body("Server error"), status_code=500)


@router.patch("/conversation/{conversationId}/title")
async def update_title(
    body: TitleBody, user: dict = Depends(get_current_user),
    conversation_id: str = Depends(conversation_id_param), db: AsyncSession = Depends(get_session),
):
    try:
        conv = await _owned(db, conversation_id, user["id"])
        if not conv:
            return JSONResponse(err_body("Conversation not found"), status_code=404)
        conv.title = body.title
        await db.commit()
        return {"title": conv.title}
    except Exception:  # noqa: BLE001
        log.exception("update_title failed")
        return JSONResponse(err_body("Server error"), status_code=500)


@router.post("/analyze_code")
async def analyze_code(body: AnalyzeCodeBody, user: dict = Depends(get_current_user)):
    analysis = await codebox_ai.analyze_code(body.code, body.filename or "code.txt")
    return {"analysis": analysis}
