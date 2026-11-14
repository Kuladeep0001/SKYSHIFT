"""Turn SPHEREx cutouts into aligned frames.

Every exposure is resampled onto one common north-up grid centred on the target,
so frames can be blinked, stacked, added and subtracted pixel-for-pixel.
"""
from __future__ import annotations

import math
import warnings
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
from astropy.io import fits
from astropy.wcs import WCS

from astropy import log as _astropy_log

warnings.filterwarnings("ignore", module="astropy")
_astropy_log.setLevel("ERROR")  # SPHEREx headers trigger a harmless SIP notice on every file

PIX_ARCSEC = 6.15  # SPHEREx pixel size
PIX_SR = (PIX_ARCSEC / 206264.806) ** 2
MJYSR_TO_UJY = 1e12 * PIX_SR  # 1 MJy/sr over one pixel, in micro-Jansky
VISIT_GAP_DAYS = 20  # exposures further apart than this belong to different visits
BANDS_PER_DET = 17  # 6 detectors x 17 = 102 spectral channels

# Flag bits (from the FLAGS header of SPHEREx Level-2 images). Read from the files at runtime too.
FLAG_BITS = {
    "TRANSIENT": 0, "OVERFLOW": 1, "SUR_ERROR": 2, "NONFUNC": 6, "DICHROIC": 7, "MISSING_DATA": 9,
    "HOT": 10, "COLD": 11, "FULLSAMPLE": 12, "PHANMISS": 14, "NONLINEAR": 15, "PERSIST": 17,
    "OUTLIER": 19, "CROSSTALK": 20, "SOURCE": 21, "GHOST": 22, "GHOST_FPA": 23, "GHOST_EXT": 24,
    "STREAK": 25, "BLOOM": 26, "SNOWBALL": 27, "HALO": 28,
}
# Pixels with these flags are broken and left out entirely.
HARD = ["NONFUNC", "MISSING_DATA", "HOT", "COLD", "OUTLIER"]
HARD_MASK = sum(1 << FLAG_BITS[n] for n in HARD)
# Saturated / too-bright pixels: kept for display (bright stars must stay visible) but marked in spectra.
SAT = ["OVERFLOW", "SUR_ERROR", "TRANSIENT", "NONLINEAR"]
SAT_MASK = sum(1 << FLAG_BITS[n] for n in SAT)
SOURCE_MASK = 1 << FLAG_BITS["SOURCE"]
# Pixels with these flags are shown as "contaminated" in the flags overlay.
WARN = ["PERSIST", "CROSSTALK", "GHOST", "GHOST_FPA", "GHOST_EXT", "STREAK", "BLOOM", "SNOWBALL", "HALO"]
WARN_MASK = sum(1 << FLAG_BITS[n] for n in WARN)


def mjd_to_iso(mjd: float) -> str:
    return (datetime(1858, 11, 17) + timedelta(days=float(mjd))).strftime("%Y-%m-%d %H:%M")


def make_grid(ra: float, dec: float, fov_arcmin: float):
    n = max(16, int(round(fov_arcmin * 60 / PIX_ARCSEC)))
    w = WCS(naxis=2)
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    w.wcs.crval = [ra, dec]
    w.wcs.crpix = [(n + 1) / 2, (n + 1) / 2]
    w.wcs.cdelt = [-PIX_ARCSEC / 3600, PIX_ARCSEC / 3600]
    y, x = np.mgrid[0:n, 0:n]
    gra, gdec = w.pixel_to_world_values(x, y)
    return w, n, gra, gdec


def _bilinear(img: np.ndarray, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    h, wd = img.shape
    x0 = np.floor(x).astype(int)
    y0 = np.floor(y).astype(int)
    fx, fy = x - x0, y - y0
    ok = (x0 >= 0) & (y0 >= 0) & (x0 < wd - 1) & (y0 < h - 1)
    xc, yc = np.clip(x0, 0, wd - 2), np.clip(y0, 0, h - 2)
    out = (img[yc, xc] * (1 - fx) * (1 - fy) + img[yc, xc + 1] * fx * (1 - fy)
           + img[yc + 1, xc] * (1 - fx) * fy + img[yc + 1, xc + 1] * fx * fy)
    out[~ok] = np.nan
    return out.astype(np.float32)


def _nearest(img: np.ndarray, x: np.ndarray, y: np.ndarray, fill=0) -> np.ndarray:
    h, wd = img.shape
    xi, yi = np.rint(x).astype(int), np.rint(y).astype(int)
    ok = (xi >= 0) & (yi >= 0) & (xi < wd) & (yi < h)
    out = img[np.clip(yi, 0, h - 1), np.clip(xi, 0, wd - 1)]
    out = np.where(ok, out, fill)
    return out


def _fill_saturated_cores(img: np.ndarray, flg: np.ndarray, rounds: int = 4) -> None:
    """Very bright stars saturate and the pipeline leaves their centre blank (NaN).

    Fill those blank cores from the brightest neighbour so the star shows as a bright blob
    instead of a black hole. Only touches blank pixels flagged as saturated or as a known source.
    """
    hole = ~np.isfinite(img) & ((flg & (SAT_MASK | SOURCE_MASK)) != 0)
    h, w = img.shape
    for _ in range(rounds):
        if not hole.any():
            return
        pad = np.pad(img, 1, constant_values=np.nan)
        neigh = np.stack([pad[dy:dy + h, dx:dx + w] for dy in range(3) for dx in range(3)])
        m = np.fmax.reduce(neigh, axis=0)  # ignores NaN
        fill = hole & np.isfinite(m)
        img[fill] = m[fill]
        hole &= ~fill


def read_flag_names(path: Path) -> dict[str, dict]:
    """Flag definitions straight from a file's FLAGS header (so new pipeline versions just work)."""
    out = {}
    with fits.open(path) as h:
        fh = h["FLAGS"].header
        for k in fh:
            if k.startswith("MSKN"):
                n = k[4:]
                out[fh[k]] = {"bit": int(n), "value": int(fh.get("MSKM" + n, 1 << int(n))),
                              "meaning": str(fh.get("MSKD" + n, ""))}
    return out


def process_cutout(path: Path, gra: np.ndarray, gdec: np.ndarray) -> dict:
    """Resample one cutout onto the common grid. Returns flux, variance, flags, wavelength maps."""
    with fits.open(path) as h:
        hdr = h["IMAGE"].header
        img = h["IMAGE"].data.astype(np.float32)
        zodi = h["ZODI"].data.astype(np.float32) if "ZODI" in h else 0.0
        var = h["VARIANCE"].data.astype(np.float32)
        flg = h["FLAGS"].data.astype(np.int64)
        wcs = WCS(hdr)
        wave_wcs = WCS(hdr, fobj=h, key="W")
        x, y = wcs.world_to_pixel_values(gra, gdec)
        sub = img - zodi  # remove the zodiacal-light model (the smooth glow from solar-system dust)
        sub[(flg & HARD_MASK) != 0] = np.nan
        _fill_saturated_cores(sub, flg)
        flux = _bilinear(sub, x, y)
        v = _bilinear(var, x, y)
        fl = _nearest(flg, x, y).astype(np.int32)
        try:
            wave, _bw = wave_wcs.pixel_to_world_values(x, y)
            wave = np.asarray(wave, dtype=np.float32)
        except Exception:
            wave = np.full(flux.shape, np.nan, np.float32)
        mjd = float(hdr.get("MJD-AVG") or hdr.get("MJD-OBS"))
        meta = {"det": int(hdr.get("DETECTOR", 0)), "obs_id": str(hdr.get("OBSID", "")), "mjd": mjd}
    good = np.isfinite(flux)
    if good.sum() > 10:
        flux -= np.nanmedian(flux)  # remove leftover sky background so frames match
    return {"flux": flux, "var": v, "flags": fl, "wave": wave, **meta}


# ---------------------------------------------------------------- frames ---

def det_ranges(meta: list[dict]) -> dict[int, tuple[float, float]]:
    out: dict[int, tuple[float, float]] = {}
    for m in meta:
        lo, hi = out.get(m["det"], (99.0, 0.0))
        out[m["det"]] = (min(lo, m["em_min"]), max(hi, m["em_max"]))
    return out


def channel_of(det: int, wave: float, ranges: dict) -> int:
    """Map (detector, wavelength) to one of the 102 channels, numbered 1..102 from blue to red."""
    if not math.isfinite(wave) or det not in ranges:
        return 0
    lo, hi = ranges[det]
    k = int(math.floor(BANDS_PER_DET * math.log(wave / lo) / math.log(hi / lo)))
    return (det - 1) * BANDS_PER_DET + min(max(k, 0), BANDS_PER_DET - 1) + 1


def channel_wave(ch: int, ranges: dict) -> tuple[float, float] | None:
    det, k = (ch - 1) // BANDS_PER_DET + 1, (ch - 1) % BANDS_PER_DET
    if det not in ranges:
        return None
    lo, hi = ranges[det]
    r = hi / lo
    return lo * r ** (k / BANDS_PER_DET), lo * r ** ((k + 1) / BANDS_PER_DET)


def assign_visits(mjds: np.ndarray) -> np.ndarray:
    order = np.argsort(mjds)
    visit = np.zeros(len(mjds), int)
    v, last = 0, None
    for i in order:
        if last is not None and mjds[i] - last > VISIT_GAP_DAYS:
            v += 1
        visit[i] = v
        last = mjds[i]
    return visit


def weighted_stack(flux: np.ndarray, var: np.ndarray, flags: np.ndarray):
    """Inverse-variance weighted mean of several aligned exposures (better signal-to-noise)."""
    w = np.where(np.isfinite(flux) & np.isfinite(var) & (var > 0), 1.0 / np.where(var > 0, var, 1), 0.0)
    num = np.nansum(np.nan_to_num(flux) * w, axis=0)
    den = w.sum(axis=0)
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = np.where(den > 0, num / den, np.nan).astype(np.float32)
    warn_frac = ((flags & WARN_MASK) != 0).mean(axis=0)
    return mean, (warn_frac > 0.5)
