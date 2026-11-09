"""FastAPI application: wiring only (middleware, error handlers, routers)."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import get_settings
from app.database import engine
from app.errors import ApiError, err_body, status_body
from app.middleware import error_catcher_middleware, rate_limit_middleware, security_headers_middleware
from app.routers import auth, conversations, interview, project, snippets

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
log = logging.getLogger("codebox")

AUTH_PATHS = ("/api/signup", "/api/login", "/api/logout", "/api/forgot-password", "/api/verify-otp", "/api/reset-password")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup check only logs - the API stays up even if the DB is briefly unreachable."""
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        log.info("Database connected successfully")
    except Exception as exc:  # noqa: BLE001
        log.error("Database connection failed: %s", exc)
    yield
    await engine.dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="CodeBox API",
        version="2.0.0",
        lifespan=lifespan,
        docs_url=None if settings.is_production else "/docs",  # Swagger UI only outside production
        redoc_url=None,
        openapi_url=None if settings.is_production else "/openapi.json",
    )

    # add_middleware: the LAST one added is the OUTERMOST. Request flow: CORS -> headers -> rate limit -> errors -> route
    app.middleware("http")(error_catcher_middleware)
    app.middleware("http")(rate_limit_middleware)
    app.middleware("http")(security_headers_middleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_url],
        allow_credentials=True,  # needed so the browser sends/accepts the httpOnly cookie
        allow_methods=["GET", "HEAD", "PUT", "PATCH", "POST", "DELETE"],
        allow_headers=["*"],
    )

    # ── error handlers ──
    @app.exception_handler(ApiError)
    async def api_error_handler(request: Request, exc: ApiError):
        return JSONResponse(exc.body, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        """Report ONLY the first problem, in the shape that route group has always used."""
        errors = exc.errors()
        first = errors[0] if errors else {}
        if first.get("type") == "json_invalid":
            message = "Invalid JSON body"
        else:
            message = str(first.get("msg", "Invalid request"))
            message = message.removeprefix("Value error, ")
        body = status_body(message) if request.url.path in AUTH_PATHS else err_body(message)
        return JSONResponse(body, status_code=400)

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        if exc.status_code in (404, 405):  # unknown route (Express answered 404 for wrong methods too)
            return JSONResponse(status_body("Route not found"), status_code=404)
        return JSONResponse(status_body(str(exc.detail)), status_code=exc.status_code)

    # ── routes ──
    @app.get("/health", tags=["health"])
    async def health():
        return {"status": "ok", "service": "CodeBox API"}

    for module in (auth, conversations, snippets, project, interview):
        app.include_router(module.router, prefix="/api")
    return app


app = create_app()
