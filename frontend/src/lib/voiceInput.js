/* Hearing the visitor: the browser's speech recognition (Chrome, Edge, Safari; not Firefox).
 *
 *   listenOnce({ onHeard })   resolves with what was said ("" = nothing heard, null = stopped or not possible)
 *   stopListening()           stop now (used before SkyShift speaks, so it never hears its own voice)
 *   micProblem                why the microphone can't be used, once that is known ("blocked", "none", "unsupported")
 */
const SR = typeof window !== "undefined" && (window.SpeechRecognition || window.webkitSpeechRecognition);
export const canListen = !!SR;
export let micProblem = SR ? "" : "unsupported";

let rec = null;

export function stopListening() {
  const r = rec;
  rec = null;
  if (r) { try { r.abort(); } catch (_) { /* already stopped */ } }
}

export function listenOnce({ onHeard } = {}) {
  stopListening();
  if (!SR) return Promise.resolve(null);
  return new Promise((resolve) => {
    const r = new SR();
    rec = r;
    r.lang = /^en/i.test(navigator.language || "") ? navigator.language : "en-US";
    r.interimResults = true;
    r.continuous = false;
    r.maxAlternatives = 1;
    let text = "", done = false, failed = false;
    const finish = (v) => { if (!done) { done = true; if (rec === r) rec = null; resolve(v); } };
    r.onresult = (e) => {
      let fin = "", live = "";
      for (let k = 0; k < e.results.length; k++) {
        const t = e.results[k][0].transcript;
        if (e.results[k].isFinal) fin += t; else live += t;
      }
      text = (fin || live).trim();
      onHeard && onHeard(text, !!fin);
    };
    r.onerror = (e) => {
      failed = true;
      if (e.error === "not-allowed" || e.error === "service-not-allowed") micProblem = "blocked";
      else if (e.error === "audio-capture") micProblem = "none";
      finish(e.error === "no-speech" ? "" : null);
    };
    r.onend = () => finish(failed ? null : text);
    try { r.start(); } catch (_) { finish(null); }
  });
}
