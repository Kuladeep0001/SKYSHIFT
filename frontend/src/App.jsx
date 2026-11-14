/* App shell: header, Simple/Expert switch, page routing. Owner: UI 1. */
import { useEffect, useState } from "react";
import { api } from "./lib/api.js";
import About from "./pages/About.jsx";
import Explorer from "./pages/Explorer.jsx";

const params = new URLSearchParams(location.search);
const embed = params.get("embed") === "1" || location.pathname.endsWith("/embed");

function readExpert() {
  if (params.get("expert") === "1") return true;
  try { return localStorage.getItem("skyshift-expert") === "1"; } catch (_) { return false; }
}

export default function App() {
  const [expert, setExpert] = useState(readExpert);
  const [page, setPage] = useState(location.hash === "#about" ? "about" : "explore");

  useEffect(() => {
    try { localStorage.setItem("skyshift-expert", expert ? "1" : "0"); } catch (_) { /* private mode */ }
  }, [expert]);
  useEffect(() => {
    const h = () => setPage(location.hash === "#about" ? "about" : "explore");
    window.addEventListener("hashchange", h);
    return () => window.removeEventListener("hashchange", h);
  }, []);

  if (embed) return <div className="app embed"><Explorer expert={expert} embed /></div>;
  return (
    <div className="app">
      <header className="top">
        <a className="brand" href="./" onClick={(e) => { if (page === "about") { e.preventDefault(); location.hash = ""; } }}>
          <svg viewBox="0 0 32 32" aria-hidden="true"><circle cx="16" cy="16" r="15" fill="#0b1426" stroke="#26385c" /><circle cx="11" cy="18" r="3" fill="#53d8c4" opacity=".45" /><circle cx="20" cy="13" r="4" fill="#ffb547" /></svg>
          <span>Sky<b>Shift</b></span>
        </a>
        <span className="tagline">Watch the infrared sky move · NASA SPHEREx</span>
        <nav>
          <a href="#" className={page === "explore" ? "on" : ""} onClick={(e) => { e.preventDefault(); location.hash = ""; }}>Explore</a>
          <a href="#about" className={page === "about" ? "on" : ""}>How it works</a>
        </nav>
        <div className="modeSwitch" role="group" aria-label="Simple or expert mode">
          <button className={!expert ? "on" : ""} onClick={() => setExpert(false)} title="Plain-English view for everyone">Simple</button>
          <button className={expert ? "on" : ""} onClick={() => setExpert(true)} title="All the science tools">Expert</button>
        </div>
      </header>
      {api.mock && <div className="mockBanner">Mock mode: showing saved sample data (no backend needed)</div>}
      <main style={{ display: page === "about" ? "none" : "block" }}><Explorer expert={expert} /></main>
      {page === "about" && <main><About /></main>}
      <footer className="foot">
        Real data from NASA's SPHEREx (via IRSA), ESA Gaia and NASA WISE. Built for the NASA Space Apps Challenge 2026 ·{" "}
        <a href="https://github.com/Kuladeep0001/SKYSHIFT" target="_blank" rel="noreferrer">GitHub</a> · <a href="/docs">API</a>
      </footer>
    </div>
  );
}
