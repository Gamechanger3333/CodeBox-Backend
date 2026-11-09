"""Request models (Pydantic v2).

The original used express-validator chains; each rule here keeps the SAME error
message, and fields are declared in the same order as the original chains
because the API reports only the FIRST failing rule.

Pattern used everywhere:
  * every field has a default so a *missing* field still reaches its validator
    (and produces the friendly message instead of a generic "field required"),
  * `mode="before"` validators coerce/trim the raw JSON value first.
"""
from __future__ import annotations

import re
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict, field_validator

from app.security import is_valid_email, normalize_email

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)


def _to_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return value if isinstance(value, str) else str(value)


def _trim(value: Any) -> str:
    return _to_str(value).strip()


Trimmed = Annotated[str, BeforeValidator(_trim)]  # JSON value -> str -> stripped
Raw = Annotated[str, BeforeValidator(_to_str)]  # JSON value -> str (not stripped)


class Body(BaseModel):
    """Base for request models: validate_default=True makes validators run even when the
    field is MISSING from the JSON (pydantic skips defaults otherwise)."""

    model_config = ConfigDict(validate_default=True)


def _fail(message: str) -> None:
    raise ValueError(message)


# ── auth ─────────────────────────────────────────────────────────────────────
class _EmailMixin(Body):
    email: Raw = ""

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        if not is_valid_email(v):
            _fail("A valid email address is required")
        normalized = normalize_email(v)
        if len(normalized) > 254:
            _fail("Email too long")
        return normalized


def _password_rule(v: str) -> str:
    if not 8 <= len(v) <= 128:
        _fail("Password must be 8–128 characters")
    return v


class SignupBody(Body):
    name: Trimmed = ""
    email: Raw = ""
    password: Raw = ""
    passwordConfirm: Any = None

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        if not 1 <= len(v) <= 100:
            _fail("Name must be 1–100 characters")
        return v

    _email = field_validator("email")(_EmailMixin._email.__func__)  # type: ignore[attr-defined]
    _pw = field_validator("password")(classmethod(lambda cls, v: _password_rule(v)))


class LoginBody(Body):
    email: Raw = ""
    password: Raw = ""

    _email = field_validator("email")(_EmailMixin._email.__func__)  # type: ignore[attr-defined]

    @field_validator("password")
    @classmethod
    def _pw(cls, v: str) -> str:
        if v == "":
            _fail("Invalid value")  # express-validator's default notEmpty() message
        return v


class ForgotPasswordBody(Body):
    email: Raw = ""
    _email = field_validator("email")(_EmailMixin._email.__func__)  # type: ignore[attr-defined]


class VerifyOtpBody(Body):
    email: Raw = ""
    otp: Trimmed = ""

    _email = field_validator("email")(_EmailMixin._email.__func__)  # type: ignore[attr-defined]

    @field_validator("otp")
    @classmethod
    def _otp(cls, v: str) -> str:
        if not re.fullmatch(r"\d{6}", v):
            _fail("OTP must be exactly 6 digits")
        return v


class ResetPasswordBody(Body):
    resetToken: Raw = ""
    password: Raw = ""
    passwordConfirm: Raw = ""

    @field_validator("resetToken")
    @classmethod
    def _token(cls, v: str) -> str:
        if v == "":
            _fail("Reset token is required")
        return v

    _pw = field_validator("password")(classmethod(lambda cls, v: _password_rule(v)))

    @field_validator("passwordConfirm")
    @classmethod
    def _confirm(cls, v: str) -> str:
        if v == "":
            _fail("Password confirmation is required")
        return v


# ── conversations ────────────────────────────────────────────────────────────
class SendMessageBody(Body):
    conversationId: Raw = ""
    message: Trimmed = ""

    @field_validator("conversationId")
    @classmethod
    def _cid(cls, v: str) -> str:
        if not UUID_RE.match(v):
            _fail("Invalid conversationId")
        return v

    @field_validator("message")
    @classmethod
    def _msg(cls, v: str) -> str:
        if not 1 <= len(v) <= 8000:
            _fail("Message must be 1–8000 characters")
        return v


class TitleBody(Body):
    title: Trimmed = ""

    @field_validator("title")
    @classmethod
    def _title(cls, v: str) -> str:
        if not 1 <= len(v) <= 100:
            _fail("Title must be 1–100 characters")
        return v


class AnalyzeCodeBody(Body):
    code: Trimmed = ""
    filename: Annotated[str | None, BeforeValidator(lambda v: None if v is None else _trim(v))] = None

    @field_validator("code")
    @classmethod
    def _code(cls, v: str) -> str:
        if not 1 <= len(v) <= 8000:
            _fail("Code must be 1–8000 characters")
        return v

    @field_validator("filename")
    @classmethod
    def _fn(cls, v: str | None) -> str | None:
        if v is not None and len(v) > 255:
            _fail("Filename too long")
        return v


# ── snippets ─────────────────────────────────────────────────────────────────
def _opt_trim(v: Any) -> str | None:
    return None if v is None else _trim(v)


OptTrimmed = Annotated[str | None, BeforeValidator(_opt_trim)]


def _to_bool(v: Any) -> bool | None:
    """express-validator isBoolean() + toBoolean(): true/false/'true'/'false'/1/0/'1'/'0'."""
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower() if isinstance(v, (int, str)) else None
    if s in ("true", "1"):
        return True
    if s in ("false", "0"):
        return False
    _fail("isPublic must be true or false")


OptBool = Annotated[bool | None, BeforeValidator(_to_bool)]


class SnippetCreateBody(Body):
    title: Trimmed = ""
    code: Trimmed = ""
    language: OptTrimmed = None
    description: OptTrimmed = None
    isPublic: OptBool = None

    @field_validator("title")
    @classmethod
    def _title(cls, v: str) -> str:
        if not 1 <= len(v) <= 100:
            _fail("Title must be 1–100 characters")
        return v

    @field_validator("code")
    @classmethod
    def _code(cls, v: str) -> str:
        if not 1 <= len(v) <= 50000:
            _fail("Code must be 1–50000 characters")
        return v

    @field_validator("language")
    @classmethod
    def _lang(cls, v: str | None) -> str | None:
        if v is not None and len(v) > 50:
            _fail("Language name too long")
        return v

    @field_validator("description")
    @classmethod
    def _desc(cls, v: str | None) -> str | None:
        if v is not None and len(v) > 500:
            _fail("Description max 500 characters")
        return v


class SnippetUpdateBody(Body):
    title: OptTrimmed = None
    code: OptTrimmed = None
    language: OptTrimmed = None
    description: OptTrimmed = None
    isPublic: OptBool = None

    @field_validator("title")
    @classmethod
    def _title(cls, v: str | None) -> str | None:
        if v is not None and not 1 <= len(v) <= 100:
            _fail("Invalid value")
        return v

    @field_validator("code")
    @classmethod
    def _code(cls, v: str | None) -> str | None:
        if v is not None and not 1 <= len(v) <= 50000:
            _fail("Code must be 1–50000 characters")
        return v

    @field_validator("language")
    @classmethod
    def _lang(cls, v: str | None) -> str | None:
        if v is not None and len(v) > 50:
            _fail("Invalid value")
        return v

    @field_validator("description")
    @classmethod
    def _desc(cls, v: str | None) -> str | None:
        if v is not None and len(v) > 500:
            _fail("Invalid value")
        return v


# ── project / interview ──────────────────────────────────────────────────────
class ProjectAskBody(Body):
    """No validators on purpose: the original /project/ask route never enforced its validator,
    the controller itself answered 'No message provided' / 'Message too long ...'."""

    message: Trimmed = ""


class InterviewAnswerBody(Body):
    answer: Trimmed = ""

    @field_validator("answer")
    @classmethod
    def _ans(cls, v: str) -> str:
        if not 1 <= len(v) <= 4000:
            _fail("Answer must be 1–4000 characters")
        return v
