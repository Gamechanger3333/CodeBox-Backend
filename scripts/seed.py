"""Create / refresh the demo account (demo@codebox.com) with sample chats and snippets.

    python -m scripts.seed
"""
import asyncio

from app.config import get_settings
from app.database import SessionLocal, engine
from app.services.demo_user import ensure_demo_user_seeded


async def main() -> None:
    async with SessionLocal() as db:
        user = await ensure_demo_user_seeded(db)
    print(f"Demo user ready: {user.email} (id {user.id}). Password = DEMO_USER_PASSWORD_SEED ({get_settings().demo_user_password_seed!r}).")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
