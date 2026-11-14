/* Listen mode: hear the data, for people who can't see the screen.
 *
 * Spectrum  -> one tone per colour channel, from shortest to longest wavelength.
 *              Pitch  = light's frequency (short wavelength = high note, long = low note)
 *              Volume = brightness at that wavelength
 *              Length = shorter wavelengths last a little longer
 *              A soft "ding" marks a band where water, CO2, methane... were found.
 * Motion    -> one tone per visit, in date order.
 *              Pitch goes UP if the star moved north, DOWN if south.
 *              Sound moves RIGHT if it moved west, LEFT if east (use headphones).
 *              Volume = how bright it was at that visit.
 * A voice explains everything before and after, and captions appear on screen too.
 */
import { useEffect, useRef, useState } from "react";
import { monthYear, PIX } from "../lib/frames.js";

let audio = null;
const ac = () => (audio ||= new (window.AudioContext || window.webkitAudioContext)());

function tone(t0, { freq, dur, gain, pan = 0, type = "sine" }) {
  const a = ac(), o = a.createOscillator(), g = a.createGain();
  o.type = type;
  o.frequency.value = freq;
  const peak = Math.max(0.0005, gain);
  g.gain.setValueAtTime(0.0001, t0);
  g.gain.exponentialRampToValueAtTime(peak, t0 + Math.min(0.03, dur / 3));
  g.gain.setValueAtTime(peak, t0 + dur * 0.75);
  g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
  o.connect(g);
  if (a.createStereoPanner) { const p = a.createStereoPanner(); p.pan.value = Math.max(-1, Math.min(1, pan)); g.connect(p); p.connect(a.destination); }
  else g.connect(a.destination);
  o.start(t0);
  o.stop(t0 + dur + 0.05);
}

const wait = (ms) => new Promise((r) => setTimeout(r, ms));

/* Find the star near (x, y) in each visit: position (centroid) and brightness. */
export function trackStar(F, x0, y0) {
  const n = F.n, out = [];
  let cx = x0, cy = y0;
  F.data.forEach((a, k) => {
    const R = k === 0 ? 2 : 3;
    let best = -Infinity, bx = Math.round(cx), by = Math.round(cy);
    for (let y = Math.round(cy) - R; y <= Math.round(cy) + R; y++)
      for (let x = Math.round(cx) - R; x <= Math.round(cx) + R; x++) {
        if (x < 1 || y < 1 || x >= n - 1 || y >= n - 1) continue;
        const v = a[y * n + x];
        if (Number.isFinite(v) && v > best) { best = v; bx = x; by = y; }
      }
    const ring = [];
    for (let y = by - 5; y <= by + 5; y++) for (let x = bx - 5; x <= bx + 5; x++) {
      if (x < 0 || y < 0 || x >= n || y >= n || (Math.abs(x - bx) < 3 && Math.abs(y - by) < 3)) continue;
      const v = a[y * n + x]; if (Number.isFinite(v)) ring.push(v);
    }
    ring.sort((p, q) => p - q);
    const bg = ring.length ? ring[ring.length >> 1] : 0;
    let s = 0, sx = 0, sy = 0;
    for (let y = by - 1; y <= by + 1; y++) for (let x = bx - 1; x <= bx + 1; x++) {
      const v = Math.max(0, (a[y * n + x] || 0) - bg); s += v; sx += v * x; sy += v * y;
    }
    cx = s > 0 ? sx / s : bx; cy = s > 0 ? sy / s : by;
    out.push({ x: cx, y: cy, flux: s, date: (F.list[k].date_range?.[0] || F.list[k].date).slice(0, 10), mjd: F.list[k].mjd });
  });
  return out;
}

function direction(dx, dy) {
  const parts = [];
  if (Math.abs(dy) > 0.15) parts.push(dy > 0 ? "north" : "south");
  if (Math.abs(dx) > 0.15) parts.push(dx > 0 ? "west" : "east");
  return parts.join(" and ") || "nowhere noticeable";
}

export default function Listen({ target, story, F, sel, getSpectrum, listenFirst }) {
  const [caption, setCaption] = useState("");
  const [busy, setBusy] = useState(false);
  const stop = useRef(false);

  const say = (text) => new Promise((resolve) => {
    setCaption(text);
    if (stop.current || !("speechSynthesis" in window)) return resolve();
    const u = new SpeechSynthesisUtterance(text);
    u.rate = 1.0;
    u.onend = u.onerror = () => resolve();
    window.speechSynthesis.speak(u);
  });

  const halt = () => {
    stop.current = true;
    window.speechSynthesis && window.speechSynthesis.cancel();
    if (audio) { audio.close(); audio = null; }
    setBusy(false);
  };
  useEffect(() => () => halt(), []);
  const name = story?.label || target?.name || "this spot";

  async function run(fn) {
    halt();
    stop.current = false;
    setBusy(true);
    try { await ac().resume(); await fn(); } finally { setBusy(false); }
  }

  const describe = () => run(async () => {
    if (!F) return;
    const first = F.list[0], last = F.list[F.list.length - 1];
    await say(`${name}. ${story ? story.story : ""} You are looking at ${F.data.length} infrared pictures of the same small patch of sky, ` +
      `taken by NASA's SPHEREx telescope between ${monthYear(first.date_range?.[0] || first.date.slice(0, 10))} and ${monthYear(last.date_range?.[0] || last.date.slice(0, 10))}. ` +
      `${story ? story.watch : ""} Press "Hear the motion" to hear how it moves, or "Hear the spectrum" to hear its colours.`);
  });

  const motion = () => run(async () => {
    if (!F || F.data.length < 2) return say("This spot needs at least two visits to hear any motion.");
    const n = F.n, x0 = sel ? sel.x : (n - 1) / 2, y0 = sel ? sel.y : (n - 1) / 2;
    const tr = trackStar(F, x0, y0);
    const f0 = tr[0].flux || 1;
    await say(`Listening to ${sel ? "the object you selected" : name}. You will hear one note for each visit, in date order. ` +
      "If the note goes higher, the star moved north; lower means south. If the sound moves to your right, it moved west; to your left, east. " +
      "Louder means brighter, quieter means fainter. Headphones help.");
    const notes = tr.map((p) => {
      const dx = p.x - tr[0].x, dy = p.y - tr[0].y;
      return { freq: 440 * Math.pow(2, (dy * 6) / 12), pan: dx * 0.7, gain: Math.min(0.6, Math.max(0.04, 0.3 * Math.sqrt(Math.max(0.01, p.flux / f0)))), dx, dy, ratio: p.flux / f0, date: p.date };
    });
    for (let k = 0; k < notes.length && !stop.current; k++) {
      const p = notes[k];
      const moved = Math.hypot(p.dx, p.dy) * PIX;
      const text = k === 0 ? `Visit 1, ${monthYear(p.date)}. This is the starting note.`
        : `Visit ${k + 1}, ${monthYear(p.date)}. Moved ${moved.toFixed(0)} arcseconds ${direction(p.dx, p.dy)} from the start. Brightness ${Math.round(p.ratio * 100)} percent of the first visit.`;
      await say(text);
      if (stop.current) break;
      tone(ac().currentTime + 0.05, { freq: p.freq, dur: 0.7, gain: p.gain, pan: p.pan, type: "triangle" });
      await wait(1000);
    }
    if (stop.current) return;
    await say("Now all visits quickly, one after another.");
    const t = ac().currentTime + 0.1;
    notes.forEach((p, k) => tone(t + k * 0.45, { freq: p.freq, dur: 0.38, gain: p.gain, pan: p.pan, type: "triangle" }));
    await wait(notes.length * 450 + 400);
    const last = notes[notes.length - 1];
    const years = (tr[tr.length - 1].mjd - tr[0].mjd) / 365.25;
    const total = Math.hypot(last.dx, last.dy) * PIX;
    const bright = Math.max(...notes.map((p) => p.ratio)), dim = Math.min(...notes.map((p) => p.ratio));
    let summary = total > 2.5
      ? `Summary: over ${years.toFixed(1)} years it moved about ${total.toFixed(0)} arcseconds toward the ${direction(last.dx, last.dy)}, about ${(total / years).toFixed(1)} arcseconds per year. That is fast: most stars barely move. `
      : "Summary: it stayed in the same place. ";
    summary += bright / dim > 1.3 ? `Its brightness changed: the brightest visit was ${(bright / dim).toFixed(1)} times brighter than the faintest.` : "Its brightness stayed about the same.";
    await say(summary);
  });

  const spectrum = () => run(async () => {
    const spec = await getSpectrum();
    const pts = (spec?.binned || []).filter((p) => !p.saturated || spec.saturated_fraction > 0.5);
    if (pts.length < 5) return say("There isn't enough data at this spot to play a spectrum.");
    const fl = pts.map((p) => p.flux), lo = Math.min(...fl), hi = Math.max(...fl);
    const seen = (spec.features || []).filter((f) => f.status !== "not seen");
    await say(`The spectrum of ${sel ? "the selected object" : name}. You will hear its brightness in all ${pts.length} infrared colours, from the shortest wavelength, 0.75 microns, to the longest, 5 microns. ` +
      "Short wavelengths are high notes, long wavelengths are low notes. Louder means brighter. Short wavelength notes last a little longer. " +
      (seen.length ? "A soft ding marks a place where a molecule or mineral may be absorbing or glowing." : ""));
    if (stop.current) return;
    let t = ac().currentTime + 0.15;
    const start = t;
    const dinged = new Set();
    for (const p of pts) {
      const frac = (p.wave - 0.75) / (5 - 0.75);
      const dur = 0.07 + 0.11 * (1 - frac);
      const level = Math.max(0, (p.flux - lo) / (hi - lo || 1));
      tone(t, { freq: 220 * Math.pow(5 / p.wave, 0.95), dur, gain: 0.03 + 0.45 * Math.sqrt(level) });
      for (const f of seen) {  // one ding when we enter a band where something was found
        if (!dinged.has(f.name) && Math.abs(p.wave - f.center_um) <= f.half_width_um) {
          dinged.add(f.name);
          tone(t, { freq: 2400, dur: 0.06, gain: 0.08 });
        }
      }
      t += dur + 0.012;
    }
    await wait((t - start) * 1000 + 300);
    if (stop.current) return;
    const peak = pts.reduce((m, p) => (p.flux > m.flux ? p : m), pts[0]);
    let s = `It is brightest at ${peak.wave.toFixed(1)} microns${peak.wave > 3 ? ", in the far infrared part, which means it is cool or dusty" : peak.wave < 1.2 ? ", at the short end, which means it is hot" : ""}. `;
    s += seen.length ? `Possible signatures: ${seen.slice(0, 4).map((f) => `${f.name.replace(/[₀-₉]/g, (c) => "0123456789"["₀₁₂₃₄₅₆₇₈₉".indexOf(c)])}, a ${Math.abs(f.change_pct).toFixed(0)} percent ${f.change_pct < 0 ? "dip" : "bump"}`).join("; ")}.`
      : "No strong molecule signatures stand out.";
    await say(s);
  });

  // keyboard shortcuts: D describe, M motion, S spectrum, Escape stop
  useEffect(() => {
    const k = (e) => {
      if (e.target.tagName === "INPUT" || e.ctrlKey || e.metaKey) return;
      if (e.key === "d" || e.key === "D") describe();
      if (e.key === "m" || e.key === "M") motion();
      if (e.key === "s" || e.key === "S") spectrum();
      if (e.key === "Escape") halt();
    };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  });

  return (
    <section className={`card listen ${listenFirst ? "prominent" : ""}`} aria-label="Listen to the data">
      <h2>🔊 Listen to the sky <small>for everyone, including blind and low-vision users</small></h2>
      <div className="listenBtns">
        <button onClick={describe} disabled={!F} aria-keyshortcuts="D">🗣 Describe <kbd>D</kbd></button>
        <button onClick={motion} disabled={!F} aria-keyshortcuts="M">🎵 Hear the motion <kbd>M</kbd></button>
        <button onClick={spectrum} disabled={!F} aria-keyshortcuts="S">🌈 Hear the spectrum <kbd>S</kbd></button>
        {busy && <button onClick={halt} className="stopBtn" aria-keyshortcuts="Escape">■ Stop <kbd>Esc</kbd></button>}
      </div>
      <p className="caption" aria-live="polite" role="status">{caption || "Press a button (or the key shown) to hear this object. A voice explains what each sound means."}</p>
      <details className="small muted">
        <summary>How the sounds work</summary>
        <ul>
          <li><b>Motion:</b> one note per visit. Higher note = moved north, lower = south; sound to the right = moved west, left = east; louder = brighter.</li>
          <li><b>Spectrum:</b> notes go from high (short wavelength, 0.75 µm) to low (long wavelength, 5 µm). Louder = brighter at that colour; short-wavelength notes last longer. A "ding" marks a possible water, CO₂, methane… band.</li>
          <li>Click a star in the picture first to hear that star instead of the centre.</li>
        </ul>
      </details>
    </section>
  );
}
