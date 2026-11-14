/* Time machine: the same patch of sky from 1950 to today (glass plates -> 2MASS -> WISE -> SPHEREx).
 * The predicted path of the target (from its known motion) is drawn so anyone can follow it.  Owner: UI 2.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { api, loadImages } from "../lib/api.js";
import { percentile } from "../lib/frames.js";
import { LUTS, makeScaler, paint } from "../lib/render.js";

const W = 640;
const FIRST_YEAR = 1950;

function b64f32(b64, count, nn) {
  const bin = atob(b64), u8 = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
  return Array.from({ length: count }, (_, k) => new Float32Array(u8.buffer, k * nn * 4, nn));
}

/* Where a star with proper motion (mas/yr) is in a given year, starting from its 2026 position. */
function posAt(t, year) {
  const dt = year - 2026;
  const dec = t.dec + ((t.pmdec || 0) * dt) / 3.6e6;
  return [t.ra + ((t.pmra || 0) * dt) / 3.6e6 / Math.cos((t.dec * Math.PI) / 180), dec];
}

/* The area to show: wide enough for the whole 1950 -> today journey. */
export function timeMachineArea(target, fov) {
  const pm = Math.hypot(target.pmra || 0, target.pmdec || 0) / 1000; // arcsec/yr
  const path = (pm * (2026 - FIRST_YEAR)) / 60;                      // arcmin
  const tfov = Math.min(20, Math.max(fov, 8, path + 4));
  if (path + 2 > 20) return { ra: target.ra, dec: target.dec, fov: 20, path };
  const [ra0, dec0] = posAt(target, FIRST_YEAR);
  return { ra: (ra0 + target.ra) / 2, dec: (dec0 + target.dec) / 2, fov: Math.round(tfov * 10) / 10, path };
}

export default function TimeMachine({ qid, target, fov, disp, onTask }) {
  const area = useMemo(() => timeMachineArea(target, fov), [target, fov]);
  const [data, setData] = useState(null);
  const [err, setErr] = useState("");
  const [idx, setIdx] = useState(0);
  const [playing, setPlaying] = useState(true);
  const [fullQid, setFullQid] = useState(null);   // a SPHEREx job covering the whole time-machine area
  const [loadingFull, setLoadingFull] = useState(false);
  const cancelRef = useRef(false);
  const canvas = useRef(null);
  const useQid = fullQid || qid;

  useEffect(() => {
    let alive = true;
    setData(null); setErr("");
    api.history(useQid, area.ra, area.dec, area.fov)
      .then((r) => { if (!alive) return; const nn = r.n * r.n; setData({ ...r, imgs: b64f32(r.data, r.count, nn) }); setIdx(0); })
      .catch((e) => alive && setErr(e.message));
    return () => { alive = false; };
  }, [useQid, area.ra, area.dec, area.fov]);

  useEffect(() => {
    if (!playing || !data || !data.count) return;
    const h = setInterval(() => setIdx((i) => (i + 1) % data.count), 1300);
    return () => clearInterval(h);
  }, [playing, data]);

  // each survey gets its own brightness scale; a dark background hides the grain of old glass plates
  const lims = useMemo(() => (data ? data.imgs.map((a, k) => percentile([a], data.frames[k].survey.startsWith("poss") ? [35, 99.85] : [10, 99.8])) : []), [data]);

  useEffect(() => {
    if (!data || !data.count || !canvas.current) return;
    const k = Math.min(idx, data.count - 1), n = data.n, f = data.frames[k];
    paint(canvas.current, data.imgs[k], n, makeScaler(lims[k][0], lims[k][1], disp.contrast, disp.bright), (LUTS[disp.cmap] || LUTS.gray));
    const ctx = canvas.current.getContext("2d"), s = W / n, scale = data.scale_arcsec;
    const toXY = (ra, dec) => {
      const cosd = Math.cos((area.dec * Math.PI) / 180);
      const xi = ((ra - area.ra) * cosd * 3600) / scale, eta = ((dec - area.dec) * 3600) / scale;
      return [((n - 1) / 2 - xi + 0.5) * s, (n - 1 - ((n - 1) / 2 + eta) + 0.5) * s];
    };
    const pm = Math.hypot(target.pmra || 0, target.pmdec || 0);
    if (pm > 50) {
      // the predicted path, with a dot for every survey date
      ctx.strokeStyle = "rgba(83,216,196,.55)"; ctx.lineWidth = 2; ctx.setLineDash([6, 5]);
      const [x0, y0] = toXY(...posAt(target, FIRST_YEAR)), [x1, y1] = toXY(target.ra, target.dec);
      ctx.beginPath(); ctx.moveTo(x0, y0); ctx.lineTo(x1, y1); ctx.stroke(); ctx.setLineDash([]);
      data.frames.forEach((g, j) => {
        const [x, y] = toXY(...posAt(target, g.year));
        ctx.strokeStyle = j === k ? "#ffa31a" : "rgba(83,216,196,.6)"; ctx.lineWidth = j === k ? 3 : 1.5;
        ctx.beginPath(); ctx.arc(x, y, j === k ? 16 : 6, 0, 2 * Math.PI); ctx.stroke();
        if (j === k) { ctx.fillStyle = "#ffa31a"; ctx.font = "600 14px Inter, sans-serif"; ctx.fillText(`${target.name || "target"} in ${Math.floor(g.year)}`, x + 20, y + 5); }
      });
    } else {
      const [x, y] = toXY(target.ra, target.dec);
      ctx.strokeStyle = "#53d8c4"; ctx.lineWidth = 2; ctx.beginPath(); ctx.arc(x, y, 14, 0, 2 * Math.PI); ctx.stroke();
    }
    if (f.coverage < 0.97) {
      ctx.fillStyle = "rgba(6,11,22,.75)"; ctx.fillRect(8, W - 34, 330, 26);
      ctx.fillStyle = "#d4d4dc"; ctx.font = "12px Inter, sans-serif";
      ctx.fillText(`SPHEREx covers ${Math.round(f.coverage * 100)}% of this area (dark = not loaded yet)`, 14, W - 16);
    }
  }, [data, idx, lims, disp.contrast, disp.bright, disp.cmap, target, area]);

  async function loadFull() {
    cancelRef.current = false;
    setLoadingFull(true);
    const started = Date.now();
    let qidLoading = null;
    const task = (p) => onTask && onTask({ id: "tm", label: "Loading SPHEREx for the whole time-machine area", detail: p?.message,
      done: p?.progress?.done || 0, total: p?.progress?.total || 0, startedAt: started,
      onCancel: () => { cancelRef.current = true; if (qidLoading) api.cancel(qidLoading).catch(() => {}); onTask(null); setLoadingFull(false); } });
    task();
    try {
      const st = await loadImages({ ra: area.ra, dec: area.dec, fov: area.fov }, (p) => { qidLoading = p.query_id; task(p); }, () => cancelRef.current);
      if (st) setFullQid(st.query_id);
    } catch (e) { setErr(e.message); } finally { onTask && onTask(null); setLoadingFull(false); }
  }

  if (err) return <p className="err">{err}</p>;
  if (!data) return <div className="progress"><div className="bar"><i style={{ width: "40%" }} className="indet" /></div><p>Fetching the same patch of sky from 1950, 1991, 2000, 2010 and today… (about 30 s the first time)</p></div>;
  if (!data.count) return <p className="hint">No older images found here. {data.notes.join(" · ")}</p>;
  const f = data.frames[Math.min(idx, data.count - 1)];
  const years = Math.floor(f.year), span = Math.floor(data.frames[data.count - 1].year - data.frames[0].year);
  const minSpherex = Math.min(...data.frames.filter((g) => g.survey === "spherex").map((g) => g.coverage));
  return (
    <div className="timeMachine">
      <div className="viewer">
        <div className="canvasWrap">
          <canvas ref={canvas} width={W} height={W} aria-label={`Sky in ${years}`} />
          <div className="stamp"><b className="year">{years}</b><span>{f.label} · {f.band}</span><span>{f.date}</span></div>
          <div className="scaleNote">{area.fov}′ wide</div>
        </div>
      </div>
      <div className="player">
        <button className="primary play" onClick={() => setPlaying(!playing)}>{playing ? "Pause" : "Play"}</button>
        <input type="range" min="0" max={data.count - 1} value={idx} onChange={(e) => { setPlaying(false); setIdx(+e.target.value); }} aria-label="Year" />
        <span className="mono frameLbl">{idx + 1}/{data.count}</span>
      </div>
      <div className="yearStrip">
        {data.frames.map((g, j) => (
          <button key={j} className={j === idx ? "on" : ""} onClick={() => { setPlaying(false); setIdx(j); }}>
            <b>{Math.floor(g.year)}</b><small>{g.label.replace("Palomar Sky Survey", "Palomar")}</small>
          </button>
        ))}
      </div>
      <p className="hint">
        {span} years of the same patch of sky. The old photos are <b>glass plates</b> in visible light; 2MASS, WISE and SPHEREx see <b>infrared</b>, so stars look a bit different.
        {area.path > 0.3 && <> The dashed line is {target.name || "the target"}'s predicted path: it travelled <b>{area.path.toFixed(1)}′</b> since {FIRST_YEAR} ({Math.round((area.path / 31) * 100)}% of the full Moon's width).</>}
      </p>
      {minSpherex < 0.95 && !fullQid && (
        <button onClick={loadFull} disabled={loadingFull}>{loadingFull ? "Loading SPHEREx for the whole area…" : `Fill in SPHEREx for the whole ${area.fov}′ area (bigger download)`}</button>
      )}
    </div>
  );
}
