/* Where is the object in each visit, and does it really move?
 * Shared by the flipbook's path overlay (ImageViewer) and the Listen tab's motion sound, so both always agree.
 * Pixel axes: x grows to the right of the picture (west), y grows upward (north).
 */
import { PIX } from "./frames.js";

/* Find the star near (x, y) in each visit: position (centroid) and brightness. */
export function trackStar(F, x0, y0) {
  const n = F.n, res = [];
  let cx = x0, cy = y0;
  F.data.forEach((a, k) => {
    const R = k === 0 ? 2 : 3;
    let best = -Infinity, bx = Math.round(cx), by = Math.round(cy);
    for (let y = Math.round(cy) - R; y <= Math.round(cy) + R; y++)
      for (let x = Math.round(cx) - R; x <= Math.round(cx) + R; x++) {
        if (x < 1 || y < 1 || x >= n - 1 || y >= n - 1) continue;
        const v = a[y * n + x];
        if (Number.isFinite(v) && v > best) { best = v; bx = x; by = y; }
      }
    const ring = [];
    for (let y = by - 5; y <= by + 5; y++) for (let x = bx - 5; x <= bx + 5; x++) {
      if (x < 0 || y < 0 || x >= n || y >= n || (Math.abs(x - bx) < 3 && Math.abs(y - by) < 3)) continue;
      const v = a[y * n + x]; if (Number.isFinite(v)) ring.push(v);
    }
    ring.sort((p, q) => p - q);
    const bg = ring.length ? ring[ring.length >> 1] : 0;
    let s = 0, sx = 0, sy = 0;
    for (let y = by - 1; y <= by + 1; y++) for (let x = bx - 1; x <= bx + 1; x++) {
      const v = Math.max(0, (a[y * n + x] || 0) - bg); s += v; sx += v * x; sy += v * y;
    }
    cx = s > 0 ? sx / s : bx; cy = s > 0 ? sy / s : by;
    res.push({ x: cx, y: cy, flux: s, date: (F.list[k].date_range?.[0] || F.list[k].date).slice(0, 10), mjd: F.list[k].mjd });
  });
  return res;
}

/* The sky noise of each frame (robust: median absolute deviation, every 3rd pixel). */
export function frameNoise(F) {
  if (!F) return [];
  return F.data.map((a) => {
    const v = [];
    for (let k = 0; k < a.length; k += 3) if (Number.isFinite(a[k])) v.push(a[k]);
    v.sort((p, q) => p - q);
    const med = v[v.length >> 1] || 0;
    const dev = v.map((x) => Math.abs(x - med)).sort((p, q) => p - q);
    return 1.4826 * (dev[dev.length >> 1] || 1e-6);
  });
}

/* Is there really a star at (cx0, cy0), and does it really move?
 * `target` (with catalogue pmra/pmdec) is used only when the spot is the target itself (`isTarget`).
 * Returns { real, moving }: empty sky or a bright star's glow -> real false; a still star -> moving false. */
export function motionCheck({ F, path, noise, isTarget, target, candidates, cx0, cy0 }) {
  if (!path || path.length < 2 || !F) return { real: false, moving: false };
  const snrs = path.map((p, k) => p.flux / (3 * (noise[k] || 1e-6))).sort((x, y) => x - y);
  const snr = snrs[snrs.length >> 1];
  // a star of its own: in every visit the brightest pixel close by sits on the measured spot. On the glow of a
  // bright neighbour it sits at the edge, towards the neighbour (a slope, not a star), and the tracker slides uphill.
  const n = F.n;
  const isPeak = (a, x, y) => {
    let best = -Infinity, bx = 0, by = 0;
    for (let yy = Math.round(y) - 2; yy <= Math.round(y) + 2; yy++) for (let xx = Math.round(x) - 2; xx <= Math.round(x) + 2; xx++) {
      if (xx < 0 || yy < 0 || xx >= n || yy >= n) continue;
      const v = a[yy * n + xx], d = Math.hypot(xx - x, yy - y);
      if (!Number.isFinite(v)) { if (d <= 1.5) return true; continue; }   // an overloaded (blank) core right here
      if (v > best) { best = v; bx = xx; by = yy; }
    }
    return Math.hypot(bx - x, by - y) <= 1.2;
  };
  const real = snr >= 5 && path.every((p, k) => isPeak(F.data[k], p.x, p.y));
  if (!real) return { real, moving: false };
  const p0 = path[0], pl = path[path.length - 1];
  const shift = Math.hypot(pl.x - p0.x, pl.y - p0.y);
  if (shift > 3) return { real: false, moving: false };   // nothing SPHEREx can see moves 3 px in a year: the tracker slid onto something else
  const years = ((F.list[F.list.length - 1].mjd || 0) - (F.list[0].mjd || 0)) / 365.25;
  // 1) the target, when its motion is known from the catalogues: trust that (R Dra, RW Aur barely move;
  //    a bright, overloaded star's centre can jitter by more than half a pixel without moving)
  if (isTarget && target && Number.isFinite(target.pmra) && Number.isFinite(target.pmdec) && (target.pmra || target.pmdec)) {
    const expectedPx = (Math.hypot(target.pmra, target.pmdec) / 1000) * years / PIX;
    return { real, moving: expectedPx >= 0.3 };
  }
  // 2) SkyShift's detector found a mover here: trust its multi-visit fit
  if ((candidates || []).some((c) => c.kind === "mover" && Math.hypot(c.x - cx0, c.y - cy0) < 2.5)) return { real, moving: true };
  // 3) otherwise: a steady shift in one direction, well above the position noise (stricter for overloaded stars)
  const ux = (pl.x - p0.x) / (shift || 1), uy = (pl.y - p0.y) / (shift || 1);
  let steady = true, prev = 0;
  for (const p of path) {
    const along = (p.x - p0.x) * ux + (p.y - p0.y) * uy, across = Math.abs(-(p.x - p0.x) * uy + (p.y - p0.y) * ux);
    if (along < prev - 0.3 || across > 0.5) steady = false;
    prev = Math.max(prev, along);
  }
  const sigma = Math.max(0.08, 1.2 / snr);
  return { real, moving: steady && shift >= Math.max(snr > 200 ? 1.0 : 0.5, 4 * sigma) };
}
