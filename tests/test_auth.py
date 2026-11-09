from datetime import timedelta

import jwt
import pytest
from sqlalchemy import select

from app.models import User, utcnow
from app.security import decode_token, hash_password, normalize_email, sign_reset_token, verify_password
from tests.conftest import signup

# Generated with Node (bcryptjs / jsonwebtoken, secret "node-compat-secret"): proves existing users keep working.
NODE_BCRYPT_HASH = "$2b$12$TlZ0MD7DPVEHyEFMzZnTLuhWbRY12PMT82vxB4xKwXSlTlsODbN0S"  # 'Legacy#Pass1'
NODE_LONG_HASH = "$2b$10$v8WbtaNtOsol5rqy.BSlF.3KNVqzOVt8EwDZFXCwm3srnFDwX.mC."  # 'A' * 80
NODE_JWT = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpZCI6NDI0MjQyLCJpYXQiOjE3OTM1MTAxOTMsImV4cCI6NDk0NzExMDE5M30.CBP-IYEF7X5w2PUK1DNiHI6Kmil6Jj2mIb8ucSD_Tug"


async def test_signup_success_shape_and_cookie(client):
    r = await client.post("/api/signup", json={"name": "  Ali  ", "email": "Ali@Example.com", "password": "Passw0rd!x", "passwordConfirm": "Passw0rd!x"})
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "success" and body["token"]
    user = body["data"]["user"]
    assert user["name"] == "Ali" and user["email"] == "ali@example.com" and user["isVerified"] is True
    assert "password" not in user and "otpCode" not in user
    assert user["createdAt"].endswith("Z")
    cookie = r.headers["set-cookie"].lower()
    assert "token=" in cookie and "httponly" in cookie and "secure" in cookie and "samesite=none" in cookie
    assert decode_token(body["token"])["id"] == user["id"]


@pytest.mark.parametrize(
    "payload,message",
    [
        ({"name": "", "email": "a@b.co", "password": "12345678", "passwordConfirm": "12345678"}, "Name must be 1–100 characters"),
        ({"name": "x", "email": "nope", "password": "12345678", "passwordConfirm": "12345678"}, "A valid email address is required"),
        ({"name": "x", "email": "a@b.co", "password": "short", "passwordConfirm": "short"}, "Password must be 8–128 characters"),
        ({"name": "x", "email": "a@b.co", "password": "12345678", "passwordConfirm": "different"}, "Passwords do not match"),
        ({}, "Name must be 1–100 characters"),
    ],
)
async def test_signup_validation_messages(client, payload, message):
    r = await client.post("/api/signup", json=payload)
    assert r.status_code == 400
    assert r.json() == {"status": "error", "message": message}


async def test_signup_duplicate_and_demo_email(client):
    await signup(client, "dup@example.com")
    r = await client.post("/api/signup", json={"name": "x", "email": "dup@example.com", "password": "Passw0rd!x", "passwordConfirm": "Passw0rd!x"})
    assert r.status_code == 400 and r.json()["message"] == "An account with this email already exists"
    r = await client.post("/api/signup", json={"name": "x", "email": "demo@codebox.com", "password": "Passw0rd!x", "passwordConfirm": "Passw0rd!x"})
    assert r.status_code == 400 and "reserved for the demo account" in r.json()["message"]


async def test_login_ok_and_wrong_credentials(client):
    await signup(client, "login@example.com", password="Passw0rd!x")
    ok = await client.post("/api/login", json={"email": "LOGIN@example.com", "password": "Passw0rd!x"})
    assert ok.status_code == 200 and ok.json()["status"] == "success"
    bad_pw = await client.post("/api/login", json={"email": "login@example.com", "password": "wrong-password"})
    no_user = await client.post("/api/login", json={"email": "ghost@example.com", "password": "whatever1"})
    assert bad_pw.status_code == no_user.status_code == 401
    assert bad_pw.json() == no_user.json() == {"status": "error", "message": "Incorrect email or password"}
    empty = await client.post("/api/login", json={"email": "login@example.com", "password": ""})
    assert empty.status_code == 400 and empty.json()["message"] == "Invalid value"


async def test_gmail_normalisation_matches_node_behaviour(client):
    assert normalize_email("John.Doe+tag@GoogleMail.com") == "johndoe@gmail.com"
    assert normalize_email("Some.One+x@Outlook.com") == "some.one@outlook.com"
    await signup(client, "john.doe+news@gmail.com")
    r = await client.post("/api/login", json={"email": "johndoe@gmail.com", "password": "Passw0rd!x"})
    assert r.status_code == 200


async def test_node_created_bcrypt_hash_and_jwt_are_accepted(client, db):
    # A user created by the OLD Node app (hash made by bcryptjs) can log in...
    db.add(User(name="Legacy", email="legacy@example.com", password=NODE_BCRYPT_HASH, is_verified=True))
    await db.commit()
    r = await client.post("/api/login", json={"email": "legacy@example.com", "password": "Legacy#Pass1"})
    assert r.status_code == 200
    # ...bcrypt ignores everything after byte 72, exactly like the Node library did
    assert await verify_password("A" * 80, NODE_LONG_HASH)
    assert await verify_password("A" * 72, NODE_LONG_HASH)
    # ...and a token signed by Node's jsonwebtoken with the same secret is accepted
    r = await client.get("/api/check_authentication", headers={"Authorization": f"Bearer {NODE_JWT}"})
    assert r.status_code == 200 and r.json()["user"]["id"] == 424242


async def test_check_authentication_cookie_bearer_missing_invalid(auth, client):
    c, user, token = auth
    r = await c.get("/api/check_authentication")  # cookie from signup
    assert r.status_code == 200 and r.json()["authenticated"] is True and r.json()["user"]["id"] == user["id"]
    client.cookies.clear()
    assert (await client.get("/api/check_authentication")).json() == {"error": "Token missing"}
    assert (await client.get("/api/check_authentication")).status_code == 401
    r = await client.get("/api/check_authentication", headers={"Authorization": "Bearer not-a-token"})
    assert r.status_code == 403 and r.json() == {"error": "Invalid or expired token"}
    r = await client.get("/api/check_authentication", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200


async def test_expired_and_wrong_secret_tokens_rejected(client):
    expired = jwt.encode({"id": 1, "exp": 1}, "node-compat-secret", algorithm="HS256")
    wrong = jwt.encode({"id": 1}, "other-secret", algorithm="HS256")
    none_alg = jwt.encode({"id": 1}, None, algorithm="none")
    for t in (expired, wrong, none_alg):
        r = await client.get("/api/check_authentication", headers={"Authorization": f"Bearer {t}"})
        assert r.status_code == 403


async def test_reset_token_cannot_be_used_as_login_token(client):
    r = await client.get("/api/check_authentication", headers={"Authorization": f"Bearer {sign_reset_token(1, 'a@b.co')}"})
    assert r.status_code == 403


async def test_logout_clears_cookie(auth):
    c, _, _ = auth
    r = await c.post("/api/logout")
    assert r.status_code == 200 and r.json() == {"status": "success", "message": "Logged out successfully"}
    assert "token=" in r.headers["set-cookie"]


async def test_full_password_reset_flow(client, sent_emails, db):
    await signup(client, "reset@example.com", name="Reset Me", password="OldPassw0rd!")
    client.cookies.clear()

    unknown = await client.post("/api/forgot-password", json={"email": "ghost@example.com"})
    assert unknown.status_code == 200 and "If an account" in unknown.json()["message"]
    assert sent_emails == []  # no e-mail, but the response is identical -> no user enumeration

    r = await client.post("/api/forgot-password", json={"email": "reset@example.com"})
    assert r.status_code == 200 and len(sent_emails) == 1
    otp = sent_emails[0]["otp"]
    assert len(otp) == 6 and otp.isdigit() and sent_emails[0]["name"] == "Reset Me"

    user = (await db.execute(select(User).where(User.email == "reset@example.com"))).scalar_one()
    assert user.otp_code != otp and user.otp_code.startswith("$2")  # stored hashed

    wrong = await client.post("/api/verify-otp", json={"email": "reset@example.com", "otp": "000000" if otp != "000000" else "111111"})
    assert wrong.status_code == 400 and wrong.json()["message"] == "Incorrect OTP. 4 attempts remaining."

    ok = await client.post("/api/verify-otp", json={"email": "reset@example.com", "otp": otp})
    assert ok.status_code == 200
    reset_token = ok.json()["resetToken"]

    reuse = await client.post("/api/verify-otp", json={"email": "reset@example.com", "otp": otp})
    assert reuse.status_code == 400 and "No active OTP" in reuse.json()["message"]  # one-time use

    mismatch = await client.post("/api/reset-password", json={"resetToken": reset_token, "password": "NewPassw0rd!", "passwordConfirm": "x" * 10})
    assert mismatch.json()["message"] == "Passwords do not match"
    done = await client.post("/api/reset-password", json={"resetToken": reset_token, "password": "NewPassw0rd!", "passwordConfirm": "NewPassw0rd!"})
    assert done.status_code == 200 and done.json()["token"]

    assert (await client.post("/api/login", json={"email": "reset@example.com", "password": "OldPassw0rd!"})).status_code == 401
    assert (await client.post("/api/login", json={"email": "reset@example.com", "password": "NewPassw0rd!"})).status_code == 200


async def test_otp_attempt_limit_expiry_and_bad_reset_tokens(client, sent_emails, db):
    await signup(client, "otp@example.com")
    client.cookies.clear()
    await client.post("/api/forgot-password", json={"email": "otp@example.com"})
    otp = sent_emails[0]["otp"]
    bad = "000000" if otp != "000000" else "111111"
    for i in range(5):
        r = await client.post("/api/verify-otp", json={"email": "otp@example.com", "otp": bad})
        assert r.status_code == 400
    r = await client.post("/api/verify-otp", json={"email": "otp@example.com", "otp": otp})  # even the right OTP is burnt now
    assert r.status_code == 429 and "Too many failed attempts" in r.json()["message"]

    await client.post("/api/forgot-password", json={"email": "otp@example.com"})
    user = (await db.execute(select(User).where(User.email == "otp@example.com"))).scalar_one()
    user.otp_expiry = utcnow() - timedelta(minutes=1)
    await db.commit()
    r = await client.post("/api/verify-otp", json={"email": "otp@example.com", "otp": sent_emails[-1]["otp"]})
    assert r.status_code == 400 and "expired" in r.json()["message"]

    bad_token = await client.post("/api/reset-password", json={"resetToken": "garbage", "password": "NewPassw0rd!", "passwordConfirm": "NewPassw0rd!"})
    assert bad_token.status_code == 400 and "Invalid or expired reset token" in bad_token.json()["message"]
    login_token = decode_token((await client.post("/api/login", json={"email": "otp@example.com", "password": "Passw0rd!x"})).json()["token"])
    assert login_token.get("purpose") is None
    from app.security import _encode  # a *login-style* token must not be accepted as a reset token
    wrong_purpose = _encode({"id": 1}, 600)
    r = await client.post("/api/reset-password", json={"resetToken": wrong_purpose, "password": "NewPassw0rd!", "passwordConfirm": "NewPassw0rd!"})
    assert r.status_code == 400 and r.json()["message"] == "Invalid reset token."


async def test_forgot_password_without_resend_key_is_503_with_safe_message(client):
    await signup(client, "nomail@example.com")
    client.cookies.clear()
    r = await client.post("/api/forgot-password", json={"email": "nomail@example.com"})
    assert r.status_code == 503
    assert r.json() == {"status": "error", "message": "Email service is temporarily unavailable. Please try again later."}


async def test_hash_password_roundtrip():
    h = await hash_password("Secret123!", 4)
    assert await verify_password("Secret123!", h) and not await verify_password("secret123!", h)
    assert not await verify_password("x", "not-a-bcrypt-hash")
