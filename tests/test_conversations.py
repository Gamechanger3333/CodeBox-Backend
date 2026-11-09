import uuid

from sqlalchemy import func, select

from app.models import Conversation, Message
from tests.conftest import signup


async def _start(c) -> str:
    r = await c.post("/api/start_conversation")
    assert r.status_code == 200
    return r.json()["conversationId"]


async def test_requires_auth(client):
    for method, path in [("get", "/api/latest_conversation"), ("post", "/api/start_conversation"), ("post", "/api/send_message"),
                         ("get", "/api/getAllConversationIDs"), ("post", "/api/analyze_code")]:
        r = await getattr(client, method)(path)
        assert r.status_code == 401 and r.json() == {"error": "Token missing"}, path


async def test_start_latest_and_empty_state(auth):
    c, _, _ = auth
    assert (await c.get("/api/latest_conversation")).status_code == 404
    assert (await c.get("/api/latest_conversation")).json() == {"error": "No conversations found"}
    cid = await _start(c)
    uuid.UUID(cid)
    assert (await c.get("/api/latest_conversation")).json() == {"conversationId": cid}


async def test_send_message_saves_both_messages_and_titles_first_message(auth, fake_groq, db):
    c, _, _ = auth
    cid = await _start(c)
    fake_groq.reply = lambda kw: "Short Title" if kw["max_tokens"] == 20 else "Here is the answer"
    r = await c.post("/api/send_message", json={"conversationId": cid, "message": "  How do I reverse a list?  "})
    assert r.status_code == 200
    assert r.json() == {"response": "Here is the answer", "title": "Short Title"}

    msgs = (await db.execute(select(Message).where(Message.conversation_id == cid).order_by(Message.created_at))).scalars().all()
    assert [(m.sender, m.content) for m in msgs] == [("user", "How do I reverse a list?"), ("bot", "Here is the answer")]
    assert msgs[0].created_at < msgs[1].created_at  # deterministic ordering

    r2 = await c.post("/api/send_message", json={"conversationId": cid, "message": "And sort it?"})
    assert r2.json()["title"] == "Short Title"  # second message does NOT regenerate the title
    assert sum(1 for call in fake_groq.calls if call["max_tokens"] == 20) == 1


async def test_context_sent_to_model_is_the_LATEST_30_messages(auth, fake_groq, db):
    c, _, _ = auth
    cid = await _start(c)
    from datetime import timedelta
    from app.models import utcnow
    base = utcnow() - timedelta(hours=1)
    for i in range(40):  # 40 historic messages: m0 .. m39
        db.add(Message(conversation_id=cid, sender="user" if i % 2 == 0 else "bot", content=f"m{i}", created_at=base + timedelta(seconds=i)))
    await db.commit()
    await c.post("/api/send_message", json={"conversationId": cid, "message": "newest question"})
    sent = [m["content"] for m in fake_groq.calls[0]["messages"][1:]]  # [0] is the system prompt
    assert len(sent) == 30
    assert sent[-1] == "newest question" and sent[-2] == "m39"  # recent history is included
    assert "m0" not in sent and "m10" not in sent  # the old Node version sent the OLDEST 30 instead


async def test_title_failure_never_breaks_the_reply(auth, fake_groq):
    c, _, _ = auth
    cid = await _start(c)
    fake_groq.reply = lambda kw: RuntimeError("title model down") if kw["max_tokens"] == 20 else "answer"
    r = await c.post("/api/send_message", json={"conversationId": cid, "message": "hi"})
    assert r.status_code == 200 and r.json()["response"] == "answer" and r.json()["title"] is None


async def test_send_message_validation_and_ownership(client, fake_groq):
    _, _ = await signup(client, "a@example.com")
    cid = await _start(client)
    r = await client.post("/api/send_message", json={"conversationId": "not-a-uuid", "message": "x"})
    assert r.status_code == 400 and r.json() == {"error": "Invalid conversationId"}
    r = await client.post("/api/send_message", json={"conversationId": cid, "message": "   "})
    assert r.json() == {"error": "Message must be 1–8000 characters"}
    r = await client.post("/api/send_message", json={"conversationId": cid, "message": "x" * 8001})
    assert r.status_code == 400

    client.cookies.clear()
    await signup(client, "b@example.com")  # a different user
    r = await client.post("/api/send_message", json={"conversationId": cid, "message": "hello"})
    assert r.status_code == 404 and r.json() == {"error": "Conversation not found"}  # cannot touch someone else's chat
    assert fake_groq.calls == []


async def test_ai_unavailable_is_503_with_safe_message(auth):
    c, _, _ = auth  # GROQ_API_KEY is empty in tests and groq_client is NOT faked here
    cid = await _start(c)
    r = await c.post("/api/send_message", json={"conversationId": cid, "message": "hi"})
    assert r.status_code == 503
    assert r.json() == {"status": "error", "message": "AI features are temporarily unavailable. Please try again later."}


async def test_get_conversation_pin_title_delete_flow(auth, fake_groq):
    c, _, _ = auth
    cid = await _start(c)
    await c.post("/api/send_message", json={"conversationId": cid, "message": "hello"})
    conv = (await c.get(f"/api/get_conversation/{cid}")).json()["conversation"]
    assert conv["id"] == cid and [m["sender"] for m in conv["messages"]] == ["user", "bot"]
    assert conv["isPinned"] is False and conv["createdAt"].endswith("Z")

    assert (await c.patch(f"/api/conversation/{cid}/pin")).json() == {"isPinned": True}
    assert (await c.patch(f"/api/conversation/{cid}/pin")).json() == {"isPinned": False}
    assert (await c.patch(f"/api/conversation/{cid}/title", json={"title": "  My title  "})).json() == {"title": "My title"}
    r = await c.patch(f"/api/conversation/{cid}/title", json={"title": ""})
    assert r.status_code == 400 and r.json() == {"error": "Title must be 1–100 characters"}

    assert (await c.get("/api/get_conversation/xyz")).json() == {"error": "conversationId must be a valid UUID"}
    assert (await c.get(f"/api/get_conversation/{uuid.uuid4()}")).status_code == 404

    r = await c.delete(f"/api/conversation/{cid}")
    assert r.json() == {"success": True, "message": "Conversation deleted"}
    assert (await c.get(f"/api/get_conversation/{cid}")).status_code == 404


async def test_delete_removes_messages_too(auth, fake_groq, db):
    c, _, _ = auth
    cid = await _start(c)
    await c.post("/api/send_message", json={"conversationId": cid, "message": "hello"})
    await c.delete(f"/api/conversation/{cid}")
    assert (await db.execute(select(func.count()).select_from(Message))).scalar_one() == 0
    assert (await db.execute(select(func.count()).select_from(Conversation))).scalar_one() == 0


async def test_other_users_cannot_pin_rename_delete_or_read(client, fake_groq):
    await signup(client, "owner@example.com")
    cid = await _start(client)
    client.cookies.clear()
    await signup(client, "intruder@example.com")
    for call in (client.get(f"/api/get_conversation/{cid}"), client.patch(f"/api/conversation/{cid}/pin"),
                 client.patch(f"/api/conversation/{cid}/title", json={"title": "x"}), client.delete(f"/api/conversation/{cid}")):
        assert (await call).status_code == 404


async def test_get_all_ids_order_pagination_and_lenient_params(auth, db):
    c, user, _ = auth
    ids = []
    for _ in range(4):
        ids.append(await _start(c))
    await c.patch(f"/api/conversation/{ids[0]}/pin")  # oldest, but pinned -> first
    rows = (await c.get("/api/getAllConversationIDs")).json()
    assert [r["id"] for r in rows] == [ids[0], ids[3], ids[2], ids[1]]
    assert set(rows[0]) == {"id", "title", "createdAt", "isPinned"} and rows[0]["isPinned"] is True

    page2 = (await c.get("/api/getAllConversationIDs?page=2&limit=3")).json()
    assert [r["id"] for r in page2] == [ids[1]]
    for q in ("?page=abc&limit=0", "?page=0", "?limit=-5"):  # invalid values fall back to defaults, as before
        assert len((await c.get("/api/getAllConversationIDs" + q)).json()) == 4


async def test_analyze_code(auth, fake_groq):
    c, _, _ = auth
    fake_groq.reply = "Looks fine"
    r = await c.post("/api/analyze_code", json={"code": "print(1)", "filename": "a.py"})
    assert r.json() == {"analysis": "Looks fine"}
    assert "a.py" in fake_groq.calls[0]["messages"][1]["content"]
    r = await c.post("/api/analyze_code", json={"code": "print(1)"})
    assert "code.txt" in fake_groq.calls[1]["messages"][1]["content"]
    assert (await c.post("/api/analyze_code", json={"code": ""})).json() == {"error": "Code must be 1–8000 characters"}
    fake_groq.reply = None  # empty model answer -> fallback text
    assert (await c.post("/api/analyze_code", json={"code": "x"})).json() == {"analysis": "Analysis failed."}
