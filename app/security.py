"""JWT, password hashing, e-mail normalisation, cookies and the auth dependency."""
from __future__ import annotations

import asyncio
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt
from fastapi import Request, Response

from app.config import get_settings
from app.errors import ApiError, err_body

# ── Passwords ────────────────────────────────────────────────────────────────
# bcrypt only looks at the first 72 BYTES. Node's bcrypt silently ignores the rest,
# Python's bcrypt>=5 raises - so we truncate explicitly to keep old hashes valid.
_BCRYPT_MAX = 72


def _pw_bytes(plain: str) -> bytes:
    return plain.encode("utf-8")[:_BCRYPT_MAX]


async def hash_password(plain: str, rounds: int = 12) -> str:
    # bcrypt is CPU heavy (~250ms at 12 rounds): run it in a thread so the event loop stays free.
    return await asyncio.to_thread(lambda: bcrypt.hashpw(_pw_bytes(plain), bcrypt.gensalt(rounds)).decode())


async def verify_password(plain: str, hashed: str) -> bool:
    try:
        return await asyncio.to_thread(lambda: bcrypt.checkpw(_pw_bytes(plain), hashed.encode()))
    except ValueError:  # malformed hash
        return False


# ── JWT ──────────────────────────────────────────────────────────────────────
ALGORITHM = "HS256"


def _encode(payload: dict[str, Any], expires_seconds: int) -> str:
    now = int(time.time())
    return jwt.encode({**payload, "iat": now, "exp": now + expires_seconds}, get_settings().jwt_secret, algorithm=ALGORITHM)


def sign_token(user_id: int) -> str:
    """Login token: {id, iat, exp} - same claims as the Node version."""
    return _encode({"id": user_id}, get_settings().jwt_expires_seconds)


def sign_reset_token(user_id: int, email: str) -> str:
    """Short-lived (15 min), single-purpose token issued after the OTP is verified."""
    return _encode({"id": user_id, "email": email, "purpose": "password_reset"}, 15 * 60)


def decode_token(token: str) -> dict[str, Any]:
    # algorithms=[...] is mandatory: it blocks "alg: none" / algorithm-confusion attacks.
    return jwt.decode(token, get_settings().jwt_secret, algorithms=[ALGORITHM])


# ── Cookies ──────────────────────────────────────────────────────────────────
def set_auth_cookie(response: Response, token: str) -> None:
    days = get_settings().jwt_cookie_expires_in
    # secure + SameSite=None because frontend (Vercel) and API (Render) are different sites.
    response.set_cookie("token", token, max_age=days * 24 * 3600, httponly=True, secure=True, samesite="none")


def clear_auth_cookie(response: Response) -> None:
    # Same attributes as login, otherwise the browser treats it as a different cookie.
    response.set_cookie(
        "token", "", expires=datetime.now(timezone.utc) + timedelta(seconds=10), httponly=True, secure=True, samesite="none"
    )


# ── Auth dependency ──────────────────────────────────────────────────────────
async def get_current_user(request: Request) -> dict[str, Any]:
    """Equivalent of middlewares/auth.js. Returns the decoded JWT payload ({id, iat, exp})."""
    token: str | None = None
    auth_header = request.headers.get("authorization")
    if auth_header and auth_header.startswith("Bearer "):
        parts = auth_header.split(" ")
        token = parts[1] if len(parts) > 1 else ""
    else:
        token = request.cookies.get("token")

    if not token:
        raise ApiError(401, err_body("Token missing"))
    try:
        decoded = decode_token(token)
    except jwt.PyJWTError:
        raise ApiError(403, err_body("Invalid or expired token"))
    # A password-reset token must never work as a normal API credential.
    if decoded.get("purpose"):
        raise ApiError(403, err_body("Invalid or expired token"))
    return decoded


# ── E-mail normalisation (mirrors express-validator's normalizeEmail defaults) ─
_GMAIL = {"gmail.com", "googlemail.com"}
_ICLOUD = {"icloud.com", "me.com"}
_OUTLOOK = {"hotmail.com", "live.com", "msn.com", "outlook.com", "passport.com", "hotmail.co.uk", "live.co.uk", "outlook.co.uk"}
_YAHOO = {"rocketmail.com", "yahoo.ca", "yahoo.co.uk", "yahoo.com", "yahoo.de", "yahoo.fr", "yahoo.in", "yahoo.it", "ymail.com"}

_EMAIL_RE = re.compile(
    r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,}$"
)


def is_valid_email(value: str) -> bool:
    if not value or len(value) > 254 or ".." in value.split("@")[0]:
        return False
    if not _EMAIL_RE.match(value):
        return False
    return len(value.split("@")[0]) <= 64


def normalize_email(email: str) -> str:
    """Lower-cases and canonicalises common providers (Gmail dots/+tags, ...).

    The Node app stored e-mails normalised this way, so login/signup MUST do the same
    or existing users (e.g. john.doe+x@gmail.com stored as johndoe@gmail.com) could not sign in.
    """
    user, _, domain = email.rpartition("@")
    domain = domain.lower()
    if domain in _GMAIL:
        user = user.split("+")[0].replace(".", "").lower()
        domain = "gmail.com"
    elif domain in _ICLOUD:
        user = user.split("+")[0].lower()
    elif domain in _OUTLOOK:
        user = user.split("+")[0].lower()
    elif domain in _YAHOO:
        parts = user.split("-")
        user = ("-".join(parts[:-1]) if len(parts) > 1 else parts[0]).lower()
    else:
        user = user.lower()
    return f"{user}@{domain}"
