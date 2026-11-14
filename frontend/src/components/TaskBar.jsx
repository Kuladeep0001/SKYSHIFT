/* Task bar: what SkyShift is downloading or updating right now, with a Cancel button.
 * tasks: [{ id, label, detail, done, total, startedAt, onCancel, kind }]
 * Owner: UI 2.
 */
function eta(t) {
  if (!t.total || !t.done || !t.startedAt) return "";
  const secs = ((Date.now() - t.startedAt) / 1000 / t.done) * (t.total - t.done);
  if (!Number.isFinite(secs) || secs < 2) return "almost done";
  return secs > 90 ? `about ${Math.round(secs / 60)} min left` : `about ${Math.round(secs)} s left`;
}

export default function TaskBar({ tasks }) {
  if (!tasks.length) return null;
  return (
    <div className="taskBar" role="region" aria-label="Downloads and updates" aria-live="polite">
      {tasks.map((t) => {
        const pct = t.total ? Math.max(3, Math.round((100 * t.done) / t.total)) : null;
        return (
          <div className="task" key={t.id}>
            <span className="taskIcon" aria-hidden="true">{t.kind === "update" ? "🔄" : "⬇️"}</span>
            <div className="taskBody">
              <div className="taskTop">
                <b>{t.label}</b>
                <span className="muted small">
                  {t.total ? `${t.done} of ${t.total} pictures · ${pct}%${eta(t) ? ` · ${eta(t)}` : ""}` : t.detail || "starting…"}
                </span>
              </div>
              <div className="bar" role="progressbar" aria-valuemin="0" aria-valuemax={t.total || 100} aria-valuenow={t.done || 0}>
                <i className={pct == null ? "indet" : ""} style={{ width: pct == null ? "30%" : `${pct}%` }} />
              </div>
            </div>
            {t.onCancel && <button className="cancelBtn" onClick={t.onCancel} title="Stop this download. Pictures already downloaded are kept.">✕ Cancel</button>}
          </div>
        );
      })}
    </div>
  );
}
