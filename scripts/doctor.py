"""One-command health check for your local setup.   python -m scripts.doctor

Checks: Python version, installed packages, .env keys, database (TCP -> SSL -> login -> tables), demo user,
embeddings provider and the Groq key. Prints NO secrets - only host names and OK / PROBLEM lines.
Paste the whole output when asking for help.
"""
from __future__ import annotations

import asyncio
import importlib
import importlib.metadata as md
import socket
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

problems: list[str] = []


def ok(msg: str) -> None:
    print(f"  [ OK ]  {msg}")


def warn(msg: str) -> None:
    print(f"  [WARN]  {msg}")


def bad(msg: str, fix: str = "") -> None:
    problems.append(msg)
    print(f"  [FAIL]  {msg}")
    if fix:
        print(f"          -> {fix}")


def section(title: str) -> None:
    print(f"\n{title}")


def check_python() -> None:
    section("1) Python")
    v = sys.version_info
    ok(f"Python {v.major}.{v.minor}.{v.micro} ({sys.executable})")
    if (v.major, v.minor) != (3, 12):
        warn("This project was tested on Python 3.12. Other versions usually work, but 3.12 is the safe choice.")
    if ".venv" not in sys.executable and "venv" not in sys.executable.lower():
        bad("You are NOT inside the project's virtual environment", r"run  .venv\Scripts\activate  and use  python -m ...")


def check_packages() -> None:
    section("2) Packages (requirements.txt)")
    wanted = {"fastapi": "fastapi", "uvicorn": "uvicorn", "sqlalchemy": "SQLAlchemy", "asyncpg": "asyncpg",
              "pydantic_settings": "pydantic-settings", "jwt": "PyJWT", "bcrypt": "bcrypt", "httpx": "httpx",
              "groq": "groq", "multipart": "python-multipart"}
    missing = []
    for module, dist in wanted.items():
        try:
            importlib.import_module(module)
            ok(f"{dist} {md.version(dist)}")
        except Exception:  # noqa: BLE001
            missing.append(dist)
            bad(f"{dist} is not installed")
    if missing:
        print("          -> python -m pip install -r requirements.txt")


def check_env():
    section("3) .env settings (values are never printed)")
    env_file = Path(".env")
    if env_file.exists():
        ok(".env found")
    else:
        bad(".env file not found in this folder", "copy .env.example to .env and fill it in")
    try:
        from app.config import get_settings

        s = get_settings()
    except Exception as exc:  # noqa: BLE001
        missing = [str(e["loc"][-1]) for e in getattr(exc, "errors", lambda: [])()] or [str(exc)[:120]]
        bad(f"Required settings missing/invalid: {', '.join(missing)}", "add them to .env (DATABASE_URL and JWT_SECRET are required)")
        return None
    ok("DATABASE_URL and JWT_SECRET are set")
    if len(s.jwt_secret) < 32:
        warn("JWT_SECRET is short (use 32+ random characters). It must equal the value used by the OLD backend so old logins stay valid.")
    ok("GROQ_API_KEY is set") if s.groq_api_key else bad("GROQ_API_KEY is empty (chat and project analysis will answer 503)", "add it to .env")
    ok("RESEND_API_KEY is set") if s.resend_api_key else warn("RESEND_API_KEY is empty (password-reset e-mails will answer 503)")
    ok(f"NODE_ENV={s.node_env}  (production hides /docs and error details)")
    ok(f"CORS allows exactly: {', '.join(s.frontend_origins)}")
    if any(o.startswith("http://") for o in s.frontend_origins) and s.is_production:
        warn("FRONTEND_URL uses http:// in production - Secure cookies need https://")
    return s


async def check_database(s) -> None:
    section("4) Database")
    u = urlparse(s.database_url.replace("postgresql://", "postgres://", 1))
    host, port = u.hostname or "?", u.port or 5432
    ok(f"host {host}  ({'pooled' if '-pooler' in host else 'direct'} connection)")
    t = time.time()
    try:
        sock = socket.create_connection((host, port), timeout=15)
        ok(f"TCP connection in {time.time() - t:.1f}s")
    except Exception as exc:  # noqa: BLE001
        bad(f"Cannot reach the database server: {exc!r}", "check the host name in DATABASE_URL, your internet/VPN/firewall")
        return
    t = time.time()
    try:
        sock.sendall(bytes.fromhex("0000000804d2162f"))
        sock.settimeout(60)
        reply = sock.recv(1)
        ok(f"SSL handshake answered {reply!r} after {time.time() - t:.1f}s") if reply == b"S" else warn(f"Server answered {reply!r} to the SSL request")
    except Exception as exc:  # noqa: BLE001
        bad(f"No SSL answer from the database ({exc!r})",
            "Neon is probably asleep: open Neon > SQL Editor, run  select 1;  then retry. If it keeps failing, try another network/hotspot")
        return
    finally:
        sock.close()

    from sqlalchemy import text

    from app.database import engine
    from app.models import Base

    t = time.time()
    try:
        async with engine.connect() as conn:
            await conn.execute(text("select 1"))
            ok(f"login + query worked ({time.time() - t:.1f}s)")
            have = {r[0] for r in (await conn.execute(text("select table_name from information_schema.tables where table_schema = 'public'"))).all()}
            missing = [t_ for t_ in Base.metadata.tables if t_ not in have]
            if missing:
                bad(f"Tables missing in the database: {', '.join(missing)}", "run  python -m scripts.init_db")
            else:
                ok("all tables exist")
            demo = (await conn.execute(text('select count(*) from "User" where lower(email) = lower(:e)'), {"e": s.demo_user_email})).scalar_one() if "User" in have else 0
            ok(f"demo account {s.demo_user_email} exists") if demo else warn(f"demo account {s.demo_user_email} not found - 'Try Demo Account' will fail. Run: python -m scripts.seed")
    except Exception as exc:  # noqa: BLE001
        bad(f"Database login/query failed: {exc!r}", "check user/password/db name in DATABASE_URL; remove &channel_binding=require if present")
    finally:
        await engine.dispose()


async def check_ai(s) -> None:
    section("5) AI services")
    import httpx

    if s.groq_api_key:
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get("https://api.groq.com/openai/v1/models", headers={"Authorization": f"Bearer {s.groq_api_key}"})
            ok("Groq key accepted") if r.status_code == 200 else bad(f"Groq rejected the key (HTTP {r.status_code})", "create a new key at console.groq.com")
        except Exception as exc:  # noqa: BLE001
            warn(f"Could not reach Groq ({exc!r}) - check your internet")
    if s.embedding_provider == "gemini":
        ok("embeddings: gemini key set") if s.gemini_api_key else bad("EMBEDDING_PROVIDER=gemini but GEMINI_API_KEY is empty", "add GEMINI_API_KEY")
    else:
        try:
            async with httpx.AsyncClient(timeout=3) as c:
                r = await c.get(f"{s.ollama_url}/api/tags")
            names = [m["name"] for m in r.json().get("models", [])]
            ok("Ollama is running and nomic-embed-text is installed") if any("nomic-embed-text" in n for n in names) else bad(
                "Ollama is running but nomic-embed-text is missing", "ollama pull nomic-embed-text")
        except Exception:  # noqa: BLE001
            warn("Ollama is not running: 'Ask about project' (RAG) will fail locally. Start Ollama, or set EMBEDDING_PROVIDER=gemini + GEMINI_API_KEY. (Render needs gemini.)")


async def main() -> None:
    print("CodeBox doctor - checking your setup")
    check_python()
    check_packages()
    s = check_env()
    if s is not None:
        await check_database(s)
        await check_ai(s)
    section("Result")
    if problems:
        print(f"  {len(problems)} problem(s) found - fix the [FAIL] lines above, top to bottom.")
        raise SystemExit(1)
    print("  Everything important looks good. Start the API:  python -m uvicorn app.main:app --reload --port 5000")


if __name__ == "__main__":
    asyncio.run(main())
