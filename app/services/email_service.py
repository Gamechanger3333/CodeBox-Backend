"""Transactional e-mail through the Resend REST API (OTP for password reset)."""
from __future__ import annotations

import html
import logging
import secrets
from datetime import datetime

import httpx

from app import prompts
from app.config import get_settings
from app.errors import ServiceUnavailable

log = logging.getLogger("codebox.email")
RESEND_URL = "https://api.resend.com/emails"


def generate_otp() -> str:
    """Cryptographically secure 6-digit code (never use random.randint for secrets)."""
    return str(secrets.randbelow(900_000) + 100_000)


def _from_address() -> str:
    # Sandbox sender only works in development; production must set EMAIL_FROM to a verified domain.
    return get_settings().email_from or "CodeBox <onboarding@resend.dev>"


async def send_password_reset_otp(email: str, name: str, otp: str) -> dict:
    key = get_settings().resend_api_key
    if not key:
        log.error("RESEND_API_KEY environment variable is not set. Check your .env file.")
        raise ServiceUnavailable("Email service is temporarily unavailable. Please try again later.", "RESEND_API_KEY_MISSING")

    body = {
        "from": _from_address(),
        "to": email,
        "subject": f"{otp} — Your CodeBox Password Reset Code",
        "html": prompts.render(prompts.EMAIL_RESET_HTML, name=html.escape(name), otp=otp, year=datetime.now().year),
    }
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(RESEND_URL, json=body, headers={"Authorization": f"Bearer {key}"})
    data = resp.json() if resp.content else {}
    if resp.status_code >= 400:
        log.error("Resend error: %s", data)
        raise RuntimeError(data.get("message", "Failed to send email"))
    log.info("Password reset OTP email sent (id: %s)", data.get("id"))
    return data
