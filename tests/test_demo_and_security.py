import asyncio

from sqlalchemy import func, select

from app.main import app
from app.middleware import api_limiter, auth_limiter
from app.models import Conversation, Message, Snippet, User
from app.services import demo_user
from app.config import get_settings


async def test_seed_and_demo_login_resets_data(client, db, fake_groq):
    user = await demo_user.ensure_demo_user_seeded(db)
    assert user.email == "demo@codebox.com" and user.is_verified
    n_conv = (await db.execute(select(func.count()).select_from(Conversation).where(Conversation.user_id == user.id))).scalar_one()
    n_snip = (await db.execute(select(func.count()).select_from(Snippet).where(Snippet.user_id == user.id))).scalar_one()
    assert (n_conv, n_snip) == (5, 16)

    r = await client.post("/api/login", json={"email": "demo@codebox.com", "password": get_settings().demo_user_password_seed})
    assert r.status_code == 200
    convs = (await client.get("/api/getAllConversationIDs")).json()
    assert len(convs) == 5 and [c["isPinned"] for c in convs][0] is True  # pinned demo chats first

    # a visitor trashes the demo account...
    await client.post("/api/snippets", json={"title": "mine", "code": "x", "language": "js"})
    await client.delete(f"/api/conversation/{convs[0]['id']}")
    assert len((await client.get("/api/getAllConversationIDs")).json()) == 4
    # ...the next demo login restores the pristine state
    client.cookies.clear()
    await client.post("/api/login", json={"email": "DEMO@codebox.com", "password": get_settings().demo_user_password_seed})
    assert len((await client.get("/api/getAllConversationIDs")).json()) == 5
    assert len((await client.get("/api/snippets")).json()["snippets"]) == 16

    first_conv = (await client.get("/api/getAllConversationIDs")).json()[0]["id"]
    msgs = (await client.get(f"/api/get_conversation/{first_conv}")).json()["conversation"]["messages"]
    assert len(msgs) >= 2 and msgs[0]["sender"] == "user"  # chat order preserved (user first)


async def test_seed_is_idempotent(db):
    a = await demo_user.ensure_demo_user_seeded(db)
    b = await demo_user.ensure_demo_user_seeded(db)
    assert a.id == b.id
    assert (await db.execute(select(func.count()).select_from(User))).scalar_one() == 1
    assert (await db.execute(select(func.count()).select_from(Snippet))).scalar_one() == 16


async def test_cors_allows_only_the_frontend_origin_with_credentials(client):
    ok = await client.options("/api/login", headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "POST",
                                                     "Access-Control-Request-Headers": "content-type"})
    assert ok.status_code == 200
    assert ok.headers["access-control-allow-origin"] == "http://localhost:3000" and ok.headers["access-control-allow-credentials"] == "true"
    evil = await client.options("/api/login", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in evil.headers
    # error responses keep the CORS headers too (otherwise the browser would hide the real error)
    err = await client.get("/api/check_authentication", headers={"Origin": "http://localhost:3000"})
    assert err.status_code == 401 and err.headers["access-control-allow-origin"] == "http://localhost:3000"


async def test_unhandled_errors_are_json_with_cors_and_no_leak_in_production(client, monkeypatch):
    from app.routers import conversations

    async def boom(*a, **k):
        raise RuntimeError("secret db password leaked?")

    await client.post("/api/signup", json={"name": "x", "email": "x@example.com", "password": "Passw0rd!x", "passwordConfirm": "Passw0rd!x"})
    monkeypatch.setattr(conversations.conversation_service, "start_conversation", boom)
    r = await client.post("/api/start_conversation", headers={"Origin": "http://localhost:3000"})
    assert r.status_code == 500 and r.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert r.json() == {"status": "error", "message": "secret db password leaked?"}  # development: message visible

    monkeypatch.setattr(get_settings(), "node_env", "production")
    r = await client.post("/api/start_conversation")
    assert r.status_code == 500 and r.json() == {"status": "error", "message": "Something went wrong. Please try again."}


async def test_rate_limiting_auth_and_api(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "rate_limit_enabled", True)
    auth_limiter.reset(); api_limiter.reset()
    body = {"email": "nobody@example.com", "password": "whatever1"}
    codes = [(await client.post("/api/login", json=body)).status_code for _ in range(21)]
    assert codes[:20] == [401] * 20 and codes[20] == 429
    r = await client.post("/api/login", json=body)
    assert r.json() == {"status": "error", "message": "Too many requests, please try again later."} and int(r.headers["retry-after"]) > 0

    auth_limiter.reset(); api_limiter.reset()
    codes = [(await client.get("/api/latest_conversation")).status_code for _ in range(61)]
    assert codes[:60] == [401] * 60 and codes[60] == 429
    assert (await client.get("/health")).status_code == 200  # health is outside /api: never throttled
    # behind the proxy the budget is per REAL client IP (last X-Forwarded-For entry)
    fresh = await client.get("/api/latest_conversation", headers={"X-Forwarded-For": "1.2.3.4, 5.6.7.8"})
    assert fresh.status_code == 401  # 5.6.7.8 has its own, untouched budget
    assert (await client.get("/api/latest_conversation")).status_code == 429  # the original client is still throttled
