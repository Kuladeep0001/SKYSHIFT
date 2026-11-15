/* Main dashboard: search, the picture, playback, explanations, and (in expert mode) science tools.
 * Owner: UI 1 (layout and state). Components are owned by UI 2.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import BeforeAfter from "../components/BeforeAfter.jsx";
import CandidatesPanel from "../components/CandidatesPanel.jsx";
import Controls from "../components/Controls.jsx";
import CoordinateInput from "../components/CoordinateInput.jsx";
import DetectorWall, { wallVisitCount } from "../components/DetectorWall.jsx";
import DisplaySettings from "../components/DisplaySettings.jsx";
import Explainer from "../components/Explainer.jsx";
import ImageViewer from "../components/ImageViewer.jsx";
import Listen from "../components/Listen.jsx";
import ObjectCard from "../components/ObjectCard.jsx";
import CatalogueCheck from "../components/CatalogueCheck.jsx";
import ReportCard from "../components/ReportCard.jsx";
import SkyHome from "../components/SkyHome.jsx";
import TimeColours from "../components/TimeColours.jsx";
import MetadataPanel from "../components/MetadataPanel.jsx";
import SpectralCube from "../components/SpectralCube.jsx";
import SkyMap from "../components/SkyMap.jsx";
import SpectrumPanel from "../components/SpectrumPanel.jsx";
import TaskBar from "../components/TaskBar.jsx";
import AskPanel from "../components/AskPanel.jsx";
import AsteroidHunter from "../components/AsteroidHunter.jsx";
import TimeMachine from "../components/TimeMachine.jsx";
import Tour, { TOUR } from "../components/Tour.jsx";
import Timeline from "../components/Timeline.jsx";
import { api, loadImages } from "../lib/api.js";
import { decodeFrames, mainVisitsOnly } from "../lib/frames.js";
import { rgbByVisit } from "../lib/render.js";
import { spherexCredit } from "../lib/sources.js";
import { findTarget, TARGETS } from "../lib/targets.js";

const params = new URLSearchParams(location.search);
const FACTS = [
  "SPHEREx photographs the entire sky every 6 months in 102 infrared colours.",
  "Pluto was discovered in 1930 by comparing two photos taken days apart, just like this.",
  "Volunteers comparing images like these have discovered hundreds of brown dwarfs.",
  "Infrared light passes through dust, so SPHEREx sees things hidden from ordinary telescopes.",
  "Barnard's Star moves the width of the full Moon across the sky in about 180 years.",
];

export default function Explorer({ expert, embed, listenMode, tourStep, setTourStep }) {
  const simple = !expert;
  const [target, setTarget] = useState(null);
  const [fov, setFov] = useState(+params.get("fov") || 6);
  const [release, setRelease] = useState(params.get("rel") || "");
  const [releases, setReleases] = useState(null);
  const [load, setLoad] = useState({ phase: "idle" });
  const [qid, setQid] = useState(null);
  const [meta, setMeta] = useState(null);
  const VIEWS = ["blink", "timecolours", "compare", "timemachine", "wall", "planes", "asteroids", "listen"];
  const [view, setView] = useState(VIEWS.includes(params.get("view")) ? params.get("view") : "blink");
  const [mode, setMode] = useState(params.get("mode") || "visit");
  const [det, setDet] = useState(+params.get("det") || 0);
  const [ch, setCh] = useState(+params.get("ch") || 40);
  const [F, setF] = useState(null);
  const [wallF, setWallF] = useState(null);
  const [idx, setIdx] = useState(0);
  const [playing, setPlaying] = useState(true);
  const [zoom, setZoom] = useState(+params.get("zoom") || 1);        // flipbook zoom on the object
  const [blinkPair, setBlinkPair] = useState(false);                  // blink only the first and last visit
  const [fps, setFps] = useState(1.5);
  const [disp, setDisp] = useState({ contrast: 0.55, bright: 0.5, cmap: "rgb", math: params.get("math") || "none" });
  const [ov, setOv] = useState({ gaia: true, wise: false, ast: false, flags: false, cross: true, path: true });
  const [cats, setCats] = useState({});
  const [asteroids, setAsteroids] = useState({});
  const [sel, setSel] = useState(null);
  const [spec, setSpec] = useState(null);
  const [specLoading, setSpecLoading] = useState(false);
  const [candidates, setCandidates] = useState(null);
  const [focus, setFocus] = useState(null);
  const [toast, setToast] = useState("");
  const [objPos, setObjPos] = useState(null);
  const [objPm, setObjPm] = useState(null);         // known motion of the selected object (mas/yr), for the catalogue check
  const [details, setDetails] = useState(null);     // details card data (for the assistant and share card)
  const [checks, setChecks] = useState({});         // verification results of found candidates
  const [tmTask, setTmTask] = useState(null);       // time-machine download task (for the task bar)
  const [detectSignal, setDetectSignal] = useState(0);
  const [tourAuto, setTourAuto] = useState(false);
  const [fresh, setFresh] = useState(null);        // freshness info from the server
  const [dataVersion, setDataVersion] = useState(0); // version of the data currently on screen
  const [newData, setNewData] = useState(null);     // set when the server has a newer version
  const loadingId = useRef(null);
  const loadStart = useRef(0);
  const [fact, setFact] = useState(0);
  const token = useRef(0);
  const firstRun = useRef(true);
  const astPending = useRef(new Set());
  const story = target ? findTarget(target.query || target.name) : null;

  const say = (m) => { setToast(m); setTimeout(() => setToast(""), 2600); };

  // Simple mode only has the flipbook and before/after views.
  useEffect(() => { if (simple && !["blink", "compare", "timecolours", "planes", "timemachine", "asteroids", "listen"].includes(view)) setView("blink"); if (simple) setMode("visit"); }, [simple]);
  // Listen mode (header button) opens the Listen tab, made for blind and low-vision visitors.
  useEffect(() => { if (listenMode) setView("listen"); }, [listenMode]);

  /* ---------------------------------------------------------- loading */
  const startLoad = useCallback(async (t, fovNow, rel) => {
    const my = ++token.current;
    setLoad({ phase: "loading", done: 0, total: 0, message: "Asking NASA which SPHEREx pictures cover this spot…" });
    loadingId.current = null; loadStart.current = Date.now(); setNewData(null); setFresh(null);
    setQid(null); setMeta(null); setF(null); setWallF(null);
    setSel(null); setSpec(null); setCandidates(null); setFocus(null); setCats({}); setAsteroids({}); setObjPos(null); setDetails(null); setChecks({});
    astPending.current = new Set();
    const rad = (fovNow / 60) * 0.75 + 0.01;
    for (const name of ["gaia", "allwise"]) {
      api.catalog(name, t.ra, t.dec, rad).then((c) => token.current === my && setCats((x) => ({ ...x, [name]: c }))).catch(() => {});
    }
    try {
      const st = await loadImages({ ra: t.ra, dec: t.dec, fov: fovNow, release: rel },
        (p) => { if (token.current === my) { loadingId.current = p.query_id; setLoad({ phase: "loading", done: p.progress.done, total: p.progress.total, message: p.message }); } },
        () => token.current !== my);
      if (!st || token.current !== my) return;
      setFresh(st.freshness || null); setDataVersion(st.freshness?.version || 0);
      const m = await api.metadata(st.query_id);
      if (token.current !== my) return;
      setMeta(m); setQid(st.query_id); setLoad({ phase: "ready" });
      const mid = m.exposures.length ? m.exposures[m.exposures.length >> 1].mjd : 0;
      setObjPos({ ra: t.ra, dec: t.dec, mjd: mid, name: findTarget(t.query || t.name) ? t.name : null });
      setObjPm(Number.isFinite(t.pmra) && Number.isFinite(t.pmdec) ? { pmra: t.pmra, pmdec: t.pmdec } : null);
      const c = (m.n_pix - 1) >> 1;  // start with the spectrum of whatever is in the middle
      api.spectrum(st.query_id, c, c).then((sp) => token.current === my && setSpec(sp)).catch(() => {});
      if (st.progress.failed) say(`${st.progress.failed} pictures couldn't be downloaded and were skipped.`);
    } catch (e) {
      if (token.current === my) setLoad({ phase: "error", message: e.message });
    }
  }, []);

  const go = useCallback(async (text) => {
    try {
      setLoad({ phase: "loading", done: 0, total: 0, message: `Looking up "${text}"…` });
      const r = await api.resolve(text);
      const t = { ...r, query: r.name ? text : null, name: r.name ? r.name.replace(/^NAME /, "") : null };
      setTarget(t);
      const s = findTarget(t.query || t.name);
      if (s && !expert) setDet(s.band);
      setZoom(Math.hypot(r.pmra || 0, r.pmdec || 0) > 300 ? 3 : 1);
      startLoad(t, fov, release);
    } catch (e) {
      setLoad({ phase: "error", message: e.message });
    }
  }, [fov, release, expert, startLoad]);

  const goCoords = (ra, dec, f = fov) => {
    const t = { ra, dec, name: null, query: null };
    setTarget(t);
    setZoom(1);
    if (f !== fov) { firstRun.current = true; setFov(f); }
    startLoad(t, f, release);
  };

  // boot: releases + URL
  useEffect(() => {
    api.releases().then(setReleases).catch(() => {});
    const ra = parseFloat(params.get("ra")), dec = parseFloat(params.get("dec"));
    if (params.get("q")) go(params.get("q"));   // a name: look it up again so we also know how it moves
    else if (Number.isFinite(ra) && Number.isFinite(dec)) {
      const t = { ra, dec, name: null, query: null };
      setTarget(t);
      startLoad(t, fov, release);
    }
  }, []);

  // reload if area or release changes after a target is loaded
  useEffect(() => {
    if (firstRun.current) { firstRun.current = false; return; }
    if (target) { const h = setTimeout(() => startLoad(target, fov, release), 600); return () => clearTimeout(h); }
  }, [fov, release]);

  // rotate fun facts while loading
  useEffect(() => {
    if (load.phase !== "loading") return;
    const h = setInterval(() => setFact((f) => (f + 1) % FACTS.length), 6000);
    return () => clearInterval(h);
  }, [load.phase]);

  /* ----------------------------------------------------------- frames */
  useEffect(() => {
    if (!qid) return;
    let alive = true;
    (async () => {
      try {
        if (view === "blink" || view === "compare" || view === "timecolours" || view === "listen") {
          const m = view === "blink" ? mode : "visit";
          const res = await api.frames(qid, { mode: m, det: m === "channel" ? 0 : det, channel: m === "channel" ? ch : 0 });
          if (!alive) return;
          let dec = decodeFrames(res);
          if (simple || view !== "blink") dec = mainVisitsOnly(dec); // the clean twice-a-year visits
          setF(dec); setIdx(0);
          if (!dec.data.length) say(m === "channel" ? `No snapshot caught this spot in colour plane ${ch}. Try a neighbouring one.` : "No pictures for this choice.");
          // RGB colour grading needs every detector of every visit
          if (disp.cmap === "rgb" && !wallF && view !== "timecolours" && view !== "listen") {
            const all = await api.frames(qid, { mode: "visitdet" });
            if (alive) setWallF(decodeFrames(all));
          }
        } else if (view === "wall") {
          if (!wallF) { const res = await api.frames(qid, { mode: "visitdet" }); if (alive) setWallF(decodeFrames(res)); }
          setIdx(0);
        }
      } catch (e) { say(e.message); }
    })();
    return () => { alive = false; };
  }, [qid, view, mode, det, ch, simple, dataVersion, disp.cmap]);
  const rgbSets = useMemo(() => (disp.cmap === "rgb" ? rgbByVisit(wallF) : null), [wallF, disp.cmap]);
  const useRGB = disp.cmap === "rgb" && det === 0 && F?.mode === "visit" && rgbSets && Object.keys(rgbSets).length > 0;

  const count = view === "wall" ? wallVisitCount(wallF) : F ? F.data.length : 0;

  // play loop
  useEffect(() => {
    if (!playing || !count || ["planes", "compare", "timecolours", "listen"].includes(view) || disp.math === "sum") return;
    const h = setInterval(() => setIdx((i) => (blinkPair ? (i === 0 ? count - 1 : 0) : (i + 1) % count)), 1000 / fps);
    return () => clearInterval(h);
  }, [playing, fps, count, view, disp.math, blinkPair]);

  // keyboard: space / arrows
  useEffect(() => {
    if (view === "listen") return;          // the Listen tab has its own keys
    const k = (e) => {
      if (e.target.tagName === "INPUT" && e.target.type === "text") return;
      if (e.code === "Space") { e.preventDefault(); setPlaying((p) => !p); }
      if (e.code === "ArrowRight" && count) setIdx((i) => (i + 1) % count);
      if (e.code === "ArrowLeft" && count) setIdx((i) => (i - 1 + count) % count);
    };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [count, view]);

  // keep the URL in sync so any view can be shared or embedded
  useEffect(() => {
    if (!target) return;
    const p = new URLSearchParams();
    if (target.query) p.set("q", target.query);
    p.set("ra", target.ra.toFixed(5)); p.set("dec", target.dec.toFixed(5)); p.set("fov", fov);
    if (release) p.set("rel", release);
    if (view !== "blink") p.set("view", view);
    if (mode !== "visit") p.set("mode", mode);
    if (det) p.set("det", det);
    if (mode === "channel") p.set("ch", ch);
    if (disp.math !== "none") p.set("math", disp.math);
    if (zoom > 1) p.set("zoom", zoom);
    if (expert) p.set("expert", "1");
    if (embed) p.set("embed", "1");
    history.replaceState(null, "", `${location.pathname}?${p}${location.hash}`);
  }, [target, fov, release, view, mode, det, ch, disp.math, expert, embed, zoom]);

  /* --------------------------------------------------------- guided tour */
  const tour = tourStep != null ? TOUR[tourStep] : null;
  const tourReady = !!tour && load.phase === "ready" && (!tour.q || target?.query === tour.q);
  useEffect(() => {
    if (!tour) return;
    if (tour.q && target?.query !== tour.q) go(tour.q);
  }, [tourStep]);
  useEffect(() => {
    if (!tourReady) return;
    if (tour.view) setView(tour.view);
    if (tour.det !== undefined) setDet(tour.det);
    if (tour.math) setDisp((d) => ({ ...d, math: tour.math }));
    if (tour.action === "detect") setDetectSignal((x) => x + 1);
  }, [tourReady, tourStep]);

  /* ------------------------------------------- cancel / stay up to date */
  const cancelLoad = async () => {
    const id = loadingId.current;
    token.current++;                       // stop listening to this download
    setLoad({ phase: "idle" });
    setTarget(null);
    if (id) { try { await api.cancel(id); } catch (_) { /* already finished */ } }
    say("Download cancelled. Pictures fetched so far are kept, so trying again will be faster.");
  };

  // While a spot is open, ask the server every 2 minutes whether NASA added pictures for it.
  useEffect(() => {
    if (!qid) return;
    const poll = async () => {
      try {
        const st = await api.imageStatus(qid);
        if (!st.freshness) return;
        setFresh(st.freshness);
        if (st.freshness.version > dataVersion) setNewData(st.freshness.last_update || {});
      } catch (_) { /* offline: try again later */ }
    };
    const h = setInterval(poll, fresh?.refreshing ? 4000 : 120000);
    return () => clearInterval(h);
  }, [qid, dataVersion, fresh?.refreshing]);

  const checkNow = async () => {
    try {
      const r = await api.checkNow(qid);
      setFresh(r.freshness);
      if (r.result.changed) say(`NASA has ${r.result.new_exposures} new pictures of this spot. Updating…`);
      else say(r.result.checked ? "Checked NASA just now: you already have the latest pictures." : `Already ${r.result.reason}.`);
    } catch (e) { say(e.message); }
  };
  const showNewData = async () => {
    const m = await api.metadata(qid);
    setMeta(m); setWallF(null); setCandidates(null);
    setDataVersion(m.status.freshness.version); setFresh(m.status.freshness); setNewData(null);
  };
  const tasks = [];
  if (load.phase === "loading") tasks.push({ id: "load", label: `Fetching ${target?.name || "this spot"} from NASA`, detail: load.message,
    done: load.done, total: load.total, startedAt: loadStart.current, onCancel: cancelLoad });
  if (tmTask) tasks.push(tmTask);
  if (fresh?.refreshing) tasks.push({ id: "refresh", kind: "update", label: "New SPHEREx pictures found: updating this spot",
    done: fresh.refresh_progress?.done || 0, total: fresh.refresh_progress?.total || 0,
    onCancel: () => api.cancel(qid).then(() => say("Update cancelled.")).catch(() => {}) });

  /* ---------------------------------------------------------- spectrum */
  // A click lands near a star, not always on it: move to the brightest pixel close by, so the spectrum
  // and the catalogue search are about that object (not the dark sky next to it).
  const snapToStar = (x, y) => {
    if (!F || !F.data.length) return [x, y];
    const a = F.data[Math.min(idx, F.data.length - 1)], n = F.n;
    let best = -Infinity, bx = x, by = y;
    for (let yy = y - 2; yy <= y + 2; yy++) for (let xx = x - 2; xx <= x + 2; xx++) {
      if (xx < 0 || yy < 0 || xx >= n || yy >= n) continue;
      const v = a[yy * n + xx];
      if (Number.isFinite(v) && v > best) { best = v; bx = xx; by = yy; }
    }
    return [bx, by];
  };
  const onPixel = async (x0, y0, opts = {}) => {
    if (!qid) return;
    const [x, y] = opts.exact ? [x0, y0] : snapToStar(x0, y0);
    setSel({ x, y });
    setObjPm(null);
    setSpecLoading(true);
    try {
      const sp = await api.spectrum(qid, x, y);
      setSpec(sp);
      const mid = meta?.exposures?.length ? meta.exposures[meta.exposures.length >> 1].mjd : 0;
      setObjPos({ ra: sp.ra, dec: sp.dec, mjd: mid, name: null, clicked: true });
    } catch (e) { say(e.message); } finally { setSpecLoading(false); }
  };
  const backToTarget = () => {
    if (!target) return;
    setSel(null);
    const mid = meta?.exposures?.length ? meta.exposures[meta.exposures.length >> 1].mjd : 0;
    setObjPos({ ra: target.ra, dec: target.dec, mjd: mid, name: story ? target.name : null });
    setObjPm(Number.isFinite(target.pmra) && Number.isFinite(target.pmdec) ? { pmra: target.pmra, pmdec: target.pmdec } : null);
    const c = (meta.n_pix - 1) >> 1;
    api.spectrum(qid, c, c).then(setSpec).catch(() => {});
  };
  const frame = F && F.list[Math.min(idx, F.data.length - 1)];
  const selFlags = useMemo(() => {
    if (!spec || !frame || !frame.members) return null;
    const p = spec.points.find((q) => frame.members.includes(q.i));
    return p ? p.flags : [...new Set(spec.points.flatMap((q) => q.flags))];
  }, [spec, frame]);

  const needAsteroids = (mjd) => {
    const key = mjd.toFixed(3);
    if (astPending.current.has(key)) return;
    astPending.current.add(key);
    api.catalog("skybot", target.ra, target.dec, (fov / 60) * 0.75, mjd)
      .then((r) => setAsteroids((a) => ({ ...a, [key]: r })))
      .catch(() => setAsteroids((a) => ({ ...a, [key]: { objects: [] } })));
  };

  const focusCand = (id) => {
    setFocus(id);
    const c = (candidates || []).find((x) => x.candidate_id === id);
    if (c) {
      onPixel(Math.round(c.x), Math.round(c.y), { exact: true });
      const m = c.kind === "mover" && c.motion;
      setObjPm(m && Number.isFinite(m.pmra_mas_yr) ? { pmra: m.pmra_mas_yr, pmdec: m.pmdec_mas_yr } : null);
    }
  };

  /* ------------------------------------------------------------ share */
  const shareURL = (forEmbed) => {
    const u = new URL(location.href);
    if (forEmbed) u.searchParams.set("embed", "1"); else u.searchParams.delete("embed");
    return u.toString();
  };
  const copy = (txt, msg) => navigator.clipboard.writeText(txt).then(() => say(msg)).catch(() => say(txt));
  const savePng = () => {
    const c = document.querySelector(".stage canvas");
    if (!c) return;
    const a = document.createElement("a");
    a.download = `skyshift_${(target?.name || "sky").replace(/\W+/g, "_")}_${idx + 1}.png`;
    a.href = c.toDataURL("image/png");
    a.click();
  };

  /* ------------------------------------- facts for sharing and the assistant */
  const moverFind = (candidates || []).find((c) => c.kind === "mover");
  const moverCheck = moverFind && checks[moverFind.candidate_id];
  const shareFacts = [];
  if (meta?.visits?.length) shareFacts.push(`Photographed in ${meta.visits.length} visits by NASA SPHEREx, ${meta.visits[0].start.slice(0, 7)} – ${meta.visits[meta.visits.length - 1].end.slice(0, 7)}`);
  if (moverFind) shareFacts.push(`Measured moving ${moverFind.motion.total_arcsec_yr.toFixed(2)}″ per year${moverCheck?.verification_status === "known_mover" ? " (confirmed by catalogues)" : ""}`);
  const distLy = details?.simbad?.distance_ly || details?.gaia?.distance_ly;
  if (distLy) shareFacts.push(`About ${distLy < 1000 ? distLy.toFixed(1) : Math.round(distLy).toLocaleString()} light-years away`);
  const seenFeats = (spec?.features || []).filter((f) => f.status === "likely" || f.status === "possible");
  if (seenFeats.length) shareFacts.push(`Spectrum hints: ${[...new Set(seenFeats.map((f) => f.species))].slice(0, 3).join(", ")}`);
  const askContext = {
    name: target?.name || "this spot", ra: target?.ra, dec: target?.dec, story: story?.story,
    pm_arcsec_yr: target ? Math.hypot(target.pmra || 0, target.pmdec || 0) / 1000 || null : null,
    details: details ? { summary: details.summary, distance_ly: distLy || null, type: details.simbad?.type,
      spectral_type: details.simbad?.spectral_type, wikipedia: details.wikipedia?.extract?.slice(0, 900) } : null,
    features: seenFeats.map((f) => ({ name: f.name, status: f.status, change_pct: f.change_pct, plain_english: f.plain_english })),
    finds: (candidates || []).slice(0, 6).map((c) => ({ kind: c.kind, plain_english: c.plain_english, verification: checks[c.candidate_id]?.plain_english || "" })),
    visits: meta?.visits || [], view,
  };

  /* ------------------------------------------------------------ render */
  const ready = load.phase === "ready" && meta;
  const source = spherexCredit(fresh?.last_update?.releases || meta?.status?.releases);
  // details card + catalogue/exoplanet check + spectrum, for the target or the clicked object
  const objectPanels = meta && (
    <>
      <ObjectCard pos={objPos} simple={simple} onLoaded={setDetails} />
      <CatalogueCheck pos={objPos} pm={objPm} simple={simple} auto={!!objPos?.clicked}
        label={objPos?.name || details?.simbad?.name || (objPos && target && Math.hypot(objPos.ra - target.ra, objPos.dec - target.dec) < 2e-3 ? target.name : null)} />
      <SpectrumPanel spec={spec} visits={meta.visits} detectors={meta.detectors} loading={specLoading} simple={simple} source={source} />
    </>
  );
  const chInfo = meta && meta.channels[ch - 1];
  const chWave = chInfo && chInfo.wave ? `${chInfo.wave[0].toFixed(2)}–${chInfo.wave[1].toFixed(2)} µm` : "";
  const tabs = simple
    ? [["blink", "Flipbook"], ["timecolours", "Colour by date"], ["compare", "Before / after"], ["timemachine", "Time machine"], ["planes", "102 colours"], ["asteroids", "Asteroids"], ["listen", "Listen"]]
    : [["blink", "Blink"], ["timecolours", "Colour by date"], ["compare", "Before / after"], ["timemachine", "Time machine"], ["wall", "6 Detectors"], ["planes", "Spectral cube (102)"], ["asteroids", "Asteroids"], ["listen", "Listen"]];

  return (
    <div className="explorer">
      {!embed && (
        <CoordinateInput initial={params.get("q") || ""} onGo={go} fov={fov} setFov={setFov} release={release}
          setRelease={setRelease} releases={releases} expert={expert} busy={load.phase === "loading"} />
      )}

      {load.phase === "idle" && !embed && (
        <section className="welcome">
          <SkyHome fovDefault={fov} onPick={(p) => (p.q ? go(p.q) : goCoords(p.ra, p.dec, p.fov))} />
          <h1>Watch the sky <span className="hl">move</span>.</h1>
          <p className="lead">NASA's <b>SPHEREx</b> telescope photographs the whole sky every six months. SkyShift lines up its pictures of any spot and plays them like a <b>flipbook</b>, so anything that moves or changes brightness jumps out. That's how Pluto was found!</p>
          <ol className="steps">
            <li><span>1</span>Pick a star (or type any sky coordinates)</li>
            <li><span>2</span>We fetch every SPHEREx picture of that spot</li>
            <li><span>3</span>Press play and spot what moves</li>
          </ol>
          <button className="primary tourBtn" onClick={() => setTourStep(0)}>Show me something amazing (guided tour)</button>
          <h2 className="center">…or start with one of the challenge's test targets</h2>
          <div className="cards">
            {TARGETS.map((t) => (
              <button key={t.id} className="tcard" onClick={() => go(t.q)}>
                <b>{t.label}</b>
                <span>{t.tagline}</span>
              </button>
            ))}
          </div>
        </section>
      )}

      {load.phase === "loading" && (
        <section className="progress card">
          <div className="bar"><i style={{ width: `${load.total ? Math.max(4, (100 * load.done) / load.total) : 3}%` }} /></div>
          <p>{load.total ? <>Fetching <b>{load.done}</b> of <b>{load.total}</b> pictures from NASA… The first time takes 1–3 minutes, then it's instant.</> : load.message}</p>
          <p className="fact">{FACTS[fact]}</p>
          <button onClick={cancelLoad} className="cancelBtn">✕ Cancel download</button>
        </section>
      )}
      {load.phase === "error" && <section className="progress card"><p className="err">{load.message}</p></section>}

      {ready && newData && (
        <div className="newData" role="status">
          NASA added data for this spot{newData.new_exposures ? `: ${newData.new_exposures} new pictures` : ""}
          {newData.new_releases?.length ? ` (new release ${newData.new_releases.join(", ").replace(/spherex_/g, "").toUpperCase()})` : ""}.
          <button className="primary" onClick={showNewData}>Show them</button>
        </div>
      )}
      {ready && (
        <div className={`layout ${embed ? "embedLayout" : ""}`}>
          <section className="stage card">
            {!embed && (
              <div className="tabs" role="tablist">
                {tabs.map(([k, label]) => <button key={k} role="tab" aria-selected={view === k} className={`${view === k ? "on" : ""} ${k === "listen" ? "listenTabBtn" : ""}`}
                  title={k === "listen" ? "For blind and low-vision visitors: hear the brightness graph and the motion" : undefined} onClick={() => setView(k)}>{label}</button>)}
              </div>
            )}

            {view === "blink" && (
              <div className="row">
                {expert && view === "blink" && (
                  <div className="seg" role="group" aria-label="How to build each picture">
                    {[["visit", "Each visit", "One stacked picture per visit (~6 months apart)"], ["exposure", "Every snapshot", "Every single exposure: best for asteroids"], ["channel", "One colour", "Only one of the 102 infrared colours"]].map(([k, l, t]) => (
                      <button key={k} title={t} className={mode === k ? "on" : ""} onClick={() => setMode(k)}>{l}</button>
                    ))}
                  </div>
                )}
                {mode !== "channel" && (
                  <div className="seg" role="group" aria-label="Infrared colour range">
                    {[0, 1, 2, 3, 4, 5, 6, 7].map((d) => (
                      <button key={d} className={det === d ? "on" : ""} onClick={() => setDet(d)}
                        title={d === 7 ? "D5 + D6 together (3.8–5 µm): the reddest light, where cold brown dwarfs glow"
                          : d ? `Detector D${d}${meta.detectors[d] ? `: ${meta.detectors[d][0].toFixed(2)}–${meta.detectors[d][1].toFixed(2)} µm` : ""}` : "All 6 detectors stacked: deepest picture"}>
                        {d === 7 ? (simple ? "Reddest" : "D5+6") : d ? (simple ? "Bluest" : `D${d}`) : (simple ? "All colours" : "All")}
                      </button>
                    )).filter((_, d) => expert || [0, 1, 7].includes(d))}
                  </div>
                )}
                {view === "blink" && (
                  <div className="seg" role="group" aria-label="Zoom on the object">
                    {[[1, "Whole picture"], [2, "2×"], [3, "3×"], [4, "4×"]].map(([z, l]) => (
                      <button key={z} className={zoom === z ? "on" : ""} onClick={() => setZoom(z)}
                        title={z === 1 ? "Show the whole area" : `Zoom ${z}× on the object (click a star to zoom on it instead)`}>{l}</button>
                    ))}
                  </div>
                )}
                {view === "blink" && F && F.data.length > 2 && (
                  <label className="tog" title="Flick between the first and the last visit only: the biggest change, like the blink comparator that found Pluto">
                    <input type="checkbox" checked={blinkPair} onChange={() => { setBlinkPair(!blinkPair); setIdx(0); }} /> Blink first ↔ last
                  </label>
                )}
                {mode === "channel" && (
                  <label className="plane">Colour plane <b>{ch}</b>
                    <input type="range" min="1" max="102" value={ch} onChange={(e) => setCh(+e.target.value)} />
                    <span className="mono small">{chWave}{chInfo ? ` · D${chInfo.det} · ${chInfo.n} snapshots` : ""}</span>
                  </label>
                )}
              </div>
            )}
            {simple && story && story.band === 7 && det === 7 && view === "blink" && (
              <p className="hint">Showing the <b>reddest</b> infrared colours, where cold brown dwarfs glow.</p>
            )}

            {view === "blink" && <ImageViewer F={F} idx={idx} disp={disp} ov={ov} target={target} cats={cats}
              asteroids={asteroids} onNeedAsteroids={needAsteroids} sel={sel} candidates={candidates} focus={focus}
              onPixel={onPixel} simple={simple} fov={fov} rgb={useRGB ? rgbSets : null} zoom={zoom} source={source} />}
            {view === "compare" && <BeforeAfter F={F} disp={disp} rgb={useRGB ? rgbSets : null} source={source} />}
            {view === "timecolours" && <TimeColours F={F} disp={disp} onPixel={onPixel} focusXY={sel} source={source} />}
            {view === "wall" && <DetectorWall F={wallF} idx={idx} disp={disp} detectors={meta.detectors} onPixel={onPixel} source={source} />}
            {view === "planes" && <SpectralCube qid={qid} visits={meta.visits} disp={disp} version={dataVersion} source={source} />}
            {view === "timemachine" && <TimeMachine qid={qid} target={target} fov={fov} disp={disp} onTask={setTmTask} />}
            {view === "asteroids" && <AsteroidHunter qid={qid} disp={disp} source={source} />}
            {view === "listen" && <Listen target={target} story={story} F={F && F.mode === "visit" ? F : null} sel={sel}
              spec={spec} loading={specLoading} onPixel={onPixel} candidates={candidates} source={source} />}

            {!["planes", "compare", "timecolours", "timemachine", "asteroids", "listen"].includes(view) && (
              <Controls playing={playing} setPlaying={setPlaying} idx={idx} count={count} setIdx={setIdx} fps={fps} setFps={setFps} disabled={!count} />
            )}
            {view === "blink" && <Timeline meta={meta} frame={frame} mode={F?.mode} simple={simple}
              onPick={(v) => { const k = F?.list.findIndex((f) => f.visit === v); if (k >= 0) setIdx(k); }} />}
            {!embed && view !== "listen" && (
              <DisplaySettings view={view} disp={disp} setDisp={setDisp} ov={ov} setOv={setOv} simple={simple}
                share={{ F, disp, target, story, facts: shareFacts, shareURL, say, rgb: useRGB ? rgbSets : null }} />
            )}
          </section>

          {!embed && (
            <aside className="side">
              {objPos?.clicked && (
                <section className="card selHead">
                  <h2>The object you clicked</h2>
                  <p className="small">Everything below is about this object: its details from <b>SIMBAD</b>, <b>Gaia DR3</b>, <b>AllWISE</b> and <b>Wikipedia</b>,
                    a check in <b>4 star catalogues</b> plus the <b>NASA Exoplanet Archive</b>, and its <b>spectrum</b> from SPHEREx.
                    Click another object in the picture to look it up.</p>
                  <button className="small" onClick={backToTarget}>← Back to {target?.name || "the target"}</button>
                </section>
              )}
              {objPos?.clicked && objectPanels}
              <Explainer story={story} target={target} mode={view === "compare" ? "visit" : mode} math={disp.math} det={det}
                channel={ch} chWave={chWave} view={view} simple={simple} />
              <CandidatesPanel qid={qid} band={det} candidates={candidates} setCandidates={setCandidates}
                focus={focus} setFocus={focusCand} expert={expert} autoRun={detectSignal} onChecks={setChecks}
                ctx={{ qid, fov, target: target?.name }} say={say} />
              <ReportCard qid={qid} sel={sel} band={det} pm={objPm} say={say}
                label={objPos?.clicked ? (details?.simbad?.name || null) : (target?.name || null)} />
              <AskPanel context={askContext} speak={listenMode} />
              <MetadataPanel target={target} meta={meta} frame={view === "blink" ? frame : null}
                flags={view === "blink" && F ? F.flags[Math.min(idx, F.flags.length - 1)] : null} fov={fov}
                releases={meta.status?.releases || []} selFlags={selFlags} simple={simple} fresh={fresh} onCheckNow={checkNow} />
              {!objPos?.clicked && objectPanels}
              <SkyMap target={target} fov={fov} onLoadHere={goCoords} />
            </aside>
          )}
        </div>
      )}
      {tour && <Tour step={tourStep} setStep={setTourStep} ready={tourReady} auto={tourAuto} setAuto={setTourAuto} speak={listenMode} />}
      <TaskBar tasks={tasks} />
      <div className={`toast ${toast ? "show" : ""}`}>{toast}</div>
    </div>
  );
}
