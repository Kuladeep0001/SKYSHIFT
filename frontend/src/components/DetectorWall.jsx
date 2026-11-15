/* Six detector arrays side by side (each stacked per visit). Normal, - first, - previous and add all work per detector. */
import { useEffect, useMemo, useRef } from "react";
import { diffFrame, meanFrames, monthYear, percentile } from "../lib/frames.js";
import { DET_COLORS, LUTS, makeDivScaler, makeScaler, paint } from "../lib/render.js";

/* Visits where all six detectors took a picture (partial passes would leave black panels). */
function visitsOf(F) {
  const dets = {};
  F.list.forEach((f) => (dets[f.visit] ||= new Set()).add(f.det));
  const all = Object.keys(dets).map(Number).sort((a, b) => a - b);
  const full = all.filter((v) => dets[v].size >= 6);
  return full.length >= 2 ? full : all;
}

export function wallVisitCount(F) {
  return F ? visitsOf(F).length : 0;
}

export default function DetectorWall({ F, idx, disp, detectors, onPixel, source }) {
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
    return out;
  }, [F]);

  useEffect(() => {
    if (!F) return;
    const n = F.n;
    for (let d = 1; d <= 6; d++) {
      const cv = refs.current[d - 1];
      if (!cv) continue;
      const idxs = F.list.map((f, k) => (f.det === d && visits.includes(f.visit) ? k : -1)).filter((k) => k >= 0);
      const k = idxs.find((j) => F.list[j].visit === v);
      if (k === undefined || !lims[d]) { cv.getContext("2d").clearRect(0, 0, cv.width, cv.height); continue; }
      let arr = F.data[k], diverge = false;
      const pos = idxs.indexOf(k);
      if (disp.math === "first" && pos > 0) { arr = diffFrame(F.data[k], F.data[idxs[0]]); diverge = true; }
      if (disp.math === "prev" && pos > 0) { arr = diffFrame(F.data[k], F.data[idxs[pos - 1]]); diverge = true; }
      if (disp.math === "sum") arr = (F._detSum ||= {})[d] || (F._detSum[d] = meanFrames(idxs.map((j) => F.data[j])));
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
  return (
    <div className="wall">
      {[1, 2, 3, 4, 5, 6].map((d) => (
        <figure key={d}>
          <canvas ref={(el) => (refs.current[d - 1] = el)} width="360" height="360" onClick={click} />
          <figcaption><b style={{ color: DET_COLORS[d - 1] }}>D{d}</b> {detectors?.[d] ? `${detectors[d][0].toFixed(2)}–${detectors[d][1].toFixed(2)} µm` : ""}</figcaption>
        </figure>
      ))}
      <p className="srcLine">Data: {source || "NASA SPHEREx via IRSA"}</p>
      <p className="hint wallNote">{disp.math === "sum" ? "All visits added together" : when}: each panel is one of SPHEREx's 6 detectors, from bluest (D1) to reddest (D6). Cold brown dwarfs only show up in the red ones.
        {(disp.math === "first" || disp.math === "prev") && v === visits[0] && <> <b>This is the first visit: the others are compared with it.</b></>}
        {(disp.math === "first" || disp.math === "prev") && v !== visits[0] && <> <b className="orange">Orange</b> = brighter now, <b className="blue">blue</b> = was brighter {disp.math === "first" ? "in the first visit" : "in the visit before"}.</>}</p>
    </div>
  );
}
