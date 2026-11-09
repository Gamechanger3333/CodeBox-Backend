import json

from sqlalchemy import func, select

from app.models import InterviewSession
from tests.test_project_rag import SAMPLE_ZIP, upload

QUESTIONS = [
    {"category": "security", "question": "Why did you pick JWT?"},
    {"category": "scaling", "question": "How would you scale this?"},
    {"category": "nonsense", "question": "What breaks first?"},
]
EVAL = {"followUp": "Consider rate limits.", "feedback": "Solid answer.", "teach": "Read about token rotation."}


def make_groq(fake_groq):
    def reply(kw):
        text = kw["messages"][-1]["content"]
        if kw["max_tokens"] == 2000:
            return json.dumps(QUESTIONS)
        if kw["max_tokens"] == 800:
            return json.dumps(EVAL)
        if kw["max_tokens"] == 1800:
            return "FINAL REPORT"
        return "analysis"

    fake_groq.reply = reply


async def _ready(c, fake_groq, fake_embeddings):
    make_groq(fake_groq)
    await upload(c)


async def test_full_interview_lifecycle(auth, fake_groq, fake_embeddings, db):
    c, _, _ = auth
    await _ready(c, fake_groq, fake_embeddings)

    assert (await c.get("/api/interview/session")).json() == {"hasInterview": False}
    start = (await c.post("/api/interview/start")).json()
    assert start["status"] == "in_progress" and start["progress"] == {"current": 0, "total": 3}
    assert start["currentQuestion"] == {"id": "q1", "category": "security", "question": "Why did you pick JWT?"}
    assert start["transcript"] == [] and start["report"] is None

    calls = len(fake_groq.calls)
    again = (await c.post("/api/interview/start")).json()
    assert again == start and len(fake_groq.calls) == calls  # resume: no new AI call, same questions

    r1 = (await c.post("/api/interview/answer", json={"answer": "  Stateless and simple.  "})).json()
    assert r1["feedback"] == "Solid answer." and r1["teach"] == "Read about token rotation." and r1["followUp"] == "Consider rate limits."
    assert r1["isLastQuestion"] is False and r1["nextQuestion"]["id"] == "q2" and r1["progress"] == {"current": 1, "total": 3}
    sess = (await c.get("/api/interview/session")).json()
    assert sess["hasInterview"] and sess["transcript"][0]["answer"] == "Stateless and simple." and sess["currentQuestion"]["id"] == "q2"

    await c.post("/api/interview/answer", json={"answer": "Add caching."})
    last = (await c.post("/api/interview/answer", json={"answer": "The database."})).json()
    assert last["isLastQuestion"] is True and last["nextQuestion"] is None and last["status"] == "ready_for_report"
    assert (await c.post("/api/interview/answer", json={"answer": "more"})).json() == {"error": "No more questions in this interview."}

    report = (await c.post("/api/interview/finish")).json()
    assert report == {"report": "FINAL REPORT"}
    n = len(fake_groq.calls)
    assert (await c.post("/api/interview/finish")).json() == {"report": "FINAL REPORT"} and len(fake_groq.calls) == n  # cached
    done = (await c.get("/api/interview/session")).json()
    assert done["status"] == "completed" and done["report"] == "FINAL REPORT" and done["currentQuestion"] is None
    assert (await c.post("/api/interview/answer", json={"answer": "late"})).json() == {"error": "This interview is already complete."}

    assert (await c.delete("/api/interview/session")).json() == {"success": True}
    assert (await c.get("/api/interview/session")).json() == {"hasInterview": False}


async def test_unknown_category_is_normalised(auth, fake_groq, fake_embeddings):
    c, _, _ = auth
    await _ready(c, fake_groq, fake_embeddings)
    await c.post("/api/interview/start")
    await c.post("/api/interview/answer", json={"answer": "a"})
    await c.post("/api/interview/answer", json={"answer": "b"})
    q3 = (await c.get("/api/interview/session")).json()["currentQuestion"]
    assert q3["category"] == "architecture"  # "nonsense" -> safe default


async def test_guard_rails(auth, fake_groq, fake_embeddings):
    c, _, _ = auth
    assert (await c.post("/api/interview/start")).json() == {"error": "No project loaded. Please upload a project first."}
    assert (await c.post("/api/interview/answer", json={"answer": "x"})).json() == {"error": "No interview in progress. Start one first."}
    assert (await c.post("/api/interview/finish")).json() == {"error": "No interview found."}
    await _ready(c, fake_groq, fake_embeddings)
    await c.post("/api/interview/start")
    r = await c.post("/api/interview/answer", json={"answer": "   "})
    assert r.status_code == 400 and r.json() == {"error": "Answer must be 1–4000 characters"}
    assert (await c.post("/api/interview/answer", json={"answer": "x" * 4001})).status_code == 400
    assert (await c.post("/api/interview/finish")).json() == {"error": "Answer at least one question before requesting a report."}


async def test_reupload_discards_stale_interview(auth, fake_groq, fake_embeddings, db):
    """Bug found in the Node version: re-uploading kept the old interview (same ProjectSession id)."""
    c, _, _ = auth
    await _ready(c, fake_groq, fake_embeddings)
    await c.post("/api/interview/start")
    await c.post("/api/interview/answer", json={"answer": "mine"})
    await upload(c)  # a new project replaces the old one
    assert (await c.get("/api/interview/session")).json() == {"hasInterview": False}
    assert (await db.execute(select(func.count()).select_from(InterviewSession))).scalar_one() == 0
    fresh = (await c.post("/api/interview/start")).json()
    assert fresh["progress"]["current"] == 0 and fresh["transcript"] == []


async def test_clearing_project_cascades_to_interview(auth, fake_groq, fake_embeddings, db):
    c, _, _ = auth
    await _ready(c, fake_groq, fake_embeddings)
    await c.post("/api/interview/start")
    await c.delete("/api/project/session")
    assert (await db.execute(select(func.count()).select_from(InterviewSession))).scalar_one() == 0  # ON DELETE CASCADE


async def test_model_returning_garbage_never_blocks_the_interview(auth, fake_groq, fake_embeddings):
    c, _, _ = auth
    fake_groq.reply = lambda kw: "no json here"
    await upload(c)
    start = (await c.post("/api/interview/start")).json()
    assert start["progress"]["total"] == 1 and "structured" in start["currentQuestion"]["question"]
    r = (await c.post("/api/interview/answer", json={"answer": "whatever"})).json()
    assert r["feedback"].startswith("Could not generate detailed feedback") and r["followUp"] == "Let's move to the next question."
    assert r["isLastQuestion"] is True
