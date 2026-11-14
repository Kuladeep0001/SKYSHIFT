/* Click any pixel: its brightness at every infrared colour (spectrum) and over time (light curve). */
import { useEffect, useRef } from "react";
import Chart from "chart.js/auto";
import { DET_COLORS, VISIT_COLORS } from "../lib/render.js";

function opts(xTitle, yTitle, timeAxis) {
  return {
    animation: false, maintainAspectRatio: false, parsing: false,
    plugins: { legend: { labels: { color: "#8fa0bd", boxWidth: 10, font: { size: 11 } } },
      tooltip: { callbacks: { label: (c) => c.raw.tip } } },
    scales: {
      x: { title: { display: true, text: xTitle, color: "#8fa0bd" }, grid: { color: "#1e2c47" },
        ticks: { color: "#8fa0bd", callback: timeAxis ? (v) => new Date((v - 40587) * 864e5).toISOString().slice(0, 7) : undefined } },
      y: { title: { display: true, text: yTitle, color: "#8fa0bd" }, ticks: { color: "#8fa0bd" }, grid: { color: "#1e2c47" } },
    },
  };
}

export default function SpectrumPanel({ spec, visits, loading }) {
  const a = useRef(null), b = useRef(null), charts = useRef([]);
  useEffect(() => {
    charts.current.forEach((c) => c.destroy());
    charts.current = [];
    if (!spec || !spec.points.length) return;
    const byVisit = {}, byDet = {}, sat = [];
    for (const p of spec.points) {
      const tip = `${p.date} · D${p.det} · ${p.wave.toFixed(3)} µm · ${p.flux.toFixed(0)} µJy${p.saturated ? " (saturated)" : ""}`;
      (byDet[p.det] ||= []).push({ x: p.mjd, y: p.flux, tip });
      if (p.saturated) sat.push({ x: p.wave, y: p.flux, tip });
      else (byVisit[p.visit] ||= []).push({ x: p.wave, y: p.flux, tip });
    }
    const sd = Object.keys(byVisit).map((v) => ({
      label: `Visit ${+v + 1} (${visits?.[v]?.start?.slice(0, 7) || ""})`, data: byVisit[v].sort((p, q) => p.x - q.x),
      showLine: false, pointRadius: 2.6, backgroundColor: VISIT_COLORS[v % 6], borderColor: VISIT_COLORS[v % 6],
    }));
    if (sat.length) sd.push({ label: "Saturated (too bright)", data: sat, showLine: false, pointRadius: 2.6, pointStyle: "crossRot", borderColor: "#5f7193", backgroundColor: "#5f7193" });
    const ld = Object.keys(byDet).map((d) => ({ label: `D${d}`, data: byDet[d], showLine: false, pointRadius: 2.4, backgroundColor: DET_COLORS[d - 1], borderColor: DET_COLORS[d - 1] }));
    charts.current = [
      new Chart(a.current, { type: "scatter", data: { datasets: sd }, options: opts("Infrared colour: wavelength (µm)", "Brightness (µJy)") }),
      new Chart(b.current, { type: "scatter", data: { datasets: ld }, options: opts("Date", "Brightness (µJy)", true) }),
    ];
    return () => charts.current.forEach((c) => c.destroy());
  }, [spec, visits]);

  const satMost = spec && spec.points.filter((p) => p.saturated).length > spec.points.length / 2;
  return (
    <section className="card">
      <h2>Spectrum <small>{loading ? "loading…" : spec ? `pixel (${spec.x}, ${spec.y}) · ${spec.points.length} measurements` : "click any spot in the picture"}</small></h2>
      <div className="chartBox"><canvas ref={a} /></div>
      <h2 className="mt">Light curve <small>same spot over time</small></h2>
      <div className="chartBox"><canvas ref={b} /></div>
      <p className="note">
        {satMost && "⚠ This star is so bright it overloads the camera, so its brightness is only a lower limit. "}
        Each dot is one snapshot. The <b>spectrum</b> shows which infrared colours the object glows in (molecules like water and CO leave dips). The <b>light curve</b> shows whether it changed over time.
      </p>
    </section>
  );
}
