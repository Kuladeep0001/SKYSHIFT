/* Six detector arrays side by side (each stacked per visit), or mixed into one infrared colour picture. */
import { useEffect, useMemo, useRef } from "react";
import { diffFrame, monthYear, percentile } from "../lib/frames.js";
import { DET_COLORS, LUTS, makeDivScaler, makeScaler, paint, paintRGBLight, rgbByVisit } from "../lib/render.js";

function visitsOf(F) {
  return [...new Set(F.list.map((f) => f.visit))].sort((a, b) => a - b);
}

export function wallVisitCount(F) {
  return F ? visitsOf(F).length : 0;
}

export default function DetectorWall({ F, idx, disp, detectors, colour, onPixel }) {
  const refs = useRef([]);
  const visits = useMemo(() => (F ? visitsOf(F) : []), [F]);
  const v = visits.length ? visits[idx % visits.length] : 0;
  const lims = useMemo(() => {
    if (!F) return {};
    const out = {};
    for (let d = 1; d <= 6; d++) {
      const arrs = F.list.map((f, k) => (f.det === d ? F.data[k] : null)).filter(Boolean);
      if (arrs.length) out[d] = percentile(arrs, [3, 99.8]);
    }
    out.rgb = [[5, 6], [3, 4], [1, 2]].map((g) => percentile(F.list.map((f, k) => (g.includes(f.det) ? F.data[k] : null)).filter(Boolean), [45, 99.7]));
    return out;
  }, [F]);

  useEffect(() => {
    if (!F) return;
    const n = F.n;
    if (colour) {
      // red = longest wavelengths (D5+D6), green = middle (D3+D4), blue = shortest (D1+D2), light grading
      const set = rgbByVisit(F)[v];
      if (set && refs.current[0]) paintRGBLight(refs.current[0], set[0], set[1], set[2], n, lims.rgb, disp.contrast, disp.bright);
      return;
    }
    for (let d = 1; d <= 6; d++) {
      const cv = refs.current[d - 1];
      if (!cv) continue;
      const idxs = F.list.map((f, k) => (f.det === d ? k : -1)).filter((k) => k >= 0);
      const k = idxs.find((j) => F.list[j].visit === v);
      if (k === undefined || !lims[d]) { cv.getContext("2d").clearRect(0, 0, cv.width, cv.height); continue; }
      let arr = F.data[k], diverge = false;
      if (disp.math === "first" && k !== idxs[0]) { arr = diffFrame(F.data[k], F.data[idxs[0]]); diverge = true; }
      const [lo, hi] = lims[d];
      const sc = diverge ? makeDivScaler((hi - lo) / 3, disp.contrast, disp.bright) : makeScaler(lo, hi, disp.contrast, disp.bright);
      paint(cv, arr, n, sc, diverge ? LUTS.diverge : (LUTS[disp.cmap] || LUTS.gray));
    }
  });

  if (!F) return null;
  const f0 = F.list.find((f) => f.visit === v);
  const click = (e) => {
    const r = e.currentTarget.getBoundingClientRect();
    onPixel(Math.floor(((e.clientX - r.left) / r.width) * F.n), F.n - 1 - Math.floor(((e.clientY - r.top) / r.height) * F.n));
  };
  const when = f0 ? monthYear(f0.date_range[0]) : "";
  if (colour) {
    return (
      <div className="viewer">
        <div className="canvasWrap">
          <canvas ref={(el) => (refs.current[0] = el)} width="720" height="720" onClick={click} />
          <div className="stamp"><b>{when}</b><span>Red = 3.8–5 µm · Green = 1.6–3.8 µm · Blue = 0.75–1.6 µm</span></div>
        </div>
        <p className="hint">Infrared "colours" turned into colours you can see: cool, dusty things look red, hot stars look blue-white.</p>
      </div>
    );
  }
  return (
    <div className="wall">
      {[1, 2, 3, 4, 5, 6].map((d) => (
        <figure key={d}>
          <canvas ref={(el) => (refs.current[d - 1] = el)} width="360" height="360" onClick={click} />
          <figcaption><b style={{ color: DET_COLORS[d - 1] }}>D{d}</b> {detectors?.[d] ? `${detectors[d][0].toFixed(2)}–${detectors[d][1].toFixed(2)} µm` : ""}</figcaption>
        </figure>
      ))}
      <p className="hint wallNote">{when}: each panel is one of SPHEREx's 6 detectors, from bluest (D1) to reddest (D6). Cold brown dwarfs only show up in the red ones.</p>
    </div>
  );
}
