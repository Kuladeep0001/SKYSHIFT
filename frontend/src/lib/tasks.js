/* Shared list of everything SkyShift is downloading or working on, for the task bar.
 *
 * Any part of the site can add a task:
 *   const t = startTask({ label: "Making the GIF", total: 12, unit: "frames", onCancel })
 *   t.update({ done: 3 })   t.finish()   t.fail("message")
 * Every backend request made through lib/api.js is added automatically (see trackRequest), each with
 * its own progress bar and Cancel button. Tasks that finish in under half a second are never shown,
 * so quick cached answers don't make the bar flicker.
 */
import { useEffect, useState } from "react";

const SHOW_AFTER_MS = 500;   // only show tasks that take a moment
const KEEP_DONE_MS = 1600;   // a finished task shows ✓ briefly
const KEEP_FAILED_MS = 6000; // a failed one stays a bit longer

let tasks = [];
let seq = 0;
const subs = new Set();
const emit = () => { const snap = tasks.slice(); subs.forEach((f) => f(snap)); };

function patch(id, changes) {
  tasks = tasks.map((t) => (t.id === id ? { ...t, ...changes } : t));
  emit();
}

function remove(id) {
  tasks = tasks.filter((t) => t.id !== id);
  emit();
}

export function startTask({ label, detail = "", kind = "download", total = 0, unit = "", onCancel = null, group = null }) {
  const id = `t${++seq}`;
  tasks = [...tasks, { id, label, detail, kind, total, unit, done: 0, group: group || label, onCancel,
    startedAt: Date.now(), status: "running", visible: false }];
  const reveal = setTimeout(() => { if (tasks.some((t) => t.id === id && t.status === "running")) patch(id, { visible: true }); }, SHOW_AFTER_MS);
  const end = (status, extra, keep) => {
    clearTimeout(reveal);
    const t = tasks.find((x) => x.id === id);
    if (!t || t.status !== "running") return;
    if (!t.visible) { remove(id); return; }      // finished before anyone saw it
    patch(id, { status, endedAt: Date.now(), ...extra });
    setTimeout(() => remove(id), keep);
  };
  return {
    id,
    update: (changes) => patch(id, changes),
    finish: () => end("done", {}, KEEP_DONE_MS),
    fail: (message) => end("failed", { detail: message || "failed" }, KEEP_FAILED_MS),
    cancelled: () => end("cancelled", { detail: "cancelled" }, KEEP_DONE_MS),
  };
}

export function useTasks() {
  const [list, setList] = useState(tasks);
  useEffect(() => { subs.add(setList); setList(tasks.slice()); return () => subs.delete(setList); }, []);
  return list;
}

/* What each backend address is, in plain words (null = don't show it as a task). */
const LABELS = [
  [/^\/api\/images\/query$/, null],                                    // the main download has its own bar
  [/^\/api\/images\/[^/]+$/, null],                                    // progress polling
  [/^\/api\/images\/[^/]+\/(check|cancel)$/, null],
  [/^\/api\/images\/[^/]+\/frames\?.*mode=visitdet/, ["Colour data from all 6 detectors", "🎨"]],
  [/^\/api\/images\/[^/]+\/frames\?.*mode=channel/, ["Pictures in one infrared colour", "🌈"]],
  [/^\/api\/images\/[^/]+\/frames\?.*mode=exposure/, ["Every single snapshot", "🖼"]],
  [/^\/api\/images\/[^/]+\/frames/, ["Pictures for the viewer", "🖼"]],
  [/^\/api\/images\/[^/]+\/spectrum/, ["Spectrum of the selected spot", "📈"]],
  [/^\/api\/images\/[^/]+\/cube/, ["Spectral cube (102 colours)", "🧊"]],
  [/^\/api\/images\/[^/]+\/history/, ["Old sky photos (1950–2010) for the time machine", "⏳"]],
  [/^\/api\/images\/[^/]+\/asteroids/, ["Known asteroids in every snapshot (IMCCE)", "☄️"]],
  [/^\/api\/images\/compare/, ["Before / after comparison", "⇔"]],
  [/^\/api\/detections\/run/, ["Looking for moving or changing things", "🔎"]],
  [/^\/api\/detections\/features/, ["Molecule finder", "💧"]],
  [/^\/api\/verification\/gaia/, ["Checking finds against Gaia, WISE and SIMBAD", "✔️"]],
  [/^\/api\/verification\/$/, ["Checking 4 star catalogues (Gaia, 2MASS, AllWISE, SIMBAD)", "🔬"]],
  [/^\/api\/catalog\/gaia/, ["Gaia stars for the overlay", "✨"]],
  [/^\/api\/catalog\/allwise/, ["WISE sources for the overlay", "✨"]],
  [/^\/api\/catalog\/skybot/, ["Asteroids at this date (overlay)", "☄️"]],
  [/^\/api\/object/, ["Object details (SIMBAD, Gaia, WISE, Wikipedia)", "🃏"]],
  [/^\/api\/ask$/, ["Answering your question", "💬"]],
  [/^\/api\/metadata\//, ["Picture details (metadata)", "📋"]],
  [/^\/api\/resolve/, ["Looking up the name", "🔤"]],
  [/^\/api\/finds/, ["Discovery board", "🔭"]],
  [/^\/api\/validation/, ["Checking SkyShift's accuracy on the 5 challenge targets", "📏"]],
];

export function labelFor(path) {
  if (!path.startsWith("/api/")) return null;
  for (const [re, label] of LABELS) if (re.test(path)) return label;
  return null;
}

/* Wrap one fetch: its own task, its own Cancel (aborts the download). */
export async function trackRequest(path, opts, run) {
  const lab = labelFor(path);
  if (!lab) return run(opts);
  const ctrl = new AbortController();
  if (opts.signal) opts.signal.addEventListener("abort", () => ctrl.abort());
  const t = startTask({ label: lab[0], kind: lab[1], onCancel: () => ctrl.abort() });
  try {
    const res = await run({ ...opts, signal: ctrl.signal });
    t.finish();
    return res;
  } catch (e) {
    if (e && e.name === "AbortError") {
      t.cancelled();
      const err = new Error("Cancelled.");
      err.cancelled = true;
      throw err;
    }
    t.fail(e && e.message);
    throw e;
  }
}
