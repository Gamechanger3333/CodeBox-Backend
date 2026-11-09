"""Error types + helpers that reproduce the original Express error contract.

Two response shapes exist in the original API and the frontend depends on both:
  * auth routes ........ {"status": "error", "message": "..."}
  * everything else .... {"error": "..."}
"""
from __future__ import annotations

from typing import Any


class ApiError(Exception):
    """Raise to send an exact JSON body with a given HTTP status."""

    def __init__(self, status_code: int, body: dict[str, Any]):
        super().__init__(str(body))
        self.status_code = status_code
        self.body = body


class ServiceUnavailable(Exception):
    """A third-party key is missing (Groq / Resend). Safe to show to the user (== err.expose)."""

    status = 503
    expose = True

    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.code = code


def err_body(message: str) -> dict[str, str]:
    return {"error": message}


def status_body(message: str) -> dict[str, str]:
    return {"status": "error", "message": message}
