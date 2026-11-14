/* Drawing helpers: colour maps, brightness stretch, painting frames, sky -> screen positions. */
import { PIX } from "./frames.js";

function lutFrom(stops) {
  const lut = new Uint8ClampedArray(256 * 3);
  for (let i = 0; i < 256; i++) {
    const t = (i / 255) * (stops.length - 1), k = Math.min(stops.length - 2, Math.floor(t)), f = t - k;
    for (let c = 0; c < 3; c++) lut[i * 3 + c] = stops[k][c] * (1 - f) + stops[k + 1][c] * f;
  }
  return lut;
}
export const LUTS = {
  gray: lutFrom([[0, 0, 0], [255, 255, 255]]),
  invert: lutFrom([[255, 255, 255], [0, 0, 0]]),
  inferno: lutFrom([[0, 0, 4], [40, 11, 84], [101, 21, 110], [159, 42, 99], [212, 72, 66], [245, 125, 21], [250, 193, 39], [252, 255, 164]]),
  // blue = was brighter before, orange = brighter now
  diverge: lutFrom([[60, 140, 255], [10, 20, 45], [255, 170, 60]]),
};
export const DET_COLORS = ["#7a8cff", "#55c6ff", "#53d8c4", "#b6e35a", "#ffb547", "#ff6b6b"];
export const VISIT_COLORS = ["#53d8c4", "#ffb547", "#ff6b8b", "#5ab0ff", "#c38bff", "#b6e35a"];

/* asinh stretch: shows faint and bright things at the same time */
export function makeScaler(lo, hi, contrast = 0.55, bright = 0.5) {
  const beta = Math.pow(10, contrast * 3) - 0.999;
  const hiEff = lo + (hi - lo) * Math.pow(10, (0.5 - bright) * 1.6);
  const span = hiEff - lo || 1, norm = Math.asinh(beta) || 1;
  return (v) => {
    let t = (v - lo) / span;
    t = t <= 0 ? 0 : t >= 1 ? 1 : Math.asinh(t * beta) / norm;
    return (t * 255) | 0;
  };
}
export function makeDivScaler(L, contrast = 0.55, bright = 0.5) {
  const beta = Math.pow(10, contrast * 3) - 0.999, norm = Math.asinh(beta) || 1;
  const Le = L * Math.pow(10, (0.5 - bright) * 1.6) || 1;
  return (v) => {
    let t = Math.max(-1, Math.min(1, v / Le));
    t = (Math.sign(t) * Math.asinh(Math.abs(t) * beta)) / norm;
    return ((t + 1) * 127.5) | 0;
  };
}

const off = document.createElement("canvas");
/* Paint a frame (FITS order: row 0 = south) onto a canvas with north up. */
export function paint(canvas, arr, n, scaler, lut, flags) {
  off.width = off.height = n;
  const octx = off.getContext("2d");
  const img = octx.createImageData(n, n);
  const d = img.data;
  for (let r = 0; r < n; r++) {
    const src = (n - 1 - r) * n;
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

export function paintRGB(canvas, chans, n) {
  off.width = off.height = n;
  const octx = off.getContext("2d"), img = octx.createImageData(n, n), d = img.data;
  for (let r = 0; r < n; r++) {
    const src = (n - 1 - r) * n;
    for (let c = 0; c < n; c++) {
      const o = (r * n + c) * 4;
      for (let k = 0; k < 3; k++) d[o + k] = chans[k].sc(chans[k].arr[src + c]);
      d[o + 3] = 255;
    }
  }
  octx.putImageData(img, 0, 0);
  const ctx = canvas.getContext("2d");
  ctx.imageSmoothingEnabled = false;
  ctx.drawImage(off, 0, 0, canvas.width, canvas.height);
}

/* Sky position -> canvas pixel, for our north-up, east-left grid centred on (ra0, dec0). */
export function skyToCanvas(ra, dec, ra0, dec0, n, W) {
  const r = Math.PI / 180, a0 = ra0 * r, d0 = dec0 * r, a = ra * r, d = dec * r;
  const cosc = Math.sin(d0) * Math.sin(d) + Math.cos(d0) * Math.cos(d) * Math.cos(a - a0);
  const xi = ((Math.cos(d) * Math.sin(a - a0)) / cosc / r) * 3600;
  const eta = ((Math.cos(d0) * Math.sin(d) - Math.sin(d0) * Math.cos(d) * Math.cos(a - a0)) / cosc / r) * 3600;
  const x0 = (n - 1) / 2 - xi / PIX, y0 = (n - 1) / 2 + eta / PIX;
  const s = W / n;
  return [(x0 + 0.5) * s, (n - 1 - y0 + 0.5) * s];
}
/* Grid pixel (x right, y up) -> canvas position (centre of that pixel). */
export function pixToCanvas(x, y, n, W) {
  const s = W / n;
  return [(x + 0.5) * s, (n - 1 - y + 0.5) * s];
}

export function arrow(ctx, x0, y0, x1, y1, head = 9) {
  const a = Math.atan2(y1 - y0, x1 - x0);
  ctx.beginPath();
  ctx.moveTo(x0, y0); ctx.lineTo(x1, y1);
  ctx.lineTo(x1 - head * Math.cos(a - 0.45), y1 - head * Math.sin(a - 0.45));
  ctx.moveTo(x1, y1);
  ctx.lineTo(x1 - head * Math.cos(a + 0.45), y1 - head * Math.sin(a + 0.45));
  ctx.stroke();
}
