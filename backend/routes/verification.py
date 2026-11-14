"""Check candidates against other telescopes (Gaia, WISE, known asteroids), plus overlay catalogues.

Owner: Verification developer.
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException, Query

from ..models.schemas import Candidate, VerificationRequest, VerificationResult
from ..services import gaia as cat
from ..services import object_info, solar_system

router = APIRouter(tags=["verification"])

FAST_PM_MAS_YR = 100  # faster than this = clearly a nearby/fast-moving object


def _year(c: Candidate) -> float:
    if c.mjd:
        return cat.mjd_to_year(c.mjd)
    if c.epoch:
        d = date.fromisoformat(c.epoch[:10])
        return d.year + (d.timetuple().tm_yday - 0.5) / 365.25
    return 2026.0


def _mjd(c: Candidate) -> float:
    return c.mjd or (_year(c) - 2000.0) * 365.25 + 51544.5


def verify_one(c: Candidate, radius_arcsec: float = 12.0) -> VerificationResult:
    year = _year(c)
    # Query a generous cone (fast stars may be far from their 2016 catalogue position), cached per area.
    # Each archive is checked on its own, so one slow service doesn't block the other.
    gm = wm = None
    errors = []
    try:
        gm = cat.crossmatch(c.ra, c.dec, year, cat.gaia(round(c.ra, 2), round(c.dec, 2), 0.06), radius_arcsec)
    except Exception as e:
        errors.append(f"Gaia: {e}")
    try:
        wm = cat.crossmatch(c.ra, c.dec, year, cat.allwise(round(c.ra, 2), round(c.dec, 2), 0.06), radius_arcsec * 1.5)
    except Exception as e:
        errors.append(f"WISE: {e}")
    if gm is None and wm is None:
        return VerificationResult(candidate_id=c.candidate_id, matches=[], verification_status="pending",
                                  plain_english="Couldn't reach the Gaia/WISE archives right now. Try again in a minute.")
    gm, wm = gm or [], wm or []
    matches = [{k: m[k] for k in ("catalog", "id", "ra", "dec", "mag", "sep_arcsec", "pm_total") if k in m}
               for m in gm[:3] + wm[:2]]

    if c.kind in ("transient", "appeared"):
        try:
            sb = solar_system.skybot(round(c.ra, 4), round(c.dec, 4), 0.02, round(_mjd(c), 3))
            near = [o for o in sb["objects"] if cat.sep_arcsec(c.ra, c.dec, o["ra"], o["dec"]) < 30]
            if near:
                o = near[0]
                matches.insert(0, {"catalog": "SkyBoT", "id": o["name"], "ra": o["ra"], "dec": o["dec"],
                                   "mag": o["mag"], "class": o["class"],
                                   "sep_arcsec": round(cat.sep_arcsec(c.ra, c.dec, o["ra"], o["dec"]), 1)})
                return VerificationResult(candidate_id=c.candidate_id, matches=matches,
                                          verification_status="known_asteroid",
                                          plain_english=f"That's the known asteroid {o['name']} ({o['class']}) passing by.")
        except Exception:
            pass

    if gm:
        best = gm[0]
        if best["pm_total"] > FAST_PM_MAS_YR:
            measured = (c.motion or {}).get("total_arcsec_yr")
            extra = (f" Gaia says it moves {best['pm_total'] / 1000:.2f}″ per year; SkyShift measured "
                     f"{measured:.2f}″ per year from SPHEREx alone.") if measured else ""
            return VerificationResult(candidate_id=c.candidate_id, matches=matches, verification_status="known_mover",
                                      plain_english="✓ Confirmed: a known fast-moving star in Gaia." + extra)
        return VerificationResult(
            candidate_id=c.candidate_id, matches=matches, verification_status="known_star",
            plain_english="✓ A known star (in Gaia). If it changed brightness, it may be a variable star."
            if c.kind != "mover" else "A known star that Gaia says barely moves, so this 'motion' is probably "
                                      "a processing artefact.")
    if wm:
        return VerificationResult(
            candidate_id=c.candidate_id, matches=matches, verification_status="known_star",
            plain_english="Seen by WISE but not by Gaia: it's very red or cold. Brown dwarfs look like this!")
    return VerificationResult(
        candidate_id=c.candidate_id, matches=matches, verification_status="unmatched",
        plain_english="? Not in Gaia or WISE. Could be something new, or an artefact. Worth a human look!")


@router.post("/api/verification/gaia")
def verify(req: VerificationRequest):
    """Cross-match candidates with Gaia DR3 and AllWISE (and SkyBoT for one-off spots).

    Send one candidate ({candidate_id, ra, dec, epoch}) to get one result, or {"candidates": [...]}
    to get a list.
    """
    if req.candidates:
        return [verify_one(c, req.radius_arcsec) for c in req.candidates]
    if req.ra is None or req.dec is None:
        raise HTTPException(422, {"status": "error", "error": "missing_position",
                                  "message": "Send ra and dec, or a list of candidates."})
    c = Candidate(candidate_id=req.candidate_id or "C000", ra=req.ra, dec=req.dec, epoch=req.epoch, kind=req.kind,
                  motion=req.motion)
    return verify_one(c, req.radius_arcsec)


@router.get("/api/catalog/{name}")
def catalog(name: str, ra: float, dec: float, radius: float = Query(0.1, gt=0, le=0.5), mjd: float = 0):
    """Overlay data: gaia (Gaia DR3, epoch 2016), allwise (epoch ~2010.5), skybot (asteroids at mjd)."""
    ra, dec, radius = round(ra, 4), round(dec, 4), round(radius, 3)
    try:
        if name == "gaia":
            return cat.gaia(ra, dec, radius)
        if name == "allwise":
            return cat.allwise(ra, dec, radius)
        if name == "skybot":
            if not mjd:
                raise HTTPException(400, {"status": "error", "error": "missing_mjd", "message": "mjd is required"})
            return solar_system.skybot(ra, dec, radius, round(mjd, 3))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, {"status": "error", "error": "upstream", "message": f"{name} lookup failed: {e}"})
    raise HTTPException(404, {"status": "error", "error": "unknown_catalog",
                              "message": "catalog must be gaia, allwise or skybot"})


@router.get("/api/object")
def object_details(ra: float = Query(..., ge=0, lt=360), dec: float = Query(..., ge=-90, le=90), mjd: float = 0,
                   name: str | None = None):
    """Details card for whatever is at (ra, dec): SIMBAD type/distance/papers, Gaia, WISE, Wikipedia, links."""
    year = cat.mjd_to_year(mjd) if mjd else 2026.0
    return object_info.details(round(ra, 6), round(dec, 6), year, name)
