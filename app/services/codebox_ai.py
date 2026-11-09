"""CodeBox AI - chat answers, code analysis, titles and language detection (Groq)."""
from __future__ import annotations

from app import prompts
from app.services import groq_client

BIG_MODEL = "openai/gpt-oss-120b"
SMALL_MODEL = "openai/gpt-oss-20b"
MAX_CONTEXT_MESSAGES = 30


async def get_codebox_ai_response(messages: list[dict[str, str]]) -> str:
    """messages: [{sender: 'user'|'bot', content}] - only the last 30 are sent (bounded token cost)."""
    capped = messages[-MAX_CONTEXT_MESSAGES:]
    formatted = [{"role": "user" if m["sender"] == "user" else "assistant", "content": m["content"]} for m in capped]
    text = await groq_client.chat_completion(
        model=BIG_MODEL,
        messages=[{"role": "system", "content": prompts.CODEBOX_SYSTEM_PROMPT}, *formatted],
        temperature=0.7,
        max_tokens=4096,
    )
    return text or "Sorry, I could not generate a response."


async def analyze_code(code: str, filename: str) -> str:
    prompt = prompts.render(prompts.ANALYZE_CODE_PROMPT, filename=filename, code=code)
    text = await groq_client.chat_completion(
        model=BIG_MODEL,
        messages=[{"role": "system", "content": prompts.CODEBOX_SYSTEM_PROMPT}, {"role": "user", "content": prompt}],
        temperature=0.5,
        max_tokens=2048,
    )
    return text or "Analysis failed."


async def generate_conversation_title(first_message: str) -> str:
    text = await groq_client.chat_completion(
        model=SMALL_MODEL,
        messages=[{"role": "user", "content": prompts.render(prompts.TITLE_PROMPT, firstMessage=first_message)}],
        temperature=0.3,
        max_tokens=20,
    )
    return (text or "").strip() or "New conversation"


async def detect_language(code: str) -> str:
    text = await groq_client.chat_completion(
        model=SMALL_MODEL,
        messages=[{"role": "user", "content": prompts.render(prompts.DETECT_PROMPT, code=code[:500])}],
        temperature=0,
        max_tokens=10,
    )
    return (text or "").strip() or "Unknown"
