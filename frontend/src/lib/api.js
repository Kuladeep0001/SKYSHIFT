/* Every call to the backend goes through this file (see API_DOCUMENTATION.md).
 *
 * Mock mode: open the site with ?mock=1 (or set VITE_MOCK=1) and it reads saved responses from
 * /public/mock instead of the real backend. UI developers can build without the Python server.
 */
const MOCK = new URLSearchParams(location.search).get("mock") === "1" || import.meta.env.VITE_MOCK === "1";

async function request(path, opts = {}) {
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
  verify: (candidates) => (MOCK ? mock("verification") : post("/api/verification/gaia", { candidates })),
  catalog: (name, ra, dec, radius, mjd = 0) =>
    MOCK ? mock(`catalog_${name}`).catch(() => ({ stars: [], objects: [] }))
      : request(`/api/catalog/${name}?ra=${ra}&dec=${dec}&radius=${radius.toFixed(3)}${mjd ? `&mjd=${mjd.toFixed(3)}` : ""}`),
};

/* Start a query and wait until the images are ready, reporting progress. */
export async function loadImages({ ra, dec, fov, release }, onProgress, isCancelled) {
  let st = await api.queryImages({ ra, dec, fov, release: release ? [release] : null });
  while (st.status === "pending") {
    onProgress && onProgress(st);
    await new Promise((r) => setTimeout(r, 1000));
    if (isCancelled && isCancelled()) return null;
    st = await api.imageStatus(st.query_id);
  }
  if (st.status === "error") throw new Error(st.message || "Loading failed");
  return st;
}
