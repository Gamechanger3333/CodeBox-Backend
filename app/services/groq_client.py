"""Single shared Groq client, created LAZILY.

If GROQ_API_KEY is missing the app still boots (auth, snippets, chats list keep
working) - only AI calls fail, with a 503 whose message is safe to show.
Everything else in the app calls `chat_completion()`; tests replace that one function.
"""
from __future__ import annotations

import logging
from typing import Any

from groq import AsyncGroq

from app.config import get_settings
from app.errors import ServiceUnavailable

log = logging.getLogger("codebox.groq")
_client: AsyncGroq | None = None


def get_groq_client() -> AsyncGroq:
    global _client
    if _client is not None:
        return _client
    key = get_settings().groq_api_key
    if not key:
        log.error("GROQ_API_KEY environment variable is not set. Check your .env file.")
        raise ServiceUnavailable("AI features are temporarily unavailable. Please try again later.", "GROQ_API_KEY_MISSING")
    _client = AsyncGroq(api_key=key)
    return _client


async def chat_completion(*, model: str, messages: list[dict[str, Any]], temperature: float, max_tokens: int) -> str | None:
    """Returns the assistant text (or None if the model returned nothing)."""
    client = get_groq_client()
    completion = await client.chat.completions.create(
        model=model, messages=messages, temperature=temperature, max_tokens=max_tokens
    )
    if not completion.choices:
        return None
    return completion.choices[0].message.content or None
