/* Play / pause / step / speed / scrub. Owner: UI 2. */
export default function Controls({ playing, setPlaying, idx, count, setIdx, fps, setFps, disabled }) {
  const step = (d) => count && setIdx((i) => (i + d + count) % count);
  return (
    <div className="player">
      <button onClick={() => step(-1)} disabled={disabled} title="Previous picture (←)" aria-label="Previous">‹ Prev</button>
      <button className="primary play" onClick={() => setPlaying(!playing)} disabled={disabled}
        title="Play / pause (space)" aria-label={playing ? "Pause" : "Play"}>{playing ? "Pause" : "Play"}</button>
      <button onClick={() => step(1)} disabled={disabled} title="Next picture (→)" aria-label="Next">Next ›</button>
      <input type="range" min="0" max={Math.max(0, count - 1)} value={Math.min(idx, Math.max(0, count - 1))}
        onChange={(e) => setIdx(+e.target.value)} disabled={disabled} aria-label="Which picture" />
      <span className="mono frameLbl">{count ? `${Math.min(idx, count - 1) + 1}/${count}` : "–"}</span>
      <label title="Pictures per second">Slow <input type="range" min="0.5" max="8" step="0.5" value={fps}
        onChange={(e) => setFps(+e.target.value)} aria-label="Speed" /> Fast</label>
    </div>
  );
}
