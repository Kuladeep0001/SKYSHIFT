"""SPHEREx images: query a patch of sky, get aligned frames, compare epochs. Owner: Feature developer 1."""
from __future__ import annotations

import base64
from functools import lru_cache

import numpy as np

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from ..models.schemas import (CompareRequest, CompareResponse, ImageInfo, ImageQuery, ImageQueryResponse,
                              Progress)
from ..services import image_processing as im
from ..services import archival, jobs
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


@lru_cache(maxsize=12)
def _cube_v(query_id: str, version: int, visit: int):
    job = ready_or_409(query_id)
    return im.build_cube(job.arrays, job.meta, visit)


@router.get("/{query_id}/cube")
def cube(query_id: str, visit: int = -1):
    """Spectral cube: 102 planes x n x n, each plane ONE wavelength band over the whole area.

    Every pixel of every snapshot goes to the plane matching the wavelength that pixel saw, then all
    snapshots in a plane are averaged. `visit=-1` = all dates; a visit number = that visit only.
    Pixels are float16 (base64), row 0 = south. `data` = brightness (MJy/sr), `err` = 1-sigma.
    """
    job = ready_or_409(query_id)
    if visit >= 0 and visit not in {m["visit"] for m in job.meta}:
        raise HTTPException(400, {"status": "error", "error": "bad_visit", "message": f"no visit {visit}"})
    c = _cube_v(query_id, job.version, visit)
    to16 = lambda a: base64.b64encode(np.nan_to_num(a, nan=np.nan).astype(np.float16).tobytes()).decode()
    return {"n": c["n"], "planes": 102, "visit": visit, "version": job.version, "pix_arcsec": im.PIX_ARCSEC,
            "exposures_used": c["exposures_used"], "channels": c["channels"], "dtype": "float16",
            "data": to16(c["cube"]), "err": to16(c["err"])}


@lru_cache(maxsize=16)
def _history_v(query_id: str, version: int, ra: float, dec: float, fov: float):
    job = ready_or_409(query_id)
    h = archival.history(ra, dec, fov)
    gra, gdec = h["grid"]
    frames = [dict(f) for f in h["frames"]]
    infos, imgs, _ = im.group_frames(job.arrays, job.meta, "visit", 0, 0, -1)
    big = max((f["n_exp"] for f in infos), default=0)
    for f, img in zip(infos, imgs):
        if f["n_exp"] < 0.25 * big:
            continue  # only the big twice-a-year visits
        on = archival.spherex_on_grid(img, job.ra, job.dec, job.fov, gra, gdec)
        frames.append({"survey": "spherex", "label": "SPHEREx", "band": "infrared 0.75–5 µm (all detectors)",
                       "mjd": f["mjd"], "date": f["date"][:10], "year": round(2000 + (f["mjd"] - 51544.5) / 365.25, 2),
                       "coverage": round(float(np.isfinite(on).mean()), 3), "image": on})
    return {"n": h["n"], "scale_arcsec": h["scale_arcsec"], "frames": frames, "notes": h["notes"]}


@router.get("/{query_id}/history")
def history(query_id: str, ra: float = Query(..., ge=0, lt=360), dec: float = Query(..., ge=-90, le=90),
            fov: float = Query(12, ge=2, le=30)):
    """Time machine: this patch in older surveys (1950s and 1990s photographic plates, 2MASS ~2000,
    WISE 2010) plus SPHEREx, all on one north-up grid (240 x 240 px). The first call can take ~20 s.
    SPHEREx only covers the area that was loaded for `query_id`; outside it the pixels are empty (NaN)."""
    job = ready_or_409(query_id)
    h = _history_v(query_id, job.version, round(ra, 4), round(dec, 4), round(fov, 1))
    frames = h["frames"]
    data = np.stack([f["image"] for f in frames]).astype(np.float32) if frames else np.zeros((0, h["n"], h["n"]), np.float32)
    return {"n": h["n"], "scale_arcsec": h["scale_arcsec"], "count": len(frames), "notes": h["notes"],
            "center": {"ra": ra, "dec": dec}, "fov": fov,
            "frames": [{k: v for k, v in f.items() if k != "image"} for f in frames],
            "data": base64.b64encode(data.tobytes()).decode()}


@lru_cache(maxsize=16)
def _asteroids_v(query_id: str, version: int):
    """Known asteroids/comets inside the picture at the moment of each snapshot (IMCCE SkyBoT).

    One SkyBoT search per observing day (wide enough to catch anything that drifts in during that day),
    then each object's position is moved along its predicted track to the exact time of every snapshot.
    """
    import math
    from concurrent.futures import ThreadPoolExecutor
    from ..services import solar_system
    job = ready_or_409(query_id)
    wcs = im.make_grid(job.ra, job.dec, job.fov)[0]
    n = int(job.arrays["flux"].shape[-1])
    days: dict[int, list[dict]] = {}
    for m in job.meta:
        days.setdefault(int(m["mjd"]), []).append(m)
    radius = job.fov / 60 * 0.75 + 0.25

    def look(day):
        try:
            return day, solar_system.skybot(round(job.ra, 4), round(job.dec, 4), round(radius, 3), day + 0.5)
        except Exception:
            return day, {"objects": []}

    with ThreadPoolExecutor(max_workers=6) as ex:
        results = dict(ex.map(look, sorted(days)))
    objs: dict[str, dict] = {}
    for day, res in results.items():
        mid = day + 0.5
        for o in res.get("objects", []):
            for m in days[day]:
                dt_h = (m["mjd"] - mid) * 24
                dec = o["dec"] + o["ddec"] * dt_h / 3600
                ra = o["ra"] + o["dra"] * dt_h / 3600 / max(1e-6, math.cos(math.radians(o["dec"])))
                x, y = wcs.world_to_pixel_values(ra, dec)
                x, y = float(x), float(y)
                if not (0 <= x < n and 0 <= y < n):
                    continue
                if not np.isfinite(job.arrays["flux"][m["i"], int(y), int(x)]):
                    continue  # that snapshot doesn't cover this pixel
                rec = objs.setdefault(o["name"], {"name": o["name"], "number": o["num"], "class": o["class"],
                                                  "mag": o["mag"], "rate_arcsec_h": round(math.hypot(o["dra"], o["ddec"]), 1),
                                                  "appearances": []})
                rec["appearances"].append({"i": m["i"], "mjd": m["mjd"], "date": m["date"], "det": m["det"],
                                           "x": round(x, 2), "y": round(y, 2), "ra": round(ra, 6), "dec": round(dec, 6)})
    out = sorted(objs.values(), key=lambda o: o["mag"])
    for o in out:
        o["appearances"].sort(key=lambda a: a["mjd"])
        o["visible_guess"] = o["mag"] < 17.5  # roughly SPHEREx's single-snapshot limit for asteroids
    return {"objects": out, "days_checked": len(days), "radius_deg": round(radius, 3)}


@router.get("/{query_id}/asteroids")
def asteroids(query_id: str):
    """Known asteroids and comets that crossed this picture during SPHEREx's snapshots, with their position in each."""
    job = ready_or_409(query_id)
    return _asteroids_v(query_id, job.version)


@router.get("/{query_id}/frames")
def frames(query_id: str, mode: str = "visit", det: int = Query(0, ge=0, le=7),
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
def frame_png(query_id: str, k: int, mode: str = "visit", det: int = Query(0, ge=0, le=7),
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
