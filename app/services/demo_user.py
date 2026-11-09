"""'Try Demo Account' support - everything demo-related lives here.

Strategy: RESET ON LOGIN. Each time someone signs in as the demo user, its data is
wiped and re-seeded with the curated sample set, so every visitor starts clean.
Trade-off (same as the original): two visitors at the same moment can wipe each other's view.
"""
from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import CodeChunk, Conversation, IngestedFileHash, Message, ProjectSession, Snippet, User, utcnow
from app.security import hash_password

DEMO_USER_NAME = "Demo User"
_DATA = json.loads((Path(__file__).resolve().parent.parent / "data" / "demo_data.json").read_text(encoding="utf-8"))
DEMO_CONVERSATIONS: list[dict] = _DATA["DEMO_CONVERSATIONS"]
DEMO_SNIPPETS: list[dict] = _DATA["DEMO_SNIPPETS"]


def demo_email() -> str:
    return get_settings().demo_user_email.lower()


def is_demo_user_email(email: str = "") -> bool:
    return email.lower() == demo_email()


async def reset_demo_user_data(db: AsyncSession, user_id: int) -> None:
    """Delete + re-create the demo user's content. Fully idempotent."""
    conv_ids = select(Conversation.id).where(Conversation.user_id == user_id)
    await db.execute(delete(Message).where(Message.conversation_id.in_(conv_ids)))  # FK is RESTRICT: messages first
    await db.execute(delete(Conversation).where(Conversation.user_id == user_id))
    await db.execute(delete(Snippet).where(Snippet.user_id == user_id))
    # Project analyzer / interview data (InterviewSession is removed by ON DELETE CASCADE).
    await db.execute(delete(ProjectSession).where(ProjectSession.user_id == user_id))
    await db.execute(delete(CodeChunk).where(CodeChunk.session_id == str(user_id)))
    await db.execute(delete(IngestedFileHash).where(IngestedFileHash.session_id == str(user_id)))

    base = utcnow()
    for ci, convo in enumerate(DEMO_CONVERSATIONS):
        # Give every message a distinct, increasing timestamp so chat order is deterministic.
        conv = Conversation(user_id=user_id, title=convo["title"], is_pinned=convo["isPinned"], created_at=base + timedelta(milliseconds=ci))
        db.add(conv)
        await db.flush()
        for mi, m in enumerate(convo["messages"]):
            db.add(Message(conversation_id=conv.id, sender=m["sender"], content=m["content"],
                           created_at=base + timedelta(milliseconds=ci * 100 + mi)))
    for s in DEMO_SNIPPETS:
        db.add(Snippet(user_id=user_id, title=s["title"], code=s["code"], language=s["language"],
                       description=s.get("description"), is_public=s["isPublic"]))
    await db.commit()


async def ensure_demo_user_seeded(db: AsyncSession) -> User:
    """Create the demo account if needed and reset its data. Safe to run on every deploy."""
    hashed = await hash_password(get_settings().demo_user_password_seed)
    user = (await db.execute(select(User).where(User.email == demo_email()))).scalar_one_or_none()
    if user:
        user.password = hashed
        user.is_verified = True
    else:
        user = User(name=DEMO_USER_NAME, email=demo_email(), password=hashed, is_verified=True)
        db.add(user)
    await db.commit()
    await db.refresh(user)
    await reset_demo_user_data(db, user.id)
    return user
