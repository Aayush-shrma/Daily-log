"""Auth: signup, login, sessions, rate limit, /auth/me."""

import datetime as dt
import uuid

from sqlalchemy import select

from app.database import SessionLocal
from app.models import Log

EMAIL = "user@example.com"
PASSWORD = "correct-horse-battery"


def signup(client, email=EMAIL, password=PASSWORD):
    return client.post("/auth/signup", json={"email": email, "password": password})


def test_signup_creates_user_and_session(client):
    resp = signup(client)
    assert resp.status_code == 201
    body = resp.json()
    assert body["email"] == EMAIL
    assert body["has_password"] is True
    assert "password" not in body
    assert "password_hash" not in body
    assert client.cookies.get("daylog_session")


def test_signup_lowercases_email(client):
    resp = signup(client, email="MiXeD@Example.COM")
    assert resp.status_code == 201
    assert resp.json()["email"] == "mixed@example.com"


def test_duplicate_signup_409(client):
    assert signup(client).status_code == 201
    resp = signup(client)
    assert resp.status_code == 409
    assert "already exists" in resp.json()["detail"]


def test_signup_rejects_short_password(client):
    resp = client.post("/auth/signup", json={"email": EMAIL, "password": "short"})
    assert resp.status_code == 422


def test_signup_rejects_bad_email(client):
    resp = client.post("/auth/signup", json={"email": "not-an-email", "password": PASSWORD})
    assert resp.status_code == 422


def test_login_ok(client):
    signup(client)
    client.cookies.clear()
    resp = client.post("/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert resp.status_code == 200
    assert resp.json()["email"] == EMAIL


def test_login_case_insensitive_email(client):
    signup(client)
    client.cookies.clear()
    resp = client.post("/auth/login", json={"email": EMAIL.upper(), "password": PASSWORD})
    assert resp.status_code == 200


def test_login_wrong_password_generic_error(client):
    signup(client)
    client.cookies.clear()
    resp = client.post("/auth/login", json={"email": EMAIL, "password": "wrong-password"})
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid email or password"


def test_login_unknown_email_same_error(client):
    resp = client.post("/auth/login", json={"email": "nobody@example.com", "password": PASSWORD})
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid email or password"


def test_login_rate_limited_after_five_failures(client):
    signup(client)
    client.cookies.clear()
    for _ in range(5):
        resp = client.post("/auth/login", json={"email": EMAIL, "password": "bad"})
        assert resp.status_code == 401
    resp = client.post("/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert resp.status_code == 429


def test_rate_limit_is_per_email(client):
    signup(client)
    client.cookies.clear()
    for _ in range(5):
        client.post("/auth/login", json={"email": EMAIL, "password": "bad"})
    other = client.post(
        "/auth/login", json={"email": "other@example.com", "password": "bad"}
    )
    assert other.status_code == 401  # not blocked


def test_rate_limit_cannot_be_bypassed_by_spoofed_ip(client, monkeypatch):
    """A different (spoofable) client IP per attempt must not reset the lockout."""
    signup(client)
    client.cookies.clear()

    spoofed = iter(f"198.51.100.{i}" for i in range(1, 100))
    monkeypatch.setattr("app.routers.auth.client_ip", lambda request: next(spoofed))

    for _ in range(5):
        resp = client.post("/auth/login", json={"email": EMAIL, "password": "bad"})
        assert resp.status_code == 401
    resp = client.post("/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert resp.status_code == 429


def test_logout_clears_cookie(client):
    signup(client)
    assert client.cookies.get("daylog_session")
    resp = client.post("/auth/logout")
    assert resp.status_code == 200
    assert not client.cookies.get("daylog_session")
    assert client.get("/auth/me").status_code == 401


def test_me_requires_auth(client):
    assert client.get("/auth/me").status_code == 401


def test_me_returns_current_user(client):
    signup(client)
    resp = client.get("/auth/me")
    assert resp.status_code == 200
    assert resp.json()["email"] == EMAIL


def test_auth_config_hides_google_when_unset(client):
    resp = client.get("/auth/config")
    assert resp.status_code == 200
    assert resp.json() == {"google_enabled": False}


def test_patch_start_date_recomputes_day_numbers(client, make_log):
    user_id = signup(client).json()["id"]
    today = dt.date.today()
    make_log(user_id, today, day_number=1)

    new_start = today - dt.timedelta(days=9)
    resp = client.patch("/auth/me", json={"start_date": new_start.isoformat()})
    assert resp.status_code == 200
    assert resp.json()["start_date"] == new_start.isoformat()

    db = SessionLocal()
    try:
        log = db.scalar(select(Log).where(Log.user_id == uuid.UUID(user_id)))
        assert log.day_number == 10
    finally:
        db.close()


def test_patch_start_date_rejects_future(client):
    signup(client)
    future = (dt.date.today() + dt.timedelta(days=1)).isoformat()
    resp = client.patch("/auth/me", json={"start_date": future})
    assert resp.status_code == 422


def test_delete_me_removes_user_and_logs(client, make_log):
    user_id = signup(client).json()["id"]
    make_log(user_id, dt.date.today())

    resp = client.delete("/auth/me")
    assert resp.status_code == 204
    assert client.get("/auth/me").status_code == 401

    db = SessionLocal()
    try:
        assert db.get(Log, 1) is None
        from app.models import User

        assert db.get(User, uuid.UUID(user_id)) is None
    finally:
        db.close()


def test_password_never_in_any_response(client):
    resp = signup(client)
    assert PASSWORD not in resp.text
    resp = client.get("/auth/me")
    assert PASSWORD not in resp.text
    resp = client.post("/auth/logout")
    assert PASSWORD not in resp.text
