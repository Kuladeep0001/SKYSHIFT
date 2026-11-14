"""Catalogue cross-check (merged from the verification branch): evidence logic, epoch handling, input checks.
These tests do not touch the network."""
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from backend.main import app
from backend.models.verification import CandidateInput
from backend.routes.crossmatch import build_evidence_summary, candidate_motion_reference, gaia_confirmed
from backend.services.allwise import ALLWISE_MOTION_EPOCH, propagate_gaia_to_epoch
from backend.services.crossmatch import crossmatch_catalogues


def _match(sep, quality="within_radius", **extra):
    return {"status": "match_found", "match_quality": quality, "matching_radius_arcsec": 6.0,
            "nearest_source": {"separation_arcsec": sep, **extra}, "epoch_correction_available": True}


def test_confirmed_when_any_catalogue_matches():
    res = {"gaia": _match(0.2, source_id="1"), "simbad": _match(0.1, main_id="X")}
    assessment, summary = build_evidence_summary(res)
    assert assessment == "confirmed_association"
    assert summary["confirmed_associations"] == 2


def test_no_association_and_unreachable_are_different():
    nothing = {"gaia": {"status": "no_match", "match_quality": "outside_radius"}}
    assert build_evidence_summary(nothing)[0] == "no_association"
    down = {"gaia": {"status": "inconclusive", "nearest_source": None}}
    assert build_evidence_summary(down)[0] == "insufficient_evidence"


def test_borderline_is_never_confirmed():
    res = {"gaia": {"status": "no_match", "match_quality": "borderline", "nearest_source": {"separation_arcsec": 6.5}}}
    assert build_evidence_summary(res)[0] == "potential_association"


def test_candidate_motion_reaches_the_allwise_epoch():
    # WISE 0855 moves ~8.1"/yr: between 2010.5 (AllWISE) and 2026 that is ~2 arcmin.
    cand = CandidateInput(candidate_id="w0855", ra=133.7598, dec=-7.2422,
                          observation_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
                          pmra_mas_yr=-8118.0, pmdec_mas_yr=673.0)
    ref = candidate_motion_reference(cand)
    assert gaia_confirmed(ref)
    ra, dec = propagate_gaia_to_epoch(ref, ALLWISE_MOTION_EPOCH)
    years = 2026.0 - ALLWISE_MOTION_EPOCH
    assert abs((dec - cand.dec) * 3600 - (-0.673 * years)) < 0.5      # went back south
    assert (ra - cand.ra) * 3600 > 100                                # and ~2' east (RA larger)


def test_crossmatch_needs_a_gaia_reference():
    out = crossmatch_catalogues({"simbad": _match(0.1)}, 6.0)
    assert out["status"] == "not_assessable"


def test_request_validation():
    c = TestClient(app)
    # no timezone on the observation time -> rejected before any catalogue is queried
    r = c.post("/api/verification/", json={"candidates": [{"candidate_id": "a", "ra": 10, "dec": 10,
                                                            "observation_time": "2026-01-01T00:00:00"}]})
    assert r.status_code == 422
    r = c.post("/api/verification/", json={"candidates": []})
    assert r.status_code == 422
