import hashlib
import hmac
import secrets
import time
import uuid

from fastapi import HTTPException, Request

COOKIE = "cloudlab_session"
SESSION_SECONDS = 12 * 60 * 60


def hash_password(password):
    salt = secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=salt.encode(), n=16384, r=8, p=1).hex()
    return f"scrypt${salt}${digest}"


def verify_password(password, encoded):
    _, salt, expected = encoded.split("$")
    actual = hashlib.scrypt(password.encode(), salt=salt.encode(), n=16384, r=8, p=1).hex()
    return hmac.compare_digest(actual, expected)


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def public_user(user):
    return {key: user[key] for key in ("id", "name", "email", "role")}


def create_user(db, name, email, password, role="student"):
    if len(password) < 10 or len(password) > 128:
        raise HTTPException(422, "Use a password with 10–128 characters.")
    user_id = uuid.uuid4().hex
    db.execute(
        "INSERT INTO users VALUES (?,?,?,?,?,?)",
        (user_id, name, email, hash_password(password), role, time.time()),
    )
    return db.one("SELECT * FROM users WHERE id=?", (user_id,))


def set_session(db, response, user, settings):
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    db.execute("DELETE FROM sessions WHERE expires_at < ?", (time.time(),))
    db.execute(
        "INSERT INTO sessions VALUES (?,?,?,?)",
        (token_hash(token), user["id"], csrf, time.time() + SESSION_SECONDS),
    )
    response.set_cookie(
        COOKIE,
        token,
        max_age=SESSION_SECONDS,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="strict",
    )
    return {"user": public_user(user), "csrf": csrf}


def authenticate(db, token):
    if not token:
        return None
    return db.one(
        "SELECT users.*, sessions.csrf FROM sessions JOIN users ON users.id=sessions.user_id WHERE token_hash=? AND expires_at>?",
        (token_hash(token), time.time()),
    )


def current_user(request: Request):
    user = authenticate(request.app.state.db, request.cookies.get(COOKIE))
    if not user:
        raise HTTPException(401, "Please sign in to continue.")
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        if not hmac.compare_digest(request.headers.get("x-csrf-token", ""), user["csrf"]):
            raise HTTPException(403, "Your session changed. Refresh the page and try again.")
    return user


def admin_user(request: Request):
    user = current_user(request)
    if user["role"] != "admin":
        raise HTTPException(403, "Administrator access is required.")
    return user
