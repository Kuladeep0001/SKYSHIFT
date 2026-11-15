/* Listen tab: the data as sound, made for blind and low-vision visitors.
 *
 * The main tool is the brightness-vs-wavelength graph (the spectrum). It is drawn big on screen AND played:
 *   Graph sound (default): one gliding note travels along the graph, from the shortest wavelength
 *                          (0.75 µm, left ear) to the longest (5 µm, right ear).
 *                          Higher note = brighter. Louder = brighter too.
 *   Colour sound:          one note per colour. The note follows the light itself (short wavelength =
 *                          high note), louder = brighter, short wavelengths last a little longer.
 *   A soft "ding" marks a band where water, CO2, methane... may have been seen.
 * Arrow keys walk along the graph one colour at a time: each step plays that point and reads its value.
 * Motion: one note per visit; higher = moved north, right ear = moved west, louder = brighter.
 * Everything works from the keyboard. Captions are on screen, and are read by screen readers when the
 * built-in voice is switched off (so the two never talk over each other).
 */
import { useEffect, useMemo, useRef, useState } from "react";
import Chart from "chart.js/auto";
import { monthYear, PIX } from "../lib/frames.js";
import { bandsPlugin } from "./SpectrumPanel.jsx";

/* ------------------------------------------------------------------ sound */
let audio = null;
const ac = () => (audio ||= new (window.AudioContext || window.webkitAudioContext)());
const live = new Set();  // oscillators that are playing, so Stop can silence them

function out(a, g, pan) {
  if (a.createStereoPanner) {
    const p = a.createStereoPanner();
    if (pan != null) p.pan.value = Math.max(-1, Math.min(1, pan));
    g.connect(p); p.connect(a.destination);
    return p;
  }
  g.connect(a.destination);
  return null;
}

function tone(t0, { freq, dur, gain, pan = 0, type = "sine" }) {
  const a = ac(), o = a.createOscillator(), g = a.createGain();
  o.type = type;
  o.frequency.value = freq;
  const peak = Math.max(0.0005, gain);
  g.gain.setValueAtTime(0.0001, t0);
  g.gain.exponentialRampToValueAtTime(peak, t0 + Math.min(0.03, dur / 3));
  g.gain.setValueAtTime(peak, t0 + dur * 0.75);
  g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
  o.connect(g); out(a, g, pan);
  o.start(t0); o.stop(t0 + dur + 0.05);
  live.add(o); o.onended = () => live.delete(o);
}

/* One continuous note whose pitch, volume and left-right position follow the graph. */
function glide(t0, notes, step) {
  const a = ac(), o = a.createOscillator(), g = a.createGain();
  o.type = "triangle";
  o.connect(g);
  const p = out(a, g, null);
  g.gain.setValueAtTime(0, t0);
  notes.forEach((nt, k) => {
    const t = t0 + k * step;
    if (k === 0) {
      o.frequency.setValueAtTime(nt.freq, t);
      g.gain.linearRampToValueAtTime(nt.gain, t + 0.03);
      p && p.pan.setValueAtTime(nt.pan, t);
    } else {
      o.frequency.linearRampToValueAtTime(nt.freq, t);
      g.gain.linearRampToValueAtTime(nt.gain, t);
      p && p.pan.linearRampToValueAtTime(nt.pan, t);
    }
  });
  const end = t0 + notes.length * step;
  g.gain.linearRampToValueAtTime(0, end + 0.08);
  o.start(t0); o.stop(end + 0.1);
  live.add(o); o.onended = () => live.delete(o);
}

function silence() {
  for (const o of live) { try { o.stop(); } catch (_) { /* already stopped */ } }
  live.clear();
}

const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const SPEED = { slow: 0.16, normal: 0.09, fast: 0.05 };          // seconds per point, graph sound
const COLOUR_SPEED = { slow: 1.6, normal: 1, fast: 0.6 };        // note-length factor, colour sound

/* ------------------------------------------------------------ the numbers */
const plainName = (s) => s.replace(/[₀-₉]/g, (c) => "0123456789"["₀₁₂₃₄₅₆₇₈₉".indexOf(c)]);
const num = (v) => (Math.abs(v) >= 100 ? Math.round(v).toLocaleString() : Math.abs(v) < 0.05 ? "about zero" : v.toPrecision(2));
const COMPASS = ["north", "north-east", "east", "south-east", "south", "south-west", "west", "north-west"];
const SCREEN = { north: "up", "north-east": "up and left", east: "left", "south-east": "down and left", south: "down",
  "south-west": "down and right", west: "right", "north-west": "up and right" };

/* Find the star near (x, y) in each visit: position (centroid) and brightness. */
export function trackStar(F, x0, y0) {
  const n = F.n, res = [];
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
    res.push({ x: cx, y: cy, flux: s, date: (F.list[k].date_range?.[0] || F.list[k].date).slice(0, 10), mjd: F.list[k].mjd });
  });
  return res;
}

function direction(dx, dy) {
  const parts = [];
  if (Math.abs(dy) > 0.15) parts.push(dy > 0 ? "north" : "south");
  if (Math.abs(dx) > 0.15) parts.push(dx > 0 ? "west" : "east");
  return parts.join(" and ") || "nowhere noticeable";
}

/* Where a pixel is, in words: "1.4 arcminutes north-east of the centre (up and left in the picture)". */
function whereIs(x, y, n) {
  const c = (n - 1) / 2, dx = x - c, dy = y - c;
  const arcmin = (Math.hypot(dx, dy) * PIX) / 60;
  if (arcmin < 0.2) return "at the centre";
  const pa = (Math.atan2(-dx, dy) * 180) / Math.PI;           // degrees east of north (east = left)
  const dir = COMPASS[Math.round(((pa + 360) % 360) / 45) % 8];
  return `${arcmin.toFixed(1)} arcminutes ${dir} of the centre (${SCREEN[dir]} in the picture)`;
}

/* The brightest stars in the picture, so people who can't click on the image can still pick one. */
function brightStars(F, max = 6) {
  if (!F || !F.data.length) return [];
  const n = F.n, N = n * n, sum = new Float32Array(N), cnt = new Uint16Array(N);
  for (const a of F.data) for (let i = 0; i < N; i++) { const v = a[i]; if (Number.isFinite(v)) { sum[i] += v; cnt[i]++; } }
  const img = Array.from(sum, (s, i) => (cnt[i] ? s / cnt[i] : NaN));
  const vals = img.filter(Number.isFinite).sort((a, b) => a - b);
  if (vals.length < 50) return [];
  const med = vals[vals.length >> 1];
  const mad = vals.map((v) => Math.abs(v - med)).sort((a, b) => a - b)[vals.length >> 1] * 1.4826 || 1e-6;
  const thr = med + 8 * mad, peaks = [];
  for (let y = 3; y < n - 3; y++) for (let x = 3; x < n - 3; x++) {
    const v = img[y * n + x];
    if (!(v > thr)) continue;
    let top = true;
    for (let j = -1; j <= 1 && top; j++) for (let i = -1; i <= 1; i++) if ((i || j) && img[(y + j) * n + x + i] > v) { top = false; break; }
    if (top) peaks.push({ x, y, v });
  }
  peaks.sort((a, b) => b.v - a.v);
  const keep = [];
  for (const p of peaks) {
    if (keep.every((q) => Math.hypot(q.x - p.x, q.y - p.y) > 5)) keep.push(p);
    if (keep.length >= max) break;
  }
  return keep.map((p) => ({ ...p, rel: p.v / keep[0].v }));
}

function graphSummary(pts, seen, who) {
  const peak = pts.reduce((m, p) => (p.flux > m.flux ? p : m), pts[0]);
  const third = Math.max(1, Math.floor(pts.length / 3));
  const avg = (a) => a.reduce((s, p) => s + p.flux, 0) / a.length;
  const first = avg(pts.slice(0, third)), last = avg(pts.slice(-third));
  let shape = last > first * 1.3 ? "The line climbs toward the long-wavelength end, which is a sign of something cool or dusty."
    : first > last * 1.3 ? "The line falls toward the long-wavelength end, so it is brighter at short wavelengths."
      : "The line stays fairly level.";
  // a rise again at the far end (above 3.9 µm) is where cold brown dwarfs and warm dust glow
  const mid = pts.filter((p) => p.wave > 1.2 && p.wave < 3.9);
  const tail = pts.filter((p) => p.wave >= 3.9);
  if (mid.length >= 5 && tail.length >= 3) {
    const low = mid.reduce((m, p) => (p.flux < m.flux ? p : m), mid[0]);
    const climbs = last > first * 1.3;
    if (!climbs && low.flux > 0 && avg(tail) > 1.6 * low.flux) {
      shape += ` But it dips to its faintest near ${low.wave.toFixed(1)} microns and rises again beyond 4 microns, where cold brown dwarfs and warm dust glow.`;
    }
  }
  const feats = seen.length
    ? `Possible signatures: ${seen.slice(0, 4).map((f) => `${plainName(f.name)}, a ${Math.abs(f.change_pct).toFixed(0)} percent ${f.change_pct < 0 ? "dip" : "bump"} near ${f.center_um.toFixed(1)} microns`).join("; ")}.`
    : "No strong molecule signatures stand out.";
  return `Graph of brightness against wavelength for ${who}. ${pts.length} points, from ${pts[0].wave.toFixed(2)} microns on the left to ${pts[pts.length - 1].wave.toFixed(1)} microns on the right. ` +
    `It is brightest at ${peak.wave.toFixed(2)} microns. ${shape} ${feats}`;
}

/* Draws the moving "you are here" line on the graph. */
const playhead = {
  id: "playhead",
  afterDatasetsDraw(chart, _a, opts) {
    const p = opts.point;
    if (!p) return;
    const { ctx, chartArea: a, scales: { x, y } } = chart;
    const px = x.getPixelForValue(p.x), py = y.getPixelForValue(p.y);
    ctx.save();
    ctx.strokeStyle = "rgba(255,255,255,.75)"; ctx.lineWidth = 2;
    ctx.beginPath(); ctx.moveTo(px, a.top); ctx.lineTo(px, a.bottom); ctx.stroke();
    ctx.fillStyle = "#ffffff"; ctx.strokeStyle = "#1a1100"; ctx.lineWidth = 3;
    ctx.beginPath(); ctx.arc(px, py, 9, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
    ctx.restore();
  },
};

/* ================================================================ the tab */
export default function Listen({ target, story, F, sel, spec, loading, onPixel, candidates, source }) {
  const [caption, setCaption] = useState("");
  const [busy, setBusy] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [cur, setCur] = useState(0);               // which point of the graph we are on
  const [style, setStyle] = useState("graph");
  const [speed, setSpeed] = useState("normal");
  const [voice, setVoice] = useState(true);
  const gen = useRef(0);                           // bumped by every Stop: older sound sequences then end themselves
  const play = useRef(null);                       // {t0, times, from, raf}
  const graphRun = useRef(false);                  // true from pressing Play until the graph ends (intro included)
  const introDone = useRef({});                    // the spoken intro plays once per sound style
  const announce = useRef("");
  const canvas = useRef(null), chart = useRef(null);
  const name = story?.label || target?.name || "this spot";

  /* the graph's points, shortest wavelength first */
  const pts = useMemo(() => {
    const good = (spec?.binned || []).filter((p) => Number.isFinite(p.flux) && (!p.saturated || spec.saturated_fraction > 0.5));
    return [...good].sort((a, b) => a.wave - b.wave);
  }, [spec]);
  const seen = useMemo(() => (spec?.features || []).filter((f) => f.status === "likely" || f.status === "possible"), [spec]);
  const range = useMemo(() => {
    const fl = pts.map((p) => p.flux);
    return { lo: Math.min(...fl), hi: Math.max(...fl) };
  }, [pts]);
  const level = (p) => Math.max(0, Math.min(1, (p.flux - range.lo) / (range.hi - range.lo || 1)));
  const featureAt = (w) => seen.find((f) => Math.abs(w - f.center_um) <= f.half_width_um);

  /* objects you can choose to listen to */
  const n = F?.n || 0, c = (n - 1) / 2;
  const stars = useMemo(() => brightStars(F), [F]);
  const choices = useMemo(() => {
    if (!n) return [];
    const list = [{ key: "centre", x: Math.round(c), y: Math.round(c), short: name, label: `${name}, at the centre of the picture` }];
    for (const cd of (candidates || []).slice(0, 4)) {
      list.push({ key: `cand-${cd.candidate_id}`, x: Math.round(cd.x), y: Math.round(cd.y), short: cd.kind === "mover" ? "the moving object" : "the changing object",
        label: `${cd.kind === "mover" ? "A moving object" : "A changing object"} found by SkyShift, ${whereIs(cd.x, cd.y, n)}` });
    }
    stars.filter((s) => Math.hypot(s.x - c, s.y - c) > 2.5).forEach((s, i) => {
      const how = s.rel > 0.6 ? "very bright" : s.rel > 0.25 ? "bright" : s.rel > 0.08 ? "medium" : "faint";
      list.push({ key: `star-${i}`, x: s.x, y: s.y, short: `Star ${i + 1}`, label: `Star ${i + 1}: ${how}, ${whereIs(s.x, s.y, n)}` });
    });
    return list;
  }, [n, c, name, candidates, stars]);
  const picked = sel ? choices.find((ch) => Math.hypot(ch.x - sel.x, ch.y - sel.y) < 1.6) : choices[0];
  const who = picked ? picked.short : sel ? "the object you clicked" : name;
  const summary = pts.length >= 5
    ? (spec?.saturated_fraction > 0.5 ? "Careful: this star is so bright it overloads the camera, so the shape of this graph is not reliable. Pick a fainter star from the list for a clean graph. " : "") + graphSummary(pts, seen, who)
    : "";

  /* ---------------------------------------------------------- speaking */
  const say = (text) => new Promise((resolve) => {
    setCaption(text);
    if (!voice || !("speechSynthesis" in window)) return resolve();
    const u = new SpeechSynthesisUtterance(text);
    let done = false;
    const finish = () => { if (!done) { done = true; resolve(); } };
    u.onend = u.onerror = finish;
    setTimeout(finish, 2500 + text.length * 85);   // some browsers never fire "end": don't get stuck
    window.speechSynthesis.speak(u);
  });
  const sayNow = (text) => {          // for quick stepping: drop whatever was being said
    window.speechSynthesis && window.speechSynthesis.cancel();
    say(text);
  };

  const halt = () => {
    gen.current++;
    window.speechSynthesis && window.speechSynthesis.cancel();
    silence();
    if (play.current) cancelAnimationFrame(play.current.raf);
    play.current = null;
    graphRun.current = false;
    setPlaying(false); setBusy(false);
  };
  useEffect(() => () => halt(), []);

  async function run(fn) {
    halt();
    const g = gen.current, dead = () => gen.current !== g;
    setBusy(true);
    try { await ac().resume(); await fn(dead); } finally { if (!dead()) setBusy(false); }
  }

  /* ------------------------------------------------------ the graph */
  useEffect(() => {
    chart.current?.destroy();
    chart.current = null;
    if (!canvas.current || pts.length < 2) return;
    const big = { family: "Inter, sans-serif", size: 14 };
    chart.current = new Chart(canvas.current, {
      type: "line",
      data: { datasets: [{ label: "Brightness", data: pts.map((p) => ({ x: p.wave, y: p.flux })), borderColor: "#ffd166",
        backgroundColor: "#ffd166", borderWidth: 3, pointRadius: 2.5, tension: 0 }] },
      options: {
        animation: false, maintainAspectRatio: false, parsing: false,
        plugins: {
          legend: { display: false }, tooltip: { enabled: false },
          bands: { features: spec?.features || [], detectors: {}, showAll: false },
          playhead: { point: null },
        },
        scales: {
          x: { type: "linear", min: 0.7, max: 5.05, title: { display: true, text: "Wavelength (µm):  shorter  ←   →  longer", color: "#e6ecf5", font: big },
            grid: { color: "#262833" }, ticks: { color: "#e6ecf5", font: big } },
          y: { title: { display: true, text: "Brightness = flux (µJy)", color: "#e6ecf5", font: big },
            grid: { color: "#262833" }, ticks: { color: "#e6ecf5", font: big } },
        },
        onClick: (evt, _e, ch) => {          // click the graph: jump there and hear that point
          const w = ch.scales.x.getValueForPixel(evt.x);
          let k = 0;
          pts.forEach((p, i) => { if (Math.abs(p.wave - w) < Math.abs(pts[k].wave - w)) k = i; });
          stepRef.current(k);
        },
      },
      plugins: [bandsPlugin, playhead],
    });
    setCur(0);
    return () => { chart.current?.destroy(); chart.current = null; };
  }, [pts]);

  useEffect(() => {        // move the playhead
    const ch = chart.current;
    if (!ch) return;
    const p = pts[cur];
    ch.options.plugins.playhead.point = p ? { x: p.wave, y: p.flux } : null;
    ch.update("none");
  }, [cur, playing, pts]);

  /* tell the listener when a newly picked object's graph is ready */
  useEffect(() => {
    if (!announce.current || loading || !spec) return;
    const what = announce.current;
    announce.current = "";
    sayNow(pts.length >= 5 ? `${what}: the graph is ready. Press P to play it, or the arrow keys to walk along it.` : `${what}: there isn't enough data here to make a graph.`);
  }, [spec, loading]);

  const noteOf = (p) => style === "graph"
    ? { freq: 220 * Math.pow(2, 3 * level(p)), gain: 0.05 + 0.3 * Math.sqrt(level(p)), pan: -0.9 + 1.8 * ((p.wave - 0.75) / 4.25) }
    : { freq: 220 * Math.pow(5 / p.wave, 0.95), gain: 0.03 + 0.45 * Math.sqrt(level(p)), pan: -0.9 + 1.8 * ((p.wave - 0.75) / 4.25) };

  const pointText = (k) => {
    const p = pts[k];
    if (!p) return "";
    const f = featureAt(p.wave);
    return `Point ${k + 1} of ${pts.length}. ${p.wave.toFixed(2)} microns. Brightness ${num(p.flux)} micro-janskys, ` +
      (range.hi > 0 ? `${Math.max(0, Math.round((100 * p.flux) / range.hi))} percent as bright as the brightest point.` : "") +
      (f ? ` Inside the ${plainName(f.name)} band.` : "") + (p.saturated ? " Overloaded camera here, so this is a lower limit." : "");
  };

  const stepRef = useRef(null);
  stepRef.current = stepTo;
  function stepTo(k) {
    if (!pts.length) return;
    halt();
    const kk = Math.max(0, Math.min(pts.length - 1, k));
    setCur(kk);
    ac().resume();
    const nt = noteOf(pts[kk]);
    tone(ac().currentTime + 0.02, { ...nt, dur: 0.35, type: style === "graph" ? "triangle" : "sine" });
    if (featureAt(pts[kk].wave)) tone(ac().currentTime + 0.02, { freq: 2400, dur: 0.06, gain: 0.08 });
    sayNow(pointText(kk));
  }

  const playGraph = (from = cur >= pts.length - 1 ? 0 : cur) => run(async (dead) => {
    if (pts.length < 5) return say("There isn't enough data at this spot to play a graph. Pick another object.");
    graphRun.current = true;
    if (from === 0 && !introDone.current[style]) {
      introDone.current[style] = true;
      await say(style === "graph"
        ? `Playing the graph of ${who}, from short wavelengths in your left ear to long wavelengths in your right ear. A higher, louder note means brighter.${seen.length ? " A soft ding marks a possible molecule." : ""}`
        : `Playing the colours of ${who}. Short wavelengths are high notes, long wavelengths are low notes. Louder means brighter.${seen.length ? " A soft ding marks a possible molecule." : ""}`);
      if (dead()) return;
    }
    const a = ac(), t0 = a.currentTime + 0.1, rest = pts.slice(from);
    const times = [];
    let t = 0;
    if (style === "graph") {
      const step = SPEED[speed];
      rest.forEach((_, k) => times.push(k * step));
      glide(t0, rest.map(noteOf), step);
      t = rest.length * step;
    } else {
      for (const p of rest) {
        const dur = (0.07 + 0.11 * (1 - (p.wave - 0.75) / 4.25)) * COLOUR_SPEED[speed];
        times.push(t);
        tone(t0 + t, { ...noteOf(p), dur });
        t += dur + 0.012;
      }
    }
    const dinged = new Set();
    rest.forEach((p, k) => {
      const f = featureAt(p.wave);
      if (f && !dinged.has(f.name)) { dinged.add(f.name); tone(t0 + times[k], { freq: 2400, dur: 0.06, gain: 0.08 }); }
    });
    setPlaying(true);
    play.current = { t0, times, from, raf: 0 };
    const tick = () => {
      if (!play.current) return;
      const el = ac().currentTime - play.current.t0;
      let k = 0;
      while (k + 1 < times.length && times[k + 1] <= el) k++;
      setCur(from + k);
      if (el < t) play.current.raf = requestAnimationFrame(tick);
    };
    play.current.raf = requestAnimationFrame(tick);
    await wait(t * 1000 + 250);
    if (dead()) return;
    play.current = null;
    graphRun.current = false;
    setPlaying(false);
    await say(summary);
  });

  const pause = () => {
    const mid = !!play.current;
    halt();
    sayNow(mid ? `Paused at ${pts[cur]?.wave.toFixed(2)} microns. Press P to carry on.` : "Stopped. Press P to play the graph.");
  };

  const describe = () => run(async () => {
    if (!F) return say("The pictures are still loading.");
    const first = F.list[0], last = F.list[F.list.length - 1];
    await say(`${name}. ${story ? story.story : ""} SkyShift has ${F.data.length} infrared pictures of this small patch of sky, ` +
      `taken by NASA's SPHEREx telescope between ${monthYear(first.date_range?.[0] || first.date.slice(0, 10))} and ${monthYear(last.date_range?.[0] || last.date.slice(0, 10))}. ` +
      `${choices.length > 1 ? `Besides the centre, there are ${choices.length - 1} other objects you can pick in the list. ` : ""}` +
      `${summary ? summary + " " : ""}Press P to play the graph, the arrow keys to walk along it, or M to hear how the object moves.`);
  });

  const motion = () => run(async (dead) => {
    if (!F || F.data.length < 2) return say("This spot needs at least two visits to hear any motion.");
    const x0 = sel ? sel.x : c, y0 = sel ? sel.y : c;
    const tr = trackStar(F, x0, y0);
    const f0 = tr[0].flux || 1;
    await say(`Listening to how ${who} moves. You will hear one note for each visit, in date order. ` +
      "If the note goes higher, it moved north; lower means south. If the sound moves to your right, it moved west; to your left, east. " +
      "Louder means brighter, quieter means fainter. Headphones help.");
    const notes = tr.map((p) => {
      const dx = p.x - tr[0].x, dy = p.y - tr[0].y;
      return { freq: 440 * Math.pow(2, (dy * 6) / 12), pan: dx * 0.7, gain: Math.min(0.6, Math.max(0.04, 0.3 * Math.sqrt(Math.max(0.01, p.flux / f0)))), dx, dy, ratio: p.flux / f0, date: p.date };
    });
    for (let k = 0; k < notes.length && !dead(); k++) {
      const p = notes[k];
      const moved = Math.hypot(p.dx, p.dy) * PIX;
      await say(k === 0 ? `Visit 1, ${monthYear(p.date)}. This is the starting note.`
        : `Visit ${k + 1}, ${monthYear(p.date)}. ${moved < 2 ? "Same place as the start." : `Moved ${moved.toFixed(0)} arcseconds ${direction(p.dx, p.dy)} from the start.`} Brightness ${Math.round(p.ratio * 100)} percent of the first visit.`);
      if (dead()) break;
      tone(ac().currentTime + 0.05, { freq: p.freq, dur: 0.7, gain: p.gain, pan: p.pan, type: "triangle" });
      await wait(1000);
    }
    if (dead()) return;
    await say("Now all visits quickly, one after another.");
    if (dead()) return;
    const t = ac().currentTime + 0.1;
    notes.forEach((p, k) => tone(t + k * 0.45, { freq: p.freq, dur: 0.38, gain: p.gain, pan: p.pan, type: "triangle" }));
    await wait(notes.length * 450 + 400);
    if (dead()) return;
    const lastN = notes[notes.length - 1];
    const years = (tr[tr.length - 1].mjd - tr[0].mjd) / 365.25;
    const total = Math.hypot(lastN.dx, lastN.dy) * PIX;
    const bright = Math.max(...notes.map((p) => p.ratio)), dim = Math.min(...notes.map((p) => p.ratio));
    let s = total > 2.5
      ? `Summary: over ${years.toFixed(1)} years it moved about ${total.toFixed(0)} arcseconds toward the ${direction(lastN.dx, lastN.dy)}, about ${(total / years).toFixed(1)} arcseconds per year. That is fast: most stars barely move. `
      : "Summary: it stayed in the same place. ";
    s += bright / dim > 1.3 ? `Its brightness changed: the brightest visit was ${(bright / dim).toFixed(1)} times brighter than the faintest.` : "Its brightness stayed about the same.";
    await say(s);
  });

  const choose = (ch) => {
    halt();
    announce.current = ch.short;
    onPixel(ch.x, ch.y);
    sayNow(`${ch.label}. Loading its graph.`);
  };

  /* keyboard: P or Space play/pause, arrows step, Home/End, D describe, M motion, Escape stop */
  useEffect(() => {
    const k = (e) => {
      const tag = e.target.tagName, type = e.target.type;
      const choice = tag === "INPUT" && (type === "radio" || type === "checkbox");   // the object list and options
      if ((tag === "INPUT" && !choice) || tag === "SELECT" || tag === "TEXTAREA" || e.ctrlKey || e.metaKey || e.altKey) return;
      const native = tag === "BUTTON" || tag === "SUMMARY" || choice;               // Space / arrows already mean something there
      const key = e.key;
      if (key === "p" || key === "P" || (key === " " && !native)) { e.preventDefault(); graphRun.current ? pause() : playGraph(); }
      else if (key === "ArrowRight" && !(choice && type === "radio")) { e.preventDefault(); stepTo(cur + 1); }
      else if (key === "ArrowLeft" && !(choice && type === "radio")) { e.preventDefault(); stepTo(cur - 1); }
      else if (key === "Home") { e.preventDefault(); stepTo(0); }
      else if (key === "End") { e.preventDefault(); stepTo(pts.length - 1); }
      else if (key === "d" || key === "D") describe();
      else if (key === "m" || key === "M") motion();
      else if (key === "Escape") { halt(); setCaption("Stopped."); }
    };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  });

  const sat = spec && spec.saturated_fraction > 0.5;
  return (
    <section className="listenTab" aria-labelledby="listenTitle">
      <h2 id="listenTitle">Listen to the sky</h2>
      <p className="lead">Made for blind and low-vision visitors. Everything here works with the keyboard and a screen reader. Headphones help: short wavelengths play in your left ear and long ones in your right.</p>

      <div className="listenBtns" role="group" aria-label="Play the brightness graph">
        <button className="primary" onClick={() => (graphRun.current ? pause() : playGraph())} disabled={pts.length < 5} aria-keyshortcuts="P">
          {playing || graphRun.current ? "Pause" : cur > 0 && cur < pts.length - 1 ? "Carry on" : "Play the graph"} <kbd>P</kbd>
        </button>
        <button onClick={() => stepTo(0)} disabled={!pts.length} aria-label="Go to the first point" aria-keyshortcuts="Home">Start</button>
        <button onClick={() => stepTo(cur - 1)} disabled={!pts.length} aria-label="Previous point" aria-keyshortcuts="ArrowLeft">Step</button>
        <button onClick={() => stepTo(cur + 1)} disabled={!pts.length} aria-label="Next point" aria-keyshortcuts="ArrowRight">Step</button>
        <button onClick={describe} aria-keyshortcuts="D">Describe <kbd>D</kbd></button>
        <button onClick={motion} disabled={!F} aria-keyshortcuts="M">Hear the motion <kbd>M</kbd></button>
        {(busy || playing) && <button onClick={() => { halt(); setCaption("Stopped."); }} className="stopBtn" aria-keyshortcuts="Escape">Stop <kbd>Esc</kbd></button>}
      </div>

      <p className="caption big" role="status" aria-live={voice ? "off" : "polite"}>
        {caption || (loading ? "Loading the graph…" : "Pick an object, then press P to hear its brightness graph.")}
      </p>

      <figure className="listenGraph">
        <figcaption>Brightness (flux) of <b>{who}</b> at each infrared wavelength</figcaption>
        <div className="chartBox listenChart">
          <canvas ref={canvas} role="img" aria-label={summary || "The graph is loading."} />
        </div>
        <p className="srcLine">Data: {source || "NASA SPHEREx via IRSA"}</p>
        {sat && <p className="note warn">This star is so bright it overloads SPHEREx's camera, so these values are lower limits. Pick a fainter star for a clean graph.</p>}
        {pts[cur] && <p className="readout" aria-hidden="true">{pts[cur].wave.toFixed(2)} µm · {num(pts[cur].flux)} µJy{featureAt(pts[cur].wave) ? ` · ${featureAt(pts[cur].wave).name} band` : ""}</p>}
      </figure>

      <fieldset className="pick">
        <legend>Choose what to listen to</legend>
        {choices.length ? choices.map((ch) => (
          <label key={ch.key} className={picked?.key === ch.key ? "on" : ""}>
            <input type="radio" name="listenObj" checked={picked?.key === ch.key} onChange={() => choose(ch)} /> {ch.label}
          </label>
        )) : <p className="muted">The pictures are still loading…</p>}
        {sel && !picked && <p className="muted">Now listening to the spot you clicked in the picture.</p>}
      </fieldset>

      <div className="row listenOpts">
        <label>Sound
          <select value={style} onChange={(e) => { halt(); setStyle(e.target.value); setCur(0); }}>
            <option value="graph">Graph: higher note = brighter</option>
            <option value="colour">Colours: note follows the wavelength, louder = brighter</option>
          </select>
        </label>
        <label>Speed
          <select value={speed} onChange={(e) => { halt(); setSpeed(e.target.value); }}>
            <option value="slow">Slow</option><option value="normal">Normal</option><option value="fast">Fast</option>
          </select>
        </label>
        <label><input type="checkbox" checked={voice} onChange={() => { halt(); setVoice(!voice); }} /> Built-in voice (turn off if you use a screen reader)</label>
      </div>

      <ul className="keys" aria-label="Keyboard shortcuts">
        <li><kbd>P</kbd> or <kbd>Space</kbd> play or pause the graph</li>
        <li><kbd>←</kbd> <kbd>→</kbd> one point at a time</li>
        <li><kbd>Home</kbd> <kbd>End</kbd> first or last point</li>
        <li><kbd>D</kbd> describe this spot</li>
        <li><kbd>M</kbd> hear how it moves</li>
        <li><kbd>Esc</kbd> stop</li>
      </ul>

      <details>
        <summary>Read the graph as a table</summary>
        <table className="features">
          <caption className="sr">Brightness of {who} at each wavelength</caption>
          <thead><tr><th>#</th><th>Wavelength (µm)</th><th>Brightness (µJy)</th><th>Note</th></tr></thead>
          <tbody>
            {pts.map((p, k) => (
              <tr key={k} className={k === cur ? "cur" : ""}>
                <td>{k + 1}</td><td className="mono">{p.wave.toFixed(3)}</td><td className="mono">{p.flux.toFixed(1)}</td>
                <td>{[featureAt(p.wave)?.name, p.saturated && "overloaded"].filter(Boolean).join(", ")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>

      <details>
        <summary>What is "brightness" (flux) on this graph?</summary>
        <p><b>Flux</b> is how much of the object's light reaches the telescope at one colour (wavelength), each second. A bigger number means the object is brighter at that colour.</p>
        <p>It is measured in <b>micro-janskys (µJy)</b>. A jansky is the unit astronomers use for faint light from space, and a micro-jansky is one millionth of that.</p>
        <p>SkyShift measures it in a small square (18 arcseconds wide) around the object, after removing the glow of the sky behind it.</p>
        <p><b>Reading the graph:</b> the highest part tells you where the object shines most. Hot stars are brightest on the left (short wavelengths), while cool brown dwarfs and dusty objects get brighter toward the right.
          A <b>dip</b> means something is absorbing that colour, such as water vapour, methane or carbon monoxide. A <b>bump</b> means something is glowing, such as hot hydrogen gas or dust.</p>
      </details>

      <details>
        <summary>How the sounds work</summary>
        <ul>
          <li><b>Graph sound:</b> one note slides along the graph from left (short wavelength, left ear) to right (long wavelength, right ear). Higher and louder = brighter. Dips sound like the note dropping.</li>
          <li><b>Colour sound:</b> one note per colour. High notes are short wavelengths and low notes are long ones, like the light itself. Louder = brighter. Short-wavelength notes last a little longer.</li>
          <li><b>Ding:</b> a possible water, CO₂, methane, CO or hydrogen band.</li>
          <li><b>Motion:</b> one note per visit. Higher note = moved north, lower = south. Sound to the right = moved west, left = east. Louder = brighter.</li>
        </ul>
      </details>
    </section>
  );
}
