/* Every call to the backend goes through this file (see API_DOCUMENTATION.md).
 *
 * Mock mode: open the site with ?mock=1 (or set VITE_MOCK=1) and it reads saved responses from
 * /public/mock instead of the real backend. UI developers can build without the Python server.
 */
import { trackRequest } from "./tasks.js";

const MOCK = new URLSearchParams(location.search).get("mock") === "1" || import.meta.env.VITE_MOCK === "1";

/* Every backend download gets its own bar (and Cancel button) in the task bar: see lib/tasks.js. */
function request(path, opts = {}) {
  return trackRequest(path, opts, (o) => fetchJSON(path, o));
}

async function fetchJSON(path, opts) {
  const r = await fetch(path, opts);
  if (!r.ok) {
    let msg = r.statusText;
    try {
      const j = await r.json();
      msg = (j.detail && (j.detail.message || j.detail)) || msg;
    } catch (_) { /* not JSON */ }
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return r.json();
}
const post = (path, body) => request(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

async function mock(name, fallback) {
  try { return await request(`/mock/${name}.json`); } catch (e) { if (fallback) return request(`/mock/${fallback}.json`); throw e; }
}

export const api = {
  mock: MOCK,
  releases: () => (MOCK ? mock("releases") : request("/api/releases")),
  resolve: (q) => (MOCK ? mock("resolve") : request(`/api/resolve?q=${encodeURIComponent(q)}`)),
  // two coordinate boxes -> RA/Dec, read forgivingly (frame: icrs | earth | galactic). A box that can't be read
  // throws an Error with .field = "a" | "b" and a plain message. No task-bar entry: it is instant and used while typing.
  resolvePosition: async (a, b, frame = "icrs") => {
    if (MOCK) return { ra: parseFloat(a) || 0, dec: parseFloat(b) || 0, read: `RA ${a}, Dec ${b}`, read_a: a, read_b: b, label: null, split: null };
    const r = await fetch(`/api/resolve/position?a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}&frame=${frame}`);
    const j = await r.json().catch(() => ({}));
    if (!r.ok) { const e = new Error((j.detail && j.detail.message) || r.statusText); e.field = j.detail && j.detail.field; throw e; }
    return j;
  },
  queryImages: (body) => (MOCK ? mock("images_query") : post("/api/images/query", body)),
  imageStatus: (id) => (MOCK ? mock("images_query") : request(`/api/images/${id}`)),
  metadata: (id) => (MOCK ? mock("metadata") : request(`/api/metadata/${id}`)),
  frames: (id, { mode = "visit", det = 0, channel = 0, visit = -1 } = {}) =>
    MOCK
      ? mock(`frames_${mode}_det${det}_ch${channel}_v${visit}`, "frames_visit_det0_ch0_v-1")
      : request(`/api/images/${id}/frames?mode=${mode}&det=${det}&channel=${channel}&visit=${visit}`),
  spectrum: (id, x, y) => (MOCK ? mock("spectrum") : request(`/api/images/${id}/spectrum?x=${x}&y=${y}&r=1`)),
  compare: (body) => (MOCK ? mock("compare") : post("/api/images/compare", body)),
  detect: (body) => (MOCK ? mock("detections") : post("/api/detections/run", body)),
  history: (id, ra, dec, fov) => (MOCK ? mock("history") : request(`/api/images/${id}/history?ra=${ra.toFixed(5)}&dec=${dec.toFixed(5)}&fov=${fov}`)),
  asteroids: (id) => (MOCK ? mock("asteroids") : request(`/api/images/${id}/asteroids`)),
  finds: (sort = "top") => (MOCK ? Promise.resolve({ total: 0, finds: [] }) : request(`/api/finds?sort=${sort}&voter=${voterId()}`)),
  report: (find) => post("/api/finds", { ...find, voter: voterId() }),
  vote: (id, value) => post(`/api/finds/${id}/vote`, { voter: voterId(), value }),
  ask: (question, context) => (MOCK ? Promise.resolve({ answer: "Ask works with the backend running.", source: "built-in" }) : post("/api/ask", { question, context })),
  validation: () => (MOCK ? mock("validation") : request("/api/validation")),
  askStatus: () => (MOCK ? Promise.resolve({ llm: false }) : request("/api/ask/status")),
  cube: (id, visit = -1) => (MOCK ? mock("cube") : request(`/api/images/${id}/cube?visit=${visit}`)),
  features: (spectrum) => (MOCK ? Promise.resolve({ features: [] }) : post("/api/detections/features", { spectrum })),
  checkNow: (id) => (MOCK ? Promise.resolve({ result: { checked: true, changed: false }, freshness: {} }) : post(`/api/images/${id}/check`, {})),
  cancel: (id) => (MOCK ? Promise.resolve({ cancelled: true }) : post(`/api/images/${id}/cancel`, {})),
  updates: () => (MOCK ? Promise.resolve({ log: [] }) : request("/api/updates")),
  verify: (candidates) => (MOCK ? mock("verification") : post("/api/verification/gaia", { candidates })),
  // Gaia + 2MASS + AllWISE + SIMBAD epoch-aware cross-match (verification branch)
  crossCheck: (candidates, radius = 6) => (MOCK ? mock("crosscheck")
    : post("/api/verification/", { candidates, catalogues: ["gaia", "2mass", "allwise", "simbad"], search_radius_arcsec: radius })),
  catalog: (name, ra, dec, radius, mjd = 0) =>
    MOCK ? mock(`catalog_${name}`).catch(() => ({ stars: [], objects: [] }))
      : request(`/api/catalog/${name}?ra=${ra}&dec=${dec}&radius=${radius.toFixed(3)}${mjd ? `&mjd=${mjd.toFixed(3)}` : ""}`),
};

/* A random id for this browser, so each person gets one vote per find (no accounts, nothing personal). */
export function voterId() {
  try {
    let v = localStorage.getItem("skyshift-voter");
    if (!v) { v = (crypto.randomUUID ? crypto.randomUUID() : String(Math.random()).slice(2) + Date.now()).replace(/-/g, ""); localStorage.setItem("skyshift-voter", v); }
    return v;
  } catch (_) { return "anon" + String(Math.random()).slice(2, 12); }
}

/* Start a query and wait until the images are ready, reporting progress. */
export async function loadImages({ ra, dec, fov, release }, onProgress, isCancelled) {
  let st = await api.queryImages({ ra, dec, fov, release: release ? [release] : null });
  while (st.status === "pending") {
    onProgress && onProgress(st);
    await new Promise((r) => setTimeout(r, 1000));
    if (isCancelled && isCancelled()) return null;
    st = await api.imageStatus(st.query_id);
  }
  if (st.status === "cancelled") return null;
  if (st.status === "error") throw new Error(st.message || "Loading failed");
  return st;
}

/* The technical report PDF (tracked in the task bar, with Cancel). Returns { blob, name }. */
export function fetchReport(id, params = {}) {
  const q = new URLSearchParams(Object.entries(params).filter(([, v]) => v != null && v !== "").map(([k, v]) => [k, String(v)]));
  const path = `/api/images/${id}/report.pdf?${q}`;
  return trackRequest(path, {}, async (o) => {
    const r = await fetch(path, o);
    if (!r.ok) {
      let msg = r.statusText;
      try { const j = await r.json(); msg = (j.detail && (j.detail.message || j.detail)) || msg; } catch (_) { /* not JSON */ }
      throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
    }
    const name = (r.headers.get("X-Report-Number") || "SkyShift-report") + ".pdf";
    return { blob: await r.blob(), name };
  });
}

export const objectDetails = (ra, dec, mjd, name) =>
  api.mock ? request("/mock/object.json")
    : request(`/api/object?ra=${ra}&dec=${dec}${mjd ? `&mjd=${mjd.toFixed(2)}` : ""}${name ? `&name=${encodeURIComponent(name)}` : ""}`);
