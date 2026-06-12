"""Behavioral verification — the agent must NOT edit this. Exercises real runtime behavior:
round-trip shorten→resolve, exact redirect status + Location, 404, and request validation."""

from fastapi.testclient import TestClient

from app import app

client = TestClient(app)


def test_shorten_returns_code():
    r = client.post("/shorten", json={"url": "https://example.com/a/b?c=1"})
    assert r.status_code == 200
    body = r.json()
    assert body["code"]
    assert body["code"] in body["short_url"]


def test_round_trip_redirect():
    url = "https://example.com/page"
    code = client.post("/shorten", json={"url": url}).json()["code"]
    r = client.get(f"/{code}", follow_redirects=False)
    assert r.status_code == 307
    assert r.headers["location"] == url


def test_unknown_code_404():
    r = client.get("/nope-not-a-real-code", follow_redirects=False)
    assert r.status_code == 404


def test_missing_url_is_422():
    r = client.post("/shorten", json={})
    assert r.status_code == 422
