"""API contract checks that don't need NASA (error formats, validation)."""
from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)


def test_health():
    assert client.get("/api/health").json() == {"status": "ok"}


def test_resolve_coordinates():
    r = client.get("/api/resolve", params={"q": "133.795 -7.245"}).json()
    assert r["ra"] == 133.795 and r["source"] == "coordinates"


def test_unknown_query_is_404_with_message():
    r = client.get("/api/images/doesnotexist")
    assert r.status_code == 404
    assert r.json()["detail"]["error"] == "unknown_query"


def test_query_validation():
    assert client.post("/api/images/query", json={"ra": 500, "dec": 0}).status_code == 422


def test_verification_needs_position():
    assert client.post("/api/verification/gaia", json={"candidate_id": "C1"}).status_code == 422
