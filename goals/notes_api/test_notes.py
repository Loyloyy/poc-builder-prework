"""Acceptance suite for the Notes API goal — the agent must NOT edit this. Exercises status codes
(201/204/404/422), CRUD round-trips, and validation across multiple endpoints."""

from fastapi.testclient import TestClient

from app import app

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_create_returns_201():
    r = client.post("/notes", json={"text": "hello"})
    assert r.status_code == 201
    body = r.json()
    assert body["text"] == "hello"
    assert "id" in body


def test_create_and_get_roundtrip():
    nid = client.post("/notes", json={"text": "roundtrip"}).json()["id"]
    g = client.get(f"/notes/{nid}")
    assert g.status_code == 200
    assert g.json()["text"] == "roundtrip"


def test_list_contains_created():
    client.post("/notes", json={"text": "listme"})
    r = client.get("/notes")
    assert r.status_code == 200
    assert any(n["text"] == "listme" for n in r.json())


def test_delete_then_404():
    nid = client.post("/notes", json={"text": "bye"}).json()["id"]
    d = client.delete(f"/notes/{nid}")
    assert d.status_code == 204
    assert client.get(f"/notes/{nid}").status_code == 404


def test_get_unknown_404():
    assert client.get("/notes/999999").status_code == 404


def test_create_missing_text_422():
    assert client.post("/notes", json={}).status_code == 422
