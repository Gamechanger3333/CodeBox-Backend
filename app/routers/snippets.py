"""Code snippets CRUD. Every query is scoped to the logged-in user (no IDOR)."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.errors import ApiError, err_body
from app.models import Snippet
from app.schemas import UUID_RE, SnippetCreateBody, SnippetUpdateBody
from app.security import get_current_user
from app.serializers import snippet_json
from app.services import codebox_ai

log = logging.getLogger("codebox.snippets")
router = APIRouter(tags=["snippets"])


def snippet_id_param(snippetId: str) -> str:
    if not UUID_RE.match(snippetId):
        raise ApiError(400, err_body("snippetId must be a valid UUID"))
    return snippetId


async def _owned(db: AsyncSession, snippet_id: str, user_id: int) -> Snippet | None:
    return (await db.execute(select(Snippet).where(Snippet.id == snippet_id, Snippet.user_id == user_id))).scalar_one_or_none()


@router.get("/snippets")
async def list_snippets(user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_session)):
    try:
        rows = (await db.execute(select(Snippet).where(Snippet.user_id == user["id"]).order_by(Snippet.created_at.desc()))).scalars().all()
        return {"snippets": [snippet_json(s) for s in rows]}
    except Exception:  # noqa: BLE001
        log.exception("list_snippets failed")
        return JSONResponse(err_body("Failed to fetch snippets"), status_code=500)


@router.post("/snippets", status_code=201)
async def create_snippet(body: SnippetCreateBody, user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_session)):
    try:
        language = body.language
        if not language or language == "auto":
            try:
                language = await codebox_ai.detect_language(body.code)
            except Exception:  # noqa: BLE001 - detection is a nice-to-have
                language = "plaintext"
        snippet = Snippet(
            title=body.title, code=body.code, language=language,
            description=(body.description or None), is_public=bool(body.isPublic), user_id=user["id"],
        )
        db.add(snippet)
        await db.commit()
        await db.refresh(snippet)
        return {"snippet": snippet_json(snippet)}
    except Exception:  # noqa: BLE001
        log.exception("create_snippet failed")
        return JSONResponse(err_body("Failed to create snippet"), status_code=500)


@router.get("/snippets/{snippetId}")
async def get_snippet(user: dict = Depends(get_current_user), snippet_id: str = Depends(snippet_id_param), db: AsyncSession = Depends(get_session)):
    try:
        snippet = await _owned(db, snippet_id, user["id"])
        if not snippet:
            return JSONResponse(err_body("Snippet not found"), status_code=404)
        return {"snippet": snippet_json(snippet)}
    except Exception:  # noqa: BLE001
        log.exception("get_snippet failed")
        return JSONResponse(err_body("Server error"), status_code=500)


@router.put("/snippets/{snippetId}")
async def update_snippet(
    body: SnippetUpdateBody, user: dict = Depends(get_current_user),
    snippet_id: str = Depends(snippet_id_param), db: AsyncSession = Depends(get_session),
):
    try:
        snippet = await _owned(db, snippet_id, user["id"])
        if not snippet:
            return JSONResponse(err_body("Snippet not found"), status_code=404)
        # Only the fields that were actually sent are changed (same rules as the Node version).
        snippet.title = body.title or snippet.title
        snippet.code = body.code or snippet.code
        snippet.language = body.language or snippet.language
        if body.description is not None:
            snippet.description = body.description
        if body.isPublic is not None:
            snippet.is_public = body.isPublic
        await db.commit()
        await db.refresh(snippet)
        return {"snippet": snippet_json(snippet)}
    except Exception:  # noqa: BLE001
        log.exception("update_snippet failed")
        return JSONResponse(err_body("Failed to update snippet"), status_code=500)


@router.delete("/snippets/{snippetId}")
async def delete_snippet(user: dict = Depends(get_current_user), snippet_id: str = Depends(snippet_id_param), db: AsyncSession = Depends(get_session)):
    try:
        snippet = await _owned(db, snippet_id, user["id"])
        if not snippet:
            return JSONResponse(err_body("Snippet not found"), status_code=404)
        await db.delete(snippet)
        await db.commit()
        return {"success": True}
    except Exception:  # noqa: BLE001
        log.exception("delete_snippet failed")
        return JSONResponse(err_body("Failed to delete snippet"), status_code=500)
