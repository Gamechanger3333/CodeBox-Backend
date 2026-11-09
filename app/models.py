"""SQLAlchemy models mapped onto the EXISTING Prisma-created tables.

Table names ("User", "Conversation", ...) and camelCase column names are kept
exactly as Prisma created them, so you can point this app at your current
database without any data migration. Python attribute names are snake_case;
the string passed to mapped_column() is the real column name.

NOTE: `InterviewSession` is declared here because the interview feature needs
it. The original schema.prisma did not contain it and the migration history
ends with it being dropped - see README ("Bugs found while porting").
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    """Naive UTC datetime - matches Prisma's TIMESTAMP(3) WITHOUT TIME ZONE columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def new_id() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


_NOW = text("CURRENT_TIMESTAMP")


class User(Base):
    __tablename__ = "User"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text)
    email: Mapped[str] = mapped_column(Text, unique=True)
    password: Mapped[str] = mapped_column(Text)
    avatar: Mapped[str | None] = mapped_column(Text, nullable=True)
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_verified: Mapped[bool] = mapped_column("isVerified", Boolean, default=False, server_default=text("false"))
    otp_code: Mapped[str | None] = mapped_column("otpCode", Text, nullable=True)
    otp_expiry: Mapped[datetime | None] = mapped_column("otpExpiry", DateTime(), nullable=True)
    otp_attempts: Mapped[int] = mapped_column("otpAttempts", Integer, default=0, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column("createdAt", DateTime(), default=utcnow, server_default=_NOW)
    updated_at: Mapped[datetime] = mapped_column("updatedAt", DateTime(), default=utcnow, onupdate=utcnow)


class Conversation(Base):
    __tablename__ = "Conversation"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=new_id)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column("createdAt", DateTime(), default=utcnow, server_default=_NOW)
    updated_at: Mapped[datetime] = mapped_column("updatedAt", DateTime(), default=utcnow, onupdate=utcnow)
    user_id: Mapped[int] = mapped_column("userId", Integer, ForeignKey("User.id", onupdate="CASCADE", ondelete="RESTRICT"))
    is_pinned: Mapped[bool] = mapped_column("isPinned", Boolean, default=False, server_default=text("false"))

    messages: Mapped[list["Message"]] = relationship(back_populates="conversation", order_by="Message.created_at")


class Message(Base):
    __tablename__ = "Message"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(
        "conversationId", Text, ForeignKey("Conversation.id", onupdate="CASCADE", ondelete="RESTRICT")
    )
    sender: Mapped[str] = mapped_column(Text)  # "user" | "bot"
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column("createdAt", DateTime(), default=utcnow, server_default=_NOW)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class Snippet(Base):
    __tablename__ = "Snippet"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(Text)
    code: Mapped[str] = mapped_column(Text)
    language: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_public: Mapped[bool] = mapped_column("isPublic", Boolean, default=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column("createdAt", DateTime(), default=utcnow, server_default=_NOW)
    updated_at: Mapped[datetime] = mapped_column("updatedAt", DateTime(), default=utcnow, onupdate=utcnow)
    user_id: Mapped[int] = mapped_column("userId", Integer, ForeignKey("User.id", onupdate="CASCADE", ondelete="RESTRICT"))


class ProjectSession(Base):
    """One uploaded project per user (new upload replaces the old one)."""

    __tablename__ = "ProjectSession"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=new_id)
    user_id: Mapped[int] = mapped_column(
        "userId", Integer, ForeignKey("User.id", onupdate="CASCADE", ondelete="CASCADE"), unique=True
    )
    project_name: Mapped[str] = mapped_column("projectName", Text)
    file_tree: Mapped[str] = mapped_column("fileTree", Text)
    files: Mapped[str] = mapped_column(Text)  # JSON: [{path, content}]
    stats: Mapped[str] = mapped_column(Text)  # JSON: {total, analyzed, skipped, totalChars}
    analysis: Mapped[str] = mapped_column(Text)
    history: Mapped[str] = mapped_column(Text, default="[]", server_default=text("'[]'"))  # JSON: [{role, content}]
    rag_status: Mapped[str] = mapped_column("ragStatus", Text, default="pending", server_default=text("'pending'"))
    rag_chunk_count: Mapped[int] = mapped_column("ragChunkCount", Integer, default=0, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column("createdAt", DateTime(), default=utcnow, server_default=_NOW)
    updated_at: Mapped[datetime] = mapped_column("updatedAt", DateTime(), default=utcnow, onupdate=utcnow)


class InterviewSession(Base):
    __tablename__ = "InterviewSession"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=new_id)
    user_id: Mapped[int] = mapped_column(
        "userId", Integer, ForeignKey("User.id", onupdate="CASCADE", ondelete="CASCADE"), unique=True
    )
    project_session_id: Mapped[str] = mapped_column(
        "projectSessionId", Text, ForeignKey("ProjectSession.id", onupdate="CASCADE", ondelete="CASCADE"), unique=True
    )
    questions: Mapped[str] = mapped_column(Text)  # JSON: [{id, category, question}]
    transcript: Mapped[str] = mapped_column(Text, default="[]", server_default=text("'[]'"))
    current_index: Mapped[int] = mapped_column("currentIndex", Integer, default=0, server_default=text("0"))
    status: Mapped[str] = mapped_column(Text, default="in_progress", server_default=text("'in_progress'"))
    report: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column("createdAt", DateTime(), default=utcnow, server_default=_NOW)
    updated_at: Mapped[datetime] = mapped_column("updatedAt", DateTime(), default=utcnow, onupdate=utcnow)


class IngestedFileHash(Base):
    """Content hash per (sessionId, filePath) so unchanged files are not re-embedded."""

    __tablename__ = "IngestedFileHash"
    __table_args__ = (
        UniqueConstraint("sessionId", "filePath", name="IngestedFileHash_sessionId_filePath_key"),
        Index("IngestedFileHash_sessionId_idx", "sessionId"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column("sessionId", Text)
    file_path: Mapped[str] = mapped_column("filePath", Text)
    content_hash: Mapped[str] = mapped_column("contentHash", Text)
    updated_at: Mapped[datetime] = mapped_column("updatedAt", DateTime(), default=utcnow, onupdate=utcnow)


class CodeChunk(Base):
    """One embedded chunk of a user's uploaded project (used for RAG retrieval)."""

    __tablename__ = "CodeChunk"
    __table_args__ = (Index("CodeChunk_sessionId_idx", "sessionId"),)

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column("sessionId", Text)  # str(user_id)
    file_path: Mapped[str] = mapped_column("filePath", Text)
    content: Mapped[str] = mapped_column(Text)
    embedding = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column("createdAt", DateTime(), default=utcnow, server_default=_NOW)
