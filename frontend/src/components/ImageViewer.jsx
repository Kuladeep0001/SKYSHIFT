/* The main picture: one SPHEREx frame with optional overlays. Owner: UI 2. */
import { useEffect, useMemo, useRef } from "react";
import { diffFrame, meanFrames, mjdToYear, monthYear, percentile, PIX } from "../lib/frames.js";
import { arrow, bandTint, LUTS, makeDivScaler, makeScaler, paint, paintRGBLight, pixToCanvas, skyToCanvas } from "../lib/render.js";

const W = 720; // internal canvas resolution

/* What to show for frame i given the add/subtract setting. */
export function displayed(F, i, math) {
  if (math === "sum") return { arr: F._sum || (F._sum = meanFrames(F.data)), diverge: false };
  if (math === "first" && i > 0) return { arr: diffFrame(F.data[i], F.data[0]), diverge: true };
  if (math === "prev" && i > 0) return { arr: diffFrame(F.data[i], F.data[i - 1]), diverge: true };
  return { arr: F.data[i], diverge: false, ref: math === "first" || math === "prev" };
}

export function useLimits(F, math) {
  return useMemo(() => {
    if (!F || !F.data.length) return null;
    const [lo, hi] = percentile(F.data, [3, 99.8]);
    const lim = { lo, hi };
    if (math === "sum") [lim.lo, lim.hi] = percentile([displayed(F, 0, "sum").arr], [3, 99.8]);
    if (math === "first" || math === "prev") {
      const diffs = [];
      for (let i = 1; i < F.data.length; i++) diffs.push(displayed(F, i, math).arr);
      lim.L = percentile(diffs.length ? diffs : [F.data[0]], [99.5], true)[0];
    }
    return lim;
  }, [F, math]);
}

export default function ImageViewer({ F, idx, disp, ov, target, cats, asteroids, onNeedAsteroids, sel, candidates,
  focus, onPixel, simple, fov, rgb }) {
  const ref = useRef(null);
  const lim = useLimits(F, disp.math);
  // RGB colour grading: one brightness range per colour channel, shared by all visits (so colours compare fairly)
  const rgbLims = useMemo(() => {
    if (!rgb || !F) return null;
    const sets = F.list.map((f) => rgb[f.visit]).filter(Boolean);
    if (!sets.length) return null;
    return [0, 1, 2].map((c) => percentile(sets.map((s) => s[c]), [45, 99.7]));  // dark, neutral sky
  }, [rgb, F]);
  const i = F ? Math.min(idx, F.data.length - 1) : 0;
  const frame = F && F.list[i];

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas || !F || !F.data.length || !lim) return;
    const { arr, diverge } = displayed(F, i, disp.math);
    const set = rgb && rgbLims && disp.math === "none" && frame ? rgb[frame.visit] : null;
    if (set) {
      paintRGBLight(canvas, set[0], set[1], set[2], F.n, rgbLims, disp.contrast, disp.bright, ov.flags ? F.flags[i] : null);
    } else {
      const scaler = diverge ? makeDivScaler(lim.L, disp.contrast, disp.bright) : makeScaler(lim.lo, lim.hi, disp.contrast, disp.bright);
      // RGB grading with a single band (one detector, or single snapshots): tint it in that band's own colour
      const lut = diverge ? LUTS.diverge : disp.cmap === "rgb" ? (frame && frame.det ? bandTint(frame.det) : LUTS.gray) : LUTS[disp.cmap];
      paint(canvas, arr, F.n, scaler, lut, ov.flags ? F.flags[i] : null);
    }
    drawOverlays(canvas.getContext("2d"), F.n, frame);
  });

  function drawOverlays(ctx, n, f) {
    const s = W / n, year = f && f.mjd ? mjdToYear(f.mjd) : 2026;
    ctx.lineWidth = 1.6;
    ctx.font = "600 14px Inter, sans-serif";
    // the target
    if (ov.cross) {
      ctx.strokeStyle = "rgba(83,216,196,.8)";
      const c = W / 2, g = 3.5 * s + 6;
      ctx.beginPath();
      ctx.moveTo(c - g - 16, c); ctx.lineTo(c - g, c); ctx.moveTo(c + g, c); ctx.lineTo(c + g + 16, c);
      ctx.moveTo(c, c - g - 16); ctx.lineTo(c, c - g); ctx.moveTo(c, c + g); ctx.lineTo(c, c + g + 16);
      ctx.stroke();
      if (simple && target && target.name) {
        ctx.fillStyle = "#53d8c4";
        ctx.fillText(target.name, c + g + 20, c - g - 4);
        const pm = Math.hypot(target.pmra || 0, target.pmdec || 0);
        if (pm > 300) { // show which way it is heading
          const ux = -(target.pmra || 0) / pm, uy = -(target.pmdec || 0) / pm;
          ctx.strokeStyle = "#53d8c4"; ctx.lineWidth = 2.5;
          arrow(ctx, c + ux * (g + 26), c + uy * (g + 26), c + ux * (g + 76), c + uy * (g + 76), 11);
          ctx.fillText("moving this way", c + ux * (g + 80) - (ux < 0 ? 120 : 0), c + uy * (g + 80) + (uy > 0 ? 16 : -4));
          ctx.lineWidth = 1.6;
        }
      }
    }
    const drawCat = (cat, color, magLimit, onlyFast) => {
      if (!cat || !cat.stars) return;
      const dt = year - cat.epoch;
      for (const st of cat.stars) {
        const pm = Math.hypot(st.pmra, st.pmdec), fast = pm > 150;
        if (onlyFast && !fast) continue;
        if (!fast && (st.mag ?? 99) > magLimit) continue;
        const dec = st.dec + (st.pmdec * dt) / 3.6e6;
        const ra = st.ra + (st.pmra * dt) / 3.6e6 / Math.cos((st.dec * Math.PI) / 180);
        const [x, y] = skyToCanvas(ra, dec, target.ra, target.dec, n, W);
        if (x < -10 || y < -10 || x > W + 10 || y > W + 10) continue;
        const rad = Math.max(5, Math.min(15, (18 - (st.mag ?? 15)) * 1.2)) * Math.max(1, s / 10);
        ctx.globalAlpha = fast ? 1 : 0.55;
        ctx.strokeStyle = fast ? "#5ab0ff" : color;
        ctx.lineWidth = fast ? 2.2 : 1.3;
        ctx.beginPath(); ctx.arc(x, y, rad, 0, 2 * Math.PI); ctx.stroke();
        if (fast && !simple) { ctx.fillStyle = "#5ab0ff"; ctx.fillText(`${(pm / 1000).toFixed(2)}″/yr`, x + rad + 4, y + rad + 12); }
      }
      ctx.globalAlpha = 1;
    };
    if (ov.gaia) drawCat(cats.gaia, "#5ab0ff", 16.5, simple);
    if (ov.wise) drawCat(cats.allwise, "#c38bff", 13.5, false);
    if (ov.ast && f) {
      const key = f.mjd.toFixed(3), a = asteroids[key];
      if (a && a.objects) {
        ctx.strokeStyle = ctx.fillStyle = "#ff6b8b";
        for (const o of a.objects) {
          const [x, y] = skyToCanvas(o.ra, o.dec, target.ra, target.dec, n, W);
          if (x < 0 || y < 0 || x > W || y > W) continue;
          ctx.beginPath(); ctx.rect(x - 10, y - 10, 20, 20); ctx.stroke();
          ctx.fillText(`${o.name}`, x + 14, y + 5);
        }
      } else if (!a) onNeedAsteroids(f.mjd);
    }
    // detected candidates
    for (const c of candidates || []) {
      if (c.x == null) continue;
      const on = focus === c.candidate_id;
      const [x, y] = pixToCanvas(c.x, c.y, n, W);
      ctx.strokeStyle = ctx.fillStyle = on ? "#ffffff" : "#ff6bd6";
      ctx.lineWidth = on ? 3 : 2;
      ctx.setLineDash(on ? [] : [5, 4]);
      ctx.beginPath(); ctx.arc(x, y, 14 + (on ? 4 : 0), 0, 2 * Math.PI); ctx.stroke();
      ctx.setLineDash([]);
      if (c.kind === "mover" && c.x_from != null) {
        const [x0, y0] = pixToCanvas(c.x_from, c.y_from, n, W);
        const k = 6; // exaggerate the (tiny) shift so the direction is visible
        arrow(ctx, x, y, x + (x - x0) * k, y + (y - y0) * k, 9);
      }
      ctx.fillText(c.candidate_id, x + 18, y - 14);
    }
    if (sel) {
      ctx.strokeStyle = "#ffa31a"; ctx.lineWidth = 2;
      const [x, y] = pixToCanvas(sel.x, sel.y, n, W);
      ctx.strokeRect(x - 1.5 * s, y - 1.5 * s, 3 * s, 3 * s);
    }
  }

  function click(e) {
    if (!F) return;
    const r = e.currentTarget.getBoundingClientRect();
    const cx = ((e.clientX - r.left) / r.width) * F.n, cy = ((e.clientY - r.top) / r.height) * F.n;
    onPixel && onPixel(Math.floor(cx), F.n - 1 - Math.floor(cy));
  }

  if (!F) return null;
  const { diverge, ref: isRef } = F.data.length ? displayed(F, i, disp.math) : {};
  const moonFrac = Math.round(31 / fov);
  return (
    <div className="viewer">
      <div className="canvasWrap">
        <canvas ref={ref} width={W} height={W} onClick={click} aria-label="SPHEREx picture" />
        <div className="compass" aria-hidden="true"><span className="n">N</span><span className="e">E</span></div>
        {frame && (
          <div className="stamp">
            {disp.math === "sum" ? <b>All {F.data.length} pictures added together</b> : (
              <>
                <b>{frame.date_range ? monthYear(frame.date_range[0]) : frame.date.slice(0, 16) + " UT"}</b>
                <span>{F.mode === "exposure" ? `snapshot ${i + 1} of ${F.data.length}` : `visit ${i + 1} of ${F.data.length}${frame.n_exp ? ` · ${frame.n_exp} snapshots stacked` : ""}`}</span>
                {isRef && <span className="tag">reference picture</span>}
              </>
            )}
          </div>
        )}
        <div className="scaleNote">{fov}′ wide{moonFrac >= 2 ? ` ≈ 1/${moonFrac} of the full Moon` : ""}</div>
        {rgb && disp.math === "none" && (
          <div className="legend rgbLegend">
            <span><i style={{ background: "#ff7b7b" }} /> longest infrared (3.8–5 µm)</span>
            <span><i style={{ background: "#7bff9a" }} /> middle (1.6–3.8 µm)</span>
            <span><i style={{ background: "#7bb8ff" }} /> shortest (0.75–1.6 µm)</span>
          </div>
        )}
        {diverge && (
          <div className="legend">
            <span><i style={{ background: "#ffaa3c" }} /> brighter now / is here now</span>
            <span><i style={{ background: "#3c8cff" }} /> was brighter / was here before</span>
          </div>
        )}
      </div>
    </div>
  );
}
