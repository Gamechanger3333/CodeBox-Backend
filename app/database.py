"""Async SQLAlchemy engine + session factory.

The same PostgreSQL database the Prisma/Node version used works unchanged:
we map the exact same tables/columns (see models.py).
"""
from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings

def _number(value: str | None) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except ValueError:
        return None


def build_engine_args(raw_url: str) -> tuple[str, dict, dict]:
    """Translate a Prisma/libpq-style DATABASE_URL into (asyncpg URL, connect_args, pool kwargs).

    Prisma URLs carry options such as ?sslmode=require&pgbouncer=true&connect_timeout=30&pool_timeout=30&connection_limit=5.
    asyncpg understands NONE of them as URL options (it would crash with "unexpected keyword argument"), so we read
    the ones that matter, convert them to the right place, and strip the whole query string.
    """
    url = make_url(raw_url)
    if url.drivername in ("postgres", "postgresql", "postgresql+psycopg2", "postgresql+asyncpg"):
        url = url.set(drivername="postgresql+asyncpg")

    query = dict(url.query)
    sslmode = query.get("sslmode")
    connect_timeout = _number(query.get("connect_timeout"))
    pool_timeout = _number(query.get("pool_timeout"))
    connection_limit = _number(query.get("connection_limit"))
    url = url.set(query={})  # drop EVERYTHING, we pass what we need explicitly below

    connect_args: dict = {
        # Works behind PgBouncer (Neon/Supabase pooled URLs) which cannot do prepared statements.
        "statement_cache_size": 0,
        "prepared_statement_cache_size": 0,
        # Seconds to wait for the TCP/TLS connection. Neon's free tier "sleeps": waking it can take 10-20 s.
        "timeout": connect_timeout if connect_timeout else 30,
    }
    if sslmode in {"require", "verify-ca", "verify-full", "prefer", "allow"}:
        connect_args["ssl"] = "require" if sslmode in {"allow", "prefer"} else sslmode

    pool_kwargs: dict = {}
    if pool_timeout:
        pool_kwargs["pool_timeout"] = pool_timeout  # how long a request waits for a free pooled connection
    if connection_limit:
        pool_kwargs["pool_size"] = int(connection_limit)
    return url.render_as_string(hide_password=False), connect_args, pool_kwargs


def create_engine_from_settings() -> AsyncEngine:
    url, connect_args, pool_kwargs = build_engine_args(get_settings().database_url)
    return create_async_engine(url, pool_pre_ping=True, connect_args=connect_args, **pool_kwargs)


engine: AsyncEngine = create_engine_from_settings()
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one session per request, always closed afterwards."""
    async with SessionLocal() as session:
        yield session
