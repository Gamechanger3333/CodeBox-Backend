"""Mock technical interview built from the user's own uploaded project."""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.errors import err_body
from app.models import InterviewSession, ProjectSession, new_id, utcnow
from app.schemas import InterviewAnswerBody
from app.security import get_current_user
from app.services import interview_analyzer

log = logging.getLogger("codebox.interview")
router = APIRouter(tags=["interview"])
MAX_ANSWER_LENGTH = 4000


def format_session_response(session: InterviewSession) -> dict:
    questions = json.loads(session.questions)
    transcript = json.loads(session.transcript)
    return {
        "status": session.status,
        "progress": {"current": session.current_index, "total": len(questions)},
        "currentQuestion": questions[session.current_index] if 0 <= session.current_index < len(questions) else None,
        "transcript": transcript,
        "report": session.report or None,
    }


async def _interview(db: AsyncSession, user_id: int) -> InterviewSession | None:
    return (await db.execute(select(InterviewSession).where(InterviewSession.user_id == user_id))).scalar_one_or_none()


@router.post("/interview/start")
async def start_interview(user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_session)):
    """Start - or RESUME - the interview for the loaded project (no regeneration, saves an AI call)."""
    user_id = user["id"]
    project = (await db.execute(select(ProjectSession).where(ProjectSession.user_id == user_id))).scalar_one_or_none()
    if not project:
        return JSONResponse(err_body("No project loaded. Please upload a project first."), status_code=404)

    existing = await _interview(db, user_id)
    if existing and existing.project_session_id == project.id:
        return format_session_response(existing)

    files = json.loads(project.files)
    questions = await interview_analyzer.generate_interview_questions(project.file_tree, files)
    values = {
        InterviewSession.project_session_id: project.id,
        InterviewSession.questions: json.dumps(questions, ensure_ascii=False),
        InterviewSession.transcript: "[]",
        InterviewSession.current_index: 0,
        InterviewSession.status: "in_progress",
        InterviewSession.report: None,
    }
    stmt = pg_insert(InterviewSession).values({InterviewSession.id: new_id(), InterviewSession.user_id: user_id,
                                               InterviewSession.created_at: utcnow(), InterviewSession.updated_at: utcnow(), **values})
    stmt = stmt.on_conflict_do_update(index_elements=[InterviewSession.user_id], set_={**values, InterviewSession.updated_at: utcnow()})
    await db.execute(stmt)
    await db.commit()
    session = await _interview(db, user_id)
    await db.refresh(session)
    return format_session_response(session)


@router.post("/interview/answer")
async def submit_answer(body: InterviewAnswerBody, user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_session)):
    user_id = user["id"]
    answer = body.answer
    if not answer:
        return JSONResponse(err_body("No answer provided"), status_code=400)

    session = await _interview(db, user_id)
    if not session:
        return JSONResponse(err_body("No interview in progress. Start one first."), status_code=404)
    if session.status == "completed":
        return JSONResponse(err_body("This interview is already complete."), status_code=400)

    questions = json.loads(session.questions)
    if not 0 <= session.current_index < len(questions):
        return JSONResponse(err_body("No more questions in this interview."), status_code=400)
    current = questions[session.current_index]

    project = await db.get(ProjectSession, session.project_session_id)
    if not project:
        return JSONResponse(err_body("The project this interview was based on no longer exists."), status_code=404)
    files = json.loads(project.files)
    transcript = json.loads(session.transcript)

    evaluation = await interview_analyzer.evaluate_answer(project.file_tree, files, current["question"], answer, transcript)

    transcript.append(
        {
            "questionId": current["id"], "category": current["category"], "question": current["question"], "answer": answer,
            "feedback": evaluation["feedback"], "teach": evaluation["teach"], "followUp": evaluation["followUp"],
        }
    )
    next_index = session.current_index + 1
    is_last = next_index >= len(questions)
    session.transcript = json.dumps(transcript, ensure_ascii=False)
    session.current_index = next_index
    session.status = "ready_for_report" if is_last else "in_progress"
    await db.commit()

    return {
        "feedback": evaluation["feedback"], "teach": evaluation["teach"], "followUp": evaluation["followUp"],
        "isLastQuestion": is_last,
        "nextQuestion": None if is_last else questions[next_index],
        "progress": {"current": next_index, "total": len(questions)},
        "status": session.status,
    }


@router.post("/interview/finish")
async def finish_interview(user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_session)):
    """Separate step from the last answer: the report is the slowest AI call, so the UI shows the
    last feedback immediately and only then asks for the report."""
    session = await _interview(db, user["id"])
    if not session:
        return JSONResponse(err_body("No interview found."), status_code=404)
    if session.status == "completed" and session.report:
        return {"report": session.report}

    project = await db.get(ProjectSession, session.project_session_id)
    if not project:
        return JSONResponse(err_body("The project this interview was based on no longer exists."), status_code=404)
    files = json.loads(project.files)
    transcript = json.loads(session.transcript)
    if not transcript:
        return JSONResponse(err_body("Answer at least one question before requesting a report."), status_code=400)

    report = await interview_analyzer.generate_final_report(project.file_tree, files, transcript)
    session.status = "completed"
    session.report = report
    await db.commit()
    return {"report": report}


@router.get("/interview/session")
async def get_interview_session(user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_session)):
    try:
        session = await _interview(db, user["id"])
        if not session:
            return {"hasInterview": False}
        return {"hasInterview": True, **format_session_response(session)}
    except Exception:  # noqa: BLE001
        log.exception("Get interview session error")
        return {"hasInterview": False}


@router.delete("/interview/session")
async def reset_interview(user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_session)):
    try:
        await db.execute(delete(InterviewSession).where(InterviewSession.user_id == user["id"]))
        await db.commit()
    except Exception:  # noqa: BLE001
        log.exception("Reset interview error")
    return {"success": True}
