"""Moving-object and brightness-change detection (baseline version).

Idea: stack each visit (every ~6 months), subtract an earlier visit from a later one, and look at
what is left over.

  * A star that MOVED leaves a dark spot where it was and a bright spot where it is now.
    We pair those up and measure the motion in arcseconds per year.
  * A star that CHANGED BRIGHTNESS leaves a single bright (brighter now) or dark (fainter now) spot.
  * A spot that only shows up in ONE exposure inside a visit is a transient. That could be an
    asteroid (it moves within hours) or a glitch. This is optional because it is noisy.

Owner: Feature developer 2. Good next steps: use more visit pairs, fit a PSF instead of a peak,
train a classifier (e.g. XGBoost on peak shape + flags) to throw out artefacts.
"""
from __future__ import annotations

import math

import numpy as np

from . import image_processing as im

MAX_CANDIDATES = 30


def robust_sigma(a: np.ndarray) -> float:
    v = a[np.isfinite(a)]
    if v.size < 10:
        return float("nan")
    med = np.median(v)
    return float(1.4826 * np.median(np.abs(v - med))) or float(np.std(v)) or 1.0


def find_peaks(img: np.ndarray, threshold: float, edge: int = 2) -> list[tuple[int, int, float]]:
    """Local maxima above threshold: [(x, y, value)], brightest first."""
    n_y, n_x = img.shape
    a = np.where(np.isfinite(img), img, -np.inf)
    pad = np.pad(a, 1, constant_values=-np.inf)
    c = pad[1:-1, 1:-1]
    is_max = c > threshold
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dx or dy:
                is_max &= c >= pad[1 + dy:n_y + 1 + dy, 1 + dx:n_x + 1 + dx]
    is_max[:edge, :] = is_max[-edge:, :] = False
    is_max[:, :edge] = is_max[:, -edge:] = False
    ys, xs = np.nonzero(is_max)
    vals = a[ys, xs]
    order = np.argsort(-vals)
    return [(int(xs[k]), int(ys[k]), float(vals[k])) for k in order]


def centroid(img: np.ndarray, x: float, y: float, r: int = 1) -> tuple[float, float]:
    """Sub-pixel position: brightness-weighted centre of the (2r+1) box around (x, y)."""
    x, y = int(round(x)), int(round(y))
    y0, y1, x0, x1 = max(0, y - r), min(img.shape[0], y + r + 1), max(0, x - r), min(img.shape[1], x + r + 1)
    box = np.nan_to_num(img[y0:y1, x0:x1])
    box = (box - np.median(box) if r > 1 else box).clip(min=0)
    s = box.sum()
    if s <= 0:
        return float(x), float(y)
    yy, xx = np.mgrid[y0:y1, x0:x1]
    return float((box * xx).sum() / s), float((box * yy).sum() / s)


def _stack(arrays: dict, idx: list[int]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Inverse-variance stack. Returns (image, variance of the stack, number of exposures per pixel)."""
    f, v = arrays["flux"][idx], arrays["var"][idx]
    ok = np.isfinite(f) & np.isfinite(v) & (v > 0)
    w = np.where(ok, 1.0 / np.where(ok, v, 1.0), 0.0)
    den = w.sum(axis=0)
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = np.where(den > 0, (np.where(ok, f, 0) * w).sum(axis=0) / den, np.nan)
        var = np.where(den > 0, 1.0 / den, np.nan)
    return mean.astype(np.float32), var.astype(np.float32), ok.sum(axis=0)


def _peak_near(img: np.ndarray, x: float, y: float, r: int = 1) -> float:
    xi, yi = int(round(x)), int(round(y))
    box = img[max(0, yi - r):yi + r + 1, max(0, xi - r):xi + r + 1]
    return float(np.nanmax(box)) if np.isfinite(box).any() else float("nan")


def _saturated_fraction(arrays: dict, idx: list[int], x: float, y: float) -> float:
    xi, yi = int(round(x)), int(round(y))
    f = arrays["flags"][idx, yi, xi]
    return float(((f & im.SAT_MASK) != 0).mean()) if len(idx) else 0.0


def run(arrays: dict, meta: list[dict], grid_wcs, visits: list[int], det: int = 0, threshold: float = 5.0,
        max_shift_px: float = 6.0, min_fraction: float = 0.25, include_transients: bool = False) -> dict:
    """Compare visits and return candidates.

    visits:   which visits to use (normally the big twice-a-year passes), in time order
    det:      0 = all detectors stacked (deepest), 1..6 = one detector
    threshold: how many noise-sigmas a residual must stand out by
    """
    members = {v: [m["i"] for m in meta if m["visit"] == v and (not det or m["det"] == det)] for v in visits}
    most = max((len(x) for x in members.values()), default=0)
    visits = [v for v in visits if len(members[v]) >= max(3, 0.25 * most)]  # skip thin visits (too noisy)
    if len(visits) < 2:
        return {"candidates": [], "pairs": [], "note": "Need at least two visits of this spot to look for changes."}
    full = {v: _stack(arrays, members[v]) for v in visits}
    stacks = {v: full[v][0] for v in visits}
    mjd = {v: float(np.mean([meta[i]["mjd"] for i in members[v]])) for v in visits}
    all_idx = [i for v in visits for i in members[v]]

    # Longest baseline first (biggest motion), then each consecutive pair.
    pairs = [(visits[0], visits[-1])] + [(a, b) for a, b in zip(visits, visits[1:]) if (a, b) != (visits[0], visits[-1])]
    raw: list[dict] = []
    for va, vb in pairs:
        (A, varA, nA), (B, varB, nB) = full[va], full[vb]
        D = B - A
        # Noise per pixel from the pipeline variance, then rescaled so the typical pixel has sigma = 1.
        S = D / np.sqrt(varA + varB)
        S[(nA < 0.3 * nA.max()) | (nB < 0.3 * nB.max())] = np.nan  # skip thinly covered edges
        scale = robust_sigma(S)
        if not math.isfinite(scale):
            continue
        S /= scale
        pos = find_peaks(S, threshold)[:60]   # brighter now
        neg = find_peaks(-S, threshold)[:60]  # fainter now
        dt_yr = (mjd[vb] - mjd[va]) / 365.25
        used_pos: set[int] = set()
        used_neg: set[int] = set()
        # 1) movers: a "was here" dip paired with a "is here now" bump nearby
        for ni, (nx, ny, nv) in enumerate(neg):
            best, best_d = None, max_shift_px
            for pi, (px, py, pv) in enumerate(pos):
                if pi in used_pos:
                    continue
                d = math.hypot(px - nx, py - ny)
                if 0.5 <= d <= best_d:
                    best, best_d = pi, d
            if best is None:
                continue
            px, py, pv = pos[best]
            ox, oy = centroid(-S, nx, ny)
            cx, cy = centroid(S, px, py)
            src = max(_peak_near(A, ox, oy), _peak_near(B, cx, cy))
            amp = min(-D[ny, nx], D[py, px])  # residual size in image units
            frac = amp / src if src and src > 0 else 0
            if frac < min_fraction:
                continue  # small residual on a bright star: alignment/PSF wobble, not motion
            if frac > 1.6:
                continue  # residual bigger than the star itself: a hole/artefact, not a real source
            used_pos.add(best)
            used_neg.add(ni)
            # Measure the shift from the star's centre in each visit (the dip/bump peaks exaggerate it).
            mx, my = (ox + cx) / 2, (oy + cy) / 2
            ax, ay = centroid(A, mx, my, r=2)
            bx, by = centroid(B, mx, my, r=2)
            if math.hypot(bx - ax, by - ay) > 0.05:
                ox, oy, cx, cy = ax, ay, bx, by
            dx, dy = cx - ox, cy - oy
            # Grid is north-up with east to the left: +x is west, +y is north.
            pmra = -dx * im.PIX_ARCSEC / dt_yr * 1000 if dt_yr else 0.0
            pmdec = dy * im.PIX_ARCSEC / dt_yr * 1000 if dt_yr else 0.0
            raw.append({"kind": "mover", "x": cx, "y": cy, "x_from": ox, "y_from": oy, "visit_a": int(va), "visit_b": int(vb),
                        "mjd": mjd[vb], "snr": min(nv, pv), "fraction": frac,
                        "motion": {"dx_px": round(dx, 2), "dy_px": round(dy, 2), "years": round(dt_yr, 3),
                                   "pmra_mas_yr": round(pmra, 1), "pmdec_mas_yr": round(pmdec, 1),
                                   "total_arcsec_yr": round(math.hypot(pmra, pmdec) / 1000, 3),
                                   "pa_deg": round(math.degrees(math.atan2(pmra, pmdec)) % 360, 1)}})
        # 2) brightness changes: unpaired bumps/dips on top of a real source
        for lst, used, sign in ((pos, used_pos, +1), (neg, used_neg, -1)):
            for k, (x, y, v) in enumerate(lst):
                if k in used:
                    continue
                cx, cy = centroid(sign * S, x, y)
                fa, fb = _peak_near(A, cx, cy), _peak_near(B, cx, cy)
                src = max(fa, fb)
                frac = (sign * D[y, x]) / src if src and src > 0 else 0
                if frac < min_fraction or frac > 1.6:
                    continue  # too small to matter, or bigger than the star itself (artefact)
                na, nb = robust_sigma(A), robust_sigma(B)
                present_before, present_after = fa > 4 * na, fb > 4 * nb
                if not (present_before or present_after):
                    continue
                if (sign > 0 and A[y, x] < -3 * na) or (sign < 0 and B[y, x] < -3 * nb):
                    continue  # a dark hole in the other visit, not a real change
                if present_before and present_after:
                    kind = "variable"
                    ratio = fb / fa
                    if not (0.05 < ratio < 20):
                        continue
                else:
                    kind = "appeared" if sign > 0 else "vanished"
                raw.append({"kind": kind, "x": cx, "y": cy, "visit_a": int(va), "visit_b": int(vb), "mjd": mjd[vb],
                            "snr": v, "fraction": frac,
                            "flux_change": {"direction": "brighter" if sign > 0 else "fainter",
                                            "before_mjysr": round(fa, 3), "after_mjysr": round(fb, 3),
                                            "ratio": round(fb / fa, 3) if fa and fa > 0 else None}})

    if include_transients:
        raw += _transients(arrays, meta, members, stacks, threshold=max(threshold, 7.0))

    # Merge duplicates found in several visit pairs (keep the strongest).
    raw.sort(key=lambda c: -c["snr"])
    merged: list[dict] = []
    for c in raw:
        if any(m["kind"] == c["kind"] and math.hypot(m["x"] - c["x"], m["y"] - c["y"]) < 2.0 for m in merged):
            continue
        merged.append(c)
    merged = merged[:MAX_CANDIDATES]

    out = []
    for k, c in enumerate(merged, 1):
        ra, dec = grid_wcs.pixel_to_world_values(c["x"], c["y"])
        sat = _saturated_fraction(arrays, all_idx, c["x"], c["y"])
        score = min(1.0, c["fraction"]) * min(1.0, c["snr"] / 25) * (0.4 if sat > 0.5 else 1.0)
        c.update(candidate_id=f"C{k:03d}", ra=round(float(ra), 6), dec=round(float(dec), 6),
                 epoch=im.mjd_to_iso(c["mjd"])[:10], mjd=float(c["mjd"]), x=round(float(c["x"]), 2),
                 y=round(float(c["y"]), 2), snr=round(float(c["snr"]), 1), fraction=round(float(c["fraction"]), 3),
                 saturated=bool(sat > 0.5), score=round(float(score), 3))
        if "flux_change" in c:
            c["flux_change"] = {k2: (round(float(v2), 3) if isinstance(v2, (int, float, np.floating)) else v2)
                                for k2, v2 in c["flux_change"].items()}
        if "x_from" in c:
            ra0, dec0 = grid_wcs.pixel_to_world_values(c["x_from"], c["y_from"])
            c.update(ra_from=round(float(ra0), 6), dec_from=round(float(dec0), 6),
                     x_from=round(c["x_from"], 2), y_from=round(c["y_from"], 2))
        out.append(c)
    priority = {"mover": 2, "variable": 1}
    out.sort(key=lambda c: (-priority.get(c["kind"], 0), -c["score"]))
    for k, c in enumerate(out, 1):
        c["candidate_id"] = f"C{k:03d}"
    return {"candidates": out, "pairs": [[int(a), int(b)] for a, b in pairs],
            "note": "Movers: dark→bright pairs between visits. Variables: brightness changed in place. "
                    "Saturated stars leave messy residuals, so their scores are lowered."}


def _transients(arrays: dict, meta: list[dict], members: dict, stacks: dict, threshold: float) -> list[dict]:
    """Single-exposure spots that are not in the visit stack (possible asteroids)."""
    out = []
    for v, idx in members.items():
        S = stacks[v]
        for i in idx:
            R = arrays["flux"][i] - S
            sig = robust_sigma(R)
            if not math.isfinite(sig):
                continue
            for x, y, val in find_peaks(R / sig, threshold)[:5]:
                fl = int(arrays["flags"][i, y, x])
                if fl & (im.HARD_MASK | im.SAT_MASK | im.WARN_MASK | (1 << im.FLAG_BITS["TRANSIENT"])):
                    continue  # cosmic ray, ghost, saturation...
                cx, cy = centroid(R, x, y)
                src = _peak_near(S, cx, cy)
                if src > 0.5 * val * sig:
                    continue  # sits on a real star: probably PSF mismatch
                out.append({"kind": "transient", "x": cx, "y": cy, "visit_a": v, "visit_b": v, "mjd": meta[i]["mjd"],
                            "snr": val, "fraction": 1.0, "exposure": i, "det": meta[i]["det"]})
    return sorted(out, key=lambda c: -c["snr"])[:10]
