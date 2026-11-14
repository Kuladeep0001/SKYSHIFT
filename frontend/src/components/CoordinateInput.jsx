/* Where to look: name or coordinates, field of view, data release. Owner: UI 1. */
import { useState } from "react";
import { TARGETS } from "../lib/targets.js";

export default function CoordinateInput({ initial, onGo, fov, setFov, release, setRelease, releases, expert, busy }) {
  const [text, setText] = useState(initial || "");
  const submit = (e) => { e.preventDefault(); if (text.trim()) onGo(text.trim()); };
  return (
    <div className="coordInput">
      <form onSubmit={submit} className="search" autoComplete="off">
        <input value={text} onChange={(e) => setText(e.target.value)} type="text"
          placeholder="Type a star's name (e.g. Barnard's Star) or sky coordinates (RA Dec)"
          aria-label="Star name or coordinates" />
        <button className="primary" type="submit" disabled={busy}>{busy ? "Loading…" : "Show me"}</button>
      </form>
      <div className="searchOpts">
        <label title="How much sky to show. Bigger catches faster movers but takes longer to download.">
          Area: <b>{fov}′</b>
          <input type="range" min="2" max="20" step="1" value={fov} onChange={(e) => setFov(+e.target.value)} />
          <small>{fov <= 6 ? "fast to load" : fov <= 12 ? "slower" : "slow (big download)"}</small>
        </label>
        {expert && (
          <select value={release} onChange={(e) => setRelease(e.target.value)} title="SPHEREx data release (found automatically at NASA IRSA)">
            <option value="">Data: newest ({(releases?.best || []).map((r) => r.replace("spherex_", "").toUpperCase()).join(" + ") || "auto"})</option>
            {(releases?.releases || []).map((r) => <option key={r.id} value={r.id}>{r.id.replace("spherex_", "").toUpperCase()} only</option>)}
          </select>
        )}
      </div>
      <div className="chips" aria-label="Try one of these">
        <span className="lbl">Try:</span>
        {TARGETS.map((t) => (
          <button key={t.id} onClick={() => { setText(t.label); onGo(t.q); }} disabled={busy} title={t.tagline}>
            {t.label}
          </button>
        ))}
      </div>
    </div>
  );
}
