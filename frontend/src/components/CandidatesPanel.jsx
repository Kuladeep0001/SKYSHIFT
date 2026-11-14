/* "Find moving things for me": runs detection, then checks each find against Gaia/WISE. */
import { useState } from "react";
import { api } from "../lib/api.js";

const ICON = { mover: "🏃", variable: "💡", appeared: "✨", vanished: "🌑", transient: "☄️" };
const BADGE = {
  known_mover: ["✓ Known fast star", "ok"], known_star: ["✓ Known star", "ok"], known_asteroid: ["☄️ Known asteroid", "ok"],
  unmatched: ["? Unknown: worth a look!", "new"], pending: ["… couldn't check", "wait"],
};

export default function CandidatesPanel({ qid, band, candidates, setCandidates, focus, setFocus, expert }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [checks, setChecks] = useState({});
  const [checking, setChecking] = useState(false);

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
      <h2>Find things that moved {expert && <small>detector {band ? `D${band}` : "all"}</small>}</h2>
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
