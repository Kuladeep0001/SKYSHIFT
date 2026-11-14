"""SkyShift web server: the API plus the website itself.

Run locally:  uvicorn backend.app:app --reload --port 8000
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import catalogs, jobs, sphx

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"

app = FastAPI(title="SkyShift API", version="0.1",
              description="Watch the SPHEREx infrared sky change over time.")
app.add_middleware(GZipMiddleware, minimum_size=2000)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=["*"])


def _job_or_404(jid: str) -> jobs.Job:
    job = jobs.get(jid)
    if job is None:
        raise HTTPException(404, "Unknown job. Load the target again.")
    return job


def _ready(jid: str) -> jobs.Job:
    job = _job_or_404(jid)
    if job.state != "done":
        raise HTTPException(409, f"Job not ready yet ({job.state}).")
    return job


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/releases")
def releases(refresh: bool = False):
    """Every SPHEREx data release at IRSA. New releases appear here automatically."""
    return sphx.releases(force=refresh)


@app.get("/api/resolve")
def resolve(q: str = Query(..., min_length=1, max_length=200)):
    try:
        return catalogs.resolve(q.strip())
    except LookupError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(502, f"Name lookup failed: {e}")


@app.get("/api/load")
def load(ra: float = Query(..., ge=0, lt=360), dec: float = Query(..., ge=-90, le=90),
         fov: float = Query(6.0, ge=1, le=60), rel: str = ""):
    """Start (or reuse) a job that gathers all SPHEREx exposures of this patch."""
    rels = [r for r in rel.split(",") if r] if rel else None
    job = jobs.start(ra, dec, fov, rels)
    return job.status()


@app.get("/api/job/{jid}")
def job_status(jid: str):
    return _job_or_404(jid).status()


@app.get("/api/job/{jid}/summary")
def job_summary(jid: str):
    return jobs.summary(_ready(jid))


@app.get("/api/job/{jid}/frames")
def job_frames(jid: str, mode: str = "visit", det: int = Query(0, ge=0, le=6),
               channel: int = Query(0, ge=0, le=102), visit: int = -1):
    try:
        return jobs.frames(_ready(jid), mode, det, channel, visit)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/job/{jid}/spectrum")
def job_spectrum(jid: str, x: int, y: int, r: int = 1):
    try:
        return jobs.spectrum(_ready(jid), x, y, r)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/catalog/{name}")
def catalog(name: str, ra: float, dec: float, radius: float = Query(0.1, gt=0, le=0.5), mjd: float = 0):
    try:
        ra, dec, radius = round(ra, 4), round(dec, 4), round(radius, 3)
        if name == "gaia":
            return catalogs.gaia(ra, dec, radius)
        if name == "allwise":
            return catalogs.allwise(ra, dec, radius)
        if name == "skybot":
            if not mjd:
                raise HTTPException(400, "mjd is required for asteroid lookups")
            return catalogs.skybot(ra, dec, radius, round(mjd, 3))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"{name} lookup failed: {e}")
    raise HTTPException(404, "Catalog must be gaia, allwise or skybot")


@app.get("/embed")
def embed():
    return FileResponse(FRONTEND / "index.html")


app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="site")
