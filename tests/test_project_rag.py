import io
import json
import zipfile
from pathlib import Path

from sqlalchemy import func, select, update

from app.models import CodeChunk, IngestedFileHash, ProjectSession
from app.routers import project as project_router
from app.services import rag_engine
from tests.conftest import fake_embedding

SAMPLE_ZIP = (Path(__file__).parent / "fixtures" / "sample_project.zip").read_bytes()


def upload(client, data: bytes = SAMPLE_ZIP, name: str = "demo-app.zip", mime: str = "application/zip"):
    return client.post("/api/project/upload", files={"project": (name, data, mime)})


def modified_zip(path_in_zip: str, new_content: str) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(SAMPLE_ZIP)) as src, zipfile.ZipFile(out, "w") as dst:
        for info in src.infolist():
            dst.writestr(info, new_content if info.filename == path_in_zip else src.read(info))
    return out.getvalue()


def smart_groq(kw):
    """Plays all three model roles used by the project flow."""
    if kw["model"] == "openai/gpt-oss-20b":  # re-ranker: prefer the first candidate
        return json.dumps([{"index": 0, "score": 10}, {"index": 1, "score": 5}])
    return "MODEL ANSWER"


async def _chunk_count(db):
    return (await db.execute(select(func.count()).select_from(CodeChunk))).scalar_one()


async def test_upload_analyses_then_indexes_in_background(auth, fake_groq, fake_embeddings, db):
    c, user, _ = auth
    fake_groq.reply = "PROJECT OVERVIEW"
    r = await upload(c)
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True and body["projectName"] == "demo-app" and body["analysis"] == "PROJECT OVERVIEW"
    assert body["ragStatus"] == "pending"  # the response reports the state at the time it was sent
    assert body["stats"]["total"] == 17 and "└── " in body["fileTree"] and "app.js" in body["fileTree"]
    assert "node_modules" not in body["fileTree"] and ".env\n" not in body["fileTree"]

    s = (await c.get("/api/project/session")).json()  # ...and by now the background task has finished
    assert s["hasProject"] and s["ragStatus"] == "ready" and s["ragChunkCount"] == await _chunk_count(db) > 0
    assert s["history"] == [] and s["messageCount"] == 0 and s["analysis"] == "PROJECT OVERVIEW"
    chunk = (await db.execute(select(CodeChunk).limit(1))).scalar_one()
    assert chunk.session_id == str(user["id"]) and len(chunk.embedding) == 64
    assert fake_groq.calls[0]["max_tokens"] == 1300  # analysis call


async def test_ask_uses_retrieved_chunks_and_persists_history(auth, fake_groq, fake_embeddings, db):
    c, _, _ = auth
    fake_groq.reply = smart_groq
    await upload(c)
    r = await c.post("/api/project/ask", json={"message": "how does the express app route work?"})
    assert r.status_code == 200 and r.json() == {"response": "MODEL ANSWER", "projectName": "demo-app"}
    answer_call = [x for x in fake_groq.calls if x["model"].endswith("120b")][-1]
    context = answer_call["messages"][1]["content"]
    assert "RELEVANT CODE SECTIONS" in context and "--- FILE: app.js (relevance:" in context  # the right file was retrieved
    assert answer_call["messages"][-1] == {"role": "user", "content": "how does the express app route work?"}
    s = (await c.get("/api/project/session")).json()
    assert [m["role"] for m in s["history"]] == ["user", "assistant"] and s["messageCount"] == 1

    await c.post("/api/project/ask", json={"message": "second question about helper sum"})
    followup = [x for x in fake_groq.calls if x["model"].endswith("120b")][-1]["messages"]
    assert {"role": "assistant", "content": "MODEL ANSWER"} in followup  # earlier turns are sent as history


async def test_history_is_capped_at_20_messages(auth, fake_groq, fake_embeddings, db):
    c, _, _ = auth
    fake_groq.reply = smart_groq
    await upload(c)
    for i in range(12):
        assert (await c.post("/api/project/ask", json={"message": f"question number {i} about app"})).status_code == 200
    history = (await c.get("/api/project/session")).json()["history"]
    assert len(history) == 20 and history[0]["content"] == "question number 2 about app"


async def test_ask_guard_rails(auth, fake_groq, fake_embeddings, db):
    c, user, _ = auth
    assert (await c.post("/api/project/ask", json={"message": "hi"})).json() == {"error": "No project loaded. Please upload a project ZIP first."}
    fake_groq.reply = smart_groq
    await upload(c)
    assert (await c.post("/api/project/ask", json={"message": "   "})).json() == {"error": "No message provided"}
    assert (await c.post("/api/project/ask", json={})).json() == {"error": "No message provided"}
    long = await c.post("/api/project/ask", json={"message": "x" * 8001})
    assert long.status_code == 400 and long.json() == {"error": "Message too long (max 8000 characters)"}

    await db.execute(update(ProjectSession).values(rag_status="pending"))
    await db.commit()
    r = await c.post("/api/project/ask", json={"message": "hello there"})
    assert r.status_code == 423 and r.json()["ragStatus"] == "pending" and "still being indexed" in r.json()["error"]
    await db.execute(update(ProjectSession).values(rag_status="failed"))
    await db.commit()
    r = await c.post("/api/project/ask", json={"message": "hello there"})
    assert r.status_code == 500 and r.json()["ragStatus"] == "failed"

    await db.execute(update(ProjectSession).values(rag_status="ready"))
    await db.execute(CodeChunk.__table__.delete())
    await db.commit()
    r = await c.post("/api/project/ask", json={"message": "hello there"})
    assert r.status_code == 404 and r.json() == {"error": "No relevant content found for that question in the indexed project."}


async def test_reupload_is_incremental(auth, fake_groq, fake_embeddings, db):
    c, _, _ = auth
    fake_groq.reply = "ok"
    await upload(c)
    first_calls = sum(len(b) for b in fake_embeddings)
    first_chunks = await _chunk_count(db)
    assert first_calls == first_chunks

    fake_embeddings.clear()
    await upload(c)  # identical project: nothing to embed
    assert fake_embeddings == [] and await _chunk_count(db) == first_chunks

    await upload(c, modified_zip("demo-app/app.js", "const changed = true;\nfunction brandNew() {\n  return 1;\n}\n"))
    texts = [t for batch in fake_embeddings for t in batch]
    assert texts and all(t.startswith("File: app.js") for t in texts)  # only the edited file was re-embedded
    contents = (await db.execute(select(CodeChunk.content).where(CodeChunk.file_path == "app.js"))).scalars().all()
    assert any("brandNew" in x for x in contents) and not any("express" in x for x in contents)  # old chunks replaced

    s = (await c.get("/api/project/session")).json()
    assert s["ragStatus"] == "ready" and s["ragChunkCount"] == await _chunk_count(db)


async def test_removed_files_lose_their_chunks(auth, fake_groq, fake_embeddings, db):
    c, _, _ = auth
    fake_groq.reply = "ok"
    await upload(c)
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(SAMPLE_ZIP)) as src, zipfile.ZipFile(out, "w") as dst:
        for info in src.infolist():
            if info.filename != "demo-app/src/index.ts":
                dst.writestr(info, src.read(info))
    await upload(c, out.getvalue())
    paths = (await db.execute(select(CodeChunk.file_path).distinct())).scalars().all()
    assert "src/index.ts" not in paths and "app.js" in paths
    hashes = (await db.execute(select(IngestedFileHash.file_path))).scalars().all()
    assert "src/index.ts" not in hashes


async def test_upload_validation_errors(auth, fake_groq, fake_embeddings, monkeypatch):
    c, _, _ = auth
    assert (await c.post("/api/project/upload")).json() == {"error": "No ZIP file uploaded"}
    r = await upload(c, b"plain text", "notes.txt", "text/plain")
    assert r.status_code == 400 and r.json() == {"error": "Only ZIP files are accepted"}
    r = await upload(c, b"this is not a zip", "broken.zip")
    assert r.status_code == 400 and r.json() == {"error": "Failed to parse ZIP file. Make sure it is a valid ZIP archive."}
    empty = io.BytesIO()
    with zipfile.ZipFile(empty, "w") as z:
        z.writestr("proj/image.png", b"\x89PNG\x00\x01")
    r = await upload(c, empty.getvalue())
    assert r.status_code == 400 and r.json()["error"].startswith("No readable source files")
    monkeypatch.setattr(project_router, "MAX_UPLOAD_BYTES", 1000)
    r = await upload(c)
    assert r.status_code == 413 and r.json() == {"error": "File too large (max 50MB)"}
    assert fake_groq.calls == []  # nothing reached the (paid) model


async def test_upload_requires_auth(client):
    r = await upload(client)
    assert r.status_code == 401


async def test_indexing_failure_is_recorded_not_raised(auth, fake_groq, monkeypatch, db):
    c, _, _ = auth
    fake_groq.reply = "ok"

    async def boom(texts):
        raise RuntimeError("ollama is down")

    monkeypatch.setattr(rag_engine, "get_embeddings_batch", boom)
    r = await upload(c)
    assert r.status_code == 200  # the user still gets the analysis
    assert (await c.get("/api/project/session")).json()["ragStatus"] == "failed"


async def test_clear_project_removes_everything(auth, fake_groq, fake_embeddings, db):
    c, _, _ = auth
    fake_groq.reply = "ok"
    await upload(c)
    assert await _chunk_count(db) > 0
    assert (await c.delete("/api/project/session")).json() == {"success": True}
    assert (await c.get("/api/project/session")).json() == {"hasProject": False}
    assert await _chunk_count(db) == 0
    assert (await db.execute(select(func.count()).select_from(IngestedFileHash))).scalar_one() == 0


async def test_projects_are_isolated_between_users(client, fake_groq, fake_embeddings, db):
    from tests.conftest import signup
    fake_groq.reply = smart_groq
    await signup(client, "one@example.com")
    await upload(client)
    client.cookies.clear()
    await signup(client, "two@example.com")
    assert (await client.get("/api/project/session")).json() == {"hasProject": False}
    r = await client.post("/api/project/ask", json={"message": "what is in app"})
    assert r.status_code == 404  # user two cannot retrieve user one's chunks


# ── retrieval internals ──────────────────────────────────────────────────────
async def _seed_chunks(db, user_id, rows):
    for path, content in rows:
        db.add(CodeChunk(session_id=str(user_id), file_path=path, content=content, embedding=fake_embedding(f"File: {path}\n{content}")))
    await db.commit()


async def test_retrieval_ranks_semantically_and_caps_chunks_per_file(auth, fake_embeddings, fake_groq, db):
    _, user, _ = auth
    rows = [("auth.js", f"login password token jwt verify user {i}") for i in range(8)] + [("db.js", "database connection pool query"), ("ui.js", "button render component css")]
    await _seed_chunks(db, user["id"], rows)
    out = await rag_engine.retrieve_relevant_chunks(db, user["id"], "how does login and jwt token verification work", top_k=6, use_reranking=False)
    assert len(out) == 2 or len(out) <= 6
    assert out[0]["filePath"] == "auth.js"
    assert sum(1 for x in out if x["filePath"] == "auth.js") <= 2  # diversity cap without re-ranking
    assert all(set(x) == {"filePath", "content", "score"} for x in out)
    assert out == sorted(out, key=lambda x: x["score"], reverse=True)


async def test_keyword_boost_and_dimension_mismatch_are_handled(auth, fake_embeddings, db):
    _, user, _ = auth
    await _seed_chunks(db, user["id"], [("a.js", "alpha beta"), ("b.js", "gamma delta")])
    db.add(CodeChunk(session_id=str(user["id"]), file_path="old.js", content="legacy vector", embedding=[0.1, 0.2, 0.3]))
    await db.commit()  # a vector of another size (e.g. produced by a different embedding model) must not crash retrieval
    out = await rag_engine.retrieve_relevant_chunks(db, user["id"], "alpha", top_k=6, use_reranking=False)
    assert "old.js" not in [x["filePath"] for x in out] and out[0]["filePath"] == "a.js"
    assert rag_engine.extract_keywords("How does the Login-flow work? JWT!") == ["login", "flow", "jwt"]


async def test_rerank_reorders_and_falls_back(auth, fake_embeddings, fake_groq, db):
    _, user, _ = auth
    cands = [{"filePath": f"f{i}.js", "content": f"content {i}", "score": 1 - i / 100} for i in range(10)]
    fake_groq.reply = json.dumps([{"index": 7, "score": 10}, {"index": 7, "score": 9}, {"index": 99, "score": 8}, {"index": -1, "score": 8}, {"index": 3, "score": 6}])
    out = await rag_engine.rerank_chunks("q", cands, 3)
    assert [x["filePath"] for x in out] == ["f7.js", "f3.js"]  # duplicates / out-of-range indices dropped
    fake_groq.reply = "total nonsense"
    assert await rag_engine.rerank_chunks("q", cands, 3) == cands[:3]  # unparseable -> keep vector order
    fake_groq.reply = RuntimeError("groq down")
    assert await rag_engine.rerank_chunks("q", cands, 3) == cands[:3]  # failure -> keep vector order
    assert await rag_engine.rerank_chunks("q", cands[:2], 3) == cands[:2]  # nothing to re-rank
    assert fake_groq.calls[0]["model"] == "openai/gpt-oss-20b" and fake_groq.calls[0]["temperature"] == 0


async def test_retrieval_gives_identical_results_without_numpy(auth, fake_embeddings, db, monkeypatch):
    """numpy is optional (no wheel on some Python versions): the pure-Python path must match it."""
    _, user, _ = auth
    await _seed_chunks(db, user["id"], [("a.js", "alpha beta gamma"), ("b.js", "gamma delta epsilon"), ("c.js", "zeta eta theta")])
    with_np = await rag_engine.retrieve_relevant_chunks(db, user["id"], "gamma alpha", top_k=3, use_reranking=False)
    monkeypatch.setattr(rag_engine, "np", None)
    without_np = await rag_engine.retrieve_relevant_chunks(db, user["id"], "gamma alpha", top_k=3, use_reranking=False)
    assert [r["filePath"] for r in with_np] == [r["filePath"] for r in without_np]
    for x, y in zip(with_np, without_np):
        assert abs(x["score"] - y["score"]) < 1e-9
    assert rag_engine.semantic_scores([[0, 0], [1, 0]], [1, 0]) == [0.0, 1.0]
