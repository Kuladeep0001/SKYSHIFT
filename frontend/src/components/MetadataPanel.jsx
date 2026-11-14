/* Facts about the current picture, including contamination flags. */
import { fmtDec, fmtRA, fmtWave, monthYear } from "../lib/frames.js";
import Term from "./Term.jsx";

function ago(t) {
  if (!t) return "never";
  const s = Date.now() / 1000 - t;
  return s < 90 ? "just now" : s < 5400 ? `${Math.round(s / 60)} min ago` : s < 172800 ? `${Math.round(s / 3600)} h ago` : `${Math.round(s / 86400)} days ago`;
}

export default function MetadataPanel({ target, meta, frame, flags, fov, releases, selFlags, simple, fresh, onCheckNow }) {
  if (!target || !meta) return null;
  let bad = null;
  if (flags) {
    let c = 0;
    for (let i = 0; i < flags.length; i++) c += flags[i];
    bad = (100 * c) / flags.length;
  }
  const rows = [
    ["Target", target.name || "Custom position"],
    [<Term k="RA / Dec" key="t">Sky address</Term>, <>{fmtRA(target.ra)} {fmtDec(target.dec)}<br /><small>{target.ra.toFixed(5)}°, {target.dec.toFixed(5)}°</small></>],
  ];
  if (target.pm_corrected && Math.hypot(target.pmra, target.pmdec) > 100)
    rows.push([<Term k="proper motion" key="pm">Motion</Term>, `${(Math.hypot(target.pmra, target.pmdec) / 1000).toFixed(2)}″ per year (centred on where it is in 2026)`]);
  rows.push(["Area shown", `${fov}′ × ${fov}′ · ${meta.n_pix}×${meta.n_pix} pixels of 6.15″`]);
  rows.push(["Pictures", `${meta.exposures.length} snapshots in ${meta.visits.length} visits${simple ? "" : ` · ${releases.join(" + ")}`}`]);
  if (frame) {
    rows.push(["This picture", frame.date_range ? `${monthYear(frame.date_range[0])} (${frame.date_range[0]} → ${frame.date_range[1]})` : `${frame.date} UT`]);
    if (!simple) {
      rows.push(["Detector", frame.det ? `D${frame.det} (${meta.detectors[frame.det].map((x) => x.toFixed(2)).join("–")} µm)` : "all 6 combined"]);
      if (frame.wave) rows.push(["Wavelength", `${fmtWave(frame.wave)}${frame.channel ? ` · plane ${frame.channel} of 102` : ""}`]);
      if (frame.n_exp) rows.push(["Stacked", `${frame.n_exp} snapshots`]);
      if (frame.obs_id) rows.push(["Exposure ID", frame.obs_id]);
    }
    if (bad != null) rows.push([simple ? "Bad pixels" : "Contaminated", `${bad.toFixed(1)}% ${simple ? "(glare, ghosts, streaks)" : "(ghost, streak, halo, crosstalk, persistence)"}`]);
  }
  if (selFlags) rows.push(["Flags at spot", selFlags.length ? selFlags.map((x) => <span key={x} className="flag" title={meta.flag_defs?.[x]?.meaning || ""}>{x}</span>) : "none"]);
  return (
    <section className="card">
      <h2>{simple ? "About this picture" : "Metadata"}</h2>
      <dl className="meta">{rows.map(([k, v], i) => <div key={i} className="mrow"><dt>{k}</dt><dd>{v}</dd></div>)}</dl>
      {fresh && (
        <div className="freshness">
          <span>🛰 Up to date with NASA as of <b>{ago(fresh.checked_at)}</b>
            {fresh.last_update?.at ? <> · last new data {ago(fresh.last_update.at)}</> : null}
            {!simple && <> · data v{fresh.version}</>}</span>
          <button onClick={onCheckNow} disabled={fresh.refreshing}>{fresh.refreshing ? "Updating…" : "🔄 Check for new pictures"}</button>
          <p className="small muted">SkyShift re-checks NASA's archive automatically, so new SPHEREx releases appear here without anyone touching the code.</p>
        </div>
      )}
    </section>
  );
}
