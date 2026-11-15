"""Metadata, data releases and name lookup. Owner: Integration lead."""
from __future__ import annotations

import numpy as np
from fastapi import APIRouter, HTTPException, Query

from ..services import image_processing as im
from ..services import coords, jobs, resolver, spherex, watcher
from .images import job_or_404, ready_or_409

router = APIRouter(tags=["metadata"])


@router.get("/api/health")
def health():
    return {"status": "ok"}


@router.get("/api/releases")
def releases(refresh: bool = False):
    """Every SPHEREx release at IRSA (new ones appear automatically) and the default 'best' combination."""
    return spherex.releases(force=refresh)


@router.get("/api/updates")
def updates():
    """Freshness feed: when SkyShift last checked NASA/ESA for new data, what it found, what's next."""
    return watcher.status()


@router.post("/api/updates/run")
def run_updates():
    """Check every cached spot for new data right now (at most once every 10 minutes)."""
    import threading
    import time
    last = watcher.STATE["last_run"]
    if watcher.STATE["running"] or (last and time.time() - last < 600):
        raise HTTPException(429, {"status": "error", "error": "too_soon",
                                  "message": "A check ran in the last 10 minutes (or is running now)."})
    threading.Thread(target=watcher.run_once, daemon=True).start()
    return {"started": True}


@router.get("/api/resolve")
def resolve(q: str = Query(..., min_length=1, max_length=200)):
    """Name or coordinates -> RA/Dec. Fast-moving stars are moved to where they are today."""
    try:
        return resolver.resolve(q.strip())
    except LookupError as e:
        raise HTTPException(404, {"status": "error", "error": "not_found", "message": str(e)})
    except Exception as e:
        raise HTTPException(502, {"status": "error", "error": "upstream", "message": f"Name lookup failed: {e}"})


@router.get("/api/resolve/position")
def resolve_position(a: str = Query("", max_length=80), b: str = Query("", max_length=80),
                     frame: str = Query("icrs", pattern="^(icrs|galactic|earth)$")):
    """Two boxes -> RA/Dec, reading whatever was typed forgivingly (see services/coords.py).
    `frame`: `icrs` (a = RA, b = Dec), `galactic` (a = longitude l, b = latitude b) or `earth` (a = latitude,
    b = longitude of a place on Earth: the sky straight above it right now). Both numbers pasted into `a`
    are split (`split` gives the two halves). Returns `ra`, `dec` (ICRS degrees), `read_a`/`read_b` (how each
    box was read), `read`, `label`. A box that can't be read: 400 with `field` ("a" or "b") and a plain message."""
    try:
        return coords.position(a, b, frame)
    except coords.CoordError as e:
        raise HTTPException(400, {"status": "error", "error": "bad_coordinates", "field": getattr(e, "field", "a"), "message": str(e)})


@router.get("/api/metadata/{query_id}")
def metadata(query_id: str):
    """Everything about a query: exposures, visits, the 102 channels, detectors, flag meanings."""
    job = job_or_404(query_id)
    if job.state != "done":
        return {"status": job.status()}
    return jobs.summary(job)


@router.get("/api/metadata/{query_id}/exposure/{i}")
def exposure_metadata(query_id: str, i: int):
    """One exposure: when, which detector, wavelength, and how much of it is flagged (and why)."""
    job = ready_or_409(query_id)
    if not 0 <= i < len(job.meta):
        raise HTTPException(404, {"status": "error", "error": "no_such_exposure", "message": f"exposure {i}"})
    flags = job.arrays["flags"][i]
    covered = np.isfinite(job.arrays["flux"][i])
    stats = {name: round(float((((flags & (1 << bit)) != 0) & covered).mean() * 100), 2)
             for name, bit in im.FLAG_BITS.items()}
    return {**job.meta[i], "flag_percent": {k: v for k, v in stats.items() if v > 0},
            "flag_meanings": {k: v["meaning"] for k, v in job.flag_defs.items()}}
