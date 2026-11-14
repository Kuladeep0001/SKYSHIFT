"""SPHEREx images: query a patch of sky, get aligned frames, compare epochs. Owner: Feature developer 1."""
from __future__ import annotations

from functools import lru_cache

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from ..models.schemas import (CompareRequest, CompareResponse, ImageInfo, ImageQuery, ImageQueryResponse,
                              Progress)
from ..services import image_processing as im
from ..services import jobs
from ..services import spectral_features as sf

router = APIRouter(prefix="/api/images", tags=["images"])


def job_or_404(query_id: str) -> jobs.Job:
    job = jobs.get(query_id)
    if job is None:
        raise HTTPException(404, {"status": "error", "error": "unknown_query",
                                  "message": "Unknown query_id. Send POST /api/images/query again."})
    return job


def ready_or_409(query_id: str) -> jobs.Job:
    job = job_or_404(query_id)
    if job.state != "done":
        raise HTTPException(409, {"status": "error", "error": "not_ready",
                                  "message": f"Images are still being prepared ({job.state}).",
                                  "progress": {"done": job.done, "total": job.total}})
    return job


def _frames_cached(query_id: str, mode: str, det: int, channel: int, visit: int):
    job = ready_or_409(query_id)
    return _frames_v(query_id, job.version, mode, det, channel, visit)


@lru_cache(maxsize=64)
def _frames_v(query_id: str, version: int, mode: str, det: int, channel: int, visit: int):
    """Cached per data version, so a refreshed spot never serves stale frames."""
    job = ready_or_409(query_id)
    return im.group_frames(job.arrays, job.meta, mode, det, channel, visit)


def _response(job: jobs.Job, bands: list[int] | None = None) -> ImageQueryResponse:
    status = {"done": "success", "error": "error", "cancelled": "cancelled"}.get(job.state, "pending")
    resp = ImageQueryResponse(status=status, query_id=job.id, message=job.message, freshness=job.freshness(),
                              progress=Progress(done=job.done, total=job.total, failed=job.failed))
    if status == "success":
        for band in bands or [0]:
            infos, _, _ = _frames_cached(job.id, "visit", band, 0, -1)
            for k, f in enumerate(infos):
                resp.images.append(ImageInfo(
                    id=f"{job.id}-b{band}-v{f['visit']}", epoch=f["date"][:10], date_range=f["date_range"],
                    band=band, visit=f["visit"], n_exposures=f["n_exp"], wavelength_um=f["wave"],
                    image_url=f"/api/images/{job.id}/frames/{k}.png?mode=visit&det={band}&v={job.version}"))
    return resp


@router.post("/query", response_model=ImageQueryResponse)
def query_images(q: ImageQuery):
    """Start gathering every SPHEREx exposure of a patch of sky (or reuse a finished one).

    The first time a spot is requested this downloads ~100-360 cutouts from NASA IRSA (1-4 minutes):
    the response says "pending". Poll GET /api/images/{query_id} until it says "success".
    """
    job = jobs.start(q.ra, q.dec, q.fov, q.release)
    return _response(job, q.bands)


@router.get("/{query_id}", response_model=ImageQueryResponse)
def image_info(query_id: str, bands: str = ""):
    """Progress, and when ready, one stacked image per visit (per requested detector band)."""
    b = [int(x) for x in bands.split(",") if x.strip().isdigit()] or None
    return _response(job_or_404(query_id), b)


@router.post("/{query_id}/check")
def check_for_new_data(query_id: str):
    """Ask NASA IRSA right now whether this spot has new or reprocessed images (at most every 2 minutes).

    If it has, the spot is rebuilt in the background: watch `freshness.refreshing` and `freshness.version`
    on GET /api/images/{query_id}.
    """
    job = ready_or_409(query_id)
    try:
        result = jobs.check(job)
    except Exception as e:
        raise HTTPException(502, {"status": "error", "error": "upstream", "message": f"IRSA check failed: {e}"})
    return {"result": result, "freshness": job.freshness()}


@router.post("/{query_id}/cancel")
def cancel_download(query_id: str):
    """Stop downloading this spot. Pictures already downloaded are kept, so asking again resumes."""
    job = job_or_404(query_id)
    return {**jobs.cancel(job), "status": job.state}


@router.get("/{query_id}/frames")
def frames(query_id: str, mode: str = "visit", det: int = Query(0, ge=0, le=6),
           channel: int = Query(0, ge=0, le=102), visit: int = -1):
    """Aligned frames as float32 pixels (base64), for the interactive viewer.

    mode: visit | exposure | channel | visitdet | planes (see API_DOCUMENTATION.md)
    """
    job = ready_or_409(query_id)
    try:
        return jobs.frames(job, mode, det, channel, visit)
    except ValueError as e:
        raise HTTPException(400, {"status": "error", "error": "bad_request", "message": str(e)})


@router.get("/{query_id}/frames/{k}.png")
def frame_png(query_id: str, k: int, mode: str = "visit", det: int = Query(0, ge=0, le=6),
              channel: int = Query(0, ge=0, le=102), visit: int = -1, contrast: float = Query(0.55, ge=0, le=1),
              v: int = 0):
    """One frame as a ready-to-show PNG (north up, east left)."""
    try:
        _, imgs, _ = _frames_cached(query_id, mode, det, channel, visit)
    except ValueError as e:
        raise HTTPException(400, {"status": "error", "error": "bad_request", "message": str(e)})
    if not 0 <= k < len(imgs):
        raise HTTPException(404, {"status": "error", "error": "no_such_frame", "message": f"frame {k} not found"})
    return Response(im.render_png(imgs[k], contrast=contrast), media_type="image/png",
                    headers={"Cache-Control": "public, max-age=3600"})


@router.get("/{query_id}/spectrum")
def spectrum(query_id: str, x: int, y: int, r: int = Query(1, ge=0, le=4)):
    """Brightness of one spot in every exposure, plus:

    - `binned`: one value per channel (1-102) = a continuous spectrum
    - `binned_by_visit`: the same, separately for each big visit (to see changes)
    - `features`: depth of known bands (water, CO2, CO, methane, hydrogen lines, minerals)
    - `ra`, `dec`: sky position of the pixel
    """
    job = ready_or_409(query_id)
    try:
        res = jobs.spectrum(job, x, y, r)
    except ValueError as e:
        raise HTTPException(400, {"status": "error", "error": "bad_request", "message": str(e)})
    pts = res["points"]
    res["binned"] = sf.bin_spectrum(pts)
    res["binned_by_visit"] = {str(v): sf.bin_spectrum([p for p in pts if p["visit"] == v]) for v in jobs.main_visits(job)}
    usable = [b for b in res["binned"] if not b["saturated"]]
    res["features"] = sf.measure_features(usable)
    res["saturated_fraction"] = round(sum(b["saturated"] for b in res["binned"]) / max(1, len(res["binned"])), 2)
    wcs = im.make_grid(job.ra, job.dec, job.fov)[0]
    ra, dec = wcs.pixel_to_world_values(x, y)
    res["ra"], res["dec"] = round(float(ra), 6), round(float(dec), 6)
    return res


def _visit_pair(job: jobs.Job, a: int | None, b: int | None) -> tuple[int, int]:
    vis = jobs.main_visits(job)
    a = vis[0] if a is None else a
    b = vis[-1] if b is None else b
    known = {m["visit"] for m in job.meta}
    if a not in known or b not in known:
        raise HTTPException(400, {"status": "error", "error": "bad_epoch",
                                  "message": f"epochs must be visit numbers in {sorted(known)}"})
    return a, b


@router.post("/compare", response_model=CompareResponse)
def compare(req: CompareRequest):
    """Subtract (or add) two visits. In a subtraction, movers show up as a blue/orange pair."""
    job = ready_or_409(req.query_id)
    a, b = _visit_pair(job, req.epoch_a, req.epoch_b)

    def info(v):
        ms = [m for m in job.meta if m["visit"] == v and (not req.band or m["det"] == req.band)]
        return {"visit": v, "start": ms[0]["date"][:10] if ms else None, "end": ms[-1]["date"][:10] if ms else None,
                "n_exposures": len(ms)}

    expl = ("Later visit minus earlier visit. Orange = brighter now (something is here now), "
            "blue = was brighter before (something was here before). A blue spot right next to an orange spot "
            "means the object MOVED. A lone orange or blue spot means it changed brightness."
            if req.op == "subtract" else "Both visits added together: fainter things become easier to see.")
    return CompareResponse(status="success", query_id=job.id, op=req.op, band=req.band, epoch_a=info(a),
                           epoch_b=info(b), explanation=expl,
                           image_url=f"/api/images/{job.id}/compare.png?a={a}&b={b}&band={req.band}&op={req.op}")


@router.get("/{query_id}/compare.png")
def compare_png(query_id: str, a: int, b: int, band: int = Query(0, ge=0, le=6), op: str = "subtract"):
    job = ready_or_409(query_id)
    ia, ib = jobs.visit_members(job, a, band), jobs.visit_members(job, b, band)
    try:
        res, _, _ = im.compare(job.arrays, job.meta, ia, ib, op)
    except ValueError as e:
        raise HTTPException(400, {"status": "error", "error": "bad_request", "message": str(e)})
    return Response(im.render_png(res, diverging=(op == "subtract")), media_type="image/png")
