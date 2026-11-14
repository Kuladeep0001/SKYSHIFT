"""The detector finds a synthetic star that moved, with the right speed and direction."""
import numpy as np
import pytest

from backend.services import detection
from backend.services import image_processing as im


def star(n, x, y, flux=100.0, sigma=1.0):
    yy, xx = np.mgrid[0:n, 0:n]
    return flux * np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * sigma ** 2))


def make_visits(shift_px=1.5, n=41):
    rng = np.random.default_rng(1)
    frames, meta = [], []
    for v, (mjd, dx) in enumerate([(60900.0, 0.0), (61265.25, shift_px)]):   # one year apart
        for k in range(8):
            img = star(n, 20 + 0 * dx, 20 + dx) + star(n, 8, 30, 60) + rng.normal(0, 1, (n, n))
            frames.append(img)
            meta.append({"i": len(meta), "visit": v, "det": 1 + k % 6, "mjd": mjd + k * 0.1})
    flux = np.stack(frames).astype(np.float32)
    arrays = {"flux": flux, "var": np.ones_like(flux), "flags": np.zeros(flux.shape, np.int32)}
    return arrays, meta


def test_finds_mover_heading_north():
    arrays, meta = make_visits(shift_px=1.5)
    w = im.make_grid(100.0, 0.0, 41 * im.PIX_ARCSEC / 60)[0]
    res = detection.run(arrays, meta, w, [0, 1])
    movers = [c for c in res["candidates"] if c["kind"] == "mover"]
    assert movers, res["candidates"]
    m = movers[0]["motion"]
    assert m["total_arcsec_yr"] == pytest.approx(1.5 * im.PIX_ARCSEC, rel=0.25)
    assert min(m["pa_deg"], 360 - m["pa_deg"]) < 20          # north
    # the static star is not reported as moving
    assert all(abs(c["x"] - 8) > 2 or abs(c["y"] - 30) > 2 for c in movers)


def test_nothing_changes_nothing_found():
    arrays, meta = make_visits(shift_px=0.0)
    w = im.make_grid(100.0, 0.0, 41 * im.PIX_ARCSEC / 60)[0]
    res = detection.run(arrays, meta, w, [0, 1])
    assert not [c for c in res["candidates"] if c["kind"] == "mover"]
