/* Task bar: one bar for every download or job SkyShift is running, each with its own Cancel button.
 *  - tasks (prop): the big jobs Explorer knows about (main SPHEREx download, time-machine area, NASA updates),
 *    [{ id, label, detail, done, total, startedAt, onCancel, kind }]
 *  - everything else comes from lib/tasks.js: every backend request is tracked automatically
 *    (spectrum, spectral cube, old sky photos, asteroids, catalogue checks, details card, assistant…)
 *    plus jobs in the browser such as making a GIF.
 * Same-kind requests running together are grouped into one bar ("×3"). Owner: UI 2.
 */
import { useEffect, useState } from "react";
import { useTasks } from "../lib/tasks.js";

const MAX_SHOWN = 5;

function eta(t) {
  if (!t.total || !t.done || !t.startedAt) return "";
  const secs = ((Date.now() - t.startedAt) / 1000 / t.done) * (t.total - t.done);
  if (!Number.isFinite(secs) || secs < 2) return "almost done";
  return secs > 90 ? `about ${Math.round(secs / 60)} min left` : `about ${Math.round(secs)} s left`;
}

const elapsed = (t) => {
  const s = Math.round(((t.endedAt || Date.now()) - t.startedAt) / 1000);
  return s >= 60 ? `${Math.floor(s / 60)} min ${s % 60} s` : `${s} s`;
};

/* Group running requests of the same kind into one row. */
function grouped(list) {
  const out = [], byKey = new Map();
  for (const t of list) {
    const key = t.status === "running" ? t.group : t.id;
    if (byKey.has(key)) {
      const g = byKey.get(key);
      g.count += 1; g.members.push(t);
      g.startedAt = Math.min(g.startedAt, t.startedAt);
    } else {
      const g = { ...t, count: 1, members: [t] };
      byKey.set(key, g); out.push(g);
    }
  }
  return out;
}

function Row({ t }) {
  const running = t.status === "running" || !t.status;
  const pct = t.status === "done" ? 100 : t.total ? Math.max(3, Math.round((100 * t.done) / t.total)) : null;
  const icon = t.status === "done" ? "✅" : t.status === "failed" ? "⚠️" : t.status === "cancelled" ? "⏹" : t.kind === "update" ? "🔄"
    : t.kind && t.kind !== "download" ? t.kind : "⬇️";
  let info;
  if (t.status === "done") info = `done in ${elapsed(t)}`;
  else if (t.status === "failed") info = `failed: ${t.detail}`;
  else if (t.status === "cancelled") info = "cancelled";
  else if (t.total) info = `${t.done} of ${t.total} ${t.unit || "pictures"} · ${pct}%${eta(t) ? ` · ${eta(t)}` : ""}`;
  else info = `${t.detail ? `${t.detail} · ` : ""}${t.startedAt ? elapsed(t) : "starting…"}`;
  const cancel = t.onCancel && running ? () => (t.members ? t.members.forEach((m) => m.onCancel && m.onCancel()) : t.onCancel()) : null;
  return (
    <div className={`task ${t.status || "running"}`}>
      <span className="taskIcon" aria-hidden="true">{icon}</span>
      <div className="taskBody">
        <div className="taskTop">
          <b>{t.label}{t.count > 1 ? <span className="taskCount"> ×{t.count}</span> : null}</b>
          <span className="muted small">{info}</span>
        </div>
        <div className="bar" role="progressbar" aria-label={t.label} aria-valuemin="0" aria-valuemax={t.total || 100} aria-valuenow={t.status === "done" ? (t.total || 100) : t.done || 0}>
          <i className={pct == null && running ? "indet" : ""} style={{ width: pct == null ? (running ? "30%" : "100%") : `${pct}%` }} />
        </div>
      </div>
      {cancel && <button className="cancelBtn" onClick={cancel} title="Stop this download. Anything already downloaded is kept.">✕ Cancel</button>}
    </div>
  );
}

export default function TaskBar({ tasks = [] }) {
  const shared = useTasks().filter((t) => t.visible);
  const [open, setOpen] = useState(true);
  const [all, setAll] = useState(false);
  const [, tick] = useState(0);
  const rows = [...tasks.map((t) => ({ ...t, status: "running" })), ...grouped(shared)];
  const running = rows.filter((t) => t.status === "running").reduce((n, t) => n + (t.count || 1), 0);

  useEffect(() => {   // keep the timers moving
    if (!running) return;
    const h = setInterval(() => tick((x) => x + 1), 1000);
    return () => clearInterval(h);
  }, [running]);

  if (!rows.length) return null;
  const shown = all ? rows : rows.slice(0, MAX_SHOWN);
  return (
    <div className="taskBar" role="region" aria-label="Downloads and updates" aria-live="polite">
      <div className="taskHead">
        <b>{running ? `⬇️ ${running} download${running > 1 ? "s" : ""} running` : "✅ Downloads finished"}</b>
        {open && running > 1 && <button className="small" onClick={() => rows.forEach((t) => t.status === "running" && (t.members ? t.members.forEach((m) => m.onCancel && m.onCancel()) : t.onCancel && t.onCancel()))}>✕ Cancel all</button>}
        <button className="small" onClick={() => setOpen(!open)} aria-expanded={open} title={open ? "Hide the list" : "Show the list"}>{open ? "▾ Hide" : `▸ Show (${rows.length})`}</button>
      </div>
      {open && shown.map((t) => <Row key={t.id} t={t} />)}
      {open && rows.length > MAX_SHOWN && (
        <button className="small taskMore" onClick={() => setAll(!all)}>{all ? "Show fewer" : `+ ${rows.length - MAX_SHOWN} more`}</button>
      )}
    </div>
  );
}
