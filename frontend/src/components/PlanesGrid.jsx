/* All 102 infrared colour planes of one visit. Click a plane to blink that exact colour over time. */
import { useEffect, useMemo, useRef } from "react";
import { percentile } from "../lib/frames.js";
import { DET_COLORS, LUTS, makeScaler, paint } from "../lib/render.js";

function Tile({ ch, info, F, k, lim, disp, onPick }) {
  const ref = useRef(null);
  useEffect(() => {
    if (k === undefined || !ref.current) return;
    paint(ref.current, F.data[k], F.n, makeScaler(lim[0], lim[1], disp.contrast, disp.bright), LUTS[disp.cmap]);
  }, [F, k, lim, disp.contrast, disp.bright, disp.cmap]);
  const mid = info.wave ? ((info.wave[0] + info.wave[1]) / 2).toFixed(2) : "";
  return (
    <figure className={k === undefined ? "empty" : ""} onClick={() => k !== undefined && onPick(ch)}
      title={info.wave ? `Plane ${ch}: ${info.wave[0].toFixed(3)}–${info.wave[1].toFixed(3)} µm (detector D${info.det})` : `Plane ${ch}`}>
      <canvas ref={ref} width={F.n} height={F.n} />
      <figcaption style={{ color: DET_COLORS[info.det - 1] }}>{ch}<br />{mid}µm</figcaption>
    </figure>
  );
}

export default function PlanesGrid({ F, channels, disp, onPick, visits, visit, setVisit }) {
  const byCh = useMemo(() => {
    const m = {};
    if (F) F.list.forEach((f, k) => (m[f.channel] = k));
    return m;
  }, [F]);
  const detLim = useMemo(() => {
    const out = {};
    if (!F) return out;
    for (let d = 1; d <= 6; d++) {
      const arrs = F.list.map((f, k) => (f.det === d ? F.data[k] : null)).filter(Boolean);
      out[d] = percentile(arrs.length ? arrs : [new Float32Array(1)], [3, 99.8]);
    }
    return out;
  }, [F]);
  return (
    <div>
      <div className="row">
        <label>Visit <select value={visit} onChange={(e) => setVisit(+e.target.value)}>
          {(visits || []).map((v) => <option key={v.visit} value={v.visit}>Visit {v.visit + 1}: {v.start}</option>)}
        </select></label>
        <span className="hint">SPHEREx splits light into <b>102 colours</b>. Here is this spot in every one, from 0.75 µm (top left) to 5 µm (bottom right). Click one to play it over time.</span>
      </div>
      <div className="planesGrid">
        {F && channels && channels.map((info) => (
          <Tile key={info.channel} ch={info.channel} info={info} F={F} k={byCh[info.channel]} lim={detLim[info.det]} disp={disp} onPick={onPick} />
        ))}
      </div>
    </div>
  );
}
