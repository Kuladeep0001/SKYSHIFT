/* Spectrum of the clicked object: all 102 channels joined into one continuous curve with an
 * uncertainty band, known molecular/mineral bands marked, each visit overlaid, plus a light curve.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import Chart from "chart.js/auto";
import { DET_COLORS, VISIT_COLORS } from "../lib/render.js";

const CAT_COLOR = { water: "90,176,255", minerals: "196,150,98", carbon: "255,181,71", organics: "120,220,120", hydrogen: "255,107,139" };
const SHORT = { H2O: "H₂O", "H2O ice": "H₂O ice", "OH/H2O in rock": "hydrated", "silicate rock": "rock", "CO2 ice": "CO₂",
  CO: "CO", "CO gas": "CO", CH4: "CH₄", "organic molecules": "PAH", H: "H", H2: "H₂" };

/* Draw known bands behind the data, and detector edges along the bottom. */
export const bandsPlugin = {
  id: "bands",
  beforeDatasetsDraw(chart, _a, opts) {
    const { ctx, chartArea: a, scales: { x } } = chart;
    if (!a) return;
    ctx.save();
    for (const f of opts.features || []) {
      const x0 = x.getPixelForValue(f.center_um - f.half_width_um), x1 = x.getPixelForValue(f.center_um + f.half_width_um);
      if (x1 < a.left || x0 > a.right) continue;
      const seen = f.status !== "not seen";
      if (!seen && !opts.showAll) continue;
      ctx.fillStyle = `rgba(${CAT_COLOR[f.category]},${seen ? (f.status === "likely" ? 0.28 : 0.17) : 0.06})`;
      ctx.fillRect(x0, a.top, x1 - x0, a.bottom - a.top);
      if (seen || opts.showAll) {
        ctx.fillStyle = `rgba(${CAT_COLOR[f.category]},${seen ? 1 : 0.5})`;
        ctx.font = "600 10px Inter, sans-serif";
        ctx.save(); ctx.translate((x0 + x1) / 2 + 3, a.top + 4); ctx.rotate(Math.PI / 2);
        ctx.fillText(SHORT[f.species] || f.species, 0, 0); ctx.restore();
      }
    }
    ctx.setLineDash([2, 4]); ctx.strokeStyle = "rgba(143,160,189,.35)"; ctx.font = "10px JetBrains Mono, monospace"; ctx.fillStyle = "#5f7193";
    for (const [d, [lo]] of Object.entries(opts.detectors || {})) {
      const px = x.getPixelForValue(lo);
      if (px < a.left || px > a.right) continue;
      ctx.beginPath(); ctx.moveTo(px, a.top); ctx.lineTo(px, a.bottom); ctx.stroke();
      ctx.fillText(`D${d}`, px + 3, a.bottom - 4);
    }
    ctx.restore();
  },
};

function axis(title, log, min, max) {
  return { type: log ? "logarithmic" : "linear", min, max, title: { display: true, text: title, color: "#8fa0bd", font: { size: 12 } },
    grid: { color: "#1b2943" }, border: { color: "#33476e" }, ticks: { color: "#8fa0bd", font: { family: "JetBrains Mono", size: 10 } } };
}

export default function SpectrumPanel({ spec, visits, detectors, loading, simple }) {
  const a = useRef(null), b = useRef(null), charts = useRef([]);
  const [log, setLog] = useState(false);
  const [byVisit, setByVisit] = useState(true);
  const [raw, setRaw] = useState(false);
  const [allBands, setAllBands] = useState(false);
  const binned = spec?.binned || [];
  const seen = (spec?.features || []).filter((f) => f.status !== "not seen");

  useEffect(() => {
    charts.current.forEach((c) => c.destroy());
    charts.current = [];
    if (!spec || !binned.length) return;
    const good = binned.filter((p) => !p.saturated || spec.saturated_fraction > 0.5);
    const up = good.map((p) => ({ x: p.wave, y: p.flux + p.err })), dn = good.map((p) => ({ x: p.wave, y: Math.max(p.flux - p.err, log ? 1e-3 : -1e12) }));
    const ds = [
      { label: "±1σ", data: up, borderWidth: 0, pointRadius: 0, fill: "+1", backgroundColor: "rgba(255,181,71,.18)", order: 3 },
      { label: "_lo", data: dn, borderWidth: 0, pointRadius: 0, fill: false, order: 3 },
      { label: "All visits (median per channel)", data: good.map((p) => ({ x: p.wave, y: p.flux, tip: `ch ${p.channel} · ${p.wave.toFixed(3)} µm · ${p.flux.toFixed(1)} ± ${p.err.toFixed(1)} µJy · n=${p.n}${p.saturated ? " · saturated" : ""}` })),
        borderColor: "#ffb547", borderWidth: 2, pointRadius: 1.8, pointBackgroundColor: "#ffb547", tension: 0, order: 1 },
    ];
    if (byVisit && spec.binned_by_visit) {
      Object.entries(spec.binned_by_visit).forEach(([v, pts], j) => {
        if (pts.length < 10) return;
        ds.push({ label: `Visit ${+v + 1} (${visits?.find((x) => x.visit === +v)?.start?.slice(0, 7) || ""})`,
          data: pts.map((p) => ({ x: p.wave, y: p.flux, tip: `visit ${+v + 1} · ch ${p.channel} · ${p.wave.toFixed(3)} µm · ${p.flux.toFixed(1)} µJy` })),
          borderColor: VISIT_COLORS[(j + 1) % 6], borderWidth: 1.1, borderDash: [4, 3], pointRadius: 0, tension: 0, order: 2 });
      });
    }
    if (raw) ds.push({ label: "Single snapshots", type: "scatter", data: spec.points.map((p) => ({ x: p.wave, y: p.flux, tip: `${p.date} · D${p.det} · ${p.flux.toFixed(1)} µJy` })),
      pointRadius: 1.4, backgroundColor: "rgba(143,160,189,.45)", borderWidth: 0, order: 4 });
    const opts = {
      animation: false, maintainAspectRatio: false, parsing: false, interaction: { mode: "nearest", intersect: false },
      plugins: {
        legend: { labels: { color: "#8fa0bd", boxWidth: 12, font: { size: 10.5 }, filter: (l) => !l.text.startsWith("_") } },
        tooltip: { callbacks: { label: (c) => c.raw.tip || "" } },
        bands: { features: spec.features, detectors, showAll: allBands },
      },
      scales: { x: axis("Wavelength λ (µm)", false, 0.7, 5.05), y: axis("Flux density Fν (µJy)", log) },
    };
    charts.current.push(new Chart(a.current, { type: "line", data: { datasets: ds }, options: opts, plugins: [bandsPlugin] }));

    // light curve: each snapshot by detector + visit averages
    const byDet = {};
    for (const p of spec.points) (byDet[p.det] ||= []).push(p);
    const lds = Object.keys(byDet).map((d) => ({
      label: `D${d}`, type: "scatter", data: byDet[d].map((p) => ({ x: p.mjd, y: p.flux, tip: `${p.date} · D${d} · ${p.wave.toFixed(2)} µm · ${p.flux.toFixed(1)} ± ${p.err.toFixed(1)} µJy` })),
      backgroundColor: DET_COLORS[d - 1], pointRadius: 2.2, borderWidth: 0,
    }));
    charts.current.push(new Chart(b.current, {
      type: "scatter", data: { datasets: lds },
      options: { animation: false, maintainAspectRatio: false, parsing: false,
        plugins: { legend: { labels: { color: "#8fa0bd", boxWidth: 10, font: { size: 10.5 } } }, tooltip: { callbacks: { label: (c) => c.raw.tip } } },
        scales: { x: { ...axis("Date", false), ticks: { color: "#8fa0bd", font: { size: 10 }, callback: (v) => new Date((v - 40587) * 864e5).toISOString().slice(0, 7) } },
          y: axis("Flux density (µJy)", log) } },
    }));
    return () => charts.current.forEach((c) => c.destroy());
  }, [spec, visits, detectors, log, byVisit, raw, allBands]);

  const peak = useMemo(() => {
    const g = binned.filter((p) => !p.saturated);
    return g.length ? g.reduce((m, p) => (p.flux > m.flux ? p : m), g[0]) : null;
  }, [binned]);

  function downloadCSV() {
    const rows = [["channel", "wavelength_um", "flux_uJy", "err_uJy", "n_snapshots", "saturated"]];
    binned.forEach((p) => rows.push([p.channel, p.wave, p.flux, p.err, p.n, p.saturated]));
    const blob = new Blob([rows.map((r) => r.join(",")).join("\n")], { type: "text/csv" });
    const el = document.createElement("a");
    el.href = URL.createObjectURL(blob);
    el.download = `skyshift_spectrum_${spec.ra.toFixed(4)}_${spec.dec.toFixed(4)}.csv`;
    el.click();
  }

  return (
    <section className="card spectrum">
      <h2>Spectrum <small>{loading ? "loading…" : spec ? `RA ${spec.ra?.toFixed(5)} Dec ${spec.dec?.toFixed(5)} · ${binned.length}/102 channels · ${spec.points.length} snapshots` : "click any star in the picture"}</small></h2>
      {spec && (
        <>
          {simple && (
            <p className="plain">
              {peak && <>This object shines brightest at <b>{peak.wave.toFixed(2)} µm</b>{peak.wave > 3 ? " (very red: cool or dusty)" : peak.wave < 1.2 ? " (bluish: hot)" : ""}. </>}
              {seen.length ? <>Possible signs of: {[...new Set(seen.map((f) => f.category_label))].join(", ")}.</> : "No strong molecule signatures stand out."}
            </p>
          )}
          <div className="row specOpts">
            <label><input type="checkbox" checked={log} onChange={() => setLog(!log)} /> log scale</label>
            <label><input type="checkbox" checked={byVisit} onChange={() => setByVisit(!byVisit)} /> each visit</label>
            <label><input type="checkbox" checked={raw} onChange={() => setRaw(!raw)} /> single snapshots</label>
            <label><input type="checkbox" checked={allBands} onChange={() => setAllBands(!allBands)} /> all known bands</label>
            <button className="small" onClick={downloadCSV}>⤓ CSV</button>
          </div>
        </>
      )}
      <div className="chartBox tall"><canvas ref={a} aria-label="Spectrum chart" /></div>
      {spec && spec.saturated_fraction > 0.5 && <p className="note warn">⚠ This star is so bright it overloads (saturates) SPHEREx's camera, so these values are lower limits and band depths can't be measured. Click a fainter star.</p>}
      {spec && spec.features?.length > 0 && (
        <table className="features">
          <thead><tr><th>Band</th><th>λ (µm)</th><th>Change</th><th>σ</th><th>Result</th></tr></thead>
          <tbody>
            {spec.features.filter((f) => allBands || f.status !== "not seen").slice(0, allBands ? 30 : 8).map((f) => (
              <tr key={f.name} className={f.status.replace(" ", "")} title={`${f.plain_english} Seen in: ${f.seen_in}.`}>
                <td><i className="sw" style={{ background: `rgb(${CAT_COLOR[f.category]})` }} />{f.name}</td>
                <td className="mono">{f.center_um.toFixed(2)}</td>
                <td className="mono">{f.change_pct > 0 ? "+" : ""}{f.change_pct}%</td>
                <td className="mono">{f.significance}</td>
                <td>{f.status}</td>
              </tr>
            ))}
            {!seen.length && !allBands && <tr><td colSpan="5" className="muted">No band stands out above 3σ. Tick "all known bands" to see every measurement.</td></tr>}
          </tbody>
        </table>
      )}
      <h2 className="mt">Light curve <small>brightness at this spot over time</small></h2>
      <div className="chartBox"><canvas ref={b} aria-label="Light curve chart" /></div>
      <p className="note">The spectrum joins all 102 SPHEREx channels: each point is the median of every snapshot in that channel (shaded = ±1σ). Coloured stripes mark where water, CO₂, CO, methane, hydrogen or rock minerals absorb or emit light. SPHEREx's colour resolution is low, so these are hints to follow up, not proof.</p>
    </section>
  );
}
