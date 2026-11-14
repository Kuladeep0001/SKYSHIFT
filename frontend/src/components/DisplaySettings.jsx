/* Expert display controls: stretch, colour map, frame maths, overlays, sharing. Owner: UI 2. */
import ShareMenu from "./ShareMenu.jsx";

// Which settings each tab really uses (the others would do nothing there, so they are hidden).
const USES = {
  blink: { math: true, cmap: true, rgb: true, overlays: true },
  wall: { math: true, cmap: true },
  compare: { cmap: true, rgb: true },
  timecolours: {},
  planes: { cmap: true },
  timemachine: { cmap: true },
  asteroids: { cmap: true },
};

const HELP = {
  none: "Each picture as it was taken.",
  first: "Each visit minus the first visit: orange = brighter now, blue = was brighter then. A blue + orange pair side by side means it moved.",
  prev: "Each visit minus the visit before it: shows what changed between neighbouring visits.",
  sum: "All visits added together into one deeper picture: faint things show up better (moving things get smeared).",
};

export default function DisplaySettings({ view = "blink", disp, setDisp, ov, setOv, simple, share }) {
  const set = (k, v) => setDisp((d) => ({ ...d, [k]: v }));
  const tog = (k) => setOv((o) => ({ ...o, [k]: !o[k] }));
  const use = USES[view] || USES.blink;
  const MATH = simple
    ? [["none", "Normal"], ["first", "Spot the difference"], ["sum", "Add all (see faint stuff)"]]
    : [["none", "Normal"], ["first", "− first"], ["prev", "− previous"], ["sum", "Σ add all"]];
  // "RGB colour" only means something where several infrared colours are combined; elsewhere it is grey
  const cmapValue = !use.rgb && disp.cmap === "rgb" ? "gray" : disp.cmap;
  return (
    <div className="settings">
      <div className="row">
        {use.math && (
          <div className="seg" role="group" aria-label="Add or subtract pictures">
            {MATH.map(([k, label]) => (
              <button key={k} className={disp.math === k ? "on" : ""} onClick={() => set("math", k)} title={HELP[k]}>{label}</button>
            ))}
          </div>
        )}
        <label title="Brighten faint things">Contrast <input type="range" min="0" max="1" step="0.01" value={disp.contrast} onChange={(e) => set("contrast", +e.target.value)} /></label>
        {!simple && <label title="Clip bright stars">Brightness <input type="range" min="0" max="1" step="0.01" value={disp.bright} onChange={(e) => set("bright", +e.target.value)} /></label>}
        {use.cmap && (
          <select value={cmapValue} onChange={(e) => set("cmap", e.target.value)} aria-label="Colour grading">
            {use.rgb && <option value="rgb">RGB colour</option>}<option value="gray">Grey</option>
            {!simple && <><option value="inferno">Heat</option><option value="invert">Inverted</option></>}
          </select>
        )}
      </div>
      <p className="small muted mathHelp">{use.math ? HELP[disp.math] || HELP.none
        : <>Add / subtract pictures and the star overlays are in the <b>{simple ? "Flipbook" : "Blink"}</b> tab.</>}</p>
      <div className="row">
        {use.overlays && <>
          <span className="lbl">Show</span>
          <label className="tog"><input type="checkbox" checked={ov.gaia} onChange={() => tog("gaia")} /> <i className="dot gaia" />{simple ? "Known fast stars" : "Gaia DR3"}</label>
          {!simple && <label className="tog"><input type="checkbox" checked={ov.wise} onChange={() => tog("wise")} /> <i className="dot wise" />AllWISE <small>(2010)</small></label>}
          <label className="tog"><input type="checkbox" checked={ov.ast} onChange={() => tog("ast")} /> <i className="dot ast" />Known asteroids</label>
          <label className="tog"><input type="checkbox" checked={ov.flags} onChange={() => tog("flags")} /> <i className="dot flag" />{simple ? "Bad pixels" : "Contamination flags"}</label>
          <label className="tog"><input type="checkbox" checked={ov.cross} onChange={() => tog("cross")} /> Target marker</label>
        </>}
        <span className="spacer" />
        <ShareMenu {...share} />
      </div>
    </div>
  );
}
