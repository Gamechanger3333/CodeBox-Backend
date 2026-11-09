"""Create any MISSING tables (never touches existing ones).

    python -m scripts.init_db

On the database your Node/Prisma app already uses this only adds what Prisma was
missing (the InterviewSession table). On an empty database it creates everything.
For real schema evolution later, add Alembic (see README).
"""
import asyncio

from app.database import engine
from app.models import Base


async def main() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)  # checkfirst=True by default
    await engine.dispose()
    print("Tables are in place.")


if __name__ == "__main__":
    asyncio.run(main())
