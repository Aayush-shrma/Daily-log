"""Authentication: email + password, sessions, and Google OpenID Connect."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from authlib.integrations.starlette_client import OAuth
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..models import Log, User
from ..schemas import LoginRequest, SignupRequest, StartDateUpdate, UserOut
from ..security import (
    clear_session_cookie,
    client_ip,
    dummy_verify,
    get_current_user,
    hash_password,
    login_limiter,
    set_session_cookie,
    verify_password,
)
from ..services.google import resolve_google_user
from ..timeutils import local_today

router = APIRouter(prefix="/auth", tags=["auth"])

# Registered even when unconfigured so the routes import cleanly; the routes
# themselves refuse when Google is not set up.
oauth = OAuth()
oauth.register(
    name="google",
    client_id=settings.google_client_id or "unconfigured",
    client_secret=settings.google_client_secret or "unconfigured",
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)


def _generic_login_error() -> HTTPException:
    # Same message whether the email or the password is wrong.
    return HTTPException(status_code=401, detail="Invalid email or password")


def _limiter_keys(request: Request, email: str) -> list[str]:
    """Keys the login limiter counts against.

    The email-only key cannot be spoofed, so faking X-Forwarded-For (which a
    trusted proxy may turn into request.client.host) can't hand an attacker a
    fresh counter for the same account. The ip+email key adds per-client
    strictness on top.
    """
    return [f"email:{email}", f"ip:{client_ip(request)}:{email}"]


@router.post("/signup", response_model=UserOut, status_code=201)
def signup(
    payload: SignupRequest, response: Response, db: Session = Depends(get_db)
) -> UserOut:
    email = payload.email.strip().lower()
    if db.scalar(select(User).where(User.email == email)) is not None:
        raise HTTPException(
            status_code=409, detail="An account with this email already exists"
        )
    user = User(email=email, password_hash=hash_password(payload.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    set_session_cookie(response, user.id)
    return UserOut.from_user(user)


@router.post("/login", response_model=UserOut)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> UserOut:
    email = payload.email.strip().lower()
    keys = _limiter_keys(request, email)
    if any(login_limiter.is_blocked(key) for key in keys):
        raise HTTPException(
            status_code=429, detail="Too many failed attempts. Try again later."
        )

    user = db.scalar(select(User).where(User.email == email))
    if user is None or user.password_hash is None:
        # Unknown email (or Google-only account): still pay the hash cost.
        dummy_verify()
        for key in keys:
            login_limiter.record_failure(key)
        raise _generic_login_error()
    if not verify_password(payload.password, user.password_hash):
        for key in keys:
            login_limiter.record_failure(key)
        raise _generic_login_error()

    for key in keys:
        login_limiter.reset(key)
    set_session_cookie(response, user.id)
    return UserOut.from_user(user)


@router.post("/logout")
def logout(response: Response) -> dict[str, bool]:
    clear_session_cookie(response)
    return {"ok": True}


@router.get("/me", response_model=UserOut)
def read_me(user: User = Depends(get_current_user)) -> UserOut:
    return UserOut.from_user(user)


@router.patch("/me", response_model=UserOut)
def update_me(
    payload: StartDateUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserOut:
    if payload.start_date > local_today():
        raise HTTPException(status_code=422, detail="Start date cannot be in the future")
    user.start_date = payload.start_date
    db.flush()
    # Recompute Day N for every existing log in one transaction.
    for log in db.scalars(select(Log).where(Log.user_id == user.id)):
        log.day_number = (log.date - payload.start_date).days + 1
    db.commit()
    db.refresh(user)
    return UserOut.from_user(user)


@router.delete("/me", status_code=204)
def delete_me(
    response: Response,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    db.delete(user)  # cascades to the user's logs
    db.commit()
    clear_session_cookie(response)


@router.get("/config")
def auth_config() -> dict[str, bool]:
    return {"google_enabled": settings.google_enabled}


@router.get("/google/login")
async def google_login(request: Request):
    if not settings.google_enabled:
        raise HTTPException(status_code=400, detail="Google sign-in is not configured")
    redirect_uri = f"{settings.base_url.rstrip('/')}/auth/google/callback"
    return await oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/google/callback")
async def google_callback(request: Request, db: Session = Depends(get_db)):
    if not settings.google_enabled:
        raise HTTPException(status_code=400, detail="Google sign-in is not configured")
    try:
        token = await oauth.google.authorize_access_token(request)
    except Exception:
        raise HTTPException(status_code=400, detail="Google sign-in failed")
    claims = token.get("userinfo") or {}
    if not claims:
        raise HTTPException(status_code=400, detail="Google sign-in failed")
    user = resolve_google_user(db, claims)
    response = RedirectResponse(url="/", status_code=303)
    set_session_cookie(response, user.id)
    return response
