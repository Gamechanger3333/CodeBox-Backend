"""Auth endpoints: signup, login, logout and the 3-step OTP password reset.

Error contract (the frontend relies on it): {"status": "error", "message": "..."}.
"""
from __future__ import annotations

import logging

import jwt
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.errors import status_body
from app.models import User, utcnow
from app.schemas import ForgotPasswordBody, LoginBody, ResetPasswordBody, SignupBody, VerifyOtpBody
from app.security import (
    clear_auth_cookie, decode_token, hash_password, set_auth_cookie, sign_reset_token, sign_token, verify_password,
)
from app.serializers import user_json
from app.services import demo_user, email_service

log = logging.getLogger("codebox.auth")
router = APIRouter(tags=["auth"])


def fail(status: int, message: str) -> JSONResponse:
    return JSONResponse(status_body(message), status_code=status)


def send_token(user: User, status: int) -> JSONResponse:
    token = sign_token(user.id)
    response = JSONResponse({"status": "success", "token": token, "data": {"user": user_json(user)}}, status_code=status)
    set_auth_cookie(response, token)
    return response


async def _by_email(db: AsyncSession, email: str) -> User | None:
    return (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()


@router.post("/signup")
async def signup(body: SignupBody, db: AsyncSession = Depends(get_session)):
    try:
        if body.password != body.passwordConfirm:
            return fail(400, "Passwords do not match")
        # The demo e-mail is wiped on every demo login, so a real signup on it would just be erased.
        if demo_user.is_demo_user_email(body.email):
            return fail(400, "This email is reserved for the demo account. Please use a different email to sign up.")
        if await _by_email(db, body.email):
            return fail(400, "An account with this email already exists")

        user = User(name=body.name, email=body.email, password=await hash_password(body.password, 12), is_verified=True)
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return send_token(user, 201)
    except Exception:  # noqa: BLE001
        log.exception("Signup error")
        return fail(500, "Signup failed. Please try again.")


@router.post("/login")
async def login(body: LoginBody, db: AsyncSession = Depends(get_session)):
    user = await _by_email(db, body.email)
    # Same message for "no such user" and "wrong password" -> no account enumeration.
    if not user or not await verify_password(body.password, user.password):
        return fail(401, "Incorrect email or password")
    if demo_user.is_demo_user_email(user.email):
        await demo_user.reset_demo_user_data(db, user.id)  # every demo visitor starts from a clean state
        await db.refresh(user)
    return send_token(user, 200)


@router.post("/logout")
async def logout():
    """POST (not GET) so a stray <img src=...> on another site cannot log you out (CSRF)."""
    response = JSONResponse({"status": "success", "message": "Logged out successfully"})
    clear_auth_cookie(response)
    return response


@router.post("/forgot-password")
async def forgot_password(body: ForgotPasswordBody, db: AsyncSession = Depends(get_session)):
    try:
        user = await _by_email(db, body.email)
        if not user:  # always "success": do not reveal which e-mails are registered
            return JSONResponse({"status": "success", "message": "If an account with this email exists, you will receive an OTP shortly."})

        otp = email_service.generate_otp()
        from datetime import timedelta

        user.otp_code = await hash_password(otp, 10)  # store only a hash of the OTP
        user.otp_expiry = utcnow() + timedelta(minutes=10)
        user.otp_attempts = 0
        await db.commit()

        await email_service.send_password_reset_otp(body.email, user.name, otp)
        log.info("Password reset OTP issued for user %s", user.id)
        return JSONResponse({"status": "success", "message": "OTP sent to your email address. Check your inbox."})
    except Exception as exc:  # noqa: BLE001
        log.exception("Forgot password error")
        status = getattr(exc, "status", None) or 500
        message = str(exc) if getattr(exc, "expose", False) else "Failed to send OTP. Please try again."
        return fail(status, message)


@router.post("/verify-otp")
async def verify_otp(body: VerifyOtpBody, db: AsyncSession = Depends(get_session)):
    try:
        user = await _by_email(db, body.email)
        if not user or not user.otp_code or not user.otp_expiry:
            return fail(400, "No active OTP found. Please request a new one.")

        if utcnow() > user.otp_expiry:
            user.otp_code, user.otp_expiry, user.otp_attempts = None, None, 0
            await db.commit()
            return fail(400, "OTP has expired. Please request a new one.")

        if user.otp_attempts >= 5:  # brute-force protection: 5 wrong guesses burn the OTP
            user.otp_code, user.otp_expiry, user.otp_attempts = None, None, 0
            await db.commit()
            return fail(429, "Too many failed attempts. Please request a new OTP.")

        if not await verify_password(body.otp, user.otp_code):
            attempts_left = 4 - user.otp_attempts
            user.otp_attempts += 1
            await db.commit()
            return fail(400, f"Incorrect OTP. {attempts_left} attempt{'' if attempts_left == 1 else 's'} remaining.")

        reset_token = sign_reset_token(user.id, user.email)  # 15 min, single purpose
        user.otp_code, user.otp_expiry, user.otp_attempts = None, None, 0  # one-time use
        await db.commit()
        return JSONResponse({"status": "success", "message": "OTP verified successfully.", "resetToken": reset_token})
    except Exception:  # noqa: BLE001
        log.exception("Verify OTP error")
        return fail(500, "Verification failed. Please try again.")


@router.post("/reset-password")
async def reset_password(body: ResetPasswordBody, db: AsyncSession = Depends(get_session)):
    try:
        if body.password != body.passwordConfirm:
            return fail(400, "Passwords do not match")
        try:
            decoded = decode_token(body.resetToken)
        except jwt.PyJWTError:
            return fail(400, "Invalid or expired reset token. Please start over.")
        if decoded.get("purpose") != "password_reset":
            return fail(400, "Invalid reset token.")

        user = await db.get(User, decoded["id"])
        if user is None:
            raise LookupError("user not found")
        user.password = await hash_password(body.password, 12)
        await db.commit()
        log.info("Password reset completed for user %s", user.id)
        return send_token(user, 200)
    except Exception:  # noqa: BLE001
        log.exception("Reset password error")
        return fail(500, "Password reset failed. Please try again.")
