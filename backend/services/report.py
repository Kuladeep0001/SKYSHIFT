"""SkyShift technical report: one PDF with every technical detail a researcher needs for one field.

Layout follows a standard technical-report format: report number and metadata block, abstract,
numbered sections (data, processing, images, detections, object of interest, validation,
reproducibility), figure and table captions, references, and appendices (full spectrum, exposure
list, quality flags). No author names: every page carries a faint SkyShift watermark and the
website address. Owner: Integration lead.
"""
from __future__ import annotations

import asyncio
import io
import math
import platform
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape

import numpy as np
from PIL import Image as PILImage
from reportlab.graphics.shapes import Drawing, Group, Line, PolyLine, Rect, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (BaseDocTemplate, CondPageBreak, Frame, Image, PageBreak, PageTemplate, Paragraph,
                                Table, TableStyle)

from . import detection, jobs
from . import image_processing as im
from . import spectral_features as sf

ROOT = Path(__file__).resolve().parents[2]
VERSION = "SkyShift 0.2"
INK = colors.HexColor("#1b1f2a")
MUTED = colors.HexColor("#5b6274")
LINE = colors.HexColor("#d5d9e2")
HEAD = colors.HexColor("#14161d")
ACCENT = colors.HexColor("#c2610c")
W, H = A4
M = 18 * mm
CW = W - 2 * M

# ---------------------------------------------------------------- text helpers
_SUBS = {"″": " arcsec", "′": " arcmin", "σ": "sigma", "λ": "lambda", "−": "-", "≈": "~", "→": "->", "←": "<-",
         "↔": "<->", "₂": "2", "₄": "4", "Δ": "Delta", "µ": "µ", "…": "...", "’": "'", "‘": "'", "“": '"', "”": '"'}


def txt(s) -> str:
    """Escape for Paragraph markup and keep only characters the built-in PDF fonts can draw."""
    s = "" if s is None else str(s)
    for a, b in _SUBS.items():
        s = s.replace(a, b)
    s = s.encode("cp1252", "replace").decode("cp1252")
    return escape(s)


def fnum(v, fmt="{:.2f}", none="-"):
    try:
        if v is None or (isinstance(v, float) and not math.isfinite(v)):
            return none
        return fmt.format(v)
    except (TypeError, ValueError):
        return none


SS = {
    "title": ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=17, leading=21, textColor=HEAD, spaceAfter=4),
    "sub": ParagraphStyle("sub", fontName="Helvetica", fontSize=10, leading=13, textColor=MUTED, spaceAfter=8),
    "h1": ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=12.5, leading=16, textColor=HEAD, spaceBefore=10, spaceAfter=4),
    "h2": ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=10.5, leading=14, textColor=HEAD, spaceBefore=6, spaceAfter=3),
    "body": ParagraphStyle("body", fontName="Helvetica", fontSize=9, leading=12.5, textColor=INK, spaceAfter=4),
    "abs": ParagraphStyle("abs", fontName="Helvetica", fontSize=9, leading=12.5, textColor=INK, leftIndent=8, rightIndent=8, spaceAfter=6),
    "cap": ParagraphStyle("cap", fontName="Helvetica-Oblique", fontSize=8, leading=10.5, textColor=MUTED, spaceBefore=2, spaceAfter=8),
    "cell": ParagraphStyle("cell", fontName="Helvetica", fontSize=7.6, leading=9.6, textColor=INK),
    "cellb": ParagraphStyle("cellb", fontName="Helvetica-Bold", fontSize=7.6, leading=9.6, textColor=INK),
    "head": ParagraphStyle("head", fontName="Helvetica-Bold", fontSize=7.6, leading=9.6, textColor=colors.white),
    "tiny": ParagraphStyle("tiny", fontName="Helvetica", fontSize=6.6, leading=8.2, textColor=INK),
    "ref": ParagraphStyle("ref", fontName="Helvetica", fontSize=8.2, leading=11, textColor=INK, leftIndent=12, firstLineIndent=-12, spaceAfter=2),
    "bul": ParagraphStyle("bul", fontName="Helvetica", fontSize=9, leading=12.3, textColor=INK, leftIndent=10, bulletIndent=0, spaceAfter=2),
}


def P(t, s="body"):
    return Paragraph(t, SS[s])


def table(rows, widths, font="cell", head=True, zebra=True):
    data = []
    for r, row in enumerate(rows):
        st = "head" if head and r == 0 else font
        data.append([Paragraph(c, SS[st]) if isinstance(c, str) else c for c in row])
    t = Table(data, colWidths=widths, repeatRows=1 if head else 0)
    style = [("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -1), 0.3, LINE),
             ("LEFTPADDING", (0, 0), (-1, -1), 3.5), ("RIGHTPADDING", (0, 0), (-1, -1), 3.5),
             ("TOPPADDING", (0, 0), (-1, -1), 2.2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.2)]
    if head:
        style.append(("BACKGROUND", (0, 0), (-1, 0), HEAD))
    if zebra:
        for r in range(1 if head else 0, len(data)):
            if r % 2 == 0:
                style.append(("BACKGROUND", (0, r), (-1, r), colors.HexColor("#f3f4f7")))
    t.setStyle(TableStyle(style))
    return t


def kv(rows, w0=48 * mm):
    return table([[f"<b>{a}</b>", b] for a, b in rows], [w0, CW - w0], head=False)


def png_image(png: bytes, width: float) -> Image:
    r = ImageReader(io.BytesIO(png))
    iw, ih = r.getSize()
    return Image(io.BytesIO(png), width=width, height=width * ih / iw)


def nice_ticks(lo, hi, n=5):
    if not (math.isfinite(lo) and math.isfinite(hi)) or hi <= lo:
        return [lo]
    raw = (hi - lo) / n
    mag = 10 ** math.floor(math.log10(raw))
    step = min((s * mag for s in (1, 2, 2.5, 5, 10) if s * mag >= raw), default=raw)
    start = math.ceil(lo / step) * step
    out, v = [], start
    while v <= hi + 1e-9 * abs(step):
        out.append(round(v, 10))
        v += step
    return out


def plot(series, width, height, xlabel, ylabel, bands=(), xlim=None):
    """A small line/point chart drawn with PDF vector shapes. series: dicts(points=[(x, y, err)], color, kind, label)."""
    d = Drawing(width, height)
    L, B, R, T = 46, 30, 8, 16
    xs = [p[0] for s in series for p in s["points"]]
    ys = [p[1] for s in series for p in s["points"]] + [p[1] + (p[2] or 0) for s in series for p in s["points"]] + \
         [p[1] - (p[2] or 0) for s in series for p in s["points"]]
    ys = [v for v in ys if math.isfinite(v)]
    if not xs or not ys:
        d.add(String(width / 2, height / 2, "no data", fontName="Helvetica", fontSize=8, textAnchor="middle"))
        return d
    x0, x1 = xlim or (min(xs), max(xs))
    lo, hi = np.percentile(ys, [0.5, 99.5]) if len(ys) > 20 else (min(ys), max(ys))
    pad = (hi - lo) * 0.08 or 1
    y0, y1 = lo - pad, hi + pad
    pw, ph = width - L - R, height - B - T
    X = lambda v: L + (v - x0) / ((x1 - x0) or 1) * pw
    Y = lambda v: B + (min(max(v, y0), y1) - y0) / ((y1 - y0) or 1) * ph
    for b0, b1, col in bands:
        if b1 < x0 or b0 > x1:
            continue
        d.add(Rect(X(max(b0, x0)), B, X(min(b1, x1)) - X(max(b0, x0)), ph, fillColor=col, strokeColor=None))
    d.add(Rect(L, B, pw, ph, fillColor=None, strokeColor=MUTED, strokeWidth=0.6))
    for t in nice_ticks(x0, x1, 6):
        d.add(Line(X(t), B, X(t), B - 3, strokeColor=MUTED, strokeWidth=0.5))
        d.add(String(X(t), B - 11, f"{t:g}", fontName="Helvetica", fontSize=6.5, textAnchor="middle", fillColor=MUTED))
    for t in nice_ticks(y0, y1, 5):
        d.add(Line(L, Y(t), L - 3, Y(t), strokeColor=MUTED, strokeWidth=0.5))
        d.add(Line(L, Y(t), L + pw, Y(t), strokeColor=colors.HexColor("#eceef3"), strokeWidth=0.4))
        d.add(String(L - 5, Y(t) - 2.2, f"{t:g}", fontName="Helvetica", fontSize=6.5, textAnchor="end", fillColor=MUTED))
    d.add(String(L + pw / 2, 4, xlabel, fontName="Helvetica", fontSize=7.5, textAnchor="middle", fillColor=INK))
    lab = Group(String(0, 0, ylabel, fontName="Helvetica", fontSize=7.5, textAnchor="middle", fillColor=INK))
    lab.transform = (0, 1, -1, 0, 9, B + ph / 2)   # rotated 90 degrees
    d.add(lab)
    lx = L + 6
    for s in series:
        pts = [p for p in s["points"] if math.isfinite(p[1])]
        col = s.get("color", INK)
        if s.get("err"):
            for x, y, e in pts:
                if e and math.isfinite(e):
                    d.add(Line(X(x), Y(y - e), X(x), Y(y + e), strokeColor=col, strokeWidth=0.4))
        if s.get("kind", "line") == "line" and len(pts) > 1:
            flat = []
            for x, y, _ in pts:
                flat += [X(x), Y(y)]
            d.add(PolyLine(flat, strokeColor=col, strokeWidth=s.get("width", 0.9), strokeDashArray=s.get("dash")))
        if s.get("kind") in ("points", "both") or s.get("markers"):
            for x, y, _ in pts:
                d.add(Rect(X(x) - 1, Y(y) - 1, 2, 2, fillColor=col, strokeColor=None))
        if s.get("label"):
            d.add(Line(lx, B + ph + 7, lx + 10, B + ph + 7, strokeColor=col, strokeWidth=1.4, strokeDashArray=s.get("dash")))
            d.add(String(lx + 13, B + ph + 4.6, s["label"], fontName="Helvetica", fontSize=6.5, fillColor=INK))
            lx += 18 + 3.3 * len(s["label"])
    return d


# ---------------------------------------------------------------- page decoration
def _watermark_image():
    for p in (ROOT / "frontend" / "dist" / "logo-mark.png", ROOT / "frontend" / "public" / "logo-mark.png"):
        if p.exists():
            im_ = PILImage.open(p).convert("RGBA")
            a = np.asarray(im_).astype(np.float32)
            a[..., 3] *= 0.07
            buf = io.BytesIO()
            PILImage.fromarray(a.astype(np.uint8), "RGBA").save(buf, "PNG")
            buf.seek(0)
            return ImageReader(buf)
    return None


def _page(report_no: str, site: str, field: str):
    mark = _watermark_image()

    def draw(c, doc):
        c.saveState()
        # watermark: faint logo + diagonal website name
        if mark:
            c.drawImage(mark, W / 2 - 75 * mm, H / 2 - 75 * mm, 150 * mm, 150 * mm, mask="auto")
        c.setFillColor(colors.Color(0.76, 0.38, 0.05, alpha=0.06))
        c.setFont("Helvetica-Bold", 64)
        c.translate(W / 2, H / 2)
        c.rotate(35)
        c.drawCentredString(0, -20, "SKYSHIFT")
        c.setFont("Helvetica", 18)
        c.drawCentredString(0, -48, site)
        c.restoreState()
        c.saveState()
        c.setStrokeColor(LINE)
        c.setLineWidth(0.5)
        c.line(M, H - 12 * mm, W - M, H - 12 * mm)
        c.line(M, 12 * mm, W - M, 12 * mm)
        c.setFont("Helvetica-Bold", 7.5)
        c.setFillColor(ACCENT)
        c.drawString(M, H - 10 * mm, "SKYSHIFT TECHNICAL REPORT")
        c.setFont("Helvetica", 7.5)
        c.setFillColor(MUTED)
        c.drawRightString(W - M, H - 10 * mm, f"{report_no}  |  {field}")
        c.drawString(M, 8 * mm, f"Generated automatically by SkyShift  |  {site}  |  NASA SPHEREx data; not peer reviewed")
        c.drawRightString(W - M, 8 * mm, f"Page {doc.page}")
        c.restoreState()
    return draw


# ---------------------------------------------------------------- data helpers
def _visit_rows(job):
    main = set(jobs.main_visits(job))
    rows = {}
    for m in job.meta:
        r = rows.setdefault(m["visit"], {"mjd": [], "dets": set(), "dates": [], "rel": set()})
        r["mjd"].append(m["mjd"])
        r["dets"].add(m["det"])
        r["dates"].append(m["date"][:10])
        r["rel"].add(m.get("release", ""))
    out = []
    for v, r in sorted(rows.items()):
        out.append({"visit": v, "start": min(r["dates"]), "end": max(r["dates"]), "mjd": float(np.mean(r["mjd"])),
                    "n": len(r["mjd"]), "dets": sorted(r["dets"]), "main": v in main,
                    "releases": sorted(x for x in r["rel"] if x)})
    return out


def _stack(job, visit, band):
    idx = [m["i"] for m in job.meta if m["visit"] == visit and detection.det_matches(m["det"], band)]
    if len(idx) < 1:
        return None, 0
    return detection._stack(job.arrays, idx)[0], len(idx)


def _aperture(img, x, y, r=3, r_in=6, r_out=10):
    n = img.shape[-1]
    yy, xx = np.mgrid[0:n, 0:n]
    rr = np.hypot(xx - x, yy - y)
    sky = np.nanmedian(img[(rr > r_in) & (rr < r_out)])
    return float(np.nansum(img[rr <= r] - sky))


def _crossmatch(ra, dec, mjd, pm):
    """Gaia DR3 + 2MASS + AllWISE + SIMBAD + NASA Exoplanet Archive for one position (verification module)."""
    from ..models.verification import CandidateInput, VerificationRequest
    from ..routes.verification import verify_candidates
    when = datetime(1858, 11, 17, tzinfo=timezone.utc).timestamp() + mjd * 86400
    cand = {"candidate_id": "object", "ra": ra, "dec": dec,
            "observation_time": datetime.fromtimestamp(when, tz=timezone.utc)}
    if pm and pm[0] is not None and pm[1] is not None:
        cand.update(pmra_mas_yr=pm[0], pmdec_mas_yr=pm[1])
    req = VerificationRequest(candidates=[CandidateInput(**cand)], search_radius_arcsec=6.0)
    res = asyncio.run(verify_candidates(req))
    return res.results[0].model_dump()


def _quick_checks(cands):
    from ..models.schemas import Candidate
    from ..routes.checks import verify_one
    out = {}
    for c in cands:
        try:
            out[c["candidate_id"]] = verify_one(Candidate(**c)).model_dump()
        except Exception as e:  # an archive was down: keep going
            out[c["candidate_id"]] = {"verification_status": "pending", "plain_english": f"check failed: {e}"}
    return out


def _validation():
    from ..routes import validation as val
    return [val._measure(*t) for t in val.TARGETS]


# ---------------------------------------------------------------- the report
def build(job, x: int | None = None, y: int | None = None, band: int = 0, label: str | None = None,
          pm: tuple | None = None, site: str = "", external: bool = True) -> tuple[bytes, str]:
    t_start = time.time()
    from astropy import __version__ as astropy_version
    from astropy import units as u
    from astropy.coordinates import SkyCoord

    n = job.arrays["flux"].shape[-1]
    c = (n - 1) / 2
    target_px = x is None or y is None
    x = int(round(c)) if x is None else int(x)
    y = int(round(c)) if y is None else int(y)
    wcs = im.make_grid(job.ra, job.dec, job.fov)[0]
    ora, odec = (float(v) for v in wcs.pixel_to_world_values(x, y))
    centre = SkyCoord(job.ra * u.deg, job.dec * u.deg)
    obj = SkyCoord(ora * u.deg, odec * u.deg)
    visits = _visit_rows(job)
    mains = [v for v in visits if v["main"]]
    mjds = [m["mjd"] for m in job.meta]
    baseline = (max(mjds) - min(mjds)) / 365.25 if mjds else 0
    releases = sorted({m.get("release", "") for m in job.meta if m.get("release")})
    ranges = im.det_ranges(job.meta)
    now = datetime.now(timezone.utc)
    report_no = f"SKYSHIFT-TR-{now:%Y%m%d-%H%M}-{job.id[:6].upper()}"
    field = f"RA {job.ra:.4f}  Dec {job.dec:+.4f}"
    name = label or ("field centre" if target_px else f"pixel ({x}, {y})")

    # detections (same method as the website), spectrum, light curve
    dets = detection.run(job.arrays, job.meta, wcs, jobs.main_visits(job), det=band)
    cands = dets["candidates"]
    sp = jobs.spectrum(job, x, y, 1)
    pts = sp["points"]
    binned = sf.bin_spectrum(pts)
    feats = sf.measure_features([b for b in binned if not b["saturated"]])
    sat_frac = sum(b["saturated"] for b in binned) / max(1, len(binned))
    by_visit = {v["visit"]: sf.bin_spectrum([p for p in pts if p["visit"] == v["visit"]]) for v in mains}
    lc = []
    for v in mains:
        row = {"visit": v["visit"], "date": v["start"]}
        for key, b in (("all", 0), ("red", 7)):
            img, k = _stack(job, v["visit"], b)
            row[key] = _aperture(img, x, y) * im.MJYSR_TO_UJY if img is not None else float("nan")
            row[f"n_{key}"] = k
        lc.append(row)
    near = [cd for cd in cands if cd["kind"] == "mover" and math.hypot(cd["x"] - x, cd["y"] - y) < 3]
    if pm is None and near and near[0].get("motion"):
        pm = (near[0]["motion"].get("pmra_mas_yr"), near[0]["motion"].get("pmdec_mas_yr"))

    # outside services, in parallel, with a time limit (a slow archive must not block the report)
    xmatch = checks = valid = None
    notes = []
    if external:
        mid = float(np.median(mjds)) if mjds else 61000.0
        with ThreadPoolExecutor(max_workers=3) as ex:
            fx = ex.submit(_crossmatch, ora, odec, mid, pm)
            fc = ex.submit(_quick_checks, cands[:6])
            fv = ex.submit(_validation)
            for fut, key in ((fx, "x"), (fc, "c"), (fv, "v")):
                try:
                    r = fut.result(timeout=max(5, 75 - (time.time() - t_start)))
                except Exception as e:
                    r = None
                    notes.append({"x": "catalogue cross-match", "c": "candidate checks", "v": "method validation"}[key]
                                 + f" unavailable ({type(e).__name__})")
                if key == "x":
                    xmatch = r
                elif key == "c":
                    checks = r
                else:
                    valid = r

    # images: first and last main visit, and their difference
    figs = []
    if len(mains) >= 2:
        a, na = _stack(job, mains[0]["visit"], band)
        b, nb = _stack(job, mains[-1]["visit"], band)
        if a is not None and b is not None:
            figs = [(im.render_png(a), f"First visit ({mains[0]['start']}, {na} exposures)"),
                    (im.render_png(b), f"Last visit ({mains[-1]['start']}, {nb} exposures)"),
                    (im.render_png(b - a, diverging=True), "Difference (last - first): orange = brighter now, blue = brighter before")]

    band_name = {0: "all six detectors stacked", 7: "detectors D5+D6 (3.8-5.0 um)"}.get(band, f"detector D{band}")

    # ------------------------------------------------------------ story
    S = []
    S += [P("SKYSHIFT TECHNICAL REPORT", "sub"),
          P(txt(f"SPHEREx multi-epoch analysis: {name}"), "title"),
          P(txt(f"Report {report_no}  |  generated {now:%Y-%m-%d %H:%M} UTC  |  {VERSION}"), "sub")]
    gal = centre.galactic
    S += [kv([
        ("Field centre (ICRS)", txt(f"RA {job.ra:.6f} deg, Dec {job.dec:+.6f} deg  ({centre.to_string('hmsdms', precision=2)})")),
        ("Field centre (Galactic)", txt(f"l = {gal.l.deg:.4f} deg, b = {gal.b.deg:+.4f} deg")),
        ("Object of interest", txt(f"{name}: RA {ora:.6f}, Dec {odec:+.6f} (pixel x={x}, y={y}); "
                                   f"{obj.separation(centre).arcsec:.1f} arcsec from the field centre")),
        ("Field of view / grid", txt(f"{job.fov:g} arcmin square; {n} x {n} pixels of {im.PIX_ARCSEC} arcsec, TAN projection, north up, east left")),
        ("Data", txt(f"{len(job.meta)} SPHEREx exposures in {len(visits)} visits ({len(mains)} main); releases: {', '.join(releases) or '-'}")),
        ("Time span", txt(f"MJD {min(mjds):.3f} - {max(mjds):.3f} ({visits[0]['start']} to {visits[-1]['end']}); baseline {baseline:.2f} yr") if mjds else "-"),
        ("Analysis band", txt(band_name)),
        ("Data version", txt(f"spot version {job.version}, built {datetime.fromtimestamp(job.built_at, tz=timezone.utc):%Y-%m-%d %H:%M} UTC" if job.built_at else f"spot version {job.version}")),
        ("Software", txt(f"{VERSION}; Python {platform.python_version()}; NumPy {np.__version__}; Astropy {astropy_version}")),
    ])]

    # abstract
    movers = [cd for cd in cands if cd["kind"] == "mover"]
    variables = [cd for cd in cands if cd["kind"] == "variable"]
    abs_txt = (f"We analyse {len(job.meta)} NASA SPHEREx exposures ({', '.join(releases)}) of a {job.fov:g} arcmin field centred on "
               f"RA {job.ra:.4f}, Dec {job.dec:+.4f}, spanning {baseline:.2f} yr in {len(mains)} main visits. Exposures are re-projected to a "
               f"common {im.PIX_ARCSEC} arcsec grid, cleaned of zodiacal light and background, and stacked per visit with inverse-variance "
               f"weights. Comparing visits in units of the propagated noise, SkyShift finds {len(movers)} moving and {len(variables)} "
               f"variable source(s) at >= 5 sigma.")
    if near:
        m_ = near[0]["motion"]
        abs_txt += (f" The object of interest moves {m_['total_arcsec_yr']:.2f} +/- {m_.get('total_err_arcsec_yr') or 0:.2f} arcsec/yr "
                    f"toward position angle {m_['pa_deg']:.1f} deg ({m_.get('method', 'two-visit difference')}).")
    if xmatch:
        abs_txt += f" Catalogue identification: {xmatch.get('assessment', '-').replace('_', ' ')}."
        ex_ = xmatch.get("exoplanet_association") or {}
        if ex_.get("status") == "match_found":
            abs_txt += f" The NASA Exoplanet Archive lists {ex_.get('planet_count')} planet(s) for this host."
    abs_txt += (f" The spectrum of the object combines {len(pts)} exposures into {len(binned)} of 102 channels"
                f"{'; the source saturates the detector, so fluxes are lower limits' if sat_frac > 0.5 else ''}.")
    S += [P("Abstract", "h1"), P(txt(abs_txt), "abs")]

    # 1. data
    S += [P("1. Observations and data", "h1"),
          P(txt("SPHEREx images the sky with six H2RG detector arrays (D1-D6) behind linear variable filters, giving 102 spectral "
                "channels (17 per detector) from 0.75 to 5.0 um, with 6.15 arcsec pixels. Level-2 calibrated images were found with "
                "the IRSA Simple Image Access service (collections listed above) and retrieved as cutouts from the IRSA cutout service; "
                "each cutout keeps the IMAGE, FLAGS, VARIANCE, ZODI and WCS-WAVE extensions.")),
          P("Table 1. Detector bandpasses and exposures in this field.", "cap")]
    rows = [["Detector", "Wavelength range (um)", "Exposures", "Channels"]]
    for d in range(1, 7):
        lo, hi = ranges.get(d, (float("nan"), float("nan")))
        rows.append([f"D{d}", f"{fnum(lo, '{:.3f}')} - {fnum(hi, '{:.3f}')}", str(sum(1 for m in job.meta if m["det"] == d)),
                     f"{(d - 1) * 17 + 1}-{d * 17}"])
    S += [table(rows, [24 * mm, 50 * mm, 30 * mm, 30 * mm])]
    S += [P("Table 2. Visits (groups of exposures separated by > 20 days). Main visits (>= 20 exposures) are used for stacking, detection and motion fits.", "cap")]
    rows = [["Visit", "Start", "End", "Mean MJD", "Exposures", "Detectors", "Main", "Release(s)"]]
    for v in visits:
        rows.append([str(v["visit"]), v["start"], v["end"], f"{v['mjd']:.3f}", str(v["n"]), " ".join(f"D{d}" for d in v["dets"]),
                     "yes" if v["main"] else "no", txt(", ".join(v["releases"]))])
    S += [table(rows, [12 * mm, 20 * mm, 20 * mm, 22 * mm, 17 * mm, 34 * mm, 11 * mm, CW - 136 * mm])]

    # 2. processing
    S += [P("2. Processing", "h1")]
    S += [P(t, "bul") for t in [
        "&bull; <b>Re-projection.</b> Every exposure is resampled (bilinear, including SIP distortion) onto one tangent-plane grid centred on the field, north up, 6.15 arcsec per pixel; the wavelength of each pixel comes from the WCS-WAVE extension.",
        "&bull; <b>Background.</b> The ZODI model is subtracted, then a smooth background (block median) is removed.",
        "&bull; <b>Quality flags.</b> " + txt(f"Pixels flagged {', '.join(im.HARD)} are masked; {', '.join(im.SAT)} mark saturation "
                                              f"(blank saturated cores are filled from the brightest neighbour for display only); "
                                              f"{', '.join(im.WARN)} are reported as contamination warnings."),
        "&bull; <b>Stacking.</b> Exposures of one visit are combined with inverse-variance weights.",
        "&bull; <b>Detection.</b> For each pair of main visits the difference image is divided by the combined noise and rescaled to unit scatter; peaks above 5 sigma are kept. A 'was here' dip paired with an 'is here now' bump within 6 pixels is a mover; an unpaired change on a real source is a variable. Residuals smaller than 25 percent or larger than 160 percent of the source are rejected as alignment or artefact residuals.",
        "&bull; <b>Motion.</b> Each mover is followed through every main visit (brightness-weighted centroid near the predicted position) and a straight line is fitted by least squares; the uncertainty comes from the scatter about the line (or the centroid precision, ~1/SNR pixel, for two visits).",
        "&bull; <b>Spectrum.</b> In every exposure the flux in a 3 x 3 pixel box minus the median of a surrounding annulus is converted from MJy/sr to micro-Jansky; exposures are binned by channel (median, with the standard error).",
        "&bull; <b>Molecular and mineral bands.</b> Each band's depth is measured against the continuum on both sides and reported with its significance.",
    ]]

    # 3. images
    if figs:
        S += [CondPageBreak(70 * mm), P("3. Images", "h1")]
        w = (CW - 8 * mm) / 3
        S += [Table([[png_image(p, w) for p, _ in figs], [P(txt(cap), "cap") for _, cap in figs]], colWidths=[w + 2.6 * mm] * 3,
                    style=[("VALIGN", (0, 0), (-1, -1), "TOP")])]
        S += [P(txt(f"Figure 1. SPHEREx stacks of the first and last main visits ({band_name}) and their difference. "
                    f"Each panel is {job.fov:g} arcmin wide, north up, east left; asinh stretch."), "cap")]

    # 4. detections
    S += [CondPageBreak(50 * mm), P("4. Detections", "h1")]
    if cands:
        S += [P(txt(f"Table 3. Sources that changed between main visits ({band_name}). Motion from the multi-visit fit; position angle east of north."), "cap")]
        rows = [["ID", "Type", "RA (deg)", "Dec (deg)", "S/N", "pmRA, pmDec (mas/yr)", "Total (arcsec/yr)", "PA (deg)", "Visits", "Ratio", "Check"]]
        for cd in cands:
            m_ = cd.get("motion") or {}
            fc = cd.get("flux_change") or {}
            chk = (checks or {}).get(cd["candidate_id"], {})
            rows.append([cd["candidate_id"], cd["kind"], f"{cd['ra']:.5f}", f"{cd['dec']:+.5f}", fnum(cd.get("snr"), "{:.0f}"),
                         f"{fnum(m_.get('pmra_mas_yr'), '{:.0f}')}, {fnum(m_.get('pmdec_mas_yr'), '{:.0f}')}" + (f" +/- {m_['err_mas_yr']:.0f}" if m_.get("err_mas_yr") else "") if m_ else "-",
                         f"{fnum(m_.get('total_arcsec_yr'), '{:.3f}')}" + (f" +/- {m_['total_err_arcsec_yr']:.3f}" if m_.get("total_err_arcsec_yr") else "") if m_ else "-",
                         fnum(m_.get("pa_deg"), "{:.1f}") if m_ else "-", str(m_.get("n_visits", "-")) if m_ else "-",
                         f"x{fc['ratio']:.2f}" if fc.get("ratio") else "-",
                         txt(chk.get("verification_status", "-")).replace("_", " ") + (" (sat.)" if cd.get("saturated") else "")])
        S += [table(rows, [10 * mm, 13 * mm, 17 * mm, 17 * mm, 9 * mm, 27 * mm, 23 * mm, 12 * mm, 10 * mm, 12 * mm, CW - 150 * mm])]
        if checks:
            S += [P(txt("Candidate checks: each candidate was compared with Gaia DR3 (moved to the observation date), AllWISE, SIMBAD and, for one-off spots, IMCCE SkyBoT asteroid positions."), "cap")]
    else:
        S += [P(txt(f"No source changed by more than 5 sigma between the main visits ({band_name})."))]

    # 5. object of interest
    S += [CondPageBreak(60 * mm), P(txt(f"5. Object of interest: {name}"), "h1")]
    S += [P("5.1 Identification", "h2")]
    if xmatch:
        ev = (xmatch.get("evidence_summary") or {}).get("catalogues", {})
        cr = xmatch.get("catalogue_results", {})
        S += [P(txt(f"Overall: {xmatch.get('assessment', '-').replace('_', ' ')}. Matching radius 6 arcsec; each catalogue position is "
                    "compared at its own epoch using the Gaia proper motion (or the object's own motion when Gaia has no match)."))]
        rows = [["Catalogue", "Result", "Separation (arcsec)", "Identifier", "Key values"]]
        for k, lab in (("gaia", "Gaia DR3"), ("2mass", "2MASS"), ("allwise", "AllWISE"), ("simbad", "SIMBAD")):
            e = ev.get(k, {})
            src = (cr.get(k) or {}).get("nearest_source") or {}
            if k == "gaia":
                ph, d_ = src.get("photometry") or {}, src.get("distance") or {}
                pmv = (src.get("proper_motion") or {}).get("total_mas_yr")
                vals = f"G {fnum(ph.get('g_magnitude'))}; BP-RP {fnum(ph.get('bp_rp'))}; pm {fnum(pmv, '{:.1f}')} mas/yr; d {fnum(d_.get('parsecs'), '{:.2f}')} pc"
            elif k == "2mass":
                ph = src.get("photometry") or {}
                vals = "; ".join(f"{b} {fnum((ph.get(b) or {}).get('magnitude'))}" for b in ("J", "H", "Ks"))
            elif k == "allwise":
                ph = src.get("photometry") or {}
                vals = "; ".join(f"{b} {fnum((ph.get(b) or {}).get('magnitude_vega'))}" for b in ("W1", "W2")) + f"; cc {src.get('quality_flags', {}).get('cc_flags', '-')}"
            else:
                vals = f"{src.get('object_type') or '-'}; SpT {src.get('spectral_type') or '-'}"
            rows.append([lab, txt(e.get("evidence", (cr.get(k) or {}).get("status", "-"))).replace("_", " "), fnum(e.get("separation_arcsec"), "{:.2f}"),
                         txt(e.get("source_identifier") or "-"), txt(vals)])
        S += [P("Table 4. Catalogue cross-match of the object of interest.", "cap"),
              table(rows, [22 * mm, 30 * mm, 24 * mm, 42 * mm, CW - 118 * mm])]
        colours_ = (xmatch.get("photometric_assessment") or {}).get("colours") or {}
        if colours_:
            S += [P(txt("Colours: " + "; ".join(f"{c_['name']} = {fnum(c_.get('value'), '{:.3f}')} +/- {fnum(c_.get('uncertainty'), '{:.3f}')} ({c_.get('quality', '')})" for c_ in colours_.values())))]
        names = ((xmatch.get("object_profile") or {}).get("identity") or {}).get("alternative_names") or []
        if names:
            S += [P(txt("Other identifiers: " + ", ".join(names[:15])))]
        ex_ = xmatch.get("exoplanet_association") or {}
        if ex_.get("status") == "match_found" and ex_.get("planets"):
            rows = [["Planet", "Period (d)", "Radius (Earth)", "Mass (Earth)"]]
            for p in sorted(ex_["planets"], key=lambda p: (p.get("planet_parameters") or {}).get("orbital_period_days") or 1e9):
                q = p.get("planet_parameters") or {}
                mj = q.get("mass_jupiter_masses")
                rows.append([txt(p.get("planet_name")), fnum(q.get("orbital_period_days"), "{:.3f}"), fnum(q.get("radius_earth_radii")),
                             fnum(mj * 317.8 if mj is not None else None)])
            S += [P(txt(f"Table 5. Known planets of this host (NASA Exoplanet Archive; matched by {ex_.get('association_method', '-')})."), "cap"),
                  table(rows, [50 * mm, 30 * mm, 30 * mm, 30 * mm])]
        else:
            S += [P(txt(f"NASA Exoplanet Archive: {ex_.get('message') or 'no known planet host here'}."))]
    else:
        S += [P(txt("The catalogue cross-match was not available when this report was generated (outside archives unreachable or slow)."))]

    S += [P("5.2 Spectrum", "h2")]
    good = [b for b in binned if not b["saturated"] or sat_frac > 0.5]
    palette = [colors.HexColor(h) for h in ("#1f77b4", "#2ca02c", "#9467bd", "#8c564b", "#17becf")]
    series = [{"points": [(b["wave"], b["flux"], b["err"]) for b in good], "color": ACCENT, "kind": "line", "err": True, "markers": True,
               "label": "all visits (median per channel)", "width": 1.1}]
    for k_, (v, bb) in enumerate(by_visit.items()):
        if len(bb) >= 10:
            series.append({"points": [(b["wave"], b["flux"], None) for b in bb if not b["saturated"] or sat_frac > 0.5],
                           "color": palette[k_ % len(palette)], "kind": "line", "dash": [2, 2], "width": 0.6,
                           "label": f"visit {v}"})
    fbands = [(f["center_um"] - f["half_width_um"], f["center_um"] + f["half_width_um"],
               colors.Color(0.2, 0.45, 0.85, alpha=0.12 if f["status"] == "likely" else 0.07))
              for f in feats if f["status"] in ("likely", "possible")]
    S += [plot(series, CW, 62 * mm, "wavelength (um)", "flux density (micro-Jy)", bands=fbands, xlim=(0.7, 5.05)),
          P(txt(f"Figure 2. SPHEREx spectrum of {name} ({len(pts)} exposures binned into {len(binned)} channels; error bars = standard "
                f"error per channel). Shaded: bands where a feature is likely or possible."
                + (" The source saturates the detector: fluxes are lower limits." if sat_frac > 0.5 else "")), "cap")]
    shown = [f for f in feats if f["status"] != "not seen"] or feats[:8]
    if shown:
        rows = [["Band", "Centre (um)", "Change (%)", "Significance (sigma)", "Result"]]
        for f in shown[:14]:
            rows.append([txt(f["name"]), f"{f['center_um']:.2f}", f"{f['change_pct']:+.1f}", fnum(f.get("significance"), "{:.1f}"), txt(f["status"])])
        S += [P("Table 6. Molecular, mineral and line features (depth against the neighbouring continuum).", "cap"),
              table(rows, [55 * mm, 25 * mm, 25 * mm, 32 * mm, CW - 137 * mm])]

    S += [P("5.3 Brightness per visit (light curve)", "h2")]
    if lc:
        rows = [["Visit", "Start", "Flux, all detectors (micro-Jy)", "Exposures", "Flux, D5+D6 (micro-Jy)", "Exposures"]]
        for r in lc:
            rows.append([str(r["visit"]), r["date"], fnum(r["all"], "{:.1f}"), str(r["n_all"]), fnum(r["red"], "{:.1f}"), str(r["n_red"])])
        S += [P("Table 7. Aperture photometry of the object in each main visit (radius 3 px, sky annulus 6-10 px).", "cap"),
              table(rows, [14 * mm, 24 * mm, 45 * mm, 20 * mm, 45 * mm, CW - 148 * mm])]
        ser = []
        for d in range(1, 7):
            pp = [(p["mjd"], p["flux"], p.get("err")) for p in pts if p["det"] == d and math.isfinite(p["flux"])]
            if pp:
                ser.append({"points": pp, "color": palette[(d - 1) % len(palette)] if d <= 5 else ACCENT, "kind": "points", "label": f"D{d}"})
        if ser:
            S += [plot(ser, CW, 50 * mm, "MJD", "flux density (micro-Jy)"),
                  P(txt("Figure 3. Flux of the object in every single exposure, by detector (each detector sees a different wavelength range, so the levels differ)."), "cap")]

    # 6. validation
    if valid:
        S += [CondPageBreak(50 * mm), P("6. Method validation", "h1"),
              P(txt("The same pipeline applied to the five SPHEREx challenge targets, compared with catalogue values (worked out at report time)."))]
        rows = [["Target", "SkyShift", "Catalogue", "Difference", "Verdict"]]
        for r in valid:
            if r.get("status") != "ok":
                rows.append([txt(r.get("target")), txt(r.get("message", "-")), "-", "-", "-"])
            elif r["kind"] == "mover":
                rows.append([txt(r["target"]), f"{r['measured_arcsec_yr']:.3f} +/- {fnum(r.get('measured_err_arcsec_yr'), '{:.3f}')} arcsec/yr, PA {r['measured_pa_deg']:.1f}",
                             f"{r['known_arcsec_yr']:.3f} arcsec/yr, PA {r['known_pa_deg']:.1f}", f"{r['diff_pct']:.1f}% ({fnum(r.get('n_sigma'), '{:.1f}')} sigma)", txt(r["verdict"])])
            else:
                rows.append([txt(r["target"]), txt(f"brightness changed x{r.get('brightness_change')} ({r.get('band_used', '')})"), txt(r["reference"]), "-", txt(r["verdict"])])
        S += [P("Table 8. Method validation on the challenge targets.", "cap"), table(rows, [32 * mm, 48 * mm, 44 * mm, 26 * mm, CW - 150 * mm])]

    # 7. reproducibility
    base = site.rstrip("/")
    S += [CondPageBreak(40 * mm), P("7. Data availability and reproducibility", "h1"), kv([
        ("Interactive view", txt(f"{base}/?ra={job.ra:.5f}&dec={job.dec:.5f}&fov={job.fov:g}")),
        ("Frames (API)", txt(f"{base}/api/images/{job.id}/frames?mode=visit&det={band}")),
        ("Spectrum (API)", txt(f"{base}/api/images/{job.id}/spectrum?x={x}&y={y}&r=1")),
        ("Detections (API)", txt(f"POST {base}/api/detections/run  {{query_id: {job.id}, band: {band}}}")),
        ("Catalogue check (API)", txt(f"POST {base}/api/verification/  (Gaia DR3, 2MASS, AllWISE, SIMBAD, NASA Exoplanet Archive)")),
        ("This report", txt(f"{base}/api/images/{job.id}/report.pdf?x={x}&y={y}&band={band}")),
        ("Query id / version", txt(f"{job.id} / {job.version}")),
    ])]
    if notes:
        S += [P(txt("Notes: " + "; ".join(notes) + "."), "cap")]

    # references
    S += [P("References and acknowledgements", "h1")]
    refs = [
        "Astropy Collaboration, Price-Whelan, A. M., et al. 2022, ApJ, 935, 167 (Astropy).",
        "Akeson, R. L., et al. 2013, PASP, 125, 989 (NASA Exoplanet Archive).",
        "Berthier, J., et al. 2006, ASP Conf. Ser., 351, 367 (SkyBoT).",
        "Boch, T., & Fernique, P. 2014, ASP Conf. Ser., 485, 277 (Aladin Lite).",
        "Cutri, R. M., et al. 2013, Explanatory Supplement to the AllWISE Data Release Products.",
        "Dore, O., et al. 2014, arXiv:1412.4872 (SPHEREx).",
        "Gaia Collaboration, Vallenari, A., et al. 2023, A&A, 674, A1 (Gaia DR3).",
        "Skrutskie, M. F., et al. 2006, AJ, 131, 1163 (2MASS).",
        "Wenger, M., et al. 2000, A&AS, 143, 9 (SIMBAD).",
        "Wright, E. L., et al. 2010, AJ, 140, 1868 (WISE).",
    ]
    S += [P(txt(r), "ref") for r in refs]
    S += [P(txt("This report uses data from the NASA SPHEREx mission and from the NASA/IPAC Infrared Science Archive, which is funded by "
                "NASA and operated by the California Institute of Technology; data from the ESA mission Gaia, processed by the Gaia DPAC; "
                "the Two Micron All Sky Survey (UMass and IPAC/Caltech, funded by NASA and NSF); the Wide-field Infrared Survey Explorer "
                "(UCLA and JPL/Caltech, funded by NASA); the SIMBAD database operated at CDS, Strasbourg; the NASA Exoplanet Archive "
                "(Caltech/NASA Exoplanet Science Institute); and the IMCCE SkyBoT service. Generated automatically; not peer reviewed."), "cap")]

    # appendices
    S += [PageBreak(), P("Appendix A. Spectrum of the object of interest (all channels)", "h1")]
    rows = [["Channel", "Wavelength (um)", "Flux (micro-Jy)", "Error (micro-Jy)", "Exposures", "Saturated"]]
    for b in binned:
        rows.append([str(b["channel"]), f"{b['wave']:.4f}", f"{b['flux']:.2f}", f"{b['err']:.2f}", str(b["n"]), "yes" if b["saturated"] else "no"])
    S += [table(rows, [22 * mm, 30 * mm, 30 * mm, 30 * mm, 22 * mm, CW - 134 * mm], font="tiny")]
    S += [PageBreak(), P("Appendix B. Exposures used", "h1"),
          P(txt(f"All {len(job.meta)} exposures (one row per exposure and detector), in time order."), "cap")]
    rows = [["#", "Observation id", "Det", "MJD", "Date (UTC)", "Centre lambda (um)", "Ch.", "Visit", "Release", "Cov."]]
    for m in sorted(job.meta, key=lambda m: m["mjd"]):
        rows.append([str(m["i"]), txt(m.get("obs_id", "")), f"D{m['det']}", f"{m['mjd']:.5f}", txt(m["date"][:19]), f"{m['wave']:.4f}",
                     str(m.get("channel", "")), str(m["visit"]), txt(m.get("release", "")), f"{m.get('coverage', 0):.2f}"])
    S += [table(rows, [8 * mm, 40 * mm, 8 * mm, 19 * mm, 27 * mm, 18 * mm, 12 * mm, 10 * mm, 20 * mm, CW - 162 * mm], font="tiny")]
    if job.flag_defs:
        S += [CondPageBreak(40 * mm), P("Appendix C. SPHEREx quality flags", "h1"), P("Table C1. Flag bits from the FLAGS extension header and how SkyShift uses them.", "cap")]
        rows = [["Flag", "Bit", "Meaning", "SkyShift"]]
        for nm, d in sorted(job.flag_defs.items(), key=lambda kv_: kv_[1].get("bit", 0)):
            use = "masked" if nm in im.HARD else "saturation" if nm in im.SAT else "warning" if nm in im.WARN else "-"
            rows.append([txt(nm), str(d.get("bit", "")), txt(d.get("meaning", "")), use])
        S += [table(rows, [32 * mm, 12 * mm, CW - 70 * mm, 26 * mm], font="tiny")]

    buf = io.BytesIO()
    doc = BaseDocTemplate(buf, pagesize=A4, leftMargin=M, rightMargin=M, topMargin=17 * mm, bottomMargin=17 * mm,
                          title=f"SkyShift technical report {report_no}", author="SkyShift (automated report)",
                          subject=f"SPHEREx multi-epoch analysis of {name}", creator=VERSION)
    frame = Frame(M, 17 * mm, CW, H - 34 * mm, leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc.addPageTemplates([PageTemplate(id="p", frames=[frame], onPage=_page(report_no, site.rstrip("/") or "SkyShift", field))])
    doc.build(S)
    return buf.getvalue(), report_no
