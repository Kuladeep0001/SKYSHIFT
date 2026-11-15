"""SkyShift API + website.

Run locally:   uvicorn backend.main:app --reload --port 8000
API docs:      http://localhost:8000/docs
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .routes import analysis, ask, checks, crossmatch, finds, images, metadata, report, sky, validation, verification, voice
from .services import watcher

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "frontend" / "dist"  # built React app (npm run build)

app = FastAPI(title="SkyShift API", version="0.2",
              description="Watch the SPHEREx infrared sky change over time. See API_DOCUMENTATION.md.")
app.add_middleware(GZipMiddleware, minimum_size=2000)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET", "POST"], allow_headers=["*"])

for r in (images.router, analysis.router, checks.router, verification.router, crossmatch.router, metadata.router, finds.router, ask.router, sky.router, validation.router, report.router, voice.router):
    app.include_router(r)



@app.on_event("startup")
def _start_watcher():
    watcher.start()  # keeps cached spots up to date with new NASA releases


if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        """Serve the React app; unknown paths fall back to index.html (so /embed?... works)."""
        f = DIST / path
        if path and f.is_file() and DIST in f.resolve().parents:
            return FileResponse(f)
        # Data paths must say "not found", never return the web page: Aladin read the page as the
        # colour sky's Moc.fits (sky coverage) and then drew nothing.
        if path.startswith(("api/", "hips/", "mock/")):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        return FileResponse(DIST / "index.html")
else:
    @app.get("/", include_in_schema=False)
    def no_frontend():
        return JSONResponse({"message": "API is running. Build the website with: cd frontend && npm install && "
                                        "npm run build  (or run `npm run dev` and open http://localhost:5173)",
                             "docs": "/docs"})
