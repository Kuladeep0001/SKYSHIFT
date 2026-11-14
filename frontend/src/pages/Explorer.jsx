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
import SkyHome from "../components/SkyHome.jsx";
import TimeColours from "../components/TimeColours.jsx";
import MetadataPanel from "../components/MetadataPanel.jsx";
import PlanesGrid from "../components/PlanesGrid.jsx";
import SkyMap from "../components/SkyMap.jsx";
import SpectrumPanel from "../components/SpectrumPanel.jsx";
import TaskBar from "../components/TaskBar.jsx";
import Timeline from "../components/Timeline.jsx";
import { api, loadImages } from "../lib/api.js";
import { decodeFrames, mainVisitsOnly } from "../lib/frames.js";
import { findTarget, TARGETS } from "../lib/targets.js";

const params = new URLSearchParams(location.search);
const FACTS = [
  "SPHEREx photographs the entire sky every 6 months in 102 infrared colours.",
  "Pluto was discovered in 1930 by comparing two photos taken days apart, just like this.",
  "Volunteers comparing images like these have discovered hundreds of brown dwarfs.",
  "Infrared light passes through dust, so SPHEREx sees things hidden from ordinary telescopes.",
  "Barnard's Star moves the width of the full Moon across the sky in about 180 years.",
];

export default function Explorer({ expert, embed, listenMode }) {
  const simple = !expert;
  const [target, setTarget] = useState(null);
  const [fov, setFov] = useState(+params.get("fov") || 6);
  const [release, setRelease] = useState(params.get("rel") || "");
  const [releases, setReleases] = useState(null);
  const [load, setLoad] = useState({ phase: "idle" });
  const [qid, setQid] = useState(null);
  const [meta, setMeta] = useState(null);
  const [view, setView] = useState(params.get("view") || "blink");
  const [mode, setMode] = useState(params.get("mode") || "visit");
  const [det, setDet] = useState(+params.get("det") || 0);
  const [ch, setCh] = useState(+params.get("ch") || 40);
  const [planeVisit, setPlaneVisit] = useState(0);
  const [F, setF] = useState(null);
  const [wallF, setWallF] = useState(null);
  const [planesF, setPlanesF] = useState(null);
  const [idx, setIdx] = useState(0);
  const [playing, setPlaying] = useState(true);
  const [fps, setFps] = useState(1.5);
  const [disp, setDisp] = useState({ contrast: 0.55, bright: 0.5, cmap: "gray", math: params.get("math") || "none" });
  const [ov, setOv] = useState({ gaia: true, wise: false, ast: false, flags: false, cross: true });
  const [cats, setCats] = useState({});
  const [asteroids, setAsteroids] = useState({});
  const [sel, setSel] = useState(null);
  const [spec, setSpec] = useState(null);
  const [specLoading, setSpecLoading] = useState(false);
  const [candidates, setCandidates] = useState(null);
  const [focus, setFocus] = useState(null);
  const [toast, setToast] = useState("");
  const [objPos, setObjPos] = useState(null);
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
  useEffect(() => { if (simple && !["blink", "compare", "timecolours"].includes(view)) setView("blink"); if (simple) setMode("visit"); }, [simple]);

  /* ---------------------------------------------------------- loading */
  const startLoad = useCallback(async (t, fovNow, rel) => {
    const my = ++token.current;
    setLoad({ phase: "loading", done: 0, total: 0, message: "Asking NASA which SPHEREx pictures cover this spot…" });
    loadingId.current = null; loadStart.current = Date.now(); setNewData(null); setFresh(null);
    setQid(null); setMeta(null); setF(null); setWallF(null); setPlanesF(null);
    setSel(null); setSpec(null); setCandidates(null); setFocus(null); setCats({}); setAsteroids({}); setObjPos(null);
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
      startLoad(t, fov, release);
    } catch (e) {
      setLoad({ phase: "error", message: e.message });
    }
  }, [fov, release, expert, startLoad]);

  const goCoords = (ra, dec, f = fov) => {
    const t = { ra, dec, name: null, query: null };
    setTarget(t);
    if (f !== fov) { firstRun.current = true; setFov(f); }
    startLoad(t, f, release);
  };

  // boot: releases + URL
  useEffect(() => {
    api.releases().then(setReleases).catch(() => {});
    const ra = parseFloat(params.get("ra")), dec = parseFloat(params.get("dec"));
    if (Number.isFinite(ra) && Number.isFinite(dec)) {
      const t = { ra, dec, name: params.get("q"), query: params.get("q") };
      setTarget(t);
      startLoad(t, fov, release);
    } else if (params.get("q")) go(params.get("q"));
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
        if (view === "blink" || view === "compare" || view === "timecolours") {
          const m = view === "blink" ? mode : "visit";
          const res = await api.frames(qid, { mode: m, det: m === "channel" ? 0 : det, channel: m === "channel" ? ch : 0 });
          if (!alive) return;
          let dec = decodeFrames(res);
          if (simple || view !== "blink") dec = mainVisitsOnly(dec); // the clean twice-a-year visits
          setF(dec); setIdx(0);
          if (!dec.data.length) say(m === "channel" ? `No snapshot caught this spot in colour plane ${ch}. Try a neighbouring one.` : "No pictures for this choice.");
        } else if (view === "wall" || view === "color") {
          if (!wallF) { const res = await api.frames(qid, { mode: "visitdet" }); if (alive) setWallF(decodeFrames(res)); }
          setIdx(0);
        } else if (view === "planes") {
          const res = await api.frames(qid, { mode: "planes", visit: planeVisit });
          if (alive) setPlanesF(decodeFrames(res));
        }
      } catch (e) { say(e.message); }
    })();
    return () => { alive = false; };
  }, [qid, view, mode, det, ch, planeVisit, simple, dataVersion]);

  const count = view === "wall" || view === "color" ? wallVisitCount(wallF) : F ? F.data.length : 0;

  // play loop
  useEffect(() => {
    if (!playing || !count || ["planes", "compare", "timecolours"].includes(view) || disp.math === "sum") return;
    const h = setInterval(() => setIdx((i) => (i + 1) % count), 1000 / fps);
    return () => clearInterval(h);
  }, [playing, fps, count, view, disp.math]);

  // keyboard: space / arrows
  useEffect(() => {
    const k = (e) => {
      if (e.target.tagName === "INPUT" && e.target.type === "text") return;
      if (e.code === "Space") { e.preventDefault(); setPlaying((p) => !p); }
      if (e.code === "ArrowRight" && count) setIdx((i) => (i + 1) % count);
      if (e.code === "ArrowLeft" && count) setIdx((i) => (i - 1 + count) % count);
    };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [count]);

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
    if (expert) p.set("expert", "1");
    if (embed) p.set("embed", "1");
    history.replaceState(null, "", `${location.pathname}?${p}${location.hash}`);
  }, [target, fov, release, view, mode, det, ch, disp.math, expert, embed]);

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
    setMeta(m); setWallF(null); setPlanesF(null); setCandidates(null);
    setDataVersion(m.status.freshness.version); setFresh(m.status.freshness); setNewData(null);
  };
  const tasks = [];
  if (load.phase === "loading") tasks.push({ id: "load", label: `Fetching ${target?.name || "this spot"} from NASA`, detail: load.message,
    done: load.done, total: load.total, startedAt: loadStart.current, onCancel: cancelLoad });
  if (fresh?.refreshing) tasks.push({ id: "refresh", kind: "update", label: "New SPHEREx pictures found: updating this spot",
    done: fresh.refresh_progress?.done || 0, total: fresh.refresh_progress?.total || 0,
    onCancel: () => api.cancel(qid).then(() => say("Update cancelled.")).catch(() => {}) });

  /* ---------------------------------------------------------- spectrum */
  const onPixel = async (x, y) => {
    if (!qid) return;
    setSel({ x, y });
    setSpecLoading(true);
    try {
      const sp = await api.spectrum(qid, x, y);
      setSpec(sp);
      const mid = meta?.exposures?.length ? meta.exposures[meta.exposures.length >> 1].mjd : 0;
      setObjPos({ ra: sp.ra, dec: sp.dec, mjd: mid, name: null });
    } catch (e) { say(e.message); } finally { setSpecLoading(false); }
  };
  const getSpectrum = async () => {
    if (spec) return spec;
    const c = (meta.n_pix - 1) >> 1;
    const sp = await api.spectrum(qid, c, c);
    setSpec(sp);
    return sp;
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
    if (c) onPixel(Math.round(c.x), Math.round(c.y));
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

  /* ------------------------------------------------------------ render */
  const ready = load.phase === "ready" && meta;
  const chInfo = meta && meta.channels[ch - 1];
  const chWave = chInfo && chInfo.wave ? `${chInfo.wave[0].toFixed(2)}–${chInfo.wave[1].toFixed(2)} µm` : "";
  const tabs = simple
    ? [["blink", "▶ Flipbook"], ["timecolours", "🎨 Colour by date"], ["compare", "⇔ Before / after"]]
    : [["blink", "Blink"], ["timecolours", "Colour by date"], ["compare", "Before / after"], ["wall", "6 Detectors"], ["color", "Infrared colour"], ["planes", "102 Colours"]];

  return (
    <div className="explorer">
      {!embed && (
        <CoordinateInput initial={params.get("q") || ""} onGo={go} fov={fov} setFov={setFov} release={release}
          setRelease={setRelease} releases={releases} expert={expert} busy={load.phase === "loading"} />
      )}

      {load.phase === "idle" && !embed && (
        <section className="welcome">
          <h1>Watch the sky <span className="hl">move</span>.</h1>
          <p className="lead">NASA's <b>SPHEREx</b> telescope photographs the whole sky every six months. SkyShift lines up its pictures of any spot and plays them like a <b>flipbook</b>, so anything that moves or changes brightness jumps out. That's how Pluto was found!</p>
          <ol className="steps">
            <li><span>1</span>Pick a star (or type any sky coordinates)</li>
            <li><span>2</span>We fetch every SPHEREx picture of that spot</li>
            <li><span>3</span>Press play and spot what moves</li>
          </ol>
          <SkyHome fovDefault={fov} onPick={(p) => (p.q ? go(p.q) : goCoords(p.ra, p.dec, p.fov))} />
          <h2 className="center">…or start with one of the challenge's test targets</h2>
          <div className="cards">
            {TARGETS.map((t) => (
              <button key={t.id} className="tcard" onClick={() => go(t.q)}>
                <span className="emoji">{t.emoji}</span>
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
          <p className="fact">💡 {FACTS[fact]}</p>
          <button onClick={cancelLoad} className="cancelBtn">✕ Cancel download</button>
        </section>
      )}
      {load.phase === "error" && <section className="progress card"><p className="err">⚠ {load.message}</p></section>}

      {ready && newData && (
        <div className="newData" role="status">
          🆕 NASA added data for this spot{newData.new_exposures ? `: ${newData.new_exposures} new pictures` : ""}
          {newData.new_releases?.length ? ` (new release ${newData.new_releases.join(", ").replace(/spherex_/g, "").toUpperCase()})` : ""}.
          <button className="primary" onClick={showNewData}>Show them</button>
        </div>
      )}
      {ready && (
        <div className={`layout ${embed ? "embedLayout" : ""}`}>
          <section className="stage card">
            {!embed && (
              <div className="tabs" role="tablist">
                {tabs.map(([k, label]) => <button key={k} className={view === k ? "on" : ""} onClick={() => setView(k)}>{label}</button>)}
              </div>
            )}

            {view === "blink" && (
              <div className="row">
                {expert && (
                  <div className="seg" role="group" aria-label="How to build each picture">
                    {[["visit", "Each visit", "One stacked picture per visit (~6 months apart)"], ["exposure", "Every snapshot", "Every single exposure: best for asteroids"], ["channel", "One colour", "Only one of the 102 infrared colours"]].map(([k, l, t]) => (
                      <button key={k} title={t} className={mode === k ? "on" : ""} onClick={() => setMode(k)}>{l}</button>
                    ))}
                  </div>
                )}
                {mode !== "channel" && (
                  <div className="seg" role="group" aria-label="Infrared colour range">
                    {[0, 1, 2, 3, 4, 5, 6].map((d) => (
                      <button key={d} className={det === d ? "on" : ""} onClick={() => setDet(d)}
                        title={d ? `Detector D${d}${meta.detectors[d] ? `: ${meta.detectors[d][0].toFixed(2)}–${meta.detectors[d][1].toFixed(2)} µm` : ""}` : "All 6 detectors stacked: deepest picture"}>
                        {d ? (simple ? ["", "Bluest", "", "", "", "", "Reddest"][d] || `D${d}` : `D${d}`) : (simple ? "All colours" : "All")}
                      </button>
                    )).filter((_, d) => expert || [0, 1, 6].includes(d))}
                  </div>
                )}
                {mode === "channel" && (
                  <label className="plane">Colour plane <b>{ch}</b>
                    <input type="range" min="1" max="102" value={ch} onChange={(e) => setCh(+e.target.value)} />
                    <span className="mono small">{chWave}{chInfo ? ` · D${chInfo.det} · ${chInfo.n} snapshots` : ""}</span>
                  </label>
                )}
              </div>
            )}
            {simple && story && story.band === 6 && det === 6 && view === "blink" && (
              <p className="hint">Showing the <b>reddest</b> infrared colours, where cold brown dwarfs glow.</p>
            )}

            {view === "blink" && <ImageViewer F={F} idx={idx} disp={disp} ov={ov} target={target} cats={cats}
              asteroids={asteroids} onNeedAsteroids={needAsteroids} sel={sel} candidates={candidates} focus={focus}
              onPixel={onPixel} simple={simple} fov={fov} />}
            {view === "compare" && <BeforeAfter F={F} disp={disp} />}
            {view === "timecolours" && <TimeColours F={F} disp={disp} onPixel={onPixel} focusXY={sel} />}
            {(view === "wall" || view === "color") && <DetectorWall F={wallF} idx={idx} disp={disp} detectors={meta.detectors} colour={view === "color"} onPixel={onPixel} />}
            {view === "planes" && <PlanesGrid F={planesF} channels={meta.channels} disp={disp} visits={meta.visits} visit={planeVisit}
              setVisit={setPlaneVisit} onPick={(c) => { setCh(c); setMode("channel"); setView("blink"); }} />}

            {!["planes", "compare", "timecolours"].includes(view) && (
              <Controls playing={playing} setPlaying={setPlaying} idx={idx} count={count} setIdx={setIdx} fps={fps} setFps={setFps} disabled={!count} />
            )}
            {view === "blink" && <Timeline meta={meta} frame={frame} mode={F?.mode} simple={simple}
              onPick={(v) => { const k = F?.list.findIndex((f) => f.visit === v); if (k >= 0) setIdx(k); }} />}
            {!embed && view !== "planes" && (
              <DisplaySettings disp={disp} setDisp={setDisp} ov={ov} setOv={setOv} simple={simple}
                onCopyLink={() => copy(shareURL(false), "Link copied")}
                onCopyEmbed={() => copy(`<iframe src="${shareURL(true)}" width="640" height="780" style="border:0;border-radius:12px" title="SkyShift SPHEREx viewer" loading="lazy"></iframe>`, "Embed code copied")}
                onSavePng={savePng} />
            )}
          </section>

          {!embed && (
            <aside className="side">
              {listenMode && <Listen target={target} story={story} F={F && F.mode === "visit" ? F : null} sel={sel} getSpectrum={getSpectrum} listenFirst />}
              <Explainer story={story} target={target} mode={view === "compare" ? "visit" : mode} math={disp.math} det={det}
                channel={ch} chWave={chWave} view={view} simple={simple} />
              <CandidatesPanel qid={qid} band={det} candidates={candidates} setCandidates={setCandidates}
                focus={focus} setFocus={focusCand} expert={expert} />
              <MetadataPanel target={target} meta={meta} frame={view === "blink" ? frame : null}
                flags={view === "blink" && F ? F.flags[Math.min(idx, F.flags.length - 1)] : null} fov={fov}
                releases={meta.status?.releases || []} selFlags={selFlags} simple={simple} fresh={fresh} onCheckNow={checkNow} />
              <ObjectCard pos={objPos} simple={simple} />
              <SpectrumPanel spec={spec} visits={meta.visits} detectors={meta.detectors} loading={specLoading} simple={simple} />
              {!listenMode && <Listen target={target} story={story} F={F && F.mode === "visit" ? F : null} sel={sel} getSpectrum={getSpectrum} />}
              <SkyMap target={target} fov={fov} onLoadHere={goCoords} />
            </aside>
          )}
        </div>
      )}
      <TaskBar tasks={tasks} />
      <div className={`toast ${toast ? "show" : ""}`}>{toast}</div>
    </div>
  );
}
