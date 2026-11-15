/* Where each picture comes from: one short credit line shown at the bottom-left of every image. */

/* ["spherex_dr1", "spherex_qr3"] -> "DR1 + QR3" */
export function releaseLabel(rels) {
  const r = (rels || []).map((x) => String(x).replace(/^spherex_/, "").toUpperCase()).filter(Boolean);
  return r.length ? r.join(" + ") : "";
}

export function spherexCredit(rels) {
  const r = releaseLabel(rels);
  return `NASA SPHEREx via NASA/IPAC IRSA${r ? ` (${r})` : ""}`;
}

/* Time machine surveys */
export const SURVEY_CREDIT = {
  poss1: "Palomar Observatory Sky Survey I (Caltech), digitized by STScI (DSS)",
  poss2: "Palomar Sky Survey II / UK Schmidt (Caltech, AAO), digitized by STScI (DSS)",
  "2mass": "2MASS (UMass, IPAC/Caltech; NASA, NSF) via IRSA",
  wise: "NASA WISE (AllWISE) via IRSA",
  spherex: "NASA SPHEREx via IRSA",
};

/* Aladin sky map layers */
export function skyCredit(survey) {
  if (/spherex-colour/.test(survey)) return "NASA SPHEREx DR1 all-sky cube (IRSA HiPS), colours mixed by SkyShift";
  if (/allWISE/i.test(survey)) return "NASA WISE (AllWISE), HiPS by CDS Strasbourg";
  if (/2MASS/i.test(survey)) return "2MASS (UMass, IPAC/Caltech), HiPS by CDS Strasbourg";
  if (/Mellinger/i.test(survey)) return "Axel Mellinger all-sky mosaic, HiPS by CDS Strasbourg";
  if (/DSS/i.test(survey)) return "Digitized Sky Survey (STScI), HiPS by CDS Strasbourg";
  return "CDS Strasbourg HiPS";
}

/* Extra credits for the overlays switched on in the flipbook */
export function overlayCredits(ov) {
  const o = [];
  if (ov?.gaia) o.push("ESA Gaia DR3");
  if (ov?.wise) o.push("NASA AllWISE");
  if (ov?.ast) o.push("IMCCE SkyBoT");
  return o;
}
