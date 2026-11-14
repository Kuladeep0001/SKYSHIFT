"""How accurate is SkyShift? Measure the five challenge targets with SkyShift alone (SPHEREx pictures only)
and compare with the values in the catalogues. Shown on the website's "How it works" page.
Owner: Integration lead.
"""
from __future__ import annotations

import math
import time

from fastapi import APIRouter

from ..services import detection, jobs, resolver
from ..services import image_processing as im

router = APIRouter(tags=["validation"])

# (name to look up, detector band SkyShift uses, what to measure, what the catalogues say)
TARGETS = [
    ("Barnard's Star", 0, "mover", "Gaia DR3 proper motion (SIMBAD)"),
    ("eps Ind B", 7, "mover", "SIMBAD proper motion"),
    ("WISE 0855", 7, "mover", "SIMBAD proper motion (Spitzer/HST astrometry)"),
    ("RW Aur", 0, "variable", "Known variable: a young T Tauri star"),
    ("R Dra", 0, "variable", "Known variable: a Mira giant, period about 246 days"),
]
_cache: dict = {}


def _verdict(diff_pct: float, n_sigma: float | None) -> str:
    if diff_pct <= 5:
        return "excellent"
    if n_sigma is not None and n_sigma <= 2:
        return "agrees within the error"
    if diff_pct <= 15:
        return "close"
    return "off"


def _visit_brightness(job, band: int) -> list[tuple[str, float]]:
    """Aperture photometry of the target (centre of the picture) in each main visit: light inside a
    3-pixel circle minus the sky in a ring around it."""
    import numpy as np
    out = []
    for v in jobs.main_visits(job):
        idx = [m["i"] for m in job.meta if m["visit"] == v and detection.det_matches(m["det"], band)]
        if len(idx) < 3:
            continue
        img = detection._stack(job.arrays, idx)[0]
        n = img.shape[-1]
        yy, xx = np.mgrid[0:n, 0:n]
        r = np.hypot(xx - (n - 1) / 2, yy - (n - 1) / 2)
        sky = np.nanmedian(img[(r > 6) & (r < 10)])
        flux = float(np.nansum(img[r <= 3] - sky))
        date = next(m["date"][:7] for m in job.meta if m["visit"] == v)
        out.append((date, flux))
    return out


def _measure(q: str, band: int, kind: str, ref: str) -> dict:
    t = resolver.resolve(q)
    row = {"target": t["name"], "query": q, "kind": kind, "band": band, "reference": ref}
    job = jobs.start(t["ra"], t["dec"], 6.0, None)       # instant when the spot is already downloaded
    if job.state != "done":
        return {**row, "status": "downloading", "message": "Downloading this target from NASA; try again in a few minutes."}
    key = (job.id, job.version, band)
    if key not in _cache:
        grid = im.make_grid(job.ra, job.dec, job.fov)[0]
        _cache[key] = detection.run(job.arrays, job.meta, grid, jobs.main_visits(job), det=band)
    cands = _cache[key]["candidates"]
    n = job.arrays["flux"].shape[-1]
    c0 = (n - 1) / 2
    near = lambda c: math.hypot(c["x"] - c0, c["y"] - c0)
    known = math.hypot(t["pmra"], t["pmdec"]) / 1000
    known_pa = math.degrees(math.atan2(t["pmra"], t["pmdec"])) % 360
    row.update(status="ok", visits=len(jobs.main_visits(job)), known_arcsec_yr=round(known, 3), known_pa_deg=round(known_pa, 1))
    if kind == "mover":
        movers = sorted([c for c in cands if c["kind"] == "mover" and near(c) < 6], key=near)
        if not movers:
            return {**row, "status": "not_found", "message": "SkyShift did not pick out this mover."}
        m = movers[0]["motion"]
        err = m.get("total_err_arcsec_yr")
        diff = abs(m["total_arcsec_yr"] - known)
        diff_pct = 100 * diff / known if known else 0.0
        n_sigma = diff / err if err else None
        dpa = abs((m["pa_deg"] - known_pa + 180) % 360 - 180)
        row.update(measured_arcsec_yr=m["total_arcsec_yr"], measured_err_arcsec_yr=err, measured_pa_deg=m["pa_deg"],
                   n_visits=m.get("n_visits"), diff_pct=round(diff_pct, 1),
                   n_sigma=round(n_sigma, 1) if n_sigma is not None else None, pa_diff_deg=round(dpa, 1),
                   verdict=_verdict(diff_pct, n_sigma))
    else:
        # Brightness of the target itself in every visit (reddest detectors D5+D6: bright stars don't
        # overload them), then the biggest change between visits.
        moved = [c for c in cands if c["kind"] == "mover" and near(c) < 3]
        lc = [(d, f) for d, f in _visit_brightness(job, 7) if f > 0]
        if len(lc) < 2:
            return {**row, "status": "not_found", "message": "Not enough clean visits to compare brightness."}
        (d_lo, f_lo), (d_hi, f_hi) = min(lc, key=lambda x: x[1]), max(lc, key=lambda x: x[1])
        change = f_hi / f_lo
        row.update(brightness_change=round(change, 2), direction=f"brightest {d_hi}, faintest {d_lo}",
                   light_curve=[{"date": d, "flux_mjysr": round(f, 2)} for d, f in lc], band_used="D5+D6 (3.8-5 µm)",
                   stayed_put=not moved, verdict="agrees" if change > 1.2 and not moved else "unclear")
    return row


@router.get("/api/validation")
def validation():
    """SkyShift's own measurements of the challenge targets next to the catalogue values."""
    rows = [_measure(*t) for t in TARGETS]
    movers = [r for r in rows if r["kind"] == "mover" and r.get("status") == "ok"]
    return {
        "generated": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
        "method": ("Each target's pictures are stacked per visit. Movers: the star is found in every visit and a "
                   "straight line is fitted through its positions (least squares); the error comes from how well the "
                   "points fit the line. Variables: the brightness change between visits at the target's position. "
                   "Only SPHEREx pictures are used; the catalogue values are used only for this comparison."),
        "rows": rows,
        "summary": {"movers_checked": len(movers),
                    "median_diff_pct": round(sorted(r["diff_pct"] for r in movers)[len(movers) // 2], 1) if movers else None},
    }
