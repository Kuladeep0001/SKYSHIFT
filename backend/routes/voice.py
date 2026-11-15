"""Reading aloud in a natural, human-sounding voice: GET /api/voice?text=...&v=butler -> MP3 audio.

The Listen tab, the guided tour and "Ask" answers are spoken with this. The voices are Microsoft neural
voices (the ones Edge's Read Aloud uses), reached through the `edge-tts` package. The sound is streamed
as it is made, so speech starts after about a second, and every finished clip is cached in data/voice,
so anything said before plays instantly. If the voice service can't be reached the answer is 503 and the
website falls back to the device's own voice. Owner: Integration lead."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse

try:
    import edge_tts
except ImportError:  # optional: without it the website uses the device's voice
    edge_tts = None

router = APIRouter(tags=["voice"])

ROOT = Path(__file__).resolve().parents[2]
CACHE = Path(os.environ.get("SKYSHIFT_VOICE_CACHE", ROOT / "data" / "voice"))
MAX_FILES = 4000

# id -> (neural voice, speed, pitch)
VOICES = {
    "butler": ("en-GB-ThomasNeural", "-8%", "-4Hz"),   # a calm, unhurried older British gentleman
    "friendly": ("en-GB-RyanNeural", "-3%", "+0Hz"),   # a brighter, warmer British narrator
}
HEADERS = {"Cache-Control": "public, max-age=604800"}


def _unavailable(why: str) -> HTTPException:
    return HTTPException(503, {"status": "error", "error": "voice_unavailable",
                               "message": f"The natural voice isn't available right now ({why}); using the device's voice."})


def _save(path: Path, data: bytes) -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.stem}.{os.getpid()}.part")
    tmp.write_bytes(data)
    os.replace(tmp, path)
    files = sorted(CACHE.glob("*.mp3"), key=lambda p: p.stat().st_mtime)
    for old in files[: max(0, len(files) - MAX_FILES)]:   # keep the cache small: forget the oldest clips
        old.unlink(missing_ok=True)


@router.get("/api/voice", response_class=StreamingResponse,
            responses={200: {"content": {"audio/mpeg": {}}}, 503: {"description": "voice service unreachable"}})
async def voice(text: str = Query(..., min_length=1, max_length=3000), v: str = Query("butler")):
    """Speak `text` (up to 3000 characters) in voice `v`: `butler` (default) or `friendly`. Returns MP3."""
    if v not in VOICES:
        raise HTTPException(400, {"status": "error", "error": "bad_request", "message": f"v must be one of {sorted(VOICES)}"})
    text = " ".join(text.split())
    if not text:
        raise HTTPException(400, {"status": "error", "error": "bad_request", "message": "text is empty"})
    path = CACHE / f"{hashlib.sha1(f'{v}|{text}'.encode()).hexdigest()}.mp3"
    if path.exists():
        return FileResponse(path, media_type="audio/mpeg", headers=HEADERS)
    if edge_tts is None:
        raise _unavailable("edge-tts is not installed")

    name, rate, pitch = VOICES[v]
    stream = edge_tts.Communicate(text, name, rate=rate, pitch=pitch).stream()
    # Wait for the first sound before answering, so a failure is a clean 503 (the page then uses the device voice).
    first = None
    try:
        async for chunk in stream:
            if chunk["type"] == "audio" and chunk["data"]:
                first = chunk["data"]
                break
    except Exception as e:  # network down, service changed...
        await stream.aclose()
        raise _unavailable(type(e).__name__) from e
    if first is None:
        raise _unavailable("no audio came back")

    async def body():
        parts, complete = [first], False
        try:
            yield first
            async for chunk in stream:
                if chunk["type"] == "audio" and chunk["data"]:
                    parts.append(chunk["data"])
                    yield chunk["data"]
            complete = True
        finally:
            await stream.aclose()
            if complete:  # only whole clips are cached (not ones cut short by Stop)
                _save(path, b"".join(parts))

    return StreamingResponse(body(), media_type="audio/mpeg", headers=HEADERS)
