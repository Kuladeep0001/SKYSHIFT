/* Listen tab: a voice conversation about the sky, made for blind and low-vision visitors. No buttons.
 *
 * When the tab opens, SkyShift's voice (lib/voice.js, a calm British "butler") says where we are and what you
 * can say. Then it listens (lib/voiceInput.js) and you just talk: "describe", "play", "motion", "list",
 * "star 2", "go to Vega", "slower", "stop", "repeat", "help"... Anything else is a question, answered from
 * SkyShift's data by the Ask assistant. It never listens while it is talking, so it can't hear itself.
 * Keys work too (P/Space, arrows, D, M, L, N, R, H, T, Esc) for browsers without speech recognition.
 *
 * Sound is 3D (HRTF, best with headphones):
 *   Graph sound (default): one slow gliding note travels along the graph, from the shortest wavelength
 *                          (0.75 µm, in your left ear) to the longest (5 µm, in your right ear).
 *                          Higher note = brighter. Louder = brighter too.
 *   Colour sound:          one note per colour; the note follows the light itself (short wavelength = high note).
 *   A soft "ding" marks a band where water, CO2, methane... may have been seen.
 *   Motion:                one sound travels the way the star moved in the picture: moving left to right, it
 *                          starts in your left ear and slowly crosses to your right; moving up (north), it rises.
 *                          A tick marks each visit. A star that stays put stays in the middle.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import Chart from "chart.js/auto";
import "../voiceChat.css";
import { monthYear, PIX } from "../lib/frames.js";
import { api } from "../lib/api.js";
import { frameNoise, motionCheck, trackStar } from "../lib/motion.js";
import { canListen, listenOnce, micProblem, stopListening } from "../lib/voiceInput.js";
import { bandsPlugin } from "./SpectrumPanel.jsx";
import { getVoice, setVoice, speak, stopSpeaking } from "../lib/voice.js";

/* ------------------------------------------------------------------ sound */
let audio = null;
const ac = () => (audio ||= new (window.AudioContext || window.webkitAudioContext)());
const live = new Set();  // oscillators that are playing, so Stop can silence them

/* Put a sound around the listener's head (HRTF = how real ears hear direction; best with headphones).
   pan: -1 = fully in the left ear, 0 = straight ahead, 1 = right ear. up: -1 below ... 1 above. */
function place(p, pan, up = 0, t = 0, ramp = false) {
  const th = (Math.max(-1, Math.min(1, pan || 0)) * Math.PI) / 2;
  const x = Math.sin(th), y = Math.max(-1, Math.min(1, up || 0)) * 0.8, z = -Math.cos(th);
  if (p.positionX) {
    const f = ramp ? "linearRampToValueAtTime" : "setValueAtTime";
    p.positionX[f](x, t); p.positionY[f](y, t); p.positionZ[f](z, t);
  } else if (p.setPosition) p.setPosition(x, y, z);
}

function out(a, g, pan, up = 0) {
  const p = a.createPanner();
  p.panningModel = "HRTF";
  p.distanceModel = "inverse";
  p.refDistance = 1;
  p.rolloffFactor = 0;          // same loudness wherever it is: only the direction changes
  place(p, pan, up, a.currentTime);
  g.connect(p); p.connect(a.destination);
  return p;
}

function tone(t0, { freq, dur, gain, pan = 0, up = 0, type = "sine" }) {
  const a = ac(), o = a.createOscillator(), g = a.createGain();
  o.type = type;
  o.frequency.value = freq;
  const peak = Math.max(0.0005, gain);
  g.gain.setValueAtTime(0.0001, t0);
  g.gain.exponentialRampToValueAtTime(peak, t0 + Math.min(0.03, dur / 3));
  g.gain.setValueAtTime(peak, t0 + dur * 0.75);
  g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
  o.connect(g); out(a, g, pan, up);
  o.start(t0); o.stop(t0 + dur + 0.05);
  live.add(o); o.onended = () => live.delete(o);
}

/* One continuous note whose pitch, volume and left-right position follow the graph. */
function glide(t0, notes, step) {
  const a = ac(), o = a.createOscillator(), g = a.createGain();
  o.type = "triangle";
  o.connect(g);
  const p = out(a, g, notes[0].pan);
  g.gain.setValueAtTime(0, t0);
  notes.forEach((nt, k) => {
    const t = t0 + k * step;
    if (k === 0) {
      o.frequency.setValueAtTime(nt.freq, t);
      g.gain.linearRampToValueAtTime(nt.gain, t + 0.03);
      place(p, nt.pan, 0, t);
    } else {
      o.frequency.linearRampToValueAtTime(nt.freq, t);
      g.gain.linearRampToValueAtTime(nt.gain, t);
      place(p, nt.pan, 0, t, true);
    }
  });
  const end = t0 + notes.length * step;
  g.gain.linearRampToValueAtTime(0, end + 0.08);
  o.start(t0); o.stop(end + 0.1);
  live.add(o); o.onended = () => live.delete(o);
}

/* One sound that travels through space over `dur` seconds, through each point { t, pan, up, freq, gain }. */
function sweep(t0, notes, dur) {
  const a = ac(), o = a.createOscillator(), g = a.createGain();
  o.type = "triangle";
  o.connect(g);
  const p = out(a, g, notes[0].pan, notes[0].up);
  g.gain.setValueAtTime(0.0001, t0);
  notes.forEach((nt, k) => {
    const t = t0 + nt.t;
    if (k === 0) {
      o.frequency.setValueAtTime(nt.freq, t);
      g.gain.linearRampToValueAtTime(nt.gain, t + 0.3);
      place(p, nt.pan, nt.up, t);
    } else {
      o.frequency.linearRampToValueAtTime(nt.freq, t);
      g.gain.linearRampToValueAtTime(nt.gain, t);
      place(p, nt.pan, nt.up, t, true);
    }
  });
  g.gain.linearRampToValueAtTime(0.0001, t0 + dur + 0.6);
  o.start(t0); o.stop(t0 + dur + 0.7);
  live.add(o); o.onended = () => live.delete(o);
}

function silence() {
  for (const o of live) { try { o.stop(); } catch (_) { /* already stopped */ } }
  live.clear();
}

const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const SPEED = { slow: 0.3, normal: 0.18, fast: 0.1 };            // seconds per point, graph sound (102 points: 18 s)
const COLOUR_SPEED = { slow: 2.4, normal: 1.6, fast: 1 };        // note-length factor, colour sound
const SPEEDS = ["slow", "normal", "fast"];
const NUM = { one: 1, won: 1, two: 2, to: 2, too: 2, three: 3, tree: 3, four: 4, for: 4, five: 5, six: 6, seven: 7, eight: 8, nine: 9, ten: 10 };
let welcomed = false;   // the full welcome (with everything you can say) plays once; later visits get a short one

/* ------------------------------------------------------------ the numbers */
const plainName = (s) => s.replace(/[₀-₉]/g, (c) => "0123456789"["₀₁₂₃₄₅₆₇₈₉".indexOf(c)]);
const num = (v) => (Math.abs(v) >= 100 ? Math.round(v).toLocaleString() : Math.abs(v) < 0.05 ? "about zero" : v.toPrecision(2));
const COMPASS = ["north", "north-east", "east", "south-east", "south", "south-west", "west", "north-west"];
const SCREEN = { north: "up", "north-east": "up and left", east: "left", "south-east": "down and left", south: "down",
  "south-west": "down and right", west: "right", "north-west": "up and right" };

export { trackStar };   // moved to lib/motion.js (shared with the flipbook)

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
export default function Listen({ target, story, F, sel, spec, loading, onPixel, candidates, source, onGo, askContext }) {
  const [caption, setCaption] = useState("");
  const [busy, setBusy] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [cur, setCur] = useState(0);               // which point of the graph we are on
  const [style, setStyle] = useState("graph");
  const [speed, setSpeed] = useState("normal");
  const [log, setLog] = useState([]);              // the conversation so far: { who: "sky" | "you", text }
  const [mic, setMic] = useState("off");           // "listening" | "speaking" | "thinking" | "off"
  const [heard, setHeard] = useState("");          // the words being heard right now
  const talking = useRef(0);                       // sentences being spoken now (never listen meanwhile)
  const lastSaid = useRef("");
  const spoke = useRef(false);                     // said something since the last chime
  const convo = useRef(0);                         // conversation run id; bumped to end it
  const logEnd = useRef(null);
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
  const say = async (text) => {      // on screen + spoken; resolves when the voice has finished
    setCaption(text);
    lastSaid.current = text;
    spoke.current = true;
    setLog((l) => [...l.slice(-40), { who: "sky", text }]);
    stopListening();                 // don't hear our own voice
    talking.current++;
    setMic("speaking");
    try { await speak(text, getVoice() === "off" ? { voice: "butler" } : {}); } finally {
      talking.current--;
      if (!talking.current) setMic((m) => (m === "speaking" ? "off" : m));
    }
  };
  const sayNow = (text) => { say(text); };   // for quick stepping (speak() drops whatever was being said)

  const halt = () => {
    gen.current++;
    stopSpeaking();
    silence();
    if (play.current) cancelAnimationFrame(play.current.raf);
    play.current = null;
    graphRun.current = false;
    setPlaying(false); setBusy(false);
  };
  useEffect(() => () => { convo.current++; stopListening(); halt(); }, []);
  useEffect(() => { logEnd.current && logEnd.current.scrollIntoView({ block: "nearest" }); }, [log, heard]);

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
    sayNow(pts.length >= 5 ? `${what} is ready. Say play to hear its graph, or motion to hear how it moves.` : `${what}: there isn't enough data here to make a graph. Say list to hear other stars.`);
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
    if (pts.length < 5) return say("There isn't enough data at this spot to play a graph. Say list to hear other stars you can pick.");
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
    sayNow(mid ? `Paused at ${pts[cur]?.wave.toFixed(2)} microns. Say play to carry on.` : "Stopped. Say play to hear the graph.");
  };

  const describe = () => run(async () => {
    if (!F) return say("The pictures are still loading.");
    const first = F.list[0], last = F.list[F.list.length - 1];
    await say(`${name}. ${story ? story.story : ""} SkyShift has ${F.data.length} infrared pictures of this small patch of sky, ` +
      `taken by NASA's SPHEREx telescope between ${monthYear(first.date_range?.[0] || first.date.slice(0, 10))} and ${monthYear(last.date_range?.[0] || last.date.slice(0, 10))}. ` +
      `${choices.length > 1 ? `Besides the centre, there are ${choices.length - 1} other objects here; say list to hear them. ` : ""}` +
      `${summary ? summary + " " : ""}Say play to hear the graph, or motion to hear how it moves.`);
  });

  const motion = () => run(async (dead) => {
    if (!F || F.data.length < 2) return say("This spot needs at least two visits to hear any motion.");
    const x0 = sel ? sel.x : c, y0 = sel ? sel.y : c;
    const tr = trackStar(F, x0, y0);
    const chk = motionCheck({ F, path: tr, noise: frameNoise(F), isTarget: !sel, target, candidates, cx0: x0, cy0: y0 });
    if (!chk.real) return say("There's no clear star at this spot to follow. Say list to hear the stars you can pick.");
    const p0 = tr[0], pl = tr[tr.length - 1], f0 = p0.flux || 1;
    const dx = pl.x - p0.x, dy = pl.y - p0.y, dd = Math.hypot(dx, dy) || 1;
    const ux = chk.moving ? dx / dd : 0, uy = chk.moving ? dy / dd : 0;   // picture directions: right (west), up (north)
    const d0 = monthYear(p0.date), d1 = monthYear(pl.date);
    const lr = ux > 0.35 ? "from your left ear across to your right ear" : ux < -0.35 ? "from your right ear across to your left ear" : "";
    const ud = uy > 0.35 ? "rising, because it moved up the picture, to the north" : uy < -0.35 ? "falling, because it moved down the picture, to the south" : "";
    await say(chk.moving
      ? `Listening to how ${who} moves. Headphones help. One sound starts where it was in ${d0} and slowly travels to where it was in ${d1}: ${[lr, ud].filter(Boolean).join(", and ")}. A soft tick marks each visit.`
      : `Listening to ${who}. Headphones help. If it moved, the sound would travel from one ear to the other. A soft tick marks each visit.`);
    if (dead()) return;
    const DUR = 8, span = (pl.mjd - p0.mjd) || 1;
    const notes = tr.map((p) => {
      const fr = Math.max(0, Math.min(1, (p.mjd - p0.mjd) / span));
      return { t: fr * DUR, pan: ux * (-0.95 + 1.9 * fr), up: uy * (-0.8 + 1.6 * fr), freq: 330 * Math.pow(2, (uy * (fr - 0.5) * 7) / 12),
        gain: Math.min(0.45, Math.max(0.05, 0.22 * Math.sqrt(Math.max(0.01, p.flux / f0)))) };
    });
    const t0 = ac().currentTime + 0.15;
    sweep(t0, notes, DUR);
    notes.forEach((nt) => tone(t0 + nt.t, { freq: 1700, dur: 0.05, gain: 0.1, pan: nt.pan, up: nt.up }));
    setPlaying(true);
    await wait(DUR * 1000 + 800);
    setPlaying(false);
    if (dead()) return;
    const years = (pl.mjd - p0.mjd) / 365.25;
    const total = Math.hypot(dx, dy) * PIX;
    const ratios = tr.map((p) => p.flux / f0), bright = Math.max(...ratios), dim = Math.max(1e-3, Math.min(...ratios));
    let s = chk.moving
      ? `It moved about ${total.toFixed(0)} arcseconds toward the ${direction(dx, dy)} in ${years.toFixed(1)} years. That shift is tiny in the picture, so the sound makes it bigger for your ears. Most stars barely move at all, so this one is fast. `
      : "It stayed in the same place, so the sound stayed in front of you. ";
    s += bright / dim > 1.3 ? `Its brightness changed: the brightest visit was ${(bright / dim).toFixed(1)} times brighter than the faintest, which is why the sound got louder or quieter.` : "Its brightness stayed about the same.";
    await say(s + " Say motion to hear it again.");
  });

  const choose = (ch) => {
    halt();
    announce.current = ch.short;
    onPixel(ch.x, ch.y);
    sayNow(`${ch.label}. One moment.`);
  };

  /* ------------------------------------------------------ the conversation */
  const helpText = (keys = !canListen) => keys
    ? "Here are the keys. P or space: play or pause the graph. Left and right arrows: one point at a time. D: describe this place. " +
      "M: hear how it moves. L: list the stars here, and N: the next star. R: repeat. H: help. T: talk to me. Escape: stop."
    : "Here is what you can say. " +
      "Describe: I shall tell you about this place. " +
      "Play: you will hear its brightness graph, from your left ear to your right. " +
      "Motion: you will hear how it moves across the sky. " +
      "List: I shall name the other stars here, and you may pick one by saying, for example, star two. " +
      "Next, or back: one point of the graph at a time. " +
      "Go to, and a star's name, to travel somewhere else, for example, go to Vega. " +
      "Slower, or faster. Stop. Repeat. And help, to hear this list again. " +
      "You may also simply ask me a question, such as, how far away is it? " +
      "When I am talking, press Escape to stop me. After the soft chime, I am listening.";
  const listText = () => choices.length
    ? `There are ${choices.length} things to listen to here. ${choices.map((ch) => ch.label).join(". ")}. Say the one you want, like ${choices.length > 1 ? choices[1].short.toLowerCase() : "centre"}, or centre.`
    : "The pictures are still loading.";
  // Opening: the commands first, then only where we are. Nothing about the place is read until you ask.
  const welcomeText = () => {
    if (welcomed) return `We have arrived at ${name}. What would you like to do? Say help to hear the commands.`;
    welcomed = true;
    return canListen
      ? `Good day, and welcome to SkyShift's listening mode. I shall be your guide, and you can simply talk to me. ${helpText(false)} We are at ${name}. What would you like to do?`
      : `Good day, and welcome to SkyShift's listening mode. This browser can't hear voice commands, so please use the keys. Chrome or Edge can hear you. ${helpText(true)} We are at ${name}.`;
  };
  const pickChoice = (ch) => (ch ? choose(ch) : say("I couldn't find that one. Say list to hear what's here."));
  const askAbout = async (q) => {
    setMic("thinking");
    try {
      const r = await api.ask(q, askContext || { name });
      await say(r.answer);
    } catch (_) {
      await say("I'm afraid I couldn't find an answer to that. Say help to hear what you can say.");
    }
  };
  const travel = async (where) => {
    halt();
    await say(`Certainly. Looking for ${where}.`);
    try {
      const r = await api.resolve(where);
      const nm = (r.name || where).replace(/^NAME /, "");
      await say(`Found it. Off we go to ${nm}. Fetching its pictures can take up to a minute; I shall tell you when we have arrived.`);
      onGo && onGo(where);
    } catch (_) {
      await say(`I'm afraid I couldn't find ${where}. Perhaps try another name, like Vega or Barnard's Star.`);
    }
  };

  /* What did they say? Commands first, then anything else is a question for the Ask assistant. */
  function handle(raw) {
    const t = ` ${raw.toLowerCase().replace(/[^a-z0-9' ]/g, " ").replace(/\s+/g, " ").trim()} `;
    const any = (...w) => w.some((x) => t.includes(` ${x} `));
    const curPick = choices.findIndex((ch) => ch === picked);
    const wasPlaying = !!play.current;
    halt();                                       // whatever you say ends what was going on
    if (any("stop", "pause", "quiet", "silence", "enough", "shut up", "hold on", "wait")) return sayNow(wasPlaying ? "Very good, paused. Say play to carry on." : "Very good. What would you like next?");
    if (any("help", "commands", "what can i say", "what can i do", "options")) return say(helpText(false));
    if (any("repeat", "pardon", "say that again", "say it again", "come again", "what did you say") || t === " again ") return say(lastSaid.current || helpText(false));
    if (any("keys", "keyboard", "shortcuts")) return say(helpText(true));
    const goTo = t.match(/^ (?:please )?(?:go to|take me to|fly to|travel to|let's go to|lets go to|load|open|find|search for|show me) (.+) $/);
    if (any("slower", "slow down", "too fast", "more slowly")) {
      const k = SPEEDS.indexOf(speed);
      if (k <= 0) return say("This is already the slowest.");
      halt(); setSpeed(SPEEDS[k - 1]); return say("Certainly, a little slower. Say play to hear it.");
    }
    if (any("faster", "speed up", "too slow", "quicker")) {
      const k = SPEEDS.indexOf(speed);
      if (k >= SPEEDS.length - 1) return say("This is already the fastest.");
      halt(); setSpeed(SPEEDS[k + 1]); return say("Certainly, a little faster. Say play to hear it.");
    }
    if (any("colour sound", "color sound", "colours", "colors", "colour", "color")) { halt(); setStyle("colour"); setCur(0); return say("Colour sound: one note per colour, high notes for short wavelengths. Say play to hear it."); }
    if (any("graph sound", "normal sound", "line sound")) { halt(); setStyle("graph"); setCur(0); return say("Graph sound: one gliding note, higher means brighter. Say play to hear it."); }
    if (any("change voice", "change the voice", "other voice", "another voice", "different voice", "new voice")) {
      const v = getVoice() === "friendly" ? "butler" : "friendly";
      setVoice(v);
      return say(v === "butler" ? "Very good. I shall carry on in this voice." : "Okay! I'll talk to you in this voice from now on.");
    }
    const num = t.match(/ (?:star|number|object|option) (\d+|one|won|two|to|too|three|tree|four|for|five|six|seven|eight|nine|ten) /);
    if (num) { const k = +num[1] || NUM[num[1]]; return pickChoice(choices.find((ch) => ch.short === `Star ${k}`)); }
    const strong = any("what is this", "what's this", "whats this", "what am i looking at", "what am i hearing", "where am i", "which stars", "what stars",
      "what else", "what's here", "whats here", "how does it move", "is it moving", "does it move", "did it move");
    if (/^ (what|why|how|who|when|where|which|is|are|does|do|did|can|could|would|will|should|tell me about) /.test(t) && !strong) return askAbout(raw);
    if (any("centre", "center", "middle", "main star", "the target", "go back")) return pickChoice(choices[0]);
    if (any("moving object", "changing object", "the mover", "new object")) return pickChoice(choices.find((ch) => ch.key.startsWith("cand-")));
    if (any("next star", "next object", "another star", "next one", "other star")) return pickChoice(choices[(curPick + 1) % Math.max(1, choices.length)]);
    if (any("previous star", "previous object", "last star")) return pickChoice(choices[(curPick - 1 + choices.length) % Math.max(1, choices.length)]);
    if (any("list", "which stars", "what stars", "what else", "what's here", "whats here", "objects", "stars")) return say(listText());
    if (goTo && !any("motion", "move", "moves", "moving", "graph", "spectrum", "list", "stars")) {
      const m = raw.trim().replace(/[.!?]+$/, "").match(/(?:go to|take me to|fly to|travel to|let's go to|lets go to|load|open|find|search for|show me)\s+(.+)$/i);
      return travel((m ? m[1] : goTo[1]).replace(/^the star\s+/i, ""));
    }
    if (any("motion", "move", "moves", "moving", "moved", "movement", "shift", "how does it move")) return motion();
    if (any("describe", "what is this", "what's this", "whats this", "what am i looking at", "where am i", "about this", "about it", "tell me")) return describe();
    if (any("play", "graph", "spectrum", "brightness", "continue", "carry on", "resume", "start", "listen")) return playGraph();
    if (any("first point", "beginning", "the start")) return stepTo(0);
    if (any("last point", "the end")) return stepTo(pts.length - 1);
    if (any("next", "forward", "right")) return stepTo(cur + 1);
    if (any("back", "previous", "left")) return stepTo(cur - 1);
    if (any("hello", "hi", "hey", "good morning", "good evening", "good afternoon")) return say(`Hello. We are at ${name}. How may I help? Say help to hear the commands.`);
    if (any("thank you", "thanks")) return say("You are most welcome.");
    return askAbout(raw);
  }

  const busyRef = useRef(false);
  busyRef.current = busy || playing;
  const latest = useRef({});
  latest.current = { handle, say, welcomeText };
  async function conversation() {
    const my = ++convo.current;
    let quiet = 0;
    while (convo.current === my) {
      while (talking.current > 0 && convo.current === my) await wait(150);    // never listen while talking
      if (convo.current !== my) return;
      if (spoke.current) {                                                      // your turn: a soft rising chime
        spoke.current = false;
        try { await ac().resume(); const t = ac().currentTime + 0.02; tone(t, { freq: 880, dur: 0.12, gain: 0.08 }); tone(t + 0.12, { freq: 1320, dur: 0.16, gain: 0.08 }); } catch (_) { /* no sound */ }
        await wait(320);
        if (convo.current !== my || talking.current) continue;
      }
      setMic("listening"); setHeard("");
      const text = await listenOnce({ onHeard: (h) => setHeard(h) });
      if (convo.current !== my) return;
      setHeard("");
      if (text === null) {
        if (micProblem) {
          convo.current++;
          setMic("off");
          await latest.current.say(micProblem === "blocked"
            ? "I can't use the microphone because it's blocked for this site. Allow the microphone and press T, or use the keys. Press H to hear them."
            : "I can't find a microphone. You can use the keys instead. Press H to hear them.");
          return;
        }
        await wait(300);                                                        // interrupted by our own speech: listen again after
        continue;
      }
      if (!text) {
        if (busyRef.current || talking.current) { quiet = 0; continue; }          // sound playing or something running: just keep listening
        if (++quiet === 4) await latest.current.say("I am still here, listening. Say help to hear the commands.");
        continue;
      }
      quiet = 0;
      setLog((l) => [...l.slice(-40), { who: "you", text }]);
      latest.current.handle(text);                                              // not awaited: you can say "stop" while sound plays
      await wait(400);
    }
  }
  const startTalking = () => { if (canListen) conversation(); };

  // Opening the tab: say where we are and what you can say, then listen.
  useEffect(() => {
    let alive = true;
    (async () => {
      await wait(400);
      if (!alive) return;
      await latest.current.say(latest.current.welcomeText());
      if (alive) startTalking();
    })();
    return () => { alive = false; };
  }, []);

  /* keyboard: P or Space play/pause, arrows step, Home/End, D describe, M motion, L list, N next star, R repeat, H help, T talk, Escape stop */
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
      else if (key === "l" || key === "L") say(listText());
      else if (key === "n" || key === "N") pickChoice(choices[(choices.findIndex((ch) => ch === picked) + 1) % Math.max(1, choices.length)]);
      else if (key === "r" || key === "R") say(lastSaid.current || helpText());
      else if (key === "h" || key === "H") say(helpText(true));
      else if (key === "t" || key === "T") { halt(); startTalking(); }
      else if (key === "Escape") { halt(); setCaption("Stopped."); }
    };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  });

  const sat = spec && spec.saturated_fraction > 0.5;
  return (
    <section className="listenTab" aria-labelledby="listenTitle">
      <h2 id="listenTitle">Listen to the sky</h2>
      <p className="lead">Made for blind and low-vision visitors: just talk. SkyShift tells you what you can say, then listens.
        Say <i>describe</i>, <i>play</i>, <i>motion</i>, <i>list</i>, <i>go to</i> a star, <i>stop</i> or <i>help</i>, or ask any question.
        Use headphones: the sound moves around your head.</p>

      <div className={`voiceState ${mic}`} role="status" aria-live="off">
        <span className="voiceDot" aria-hidden="true" />
        <span>{mic === "listening" ? (heard ? `Hearing: "${heard}"` : "Listening… speak now")
          : mic === "speaking" ? "Speaking…" : mic === "thinking" ? "Thinking…"
            : canListen ? (playing ? "Playing sound…" : "Press T to talk") : "Voice commands need Chrome or Edge: use the keys below"}</span>
      </div>

      <p className="caption big" aria-live="off">
        {caption || (loading ? "Loading the graph…" : "One moment…")}
      </p>

      <div className="voiceLog" aria-label="Conversation">
        {log.map((m, k) => <p key={k} className={`vmsg ${m.who}`}><b>{m.who === "you" ? "You" : "SkyShift"}</b>{m.text}</p>)}
        <span ref={logEnd} />
      </div>

      <figure className="listenGraph">
        <figcaption>Brightness (flux) of <b>{who}</b> at each infrared wavelength</figcaption>
        <div className="chartBox listenChart">
          <canvas ref={canvas} role="img" aria-label={summary || "The graph is loading."} />
        </div>
        <p className="srcLine">Data: {source || "NASA SPHEREx via IRSA"}</p>
        {sat && <p className="note warn">This star is so bright it overloads SPHEREx's camera, so these values are lower limits. Pick a fainter star for a clean graph.</p>}
        {pts[cur] && <p className="readout" aria-hidden="true">{pts[cur].wave.toFixed(2)} µm · {num(pts[cur].flux)} µJy{featureAt(pts[cur].wave) ? ` · ${featureAt(pts[cur].wave).name} band` : ""}</p>}
      </figure>

      <ul className="keys" aria-label="Keyboard shortcuts">
        <li><kbd>T</kbd> talk to SkyShift (it listens after every answer)</li>
        <li><kbd>P</kbd> or <kbd>Space</kbd> play or pause the graph</li>
        <li><kbd>←</kbd> <kbd>→</kbd> one point at a time</li>
        <li><kbd>D</kbd> describe · <kbd>M</kbd> motion · <kbd>L</kbd> list the stars · <kbd>N</kbd> next star</li>
        <li><kbd>R</kbd> repeat · <kbd>H</kbd> help · <kbd>Esc</kbd> stop</li>
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
          <li><b>Graph sound:</b> one slow note slides along the graph from left (short wavelength, left ear) to right (long wavelength, right ear). Higher and louder = brighter. Dips sound like the note dropping.</li>
          <li><b>Colour sound:</b> one note per colour. High notes are short wavelengths and low notes are long ones, like the light itself. Louder = brighter. Short-wavelength notes last a little longer.</li>
          <li><b>Ding:</b> a possible water, CO₂, methane, CO or hydrogen band.</li>
          <li><b>Motion:</b> one sound travels the way the star moved in the picture. Moving left to right, it starts in your left ear and slowly crosses to your right; moving up (north), it rises. A tick marks each visit. Louder = brighter. A star that stays put stays in front of you.</li>
          <li><b>3D sound:</b> the sounds are placed around your head the way real ears hear direction (HRTF). Use headphones.</li>
        </ul>
      </details>
    </section>
  );
}
