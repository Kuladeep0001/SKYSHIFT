/* Details card: what is the object you clicked? Pulled live from SIMBAD, Gaia, WISE and Wikipedia. */
import { useEffect, useState } from "react";
import { objectDetails } from "../lib/api.js";
import { fmtDec, fmtRA } from "../lib/frames.js";

export default function ObjectCard({ pos, simple }) {
  const [d, setD] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  useEffect(() => {
    if (!pos) return;
    let alive = true;
    setBusy(true); setErr("");
    objectDetails(pos.ra, pos.dec, pos.mjd, pos.name)
      .then((r) => alive && setD(r))
      .catch((e) => alive && setErr(e.message))
      .finally(() => alive && setBusy(false));
    return () => { alive = false; };
  }, [pos && pos.ra, pos && pos.dec, pos && pos.name]);

  if (!pos) return null;
  const sim = d?.simbad, g = d?.gaia, w = d?.wise, wiki = d?.wikipedia;
  const rows = [];
  if (sim) {
    rows.push(["Type", sim.type]);
    if (sim.spectral_type) rows.push(["Spectral type", sim.spectral_type]);
  }
  const dist = sim?.distance_ly || g?.distance_ly;
  if (dist) rows.push(["Distance", `${dist < 1000 ? dist.toFixed(1) : Math.round(dist).toLocaleString()} light-years`]);
  if (g) rows.push(["Gaia G mag", `${g.mag}${g.pm_total ? ` · moves ${(g.pm_total / 1000).toFixed(3)}″/yr` : ""}`]);
  if (w) rows.push(["WISE W1 / W2", `${w.mag ?? "–"} / ${w.w2 ?? "–"}${w.w1_w2 != null ? ` (W1−W2 = ${w.w1_w2}${w.w1_w2 > 0.8 ? ", very red" : ""})` : ""}`]);
  if (sim?.radial_velocity_kms != null && !simple) rows.push(["Radial velocity", `${sim.radial_velocity_kms} km/s`]);
  if (sim?.n_references) rows.push(["Papers", sim.n_references.toLocaleString()]);
  rows.push(["Position", `${fmtRA(pos.ra)} ${fmtDec(pos.dec)}`]);

  return (
    <section className="card objectCard" aria-live="polite">
      <h2>Object details <small>{busy ? "asking SIMBAD, Gaia, WISE, Wikipedia…" : d ? d.sources.join(" · ") : ""}</small></h2>
      {err && <p className="err">{err}</p>}
      {d && (
        <>
          <div className="objHead">
            {wiki?.thumbnail && <img src={wiki.thumbnail} alt={wiki.title} />}
            <div>
              <h3>{sim?.name || pos.name || "Unnamed source"}</h3>
              <p>{d.summary}</p>
            </div>
          </div>
          {wiki && <blockquote>{wiki.extract.length > 420 ? wiki.extract.slice(0, 420) + "…" : wiki.extract} <a href={wiki.url} target="_blank" rel="noreferrer">Wikipedia</a></blockquote>}
          <dl className="meta">{rows.map(([k, v]) => <div key={k} className="mrow"><dt>{k}</dt><dd>{v}</dd></div>)}</dl>
          <div className="links">{d.links.map((l) => <a key={l.label} href={l.url} target="_blank" rel="noreferrer">{l.label} ↗</a>)}</div>
          {d.errors?.length > 0 && !simple && <p className="small muted">Some services didn't answer: {d.errors.join("; ")}</p>}
        </>
      )}
    </section>
  );
}
