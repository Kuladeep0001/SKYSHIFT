/* Reading aloud in a natural, human-sounding voice (Listen tab, guided tour, "Ask" answers).
 *
 * Default voice: "butler", a calm, unhurried older British gentleman. It is a neural voice made on our
 * server (GET /api/voice), so it sounds like a person, with natural pauses and expression.
 * If the server voice can't be reached (offline, mock mode), this device's own voice is used instead,
 * picking a British male voice when the device has one.
 *
 *   speak(text)      say it (stops whatever was being said); the promise resolves when it has finished
 *   stopSpeaking()   be quiet now
 */
const KEY = "skyshift-voice";
export const VOICES = [
  { id: "butler", label: "British butler: calm, older gentleman" },
  { id: "friendly", label: "Friendly British narrator" },
  { id: "device", label: "This device's own voice (works offline)" },
  { id: "off", label: "Off (I use a screen reader)" },
];
const MOCK = new URLSearchParams(location.search).get("mock") === "1" || import.meta.env.VITE_MOCK === "1";

let chosen = "butler";
try { chosen = localStorage.getItem(KEY) || "butler"; } catch (_) { /* private mode */ }
if (!VOICES.some((v) => v.id === chosen)) chosen = "butler";
export const getVoice = () => chosen;
export function setVoice(id) {
  chosen = id;
  try { localStorage.setItem(KEY, id); } catch (_) { /* private mode */ }
}

/* Say symbols and short forms the way a person would read them. */
export function forSpeech(t) {
  return String(t || "")
    .replace(/SPHEREx/g, "Sphere X")
    .replace(/\bDR(\d)\b/g, "Data Release $1").replace(/\bQR(\d)\b/g, "Quick Release $1")
    .replace(/µm\b/g, " microns").replace(/µJy\b/g, " micro-janskys")
    .replace(/(\d)\s*″/g, "$1 arcseconds").replace(/(\d)\s*′/g, "$1 arcminutes")
    .replace(/(\d)\s*°\s*C\b/g, "$1 degrees Celsius").replace(/(\d)\s*°/g, "$1 degrees")
    .replace(/−(?=\d)/g, "minus ")
    .replace(/(\d)\s*–\s*(\d)/g, "$1 to $2")
    .replace(/km\/s\b/g, "kilometres per second").replace(/mas\/yr\b/g, "milliarcseconds per year")
    .replace(/\be\.g\.\s*/g, "for example, ").replace(/\bi\.e\.\s*/g, "that is, ")
    .replace(/≈/g, " about ").replace(/±/g, " plus or minus ").replace(/×/g, " times ").replace(/→/g, " to ")
    .replace(/·/g, ", ").replace(/[←↗▾▸▲▼✓✕↔]/g, " ")
    .replace(/\s+([,.;:!?])/g, "$1").replace(/\s+/g, " ").trim();
}

/* The device voice that sounds most like a British gentleman. */
function deviceVoice() {
  const rank = (v) => {
    if (!/^en/i.test(v.lang)) return -99;
    let s = 0;
    if (/en[-_]GB/i.test(v.lang)) s += 4;
    if (/natural|neural|online/i.test(v.name)) s += 3;
    if (/Thomas|Ryan|George|Daniel|Arthur|Oliver|UK English Male|\bMale\b/i.test(v.name)) s += 2;
    if (/Libby|Sonia|Maisie|Hazel|Susan|Kate|Serena|Female/i.test(v.name)) s -= 2;
    return s;
  };
  const vs = window.speechSynthesis.getVoices().filter((v) => rank(v) > -99);
  return vs.sort((a, b) => rank(b) - rank(a))[0] || null;
}
if (typeof window !== "undefined" && "speechSynthesis" in window) window.speechSynthesis.getVoices();  // start loading the list

/* Long text is spoken a few sentences at a time: the first part starts sooner, and the next part is
   fetched while this one plays. Splits only at a full stop followed by a space (not inside "0.75"). */
function parts(text) {
  const out = [];
  let acc = "";
  for (const s of text.split(/(?<=[.!?])\s+/)) {
    if (acc && (acc + " " + s).length > 260) { out.push(acc); acc = s; } else acc = acc ? acc + " " + s : s;
  }
  if (acc) out.push(acc);
  return out;
}

let token = 0;
let cur = null;   // what is speaking now: { my, audio?, next?, finish }

const drop = (a) => { if (a) { try { a.pause(); a.removeAttribute("src"); a.load(); } catch (_) { /* already gone */ } } };

export function stopSpeaking() {
  token++;
  const c = cur;
  cur = null;
  if (c) { drop(c.audio); drop(c.next); c.finish(); }
  if ("speechSynthesis" in window) window.speechSynthesis.cancel();
}

export function speak(raw, opts = {}) {
  stopSpeaking();
  const id = opts.voice || chosen, text = forSpeech(raw), my = token;
  return new Promise((resolve) => {
    if (!text || id === "off") return resolve();
    let done = false;
    const finish = () => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      if (cur && cur.my === my) cur = null;
      resolve();
    };
    const timer = setTimeout(finish, 15000 + text.length * 120);   // never get stuck waiting for an "end"
    const device = (t) => {
      if (my !== token || done) return finish();
      if (!("speechSynthesis" in window)) return finish();
      const u = new SpeechSynthesisUtterance(t);
      const v = deviceVoice();
      if (v) { u.voice = v; u.lang = v.lang; }
      u.rate = 0.92;
      u.pitch = id === "butler" ? 0.85 : 1;
      u.onend = u.onerror = finish;
      cur = { my, finish };
      window.speechSynthesis.speak(u);
    };
    if (id === "device" || MOCK) return device(text);

    const P = parts(text);
    const load = (k) => { const a = new Audio(); a.preload = "auto"; a.src = `/api/voice?v=${encodeURIComponent(id)}&text=${encodeURIComponent(P[k])}`; return a; };
    let i = 0, fell = false;
    const fallBack = () => {                    // server voice unavailable: the device's voice says the rest
      if (fell || done || my !== token) return;
      fell = true;
      if (cur) { drop(cur.audio); drop(cur.next); }
      cur = null;
      device(P.slice(i).join(" "));
    };
    const play = (a) => {
      if (my !== token || done) return;
      const next = i + 1 < P.length ? load(i + 1) : null;
      cur = { my, audio: a, next, finish };
      a.onerror = fallBack;
      a.onended = () => { if (my !== token || done) return; i++; if (i >= P.length) finish(); else play(next); };
      a.play().catch((e) => { if (!(e && e.name === "AbortError")) fallBack(); });
    };
    play(load(0));
  });
}
