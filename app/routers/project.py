"""Project Analyzer: upload a ZIP -> AI overview now, RAG indexing in the background -> Q&A."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import zipfile

from fastapi import APIRouter, BackgroundTasks, Depends, File, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import SessionLocal, get_session
from app.errors import err_body
from app.models import CodeChunk, IngestedFileHash, InterviewSession, ProjectSession, new_id, utcnow
from app.schemas import ProjectAskBody
from app.security import get_current_user
from app.services import project_analyzer, rag_engine

log = logging.getLogger("codebox.project")
router = APIRouter(tags=["project"])

MAX_HISTORY = 20  # keep the last 10 turns (20 messages)
MAX_MESSAGE_LENGTH = 8000
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
ZIP_MIME_TYPES = {"application/zip", "application/x-zip-compressed"}


async def _read_capped(file: UploadFile, limit: int) -> bytes | None:
    """Read the upload in 1 MB pieces and stop as soon as it is over the limit."""
    chunks: list[bytes] = []
    total = 0
    while True:
        piece = await file.read(1024 * 1024)
        if not piece:
            break
        total += len(piece)
        if total > limit:
            return None
        chunks.append(piece)
    return b"".join(chunks)


async def index_project_in_background(user_id: int, files: list[dict[str, str]]) -> None:
    """Runs AFTER the HTTP response is sent (FastAPI BackgroundTasks).
    Embedding 60+ files can take minutes on CPU-only hardware - the user already has the analysis."""
    try:
        result = await rag_engine.ingest_project_chunks(user_id, files)
        log.info(
            "RAG ingestion complete for user %s: %s total chunks (%s files re-embedded, %s unchanged & skipped)",
            user_id, result["chunkCount"], result["changedFileCount"], result["skippedFileCount"],
        )
        status, count = "ready", result["chunkCount"]
    except Exception:  # noqa: BLE001
        log.exception("RAG ingestion failed (follow-up Q&A will be degraded)")
        status, count = "failed", None

    try:  # the session may have been cleared/replaced mid-ingestion - safe to ignore
        async with SessionLocal() as db:
            values = {"rag_status": status}
            if count is not None:
                values["rag_chunk_count"] = count
            await db.execute(update(ProjectSession).where(ProjectSession.user_id == user_id).values(**values))
            await db.commit()
    except Exception:  # noqa: BLE001
        pass


@router.post("/project/upload")
async def upload_project(
    background: BackgroundTasks,
    project: UploadFile | None = File(None),  # the form field is called "project"
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    if project is None:
        return JSONResponse(err_body("No ZIP file uploaded"), status_code=400)

    filename = project.filename or ""
    if not (project.content_type in ZIP_MIME_TYPES or filename.lower().endswith(".zip")):
        return JSONResponse(err_body("Only ZIP files are accepted"), status_code=400)

    zip_bytes = await _read_capped(project, MAX_UPLOAD_BYTES)
    if zip_bytes is None:
        return JSONResponse(err_body("File too large (max 50MB)"), status_code=413)

    user_id = user["id"]
    project_name = re.sub(r"\.zip$", "", filename, flags=re.IGNORECASE)

    # 1. Extract (CPU bound -> thread, so other requests keep flowing)
    try:
        extracted = await asyncio.to_thread(project_analyzer.extract_project_files, zip_bytes)
    except (zipfile.BadZipFile, ValueError, OSError, RuntimeError, NotImplementedError):
        return JSONResponse(err_body("Failed to parse ZIP file. Make sure it is a valid ZIP archive."), status_code=400)

    if not extracted["files"]:
        return JSONResponse(
            err_body("No readable source files found in this ZIP. Make sure it contains source code files."), status_code=400
        )

    # 2. One-shot AI overview (uses the capped context)
    analysis = await project_analyzer.analyze_project(extracted["fileTree"], extracted["files"])

    # 3. Upsert: one row per user, a new upload replaces the old one. ragStatus restarts at "pending".
    values = {
        ProjectSession.project_name: project_name,
        ProjectSession.file_tree: extracted["fileTree"],
        ProjectSession.files: json.dumps(extracted["files"], ensure_ascii=False),
        ProjectSession.stats: json.dumps(extracted["stats"]),
        ProjectSession.analysis: analysis,
        ProjectSession.history: "[]",  # reset chat history on new upload
        ProjectSession.rag_status: "pending",
        ProjectSession.rag_chunk_count: 0,
    }
    # Keys are ORM attributes (not strings): SQLAlchemy maps them to the real camelCase column names.
    stmt = pg_insert(ProjectSession).values({ProjectSession.id: new_id(), ProjectSession.user_id: user_id,
                                             ProjectSession.created_at: utcnow(), ProjectSession.updated_at: utcnow(), **values})
    stmt = stmt.on_conflict_do_update(index_elements=[ProjectSession.user_id], set_={**values, ProjectSession.updated_at: utcnow()})
    # FIX vs original: the upsert keeps the same ProjectSession id, so an old InterviewSession
    # would still look "current" and show questions about the PREVIOUS project. Drop it explicitly.
    await db.execute(delete(InterviewSession).where(InterviewSession.user_id == user_id))
    await db.execute(stmt)
    await db.commit()

    background.add_task(index_project_in_background, user_id, extracted["allFiles"])
    return {
        "success": True,
        "projectName": project_name,
        "stats": extracted["stats"],
        "fileTree": extracted["fileTree"],
        "analysis": analysis,
        "ragStatus": "pending",
    }


@router.post("/project/ask")
async def ask_project(body: ProjectAskBody, user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_session)):
    user_id = user["id"]
    message = body.message
    if not message:
        return JSONResponse(err_body("No message provided"), status_code=400)
    if len(message) > MAX_MESSAGE_LENGTH:
        return JSONResponse(err_body(f"Message too long (max {MAX_MESSAGE_LENGTH} characters)"), status_code=400)

    session = (await db.execute(select(ProjectSession).where(ProjectSession.user_id == user_id))).scalar_one_or_none()
    if not session:
        return JSONResponse(err_body("No project loaded. Please upload a project ZIP first."), status_code=404)

    if session.rag_status == "pending":
        return JSONResponse(
            {
                "error": "Your project is still being indexed for Q&A (this runs in the background and can take a couple of minutes on this machine). Please try again shortly.",
                "ragStatus": "pending",
            },
            status_code=423,
        )
    if session.rag_status == "failed":
        return JSONResponse(
            {
                "error": "Indexing this project for Q&A failed. Try re-uploading — if it keeps failing, check that the embedding service (Ollama) is running.",
                "ragStatus": "failed",
            },
            status_code=500,
        )

    history = json.loads(session.history)
    # Retrieve only the chunks relevant to THIS question instead of resending the whole project.
    chunks = await rag_engine.retrieve_relevant_chunks(db, user_id, message)
    if not chunks:
        return JSONResponse(err_body("No relevant content found for that question in the indexed project."), status_code=404)

    response = await project_analyzer.ask_about_project_rag(chunks, history, message)

    updated = [*history, {"role": "user", "content": message}, {"role": "assistant", "content": response}][-MAX_HISTORY:]
    session.history = json.dumps(updated, ensure_ascii=False)
    await db.commit()
    return {"response": response, "projectName": session.project_name}


@router.get("/project/session")
async def get_project_session(user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_session)):
    try:
        session = (await db.execute(select(ProjectSession).where(ProjectSession.user_id == user["id"]))).scalar_one_or_none()
        if not session:
            return {"hasProject": False}
        history = json.loads(session.history)
        count = len(history) / 2
        return {
            "hasProject": True,
            "projectName": session.project_name,
            "stats": json.loads(session.stats),
            "fileTree": session.file_tree,
            "analysis": session.analysis,  # restored so the UI can show it again
            "history": history,
            "messageCount": int(count) if count == int(count) else count,
            "ragStatus": session.rag_status,  # "pending" | "ready" | "failed"
            "ragChunkCount": session.rag_chunk_count,
        }
    except Exception:  # noqa: BLE001
        log.exception("Get project session error")
        return {"hasProject": False}


@router.delete("/project/session")
async def clear_project(user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_session)):
    try:
        user_id = user["id"]
        await db.execute(delete(ProjectSession).where(ProjectSession.user_id == user_id))
        await db.execute(delete(CodeChunk).where(CodeChunk.session_id == str(user_id)))
        await db.execute(delete(IngestedFileHash).where(IngestedFileHash.session_id == str(user_id)))
        await db.commit()
    except Exception:  # noqa: BLE001
        log.exception("Clear project error")  # worst case it is already gone -> still report success
    return {"success": True}
