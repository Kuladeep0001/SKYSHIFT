/* Asteroid hunter: known asteroids and comets that crossed this picture while SPHEREx was looking.
 * Shows each snapshot where one should be, with a marker, so people can try to spot it.  Owner: UI 2.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../lib/api.js";
import { decodeFrames, percentile } from "../lib/frames.js";
import { LUTS, makeScaler, paint, pixToCanvas } from "../lib/render.js";

const W = 640;

export default function AsteroidHunter({ qid, disp, onReport }) {
  const [ast, setAst] = useState(null);
  const [frames, setFrames] = useState(null);
  const [pick, setPick] = useState(null);   // asteroid name
  const [k, setK] = useState(0);
  const [playing, setPlaying] = useState(true);
  const [err, setErr] = useState("");
  const canvas = useRef(null);

  useEffect(() => {
    let alive = true;
    setAst(null); setFrames(null); setErr("");
    Promise.all([api.asteroids(qid), api.frames(qid, { mode: "exposure", det: 0 })])
      .then(([a, f]) => { if (!alive) return; setAst(a); setFrames(decodeFrames(f)); if (a.objects.length) setPick(a.objects[0].name); })
      .catch((e) => alive && setErr(e.message));
    return () => { alive = false; };
  }, [qid]);

  const obj = ast && ast.objects.find((o) => o.name === pick);
  const seq = useMemo(() => {
    if (!obj || !frames) return [];
    const byI = new Map(frames.list.map((f, j) => [frames.list[j].members?.[0] ?? j, j]));
    return obj.appearances.map((a) => ({ ...a, j: byI.get(a.i) })).filter((a) => a.j !== undefined);
  }, [obj, frames]);

  useEffect(() => { setK(0); }, [pick]);
  useEffect(() => {
    if (!playing || seq.length < 2) return;
    const h = setInterval(() => setK((x) => (x + 1) % seq.length), 900);
    return () => clearInterval(h);
  }, [playing, seq.length]);

  useEffect(() => {
    if (!seq.length || !canvas.current) return;
    const a = seq[Math.min(k, seq.length - 1)], img = frames.data[a.j];
    const [lo, hi] = percentile([img], [3, 99.7]);
    paint(canvas.current, img, frames.n, makeScaler(lo, hi, disp.contrast, disp.bright), (LUTS[disp.cmap] || LUTS.gray));
    const ctx = canvas.current.getContext("2d");
    // the whole predicted track (faint) and where it is now (bright)
    ctx.strokeStyle = "rgba(255,107,139,.45)"; ctx.lineWidth = 1.5; ctx.beginPath();
    seq.forEach((p, j) => { const [x, y] = pixToCanvas(p.x, p.y, frames.n, W); j ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
    ctx.stroke();
    const [x, y] = pixToCanvas(a.x, a.y, frames.n, W);
    ctx.strokeStyle = "#ff6b8b"; ctx.lineWidth = 2.5;
    ctx.strokeRect(x - 16, y - 16, 32, 32);
    ctx.fillStyle = "#ff6b8b"; ctx.font = "600 14px Inter, sans-serif";
    const label = `☄ ${obj.name}`, tw = ctx.measureText(label).width;
    ctx.fillText(label, x + 20 + tw > W - 6 ? x - 20 - tw : x + 20, y - 8);  // keep the label inside the picture
  }, [seq, k, frames, disp.contrast, disp.bright, disp.cmap]);

  if (err) return <p className="err">⚠ {err}</p>;
  if (!ast) return <div className="progress"><div className="bar"><i className="indet" style={{ width: "30%" }} /></div><p>Asking the IMCCE asteroid service which asteroids crossed this spot on each day SPHEREx looked… (up to a minute the first time)</p></div>;
  if (!ast.objects.length) return (
    <p className="hint">No known asteroids crossed this picture during SPHEREx's {ast.days_checked} observing days. Asteroids travel near the <b>ecliptic</b> (the Sun's path across the sky). Try a spot close to it, like RW Aurigae.</p>
  );
  const a = seq[Math.min(k, seq.length - 1)];
  return (
    <div className="asteroids">
      <div className="cubeMain">
        <div>
          {seq.length ? (
            <div className="canvasWrap">
              <canvas ref={canvas} width={W} height={W} aria-label={`Snapshot with asteroid ${obj.name}`} />
              <div className="stamp"><b>{a.date.slice(0, 16)} UT</b><span>snapshot {k + 1} of {seq.length} where {obj.name} should be · detector D{a.det}</span></div>
            </div>
          ) : <p className="hint">This asteroid falls in snapshots that aren't loaded.</p>}
          <div className="player">
            <button className="primary play" onClick={() => setPlaying(!playing)}>{playing ? "⏸ Pause" : "▶ Play"}</button>
            <input type="range" min="0" max={Math.max(0, seq.length - 1)} value={k} onChange={(e) => { setPlaying(false); setK(+e.target.value); }} aria-label="Snapshot" />
          </div>
        </div>
        <div className="astList">
          <p className="small muted">{ast.objects.length} known asteroids/comets crossed this spot while SPHEREx was looking (IMCCE SkyBoT).</p>
          <ul>
            {ast.objects.map((o) => (
              <li key={o.name} className={o.name === pick ? "on" : ""} onClick={() => setPick(o.name)}>
                <b>{o.number && o.number !== "-" ? `(${o.number}) ` : ""}{o.name}</b>
                <span>{o.class.replace("MB>", "main belt, ")} · mag {o.mag} · {o.rate_arcsec_h}″/hour · in {o.appearances.length} snapshot{o.appearances.length > 1 ? "s" : ""}</span>
                <em className={o.visible_guess ? "ok" : ""}>{o.visible_guess ? "bright enough to spot" : "probably too faint for one snapshot"}</em>
              </li>
            ))}
          </ul>
        </div>
      </div>
      <p className="hint">Asteroids move fast: hours, not years. The pink box shows where <b>{obj?.name}</b> should be in each snapshot, and the line is its path. See a dot moving along it? That's the asteroid! Most asteroids are fainter than magnitude 17 and too dim for one SPHEREx snapshot.
        {onReport && <> Found a moving dot that <b>isn't</b> on the list? <button className="linkBtn" onClick={() => onReport(a)}>Report it on the Discovery board</button>.</>}</p>
    </div>
  );
}
