/* One colour per visit, added together. Things that stayed put add up to WHITE;
 * things that moved split into separate coloured dots, showing where they were at each date. */
import { useEffect, useMemo, useRef } from "react";
import { monthYear, percentile } from "../lib/frames.js";
import { timePalette } from "../lib/render.js";

// Colours that add up to white: 2 visits -> orange + blue; 3 visits -> red + green + blue.
export function pickVisits(F) {
  if (!F) return [];
  const n = F.data.length;
  if (n <= 3) return [...Array(n).keys()];
  return [0, Math.floor((n - 1) / 2), n - 1]; // first, middle, last
}

export default function TimeColours({ F, disp, onPixel, focusXY, source }) {
  const ref = useRef(null);
  const use = useMemo(() => pickVisits(F), [F]);
  const colours = timePalette(use.length);

  useEffect(() => {
    if (!F || use.length < 2) return;
    const n = F.n, nn = n * n;
    const [lo, hi] = percentile(use.map((k) => F.data[k]), [55, 99.6]);  // keep empty sky dark so only stars get colour
    const beta = Math.pow(10, disp.contrast * 3) - 0.999, norm = Math.asinh(beta) || 1;
    const hiEff = lo + (hi - lo) * Math.pow(10, (0.5 - disp.bright) * 1.6);
    const st = (v) => { if (!Number.isFinite(v)) return 0; const t = (v - lo) / (hiEff - lo || 1); return t <= 0 ? 0 : t >= 1 ? 1 : Math.asinh(t * beta) / norm; };
    const rgb = new Float32Array(nn * 3);
    use.forEach((k, j) => {
      const a = F.data[k], c = colours[j];
      for (let i = 0; i < nn; i++) { const t = st(a[i]); rgb[i * 3] += c[0] * t; rgb[i * 3 + 1] += c[1] * t; rgb[i * 3 + 2] += c[2] * t; }
    });
    const off = document.createElement("canvas");
    off.width = off.height = n;
    const octx = off.getContext("2d"), img = octx.createImageData(n, n);
    for (let r = 0; r < n; r++) {
      const src = (n - 1 - r) * n;
      for (let c = 0; c < n; c++) {
        const o = (r * n + c) * 4, i = (src + c) * 3;
        img.data[o] = Math.min(255, rgb[i] * 255); img.data[o + 1] = Math.min(255, rgb[i + 1] * 255);
        img.data[o + 2] = Math.min(255, rgb[i + 2] * 255); img.data[o + 3] = 255;
      }
    }
    octx.putImageData(img, 0, 0);
    const ctx = ref.current.getContext("2d");
    ctx.imageSmoothingEnabled = false;
    ctx.drawImage(off, 0, 0, ref.current.width, ref.current.height);
    if (focusXY) {
      const s = ref.current.width / n;
      ctx.strokeStyle = "#ffffff"; ctx.lineWidth = 2; ctx.setLineDash([5, 4]);
      ctx.beginPath(); ctx.arc((focusXY.x + 0.5) * s, (n - 1 - focusXY.y + 0.5) * s, 26, 0, 2 * Math.PI); ctx.stroke();
      ctx.setLineDash([]);
    }
  }, [F, use, disp.contrast, disp.bright, focusXY]);

  if (!F || use.length < 2) return <p className="hint">Need at least two visits to colour by date.</p>;
  const css = (c) => `rgb(${c.map((x) => Math.round(x * 255)).join(",")})`;
  const click = (e) => {
    const r = e.currentTarget.getBoundingClientRect();
    onPixel && onPixel(Math.floor(((e.clientX - r.left) / r.width) * F.n), F.n - 1 - Math.floor(((e.clientY - r.top) / r.height) * F.n));
  };
  return (
    <div className="viewer">
      <div className="canvasWrap">
        <canvas ref={ref} width="720" height="720" onClick={click} aria-label="Pictures from different dates in different colours" />
        <div className="imgFoot"><span className="src">Data: {source || "NASA SPHEREx via IRSA"}</span></div>
        <div className="legend timeLegend">
          {use.map((k, j) => (
            <span key={k}><i style={{ background: css(colours[j]) }} /> {monthYear((F.list[k].date_range?.[0] || F.list[k].date).slice(0, 10))}</span>
          ))}
          <span><i style={{ background: "#fff" }} /> all dates (didn't move)</span>
        </div>
      </div>
      <p className="hint">Each date gets its own colour. <b>White</b> = in the same place every time (didn't move).
        A star that <b>moved</b> splits into separate coloured dots, one for each date, in order.</p>
    </div>
  );
}
