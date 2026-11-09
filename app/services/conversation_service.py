"""Chat conversations: create, send a message (AI reply + auto title), delete."""
from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Conversation, Message, utcnow
from app.services import codebox_ai

log = logging.getLogger("codebox.chat")
MAX_CONTEXT_MESSAGES = 30  # keeps Groq token cost predictable on long chats


async def start_conversation(db: AsyncSession, user_id: int) -> Conversation:
    conv = Conversation(user_id=user_id)
    db.add(conv)
    await db.commit()
    return conv


async def send_message(db: AsyncSession, conversation_id: str, message: str, sender: str = "user") -> str:
    """Save the user's message + the bot reply atomically and return the reply."""
    if not conversation_id or not message or not sender:
        raise ValueError("Missing conversationId, message, or sender")

    # FIX vs original: the Node version ordered ASC and took the first 30, i.e. the OLDEST
    # messages, so after 30 messages the model stopped seeing recent history. We take the
    # LATEST 30 (DESC + limit, then reverse into chronological order).
    rows = (
        await db.execute(
            select(Message).where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc(), Message.id.desc()).limit(MAX_CONTEXT_MESSAGES)
        )
    ).scalars().all()
    existing = list(reversed(rows))
    is_first_message = len(existing) == 0

    history = [{"sender": m.sender, "content": m.content} for m in existing] + [{"sender": "user", "content": message}]
    bot_response = await codebox_ai.get_codebox_ai_response(history)

    now = utcnow()
    # Distinct timestamps (1 ms apart) so "user then bot" ordering is never ambiguous.
    db.add(Message(conversation_id=conversation_id, sender=sender, content=message, created_at=now))
    db.add(Message(conversation_id=conversation_id, sender="bot", content=bot_response, created_at=now + timedelta(milliseconds=1)))
    await db.commit()  # one transaction: never a user message without its reply

    if is_first_message:  # title generation is non-critical - never fail the request because of it
        try:
            title = await codebox_ai.generate_conversation_title(message)
            conv = await db.get(Conversation, conversation_id)
            if conv:
                conv.title = title
                await db.commit()
        except Exception as exc:  # noqa: BLE001
            await db.rollback()
            log.error("Title generation failed: %s", exc)
    return bot_response


async def delete_conversation_by_id(db: AsyncSession, conversation_id: str) -> None:
    """Messages + conversation in ONE transaction (no orphans on crash)."""
    await db.execute(delete(Message).where(Message.conversation_id == conversation_id))
    await db.execute(delete(Conversation).where(Conversation.id == conversation_id))
    await db.commit()
