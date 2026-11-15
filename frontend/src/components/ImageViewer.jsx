/* The main picture: one SPHEREx frame with optional overlays. Owner: UI 2. */
import { useEffect, useMemo, useRef } from "react";
import { diffFrame, meanFrames, mjdToYear, monthYear, percentile, PIX } from "../lib/frames.js";
import { arrow, bandTint, LUTS, makeDivScaler, makeScaler, paint, paintRGBLight, pixToCanvas, skyToCanvas, zoomView } from "../lib/render.js";
import { frameNoise, motionCheck, trackStar } from "../lib/motion.js";
import { overlayCredits } from "../lib/sources.js";

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
  focus, onPixel, simple, fov, rgb, zoom = 1, source }) {
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
  // what we zoom on and follow: the object you clicked, or the target in the middle
  const n0 = F ? F.n : 0, cx0 = sel ? sel.x : (n0 - 1) / 2, cy0 = sel ? sel.y : (n0 - 1) / 2;
  const view = F ? zoomView(F.n, zoom, cx0, cy0) : null;
  // the object's measured position in every frame (for the path)
  const path = useMemo(() => (F && F.data.length > 1 && F.mode !== "exposure" ? trackStar(F, cx0, cy0) : null), [F, cx0, cy0]);
  // Is there really a star there, and does it really move? (Empty sky or a still star must not get a "was here" circle.)
  const noise = useMemo(() => frameNoise(F), [F]);
  const track = useMemo(() => motionCheck({ F, path, noise, isTarget: !sel, target, candidates, cx0, cy0 }),
    [path, noise, F, sel, target, candidates, cx0, cy0]);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas || !F || !F.data.length || !lim) return;
    const { arr, diverge } = displayed(F, i, disp.math);
    const set = rgb && rgbLims && disp.math === "none" && frame ? rgb[frame.visit] : null;
    if (set) {
      paintRGBLight(canvas, set[0], set[1], set[2], F.n, rgbLims, disp.contrast, disp.bright, ov.flags ? F.flags[i] : null, view);
    } else {
      const scaler = diverge ? makeDivScaler(lim.L, disp.contrast, disp.bright) : makeScaler(lim.lo, lim.hi, disp.contrast, disp.bright);
      // RGB grading with a single band (one detector, or single snapshots): tint it in that band's own colour
      const lut = diverge ? LUTS.diverge : disp.cmap === "rgb" ? (frame && frame.det ? bandTint(frame.det) : LUTS.gray) : LUTS[disp.cmap];
      paint(canvas, arr, F.n, scaler, lut, ov.flags ? F.flags[i] : null, view);
    }
    drawOverlays(canvas.getContext("2d"), F.n, frame);
  });

  function drawOverlays(ctx, n, f) {
    const z = view ? n / view.sw : 1;
    const s = (W / n) * z, year = f && f.mjd ? mjdToYear(f.mjd) : 2026;
    // full-picture canvas position -> zoomed canvas position
    const Z = ([x, y]) => (view ? [(x - view.sx * (W / n)) * z, (y - view.sy * (W / n)) * z] : [x, y]);
    ctx.lineWidth = 1.6;
    ctx.font = "600 14px Inter, sans-serif";
    // the shift, drawn so anyone can see it: dashed circle = where the star was at the first visit,
    // gold circle = where it is in this picture, arrow = the shift, small dots = the visits in between
    if (ov.path !== false && path && track.moving && disp.math !== "sum") {
      const pts = path.map((p) => Z(pixToCanvas(p.x, p.y, n, W)));
      const R = Math.max(14, Math.min(110, 2.4 * s));        // about the size of the star
      const [x0, y0] = pts[0], [xi, yi] = pts[i];
      const first = F.list[0], d0 = first.date_range ? monthYear(first.date_range[0]) : first.date.slice(0, 7);
      ctx.save();
      ctx.fillStyle = "rgba(255,207,77,.95)";
      pts.forEach(([x, y], k) => { if (k > 0 && k < i) { ctx.beginPath(); ctx.arc(x, y, 3.5, 0, 2 * Math.PI); ctx.fill(); } });
      ctx.lineWidth = 2.5; ctx.strokeStyle = "rgba(255,255,255,.95)"; ctx.setLineDash([9, 7]);
      ctx.beginPath(); ctx.arc(x0, y0, R, 0, 2 * Math.PI); ctx.stroke();
      ctx.setLineDash([]);
      ctx.font = "700 13px Inter, sans-serif"; ctx.fillStyle = "#ffffff";
      ctx.shadowColor = "#000"; ctx.shadowBlur = 4;
      ctx.fillText(`was here in ${d0}`, x0 - R, y0 + R + 18);
      if (i > 0) {
        ctx.strokeStyle = "#ffcf4d"; ctx.lineWidth = 3;
        ctx.beginPath(); ctx.arc(xi, yi, R, 0, 2 * Math.PI); ctx.stroke();
        if (Math.hypot(xi - x0, yi - y0) > 6) { ctx.lineWidth = 3; arrow(ctx, x0, y0, xi, yi, 12); }
        ctx.fillStyle = "#ffcf4d";
        ctx.fillText("is here now", xi - R, yi - R - 8);
      }
      ctx.restore();
      ctx.font = "600 14px Inter, sans-serif"; ctx.lineWidth = 1.6;
    }
    // the target
    if (ov.cross && z === 1) {
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
        const [x, y] = Z(skyToCanvas(ra, dec, target.ra, target.dec, n, W));
        if (x < -10 || y < -10 || x > W + 10 || y > W + 10) continue;
        const rad = Math.max(5, Math.min(15, (18 - (st.mag ?? 15)) * 1.2)) * Math.max(1, (W / n) / 10) * Math.min(z, 2.5);
        ctx.globalAlpha = fast ? (z > 1 ? 0.8 : 1) : 0.55;
        ctx.strokeStyle = fast ? "#5ab0ff" : color;
        ctx.lineWidth = fast ? (z > 1 ? 1.4 : 2.2) : 1.3;
        if (z > 1) ctx.setLineDash([6, 5]);
        ctx.beginPath(); ctx.arc(x, y, rad, 0, 2 * Math.PI); ctx.stroke();
        ctx.setLineDash([]);
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
          const [x, y] = Z(skyToCanvas(o.ra, o.dec, target.ra, target.dec, n, W));
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
      const [x, y] = Z(pixToCanvas(c.x, c.y, n, W));
      ctx.strokeStyle = ctx.fillStyle = on ? "#ffffff" : "#ff6bd6";
      ctx.lineWidth = on ? 3 : 2;
      ctx.setLineDash(on ? [] : [5, 4]);
      ctx.beginPath(); ctx.arc(x, y, 14 + (on ? 4 : 0), 0, 2 * Math.PI); ctx.stroke();
      ctx.setLineDash([]);
      if (c.kind === "mover" && c.x_from != null) {
        const [x0, y0] = Z(pixToCanvas(c.x_from, c.y_from, n, W));
        const k = Math.max(1.5, 6 / z); // exaggerate the (tiny) shift so the direction is visible
        arrow(ctx, x, y, x + (x - x0) * k, y + (y - y0) * k, 9);
      }
      ctx.fillText(c.candidate_id, x + 18, y - 14);
    }
    if (sel) {
      ctx.strokeStyle = "#ffa31a"; ctx.lineWidth = 2;
      const [x, y] = Z(pixToCanvas(sel.x, sel.y, n, W));
      if (z === 1) ctx.strokeRect(x - 1.5 * s, y - 1.5 * s, 3 * s, 3 * s);
    }
  }

  function click(e) {
    if (!F) return;
    const r = e.currentTarget.getBoundingClientRect();
    const fx = (e.clientX - r.left) / r.width, fy = (e.clientY - r.top) / r.height;
    const cx = view ? view.sx + fx * view.sw : fx * F.n, cy = view ? view.sy + fy * view.sw : fy * F.n;
    onPixel && onPixel(Math.floor(cx), F.n - 1 - Math.floor(cy));
  }

  if (!F) return null;
  const { diverge, ref: isRef } = F.data.length ? displayed(F, i, disp.math) : {};
  let motion = null;
  if (ov.path !== false && path && track.real && disp.math !== "sum" && F.list[0]) {
    const f0 = F.list[0], d0 = f0.date_range ? monthYear(f0.date_range[0]) : f0.date.slice(0, 7);
    if (!track.moving) motion = `Stays in place: no shift between visits (less than 3″ since ${d0}).`;
    else if (i === 0) motion = `Starting point (${d0}): press play and watch the star leave the dashed circle.`;
    else {
      const dx = path[i].x - path[0].x, dy = path[i].y - path[0].y, px = Math.hypot(dx, dy), arcsec = px * PIX;
      const yrs = ((F.list[i].mjd || 0) - (f0.mjd || 0)) / 365.25;
      const dir = [dy > 0.15 ? "north" : dy < -0.15 ? "south" : "", dx > 0.15 ? "west" : dx < -0.15 ? "east" : ""].filter(Boolean).join("-");
      motion = arcsec >= 2
        ? `Moved ${arcsec.toFixed(1)}″ ${dir || ""} since ${d0}${yrs > 0.1 ? ` (in ${yrs.toFixed(1)} years)` : ""}: ${px.toFixed(1)} SPHEREx pixels.`
        : `No clear shift since ${d0} (under 2″): it stays in place.`;
    }
  }
  const credits = [source || "NASA SPHEREx via IRSA", ...overlayCredits(ov)];
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
        {motion && <div className="motionNote">{motion}</div>}
        <div className="imgFoot">
          <span>{view ? `zoomed ${zoom}× · ${(fov / zoom).toFixed(1)}′ wide` : `${fov}′ wide${moonFrac >= 2 ? ` ≈ 1/${moonFrac} of the full Moon` : ""}`}</span>
          <span className="src">Data: {credits.join(" · ")}</span>
        </div>
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
      {simple && motion && track.moving && ov.path !== false && (
        <p className="hint">Dashed white circle = where the star was at the first visit. Gold circle = where it is in this picture. The arrow is the shift.</p>
      )}
    </div>
  );
}
