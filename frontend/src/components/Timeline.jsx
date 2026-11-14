/* When each SPHEREx snapshot of this spot was taken. Owner: UI 2. */
import { useEffect, useRef, useState } from "react";
import { DET_COLORS } from "../lib/render.js";

export default function Timeline({ meta, frame, mode, onPick, simple }) {
  const ref = useRef(null);
  const [w, setW] = useState(800);
  useEffect(() => {
    const ro = new ResizeObserver(([e]) => setW(e.contentRect.width || 800));
    if (ref.current) ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);
  if (!meta) return null;
  const ex = meta.exposures, H = simple ? 50 : 76, padL = simple ? 8 : 30, padR = 10;
  const t0 = Math.min(...ex.map((e) => e.mjd)) - 5, t1 = Math.max(...ex.map((e) => e.mjd)) + 5;
  const x = (m) => padL + ((m - t0) / (t1 - t0)) * (w - padL - padR);
  const y = (d) => (simple ? 18 : 6 + d * 9 - 3);
  let cur = null;
  if (frame) {
    if (mode !== "exposure" && frame.visit !== undefined) {
      const a = ex.filter((e) => e.visit === frame.visit);
      const x0 = x(Math.min(...a.map((e) => e.mjd))) - 5, x1 = x(Math.max(...a.map((e) => e.mjd))) + 5;
      cur = <rect x={x0} y="2" width={Math.max(10, x1 - x0)} height={H - 18} rx="5" fill="#ffb547" opacity=".22" />;
    } else cur = <rect x={x(frame.mjd) - 1.5} y="2" width="3" height={H - 18} fill="#ffb547" />;
  }
  return (
    <div ref={ref} className="timelineWrap">
      <svg width="100%" height={H} viewBox={`0 0 ${w} ${H}`} className="timeline" aria-label="When the pictures were taken">
        {!simple && [1, 2, 3, 4, 5, 6].map((d) => <text key={d} x="2" y={6 + d * 9}>D{d}</text>)}
        {cur}
        {meta.visits.map((v) => {
          const a = ex.filter((e) => e.visit === v.visit);
          const x0 = x(Math.min(...a.map((e) => e.mjd))) - 5;
          return <g key={v.visit} onClick={() => onPick && onPick(v.visit)} style={{ cursor: "pointer" }}>
            <text x={Math.min(x0, w - 46)} y={H - 2}>{v.start.slice(0, 7)}</text>
          </g>;
        })}
        {ex.map((e) => <circle key={e.i} cx={x(e.mjd)} cy={y(e.det)} r={simple ? 3 : 2.3}
          fill={simple ? "#8fa0bd" : DET_COLORS[e.det - 1]} opacity=".85" />)}
      </svg>
      {simple && <p className="hint small">Each dot is one snapshot. The clumps are visits, about every 6 months.</p>}
    </div>
  );
}
