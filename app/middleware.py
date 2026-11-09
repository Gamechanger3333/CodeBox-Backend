"""Security headers, rate limiting and the global error catcher.

Why a catch-all *middleware* instead of app.add_exception_handler(Exception, ...)?
Starlette runs a handler registered for `Exception` in ServerErrorMiddleware, which
sits OUTSIDE CORSMiddleware - so the 500 response would have no CORS headers and the
browser would hide the real error behind a CORS failure. Catching inside the middleware
stack keeps the CORS headers on every response.
"""
from __future__ import annotations

import logging
import math
import time
from collections.abc import Awaitable, Callable

from fastapi import Request
from fastapi.responses import JSONResponse, Response

from app.config import get_settings
from app.errors import status_body

log = logging.getLogger("codebox")

# ── helmet-like headers ──────────────────────────────────────────────────────
SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self';base-uri 'self';font-src 'self' https: data:;form-action 'self';"
    "frame-ancestors 'self';img-src 'self' data:;object-src 'none';script-src 'self';script-src-attr 'none';"
    "style-src 'self' https: 'unsafe-inline';upgrade-insecure-requests",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Origin-Agent-Cluster": "?1",
    "Referrer-Policy": "no-referrer",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "X-Content-Type-Options": "nosniff",
    "X-DNS-Prefetch-Control": "off",
    "X-Download-Options": "noopen",
    "X-Frame-Options": "SAMEORIGIN",
    "X-Permitted-Cross-Domain-Policies": "none",
    "X-XSS-Protection": "0",
}
_DOC_PATHS = ("/docs", "/redoc", "/openapi.json")  # Swagger UI needs inline scripts / CDN assets


async def security_headers_middleware(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    response = await call_next(request)
    if not request.url.path.startswith(_DOC_PATHS):
        for key, value in SECURITY_HEADERS.items():
            response.headers.setdefault(key, value)
    return response


# ── rate limiting (fixed window, in memory, per client IP) ───────────────────
class FixedWindowLimiter:
    """Same idea as express-rate-limit's default MemoryStore.

    In-memory means each server process has its own counters. With several
    instances you would back this with Redis (e.g. slowapi + Redis).
    """

    def __init__(self, window_seconds: int, max_requests: int, message: str):
        self.window = window_seconds
        self.max = max_requests
        self.message = message
        self._hits: dict[str, tuple[int, float]] = {}

    def hit(self, key: str) -> tuple[bool, int]:
        now = time.monotonic()
        if len(self._hits) > 10_000:  # opportunistic cleanup so memory stays bounded
            self._hits = {k: v for k, v in self._hits.items() if v[1] > now}
        count, reset_at = self._hits.get(key, (0, now + self.window))
        if reset_at <= now:
            count, reset_at = 0, now + self.window
        count += 1
        self._hits[key] = (count, reset_at)
        return count <= self.max, max(1, math.ceil(reset_at - now))

    def reset(self) -> None:
        self._hits.clear()


auth_limiter = FixedWindowLimiter(15 * 60, 20, "Too many requests, please try again later.")
api_limiter = FixedWindowLimiter(60, 60, "Rate limit exceeded. Please slow down.")
AUTH_LIMITED_PATHS = ("/api/login", "/api/signup", "/api/forgot-password", "/api/verify-otp", "/api/reset-password")


def client_ip(request: Request) -> str:
    """Behind one trusted proxy (Render/Vercel) the real client is the LAST X-Forwarded-For entry."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


async def rate_limit_middleware(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    path = request.url.path
    if get_settings().rate_limit_enabled and request.method != "OPTIONS" and (path == "/api" or path.startswith("/api/")):
        ip = client_ip(request)
        limiters = []
        if path.startswith(AUTH_LIMITED_PATHS):
            limiters.append(auth_limiter)
        limiters.append(api_limiter)
        for limiter in limiters:
            allowed, retry_after = limiter.hit(ip)
            if not allowed:
                return JSONResponse(status_body(limiter.message), status_code=429, headers={"Retry-After": str(retry_after)})
    return await call_next(request)


# ── global error handler ─────────────────────────────────────────────────────
async def error_catcher_middleware(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    try:
        return await call_next(request)
    except Exception as exc:  # noqa: BLE001 - this IS the last line of defence
        log.exception("Unhandled error on %s %s", request.method, request.url.path)
        return error_response(exc)


def error_response(exc: Exception) -> JSONResponse:
    """Never leak internals in production, except errors explicitly marked safe (`expose`)."""
    is_prod = get_settings().is_production
    status = getattr(exc, "status", None) or getattr(exc, "status_code", None) or 500
    expose = getattr(exc, "expose", False) is True or (isinstance(status, int) and status < 500 and getattr(exc, "status", None))
    if not is_prod or (is_prod and expose):
        message = str(exc) or "Internal Server Error"
    else:
        message = "Something went wrong. Please try again."
    return JSONResponse(status_body(message), status_code=status if isinstance(status, int) else 500)
