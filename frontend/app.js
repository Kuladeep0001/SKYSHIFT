/* SkyShift front end: loads aligned SPHEREx frames from the API and plays them like a flipbook. */
"use strict";

const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];

const TARGETS = [
  { label: "Barnard's Star", q: "Barnard's Star", note: "fast star" },
  { label: "Epsilon Indi B", q: "eps Ind B", note: "brown dwarfs" },
  { label: "WISE 0855", q: "WISE J085510.83-071442.5", note: "fast brown dwarf" },
  { label: "RW Aurigae", q: "RW Aur", note: "variable" },
  { label: "R Draconis", q: "R Dra", note: "variable" },
];
const DET_COLORS = ["#7a8cff", "#55c6ff", "#53d8c4", "#b6e35a", "#ffb547", "#ff6b6b"];
const VISIT_COLORS = ["#53d8c4", "#ffb547", "#ff6b8b", "#5ab0ff", "#c38bff", "#b6e35a"];
const PIX = 6.15; // arcsec per pixel

const S = {
  target: null, fov: 6, rel: "", job: null, sum: null,
  view: "blink", mode: "visit", det: 0, ch: 40, visit: 0,
  F: null, idx: 0, playing: true, fps: 2,
  contrast: 0.55, bright: 0.5, cmap: "gray", math: "none",
  sel: null, cats: {}, ast: {}, wallF: null, planesF: null,
};
const params = new URLSearchParams(location.search);
const embed = params.get("embed") === "1" || location.pathname.endsWith("/embed");
if (embed) document.body.classList.add("embed");

/* ------------------------------------------------------------------ utils */
function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.remove("show"), 2600);
}
async function api(path) {
  const r = await fetch(path);
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch (_) {}
    throw new Error(msg);
  }
  return r.json();
}
function b64ToBytes(b64) {
  const bin = atob(b64);
  const u8 = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
  return u8;
}
function decodeFrames(res) {
  const n = res.n, nn = n * n;
  const bytes = res.data ? b64ToBytes(res.data) : new Uint8Array(0);
  const warn = res.warn ? b64ToBytes(res.warn) : new Uint8Array(0);
  const data = [], flags = [];
  for (let k = 0; k < res.count; k++) {
    data.push(new Float32Array(bytes.buffer, k * nn * 4, nn));
    flags.push(warn.subarray(k * nn, (k + 1) * nn));
  }
  return { n, list: res.frames, data, flags, mode: res.mode };
}
function percentile(arrs, ps, absval = false) {
  const sample = [];
  for (const a of arrs) {
    const step = Math.max(1, Math.floor(a.length / 4000));
    for (let i = 0; i < a.length; i += step) {
      const v = a[i];
      if (Number.isFinite(v)) sample.push(absval ? Math.abs(v) : v);
    }
  }
  if (!sample.length) return ps.map(() => 0);
  sample.sort((x, y) => x - y);
  return ps.map((p) => sample[Math.min(sample.length - 1, Math.floor((p / 100) * sample.length))]);
}
const mjdToYear = (mjd) => 2000 + (mjd - 51544.5) / 365.25;
const fmtWave = (w) => (w == null ? "—" : `${w.toFixed(3)} µm`);
const fmtRA = (ra) => { const h = ra / 15; const hh = Math.floor(h); const m = (h - hh) * 60; const mm = Math.floor(m); return `${String(hh).padStart(2, "0")}h${String(mm).padStart(2, "0")}m${((m - mm) * 60).toFixed(2).padStart(5, "0")}s`; };
const fmtDec = (d) => { const s = d < 0 ? "−" : "+"; d = Math.abs(d); const dd = Math.floor(d); const m = (d - dd) * 60; const mm = Math.floor(m); return `${s}${String(dd).padStart(2, "0")}°${String(mm).padStart(2, "0")}′${((m - mm) * 60).toFixed(1).padStart(4, "0")}″`; };

/* ------------------------------------------------------------- colour maps */
const INFERNO = [[0, 0, 4], [40, 11, 84], [101, 21, 110], [159, 42, 99], [212, 72, 66], [245, 125, 21], [250, 193, 39], [252, 255, 164]];
function lutFrom(stops) {
  const lut = new Uint8ClampedArray(256 * 3);
  for (let i = 0; i < 256; i++) {
    const t = (i / 255) * (stops.length - 1), k = Math.min(stops.length - 2, Math.floor(t)), f = t - k;
    for (let c = 0; c < 3; c++) lut[i * 3 + c] = stops[k][c] * (1 - f) + stops[k + 1][c] * f;
  }
  return lut;
}
const LUTS = {
  gray: lutFrom([[0, 0, 0], [255, 255, 255]]),
  invert: lutFrom([[255, 255, 255], [0, 0, 0]]),
  inferno: lutFrom(INFERNO),
  diverge: lutFrom([[40, 110, 255], [10, 20, 45], [255, 170, 60]]),
};

/* Map values to 0..255 with an asinh stretch (shows faint and bright things at once). */
function makeScaler(lo, hi) {
  const beta = Math.pow(10, S.contrast * 3) - 0.999;
  const hiEff = lo + (hi - lo) * Math.pow(10, (0.5 - S.bright) * 1.6);
  const span = hiEff - lo || 1, norm = Math.asinh(beta) || 1;
  return (v) => {
    let t = (v - lo) / span;
    t = t <= 0 ? 0 : t >= 1 ? 1 : Math.asinh(t * beta) / norm;
    return (t * 255) | 0;
  };
}
function makeDivScaler(L) {
  const beta = Math.pow(10, S.contrast * 3) - 0.999, norm = Math.asinh(beta) || 1;
  const Le = L * Math.pow(10, (0.5 - S.bright) * 1.6) || 1;
  return (v) => {
    let t = Math.max(-1, Math.min(1, v / Le));
    t = Math.sign(t) * Math.asinh(Math.abs(t) * beta) / norm;
    return ((t + 1) * 127.5) | 0;
  };
}

/* ---------------------------------------------------------- frame maths */
function sumFrames(F) {
  const nn = F.n * F.n, out = new Float32Array(nn), cnt = new Uint16Array(nn);
  for (const a of F.data) for (let i = 0; i < nn; i++) if (Number.isFinite(a[i])) { out[i] += a[i]; cnt[i]++; }
  for (let i = 0; i < nn; i++) out[i] = cnt[i] ? out[i] / cnt[i] : NaN;
  return out;
}
function diffFrame(a, b) {
  const out = new Float32Array(a.length);
  for (let i = 0; i < a.length; i++) out[i] = a[i] - b[i];
  return out;
}
/* What to display for frame i, given the add/subtract setting. */
function displayed(F, i) {
  if (S.math === "sum") return { arr: F._sum || (F._sum = sumFrames(F)), diverge: false };
  if (S.math === "first" && i > 0) return { arr: diffFrame(F.data[i], F.data[0]), diverge: true };
  if (S.math === "prev" && i > 0) return { arr: diffFrame(F.data[i], F.data[i - 1]), diverge: true };
  // In difference mode the first frame is the reference, shown normally.
  return { arr: F.data[i], diverge: false, ref: S.math === "first" || S.math === "prev" };
}
function limits(F) {
  if (!F._base) { const [lo, hi] = percentile(F.data, [3, 99.8]); F._base = { lo, hi }; }
  if (S.math === "sum") {
    if (!F._sumLim) { const [lo, hi] = percentile([displayed(F, 0).arr], [3, 99.8]); F._sumLim = { lo, hi }; }
    return F._sumLim;
  }
  if (S.math === "first" || S.math === "prev") {
    if (!F._dl || F._dl.key !== S.math) {
      const diffs = [];
      for (let i = 1; i < F.data.length; i++) diffs.push(displayed(F, i).arr);
      F._dl = { key: S.math, L: percentile(diffs.length ? diffs : [F.data[0]], [99.5], true)[0], ...F._base };
    }
    return F._dl;
  }
  return F._base;
}

/* ---------------------------------------------------------- drawing */
const off = document.createElement("canvas");
function paint(canvas, arr, n, scaler, lut, flags) {
  off.width = off.height = n;
  const octx = off.getContext("2d");
  const img = octx.createImageData(n, n);
  const d = img.data;
  for (let r = 0; r < n; r++) {
    const src = (n - 1 - r) * n; // FITS row 0 is south; flip so north is up
    for (let c = 0; c < n; c++) {
      const v = arr[src + c], o = (r * n + c) * 4;
      if (!Number.isFinite(v)) { d[o] = 18; d[o + 1] = 22; d[o + 2] = 34; d[o + 3] = 255; continue; }
      const k = scaler(v) * 3;
      d[o] = lut[k]; d[o + 1] = lut[k + 1]; d[o + 2] = lut[k + 2]; d[o + 3] = 255;
      if (flags && flags[src + c]) { d[o] = (d[o] + 255) >> 1; d[o + 1] = (d[o + 1] + 138) >> 1; d[o + 2] = (d[o + 2] + 61) >> 1; }
    }
  }
  octx.putImageData(img, 0, 0);
  const ctx = canvas.getContext("2d");
  ctx.imageSmoothingEnabled = false;
  ctx.drawImage(off, 0, 0, canvas.width, canvas.height);
}

/* Sky position -> canvas pixel on our north-up grid (gnomonic projection). */
function skyToCanvas(ra, dec, n, W) {
  const r = Math.PI / 180, a0 = S.target.ra * r, d0 = S.target.dec * r, a = ra * r, d = dec * r;
  const cosc = Math.sin(d0) * Math.sin(d) + Math.cos(d0) * Math.cos(d) * Math.cos(a - a0);
  const xi = (Math.cos(d) * Math.sin(a - a0)) / cosc / r * 3600; // arcsec east
  const eta = ((Math.cos(d0) * Math.sin(d) - Math.sin(d0) * Math.cos(d) * Math.cos(a - a0)) / cosc) / r * 3600;
  const x0 = (n - 1) / 2 - xi / PIX, y0 = (n - 1) / 2 + eta / PIX;
  const s = W / n;
  return [(x0 + 0.5) * s, (n - 1 - y0 + 0.5) * s];
}

function drawOverlays(canvas, n, frame) {
  const ctx = canvas.getContext("2d"), W = canvas.width, s = W / n;
  const year = frame && frame.mjd ? mjdToYear(frame.mjd) : 2026;
  ctx.lineWidth = 1.6;
  if ($("#ovCross").checked) {
    ctx.strokeStyle = "rgba(83,216,196,.75)";
    const c = W / 2, g = 7 * s / 2 + 6;
    ctx.beginPath();
    ctx.moveTo(c - g - 14, c); ctx.lineTo(c - g, c); ctx.moveTo(c + g, c); ctx.lineTo(c + g + 14, c);
    ctx.moveTo(c, c - g - 14); ctx.lineTo(c, c - g); ctx.moveTo(c, c + g); ctx.lineTo(c, c + g + 14);
    ctx.stroke();
  }
  // Known stars, moved to this frame's date using their proper motion. Fast movers get a label.
  const drawCat = (cat, color, epoch, magLimit) => {
    if (!cat) return;
    const dt = year - epoch;
    ctx.font = "600 12px Inter, sans-serif";
    for (const st of cat.stars) {
      const pm = Math.hypot(st.pmra, st.pmdec);
      const fast = pm > 150;
      if (!fast && (st.mag ?? 99) > magLimit) continue;
      const dec = st.dec + (st.pmdec * dt) / 3.6e6;
      const ra = st.ra + (st.pmra * dt) / 3.6e6 / Math.cos((st.dec * Math.PI) / 180);
      const [x, y] = skyToCanvas(ra, dec, n, W);
      if (x < -10 || y < -10 || x > W + 10 || y > W + 10) continue;
      const rad = Math.max(5, Math.min(15, (18 - (st.mag ?? 15)) * 1.2)) * Math.max(1, s / 10);
      ctx.globalAlpha = fast ? 1 : 0.55;
      ctx.strokeStyle = fast ? "#53d8c4" : color;
      ctx.lineWidth = fast ? 2.2 : 1.3;
      ctx.beginPath(); ctx.arc(x, y, rad, 0, 2 * Math.PI); ctx.stroke();
      if (fast) {
        ctx.fillStyle = "#53d8c4";
        ctx.fillText(`${(pm / 1000).toFixed(2)}″/yr`, x + rad + 4, y - rad);
      }
    }
    ctx.globalAlpha = 1;
  };
  if ($("#ovGaia").checked) drawCat(S.cats.gaia, "#5ab0ff", 2016.0, 16.5);
  if ($("#ovWise").checked) drawCat(S.cats.allwise, "#c38bff", 2010.5, 13.5);
  if ($("#ovAst").checked && frame) {
    const key = frame.mjd.toFixed(3), ast = S.ast[key];
    if (ast && ast.objects) {
      ctx.strokeStyle = ctx.fillStyle = "#ff6b8b";
      ctx.font = "12px Inter, sans-serif";
      for (const o of ast.objects) {
        const [x, y] = skyToCanvas(o.ra, o.dec, n, W);
        if (x < 0 || y < 0 || x > W || y > W) continue;
        ctx.beginPath(); ctx.rect(x - 9, y - 9, 18, 18); ctx.stroke();
        ctx.fillText(o.name, x + 12, y + 4);
      }
    } else if (!ast) loadAsteroids(frame.mjd);
  }
  if (S.sel) {
    ctx.strokeStyle = "#ffb547"; ctx.lineWidth = 2;
    const x = S.sel.x, y = n - 1 - S.sel.y;
    ctx.strokeRect((x - 1) * s, (y - 1) * s, 3 * s, 3 * s);
  }
}

function frameLabel(f) {
  if (!f) return "";
  if (S.F && S.F.mode === "exposure") return `${f.date} UT\nD${f.det} · ${fmtWave(f.wave)} · plane ${f.channel}`;
  const det = f.det ? `D${f.det}` : "All detectors";
  const ch = f.channel ? ` · plane ${f.channel}` : "";
  return `Visit ${f.visit + 1}: ${f.date_range[0]} → ${f.date_range[1]}\n${det}${ch} · ${f.n_exp} exposures stacked`;
}

function renderMain() {
  const F = S.F;
  if (!F || !F.data.length) return;
  const i = Math.min(S.idx, F.data.length - 1);
  const { arr, diverge, ref } = displayed(F, i);
  const lim = limits(F);
  const scaler = diverge ? makeDivScaler(lim.L) : makeScaler(lim.lo, lim.hi);
  const lut = diverge ? LUTS.diverge : LUTS[S.cmap];
  const canvas = $("#main");
  paint(canvas, arr, F.n, scaler, lut, $("#ovFlags").checked ? F.flags[i] : null);
  drawOverlays(canvas, F.n, F.list[i]);
  $("#stamp").textContent = S.math === "sum" ? `All ${F.data.length} frames added together`
    : (ref ? "REFERENCE (subtracted from the other frames)
" : diverge ? `MINUS ${S.math === "first" ? "frame 1" : "previous frame"}: orange = brighter now, blue = was brighter
` : "") + frameLabel(F.list[i]);
  $("#frameLbl").textContent = `${i + 1}/${F.data.length}`;
  $("#scrub").value = i;
  renderMeta(F.list[i]);
  highlightTimeline(F.list[i]);
}

function renderWall() {
  const F = S.wallF;
  if (!F) return;
  const visits = [...new Set(F.list.map((f) => f.visit))].sort((a, b) => a - b);
  const v = visits[S.idx % visits.length];
  const wall = $("#wall");
  if (!wall.children.length) {
    for (let d = 1; d <= 6; d++) {
      const fig = document.createElement("figure");
      fig.innerHTML = `<canvas width="360" height="360" data-det="${d}"></canvas><figcaption></figcaption>`;
      fig.querySelector("canvas").addEventListener("click", (e) => clickCanvas(e, F.n));
      wall.appendChild(fig);
    }
  }
  for (let d = 1; d <= 6; d++) {
    const fig = wall.children[d - 1], cv = fig.querySelector("canvas");
    const idxs = F.list.map((f, k) => (f.det === d ? k : -1)).filter((k) => k >= 0);
    const k = idxs.find((j) => F.list[j].visit === v);
    const range = S.sum.detectors[d];
    fig.querySelector("figcaption").innerHTML = `<b style="color:${DET_COLORS[d - 1]}">D${d}</b> ${range ? range[0].toFixed(2) + "–" + range[1].toFixed(2) + " µm" : ""}`;
    if (k === undefined) { cv.getContext("2d").clearRect(0, 0, cv.width, cv.height); continue; }
    if (!F._dlim) F._dlim = {};
    if (!F._dlim[d]) { const [lo, hi] = percentile(idxs.map((j) => F.data[j]), [3, 99.8]); F._dlim[d] = { lo, hi }; }
    let arr = F.data[k], diverge = false;
    if (S.math === "first") { const k0 = idxs[0]; if (k !== k0) { arr = diffFrame(F.data[k], F.data[k0]); diverge = true; } }
    const lim = F._dlim[d];
    const scaler = diverge ? makeDivScaler((lim.hi - lim.lo) / 3) : makeScaler(lim.lo, lim.hi);
    paint(cv, arr, F.n, scaler, diverge ? LUTS.diverge : LUTS[S.cmap], null);
    drawOverlays(cv, F.n, F.list[k]);
  }
  const f0 = F.list.find((f) => f.visit === v);
  $("#frameLbl").textContent = `${visits.indexOf(v) + 1}/${visits.length}`;
  $("#scrub").max = visits.length - 1;
  $("#scrub").value = visits.indexOf(v);
  renderMeta({ ...f0, wave: null, det: "all 6 (one panel each)", n_exp: F.list.filter((f) => f.visit === v).reduce((a, f) => a + f.n_exp, 0) });
}

function renderColor() {
  const F = S.wallF;
  if (!F) return;
  const visits = [...new Set(F.list.map((f) => f.visit))].sort((a, b) => a - b);
  const v = visits[S.idx % visits.length];
  const n = F.n, nn = n * n;
  // blue = D1+D2 (shortest), green = D3+D4, red = D5+D6 (longest wavelengths)
  const groups = [[5, 6], [3, 4], [1, 2]];
  if (!F._clim) {
    F._clim = groups.map((g) => {
      const arrs = F.list.map((f, k) => (g.includes(f.det) ? F.data[k] : null)).filter(Boolean);
      return percentile(arrs, [5, 99.7]);
    });
  }
  const chans = groups.map((g, gi) => {
    const out = new Float32Array(nn);
    let cnt = 0;
    F.list.forEach((f, k) => {
      if (f.visit === v && g.includes(f.det)) { cnt++; const a = F.data[k]; for (let i = 0; i < nn; i++) out[i] += Number.isFinite(a[i]) ? a[i] : 0; }
    });
    if (cnt) for (let i = 0; i < nn; i++) out[i] /= cnt;
    const [lo, hi] = F._clim[gi];
    return { arr: out, sc: makeScaler(lo, hi) };
  });
  off.width = off.height = n;
  const octx = off.getContext("2d"), img = octx.createImageData(n, n), d = img.data;
  for (let r = 0; r < n; r++) {
    const src = (n - 1 - r) * n;
    for (let c = 0; c < n; c++) {
      const o = (r * n + c) * 4;
      d[o] = chans[0].sc(chans[0].arr[src + c]); d[o + 1] = chans[1].sc(chans[1].arr[src + c]);
      d[o + 2] = chans[2].sc(chans[2].arr[src + c]); d[o + 3] = 255;
    }
  }
  octx.putImageData(img, 0, 0);
  const canvas = $("#main"), ctx = canvas.getContext("2d");
  ctx.imageSmoothingEnabled = false;
  ctx.drawImage(off, 0, 0, canvas.width, canvas.height);
  const f0 = F.list.find((f) => f.visit === v);
  drawOverlays(canvas, n, f0);
  $("#stamp").textContent = `Visit ${v + 1}: ${f0.date_range[0]} → ${f0.date_range[1]}\nRed = D5+D6 (3.8–5 µm) · Green = D3+D4 · Blue = D1+D2`;
  $("#frameLbl").textContent = `${visits.indexOf(v) + 1}/${visits.length}`;
  $("#scrub").max = visits.length - 1;
  $("#scrub").value = visits.indexOf(v);
  renderMeta({ ...f0, wave: null, det: "colour composite (all 6)", n_exp: F.list.filter((f) => f.visit === v).reduce((a, f) => a + f.n_exp, 0) });
}

function renderPlanes() {
  const F = S.planesF, grid = $("#planesGrid");
  grid.innerHTML = "";
  if (!F) return;
  const byCh = {};
  F.list.forEach((f, k) => (byCh[f.channel] = k));
  const detLim = {};
  for (let d = 1; d <= 6; d++) {
    const arrs = F.list.map((f, k) => (f.det === d ? F.data[k] : null)).filter(Boolean);
    detLim[d] = percentile(arrs.length ? arrs : [new Float32Array(1)], [3, 99.8]);
  }
  for (let ch = 1; ch <= 102; ch++) {
    const info = S.sum.channels[ch - 1], k = byCh[ch];
    const fig = document.createElement("figure");
    fig.title = info.wave ? `Plane ${ch}: ${info.wave[0].toFixed(3)}–${info.wave[1].toFixed(3)} µm (D${info.det})` : `Plane ${ch}`;
    fig.innerHTML = `<canvas width="${F.n}" height="${F.n}"></canvas><figcaption>${ch}<br>${info.wave ? ((info.wave[0] + info.wave[1]) / 2).toFixed(2) + "µm" : ""}</figcaption>`;
    if (k === undefined) fig.classList.add("empty");
    else {
      const [lo, hi] = detLim[info.det];
      paint(fig.querySelector("canvas"), F.data[k], F.n, makeScaler(lo, hi), LUTS[S.cmap], null);
      fig.querySelector("figcaption").style.color = DET_COLORS[info.det - 1];
      fig.addEventListener("click", () => {
        S.ch = ch; $("#plane").value = ch;
        setView("blink"); setMode("channel");
      });
    }
    grid.appendChild(fig);
  }
}

function render() {
  if (S.view === "blink") renderMain();
  else if (S.view === "wall") renderWall();
  else if (S.view === "color") renderColor();
}

/* ------------------------------------------------------------ metadata */
function renderMeta(f) {
  const t = S.target, rows = [];
  rows.push(["Target", t.name ? `${t.name}` : "Custom position"]);
  rows.push(["RA, Dec", `${fmtRA(t.ra)} ${fmtDec(t.dec)}<br>${t.ra.toFixed(5)}° ${t.dec.toFixed(5)}°`]);
  if (t.pm_corrected) rows.push(["Motion", `centred for ${t.pmra.toFixed(0)}, ${t.pmdec.toFixed(0)} mas/yr (epoch 2026)`]);
  rows.push(["View", `${S.fov}′ × ${S.fov}′ · ${S.sum.n_pix}×${S.sum.n_pix} px of ${PIX}″`]);
  rows.push(["Data", `${S.sum.exposures.length} exposures · ${S.job.releases.join(" + ")}`]);
  if (f) {
    rows.push(["Date", f.date_range ? `${f.date_range[0]} → ${f.date_range[1]}` : `${f.date} UT`]);
    if (f.visit !== undefined) rows.push(["Visit", `${f.visit + 1} of ${S.sum.visits.length}`]);
    rows.push(["Detector", typeof f.det === "number" ? (f.det ? `D${f.det} (${S.sum.detectors[f.det].map((x) => x.toFixed(2)).join("–")} µm)` : "all 6 combined") : f.det]);
    if (f.wave) rows.push(["Wavelength", `${fmtWave(f.wave)}${f.channel ? ` · plane ${f.channel} of 102` : ""}`]);
    if (f.n_exp) rows.push(["Exposures", `${f.n_exp} stacked`]);
    if (f.obs_id) rows.push(["Exposure ID", f.obs_id]);
    const F = S.view === "blink" ? S.F : null;
    if (F) {
      const fl = F.flags[Math.min(S.idx, F.flags.length - 1)];
      let c = 0;
      for (let i = 0; i < fl.length; i++) c += fl[i];
      rows.push(["Contaminated", `${((100 * c) / fl.length).toFixed(1)}% of pixels <small>(ghost, streak, halo, crosstalk…)</small>`]);
    }
  }
  if (S.selFlags) rows.push(["Flags at pixel", S.selFlags.length ? S.selFlags.map((x) => `<span class="flag" title="${(S.sum.flag_defs[x] || {}).meaning || ""}">${x}</span>`).join("") : "none"]);
  $("#meta").innerHTML = rows.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("");
}

/* ------------------------------------------------------------ timeline */
function drawTimeline() {
  const svg = $("#timeline"), ex = S.sum.exposures;
  const W = svg.clientWidth || 800, H = 74, padL = 30, padR = 10;
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  const t0 = Math.min(...ex.map((e) => e.mjd)) - 5, t1 = Math.max(...ex.map((e) => e.mjd)) + 5;
  const x = (m) => padL + ((m - t0) / (t1 - t0)) * (W - padL - padR);
  let html = "";
  for (let d = 1; d <= 6; d++) html += `<text x="2" y="${6 + d * 9}">D${d}</text>`;
  for (const v of S.sum.visits) {
    const a = ex.filter((e) => e.visit === v.visit);
    const x0 = x(Math.min(...a.map((e) => e.mjd))) - 4, x1 = x(Math.max(...a.map((e) => e.mjd))) + 4;
    html += `<rect class="vband" data-visit="${v.visit}" x="${x0}" y="4" width="${Math.max(8, x1 - x0)}" height="56" rx="4" fill="#ffffff08" stroke="#ffffff14"/>`;
    html += `<text x="${x0}" y="72">${v.start}</text>`;
  }
  for (const e of ex) html += `<circle data-i="${e.i}" cx="${x(e.mjd).toFixed(1)}" cy="${6 + e.det * 9 - 3}" r="2.3" fill="${DET_COLORS[e.det - 1]}" opacity=".85"/>`;
  html += `<rect id="tlCursor" x="0" y="2" width="3" height="60" fill="#ffb547" opacity=".0"/>`;
  svg.innerHTML = html;
  svg._x = x;
}
function highlightTimeline(f) {
  const svg = $("#timeline"), cur = $("#tlCursor");
  if (!svg._x || !cur || !f) return;
  if (f.date_range && S.F.mode !== "exposure") {
    const a = S.sum.exposures.filter((e) => e.visit === f.visit);
    const x0 = svg._x(Math.min(...a.map((e) => e.mjd))) - 4, x1 = svg._x(Math.max(...a.map((e) => e.mjd))) + 4;
    cur.setAttribute("x", x0); cur.setAttribute("width", Math.max(8, x1 - x0)); cur.setAttribute("opacity", ".25");
  } else {
    cur.setAttribute("x", svg._x(f.mjd) - 1.5); cur.setAttribute("width", 3); cur.setAttribute("opacity", ".9");
  }
}

/* ------------------------------------------------------------- spectrum */
let specChart = null, lcChart = null;
function chartOpts(xTitle, yTitle, timeAxis) {
  return {
    animation: false, maintainAspectRatio: false, parsing: false,
    plugins: { legend: { labels: { color: "#8fa0bd", boxWidth: 10, font: { size: 11 } } },
      tooltip: { callbacks: { label: (c) => c.raw.tip || `${c.raw.x}, ${c.raw.y}` } } },
    scales: {
      x: { title: { display: true, text: xTitle, color: "#8fa0bd" }, ticks: { color: "#8fa0bd", callback: timeAxis ? (v) => new Date((v - 40587) * 864e5).toISOString().slice(0, 7) : undefined }, grid: { color: "#1e2c47" } },
      y: { title: { display: true, text: yTitle, color: "#8fa0bd" }, ticks: { color: "#8fa0bd" }, grid: { color: "#1e2c47" } },
    },
  };
}
async function loadSpectrum(x, y) {
  if (!S.job || typeof Chart === "undefined") return;
  S.sel = { x, y };
  render();
  $("#specHint").textContent = `pixel (${x}, ${y}) · loading…`;
  try {
    const sp = await api(`/api/job/${S.job.id}/spectrum?x=${x}&y=${y}&r=1`);
    const byVisit = {}, byDet = {}, sat = [];
    for (const p of sp.points) {
      const tip = `${p.date} · D${p.det} · ${p.wave.toFixed(3)} µm · ${p.flux.toFixed(0)} µJy${p.flags.length ? " · " + p.flags.join(",") : ""}`;
      (byDet[p.det] ||= []).push({ x: p.mjd, y: p.flux, tip: tip + (p.saturated ? " (saturated)" : "") });
      if (p.saturated) { sat.push({ x: p.wave, y: p.flux, tip: tip + " (saturated)" }); continue; }
      (byVisit[p.visit] ||= []).push({ x: p.wave, y: p.flux, tip });
    }
    const vs = S.sum.visits;
    const specData = Object.keys(byVisit).map((v) => ({
      label: `Visit ${+v + 1} (${vs[v] ? vs[v].start.slice(0, 7) : ""})`, data: byVisit[v].sort((a, b) => a.x - b.x),
      showLine: false, pointRadius: 2.6, backgroundColor: VISIT_COLORS[v % VISIT_COLORS.length], borderColor: VISIT_COLORS[v % VISIT_COLORS.length],
    }));
    if (sat.length) specData.push({ label: "Saturated (too bright)", data: sat.sort((a, b) => a.x - b.x), showLine: false,
      pointRadius: 2.6, pointStyle: "crossRot", borderColor: "#5f7193", backgroundColor: "#5f7193" });
    const lcData = Object.keys(byDet).map((d) => ({
      label: `D${d}`, data: byDet[d], showLine: false, pointRadius: 2.4,
      backgroundColor: DET_COLORS[d - 1], borderColor: DET_COLORS[d - 1],
    }));
    specChart && specChart.destroy();
    lcChart && lcChart.destroy();
    specChart = new Chart($("#specChart"), { type: "scatter", data: { datasets: specData }, options: chartOpts("Wavelength (µm)", "Flux (µJy)") });
    lcChart = new Chart($("#lcChart"), { type: "scatter", data: { datasets: lcData }, options: chartOpts("Date", "Flux (µJy)", true) });
    $("#specHint").textContent = `pixel (${x}, ${y}) · ${sp.points.length} measurements`;
    $("#specNote").textContent = (sat.length > sp.points.length / 2
      ? "⚠ This source is so bright it saturates SPHEREx, so its measured brightness is only a lower limit. Try a fainter star nearby. "
      : "") + "Each dot is one SPHEREx exposure (3×3 pixel box, local sky removed). If the visits don't match, the source changed or moved.";
    const mid = sp.points.find((p) => p.i === (S.F && S.F.list[S.idx] && S.F.list[S.idx].members ? S.F.list[S.idx].members[0] : -1));
    S.selFlags = mid ? mid.flags : [...new Set(sp.points.flatMap((p) => p.flags))];
    render();
  } catch (e) {
    $("#specHint").textContent = "spectrum failed";
    toast(e.message);
  }
}
function clickCanvas(e, n) {
  const rect = e.target.getBoundingClientRect();
  const cx = ((e.clientX - rect.left) / rect.width) * n, cy = ((e.clientY - rect.top) / rect.height) * n;
  const x = Math.floor(cx), y = n - 1 - Math.floor(cy);
  loadSpectrum(x, y);
}

/* ----------------------------------------------------------- catalogs */
async function loadCatalogs() {
  const t = S.target, rad = (S.fov / 60) * 0.75 + 0.01;
  S.cats = {};
  for (const name of ["gaia", "allwise"]) {
    api(`/api/catalog/${name}?ra=${t.ra}&dec=${t.dec}&radius=${rad.toFixed(3)}`)
      .then((c) => { S.cats[name] = c; render(); })
      .catch((e) => console.warn(name, e));
  }
}
const astPending = new Set();
function loadAsteroids(mjd) {
  const key = mjd.toFixed(3);
  if (astPending.has(key)) return;
  astPending.add(key);
  const t = S.target, rad = (S.fov / 60) * 0.75;
  api(`/api/catalog/skybot?ra=${t.ra}&dec=${t.dec}&radius=${rad.toFixed(3)}&mjd=${key}`)
    .then((r) => { S.ast[key] = r; render(); })
    .catch(() => { S.ast[key] = { objects: [] }; });
}

/* ------------------------------------------------------------- aladin */
let aladin = null, aladinOverlay = null;
function initAladin() {
  if (embed || aladin) return;
  if (typeof window.A === "undefined") { window.addEventListener("aladin-ready", initAladin, { once: true }); return; }
  A.init.then(() => {
    aladin = A.aladin("#aladin", { survey: $("#hips").value, fov: 0.4, target: "269.4463 4.7682",
      showReticle: true, showZoomControl: true, showFullscreenControl: true, showLayersControl: true, showGotoControl: false, showFrame: false, showCooGrid: false });
    aladinOverlay = A.graphicOverlay({ color: "#ffb547", lineWidth: 2 });
    aladin.addOverlay(aladinOverlay);
    if (S.target) syncAladin();
  }).catch((e) => console.warn("Aladin failed", e));
}
function syncAladin() {
  if (!aladin || !S.target) return;
  const { ra, dec } = S.target, h = S.fov / 120, c = Math.cos((dec * Math.PI) / 180);
  aladin.gotoRaDec(ra, dec);
  aladin.setFoV(Math.max(0.15, (S.fov / 60) * 3));
  aladinOverlay.removeAll();
  aladinOverlay.add(A.polygon([[ra + h / c, dec - h], [ra - h / c, dec - h], [ra - h / c, dec + h], [ra + h / c, dec + h]]));
}

/* ---------------------------------------------------------------- flow */
function updateURL() {
  if (!S.target) return;
  const p = new URLSearchParams();
  if (S.target.name && S.target.query) p.set("q", S.target.query);
  p.set("ra", S.target.ra.toFixed(5)); p.set("dec", S.target.dec.toFixed(5)); p.set("fov", S.fov);
  if (S.rel) p.set("rel", S.rel);
  if (S.view !== "blink") p.set("view", S.view);
  if (S.mode !== "visit") p.set("mode", S.mode);
  if (S.det) p.set("det", S.det);
  if (S.mode === "channel") p.set("ch", S.ch);
  if (S.math !== "none") p.set("math", S.math);
  if (embed) p.set("embed", "1");
  history.replaceState(null, "", `${location.pathname}?${p}`);
}
function shareURL(forEmbed) {
  const u = new URL(location.href);
  u.pathname = u.pathname.replace(/embed$/, "");
  if (forEmbed) u.searchParams.set("embed", "1"); else u.searchParams.delete("embed");
  return u.toString();
}

async function lookupAndLoad(text) {
  text = text.trim();
  if (!text) return;
  $("#q").value = text;
  try {
    const r = await api(`/api/resolve?q=${encodeURIComponent(text)}`);
    S.target = { ...r, query: r.name ? text : null, name: r.name ? r.name.replace(/^NAME /, "") : null };
    startLoad();
  } catch (e) {
    toast(e.message);
  }
}

async function startLoad() {
  S.fov = +$("#fov").value;
  S.rel = $("#rel").value;
  S.F = S.wallF = S.planesF = null;
  S.sel = null; S.selFlags = null; S.ast = {}; S.cats = {};
  $("#welcome").classList.add("hidden");
  $("#views").classList.add("hidden");
  $("#progress").classList.remove("hidden");
  $("#progText").textContent = "Asking NASA which SPHEREx images cover this spot…";
  $("#progBar").style.width = "3%";
  updateURL();
  syncAladin();
  loadCatalogs();
  try {
    const t = S.target;
    let st = await api(`/api/load?ra=${t.ra.toFixed(6)}&dec=${t.dec.toFixed(6)}&fov=${S.fov}&rel=${encodeURIComponent(S.rel)}`);
    const myTarget = S.target;
    while (st.state !== "done") {
      if (st.state === "error") throw new Error(st.message);
      const pct = st.total ? Math.max(4, (100 * st.done) / st.total) : 3;
      $("#progBar").style.width = `${pct}%`;
      $("#progText").textContent = st.total
        ? `Downloading SPHEREx exposures from NASA IRSA: ${st.done} of ${st.total} (${st.elapsed}s). Next time this spot loads instantly.`
        : st.message;
      await new Promise((r) => setTimeout(r, 1000));
      if (S.target !== myTarget) return; // user started something else
      st = await api(`/api/job/${st.id}`);
    }
    S.job = st;
    S.sum = await api(`/api/job/${st.id}/summary`);
    $("#progress").classList.add("hidden");
    $("#views").classList.remove("hidden");
    fillVisitSelect();
    drawTimeline();
    await refreshFrames();
    if (st.failed) toast(`${st.failed} exposures couldn't be downloaded and were skipped.`);
  } catch (e) {
    $("#progText").textContent = `⚠ ${e.message}`;
    $("#progBar").style.width = "0";
  }
}

function fillVisitSelect() {
  $("#visitSel").innerHTML = S.sum.visits.map((v) => `<option value="${v.visit}">Visit ${v.visit + 1}: ${v.start}</option>`).join("");
  S.visit = Math.min(S.visit, S.sum.visits.length - 1);
  $("#visitSel").value = S.visit;
  updatePlaneLabel();
}
function updatePlaneLabel() {
  $("#planeVal").textContent = S.ch;
  const c = S.sum && S.sum.channels[S.ch - 1];
  $("#planeWave").textContent = c && c.wave ? `${c.wave[0].toFixed(2)}–${c.wave[1].toFixed(2)} µm · D${c.det} · ${c.n} exp` : "";
}

async function refreshFrames() {
  if (!S.job) return;
  const id = S.job.id;
  $("#mainWrap").classList.toggle("hidden", S.view === "wall" || S.view === "planes");
  $("#wall").classList.toggle("hidden", S.view !== "wall");
  $("#planesGrid").classList.toggle("hidden", S.view !== "planes");
  $("#blinkControls").classList.toggle("hidden", S.view !== "blink" && S.view !== "planes");
  $("#modeSeg").classList.toggle("hidden", S.view !== "blink");
  $("#detSeg").classList.toggle("hidden", S.view !== "blink" || S.mode === "channel");
  $("#planeBox").classList.toggle("hidden", !(S.view === "blink" && S.mode === "channel"));
  $("#visitBox").classList.toggle("hidden", S.view !== "planes");
  $("#player").classList.toggle("hidden", S.view === "planes");
  try {
    if (S.view === "blink") {
      const q = S.mode === "channel" ? `mode=channel&channel=${S.ch}` : `mode=${S.mode}&det=${S.det}`;
      S.F = decodeFrames(await api(`/api/job/${id}/frames?${q}`));
      if (!S.F.data.length) {
        toast(S.mode === "channel" ? `No exposures caught this spot in plane ${S.ch}. Try a neighbouring plane.` : "No frames for this choice.");
      }
      S.idx = 0;
      $("#scrub").max = Math.max(0, S.F.data.length - 1);
    } else if (S.view === "wall" || S.view === "color") {
      if (!S.wallF) S.wallF = decodeFrames(await api(`/api/job/${id}/frames?mode=visitdet`));
      S.idx = 0;
    } else if (S.view === "planes") {
      S.planesF = decodeFrames(await api(`/api/job/${id}/frames?mode=planes&visit=${S.visit}`));
      renderPlanes();
    }
    render();
  } catch (e) {
    toast(e.message);
  }
  updateURL();
}

function setView(v) {
  S.view = v;
  $$(".tabs button").forEach((b) => b.classList.toggle("on", b.dataset.view === v));
  if (S.job) refreshFrames();
}
function setMode(m) {
  S.mode = m;
  $$("#modeSeg button").forEach((b) => b.classList.toggle("on", b.dataset.mode === m));
  updatePlaneLabel();
  refreshFrames();
}

/* --------------------------------------------------------------- player */
let lastTick = 0;
function tick(ts) {
  requestAnimationFrame(tick);
  if (!S.playing || S.view === "planes") return;
  if (ts - lastTick < 1000 / S.fps) return;
  lastTick = ts;
  step(1);
}
function frameCount() {
  if (S.view === "blink") return S.F ? S.F.data.length : 0;
  if (S.wallF) return new Set(S.wallF.list.map((f) => f.visit)).size;
  return 0;
}
function step(d) {
  const n = frameCount();
  if (!n) return;
  if (S.math === "sum" && S.view === "blink") return;
  S.idx = (S.idx + d + n) % n;
  render();
}

/* ---------------------------------------------------------------- wiring */
function wire() {
  const chips = $("#chips");
  chips.innerHTML = `<span class="lbl">Challenge targets</span>` +
    TARGETS.map((t, i) => `<button data-t="${i}">${t.label}<small>${t.note}</small></button>`).join("");
  chips.addEventListener("click", (e) => {
    const b = e.target.closest("button[data-t]");
    if (b) lookupAndLoad(TARGETS[+b.dataset.t].q);
  });
  $("#searchForm").addEventListener("submit", (e) => { e.preventDefault(); lookupAndLoad($("#q").value); });
  $("#fov").addEventListener("input", () => ($("#fovVal").textContent = `${$("#fov").value}′`));
  $$(".tabs button").forEach((b) => b.addEventListener("click", () => setView(b.dataset.view)));
  $$("#modeSeg button").forEach((b) => b.addEventListener("click", () => setMode(b.dataset.mode)));
  $$("#detSeg button").forEach((b) => b.addEventListener("click", () => {
    S.det = +b.dataset.det;
    $$("#detSeg button").forEach((x) => x.classList.toggle("on", x === b));
    refreshFrames();
  }));
  $$("#mathSeg button").forEach((b) => b.addEventListener("click", () => {
    S.math = b.dataset.math;
    $$("#mathSeg button").forEach((x) => x.classList.toggle("on", x === b));
    render(); updateURL();
  }));
  let planeTimer;
  $("#plane").addEventListener("input", () => {
    S.ch = +$("#plane").value; updatePlaneLabel();
    clearTimeout(planeTimer); planeTimer = setTimeout(refreshFrames, 250);
  });
  $("#visitSel").addEventListener("change", () => { S.visit = +$("#visitSel").value; refreshFrames(); });
  $("#play").addEventListener("click", () => { S.playing = !S.playing; $("#play").textContent = S.playing ? "⏸" : "▶"; });
  $("#prev").addEventListener("click", () => step(-1));
  $("#next").addEventListener("click", () => step(1));
  $("#scrub").addEventListener("input", () => { S.idx = +$("#scrub").value; render(); });
  $("#fps").addEventListener("input", () => (S.fps = +$("#fps").value));
  for (const id of ["contrast", "bright"]) $(`#${id}`).addEventListener("input", () => { S[id] = +$(`#${id}`).value; render(); if (S.view === "planes") renderPlanes(); });
  $("#cmap").addEventListener("change", () => { S.cmap = $("#cmap").value; render(); if (S.view === "planes") renderPlanes(); });
  for (const id of ["ovGaia", "ovWise", "ovAst", "ovFlags", "ovCross"]) $(`#${id}`).addEventListener("change", render);
  $("#main").addEventListener("click", (e) => { const n = S.view === "blink" ? S.F && S.F.n : S.wallF && S.wallF.n; if (n) clickCanvas(e, n); });
  $("#copyLink").addEventListener("click", () => navigator.clipboard.writeText(shareURL(false)).then(() => toast("Link copied")));
  $("#copyEmbed").addEventListener("click", () => {
    const code = `<iframe src="${shareURL(true)}" width="640" height="760" style="border:0;border-radius:12px" title="SkyShift SPHEREx viewer" loading="lazy"></iframe>`;
    navigator.clipboard.writeText(code).then(() => toast("Embed code copied"));
  });
  $("#savePng").addEventListener("click", () => {
    const a = document.createElement("a");
    a.download = `skyshift_${(S.target.name || "sky").replace(/\W+/g, "_")}_${S.idx + 1}.png`;
    a.href = $("#main").toDataURL("image/png");
    a.click();
  });
  $("#hips").addEventListener("change", () => aladin && aladin.setImageSurvey($("#hips").value));
  $("#aladinGo").addEventListener("click", () => {
    if (!aladin) return;
    const [ra, dec] = aladin.getRaDec();
    S.target = { ra, dec, name: null, query: null };
    $("#q").value = `${ra.toFixed(5)} ${dec.toFixed(5)}`;
    startLoad();
  });
  document.addEventListener("keydown", (e) => {
    if (e.target.tagName === "INPUT" && e.target.type === "text") return;
    if (e.code === "Space") { e.preventDefault(); $("#play").click(); }
    if (e.code === "ArrowRight") step(1);
    if (e.code === "ArrowLeft") step(-1);
  });
  window.addEventListener("resize", () => S.sum && drawTimeline());
}

async function boot() {
  wire();
  requestAnimationFrame(tick);
  initAladin();
  api("/api/releases").then((r) => {
    $("#rel").innerHTML = `<option value="">Best available (${r.best.join(" + ").replace(/spherex_/g, "").toUpperCase()})</option>` +
      r.releases.map((x) => `<option value="${x.id}">${x.id.replace("spherex_", "").toUpperCase()} only</option>`).join("");
    if (params.get("rel")) $("#rel").value = params.get("rel");
  }).catch(() => {});

  // Restore state from the URL, e.g. ?ra=133.79&dec=-7.25&fov=8&mode=exposure&det=3
  if (params.get("fov")) { $("#fov").value = params.get("fov"); $("#fovVal").textContent = `${params.get("fov")}′`; }
  if (params.get("rel")) S.rel = params.get("rel");
  if (params.get("mode")) setModeSilently(params.get("mode"));
  if (params.get("det")) { S.det = +params.get("det"); $$("#detSeg button").forEach((x) => x.classList.toggle("on", +x.dataset.det === S.det)); }
  if (params.get("ch")) { S.ch = +params.get("ch"); $("#plane").value = S.ch; }
  if (params.get("math")) { S.math = params.get("math"); $$("#mathSeg button").forEach((x) => x.classList.toggle("on", x.dataset.math === S.math)); }
  if (params.get("view")) { S.view = params.get("view"); $$(".tabs button").forEach((b) => b.classList.toggle("on", b.dataset.view === S.view)); }
  const ra = parseFloat(params.get("ra")), dec = parseFloat(params.get("dec"));
  if (Number.isFinite(ra) && Number.isFinite(dec)) {
    S.target = { ra, dec, name: params.get("q"), query: params.get("q") };
    $("#q").value = params.get("q") || `${ra} ${dec}`;
    startLoad();
  } else if (params.get("q")) {
    lookupAndLoad(params.get("q"));
  }
}
function setModeSilently(m) {
  S.mode = m;
  $$("#modeSeg button").forEach((b) => b.classList.toggle("on", b.dataset.mode === m));
}
boot();
