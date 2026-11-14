/* Movers only: hide everything that stays put, keep only what moved or changed.
 * Same idea as background-oriented schlieren (BOS): register the images, take a stable background,
 * subtract it, and track how each star's pattern shifted.  Owner: UI 2.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../lib/api.js";
import { monthYear, percentile } from "../lib/frames.js";
import { arrow, pixToCanvas, timePalette, VISIT_COLORS } from "../lib/render.js";

const W = 640;
const EXAGGERATE = 8; // arrows are drawn 8x longer than the real shift so you can see them

function f32(b64, count, nn) {
  const bin = atob(b64), u8 = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
  return Array.from({ length: count }, (_, k) => new Float32Array(u8.buffer, k * nn * 4, nn));
}

export default function MoversOnly({ qid, det, version, onPixel }) {
  const [d, setD] = useState(null);
  const [err, setErr] = useState("");
  const [k, setK] = useState(0);
  const [playing, setPlaying] = useState(true);
  const [mode, setMode] = useState("flip");   // flip | trail
  const [bgAlpha, setBgAlpha] = useState(0.25);
  const [cut, setCut] = useState(4);
  const [arrows, setArrows] = useState(true);
  const [allStars, setAllStars] = useState(false);
  const [showGone, setShowGone] = useState(false);
  const canvas = useRef(null);

  useEffect(() => {
    let alive = true;
    setD(null); setErr("");
    api.movers(qid, det).then((r) => {
      if (!alive) return;
      const nn = r.n * r.n;
      setD({ ...r, bg: f32(r.background, 1, nn)[0], res: f32(r.residuals, r.count, nn) });
      setK(0);
    }).catch((e) => alive && setErr(e.message));
    return () => { alive = false; };
  }, [qid, det, version]);

  useEffect(() => {
    if (!playing || !d || mode !== "flip") return;
    const h = setInterval(() => setK((x) => (x + 1) % d.count), 1200);
    return () => clearInterval(h);
  }, [playing, d, mode]);

  const bgLim = useMemo(() => (d ? percentile([d.bg], [5, 99.7]) : [0, 1]), [d]);

  useEffect(() => {
    if (!d || !canvas.current) return;
    const n = d.n, nn = n * n;
    const off = document.createElement("canvas"); off.width = off.height = n;
    const octx = off.getContext("2d"), img = octx.createImageData(n, n), px = img.data;
    const bgS = (v) => { const t = (v - bgLim[0]) / (bgLim[1] - bgLim[0] || 1); return t <= 0 ? 0 : t >= 1 ? 1 : Math.asinh(t * 30) / Math.asinh(30); };
    const rgb = new Float32Array(nn * 3);
    for (let i = 0; i < nn; i++) { const g = Number.isFinite(d.bg[i]) ? bgS(d.bg[i]) * bgAlpha : 0; rgb[3 * i] = rgb[3 * i + 1] = rgb[3 * i + 2] = g; }
    // light 3x3 smoothing before the cutoff, so single noisy pixels don't light up
    const smooth = (res) => {
      const out = new Float32Array(nn);
      for (let y = 0; y < n; y++) for (let x = 0; x < n; x++) {
        let s = 0, c = 0;
        for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) {
          const yy = y + dy, xx = x + dx;
          if (yy < 0 || xx < 0 || yy >= n || xx >= n) continue;
          const v = res[yy * n + xx];
          if (Number.isFinite(v)) { s += v; c++; }
        }
        out[y * n + x] = c ? s / c : NaN;
      }
      return out;
    };
    const add = (raw, sigma, col, sign = 1) => {
      const res = smooth(raw), sig3 = sigma / 2.2;  // noise drops ~3x after 3x3 averaging (neighbours are correlated)
      const top = 8 * sig3;
      sigma = sig3;
      for (let i = 0; i < nn; i++) {
        const v = sign * res[i];
        if (!(v > cut * sigma)) continue;
        const t = Math.min(1, (v - cut * sigma) / (top - cut * sigma || 1)) * 0.85 + 0.15;
        rgb[3 * i] += col[0] * t; rgb[3 * i + 1] += col[1] * t; rgb[3 * i + 2] += col[2] * t;
      }
    };
    if (mode === "trail") {
      const pal = timePalette(Math.min(3, d.count));
      const pick = d.count <= 3 ? [...Array(d.count).keys()] : [0, Math.floor((d.count - 1) / 2), d.count - 1];
      pick.forEach((j, c) => add(d.res[j], d.frames[j].sigma, pal[c] || pal[pal.length - 1]));
    } else {
      add(d.res[k], d.frames[k].sigma, [1, 0.72, 0.28]);
      if (showGone) add(d.res[k], d.frames[k].sigma, [0.25, 0.55, 1], -1);
    }
    for (let r = 0; r < n; r++) {
      const src = (n - 1 - r) * n;
      for (let c = 0; c < n; c++) {
        const o = (r * n + c) * 4, i = src + c;
        px[o] = Math.min(255, rgb[3 * i] * 255); px[o + 1] = Math.min(255, rgb[3 * i + 1] * 255); px[o + 2] = Math.min(255, rgb[3 * i + 2] * 255); px[o + 3] = 255;
      }
    }
    octx.putImageData(img, 0, 0);
    const ctx = canvas.current.getContext("2d");
    ctx.imageSmoothingEnabled = false;
    ctx.drawImage(off, 0, 0, W, W);
    if (arrows) {
      ctx.font = "600 13px Inter, sans-serif";
      for (const v of d.vectors) {
        const [x, y] = pixToCanvas(v.x, v.y, n, W), s = W / n;
        if (v.significant) {
          ctx.strokeStyle = ctx.fillStyle = "#53d8c4"; ctx.lineWidth = 3;
          arrow(ctx, x, y, x + v.dx * s * EXAGGERATE, y - v.dy * s * EXAGGERATE, 12);
          ctx.fillText(`${v.arcsec_per_yr}″/yr`, x + 12, y + 18);
        } else if (v.brightness_changed) {
          ctx.strokeStyle = ctx.fillStyle = "#f0e442"; ctx.lineWidth = 2;
          ctx.beginPath(); ctx.arc(x, y, 14, 0, 2 * Math.PI); ctx.stroke();
          ctx.fillText(v.flux_ratio > 1 ? `${v.flux_ratio.toFixed(1)}× brighter` : `${(1 / v.flux_ratio).toFixed(1)}× fainter`, x + 18, y + 4);
        } else if (allStars) {
          ctx.strokeStyle = "rgba(143,160,189,.6)"; ctx.lineWidth = 1;
          arrow(ctx, x, y, x + v.dx * s * EXAGGERATE, y - v.dy * s * EXAGGERATE, 5);
        }
      }
    }
  }, [d, k, mode, bgAlpha, cut, arrows, allStars, showGone, bgLim]);

  if (err) return <p className="err">⚠ {err}</p>;
  if (!d) return <p className="hint">Lining up the visits and removing everything that stays still…</p>;
  const f = d.frames[Math.min(k, d.count - 1)];
  const movers = d.vectors.filter((v) => v.significant), changed = d.vectors.filter((v) => v.brightness_changed);
  const maxShift = Math.max(...d.frames.map((g) => Math.hypot(g.shift.dx, g.shift.dy)));
  const pal = timePalette(Math.min(3, d.count)).map((c) => `rgb(${c.map((x) => Math.round(x * 255)).join(",")})`);
  const trailIdx = d.count <= 3 ? [...Array(d.count).keys()] : [0, Math.floor((d.count - 1) / 2), d.count - 1];
  const click = (e) => {
    const r = e.currentTarget.getBoundingClientRect();
    onPixel && onPixel(Math.floor(((e.clientX - r.left) / r.width) * d.n), d.n - 1 - Math.floor(((e.clientY - r.top) / r.height) * d.n));
  };
  return (
    <div className="movers">
      <div className="row">
        <div className="seg" role="group" aria-label="Show">
          <button className={mode === "flip" ? "on" : ""} onClick={() => setMode("flip")}>▶ Time-lapse</button>
          <button className={mode === "trail" ? "on" : ""} onClick={() => setMode("trail")}>🌠 Trail (all dates at once)</button>
        </div>
        <label title="How much of the still sky to show behind the movers">Background <input type="range" min="0" max="0.8" step="0.05" value={bgAlpha} onChange={(e) => setBgAlpha(+e.target.value)} /></label>
        <label title="Hide faint leftovers (noise). Higher = only strong changes">Noise cutoff <input type="range" min="2" max="8" step="0.5" value={cut} onChange={(e) => setCut(+e.target.value)} /> <span className="mono small">{cut}σ</span></label>
      </div>
      <div className="row">
        <label className="tog"><input type="checkbox" checked={arrows} onChange={() => setArrows(!arrows)} /> motion arrows (×{EXAGGERATE})</label>
        <label className="tog"><input type="checkbox" checked={allStars} onChange={() => setAllStars(!allStars)} /> arrows for every tracked star</label>
        {mode === "flip" && <label className="tog"><input type="checkbox" checked={showGone} onChange={() => setShowGone(!showGone)} /> show where things were (blue)</label>}
      </div>
      <div className="viewer">
        <div className="canvasWrap">
          <canvas ref={canvas} width={W} height={W} onClick={click} aria-label="Only the things that moved or changed" />
          {mode === "flip" ? (
            <div className="stamp"><b>{monthYear(f.date_range[0])}</b><span>visit {k + 1} of {d.count} · still sky removed</span></div>
          ) : (
            <div className="legend timeLegend">
              {trailIdx.map((j, c) => <span key={j}><i style={{ background: pal[c] || pal[pal.length - 1] }} /> {monthYear(d.frames[j].date_range[0])}</span>)}
            </div>
          )}
        </div>
      </div>
      {mode === "flip" && (
        <div className="player">
          <button className="primary play" onClick={() => setPlaying(!playing)}>{playing ? "⏸ Pause" : "▶ Play"}</button>
          <input type="range" min="0" max={d.count - 1} value={k} onChange={(e) => { setPlaying(false); setK(+e.target.value); }} aria-label="Visit" />
          <span className="mono frameLbl">{k + 1}/{d.count}</span>
        </div>
      )}
      <div className="moverResult">
        {movers.length ? movers.map((v, j) => (
          <p key={j}>🏃 A star at pixel ({v.x}, {v.y}) shifted <b>{v.shift_px.toFixed(2)} px</b> in {d.years.toFixed(1)} years → <b>{v.arcsec_per_yr}″ per year</b> toward {v.pa_deg}° (0° = north, 90° = east).</p>
        )) : <p>No star moved by more than the measuring noise.</p>}
        {changed.map((v, j) => <p key={`c${j}`}>💡 The source at ({v.x}, {v.y}) got {v.flux_ratio > 1 ? `${v.flux_ratio.toFixed(1)}× brighter` : `${(1 / v.flux_ratio).toFixed(1)}× fainter`} between the first and last visit.</p>)}
      </div>
      <details className="howBos" open>
        <summary>How this works (the same trick as background-oriented schlieren)</summary>
        <ol>
          <li><b>Line up (register) the visits.</b> Each star in the first visit is matched with its twin in the others by cross-correlation. Most stars don't move, so their typical shift is just the pointing error: here at most <b>{maxShift.toFixed(2)} pixels</b>, corrected.</li>
          <li><b>Build a still background.</b> For every pixel, take the middle (median) value of all visits. Things that stay put survive; a star that's somewhere else each time is dropped.</li>
          <li><b>Subtract it.</b> Each visit minus the background leaves <b>only</b> what moved or changed. The time-lapse shows those leftovers; the trail puts every date on one picture in its own colour.</li>
          <li><b>Motion arrows.</b> Like the displacement field in BOS/PIV: the star pattern in a small window is matched between the first and last visit, giving its shift to a fraction of a pixel. Arrows are drawn {EXAGGERATE}× longer so you can see them.</li>
        </ol>
        <p className="small muted">{d.note}</p>
      </details>
    </div>
  );
}
