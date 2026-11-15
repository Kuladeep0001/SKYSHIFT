/* App shell: header, Simple/Expert switch, page routing. Owner: UI 1. */
import { useEffect, useState } from "react";
import { api } from "./lib/api.js";
import About from "./pages/About.jsx";
import Board from "./pages/Board.jsx";
import Explorer from "./pages/Explorer.jsx";
import TaskBar from "./components/TaskBar.jsx";
import Intro from "./components/Intro.jsx";

const params = new URLSearchParams(location.search);
const embed = params.get("embed") === "1" || location.pathname.endsWith("/embed");

function readExpert() {
  if (params.get("expert") === "1") return true;
  try { return localStorage.getItem("skyshift-expert") === "1"; } catch (_) { return false; }
}

export default function App() {
  const [expert, setExpert] = useState(readExpert);
  const pageOf = () => (location.hash.startsWith("#about") ? "about" : location.hash === "#board" ? "board" : "explore");
  const [page, setPage] = useState(pageOf);
  const [tourStep, setTourStep] = useState(params.get("tour") === "1" ? 0 : null);
  const [listen, setListen] = useState(params.get("listen") === "1");
  const [begun, setBegun] = useState(false);

  useEffect(() => {
    try { localStorage.setItem("skyshift-expert", expert ? "1" : "0"); } catch (_) { /* private mode */ }
  }, [expert]);
  useEffect(() => {
    const h = () => setPage(pageOf());
    window.addEventListener("hashchange", h);
    return () => window.removeEventListener("hashchange", h);
  }, []);

  if (embed) return <div className="app embed"><Explorer expert={expert} embed listenMode={listen} /></div>;
  if (!begun) return <Intro onBegin={() => setBegun(true)} />;
  return (
    <div className="app">
      <header className="top">
        <a className="brand" href="./" onClick={(e) => { if (page === "about") { e.preventDefault(); location.hash = ""; } }}>
          <img className="brandMark" src="/logo-mark.png" alt="" aria-hidden="true" />
          <span className="brandText">
            <img className="brandWord" src="/logo-word.png" alt="SkyShift" />
            <span className="brandTag">Explore · Identify · Understand</span>
          </span>
        </a>
        <nav>
          <a href="#" className={page === "explore" ? "on" : ""} onClick={(e) => { e.preventDefault(); location.hash = ""; }}>Explore</a>
          <a href="#board" className={page === "board" ? "on" : ""}>Discovery board</a>
          <a href="#about" className={page === "about" ? "on" : ""}>How it works</a>
          <a href="#" onClick={(e) => { e.preventDefault(); location.hash = ""; setTourStep(0); }}>Tour</a>
        </nav>
        <button className={`listenToggle ${listen ? "on" : ""}`} onClick={() => setListen(!listen)} aria-pressed={listen}
          title="Listen mode: opens the Listen tab, where the brightness graph and the motion are played as sound, and reads answers aloud (for blind and low-vision visitors)">Listen mode</button>
        <div className="modeSwitch" role="group" aria-label="Simple or expert mode">
          <button className={!expert ? "on" : ""} onClick={() => setExpert(false)} title="Plain-English view for everyone">Simple</button>
          <button className={expert ? "on" : ""} onClick={() => setExpert(true)} title="All the science tools">Expert</button>
        </div>
      </header>
      {api.mock && <div className="mockBanner">Mock mode: showing saved sample data (no backend needed)</div>}
      <main style={{ display: page === "explore" ? "block" : "none" }}><Explorer expert={expert} listenMode={listen} tourStep={tourStep} setTourStep={setTourStep} /></main>
      {page === "about" && <main><About /></main>}
      {page === "board" && <main><Board /></main>}
      {page !== "explore" && <TaskBar />}
      <footer className="foot">
        Real data from NASA's SPHEREx (via IRSA), ESA Gaia and NASA WISE. Built for the NASA Space Apps Challenge 2026 ·{" "}
        <a href="https://github.com/Kuladeep0001/SKYSHIFT" target="_blank" rel="noreferrer">GitHub</a> · <a href="/docs">API</a>
      </footer>
    </div>
  );
}
