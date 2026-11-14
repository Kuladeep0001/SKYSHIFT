/* Expert display controls: stretch, colour map, frame maths, overlays, sharing. Owner: UI 2. */
export default function DisplaySettings({ disp, setDisp, ov, setOv, simple, onCopyLink, onCopyEmbed, onSavePng }) {
  const set = (k, v) => setDisp((d) => ({ ...d, [k]: v }));
  const tog = (k) => setOv((o) => ({ ...o, [k]: !o[k] }));
  const MATH = simple
    ? [["none", "Normal"], ["first", "Spot the difference"], ["sum", "Add all (see faint stuff)"]]
    : [["none", "Normal"], ["first", "− first"], ["prev", "− previous"], ["sum", "Σ add all"]];
  return (
    <div className="settings">
      <div className="row">
        <div className="seg" role="group" aria-label="Add or subtract pictures">
          {MATH.map(([k, label]) => (
            <button key={k} className={disp.math === k ? "on" : ""} onClick={() => set("math", k)}>{label}</button>
          ))}
        </div>
        <label title="Brighten faint things">Contrast <input type="range" min="0" max="1" step="0.01" value={disp.contrast} onChange={(e) => set("contrast", +e.target.value)} /></label>
        {!simple && <label title="Clip bright stars">Brightness <input type="range" min="0" max="1" step="0.01" value={disp.bright} onChange={(e) => set("bright", +e.target.value)} /></label>}
        {!simple && (
          <select value={disp.cmap} onChange={(e) => set("cmap", e.target.value)} aria-label="Colour map">
            <option value="gray">Grey</option><option value="inferno">Heat</option><option value="invert">Inverted</option>
          </select>
        )}
      </div>
      <div className="row">
        <span className="lbl">Show</span>
        <label className="tog"><input type="checkbox" checked={ov.gaia} onChange={() => tog("gaia")} /> <i className="dot gaia" />{simple ? "Known fast stars" : "Gaia DR3"}</label>
        {!simple && <label className="tog"><input type="checkbox" checked={ov.wise} onChange={() => tog("wise")} /> <i className="dot wise" />AllWISE <small>(2010)</small></label>}
        <label className="tog"><input type="checkbox" checked={ov.ast} onChange={() => tog("ast")} /> <i className="dot ast" />Known asteroids</label>
        <label className="tog"><input type="checkbox" checked={ov.flags} onChange={() => tog("flags")} /> <i className="dot flag" />{simple ? "Bad pixels" : "Contamination flags"}</label>
        <label className="tog"><input type="checkbox" checked={ov.cross} onChange={() => tog("cross")} /> Target marker</label>
        <span className="spacer" />
        <button onClick={onCopyLink} title="Copy a link to exactly this view">🔗 Share link</button>
        <button onClick={onCopyEmbed} title="Copy code to put this viewer on another website">&lt;/&gt; Embed</button>
        <button onClick={onSavePng} title="Save this picture">⤓ Save picture</button>
      </div>
    </div>
  );
}
