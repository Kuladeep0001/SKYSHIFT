/* Spectral cube: 102 planes of the same patch of sky, each in ONE infrared colour, stacked like pages.
 * Pick a pixel (click) or an area (drag) and its spectrum is read straight down through all 102 planes.
 *
 * Why this is needed: SPHEREx's filter changes colour across every snapshot (a rainbow from one edge to
 * the other). The server sends every pixel of every snapshot to the plane of the colour that pixel saw,
 * then averages them, so each plane has one uniform colour.  Owner: UI 2 (viewer) + Feature dev 1 (cube).
 */
import { useEffect, useMemo, useRef, useState } from "react";
import Chart from "chart.js/auto";
import { api } from "../lib/api.js";
import { percentile, PIX } from "../lib/frames.js";
import { DET_COLORS, LUTS, makeScaler, paint, VISIT_COLORS } from "../lib/render.js";
import { bandsPlugin } from "./SpectrumPanel.jsx";

const MJYSR_TO_UJY = 1e12 * (PIX / 206264.806) ** 2;
const W = 640;

// float16 -> float32 lookup table (the cube is sent as float16 to keep it small)
const F16 = (() => {
  const t = new Float32Array(65536);
  for (let h = 0; h < 65536; h++) {
    const s = h & 0x8000 ? -1 : 1, e = (h >> 10) & 0x1f, f = h & 0x3ff;
    t[h] = e === 0 ? s * 2 ** -14 * (f / 1024) : e === 31 ? (f ? NaN : s * Infinity) : s * 2 ** (e - 15) * (1 + f / 1024);
  }
  return t;
})();
function decode16(b64, planes, nn) {
  const bin = atob(b64), u16 = new Uint16Array(bin.length / 2);
  for (let i = 0; i < u16.length; i++) u16[i] = bin.charCodeAt(2 * i) | (bin.charCodeAt(2 * i + 1) << 8);
  const out = [];
  for (let k = 0; k < planes; k++) {
    const a = new Float32Array(nn);
    for (let i = 0; i < nn; i++) a[i] = F16[u16[k * nn + i]];
    out.push(a);
  }
  return out;
}

/* Brightness of a box in every plane (local sky from a ring around the box removed). */
export function boxSpectrum(cube, box) {
  const { n, data, err, channels } = cube;
  const x0 = Math.max(0, Math.min(box.x0, box.x1)), x1 = Math.min(n - 1, Math.max(box.x0, box.x1));
  const y0 = Math.max(0, Math.min(box.y0, box.y1)), y1 = Math.min(n - 1, Math.max(box.y0, box.y1));
  const R = 3;
  return channels.map((c, k) => {
    const a = data[k], e = err[k];
    let s = 0, v = 0, good = 0, tot = 0;
    const ring = [];
    for (let y = y0 - R; y <= y1 + R; y++) for (let x = x0 - R; x <= x1 + R; x++) {
      if (x < 0 || y < 0 || x >= n || y >= n) continue;
      const val = a[y * n + x];
      const inside = x >= x0 && x <= x1 && y >= y0 && y <= y1;
      if (inside) { tot++; if (Number.isFinite(val)) { s += val; v += e[y * n + x] ** 2; good++; } }
      else if (Number.isFinite(val)) ring.push(val);
    }
    if (!good || good < 0.6 * tot || !c.wave) return null;
    ring.sort((p, q) => p - q);
    const bg = ring.length ? ring[ring.length >> 1] : 0;
    const flux = ((s - bg * good) * tot) / good * MJYSR_TO_UJY;
    return { channel: c.channel, det: c.det, wave: c.wave, flux, err: Math.sqrt(v) * MJYSR_TO_UJY * Math.sqrt(tot / good) };
  }).filter(Boolean);
}

/* A smooth curve through the spectrum (running median), to show where it departs from "smooth". */
function smooth(pts, half = 6) {
  return pts.map((p, i) => {
    const w = pts.slice(Math.max(0, i - half), i + half + 1).map((q) => q.flux).sort((a, b) => a - b);
    return w[w.length >> 1];
  });
}

export default function SpectralCube({ qid, visits, disp, version }) {
  const [visit, setVisit] = useState(-1);
  const [cubes, setCubes] = useState({});       // visit -> decoded cube
  const [k, setK] = useState(40);                // current plane (0-based)
  const [playing, setPlaying] = useState(false);
  const [box, setBox] = useState(null);          // selection {x0,y0,x1,y1}
  const [drag, setDrag] = useState(null);
  const [grid, setGrid] = useState(false);
  const [resid, setResid] = useState(false);
  const [compare, setCompare] = useState(false);
  const [features, setFeatures] = useState([]);
  const [busy, setBusy] = useState(false);
  const canvas = useRef(null), chartEl = useRef(null), chart = useRef(null);
  const cube = cubes[visit];

  async function getCube(v) {
    if (cubes[v]) return cubes[v];
    const r = await api.cube(qid, v);
    const nn = r.n * r.n;
    const c = { ...r, data: decode16(r.data, r.planes, nn), err: decode16(r.err, r.planes, nn) };
    setCubes((x) => ({ ...x, [v]: c }));
    return c;
  }
  useEffect(() => { setCubes({}); }, [qid, version]);
  useEffect(() => {
    let alive = true;
    setBusy(true);
    getCube(visit).then((c) => alive && !box && setBox({ x0: (c.n >> 1) - 1, y0: (c.n >> 1) - 1, x1: (c.n >> 1) + 1, y1: (c.n >> 1) + 1 }))
      .catch(() => {}).finally(() => alive && setBusy(false));
    return () => { alive = false; };
  }, [qid, visit, version]);
  const mainVisits = (visits || []).filter((v) => v.n >= 20);
  useEffect(() => { if (compare) mainVisits.forEach((v) => getCube(v.visit).catch(() => {})); }, [compare, qid]);

  // fly through the wavelengths
  useEffect(() => {
    if (!playing) return;
    const h = setInterval(() => setK((x) => (x + 1) % 102), 140);
    return () => clearInterval(h);
  }, [playing]);

  // per-detector brightness scale, so each plane is visible
  const lims = useMemo(() => {
    if (!cube) return null;
    const out = {};
    for (let d = 1; d <= 6; d++) out[d] = percentile(cube.data.slice((d - 1) * 17, d * 17), [3, 99.7]);
    return out;
  }, [cube]);

  // draw the current plane + selection
  useEffect(() => {
    if (!cube || !lims || !canvas.current) return;
    const det = cube.channels[k].det, [lo, hi] = lims[det];
    paint(canvas.current, cube.data[k], cube.n, makeScaler(lo, hi, disp.contrast, disp.bright), LUTS[disp.cmap]);
    const b = drag || box;
    if (b) {
      const ctx = canvas.current.getContext("2d"), s = W / cube.n;
      const x0 = Math.min(b.x0, b.x1), x1 = Math.max(b.x0, b.x1), y0 = Math.min(b.y0, b.y1), y1 = Math.max(b.y0, b.y1);
      ctx.strokeStyle = "#ffb547"; ctx.lineWidth = 2;
      ctx.strokeRect(x0 * s, (cube.n - 1 - y1) * s, (x1 - x0 + 1) * s, (y1 - y0 + 1) * s);
    }
  }, [cube, lims, k, box, drag, disp.contrast, disp.bright, disp.cmap]);

  const spec = useMemo(() => (cube && box ? boxSpectrum(cube, box) : []), [cube, box]);
  const others = useMemo(() => (compare && box ? mainVisits.map((v) => ({ v, pts: cubes[v.visit] ? boxSpectrum(cubes[v.visit], box) : null })) : []), [compare, box, cubes]);

  // ask the server which molecule/mineral bands show up in this area's spectrum
  useEffect(() => {
    if (spec.length < 10) return;
    const h = setTimeout(() => api.features(spec.map((p) => ({ wave: p.wave, flux: p.flux, err: p.err }))).then((r) => setFeatures(r.features)).catch(() => {}), 300);
    return () => clearTimeout(h);
  }, [spec]);

  // spectrum chart
  useEffect(() => {
    chart.current && chart.current.destroy();
    if (!spec.length || !chartEl.current) return;
    const cont = smooth(spec);
    const val = (p, i) => (resid ? (100 * (p.flux - cont[i])) / Math.abs(cont[i] || 1) : p.flux);
    const ds = [];
    if (!resid) {
      ds.push({ label: "±1σ", data: spec.map((p) => ({ x: p.wave, y: p.flux + p.err })), borderWidth: 0, pointRadius: 0, fill: "+1", backgroundColor: "rgba(255,181,71,.18)" });
      ds.push({ label: "_lo", data: spec.map((p) => ({ x: p.wave, y: p.flux - p.err })), borderWidth: 0, pointRadius: 0, fill: false });
    }
    ds.push({ label: resid ? "Difference from the smooth curve (%)" : (visit < 0 ? "All dates" : `Visit ${visit + 1}`),
      data: spec.map((p, i) => ({ x: p.wave, y: val(p, i), tip: `plane ${p.channel} · ${p.wave.toFixed(3)} µm · ${p.flux.toFixed(1)} ± ${p.err.toFixed(1)} µJy` })),
      borderColor: "#ffb547", borderWidth: 2, pointRadius: spec.map((p) => (p.channel === k + 1 ? 6 : 1.8)),
      pointBackgroundColor: spec.map((p) => (p.channel === k + 1 ? "#ffffff" : "#ffb547")) });
    if (!resid) ds.push({ label: "Smooth curve", data: spec.map((p, i) => ({ x: p.wave, y: cont[i] })), borderColor: "rgba(143,160,189,.7)", borderDash: [5, 4], borderWidth: 1.2, pointRadius: 0 });
    others.forEach(({ v, pts }, j) => pts && !resid && ds.push({ label: `Visit ${v.visit + 1} (${v.start.slice(0, 7)})`,
      data: pts.map((p) => ({ x: p.wave, y: p.flux, tip: `visit ${v.visit + 1} · ${p.wave.toFixed(3)} µm · ${p.flux.toFixed(1)} µJy` })),
      borderColor: VISIT_COLORS[(j + 1) % 6], borderWidth: 1.2, pointRadius: 0 }));
    const ax = (t) => ({ title: { display: true, text: t, color: "#8fa0bd" }, grid: { color: "#1b2943" }, ticks: { color: "#8fa0bd", font: { family: "JetBrains Mono", size: 10 } } });
    chart.current = new Chart(chartEl.current, {
      type: "line", data: { datasets: ds }, plugins: [bandsPlugin],
      options: { animation: false, maintainAspectRatio: false, parsing: false,
        onClick: (_e, els) => { if (els.length) { const p = spec[els[0].index]; if (p) setK(p.channel - 1); } },
        plugins: { legend: { labels: { color: "#8fa0bd", boxWidth: 12, font: { size: 10.5 }, filter: (l) => !l.text.startsWith("_") } },
          tooltip: { callbacks: { label: (c) => c.raw.tip || `${c.raw.y.toFixed(1)}` } },
          bands: { features, detectors: Object.fromEntries([1, 2, 3, 4, 5, 6].map((d) => [d, [cube.channels[(d - 1) * 17].wave_lo]])), showAll: false } },
        scales: { x: { type: "linear", min: 0.7, max: 5.05, ...ax("Wavelength λ (µm)") }, y: ax(resid ? "Difference from smooth (%)" : "Flux density Fν (µJy)") } },
    });
    return () => chart.current && chart.current.destroy();
  }, [spec, others, resid, k, features]);

  const pix = (e) => {
    const r = e.currentTarget.getBoundingClientRect();
    return [Math.floor(((e.clientX - r.left) / r.width) * cube.n), cube.n - 1 - Math.floor(((e.clientY - r.top) / r.height) * cube.n)];
  };
  const down = (e) => { const [x, y] = pix(e); setDrag({ x0: x, y0: y, x1: x, y1: y }); };
  const move = (e) => { if (drag) { const [x, y] = pix(e); setDrag((d) => ({ ...d, x1: x, y1: y })); } };
  const up = () => {
    if (!drag) return;
    const single = drag.x0 === drag.x1 && drag.y0 === drag.y1;
    setBox(single ? { x0: drag.x0 - 1, y0: drag.y0 - 1, x1: drag.x0 + 1, y1: drag.y0 + 1 } : drag);
    setDrag(null);
  };

  if (!cube) return <p className="hint">{busy ? "Building the 102-colour cube…" : "Cube not available."}</p>;
  const c = cube.channels[k];
  const stack = [...new Set([...Array.from({ length: 12 }, (_, i) => Math.round((i * 101) / 11)), k])].sort((a, b) => a - b);
  const bw = box ? Math.abs(box.x1 - box.x0) + 1 : 0, bh = box ? Math.abs(box.y1 - box.y0) + 1 : 0;
  const seen = features.filter((f) => f.status === "likely" || f.status === "possible");

  return (
    <div className="cubeView">
      <div className="row">
        <label>Dates <select value={visit} onChange={(e) => setVisit(+e.target.value)}>
          <option value={-1}>All dates combined (deepest)</option>
          {mainVisits.map((v) => <option key={v.visit} value={v.visit}>Visit {v.visit + 1}: {v.start}</option>)}
        </select></label>
        <label className="tog"><input type="checkbox" checked={grid} onChange={() => setGrid(!grid)} /> show all 102 at once</label>
        <span className="hint small">{cube.exposures_used} snapshots sorted into 102 colour planes</span>
      </div>

      {grid ? (
        <div className="planesGrid">
          {cube.channels.map((ch, i) => <CubeTile key={i} cube={cube} i={i} lims={lims} disp={disp} on={i === k} onPick={() => { setK(i); setGrid(false); }} />)}
        </div>
      ) : (
        <div className="cubeMain">
          <div>
            <div className="canvasWrap cubeCanvas">
              <canvas ref={canvas} width={W} height={W} onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerLeave={() => setDrag(null)} aria-label={`Plane ${k + 1}`} />
              <div className="stamp"><b style={{ color: DET_COLORS[c.det - 1] }}>{c.wave?.toFixed(2)} µm</b><span>plane {k + 1} of 102 · detector D{c.det} · ≈{c.snapshots_per_pixel} snapshots per pixel</span></div>
            </div>
            <div className="player">
              <button className="primary play" onClick={() => setPlaying(!playing)}>{playing ? "⏸ Pause" : "▶ Fly through colours"}</button>
              <input type="range" min="0" max="101" value={k} onChange={(e) => setK(+e.target.value)} aria-label="Wavelength plane" />
              <span className="mono frameLbl">{k + 1}/102</span>
            </div>
            <div className="rainbow" aria-hidden="true">{cube.channels.map((ch, i) => <i key={i} style={{ background: DET_COLORS[ch.det - 1], opacity: i === k ? 1 : 0.35 }} onClick={() => setK(i)} />)}</div>
          </div>
          <div className="stackBox" aria-label="The 102 planes stacked like pages">
            <div className="stack">
              {stack.map((i, j) => <StackLayer key={i} cube={cube} i={i} lims={lims} disp={disp} box={box} on={i === k} z={j} onPick={() => setK(i)} />)}
            </div>
            <p className="small muted center">Planes stacked by colour: 0.75 µm at the bottom, 5 µm on top. The orange box goes straight down through every plane.</p>
          </div>
        </div>
      )}

      <div className="cubeSpec">
        <div className="row">
          <b>Spectrum of the {bw * bh <= 9 ? "selected spot" : `selected ${bw}×${bh}-pixel area`}</b>
          <span className="hint small">click a star, or drag a box around it</span>
          <label className="tog"><input type="checkbox" checked={resid} onChange={() => setResid(!resid)} /> show only the bumps and dips</label>
          {mainVisits.length > 1 && <label className="tog"><input type="checkbox" checked={compare} onChange={() => setCompare(!compare)} /> compare dates</label>}
        </div>
        <div className="chartBox tall"><canvas ref={chartEl} aria-label="Spectrum from the cube" /></div>
        <p className="note">
          Read straight down through all 102 planes. A star's light makes a <b>smooth curve</b> (dashed). Places where the real spectrum
          <b> dips below</b> or <b>bumps above</b> it are where molecules absorb or glow.
          {seen.length ? <> Here: {seen.slice(0, 4).map((f) => `${f.name} (${f.change_pct > 0 ? "+" : ""}${f.change_pct}%, ${f.status})`).join(" · ")}.</> : " No band stands out above 3σ here."}
          {" "}Click the chart to jump to that plane.
        </p>
      </div>
    </div>
  );
}

function CubeTile({ cube, i, lims, disp, on, onPick }) {
  const ref = useRef(null);
  const ch = cube.channels[i];
  useEffect(() => {
    const [lo, hi] = lims[ch.det];
    paint(ref.current, cube.data[i], cube.n, makeScaler(lo, hi, disp.contrast, disp.bright), LUTS[disp.cmap]);
  }, [cube, i, lims, disp.contrast, disp.bright, disp.cmap]);
  return (
    <figure className={on ? "on" : ""} onClick={onPick} title={`Plane ${i + 1}: ${ch.wave_lo}–${ch.wave_hi} µm`}>
      <canvas ref={ref} width={cube.n} height={cube.n} />
      <figcaption style={{ color: DET_COLORS[ch.det - 1] }}>{i + 1}<br />{ch.wave?.toFixed(2)}µm</figcaption>
    </figure>
  );
}

function StackLayer({ cube, i, lims, disp, box, on, z, onPick }) {
  const ref = useRef(null);
  const ch = cube.channels[i];
  useEffect(() => {
    const [lo, hi] = lims[ch.det];
    paint(ref.current, cube.data[i], cube.n, makeScaler(lo, hi, disp.contrast, disp.bright), LUTS[disp.cmap]);
    if (box) {
      const ctx = ref.current.getContext("2d"), s = ref.current.width / cube.n;
      const x0 = Math.min(box.x0, box.x1), x1 = Math.max(box.x0, box.x1), y0 = Math.min(box.y0, box.y1), y1 = Math.max(box.y0, box.y1);
      ctx.strokeStyle = "#ffb547"; ctx.lineWidth = 3;
      ctx.strokeRect(x0 * s, (cube.n - 1 - y1) * s, (x1 - x0 + 1) * s, (y1 - y0 + 1) * s);
    }
  }, [cube, i, lims, box, disp.contrast, disp.bright, disp.cmap]);
  return (
    <div className={`layer ${on ? "on" : ""}`} style={{ transform: `translateZ(${z * 13}px)`, zIndex: z, borderColor: on ? "#ffb547" : DET_COLORS[ch.det - 1] }}
      onClick={onPick} title={`Plane ${i + 1}: ${ch.wave?.toFixed(2)} µm`}>
      <canvas ref={ref} width="160" height="160" />
      <span style={{ color: DET_COLORS[ch.det - 1] }}>{ch.wave?.toFixed(2)} µm</span>
    </div>
  );
}
