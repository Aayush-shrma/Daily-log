"""Session cookie hardening, forged/expired tokens, CSRF origin check."""

import datetime as dt
import uuid

import jwt
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import Settings, settings


def _token(sub: str, exp_delta: dt.timedelta) -> str:
    now = dt.datetime.now(dt.timezone.utc)
    return jwt.encode(
        {"sub": sub, "exp": now + exp_delta}, settings.secret_key, algorithm="HS256"
    )


def signup(client, email="sec@example.com", password="password-123"):
    return client.post("/auth/signup", json={"email": email, "password": password})


def test_cookie_flags(client):
    resp = signup(client)
    cookie = resp.headers["set-cookie"]
    assert "daylog_session=" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie.lower() or "samesite=lax" in cookie.lower()
    # BASE_URL is http in tests, so the cookie must not be Secure.
    assert "Secure" not in cookie


def test_expired_cookie_is_401(client):
    client.cookies.set("daylog_session", _token(str(uuid.uuid4()), dt.timedelta(days=-1)))
    assert client.get("/auth/me").status_code == 401


def test_forged_cookie_is_401(client):
    token = _token(str(uuid.uuid4()), dt.timedelta(days=1))
    client.cookies.set("daylog_session", token + "tampered")
    assert client.get("/auth/me").status_code == 401


def test_cookie_signed_with_wrong_key_is_401(client):
    now = dt.datetime.now(dt.timezone.utc)
    token = jwt.encode(
        {"sub": str(uuid.uuid4()), "exp": now + dt.timedelta(days=1)},
        "some-other-key",
        algorithm="HS256",
    )
    client.cookies.set("daylog_session", token)
    assert client.get("/auth/me").status_code == 401


def test_valid_cookie_unknown_user_is_401(client):
    client.cookies.set("daylog_session", _token(str(uuid.uuid4()), dt.timedelta(days=1)))
    assert client.get("/auth/me").status_code == 401


def test_cross_origin_post_is_403(client):
    resp = client.post(
        "/auth/signup",
        json={"email": "x@example.com", "password": "password-123"},
        headers={"Origin": "https://evil.example.com"},
    )
    assert resp.status_code == 403


def test_dev_origin_is_403_unless_configured(client):
    # DEV_ALLOWED_ORIGINS is empty in tests/production, so a dev origin is foreign.
    resp = client.post(
        "/auth/signup",
        json={"email": "dev@example.com", "password": "password-123"},
        headers={"Origin": "http://localhost:5173"},
    )
    assert resp.status_code == 403


def test_dev_origin_is_allowed_when_configured(client, monkeypatch):
    monkeypatch.setattr(settings, "dev_allowed_origins", "http://localhost:5173")
    resp = client.post(
        "/auth/signup",
        json={"email": "dev@example.com", "password": "password-123"},
        headers={"Origin": "http://localhost:5173"},
    )
    assert resp.status_code == 201


def test_same_origin_post_is_allowed(client):
    resp = client.post(
        "/auth/signup",
        json={"email": "ok@example.com", "password": "password-123"},
        headers={"Origin": settings.base_url},
    )
    assert resp.status_code == 201


def test_missing_origin_is_allowed(client):
    resp = client.post(
        "/auth/signup", json={"email": "no@example.com", "password": "password-123"}
    )
    assert resp.status_code == 201


def test_security_headers_present(client):
    resp = client.get("/health")
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["referrer-policy"] == "no-referrer"
    assert "default-src 'self'" in resp.headers["content-security-policy"]


# --- production hardening ----------------------------------------------------

def test_production_refuses_default_or_short_secret_key():
    with pytest.raises(ValidationError):
        Settings(debug=False, secret_key="change-me")
    with pytest.raises(ValidationError):
        Settings(debug=False, secret_key="short")
    # A long random key is accepted in production.
    assert Settings(debug=False, secret_key="k" * 40).secret_key == "k" * 40


def test_https_base_url_is_treated_as_production():
    with pytest.raises(ValidationError):
        Settings(debug=True, secret_key="change-me", base_url="https://daylog.example.com")


def test_unhandled_error_leaks_no_stack_trace():
    from fastapi.routing import APIRoute

    from app.main import app

    def boom():
        raise RuntimeError("internal-detail-that-must-not-leak")

    # Insert before the SPA catch-all so the route is reachable.
    route = APIRoute("/_boom", boom, include_in_schema=False)
    app.router.routes.insert(0, route)
    try:
        with TestClient(app, raise_server_exceptions=False) as c:
            resp = c.get("/_boom")
    finally:
        app.router.routes.remove(route)

    assert resp.status_code == 500
    assert resp.json() == {"detail": "Internal server error"}
    assert "RuntimeError" not in resp.text
    assert "internal-detail-that-must-not-leak" not in resp.text
    # Error responses still carry the standard headers.
    assert resp.headers["x-content-type-options"] == "nosniff"
