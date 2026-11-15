"""The reading-aloud voice endpoint: streams MP3, caches whole clips, answers 503 when the voice service fails
(so the website falls back to the device's voice). No network: edge-tts is replaced by a fake."""
from fastapi.testclient import TestClient

from backend.main import app
from backend.routes import voice

client = TestClient(app)


class FakeCommunicate:
    calls = 0
    fail = False

    def __init__(self, text, name, rate, pitch):
        FakeCommunicate.calls += 1
        self.text, self.name = text, name

    async def stream(self):
        if FakeCommunicate.fail:
            raise ConnectionError("offline")
        yield {"type": "WordBoundary", "text": "x"}
        for k in range(3):
            yield {"type": "audio", "data": f"[{self.name}:{k}]".encode()}


class FakeTTS:
    Communicate = FakeCommunicate


def setup(monkeypatch, tmp_path):
    monkeypatch.setattr(voice, "edge_tts", FakeTTS)
    monkeypatch.setattr(voice, "CACHE", tmp_path)
    FakeCommunicate.calls, FakeCommunicate.fail = 0, False


def test_streams_and_caches(monkeypatch, tmp_path):
    setup(monkeypatch, tmp_path)
    r = client.get("/api/voice", params={"text": "Good   evening.", "v": "butler"})
    assert r.status_code == 200 and r.headers["content-type"] == "audio/mpeg"
    assert r.content == b"[en-GB-ThomasNeural:0][en-GB-ThomasNeural:1][en-GB-ThomasNeural:2]"
    assert len(list(tmp_path.glob("*.mp3"))) == 1
    again = client.get("/api/voice", params={"text": "Good evening.", "v": "butler"})   # same words: from the cache
    assert again.content == r.content and FakeCommunicate.calls == 1
    other = client.get("/api/voice", params={"text": "Good evening.", "v": "friendly"})
    assert other.content.startswith(b"[en-GB-RyanNeural:0]") and FakeCommunicate.calls == 2


def test_bad_requests(monkeypatch, tmp_path):
    setup(monkeypatch, tmp_path)
    assert client.get("/api/voice", params={"text": "hi", "v": "alfred"}).status_code == 400
    assert client.get("/api/voice", params={"text": "   ", "v": "butler"}).status_code == 400
    assert client.get("/api/voice", params={"text": "x" * 3001}).status_code == 422


def test_voice_service_down_is_503(monkeypatch, tmp_path):
    setup(monkeypatch, tmp_path)
    FakeCommunicate.fail = True
    r = client.get("/api/voice", params={"text": "Hello there."})
    assert r.status_code == 503 and r.json()["detail"]["error"] == "voice_unavailable"
    assert not list(tmp_path.glob("*.mp3"))
    monkeypatch.setattr(voice, "edge_tts", None)
    assert client.get("/api/voice", params={"text": "Hello there."}).status_code == 503
