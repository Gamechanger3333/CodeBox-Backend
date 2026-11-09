"""Test setup.

Tests run against a REAL PostgreSQL database (set TEST_DATABASE_URL, falls back to
DATABASE_URL). Only the AI/network edges are faked:
  * Groq chat completions  -> `fake_groq` fixture
  * embeddings (Ollama)    -> deterministic bag-of-words vectors
  * Resend e-mail          -> captured in a list
WARNING: tables are TRUNCATED between tests - never point this at a database you care about.
"""
import hashlib
import os
import re

os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL", "postgresql://app:app@localhost:5432/codebox")
os.environ.setdefault("JWT_SECRET", "node-compat-secret")
os.environ["JWT_SECRET"] = "node-compat-secret"
os.environ["RATE_LIMIT_ENABLED"] = "false"
os.environ["NODE_ENV"] = "test"
os.environ["GROQ_API_KEY"] = ""
os.environ["RESEND_API_KEY"] = ""
os.environ["FRONTEND_URL"] = "http://localhost:3000"

import httpx  # noqa: E402
import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.database import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.middleware import api_limiter, auth_limiter  # noqa: E402
from app.models import Base  # noqa: E402
from app.services import email_service, groq_client, rag_engine  # noqa: E402

DIM = 64


def fake_embedding(text_: str) -> list[float]:
    """Bag-of-words hashed into DIM buckets: similar words => similar vectors, fully deterministic."""
    vec = [0.0] * DIM
    for word in re.findall(r"[a-z0-9]+", text_.lower()):
        vec[int(hashlib.md5(word.encode()).hexdigest(), 16) % DIM] += 1.0
    return vec


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _schema():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


@pytest_asyncio.fixture(autouse=True)
async def _clean_db():
    async with engine.begin() as conn:
        await conn.execute(
            text('TRUNCATE "User","Conversation","Message","Snippet","ProjectSession","InterviewSession","CodeChunk","IngestedFileHash" RESTART IDENTITY CASCADE')
        )
    api_limiter.reset()
    auth_limiter.reset()
    yield


@pytest_asyncio.fixture
async def client():
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    # https:// so the Secure auth cookie is sent back by the cookie jar, like in a real browser
    async with httpx.AsyncClient(transport=transport, base_url="https://testserver") as c:
        yield c


@pytest_asyncio.fixture
async def db():
    async with SessionLocal() as session:
        yield session


class FakeGroq:
    """Records every call; `.reply` can be a string or a callable(kwargs) -> str."""

    def __init__(self):
        self.calls: list[dict] = []
        self.reply = "AI reply"

    async def __call__(self, **kwargs):
        self.calls.append(kwargs)
        r = self.reply(kwargs) if callable(self.reply) else self.reply
        if isinstance(r, Exception):
            raise r
        return r


@pytest.fixture
def fake_groq(monkeypatch):
    fake = FakeGroq()
    monkeypatch.setattr(groq_client, "chat_completion", fake)
    return fake


@pytest.fixture
def fake_embeddings(monkeypatch):
    calls: list[list[str]] = []

    async def _batch(texts):
        calls.append(list(texts))
        return [fake_embedding(t) for t in texts]

    monkeypatch.setattr(rag_engine, "get_embeddings_batch", _batch)
    return calls


@pytest.fixture
def sent_emails(monkeypatch):
    sent: list[dict] = []

    async def _send(email, name, otp):
        sent.append({"email": email, "name": name, "otp": otp})
        return {"id": "fake"}

    monkeypatch.setattr(email_service, "send_password_reset_otp", _send)
    return sent


async def signup(client, email="user@example.com", name="Test User", password="Passw0rd!x"):
    r = await client.post("/api/signup", json={"name": name, "email": email, "password": password, "passwordConfirm": password})
    assert r.status_code == 201, r.text
    return r.json()["data"]["user"], r.json()["token"]


@pytest_asyncio.fixture
async def auth(client):
    """A logged-in client (cookie jar holds the token). Returns (client, user, token)."""
    user, token = await signup(client)
    return client, user, token
