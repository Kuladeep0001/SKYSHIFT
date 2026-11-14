"""Movers only: register the visits, build a stable background, subtract it (like background-oriented schlieren).

1. Feature tracking (as in BOS / PIV): every star in the reference visit is matched by normalised
   cross-correlation in the other visit -> a displacement vector per star.
2. Registration: most stars don't move, so the MEDIAN displacement is the small leftover pointing error
   between visits. Each visit is shifted back by it.
3. Background: the pixel-by-pixel median of the registered visits keeps everything that stays put and
   drops a star that is somewhere else at each date.
4. Subtract: visit - background leaves only what moved or changed brightness.
Owner: Feature developer 1 / 2.
"""
from __future__ import annotations

import math

import numpy as np

from . import image_processing as im
from .detection import find_peaks, robust_sigma


def _clean(a: np.ndarray) -> np.ndarray:
    return np.nan_to_num(a - np.nanmedian(a), nan=0.0).astype(np.float64)


def _parabola(c_m: float, c_0: float, c_p: float) -> float:
    d = c_m - 2 * c_0 + c_p
    return 0.0 if d == 0 else 0.5 * (c_m - c_p) / d


def track(ref: np.ndarray, img: np.ndarray, win: int = 3, search: int = 3, min_snr: float = 8.0,
          max_stars: int = 80) -> list[dict]:
    """Displacement of each star from `ref` to `img` (pixels, x right/west, y up/north), sub-pixel."""
    a, b = _clean(ref), _clean(img)
    sig = robust_sigma(a)
    if not math.isfinite(sig) or sig <= 0:
        return []
    n_y, n_x = a.shape
    edge = win + search + 1
    out = []
    for x, y, v in find_peaks(a / sig, min_snr)[:max_stars]:
        if x < edge or y < edge or x >= n_x - edge or y >= n_y - edge:
            continue
        t = a[y - win:y + win + 1, x - win:x + win + 1]
        t = t - t.mean()
        tn = np.sqrt((t * t).sum())
        if tn == 0:
            continue
        cc = np.full((2 * search + 1, 2 * search + 1), -1.0)
        for dy in range(-search, search + 1):
            for dx in range(-search, search + 1):
                w = b[y + dy - win:y + dy + win + 1, x + dx - win:x + dx + win + 1]
                w = w - w.mean()
                wn = np.sqrt((w * w).sum())
                if wn > 0:
                    cc[dy + search, dx + search] = (t * w).sum() / (tn * wn)
        iy, ix = np.unravel_index(np.argmax(cc), cc.shape)
        peak = float(cc[iy, ix])
        if peak < 0.5 or iy in (0, 2 * search) or ix in (0, 2 * search):
            continue  # weak match, or the best match is at the edge of the search box
        fy = _parabola(cc[iy - 1, ix], cc[iy, ix], cc[iy + 1, ix])
        fx = _parabola(cc[iy, ix - 1], cc[iy, ix], cc[iy, ix + 1])
        my, mx = y + iy - search, x + ix - search
        f0 = float(np.clip(a[y - win:y + win + 1, x - win:x + win + 1], 0, None).sum())
        f1 = float(np.clip(b[my - win:my + win + 1, mx - win:mx + win + 1], 0, None).sum())
        out.append({"x": x, "y": y, "dx": round(ix - search + fx, 3), "dy": round(iy - search + fy, 3),
                     "match": round(peak, 3), "snr": round(v, 1), "flux_ratio": round(f1 / f0, 3) if f0 > 0 else None})
    return out


def _shift(img: np.ndarray, dx: float, dy: float) -> np.ndarray:
    """Move an image by (-dx, -dy) so a star that sat at x+dx goes back to x."""
    n_y, n_x = img.shape
    yy, xx = np.mgrid[0:n_y, 0:n_x].astype(np.float64)
    return im._bilinear(img.astype(np.float32), xx + dx, yy + dy)


def movers_only(stacks: list[np.ndarray], mjds: list[float]) -> dict:
    """Register every visit to the first, then background = median, residual = visit - background."""
    ref = stacks[0]
    shifts, aligned = [], []
    for k, s in enumerate(stacks):
        if k == 0:
            shifts.append({"dx": 0.0, "dy": 0.0, "stars": 0})
            aligned.append(s.astype(np.float32))
            continue
        v = track(ref, s)
        if len(v) >= 5:
            dx = float(np.median([p["dx"] for p in v]))
            dy = float(np.median([p["dy"] for p in v]))
        else:
            dx = dy = 0.0  # not enough stars to measure: trust the sky coordinates
        shifts.append({"dx": round(dx, 3), "dy": round(dy, 3), "stars": len(v)})
        aligned.append(_shift(s, dx, dy) if abs(dx) + abs(dy) > 0.02 else s.astype(np.float32))
    cube = np.stack(aligned)
    bg = np.nanmedian(cube, axis=0).astype(np.float32) if len(aligned) >= 3 else aligned[0]
    resid = (cube - bg).astype(np.float32)
    sig = [robust_sigma(r) for r in resid]

    # Motion vectors between the first and last visit, after registration (BOS-style).
    years = (mjds[-1] - mjds[0]) / 365.25 if len(mjds) > 1 else 0
    vecs = track(aligned[0], aligned[-1]) if len(aligned) > 1 else []
    if vecs:
        jitter = 1.4826 * float(np.median([math.hypot(p["dx"], p["dy"]) for p in vecs])) + 0.05
        for p in vecs:
            d = math.hypot(p["dx"], p["dy"])
            p["shift_px"] = round(d, 3)
            p["arcsec_per_yr"] = round(d * im.PIX_ARCSEC / years, 2) if years else None
            p["pa_deg"] = round(math.degrees(math.atan2(-p["dx"], p["dy"])) % 360, 1)  # +x is west
            r = p.get("flux_ratio") or 1.0
            p["brightness_changed"] = bool(r < 0.67 or r > 1.5)
            # A star that brightened or faded changes shape too, which fools the matching: don't call it a mover.
            p["significant"] = bool(d > max(0.35, 4 * jitter)) and not p["brightness_changed"]
        # A faint "star" sitting in the glare of a much brighter star is usually part of that glare.
        for p in vecs:
            for q in vecs:
                if q is not p and q["snr"] > 3 * p["snr"] and math.hypot(q["x"] - p["x"], q["y"] - p["y"]) < 7:
                    if p["significant"] or p["brightness_changed"]:
                        p["significant"] = p["brightness_changed"] = False
                        p["note"] = "inside the glare of a brighter star"
    return {"background": bg, "residuals": resid, "aligned": cube, "shifts": shifts, "sigma": sig,
            "vectors": vecs, "years": round(years, 3),
            "note": "Background = median of the visits (needs 3+ visits)." if len(aligned) >= 3
            else "Only two visits: the background is the first visit, so a mover shows as a dark+bright pair."}
