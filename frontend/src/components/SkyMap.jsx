/* Zoomable sky atlas around the target (Aladin Lite from CDS Strasbourg). */
import { useEffect, useRef, useState } from "react";

const ALADIN_URL = "https://cdn.jsdelivr.net/npm/aladin-lite@3.8.2/dist/aladin.js";
let aladinModule = null;

export default function SkyMap({ target, fov, onLoadHere }) {
  const div = useRef(null), al = useRef(null), overlay = useRef(null);
  const [survey, setSurvey] = useState("P/allWISE/color");
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        aladinModule = aladinModule || (await import(/* @vite-ignore */ ALADIN_URL)).default;
        await aladinModule.init;
        if (!alive || al.current) return;
        al.current = aladinModule.aladin(div.current, { survey, fov: 0.4, showReticle: true, showZoomControl: true,
          showFullscreenControl: true, showLayersControl: true, showGotoControl: false, showFrame: false });
        overlay.current = aladinModule.graphicOverlay({ color: "#ffb547", lineWidth: 2 });
        al.current.addOverlay(overlay.current);
        sync();
      } catch (e) {
        console.warn("Aladin failed", e);
        setFailed(true);
      }
    })();
    return () => { alive = false; };
  }, []);

  function sync() {
    if (!al.current || !target) return;
    const { ra, dec } = target, h = fov / 120, c = Math.cos((dec * Math.PI) / 180);
    al.current.gotoRaDec(ra, dec);
    al.current.setFoV(Math.max(0.15, (fov / 60) * 3));
    overlay.current.removeAll();
    overlay.current.add(aladinModule.polygon([[ra + h / c, dec - h], [ra - h / c, dec - h], [ra - h / c, dec + h], [ra + h / c, dec + h]]));
  }
  useEffect(sync, [target, fov]);
  useEffect(() => { al.current && al.current.setImageSurvey(survey); }, [survey]);

  return (
    <section className="card">
      <h2>Sky map <small>Aladin · CDS</small>
        <select value={survey} onChange={(e) => setSurvey(e.target.value)}>
          <option value="P/allWISE/color">WISE infrared</option>
          <option value="P/2MASS/color">2MASS infrared</option>
          <option value="P/DSS2/color">Visible light (DSS)</option>
        </select>
      </h2>
      {failed ? <p className="hint">Sky map unavailable (needs WebGL2).</p> : <div ref={div} className="aladin" />}
      <p className="small muted">The orange box is the area SkyShift is showing. Drag to explore, then:</p>
      <button className="full" onClick={() => { if (al.current) { const [ra, dec] = al.current.getRaDec(); onLoadHere(ra, dec); } }}>
        Show the spot at the centre of this map
      </button>
    </section>
  );
}
