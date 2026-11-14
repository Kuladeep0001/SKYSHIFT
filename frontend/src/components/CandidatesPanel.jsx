/* "Find moving things for me": runs detection, then checks each find against Gaia/WISE. */
import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api.js";

const ICON = { mover: "🏃", variable: "💡", appeared: "✨", vanished: "🌑", transient: "☄️" };
const BADGE = {
  known_mover: ["✓ Known fast star", "ok"], known_star: ["✓ Known star", "ok"], known_asteroid: ["☄️ Known asteroid", "ok"],
  likely_artefact: ["⚠ Probably glare", "wait"],
  unmatched: ["? Unknown: worth a look!", "new"], pending: ["… couldn't check", "wait"],
};

function ReportForm({ c, v, ctx, onDone }) {
  const [nick, setNick] = useState(() => { try { return localStorage.getItem("skyshift-nick") || ""; } catch (_) { return ""; } });
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const send = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      try { localStorage.setItem("skyshift-nick", nick); } catch (_) { /* private mode */ }
      const r = await api.report({ ra: c.ra, dec: c.dec, fov: ctx.fov, query_id: ctx.qid, x: c.x, y: c.y, kind: c.kind,
        verification: v?.verification_status || null, summary: `${c.plain_english} ${v ? v.plain_english : ""}`.trim().slice(0, 600),
        note, nickname: nick, target: ctx.target || "" });
      onDone(r.merged_with_existing ? "Someone already reported this. Your report counts as a vote! See the Discovery board." : "Reported! It's on the Discovery board for others to check.");
    } catch (err) { onDone(`Couldn't report: ${err.message}`); } finally { setBusy(false); }
  };
  return (
    <form className="reportForm" onSubmit={send} onClick={(e) => e.stopPropagation()}>
      <input value={nick} onChange={(e) => setNick(e.target.value)} placeholder="Your nickname (optional)" maxLength={40} aria-label="Nickname" />
      <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="What did you notice? (optional)" maxLength={280} aria-label="Note" />
      <button className="primary" disabled={busy}>{busy ? "Sending…" : "📣 Report"}</button>
    </form>
  );
}

export default function CandidatesPanel({ qid, band, candidates, setCandidates, focus, setFocus, expert, autoRun, onChecks, ctx, say }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [checks, setChecks] = useState({});
  const [checking, setChecking] = useState(false);
  const [reporting, setReporting] = useState(null);
  const lastSignal = useRef(autoRun);  // only react to NEW requests (not when the panel remounts)
  useEffect(() => { if (autoRun && autoRun !== lastSignal.current) { lastSignal.current = autoRun; run(); } }, [autoRun]);
  useEffect(() => { onChecks && onChecks(checks); }, [checks]);

  async function run() {
    setBusy(true); setErr(""); setChecks({}); setFocus(null);
    try {
      const res = await api.detect({ query_id: qid, band });
      setCandidates(res.candidates);
      if (res.candidates.length) {
        setFocus(res.candidates[0].candidate_id);
        setChecking(true);
        api.verify(res.candidates.slice(0, 8))
          .then((rs) => setChecks(Object.fromEntries(rs.map((r) => [r.candidate_id, r]))))
          .catch(() => {})
          .finally(() => setChecking(false));
      }
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card candidates">
      <h2>Find things that moved {expert && <small>detector {band === 7 ? "D5+D6" : band ? `D${band}` : "all"}</small>}</h2>
      <p className="small muted">SkyShift compares the visits, points out anything that moved or changed brightness, and checks it against other telescopes.</p>
      <button className="primary full" onClick={run} disabled={busy || !qid}>{busy ? "Searching…" : "🔎 Find moving or changing things"}</button>
      {err && <p className="err">{err}</p>}
      {candidates && !candidates.length && <p className="hint">Nothing obvious changed here. Try another detector or a bigger area.</p>}
      <ul className="candList">
        {(candidates || []).map((c) => {
          const v = checks[c.candidate_id];
          const [label, cls] = v ? BADGE[v.verification_status] : checking ? ["checking…", "wait"] : ["", ""];
          return (
            <li key={c.candidate_id} className={focus === c.candidate_id ? "on" : ""} onClick={() => setFocus(c.candidate_id)}>
              <div className="candHead">
                <span className="ico">{ICON[c.kind] || "•"}</span>
                <b>{c.candidate_id}</b>
                <span className="kind">{c.kind}</span>
                {label && <span className={`badge ${cls}`}>{label}</span>}
              </div>
              <p>{c.plain_english}</p>
              {v && <p className="verify">{v.plain_english}</p>}
              {reporting === c.candidate_id ? <ReportForm c={c} v={v} ctx={ctx || {}} onDone={(m) => { setReporting(null); say && say(m); }} />
                : <button className="linkBtn small" onClick={(e) => { e.stopPropagation(); setReporting(c.candidate_id); }}>📣 Report this find</button>}
              {expert && (
                <p className="mono small muted">
                  RA {c.ra.toFixed(5)} Dec {c.dec.toFixed(5)} · S/N {c.snr} · score {c.score}
                  {c.motion ? ` · ${c.motion.total_arcsec_yr}″/yr PA ${c.motion.pa_deg}°` : ""}
                  {c.flux_change && c.flux_change.ratio ? ` · ×${c.flux_change.ratio}` : ""}
                </p>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
