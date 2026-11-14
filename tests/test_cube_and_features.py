"""Spectral cube (one wavelength per plane) and the molecule/mineral finder."""
import numpy as np

from backend.services import detection
from backend.services import image_processing as im
from backend.services import spectral_features as sf


def test_cube_puts_each_pixel_in_its_own_wavelength_plane():
    n = 10
    # one exposure on detector 1 whose wavelength changes from left to right (like SPHEREx's filter)
    lo, hi = 0.75, 1.10
    wave = np.tile(np.linspace(lo * 1.001, hi * 0.999, n), (n, 1)).astype(np.float32)
    flux = np.tile(np.arange(n, dtype=np.float32), (n, 1))
    arrays = {"flux": flux[None], "var": np.ones((1, n, n), np.float32), "wave": wave[None],
              "flags": np.zeros((1, n, n), np.int32)}
    meta = [{"i": 0, "det": 1, "visit": 0, "em_min": lo, "em_max": hi, "mjd": 60900.0}]
    c = im.build_cube(arrays, meta)
    assert c["cube"].shape == (102, n, n)
    left_plane = im.channel_map(1, wave, {1: (lo, hi)})[0, 0]
    right_plane = im.channel_map(1, wave, {1: (lo, hi)})[0, -1]
    assert left_plane == 0 and right_plane == 16                  # D1 covers planes 1..17
    assert c["cube"][0, 0, 0] == 0 and np.isnan(c["cube"][0, 0, -1])  # column 0 only in plane 1
    assert c["cube"][16, 0, -1] == n - 1


def _spectrum(dips):
    w = np.linspace(0.75, 5.0, 102)
    f = np.full_like(w, 1000.0)
    for c, depth, width in dips:
        f *= 1 - depth * np.exp(-0.5 * ((w - c) / width) ** 2)
    return [{"channel": i + 1, "wave": float(x), "flux": float(y), "err": 5.0, "n": 5, "saturated": False}
            for i, (x, y) in enumerate(zip(w, f))]


def test_water_dip_is_found():
    feats = sf.measure_features(_spectrum([(1.4, 0.5, 0.05)]))
    water = next(f for f in feats if f["name"].startswith("H₂O vapour 1.4"))
    assert water["status"] == "likely" and water["change_pct"] < -20


def test_bump_between_two_dips_is_not_called_hydrogen():
    feats = sf.measure_features(_spectrum([(1.15, 0.6, 0.05), (1.4, 0.6, 0.05)]))
    pab = next(f for f in feats if f["name"].startswith("Paschen"))
    assert pab["status"] in ("ambiguous", "not seen")


def test_reddest_two_detectors_option():
    assert detection.det_matches(5, 7) and detection.det_matches(6, 7) and not detection.det_matches(4, 7)
    assert detection.det_matches(3, 0) and detection.det_matches(3, 3) and not detection.det_matches(2, 3)
