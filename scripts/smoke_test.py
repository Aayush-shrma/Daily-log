"""End-to-end smoke test against a *running* DayLog server (httpx only).

Signs up a throwaway user through the real API, exercises the endpoints,
optionally checks the BYOK path with SMOKE_LLM_KEY, then deletes the user.

Usage (server must already be running):
    set SMOKE_LLM_KEY=...        # optional
    python scripts/smoke_test.py

Env:
    SMOKE_BASE_URL  default http://127.0.0.1:8000
    SMOKE_LLM_KEY   optional; enables the BYOK + /llm/check steps
    SMOKE_LLM_PROVIDER  default "gemini"
"""

import datetime as dt
import os
import sys
import uuid

import httpx

BASE_URL = os.environ.get("SMOKE_BASE_URL", "http://127.0.0.1:8000")
LLM_KEY = os.environ.get("SMOKE_LLM_KEY", "")
LLM_PROVIDER = os.environ.get("SMOKE_LLM_PROVIDER", "gemini")

_failures = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global _failures
    if not condition:
        _failures += 1
    mark = "PASS" if condition else "FAIL"
    suffix = f"  ({detail})" if detail else ""
    print(f"[{mark}] {name}{suffix}")


def main() -> int:
    email = f"smoke-{uuid.uuid4().hex[:12]}@example.com"
    password = "smoke-test-password-123"
    today = dt.date.today()
    yesterday = today - dt.timedelta(days=1)

    print(f"Smoke test against {BASE_URL}")
    print(f"Throwaway user: {email}\n")

    with httpx.Client(base_url=BASE_URL, timeout=60) as client:
        resp = client.get("/health")
        check("/health", resp.status_code == 200 and resp.json().get("status") == "ok")

        resp = client.post("/auth/signup", json={"email": email, "password": password})
        check("signup", resp.status_code == 201, f"{resp.status_code}")

        resp = client.get("/auth/me")
        check("/auth/me", resp.status_code == 200 and resp.json()["email"] == email)

        resp = client.patch("/auth/me", json={"start_date": yesterday.isoformat()})
        check("PATCH /auth/me start_date", resp.status_code == 200, f"{resp.status_code}")

        resp = client.post("/logs", json={"raw_text": "smoke test log\nsecond line", "date": today.isoformat()})
        log_ok = resp.status_code == 201
        check("POST /logs", log_ok, f"{resp.status_code}")
        log_id = resp.json()["log"]["id"] if log_ok else None
        if log_ok:
            check("POST /logs day_number", resp.json()["log"]["day_number"] == 2)
            check("POST /logs used is not empty", bool(resp.json()["used"]))

        resp = client.get("/logs/day/2")
        check("GET /logs/day/2", resp.status_code == 200, f"{resp.status_code}")

        resp = client.get("/logs", params={"q": "smoke"})
        check(
            "GET /logs?q=smoke",
            resp.status_code == 200 and any(item["id"] == log_id for item in resp.json()),
        )

        if log_id is not None:
            resp = client.put(
                f"/logs/{log_id}",
                json={"bullets": ["smoke one", "smoke two"], "tweet_text": "Day 2: smoke"},
            )
            check(
                "PUT /logs/{id}",
                resp.status_code == 200 and resp.json()["item_count"] == 2,
                f"{resp.status_code}",
            )

        resp = client.get("/stats")
        stats_ok = resp.status_code == 200
        check("GET /stats", stats_ok, f"{resp.status_code}")
        if stats_ok:
            body = resp.json()
            check("stats heatmap length", len(body["heatmap"]) == 365)
            check("stats totals", body["total_days"] >= 1 and body["total_items"] >= 1)

        if LLM_KEY:
            headers = {"X-LLM-Provider": LLM_PROVIDER, "X-LLM-Key": LLM_KEY}
            resp = client.post("/llm/check", headers=headers)
            body = resp.json() if resp.status_code == 200 else {}
            check(
                "POST /llm/check (BYOK)",
                resp.status_code == 200 and body.get("ok") is True,
                f"{resp.status_code} {body.get('message', '')}".strip(),
            )
            check("key not echoed", LLM_KEY not in resp.text)

            resp = client.post(
                "/logs",
                json={"raw_text": "byok smoke log\nanother line", "date": yesterday.isoformat()},
                headers=headers,
            )
            ok = resp.status_code == 201
            check("POST /logs with BYOK headers", ok, f"{resp.status_code}")
            if ok:
                check("BYOK call used the user key", resp.json()["used"] == "user")
                check("key not echoed", LLM_KEY not in resp.text)
        else:
            print("[SKIP] /llm/check and BYOK POST /logs (SMOKE_LLM_KEY is empty)")

        resp = client.delete("/auth/me")
        check("DELETE /auth/me", resp.status_code == 204, f"{resp.status_code}")

        resp = client.get("/auth/me")
        check("session gone after delete", resp.status_code == 401)

    print()
    if _failures:
        print(f"RESULT: FAIL ({_failures} check(s) failed)")
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
