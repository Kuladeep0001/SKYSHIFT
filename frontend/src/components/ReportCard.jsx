/* Technical report (PDF) for researchers: view it in a new tab or download it. Built on the server
 * (GET /api/images/{id}/report.pdf) from the same data as the website; takes 10-60 s. */
import { useState } from "react";
import { fetchReport } from "../lib/api.js";

export default function ReportCard({ qid, sel, band, label, pm, say }) {
  const [busy, setBusy] = useState("");
  if (!qid) return null;
  const params = { band };
  if (sel) { params.x = sel.x; params.y = sel.y; }
  if (label) params.label = label;
  if (pm && Number.isFinite(pm.pmra) && Number.isFinite(pm.pmdec)) { params.pmra = pm.pmra; params.pmdec = pm.pmdec; }

  async function make(mode) {
    // open the tab now (a tab opened after a long wait is often blocked), fill it when the PDF is ready
    const tab = mode === "view" ? window.open("", "_blank") : null;
    if (tab) tab.document.write("<p style='font:15px system-ui;padding:24px'>Building the SkyShift technical report… (10–60 seconds)</p>");
    setBusy(mode === "view" ? "Building the report…" : "Preparing the download…");
    try {
      const { blob, name } = await fetchReport(qid, params);
      const url = URL.createObjectURL(blob);
      if (tab) tab.location.href = url;
      else {
        const a = document.createElement("a");
        a.href = url; a.download = name; a.click();
      }
      setTimeout(() => URL.revokeObjectURL(url), 120000);
      say && say(mode === "view" ? "Report opened in a new tab." : `Saved ${name}`);
    } catch (e) {
      if (tab) tab.close();
      say && say(e.cancelled ? "Report cancelled." : `Report failed: ${e.message}`);
    } finally { setBusy(""); }
  }

  return (
    <section className="card reportCard">
      <h2>Technical report <small>PDF for researchers</small></h2>
      <p className="small">Everything SkyShift knows about this spot{sel ? " and the object you clicked" : ""}, in a technical-report format:
        data and processing, images, detections with motion fits and errors, identification in Gaia, 2MASS, AllWISE, SIMBAD
        and the NASA Exoplanet Archive, spectrum, light curve, method validation, references, and appendices with every channel,
        exposure and quality flag.</p>
      <div className="row">
        <button className="primary" onClick={() => make("view")} disabled={!!busy}>{busy || "View report"}</button>
        <button onClick={() => make("download")} disabled={!!busy}>Download PDF</button>
      </div>
      <p className="small muted">Built from live archive queries, so it takes 10–60 seconds. Progress shows in the download bar.</p>
    </section>
  );
}
