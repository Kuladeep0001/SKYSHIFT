"""Time machine: the same patch of sky in older surveys, lined up with SPHEREx.

  1950s  Palomar Observatory Sky Survey I (POSS-I, red photographic plates)   STScI DSS
  1990s  POSS-II / UK Schmidt (red plates)                                    STScI DSS
  ~2000  2MASS, Ks band 2.2 µm                                                NASA IRSA
  2010   WISE (AllWISE), W1 band 3.4 µm                                       NASA IRSA
  now    SPHEREx                                                              NASA IRSA

Every image is resampled onto one common north-up grid so they can be blinked together.
Owner: Feature developer 1.
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import io
import warnings
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import numpy as np
from astropy.io import fits
from astropy.wcs import WCS

from . import image_processing as im
from .spherex import CACHE, IRSA_SIA, SESSION

warnings.filterwarnings("ignore", module="astropy")
ARCH = CACHE / "archival"
ARCH.mkdir(parents=True, exist_ok=True)
DSS = "https://archive.stsci.edu/cgi-bin/dss_search"

SURVEYS = [
    {"id": "poss1", "label": "Palomar Sky Survey I", "band": "red light (0.65 µm), glass photographic plate", "kind": "dss", "v": "poss1_red"},
    {"id": "poss2", "label": "Palomar Sky Survey II", "band": "red light (0.65 µm), glass photographic plate", "kind": "dss", "v": "poss2ukstu_red"},
    {"id": "2mass", "label": "2MASS", "band": "infrared Ks (2.2 µm)", "kind": "irsa", "collection": "twomass_allsky", "bandname": "K"},
    {"id": "wise", "label": "WISE", "band": "infrared W1 (3.4 µm)", "kind": "irsa", "collection": "wise_allwise", "bandname": "W1"},
]


def mjd_from_iso(d: str) -> float:
    y, m, dd = (int(x) for x in d[:10].split("-"))
    return (date(y, m, dd) - date(1858, 11, 17)).days


def _cache_path(sid: str, ra: float, dec: float, size: float) -> Path:
    key = hashlib.sha1(f"{sid}|{ra:.4f}|{dec:.4f}|{size:.3f}".encode()).hexdigest()[:20]
    return ARCH / f"{sid}_{key}.fits"


def _read_fits_bytes(b: bytes) -> fits.HDUList:
    if b[:2] == b"\x1f\x8b":
        b = gzip.decompress(b)
    return fits.open(io.BytesIO(b))


def _cached(path: Path):
    with fits.open(path) as h:
        return h[0].data.astype(np.float32), h[0].header, float(h[0].header["SKYMJD"])


def _store(path: Path, data: np.ndarray, hdr: fits.Header, mjd: float):
    hdr = hdr.copy()
    hdr["SKYMJD"] = mjd
    fits.PrimaryHDU(data=data, header=hdr).writeto(path, overwrite=True)
    return data, hdr, mjd


def fetch(s: dict, ra: float, dec: float, size_deg: float) -> list[tuple[np.ndarray, fits.Header, float]]:
    """Images of one survey covering a square around (ra, dec): [(data, header, mjd)]. Cached on disk.

    Survey images come in tiles (2MASS strips are only 8.5' wide), so we fetch every tile that overlaps.
    """
    base = _cache_path(s["id"], ra, dec, size_deg)
    done = sorted(base.parent.glob(base.stem + "*.fits"))
    if done:
        return [_cached(p) for p in done]
    out = []
    if s["kind"] == "dss":
        arcmin = min(60.0, size_deg * 60)
        r = SESSION.get(DSS, params={"v": s["v"], "r": f"{ra:.6f}", "d": f"{dec:.6f}", "e": "J2000", "h": f"{arcmin:.2f}",
                                     "w": f"{arcmin:.2f}", "f": "fits", "c": "none"}, timeout=90)
        r.raise_for_status()
        if r.content[:6] == b"SIMPLE":
            h = _read_fits_bytes(r.content)
            hdr = h[0].header
            out.append(_store(base.with_name(base.stem + "_0.fits"), h[0].data.astype(np.float32), hdr,
                              float(mjd_from_iso(str(hdr.get("DATE-OBS", "1950-01-01"))))))
        return out
    r = SESSION.get(IRSA_SIA, params={"COLLECTION": s["collection"], "POS": f"circle {ra:.6f} {dec:.6f} {size_deg / 2:.4f}",
                                      "RESPONSEFORMAT": "CSV"}, timeout=60)
    r.raise_for_status()
    rows, seen = [], set()
    for x in csv.DictReader(io.StringIO(r.text)):
        u = x.get("access_url", "")
        if (x.get("energy_bandpassname") == s["bandname"] and x.get("dataproduct_subtype", "science") == "science"
                and ".fits" in u and "unc" not in u and "cov" not in u and u not in seen):
            seen.add(u)
            rows.append(x)
    for k, row in enumerate(rows[:8]):
        try:
            c = SESSION.get(row["access_url"], params={"center": f"{ra:.6f},{dec:.6f}", "size": f"{size_deg:.4f}"}, timeout=120)
            if c.status_code != 200 or len(c.content) < 2880:
                continue
            h = _read_fits_bytes(c.content)
            hdu = next(x for x in h if x.data is not None)
            mjd = (float(row["t_min"]) + float(row["t_max"])) / 2 if row.get("t_max") else float(row["t_min"])
            out.append(_store(base.with_name(f"{base.stem}_{k}.fits"), hdu.data.astype(np.float32), hdu.header, mjd))
        except Exception:
            continue
    return out


def _box_blur(img: np.ndarray, k: int) -> np.ndarray:
    """Average over k x k boxes (prevents sparkly aliasing when shrinking a sharp image)."""
    if k <= 1:
        return img
    a = np.nan_to_num(img, nan=float(np.nanmedian(img)))
    c = np.cumsum(np.cumsum(np.pad(a, ((1, 0), (1, 0))), 0), 1)
    h, w = a.shape
    r = k // 2
    y0 = np.clip(np.arange(h) - r, 0, h); y1 = np.clip(np.arange(h) + r + 1, 0, h)
    x0 = np.clip(np.arange(w) - r, 0, w); x1 = np.clip(np.arange(w) + r + 1, 0, w)
    s = c[y1][:, x1] - c[y0][:, x1] - c[y1][:, x0] + c[y0][:, x0]
    return (s / ((y1 - y0)[:, None] * (x1 - x0)[None, :])).astype(np.float32)


def resample(data: np.ndarray, hdr: fits.Header, gra: np.ndarray, gdec: np.ndarray, out_scale_arcsec: float) -> np.ndarray:
    w = WCS(hdr, naxis=2)
    try:
        in_scale = float(np.mean(np.abs(w.proj_plane_pixel_scales())) * 3600)
    except Exception:
        in_scale = out_scale_arcsec
    img = _box_blur(data.astype(np.float32), int(round(out_scale_arcsec / max(in_scale, 0.1))))
    x, y = w.world_to_pixel_values(gra, gdec)
    out = im._bilinear(img, x, y)
    good = np.isfinite(out)
    if good.sum() > 20:
        out = im.subtract_background(out, block=max(10, out.shape[0] // 8))
    return out


def history(ra: float, dec: float, fov_arcmin: float, n: int = 240) -> dict:
    """All older surveys on one grid centred at (ra, dec), fov arcmin wide, n x n pixels."""
    scale = fov_arcmin * 60 / n
    w = WCS(naxis=2)
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    w.wcs.crval = [ra, dec]
    w.wcs.crpix = [(n + 1) / 2, (n + 1) / 2]
    w.wcs.cdelt = [-scale / 3600, scale / 3600]
    yy, xx = np.mgrid[0:n, 0:n]
    gra, gdec = w.pixel_to_world_values(xx, yy)
    size = fov_arcmin / 60 * 1.5
    frames, notes = [], []

    def one(s):
        try:
            tiles = fetch(s, ra, dec, size)
            if not tiles:
                return s, None, "no image here"
            parts = [resample(d, h, gra, gdec, scale) for d, h, _ in tiles]
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                img = np.nanmean(np.stack(parts), axis=0).astype(np.float32)  # stitch overlapping tiles
            return s, (img, float(np.mean([m for _, _, m in tiles]))), None
        except Exception as e:
            return s, None, str(e)[:120]

    with ThreadPoolExecutor(max_workers=4) as ex:
        for s, res, err in ex.map(one, SURVEYS):
            if res is None:
                notes.append(f"{s['label']}: {err}")
                continue
            img, mjd = res
            frames.append({"survey": s["id"], "label": s["label"], "band": s["band"], "mjd": mjd,
                           "date": im.mjd_to_iso(mjd)[:10], "year": round(2000 + (mjd - 51544.5) / 365.25, 2),
                           "coverage": round(float(np.isfinite(img).mean()), 3), "image": img})
    frames.sort(key=lambda f: f["mjd"])
    return {"n": n, "scale_arcsec": scale, "wcs": w, "grid": (gra, gdec), "frames": frames, "notes": notes}


def spherex_on_grid(stack: np.ndarray, job_ra: float, job_dec: float, job_fov: float, gra: np.ndarray, gdec: np.ndarray) -> np.ndarray:
    """Put a SPHEREx stack (on the job's grid) onto the time-machine grid."""
    jw = im.make_grid(job_ra, job_dec, job_fov)[0]
    x, y = jw.world_to_pixel_values(gra, gdec)
    return im._bilinear(stack.astype(np.float32), x, y)
