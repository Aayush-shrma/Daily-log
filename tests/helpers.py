"""Test helpers: a fake httpx module so no provider call leaves the machine."""

from app.services import llm


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeHttpx:
    def __init__(self, response=None, exc=None):
        self.response = response
        self.exc = exc
        self.calls = []

    def post(self, url, headers=None, json=None, timeout=None):
        self.calls.append({"url": url, "headers": headers, "json": json})
        if self.exc is not None:
            raise self.exc
        return self.response


def patch_httpx(monkeypatch, response=None, exc=None) -> FakeHttpx:
    fake = FakeHttpx(response=response, exc=exc)
    monkeypatch.setattr(llm, "httpx", fake)
    return fake
