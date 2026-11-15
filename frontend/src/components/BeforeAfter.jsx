/* Drag a handle to compare the first and last visit. The simplest way to "spot the difference". */
import { useEffect, useRef, useState } from "react";
import { monthYear, percentile } from "../lib/frames.js";
import { LUTS, makeScaler, paint, paintRGBLight } from "../lib/render.js";

export default function BeforeAfter({ F, disp, rgb, source }) {
  const a = useRef(null), b = useRef(null);
  const [pos, setPos] = useState(50);
  const first = 0, last = F ? F.data.length - 1 : 0;
  useEffect(() => {
    if (!F || F.data.length < 2) return;
    const sa = rgb && rgb[F.list[first].visit], sb = rgb && rgb[F.list[last].visit];
    if (sa && sb) {  // RGB colour grading, one shared range per channel so colours compare fairly
      const lims = [0, 1, 2].map((c) => percentile([sa[c], sb[c]], [45, 99.7]));
      paintRGBLight(a.current, sa[0], sa[1], sa[2], F.n, lims, disp.contrast, disp.bright);
      paintRGBLight(b.current, sb[0], sb[1], sb[2], F.n, lims, disp.contrast, disp.bright);
      return;
    }
    const [lo, hi] = percentile([F.data[first], F.data[last]], [3, 99.8]);
    const sc = makeScaler(lo, hi, disp.contrast, disp.bright);
    paint(a.current, F.data[first], F.n, sc, (LUTS[disp.cmap] || LUTS.gray));
    paint(b.current, F.data[last], F.n, sc, (LUTS[disp.cmap] || LUTS.gray));
  }, [F, disp.contrast, disp.bright, disp.cmap, first, last, rgb]);
  if (!F || F.data.length < 2) return <p className="hint">Need at least two visits to compare.</p>;
  const da = (F.list[first].date_range?.[0] || F.list[first].date).slice(0, 10);
  const db = (F.list[last].date_range?.[0] || F.list[last].date).slice(0, 10);
  return (
    <div className="beforeAfter">
      <div className="baWrap">
        <canvas ref={b} width="720" height="720" />
        <canvas ref={a} width="720" height="720" style={{ clipPath: `inset(0 ${100 - pos}% 0 0)` }} />
        <div className="baLine" style={{ left: `${pos}%` }}><span></span></div>
        <div className="baTag left">{monthYear(da)}</div>
        <div className="baTag right">{monthYear(db)}</div>
        <div className="imgFoot"><span className="src">Data: {source || "NASA SPHEREx via IRSA"}</span></div>
        <input className="baRange" type="range" min="0" max="100" value={pos} onChange={(e) => setPos(+e.target.value)}
          aria-label="Compare before and after" />
      </div>
      <p className="hint">Drag the slider: left is <b>{monthYear(da)}</b>, right is <b>{monthYear(db)}</b>.</p>
    </div>
  );
}
