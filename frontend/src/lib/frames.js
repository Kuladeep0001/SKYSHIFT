/* Frame data helpers: decode the API's base64 pixels and do frame maths in the browser. */

export const PIX = 6.15; // arcseconds per SPHEREx pixel

function b64ToBytes(b64) {
  const bin = atob(b64);
  const u8 = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
  return u8;
}

/* API frames response -> { n, list, data: Float32Array[], flags: Uint8Array[], mode } */
export function decodeFrames(res) {
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

export function percentile(arrs, ps, absval = false) {
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

export function meanFrames(arrs) {
  const nn = arrs[0].length, out = new Float32Array(nn), cnt = new Uint16Array(nn);
  for (const a of arrs) for (let i = 0; i < nn; i++) if (Number.isFinite(a[i])) { out[i] += a[i]; cnt[i]++; }
  for (let i = 0; i < nn; i++) out[i] = cnt[i] ? out[i] / cnt[i] : NaN;
  return out;
}

export function diffFrame(a, b) {
  const out = new Float32Array(a.length);
  for (let i = 0; i < a.length; i++) out[i] = a[i] - b[i];
  return out;
}

export const mjdToYear = (mjd) => 2000 + (mjd - 51544.5) / 365.25;
const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
export const monthYear = (iso) => { const [y, m] = iso.split("-"); return `${MONTHS[+m - 1]} ${y}`; };
export const fmtWave = (w) => (w == null ? "—" : `${w.toFixed(3)} µm`);
export const fmtRA = (ra) => { const h = ra / 15, hh = Math.floor(h), m = (h - hh) * 60, mm = Math.floor(m); return `${String(hh).padStart(2, "0")}h${String(mm).padStart(2, "0")}m${((m - mm) * 60).toFixed(1).padStart(4, "0")}s`; };
export const fmtDec = (d) => { const s = d < 0 ? "−" : "+"; d = Math.abs(d); const dd = Math.floor(d), m = (d - dd) * 60, mm = Math.floor(m); return `${s}${String(dd).padStart(2, "0")}°${String(mm).padStart(2, "0")}′${((m - mm) * 60).toFixed(0).padStart(2, "0")}″`; };

/* Keep only the big twice-a-year visits (drop small side visits with a handful of snapshots). */
export function mainVisitsOnly(F) {
  if (!F || F.mode !== "visit" || F.list.length < 3) return F;
  const mx = Math.max(...F.list.map((f) => f.n_exp || 1));
  const keep = F.list.map((f, k) => ((f.n_exp || 1) >= Math.max(3, 0.25 * mx) ? k : -1)).filter((k) => k >= 0);
  if (keep.length < 2) return F;
  return { ...F, list: keep.map((k) => F.list[k]), data: keep.map((k) => F.data[k]), flags: keep.map((k) => F.flags[k]) };
}
