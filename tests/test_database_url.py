import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.database import build_engine_args

NEON = "postgresql://neondb_owner:secret@ep-small-leaf-aegv7kiw-pooler.c-2.us-east-2.aws.neon.tech/neondb"


def test_prisma_style_url_with_every_common_option_is_translated():
    """The exact style of URL a Prisma/Neon user has in .env (this used to crash: unexpected keyword 'pool_timeout')."""
    url, connect_args, pool = build_engine_args(NEON + "?sslmode=require&pgbouncer=true&connect_timeout=30&pool_timeout=30&connection_limit=5&channel_binding=require")
    assert url == "postgresql+asyncpg://neondb_owner:secret@ep-small-leaf-aegv7kiw-pooler.c-2.us-east-2.aws.neon.tech/neondb"  # no query left
    assert connect_args["ssl"] == "require" and connect_args["timeout"] == 30.0
    assert connect_args["statement_cache_size"] == 0 and connect_args["prepared_statement_cache_size"] == 0
    assert pool == {"pool_timeout": 30.0, "pool_size": 5}


@pytest.mark.parametrize("query", ["", "?sslmode=disable", "?foo=bar&schema=public&options=x", "?connect_timeout=abc", "?pool_timeout="])
def test_unknown_or_odd_options_never_reach_asyncpg(query):
    url, connect_args, pool = build_engine_args(NEON + query)
    assert "?" not in url
    assert "ssl" not in connect_args
    assert connect_args["timeout"] == 30  # sensible default for a sleeping Neon database
    assert pool == {}


def test_plain_postgres_scheme_and_prefer_mode():
    url, connect_args, _ = build_engine_args("postgres://u:p@host:5432/db?sslmode=prefer")
    assert url.startswith("postgresql+asyncpg://") and connect_args["ssl"] == "require"


async def test_real_connection_with_a_prisma_style_url():
    import os
    base = os.environ["DATABASE_URL"].split("?")[0]
    url, connect_args, pool = build_engine_args(base + "?sslmode=disable&pgbouncer=true&connect_timeout=30&pool_timeout=30&connection_limit=3&channel_binding=require")
    engine = create_async_engine(url, connect_args=connect_args, **pool)
    try:
        async with engine.connect() as conn:
            assert (await conn.execute(text("select 1"))).scalar_one() == 1
    finally:
        await engine.dispose()
