"""Turn ORM rows into the exact JSON shapes the original (Prisma) API returned."""
from __future__ import annotations

from datetime import datetime

from app.models import Conversation, Message, Snippet, User


def iso(dt: datetime | None) -> str | None:
    """Prisma/JS style: 2026-01-31T10:20:30.123Z (UTC, milliseconds)."""
    return None if dt is None else dt.isoformat(timespec="milliseconds") + "Z"


def user_json(u: User) -> dict:
    # password + otp* are never sent to the client
    return {
        "id": u.id, "name": u.name, "email": u.email, "avatar": u.avatar, "bio": u.bio,
        "isVerified": u.is_verified, "createdAt": iso(u.created_at), "updatedAt": iso(u.updated_at),
    }


def message_json(m: Message) -> dict:
    return {"id": m.id, "conversationId": m.conversation_id, "sender": m.sender, "content": m.content, "createdAt": iso(m.created_at)}


def conversation_json(c: Conversation, messages: list[Message] | None = None) -> dict:
    data = {
        "id": c.id, "title": c.title, "createdAt": iso(c.created_at), "updatedAt": iso(c.updated_at),
        "userId": c.user_id, "isPinned": c.is_pinned,
    }
    if messages is not None:
        data["messages"] = [message_json(m) for m in messages]
    return data


def snippet_json(s: Snippet) -> dict:
    return {
        "id": s.id, "title": s.title, "code": s.code, "language": s.language, "description": s.description,
        "isPublic": s.is_public, "createdAt": iso(s.created_at), "updatedAt": iso(s.updated_at), "userId": s.user_id,
    }
