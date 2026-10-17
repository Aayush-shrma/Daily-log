"""Password hashing, session cookies, the current-user dependency, the CSRF
origin check and the in-memory login rate limiter."""

import datetime as dt
import uuid

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, Response
from sqlalchemy.orm import Session

from .config import settings
from .database import get_db
from .models import User

COOKIE_NAME = "daylog_session"
JWT_ALGORITHM = "HS256"
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

_ph = PasswordHasher()
# Precomputed hash so unknown-user logins still pay the argon2 cost.
_DUMMY_HASH = _ph.hash("daylog-dummy-password")


# --- passwords ---------------------------------------------------------------

def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _ph.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def dummy_verify() -> None:
    """Burn roughly the same time as a real check, for unknown emails."""
    try:
        _ph.verify(_DUMMY_HASH, "not-the-password")
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        pass


# --- session token -----------------------------------------------------------

def create_session_token(user_id: uuid.UUID) -> str:
    now = dt.datetime.now(dt.timezone.utc)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + dt.timedelta(days=settings.session_days),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=JWT_ALGORITHM)


def decode_session_token(token: str) -> uuid.UUID | None:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        return None
    sub = payload.get("sub")
    if not sub:
        return None
    try:
        return uuid.UUID(str(sub))
    except ValueError:
        return None


def set_session_cookie(response: Response, user_id: uuid.UUID) -> None:
    response.set_cookie(
        COOKIE_NAME,
        create_session_token(user_id),
        max_age=settings.session_days * 24 * 60 * 60,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
    )


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise _unauthorized()
    user_id = decode_session_token(token)
    if user_id is None:
        raise _unauthorized()
    user = db.get(User, user_id)
    if user is None:
        raise _unauthorized()
    return user


# --- CSRF origin check -------------------------------------------------------

def _origin_of(url: str) -> str:
    from urllib.parse import urlparse

    parts = urlparse(url)
    return f"{parts.scheme}://{parts.netloc}"


def _allowed_origins() -> set[str]:
    """BASE_URL's origin, plus any dev-only origins (empty in production)."""
    allowed = {_origin_of(settings.base_url)}
    for raw in settings.dev_allowed_origins.split(","):
        origin = raw.strip()
        if origin:
            allowed.add(_origin_of(origin))
    return allowed


async def origin_check_middleware(request: Request, call_next):
    """Reject unsafe cross-origin requests when an Origin header is present."""
    if request.method in UNSAFE_METHODS:
        origin = request.headers.get("origin")
        if origin and _origin_of(origin) not in _allowed_origins():
            return JSONResponse(
                {"detail": "Cross-origin request rejected"}, status_code=403
            )
    return await call_next(request)


# --- login rate limiting -----------------------------------------------------
# In-memory only: fine for a single instance (v1). With multiple workers/instances
# each process would keep its own counters, so a shared store is needed later.
class LoginRateLimiter:
    def __init__(self, max_attempts: int = 5, window_seconds: int = 900) -> None:
        self.max_attempts = max_attempts
        self.window = dt.timedelta(seconds=window_seconds)
        self._failures: dict[str, list[dt.datetime]] = {}

    def _recent(self, key: str, now: dt.datetime) -> list[dt.datetime]:
        return [t for t in self._failures.get(key, []) if now - t < self.window]

    def is_blocked(self, key: str) -> bool:
        now = dt.datetime.now(dt.timezone.utc)
        return len(self._recent(key, now)) >= self.max_attempts

    def record_failure(self, key: str) -> None:
        now = dt.datetime.now(dt.timezone.utc)
        recent = self._recent(key, now)
        recent.append(now)
        self._failures[key] = recent

    def reset(self, key: str) -> None:
        self._failures.pop(key, None)


login_limiter = LoginRateLimiter()

# Counts key-check requests per user (not failures); reuses the same window logic.
key_check_limiter = LoginRateLimiter(max_attempts=10, window_seconds=300)


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"
