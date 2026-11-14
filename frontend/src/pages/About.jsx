/* "How it works" for everyone: what SkyShift does, how it answers the challenge, how accurate it is,
 * who it helps, plus credits. Owner: UI 1. */
import { useEffect, useState } from "react";
import { api } from "../lib/api.js";
import { GLOSSARY } from "../lib/targets.js";

const go = (q, view, extra = "") => `./?q=${encodeURIComponent(q)}${view ? `&view=${view}` : ""}${extra}`;

/* The challenge's requirements and where SkyShift answers each one. */
const CHALLENGE = [
  ["Must have", "Enter RA/Dec (any format) or a star's name", "Search box (also on the home sky map: click a spot or draw a square)", go("17 57 48.5 +04 41 36")],
  ["Must have", "Retrieve SPHEREx images of that spot", "Every SPHEREx exposure from NASA IRSA (newest release first), cut out, aligned north-up and cleaned", go("Barnard's Star")],
  ["Must have", "Show images from different times", "One stacked picture per visit, with dates; every single snapshot in Expert mode", go("Barnard's Star")],
  ["Must have", "Play them like a video", "Flipbook with speed control and keyboard (Space, ← →)", go("Barnard's Star")],
  ["Extra", "Easy updates with new data releases", "Detects new SPHEREx releases and new pictures by itself, rebuilds the spot, shows \"NASA added data\"", "#about-updates"],
  ["Extra", "Creative use of the 102 bands", "RGB colour grading, 102-colour spectral cube, continuous spectrum, molecule finder, sound", go("eps Ind B", "planes", "&expert=1")],
  ["Extra", "Combine the 6 detectors", "All six stacked (deepest), \"Reddest\" (D5+D6) for brown dwarfs, 6-detector wall", go("Barnard's Star", "wall", "&expert=1")],
  ["Extra", "Add / subtract epochs", "− first, − previous, Σ add all, Before/after slider", go("Barnard's Star", "compare")],
  ["Extra", "Selectable field of view", "Area slider 2′–20′, or draw a square on the sky map", go("R Dra")],
  ["Extra", "Gaia / WISE overlays", "Gaia stars moved to each picture's date, AllWISE sources, known asteroids", go("Barnard's Star")],
  ["Extra", "URL coordinate queries", "Every view has its own link (?ra=…&dec=…&fov=…), plus &embed=1 for other websites", go("WISE 0855", "", "&fov=6")],
  ["Extra", "Metadata and contamination flags", "Per-picture details and SPHEREx flags; bad-pixel overlay", go("RW Aur", "", "&expert=1")],
  ["Extra", "Use Aladin and astropy", "Aladin Lite sky maps; astropy for WCS, coordinates and time", "./"],
];

const AUDIENCES = [
  ["Students and the public", "Simple mode, guided tour, plain-English explanations of every picture, stories for each target.", go("Barnard's Star", "", "&tour=1")],
  ["Teachers", "Ready-made activities below: measure a star's speed, find water on a brown dwarf, hear a giant star breathe.", "#about-teach"],
  ["Citizen scientists", "Find moving or changing things anywhere on the sky, check them against 4 catalogues, report them on the Discovery board.", "#board"],
  ["Astronomers", "Expert mode: single exposures, 102-colour cube, spectra with errors, light curves, flags, CSV export, REST API.", go("eps Ind B", "", "&expert=1")],
  ["Blind and low-vision visitors", "Listen tab: the brightness graph and the motion as sound, keyboard and screen-reader friendly.", go("Barnard's Star", "listen", "&listen=1")],
  ["Colour-blind visitors", "Colour-safe switches every red/green to orange/blue.", "./"],
  ["Developers", "Open source, documented API, Docker, mock mode, embed code for any website.", "/docs"],
];

const ACTIVITIES = [
  ["Measure the fastest star", "Open Barnard's Star, press, then Find moving things. How many arcseconds per year does it move? How long until it crosses the full Moon's width (1800″)?", go("Barnard's Star")],
  ["Find water on a failed star", "Open Epsilon Indi B and look at the spectrum: where does the line dip? Those dips at 1.4 and 1.9 µm are water vapour in a brown dwarf's air.", go("eps Ind B", "", "&expert=1")],
  ["Hear a giant star breathe", "Open R Draconis, Before/after tab: compare the two visits. Then the Listen tab: play the graph and describe what you hear.", go("R Dra", "compare")],
];

function Accuracy() {
  const [d, setD] = useState(null);
  const [err, setErr] = useState("");
  useEffect(() => { api.validation().then(setD).catch((e) => setErr(e.message)); }, []);
  const verdictIcon = { excellent: "", "agrees within the error": "", agrees: "", close: "", off: "", unclear: "" };
  return (
    <section className="card" id="about-accuracy">
      <h2>How accurate is SkyShift?</h2>
      <p>SkyShift measures the five challenge targets using <b>only SPHEREx pictures</b>, then we compare with what astronomers already know. This table is worked out live by the server each time you open this page.</p>
      {!d && !err && <p className="small muted"><span className="spin" aria-hidden="true" /> Measuring the five targets…</p>}
      {err && <p className="err">{err}</p>}
      {d && (
        <>
          <div className="tableScroll">
            <table className="features accTable">
              <thead><tr><th>Target</th><th>SkyShift measured</th><th>Known value</th><th>Difference</th><th>Verdict</th></tr></thead>
              <tbody>
                {d.rows.map((r) => (
                  <tr key={r.query}>
                    <td><a href={go(r.query)}>{r.target}</a></td>
                    {r.status !== "ok" ? <td colSpan="4" className="muted">{r.message}</td>
                      : r.kind === "mover" ? (
                        <>
                          <td className="mono">{r.measured_arcsec_yr.toFixed(2)}{r.measured_err_arcsec_yr != null ? ` ± ${r.measured_err_arcsec_yr.toFixed(2)}` : ""}″/yr<br /><span className="muted">toward {r.measured_pa_deg}° · {r.n_visits} visits</span></td>
                          <td className="mono">{r.known_arcsec_yr.toFixed(2)}″/yr<br /><span className="muted">toward {r.known_pa_deg}°</span></td>
                          <td className="mono">{r.diff_pct}%{r.n_sigma != null ? <><br /><span className="muted">{r.n_sigma}σ · {r.pa_diff_deg}° in direction</span></> : null}</td>
                          <td>{verdictIcon[r.verdict] || ""} {r.verdict}</td>
                        </>
                      ) : (
                        <>
                          <td>Brightness changed <b>{r.brightness_change}×</b> between visits ({r.direction}){r.stayed_put ? "; it stayed in place" : ""}<br /><span className="muted">{r.band_used}</span></td>
                          <td>{r.reference}</td>
                          <td className="muted">–</td>
                          <td>{verdictIcon[r.verdict] || ""} {r.verdict}</td>
                        </>
                      )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="small"><b>How it is measured:</b> {d.method}</p>
          <p className="small muted"><b>Honest limits:</b> SPHEREx pixels are 6.15″ wide, so a star must move about a pixel between visits to be measured well.
            Very faint objects can be blended with a background star (WISE 0855 is), which pulls the measurement low; the error bar shows this.
            Very bright stars overload the camera; their positions are still good, but their spectra are lower limits. Spectral "molecule" bands are hints to follow up, not proof.</p>
        </>
      )}
    </section>
  );
}

export default function About() {
  return (
    <div className="about">
      <div className="brandBanner"><img src="/logo.png" alt="SkyShift: Explore. Identify. Understand." /></div>
      <section className="card">
        <h1>How SkyShift works</h1>
        <ol className="how">
          <li><b>NASA's SPHEREx telescope</b> photographs the entire sky every six months, in 102 colours of infrared light.</li>
          <li>You pick a spot. SkyShift asks NASA's archive (IRSA) for <b>every</b> SPHEREx picture of it. That's often 100 to 500 snapshots.</li>
          <li>We cut out the same small square from each one, <b>line them up</b> (north up), remove the sky glow, and stack each visit into one clean picture.</li>
          <li>Press play: the pictures flip like a <b>flipbook</b>. Things that move jump; things that change brightness blink.</li>
          <li><b>Find things that moved</b> compares the visits, measures how fast and which way things move, then checks them against the <b>Gaia</b>, <b>2MASS</b>, <b>WISE</b> and <b>SIMBAD</b> catalogues and known asteroids.</li>
        </ol>
        <p>This is exactly how Pluto was discovered in 1930, and how volunteers on projects like <a href="https://backyardworlds.org" target="_blank" rel="noreferrer">Backyard Worlds</a> have found hundreds of brown dwarfs.</p>
      </section>

      <section className="card" id="about-challenge">
        <h2>How SkyShift answers the NASA challenge</h2>
        <p>Every requirement of the SPHEREx challenge, and where to try it. Each link opens SkyShift at the right place.</p>
        <div className="tableScroll">
          <table className="features reqTable">
            <thead><tr><th></th><th>The challenge asks for</th><th>SkyShift</th><th></th></tr></thead>
            <tbody>{CHALLENGE.map(([kind, need, how, link]) => (
              <tr key={need}><td><span className={`pill ${kind === "Must have" ? "must" : ""}`}>{kind}</span></td><td><b>{need}</b></td><td>{how}</td>
                <td><a href={link}>Try it →</a></td></tr>
            ))}</tbody>
          </table>
        </div>
      </section>

      <Accuracy />

      <section className="card" id="about-who">
        <h2>Who SkyShift helps</h2>
        <div className="audGrid">
          {AUDIENCES.map(([who, what, link]) => (
            <a key={who} className="aud" href={link}><b>{who}</b><span>{what}</span></a>
          ))}
        </div>
      </section>

      <section className="card" id="about-teach">
        <h2>Three classroom activities (10 minutes each)</h2>
        <ol className="how">
          {ACTIVITIES.map(([title, text, link]) => <li key={title}><b>{title}.</b> {text} <a href={link}>Open it →</a></li>)}
        </ol>
      </section>

      <section className="card" id="about-updates">
        <h2>Always up to date</h2>
        <p>NASA adds SPHEREx pictures every week and publishes new data releases, but it doesn't notify anyone. So SkyShift asks NASA's archive every few hours: if a new release or new pictures of a spot you've opened appear, it downloads them in the background, rebuilds that spot, and the page shows <b>"NASA added data"</b>. The newest Gaia release is picked up the same way.</p>
      </section>

      <section className="card">
        <h2>How can infrared pictures have colours?</h2>
        <p>Our eyes can't see infrared, so every infrared picture is <b>false colour</b>: we choose which visible colour stands for which infrared wavelength.</p>
        <ul>
          <li><b>RGB grading</b> (the flipbook): longest infrared (3.8–5 µm) → red, middle (1.6–3.8 µm) → green, shortest (0.75–1.6 µm) → blue. Cool, dusty things look red; hot stars look blue-white.</li>
          <li><b>The all-sky map</b>: SkyShift picks the colours where particular things glow. <span style={{ color: "#ffa36b" }}>Dust</span> made of organic molecules shines at 3.29 µm (orange), <span style={{ color: "#7fe8ff" }}>hot hydrogen gas</span> at 4.05 µm (cyan, with starlight subtracted), and stars at 1–1.6 µm (white). The pieces come from NASA's SPHEREx all-sky map (IRSA), mixed on our server.</li>
        </ul>
        <img src="/spherex_allsky.jpg" alt="SPHEREx all-sky false-colour map" style={{ width: "100%", borderRadius: 12 }} />
      </section>
      <section className="card">
        <h2>Words you might see</h2>
        <dl className="gloss">{Object.entries(GLOSSARY).map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}</dl>
      </section>
      <section className="card">
        <h2>For scientists and developers</h2>
        <p>Switch on <b>Expert</b> (top right) for every detector, all 102 colour planes, single snapshots, spectra and light curves, contamination flags, and data-release selection.
          Every view has a shareable URL (<code>?ra=…&amp;dec=…&amp;fov=…</code>) and <code>&amp;embed=1</code> gives a bare player for other websites. The REST API is documented at <a href="/docs">/docs</a>.</p>
        <p className="small muted">Data: NASA/IPAC Infrared Science Archive (SPHEREx, 2MASS, AllWISE) · ESA Gaia DR3 · CDS SIMBAD, Sesame &amp; Aladin Lite · NASA Exoplanet Archive · IMCCE SkyBoT · astropy. Built for the NASA Space Apps Challenge 2026.</p>
      </section>
    </div>
  );
}
