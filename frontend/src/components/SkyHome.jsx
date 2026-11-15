/* Home page sky: the whole sky in Aladin Lite (CDS), shown big at the top of the home page.
 * Zoom in, then click a spot or drag a square to choose an area: SkyShift loads every SPHEREx picture of it.
 * The view is in galactic coordinates (the Milky Way runs across the middle, like NASA's all-sky picture);
 * every position we hand to SkyShift is converted to RA/Dec (ICRS). Owner: UI 1. */
import { useEffect, useRef, useState } from "react";
import { fmtDec, fmtRA } from "../lib/frames.js";
import { TARGETS } from "../lib/targets.js";
import { skyCredit } from "../lib/sources.js";

export function hasWebGL2() {
  try { return !!document.createElement("canvas").getContext("webgl2"); } catch (_) { return false; }
}

// SPHEREx's own all-sky map in false colour, mixed by our server from IRSA's SPHEREx DR1 cube
export const COLOUR_SKY = `${location.origin}/hips/spherex-colour`;

const ALADIN_URL = "https://cdn.jsdelivr.net/npm/aladin-lite@3.8.2/dist/aladin.js";
// J2026 positions of the challenge targets (for the markers)
const MARKS = { barnard: [269.4463, 4.7682], epsindi: [331.0966, -56.8007], wise0855: [133.7598, -7.2422], rwaur: [76.9566, 30.4013], rdra: [248.1672, 66.7550] };

const SURVEYS = [
  [COLOUR_SKY, "SPHEREx colour sky (dust · gas · stars)"],
  ["P/allWISE/color", "Infrared sky (WISE)"],
  ["P/2MASS/color", "Infrared sky (2MASS)"],
  ["P/Mellinger/color", "Visible sky (Mellinger)"],
  ["P/DSS2/color", "Visible sky (DSS)"],
];

export default function SkyHome({ onPick, fovDefault }) {
  const div = useRef(null), al = useRef(null), A = useRef(null);
  const [mode, setMode] = useState("pan");        // pan | point | box
  const [drag, setDrag] = useState(null);         // {x0,y0,x1,y1} in px
  const [hover, setHover] = useState(null);
  const [fov, setFov] = useState(null);
  const [failed, setFailed] = useState(false);
  const [survey, setSurvey] = useState(COLOUR_SKY);

  useEffect(() => {
    let alive = true;
    (async () => {
      if (!hasWebGL2()) { setFailed(true); return; }  // the sky atlas needs WebGL2
      try {
        A.current = (await import(/* @vite-ignore */ ALADIN_URL)).default;
        await A.current.init;
        if (!alive || al.current) return;
        al.current = A.current.aladin(div.current, {
          survey, fov: 360, projection: "AIT", cooFrame: "galactic", target: "0 0",
          showCooGrid: false, showReticle: false, showZoomControl: true, showFullscreenControl: true,
          showLayersControl: false, showGotoControl: true, showFrame: true, showCooGridControl: true,
          showProjectionControl: false, showSimbadPointerControl: false, showStatusBar: false,
        });
        const cat = A.current.catalog({ name: "Challenge targets", sourceSize: 18, color: "#53d8c4", shape: "circle", displayLabel: true, labelColumn: "name", labelColor: "#53d8c4", labelFont: "13px Inter" });
        al.current.addCatalog(cat);
        cat.addSources(TARGETS.map((t) => A.current.source(MARKS[t.id][0], MARKS[t.id][1], { name: t.label, q: t.q })));
        al.current.on("objectClicked", (o) => { if (o && o.data && o.data.q) onPick({ q: o.data.q }); });
        al.current.on("zoomChanged", (f) => setFov(f));
        setFov(360);
      } catch (e) {
        console.warn("Aladin failed", e);
        if (alive) setFailed(true);
      }
    })();
    return () => { alive = false; };
  }, []);
  useEffect(() => { al.current && al.current.setImageSurvey(survey); }, [survey]);

  // pixel on the map -> RA/Dec (always ICRS, whatever frame the map is drawn in)
  const world = (x, y) => { try { const r = al.current.pix2world(x, y, "icrs"); return r && Number.isFinite(r[0]) ? r : null; } catch (_) { return null; } };
  const rel = (e) => { const r = div.current.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; };

  function down(e) { if (mode === "pan") return; const [x, y] = rel(e); setDrag({ x0: x, y0: y, x1: x, y1: y }); }
  function move(e) {
    const [x, y] = rel(e);
    if (al.current) setHover(world(x, y));
    if (drag) setDrag((d) => ({ ...d, x1: x, y1: y }));
  }
  function up() {
    if (!drag) return;
    const { x0, y0, x1, y1 } = drag;
    setDrag(null);
    const c = world((x0 + x1) / 2, (y0 + y1) / 2);
    if (!c) return;
    if (mode === "point" || Math.hypot(x1 - x0, y1 - y0) < 6) { onPick({ ra: c[0], dec: c[1], fov: fovDefault }); return; }
    // size of the square in arcminutes, from its corner-to-corner span
    const p0 = world(Math.min(x0, x1), Math.min(y0, y1)), p1 = world(Math.max(x0, x1), Math.max(y0, y1));
    if (!p0 || !p1) return;
    const dra = ((p0[0] - p1[0] + 540) % 360 - 180) * Math.cos((c[1] * Math.PI) / 180), ddec = p0[1] - p1[1];
    const side = (Math.hypot(dra, ddec) / Math.SQRT2) * 60;
    onPick({ ra: c[0], dec: c[1], fov: Math.round(Math.min(20, Math.max(2, side))), requested: side });
  }

  const tooWide = fov && fov > 2;
  const colour = survey === COLOUR_SKY;
  return (
    <section className="skyHome lead-map" aria-label="Interactive map of the whole sky">
      <div className="skyTools row">
        <div className="seg" role="group" aria-label="Map tool">
          <button className={mode === "pan" ? "on" : ""} onClick={() => setMode("pan")} title="Drag to move around, scroll to zoom">Move / zoom</button>
          <button className={mode === "point" ? "on" : ""} onClick={() => setMode("point")} title="Click a spot to load it">Pick a spot</button>
          <button className={mode === "box" ? "on" : ""} onClick={() => setMode("box")} title="Drag a square to load that area">Draw a square</button>
        </div>
        <select value={survey} onChange={(e) => setSurvey(e.target.value)} aria-label="Background sky picture">
          {SURVEYS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
        <span className="mono small muted">{hover ? `RA ${fmtRA(hover[0])} Dec ${fmtDec(hover[1])} · ${hover[0].toFixed(3)}°, ${hover[1].toFixed(3)}°` : "move the mouse over the sky"}</span>
      </div>
      <div className="skyWrap" onPointerMove={(e) => { if (al.current && !drag) { const [x, y] = rel(e); setHover(world(x, y)); } }}
        onPointerLeave={() => setHover(null)}>
        {failed
          ? <img className="skyStill" src="/spherex_allsky.jpg" alt="The whole sky in infrared as seen by NASA's SPHEREx, in false colour" />
          : <div ref={div} className="skyMap" />}
        {!failed && <div className="imgFoot skyFoot"><span className="src">Data: {skyCredit(survey)}</span></div>}
        {mode !== "pan" && !failed && (
          <div className="skyCatcher" onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerLeave={() => setDrag(null)}
            style={{ cursor: "crosshair" }} aria-label="Click or drag to choose an area" />
        )}
        {drag && <div className="skyBox" style={{ left: Math.min(drag.x0, drag.x1), top: Math.min(drag.y0, drag.y1), width: Math.abs(drag.x1 - drag.x0), height: Math.abs(drag.y1 - drag.y0) }} />}
        {mode !== "pan" && tooWide && <div className="skyTip">Zoom in first (mode + scroll): SkyShift loads areas up to 20 arcminutes wide.<br />Right now the map shows {fov > 1 ? `${fov.toFixed(0)}°` : `${(fov * 60).toFixed(0)}′`}.</div>}
      </div>
      <p className="hint">
        {failed ? <><b>The whole sky as SPHEREx sees it.</b> (Your browser can't show the zoomable map, so this is a still picture. Use the search box above instead.) </>
          : <><b>The whole sky, live and zoomable.</b> Scroll to zoom, drag to move. </>}
        {colour
          ? <>Infrared light is invisible, so SkyShift turns it into colours: <b style={{ color: "#ff9a6b" }}>orange-red</b> = glowing dust, <b style={{ color: "#7fe8ff" }}>cyan</b> = hot hydrogen gas, white/blue = stars. The Milky Way runs across the middle. </>
          : <>Use the menu to switch between infrared and visible-light pictures of the sky. </>}
        {!failed && <>Turquoise circles are the challenge targets (click one). Zoom in, choose <b>Pick a spot</b> or <b>Draw a square</b>, and SkyShift will fetch every SPHEREx picture of that area.</>}
      </p>
    </section>
  );
}
