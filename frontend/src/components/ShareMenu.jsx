/* Share: animated GIF of the flipbook, a picture card for social media, a link, or embed code. */
import { useState } from "react";
import { applyPalette, GIFEncoder, quantize } from "gifenc";
import { monthYear, percentile } from "../lib/frames.js";
import { LUTS, makeScaler, paint, paintRGBLight } from "../lib/render.js";
import { startTask } from "../lib/tasks.js";

const SIZE = 480;

function stamp(ctx, w, lines) {
  ctx.fillStyle = "rgba(4,5,10,.74)";
  ctx.fillRect(0, 0, w, 52);
  ctx.fillStyle = "#fff"; ctx.font = "700 22px Inter, sans-serif"; ctx.fillText(lines[0], 12, 26);
  ctx.fillStyle = "#d4d4dc"; ctx.font = "13px Inter, sans-serif"; ctx.fillText(lines[1] || "", 12, 45);
  ctx.fillStyle = "rgba(4,5,10,.74)"; ctx.fillRect(0, w - 24, w, 24);
  ctx.fillStyle = "#ffa31a"; ctx.font = "600 12px Inter, sans-serif"; ctx.fillText("Data: NASA SPHEREx via IRSA · SkyShift", 10, w - 8);
}

function download(blob, name) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 5000);
}

async function shareOrDownload(blob, name, title, text, url, say) {
  const file = new File([blob], name, { type: blob.type });
  if (navigator.canShare && navigator.canShare({ files: [file] })) {
    try { await navigator.share({ files: [file], title, text, url }); return; } catch (_) { /* cancelled: fall back */ }
  }
  download(blob, name);
  say && say("Saved to your downloads.");
}

function wrap(ctx, text, x, y, maxW, lh, maxLines) {
  const words = (text || "").split(" ");
  let line = "", n = 0;
  for (const w of words) {
    if (ctx.measureText(line + w).width > maxW && line) {
      ctx.fillText(line, x, y); y += lh; line = ""; if (++n >= maxLines - 1) { ctx.fillText(words.slice(words.indexOf(w)).join(" ").slice(0, 60) + "…", x, y); return y + lh; }
    }
    line += w + " ";
  }
  ctx.fillText(line, x, y);
  return y + lh;
}

export default function ShareMenu({ F, disp, target, story, facts, shareURL, say, rgb }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState("");
  const name = (target?.name || "sky").replace(/\W+/g, "_");

  async function gif() {
    if (!F || !F.data.length) return say("Open the Flipbook first.");
    setBusy("Making GIF…");
    let stopped = false;
    const task = startTask({ label: "Making the animated GIF", kind: "", total: F.data.length, unit: "frames", onCancel: () => { stopped = true; } });
    try {
      const [lo, hi] = percentile(F.data, [3, 99.8]);
      const sets = rgb ? F.list.map((f) => rgb[f.visit]) : [];
      const rl = sets.length && sets.every(Boolean) ? [0, 1, 2].map((c) => percentile(sets.map((s) => s[c]), [45, 99.7])) : null;
      const sc = makeScaler(lo, hi, disp.contrast, disp.bright);
      const c = document.createElement("canvas"); c.width = c.height = SIZE;
      const ctx = c.getContext("2d");
      const enc = GIFEncoder();
      for (let k = 0; k < F.data.length; k++) {
        if (stopped) { task.cancelled(); say("GIF cancelled."); return; }
        task.update({ done: k });
        if (rl) paintRGBLight(c, sets[k][0], sets[k][1], sets[k][2], F.n, rl, disp.contrast, disp.bright);
        else paint(c, F.data[k], F.n, sc, (LUTS[disp.cmap] || LUTS.gray));
        const f = F.list[k];
        stamp(ctx, SIZE, [f.date_range ? monthYear(f.date_range[0]) : f.date.slice(0, 16), target?.name || ""]);
        const { data } = ctx.getImageData(0, 0, SIZE, SIZE);
        const palette = quantize(data, 256);
        enc.writeFrame(applyPalette(data, palette), SIZE, SIZE, { palette, delay: 800 });
        await new Promise((r) => setTimeout(r, 0));
      }
      enc.finish();
      task.update({ done: F.data.length });
      task.finish();
      await shareOrDownload(new Blob([enc.bytes()], { type: "image/gif" }), `skyshift_${name}.gif`,
        `${target?.name || "The sky"} moving, seen by NASA SPHEREx`, "Made with SkyShift", shareURL(), say);
    } catch (e) { task.fail(e.message); throw e; } finally { setBusy(""); }
  }

  async function card() {
    setBusy("Making card…");
    try {
      const src = document.querySelector(".stage canvas");
      const c = document.createElement("canvas"); c.width = 1200; c.height = 630;
      const ctx = c.getContext("2d");
      const g = ctx.createLinearGradient(0, 0, 1200, 630); g.addColorStop(0, "#04050a"); g.addColorStop(1, "#1a0f06");
      ctx.fillStyle = g; ctx.fillRect(0, 0, 1200, 630);
      if (src) ctx.drawImage(src, 15, 15, 600, 600);
      const load = (u) => new Promise((ok) => { const im = new Image(); im.onload = () => ok(im); im.onerror = () => ok(null); im.src = u; });
      const [mark, word] = await Promise.all([load("/logo-mark.png"), load("/logo-word.png")]);
      if (mark) ctx.drawImage(mark, 648, 30, 58, 58);
      if (word) ctx.drawImage(word, 716, 48, 230, 230 * word.height / word.width);
      else { ctx.fillStyle = "#ffa31a"; ctx.font = "800 30px Inter, sans-serif"; ctx.fillText("SkyShift", 716, 70); }
      ctx.fillStyle = "#ffb43a"; ctx.font = "600 13px Inter, sans-serif"; ctx.fillText("EXPLORE · IDENTIFY · UNDERSTAND  ·  NASA SPHEREx", 650, 112);
      ctx.fillStyle = "#ffffff"; ctx.font = "700 40px Inter, sans-serif";
      let y = wrap(ctx, `${target?.name || "A patch of sky"}`, 650, 175, 520, 46, 2);
      ctx.fillStyle = "#d4d4dc"; ctx.font = "20px Inter, sans-serif";
      y = wrap(ctx, story?.tagline || "", 650, y + 4, 520, 28, 2);
      ctx.fillStyle = "#ffcf4d"; ctx.font = "600 19px Inter, sans-serif";
      for (const f of (facts || []).slice(0, 4)) y = wrap(ctx, `• ${f}`, 650, y + 14, 520, 26, 3);
      ctx.fillStyle = "#707282"; ctx.font = "14px Inter, sans-serif"; ctx.fillText("Real data: NASA/IPAC IRSA (SPHEREx), ESA Gaia, NASA WISE", 650, 600);
      const blob = await new Promise((r) => c.toBlob(r, "image/png"));
      await shareOrDownload(blob, `skyshift_${name}_card.png`, `${target?.name || "The sky"} on SkyShift`, (facts || []).join(" · "), shareURL(), say);
    } finally { setBusy(""); }
  }

  const copy = (txt, msg) => navigator.clipboard.writeText(txt).then(() => say(msg)).catch(() => say(txt));
  return (
    <div className="shareMenu">
      <button onClick={() => setOpen(!open)} aria-expanded={open} disabled={!!busy}>{busy || "Share ▾"}</button>
      {open && (
        <div className="shareList" role="menu" onClick={() => setOpen(false)}>
          <button role="menuitem" onClick={gif}>Animated GIF of the flipbook</button>
          <button role="menuitem" onClick={card}>Picture card for social media</button>
          <button role="menuitem" onClick={() => copy(shareURL(), "Link copied")}>Copy link to this view</button>
          <button role="menuitem" onClick={() => copy(`<iframe src="${shareURL(true)}" width="640" height="780" style="border:0;border-radius:12px" title="SkyShift SPHEREx viewer" loading="lazy"></iframe>`, "Embed code copied")}>&lt;/&gt; Embed on a website</button>
        </div>
      )}
    </div>
  );
}
