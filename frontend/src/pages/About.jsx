/* "How it works" for everyone, plus credits. Owner: UI 1. */
import { GLOSSARY } from "../lib/targets.js";

export default function About() {
  return (
    <div className="about">
      <section className="card">
        <h1>How SkyShift works</h1>
        <ol className="how">
          <li><b>NASA's SPHEREx telescope</b> photographs the entire sky every six months, in 102 colours of infrared light.</li>
          <li>You pick a spot. SkyShift asks NASA's archive (IRSA) for <b>every</b> SPHEREx picture of it. That's often 100 to 400 snapshots.</li>
          <li>We cut out the same small square from each one, <b>line them up</b> (north up), remove the sky glow, and stack each visit into one clean picture.</li>
          <li>Press play: the pictures flip like a <b>flipbook</b>. Things that move jump; things that change brightness blink.</li>
          <li><b>Find things that moved</b> subtracts an old visit from a new one, points out what changed, then checks it against the <b>Gaia</b> and <b>WISE</b> telescopes and known asteroids.</li>
        </ol>
        <p>This is exactly how Pluto was discovered in 1930, and how volunteers on projects like <a href="https://backyardworlds.org" target="_blank" rel="noreferrer">Backyard Worlds</a> have found hundreds of brown dwarfs.</p>
      </section>
      <section className="card">
        <h2>How can infrared pictures have colours?</h2>
        <p>Our eyes can't see infrared, so every infrared picture is <b>false colour</b>: we choose which visible colour stands for which infrared wavelength.</p>
        <ul>
          <li><b>RGB grading</b> (the flipbook): longest infrared (3.8–5 µm) → red, middle (1.6–3.8 µm) → green, shortest (0.75–1.6 µm) → blue. Cool, dusty things look red; hot stars look blue-white.</li>
          <li><b>The all-sky picture</b>: SkyShift picks the colours where particular things glow. <span style={{ color: "#ffa36b" }}>Dust</span> made of organic molecules shines at 3.29 µm (orange), <span style={{ color: "#7fe8ff" }}>hot hydrogen gas</span> at 4.05 µm (cyan, with starlight subtracted), and stars at 1–1.6 µm (white). The pieces come from NASA's SPHEREx all-sky map (IRSA), mixed on our server.</li>
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
        <p className="small muted">Data: NASA/IPAC Infrared Science Archive (SPHEREx) · ESA Gaia DR3 · NASA WISE/AllWISE · IMCCE SkyBoT · CDS Sesame &amp; Aladin Lite · astropy. Built for the NASA Space Apps Challenge 2026.</p>
      </section>
    </div>
  );
}
