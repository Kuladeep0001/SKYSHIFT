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
    if np.isfinite(flux).sum() > 10:
        flux = subtract_background(flux)  # remove leftover sky glow so frames from different dates match
    return {"flux": flux, "var": v, "flags": fl, "wave": wave, **meta}


def subtract_background(img: np.ndarray, block: int = 10) -> np.ndarray:
    """Remove smooth large-scale sky brightness (what the zodiacal model leaves behind).

    Splits the image into ~block x block boxes, takes a star-free median in each (3-sigma clipped),
    and subtracts a smooth surface interpolated between the box centres. Point sources survive;
    very extended things (big nebulae, galaxies) get flattened, which is fine for spotting movers.
    """
    h, w = img.shape
    nby, nbx = max(1, round(h / block)), max(1, round(w / block))
    ys = np.linspace(0, h, nby + 1).astype(int)
    xs = np.linspace(0, w, nbx + 1).astype(int)
    grid = np.full((nby, nbx), np.nan)
    for i in range(nby):
        for j in range(nbx):
            v = img[ys[i]:ys[i + 1], xs[j]:xs[j + 1]]
            v = v[np.isfinite(v)]
            if v.size < 10:
                continue
            for _ in range(3):  # clip stars
                med = np.median(v)
                mad = 1.4826 * np.median(np.abs(v - med)) or 1e-9
                v = v[np.abs(v - med) < 3 * mad]
                if v.size < 10:
                    break
            grid[i, j] = np.median(v) if v.size else med
    if not np.isfinite(grid).any():
        return img - np.nanmedian(img)
    grid = np.where(np.isfinite(grid), grid, np.nanmedian(grid))
    cy = (ys[:-1] + ys[1:]) / 2 - 0.5
    cx = (xs[:-1] + xs[1:]) / 2 - 0.5
    rows = np.array([np.interp(np.arange(w), cx, grid[i]) for i in range(nby)])  # (nby, w)
    bg = np.array([np.interp(np.arange(h), cy, rows[:, k]) for k in range(w)]).T  # (h, w)
    return (img - bg).astype(np.float32)


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


# ------------------------------------------------- frames for the player ---

def group_frames(arrays: dict, meta: list, mode: str, det: int = 0, channel: int = 0, visit: int = -1):
    """Build the frames for the player.

    mode = exposure : every single exposure (optionally one detector or one channel)
           visit    : one stacked frame per visit (one detector, or det=0 for all detectors combined)
           visitdet : one stacked frame per visit per detector (for the 6-detector wall and colour)
           channel  : one stacked frame per visit using only one of the 102 channels (same wavelength)
           planes   : all 102 channels for one visit
    """
    flux, var, flags = arrays["flux"], arrays["var"], arrays["flags"]
    idx = list(range(len(meta)))
    if det:
        idx = [i for i in idx if meta[i]["det"] == det]
    if channel and mode in ("exposure", "channel"):
        idx = [i for i in idx if meta[i]["channel"] == channel]
    if visit >= 0:
        idx = [i for i in idx if meta[i]["visit"] == visit]

    groups: list[tuple[dict, list[int]]] = []
    if mode == "exposure":
        groups = [({"det": meta[i]["det"], "channel": meta[i]["channel"], "wave": meta[i]["wave"],
                    "obs_id": meta[i]["obs_id"], "visit": meta[i]["visit"]}, [i]) for i in idx]
    elif mode in ("visit", "channel"):
        for v in sorted({meta[i]["visit"] for i in idx}):
            groups.append(({"visit": v, "det": det, "channel": channel}, [i for i in idx if meta[i]["visit"] == v]))
    elif mode == "visitdet":
        for v in sorted({meta[i]["visit"] for i in idx}):
            for d in range(1, 7):
                g = [i for i in idx if meta[i]["visit"] == v and meta[i]["det"] == d]
                if g:
                    groups.append(({"visit": v, "det": d}, g))
    elif mode == "planes":
        for ch in range(1, 103):
            g = [i for i in idx if meta[i]["channel"] == ch]
            if g:
                groups.append(({"channel": ch, "det": (ch - 1) // 17 + 1, "visit": visit}, g))
    else:
        raise ValueError(f"unknown mode {mode}")

    imgs, warns, out = [], [], []
    for info, g in groups:
        if len(g) == 1:
            img = flux[g[0]]
            warn = (flags[g[0]] & WARN_MASK) != 0
        else:
            img, warn = weighted_stack(flux[g], var[g], flags[g])
        mj = [meta[i]["mjd"] for i in g]
        waves = [meta[i]["wave"] for i in g if meta[i]["wave"] == meta[i]["wave"]]
        info.update(n_exp=len(g), mjd=float(np.mean(mj)), date=mjd_to_iso(float(np.mean(mj))),
                    date_range=[mjd_to_iso(min(mj))[:10], mjd_to_iso(max(mj))[:10]],
                    wave=round(float(np.median(waves)), 4) if waves else None, members=g)
        imgs.append(img.astype(np.float32))
        warns.append(warn.astype(np.uint8))
        out.append(info)
    n = int(flux.shape[-1])
    imgs_a = np.stack(imgs) if imgs else np.zeros((0, n, n), np.float32)
    warns_a = np.stack(warns) if warns else np.zeros((0, n, n), np.uint8)
    return out, imgs_a, warns_a


def measure_spectrum(arrays: dict, meta: list, x: int, y: int, r: int = 1) -> dict:
    """Brightness of a small box at pixel (x, y) in every exposure: a spectrum + light curve."""
    flux, var, flags, wave = (arrays[k] for k in ("flux", "var", "flags", "wave"))
    n = flux.shape[-1]
    x, y, r = int(x), int(y), int(min(max(r, 0), 4))
    if not (0 <= x < n and 0 <= y < n):
        raise ValueError("pixel outside the image")
    y0, y1, x0, x1 = max(0, y - r), min(n, y + r + 1), max(0, x - r), min(n, x + r + 1)
    # Local background ring a few pixels out from the box.
    R = r + 4
    by0, by1, bx0, bx1 = max(0, y - R), min(n, y + R + 1), max(0, x - R), min(n, x + R + 1)
    ring = np.ones((by1 - by0, bx1 - bx0), bool)
    ring[(y0 - by0):(y1 - by0), (x0 - bx0):(x1 - bx0)] = False
    ranges = det_ranges(meta)
    pts = []
    for i, m in enumerate(meta):
        box = flux[i, y0:y1, x0:x1]
        good = np.isfinite(box)
        if good.mean() < 0.6:
            continue
        bg = np.nanmedian(flux[i, by0:by1, bx0:bx1][ring])
        bg = 0.0 if not np.isfinite(bg) else bg
        s = (np.nansum(box - bg) / good.mean()) * MJYSR_TO_UJY
        e = np.sqrt(np.nansum(var[i, y0:y1, x0:x1])) * MJYSR_TO_UJY
        w = float(wave[i, y, x])
        if not np.isfinite(w):
            continue
        fl = int(np.bitwise_or.reduce(flags[i, y0:y1, x0:x1].ravel()))
        names = [k for k, b in FLAG_BITS.items() if fl & (1 << b)]
        saturated = bool(fl & SAT_MASK)
        pts.append({"i": i, "wave": round(w, 4), "flux": round(float(s), 3), "err": round(float(e), 3),
                    "mjd": m["mjd"], "date": m["date"][:10], "visit": m["visit"], "det": m["det"],
                    "channel": channel_of(m["det"], w, ranges), "flags": names, "saturated": saturated})
    return {"x": x, "y": y, "r": r, "unit": "uJy", "points": pts}


def compare(arrays: dict, meta: list, a: list[int], b: list[int], op: str = "subtract"):
    """Stack two sets of exposures (e.g. two visits) and subtract or add them.

    Returns (result image, stack A, stack B). In a subtraction a moving star shows up as a
    dark/bright pair, and a star that changed brightness as a single dark or bright spot.
    """
    if not a or not b:
        raise ValueError("both sides of the comparison need at least one exposure")
    sa, _ = weighted_stack(arrays["flux"][a], arrays["var"][a], arrays["flags"][a]) if len(a) > 1 else (arrays["flux"][a[0]], None)
    sb, _ = weighted_stack(arrays["flux"][b], arrays["var"][b], arrays["flags"][b]) if len(b) > 1 else (arrays["flux"][b[0]], None)
    if op == "subtract":
        res = sb - sa
    elif op == "add":
        res = np.nanmean(np.stack([sa, sb]), axis=0)
    else:
        raise ValueError("op must be 'subtract' or 'add'")
    return res.astype(np.float32), sa, sb


def render_png(img: np.ndarray, diverging: bool = False, contrast: float = 0.55) -> bytes:
    """Render a frame as a PNG (asinh stretch, north up). Used by /frames/{k}.png and /compare."""
    from io import BytesIO

    from PIL import Image

    a = np.asarray(img, dtype=np.float64)
    good = np.isfinite(a)
    beta = 10 ** (contrast * 3) - 0.999
    if diverging:
        lim = np.nanpercentile(np.abs(a[good]), 99.5) if good.any() else 1.0
        t = np.clip(a / (lim or 1), -1, 1)
        t = np.sign(t) * np.arcsinh(np.abs(t) * beta) / np.arcsinh(beta)
        rgb = np.zeros(a.shape + (3,), np.uint8)
        pos, neg = np.clip(t, 0, 1), np.clip(-t, 0, 1)
        rgb[..., 0] = 10 + 245 * pos + 30 * neg
        rgb[..., 1] = 20 + 150 * pos + 90 * neg
        rgb[..., 2] = 45 + 15 * pos + 210 * neg
    else:
        lo, hi = (np.nanpercentile(a[good], [3, 99.8]) if good.any() else (0, 1))
        t = np.clip((a - lo) / ((hi - lo) or 1), 0, 1)
        g = (255 * np.arcsinh(t * beta) / np.arcsinh(beta)).astype(np.uint8)
        rgb = np.repeat(g[..., None], 3, axis=2)
    rgb[~good] = (18, 22, 34)
    im_ = Image.fromarray(np.flipud(rgb), "RGB")  # FITS row 0 is south: flip so north is up
    scale = max(1, 512 // max(a.shape))
    im_ = im_.resize((a.shape[1] * scale, a.shape[0] * scale), Image.NEAREST)
    buf = BytesIO()
    im_.save(buf, format="PNG")
    return buf.getvalue()
