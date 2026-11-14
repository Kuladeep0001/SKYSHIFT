/* Catalogue cross-check: is the selected object already known? Checks Gaia DR3, 2MASS, AllWISE and SIMBAD,
 * each at its own observing date (stars move), via POST /api/verification/ (backend/routes/crossmatch.py).
 * Owner: Verification (Meenakshi K) + UI.
 */
import { useEffect, useState } from "react";
import { api } from "../lib/api.js";

const CATS = [
  ["gaia", "Gaia DR3", "ESA, visible light, 2016"],
  ["2mass", "2MASS", "near-infrared, about 1999"],
  ["allwise", "AllWISE", "mid-infrared, 2010"],
  ["simbad", "SIMBAD", "the astronomers' encyclopedia of named objects"],
];

const VERDICT = {
  confirmed_association: ["✅", "Known object", "good"],
  potential_association: ["🟡", "Possibly known", "maybe"],
  no_association: ["❓", "Not in these catalogues", "none"],
  insufficient_evidence: ["⚪", "Couldn't tell", "none"],
  conflicting_evidence: ["⚠️", "The catalogues disagree", "maybe"],
};

const ROW = {
  confirmed_association: ["✓", "match"],
  potential_association: ["~", "maybe"],
  no_association: ["–", "nothing there"],
  insufficient_evidence: ["?", "no answer"],
};

const mag = (v) => (v == null ? "–" : v.toFixed(2));

function plainVerdict(res, n) {
  const ev = res.evidence_summary?.catalogues || {};
  const hits = CATS.filter(([k]) => ev[k]?.evidence === "confirmed_association").map(([, l]) => l);
  switch (res.assessment) {
    case "confirmed_association":
      return `Found at this exact spot in ${hits.length} of ${n} catalogues (${hits.join(", ")}), after allowing for how far it moved between their observing dates. This is an object astronomers already know.`;
    case "potential_association":
      return "Something is close by in the catalogues, but not close enough, or not at the right date, to be sure it is the same object.";
    case "no_association":
      return "None of the catalogues has anything at this spot. It could be something new, something too faint for them, or a camera artefact. Worth a closer look!";
    case "conflicting_evidence":
      return "The catalogues give conflicting answers. This needs a human to look.";
    default:
      return "Some catalogue servers didn't answer, so we can't say yet. Try again in a minute.";
  }
}

function highlights(key, r) {
  const s = r?.nearest_source;
  if (!s) return null;
  if (key === "gaia") {
    const d = s.distance, pm = s.proper_motion?.total_mas_yr;
    return [d && `${d.light_years < 1000 ? d.light_years.toFixed(1) : Math.round(d.light_years).toLocaleString()} light-years away`,
      pm != null && `moves ${(pm / 1000).toFixed(3)}″/yr`, s.photometry?.g_magnitude != null && `G ${mag(s.photometry.g_magnitude)}`,
      s.photometry?.temperature_k && `≈${Math.round(s.photometry.temperature_k).toLocaleString()} K`].filter(Boolean).join(" · ");
  }
  if (key === "2mass") {
    const p = s.photometry || {};
    return ["J", "H", "Ks"].map((b) => `${b} ${p[b]?.is_detection ? mag(p[b].magnitude) : p[b]?.is_upper_limit ? `>${mag(p[b].magnitude)}` : "–"}`).join(" · ");
  }
  if (key === "allwise") {
    const p = s.photometry || {};
    const w1 = p.W1?.magnitude_vega, w2 = p.W2?.magnitude_vega;
    const col = w1 != null && w2 != null ? ` · W1−W2 ${(w1 - w2).toFixed(2)}${w1 - w2 > 0.8 ? " (very red)" : ""}` : "";
    return `W1 ${mag(w1)} · W2 ${mag(w2)}${col}`;
  }
  if (key === "simbad") {
    return [s.object_type, s.spectral_type && `type ${s.spectral_type}`].filter(Boolean).join(" · ");
  }
  return null;
}

const MJ_TO_EARTH = 317.8;

/* Known planets of this star (NASA Exoplanet Archive, matched by Gaia ID or position). */
function Planets({ exo, simple }) {
  if (!exo || exo.status !== "match_found" || !exo.planets?.length) return null;
  const pl = [...exo.planets].sort((a, b) => (a.planet_parameters?.orbital_period_days || 9e9) - (b.planet_parameters?.orbital_period_days || 9e9));
  const names = pl.map((x) => x.planet_name);
  const fastest = pl[0]?.planet_parameters?.orbital_period_days;
  return (
    <div className="planets">
      <p className="small"><span aria-hidden="true">🪐</span> <b>This star has {exo.planet_count || pl.length} known planet{(exo.planet_count || pl.length) > 1 ? "s" : ""}</b>: {names.join(", ")}
        {simple && fastest ? <>. The closest one goes round its star in just {fastest < 10 ? fastest.toFixed(1) : Math.round(fastest)} days.</> : "."}
        <span className="muted"> (NASA Exoplanet Archive)</span></p>
      {!simple && (
        <table className="features catTable">
          <thead><tr><th>Planet</th><th>Orbit (days)</th><th>Size (Earths)</th><th>Mass (Earths)</th></tr></thead>
          <tbody>{pl.map((x) => {
            const q = x.planet_parameters || {};
            return (
              <tr key={x.planet_name}><td>{x.planet_name}</td><td className="mono">{q.orbital_period_days != null ? q.orbital_period_days.toFixed(2) : "–"}</td>
                <td className="mono">{q.radius_earth_radii != null ? q.radius_earth_radii.toFixed(2) : "–"}</td>
                <td className="mono">{q.mass_jupiter_masses != null ? (q.mass_jupiter_masses * MJ_TO_EARTH).toFixed(2) : "–"}</td></tr>
            );
          })}</tbody>
        </table>
      )}
    </div>
  );
}

/* Expert extras from the verification module: colours across catalogues and other names. */
function Extras({ res }) {
  const colours = Object.values(res.photometric_assessment?.colours || {});
  const names = res.object_profile?.identity?.alternative_names || [];
  if (!colours.length && !names.length) return null;
  return (
    <>
      {colours.length > 0 && (
        <p className="small"><b>Colours:</b> {colours.map((c) => `${c.name} ${c.value?.toFixed(2)}${c.quality && c.quality !== "usable" ? " (uncertain)" : ""}`).join(" · ")}</p>
      )}
      {names.length > 0 && <p className="small muted"><b>Also known as:</b> {names.slice(0, 8).join(", ")}</p>}
    </>
  );
}

export default function CatalogueCheck({ pos, pm, label, simple }) {
  const [res, setRes] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  useEffect(() => { setRes(null); setErr(""); }, [pos && pos.ra, pos && pos.dec]);
  if (!pos) return null;

  async function run() {
    setBusy(true); setErr(""); setRes(null);
    try {
      const when = pos.mjd ? new Date((pos.mjd - 40587) * 864e5) : new Date();
      const cand = { candidate_id: label || "selected", ra: pos.ra, dec: pos.dec, observation_time: when.toISOString() };
      if (pm && Number.isFinite(pm.pmra) && Number.isFinite(pm.pmdec)) { cand.pmra_mas_yr = pm.pmra; cand.pmdec_mas_yr = pm.pmdec; }
      const r = await api.crossCheck([cand]);
      setRes(r.results[0]);
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  }

  const ev = res?.evidence_summary?.catalogues || {};
  const v = res && (VERDICT[res.assessment] || VERDICT.insufficient_evidence);
  const caveats = res ? [...new Set([...Object.values(ev).flatMap((c) => c.photometric_caveats || []), ...(simple ? [] : res.photometric_assessment?.warnings || [])])] : [];
  const cross = res?.cross_catalogue_association;
  const simbadSrc = res?.catalogue_results?.simbad?.nearest_source;

  return (
    <section className="card catCheck" aria-live="polite">
      <h2>🔬 Is it already known? <small>Gaia · 2MASS · AllWISE · SIMBAD</small></h2>
      {!res && !busy && (
        <>
          <p className="small">{simple
            ? "Check four big star catalogues for this object. Stars move, so each catalogue is compared at the date it was made."
            : "Epoch-aware cross-match within 6″ (one SPHEREx pixel): Gaia DR3 is propagated with its proper motion to the 2MASS and AllWISE epochs; SIMBAD positions are propagated from J2000."}</p>
          <button className="primary" onClick={run}>Check {label ? `“${label}”` : "this object"} in 4 catalogues</button>
          {pm && <p className="small muted">Using its measured motion ({(Math.hypot(pm.pmra, pm.pmdec) / 1000).toFixed(2)}″/yr) to find it at older dates.</p>}
        </>
      )}
      {busy && <p className="small"><span className="spin" aria-hidden="true" /> Asking Gaia, 2MASS, AllWISE and SIMBAD… (10–30 seconds)</p>}
      {err && <p className="err">{err} <button className="small" onClick={run}>Try again</button></p>}
      {res && (
        <>
          <p className={`verdict ${v[2]}`}><span aria-hidden="true">{v[0]}</span> <b>{v[1]}</b></p>
          <p className="small">{plainVerdict(res, Object.keys(ev).length)}</p>
          {simbadSrc?.name && ev.simbad?.evidence === "confirmed_association" && (
            <p className="small">SIMBAD knows it as <a href={simbadSrc.url} target="_blank" rel="noreferrer"><b>{simbadSrc.name}</b></a>{simbadSrc.object_type ? ` (${simbadSrc.object_type})` : ""}.</p>
          )}
          <table className="features catTable">
            <thead><tr><th>Catalogue</th><th>Result</th><th>Off by</th><th>{simple ? "What it says" : "Details"}</th></tr></thead>
            <tbody>
              {CATS.filter(([k]) => ev[k]).map(([k, name, what]) => {
                const e = ev[k], [icon, word] = ROW[e.evidence] || ROW.insufficient_evidence;
                const r = res.catalogue_results[k];
                return (
                  <tr key={k} className={e.evidence === "confirmed_association" ? "likely" : e.evidence === "potential_association" ? "possible" : ""}
                    title={`${what}. ${(e.reasons || []).join(" ")} ${r?.message || ""}`}>
                    <td><b>{name}</b></td>
                    <td>{icon} {word}</td>
                    <td className="mono">{e.separation_arcsec != null ? `${e.separation_arcsec.toFixed(2)}″` : "–"}</td>
                    <td className="small">{e.evidence === "confirmed_association" || !simple ? highlights(k, r) || e.source_identifier || "" : r?.message || ""}
                      {!simple && e.source_identifier && <div className="mono muted">{e.source_identifier}</div>}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {cross && cross.status !== "not_assessable" && (
            <p className="small">{cross.status === "consistent" ? "✓ The catalogue positions agree with each other once Gaia's measured motion is taken into account."
              : cross.status === "mixed_evidence" ? "⚠ Some catalogue positions agree with Gaia and some don't."
                : `Catalogue positions vs Gaia: ${cross.status}.`}</p>
          )}
          <Planets exo={res.exoplanet_association} simple={simple} />
          {!simple && <Extras res={res} />}
          {caveats.length > 0 && <ul className="small warnList">{caveats.map((c) => <li key={c}>⚠ {c}</li>)}</ul>}
          {!simple && (
            <details className="small"><summary>Raw result (JSON)</summary><pre className="raw">{JSON.stringify(res, null, 1)}</pre></details>
          )}
          <button className="small" onClick={run}>↻ Check again</button>
        </>
      )}
    </section>
  );
}
