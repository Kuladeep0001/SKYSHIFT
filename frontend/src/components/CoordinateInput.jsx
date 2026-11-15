/* Where to look: a name box, or two coordinate boxes (RA & Dec, a place on Earth, or galactic), field of view,
 * data release. Coordinates are read forgivingly by the server (/api/resolve/position): stray spaces, signs,
 * h m s, ° ′ ″, decimal commas, N/S/E/W, or both numbers pasted into the first box. What was understood is
 * shown under the boxes before anything loads. Owner: UI 1. */
import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api.js";
import { TARGETS } from "../lib/targets.js";

const FRAMES = {
  icrs: { label: "Sky: RA and Dec", a: "RA", b: "Dec", pa: "17 57 48.5  or  269.45", pb: "+04 41 36  or  4.69" },
  earth: { label: "Place on Earth: latitude and longitude (the sky overhead now)", a: "Latitude", b: "Longitude", pa: "12.97 N  or  12.9716", pb: "77.59 E  or  -74.0" },
  galactic: { label: "Galactic: l and b", a: "Galactic l", b: "Galactic b", pa: "31.0", pb: "+14.1" },
};
const HINT = "Type a name, or RA and Dec in any form: 269.45 · 17 57 48.5 · 17h57m48.5s · +04°41′36″. Latitude and longitude show the sky straight above that place right now.";

export default function CoordinateInput({ initial, onGo, onGoCoords, fov, setFov, release, setRelease, releases, expert, busy }) {
  const [name, setName] = useState(initial || "");
  const [a, setA] = useState("");
  const [b, setB] = useState("");
  const [frame, setFrame] = useState("icrs");
  const [last, setLast] = useState("name");        // which group was typed in last: it wins on Show me
  const [note, setNote] = useState(null);          // { text, err, field }
  const timer = useRef(0);
  const F = FRAMES[frame];

  const readAs = (r) => `Read as ${F.a} ${r.read_a}, ${F.b} ${r.read_b}` +
    (frame === "earth" ? ` → the sky overhead now: ${r.read}` : frame === "galactic" ? ` → ${r.read}` : "") +
    (r.split ? " (I split the two numbers you typed in one box)" : "");

  // read back what was typed, half a second after typing stops (needs both boxes, or a pair in the first one)
  useEffect(() => {
    clearTimeout(timer.current);
    const ta = a.trim(), tb = b.trim();
    if (!ta && !tb) { if (last === "coords") setNote(null); return; }
    if (!tb && !/[\s,+-].*\d/.test(ta.slice(1))) return;                 // one number so far: wait for the other box
    timer.current = setTimeout(async () => {
      try {
        const r = await api.resolvePosition(ta, tb, frame);
        setNote({ text: readAs(r) });
      } catch (e) { setNote({ err: true, field: e.field, text: e.message }); }
    }, 500);
    return () => clearTimeout(timer.current);
  }, [a, b, frame]);

  const submit = async (e) => {
    e.preventDefault();
    const ta = a.trim(), tb = b.trim(), tn = name.trim();
    const useName = tn && (last === "name" || !(ta || tb));
    if (useName) { setNote(null); onGo(tn); return; }
    if (!ta && !tb) { setNote({ err: true, text: "Type a star or planet name, or both coordinates." }); return; }
    clearTimeout(timer.current);
    try {
      const r = await api.resolvePosition(ta, tb, frame);
      if (r.split) { setA(r.split[0]); setB(r.split[1]); }
      setNote({ text: readAs(r) });
      onGoCoords(r.ra, r.dec);
    } catch (err) { setNote({ err: true, field: err.field, text: err.message }); }
  };
  const onCoord = (set) => (e) => { set(e.target.value); setLast("coords"); };

  return (
    <div className="coordInput">
      <form onSubmit={submit} className="searchBoxes" autoComplete="off">
        <label className="nameBox">
          <span>Star or planet name</span>
          <input value={name} onChange={(e) => { setName(e.target.value); setLast("name"); }} type="text"
            placeholder="e.g. Barnard's Star, Vega, 51 Peg b, Orion Nebula" aria-label="Star or planet name" />
        </label>
        <span className="orSep">or</span>
        <div className="coordPair" role="group" aria-label={F.label}>
          <label>
            <span>{F.a}</span>
            <input value={a} onChange={onCoord(setA)} type="text" placeholder={F.pa} aria-label={F.a}
              className={note?.err && note.field === "a" ? "bad" : ""} aria-invalid={note?.err && note.field === "a" ? "true" : undefined} />
          </label>
          <label>
            <span>{F.b}</span>
            <input value={b} onChange={onCoord(setB)} type="text" placeholder={F.pb} aria-label={F.b}
              className={note?.err && note.field === "b" ? "bad" : ""} aria-invalid={note?.err && note.field === "b" ? "true" : undefined} />
          </label>
        </div>
        <button className="primary goBtn" type="submit" disabled={busy}>{busy ? "Loading…" : "Show me"}</button>
      </form>
      <p className={`searchNote ${note?.err ? "err" : ""}`} aria-live="polite">{note ? note.text : HINT}</p>
      <div className="searchOpts">
        <label title="What the two coordinate boxes mean">
          Coordinates:
          <select className="frameSel" value={frame} onChange={(e) => { setFrame(e.target.value); setNote(null); }} aria-label="Kind of coordinates">
            {Object.entries(FRAMES).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
          </select>
        </label>
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
          <button key={t.id} onClick={() => { setName(t.label); setLast("name"); setNote(null); onGo(t.q); }} disabled={busy} title={t.tagline}>
            {t.label}
          </button>
        ))}
      </div>
    </div>
  );
}
