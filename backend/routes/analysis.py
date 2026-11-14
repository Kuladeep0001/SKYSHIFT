"""Moving-object / brightness-change detection. Owner: Feature developer 2."""
from __future__ import annotations

from fastapi import APIRouter

from ..models.schemas import DetectionRequest, DetectionResponse
from ..services import detection, jobs
from ..services import image_processing as im
from .images import ready_or_409

router = APIRouter(prefix="/api/detections", tags=["analysis"])
_cache: dict[tuple, dict] = {}

COMPASS = ["north", "north-east", "east", "south-east", "south", "south-west", "west", "north-west"]


def plain_english(c: dict, meta: list[dict]) -> str:
    """One or two sentences anyone can understand."""
    def visit_dates(v):
        ms = [m for m in meta if m["visit"] == v]
        return ms[0]["date"][:7] if ms else "?"

    when = f"between {visit_dates(c['visit_a'])} and {visit_dates(c['visit_b'])}"
    if c["kind"] == "mover":
        m = c["motion"]
        way = COMPASS[int(((m["pa_deg"] + 22.5) % 360) // 45)]
        speed = m["total_arcsec_yr"]
        text = (f"Something here moved toward the {way} {when}, at about {speed:.1f} arcseconds per year. "
                "Most stars move less than 0.1″ a year, so this is a fast, probably nearby, object.")
    elif c["kind"] == "variable":
        r = c["flux_change"].get("ratio") or 1
        text = (f"This object got about {r:.1f}× brighter {when}." if r >= 1
                else f"This object got about {1 / r:.1f}× fainter {when}.")
    elif c["kind"] == "appeared":
        text = f"A spot of light appeared {when} where there was nothing before."
    elif c["kind"] == "vanished":
        text = f"A spot of light that was here disappeared {when}."
    else:
        text = "A spot showed up in a single snapshot only: maybe an asteroid passing by, maybe a glitch."
    if c.get("saturated"):
        text += " (This star is so bright it overloads the camera, so treat the numbers as rough.)"
    return text


@router.post("/run", response_model=DetectionResponse)
def run_detection(req: DetectionRequest):
    """Find things that moved or changed brightness between visits of this patch."""
    job = ready_or_409(req.query_id)
    key = (job.id, job.version, req.band, req.threshold, req.include_transients)
    if key not in _cache:
        grid_wcs = im.make_grid(job.ra, job.dec, job.fov)[0]
        res = detection.run(job.arrays, job.meta, grid_wcs, jobs.main_visits(job), det=req.band,
                            threshold=req.threshold, include_transients=req.include_transients)
        for c in res["candidates"]:
            c["plain_english"] = plain_english(c, job.meta)
        _cache[key] = res
    res = _cache[key]
    return DetectionResponse(status="success", query_id=job.id, band=req.band, candidates=res["candidates"],
                             note=res["note"])
