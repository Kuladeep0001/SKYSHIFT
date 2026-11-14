"""Details card: what is this object? Pulled live from SIMBAD, Gaia, WISE and Wikipedia.

Owner: Verification developer.
"""
from __future__ import annotations

import csv
import io
import math
import re
from functools import lru_cache
from urllib.parse import quote

from . import gaia as cat
from .spherex import SESSION

SIMBAD_TAP = ["https://simbad.cds.unistra.fr/simbad/sim-tap/sync", "https://simbad.harvard.edu/simbad/sim-tap/sync"]
WIKI = "https://en.wikipedia.org/api/rest_v1/page/summary/"
LY_PER_PC = 3.26156

# SIMBAD object types in plain English (most common ones).
OTYPES = {
    "*": "star", "**": "double star", "PM*": "fast-moving (high proper motion) star", "BD*": "brown dwarf",
    "BD?": "possible brown dwarf", "LM*": "low-mass star", "RD*": "red dwarf", "Mi*": "Mira variable (pulsating giant)",
    "LP*": "long-period variable star", "V*": "variable star", "TT*": "young T Tauri star", "Or*": "young variable star",
    "Y*O": "young stellar object", "Ae*": "young Herbig star", "RG*": "red giant", "AB*": "asymptotic giant branch star",
    "C*": "carbon star", "WD*": "white dwarf", "EB*": "eclipsing binary star", "SB*": "spectroscopic binary",
    "HS*": "hot subdwarf", "s*r": "red supergiant", "G": "galaxy", "GiG": "galaxy in a group", "AGN": "active galaxy",
    "QSO": "quasar", "Sy1": "Seyfert galaxy", "Sy2": "Seyfert galaxy", "IR": "infrared source", "Pl": "planet",
    "As*": "group of stars", "Cl*": "star cluster", "GlC": "globular cluster", "OpC": "open cluster",
    "PN": "planetary nebula", "HII": "glowing gas cloud (H II region)", "MoC": "molecular cloud", "DNe": "dark nebula",
    "SN*": "supernova", "Em*": "emission-line star", "Be*": "Be star", "Psr": "pulsar", "X": "X-ray source",
    "Ce*": "Cepheid variable", "RR*": "RR Lyrae variable", "sg*": "supergiant", "HB*": "horizontal-branch star",
    "pr*": "pre-main-sequence star", "MS*": "main-sequence star", "Ro*": "rotating variable star",
    "BY*": "red dwarf with starspots (BY Draconis variable)", "Fl*": "flare star", "LP?": "possible long-period variable",
    "TT?": "possible young T Tauri star", "Y*?": "possible young star", "BD*?": "possible brown dwarf",
}


def _tap(url: str, query: str) -> list[dict]:
    r = SESSION.post(url, data={"REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "csv", "QUERY": query}, timeout=25)
    r.raise_for_status()
    if not r.text.lstrip().startswith(("main_id", '"')) and "<html" in r.text[:200].lower():
        raise IOError("SIMBAD returned an error page")
    return list(csv.DictReader(io.StringIO(r.text)))


@lru_cache(maxsize=256)
def simbad_near(ra: float, dec: float, year: float, radius_arcsec: float = 12.0) -> dict | None:
    """Nearest SIMBAD object at a given date (fast-moving stars are moved from their J2000 position)."""
    q = ("SELECT TOP 300 b.oid, b.main_id, b.otype, b.sp_type, b.ra, b.dec, b.plx_value, b.pmra, b.pmdec, "
         "b.rvz_radvel, b.nbref FROM basic AS b WHERE CONTAINS(POINT('ICRS', b.ra, b.dec), "
         f"CIRCLE('ICRS', {ra:.6f}, {dec:.6f}, 0.1)) = 1")
    rows, last = None, None
    for url in SIMBAD_TAP:
        try:
            rows = _tap(url, q)
            break
        except Exception as e:
            last = e
    if rows is None:
        raise IOError(f"SIMBAD unreachable ({last})")
    best = None
    for r in rows:
        try:
            st = {"ra": float(r["ra"]), "dec": float(r["dec"]), "pmra": float(r["pmra"] or 0), "pmdec": float(r["pmdec"] or 0)}
        except ValueError:
            continue
        sra, sdec = cat.move_to_epoch(st, year, 2000.0)
        d = cat.sep_arcsec(ra, dec, sra, sdec)
        if d > radius_arcsec:
            continue
        # Prefer the star itself over its planets, and well-studied objects when positions tie.
        rank = (r["otype"] == "Pl", round(d / 3), -int(r["nbref"] or 0))
        if best is None or rank < best[0]:
            best = (rank, r, d)
    if not best:
        return None
    _, r, d = best
    plx = float(r["plx_value"]) if r["plx_value"] else None
    name = re.sub(r"^(NAME|\*+|V\*)\s+", "", r["main_id"]).strip()
    otype = r["otype"]
    return {
        "main_id": r["main_id"], "name": name, "otype": otype, "type": OTYPES.get(otype, otype),
        "spectral_type": r["sp_type"] or None, "parallax_mas": plx,
        "distance_ly": round(1000 / plx * LY_PER_PC, 2) if plx and plx > 0 else None,
        "pm_mas_yr": round(math.hypot(float(r["pmra"] or 0), float(r["pmdec"] or 0)), 1),
        "radial_velocity_kms": float(r["rvz_radvel"]) if r["rvz_radvel"] else None,
        "n_references": int(r["nbref"] or 0), "separation_arcsec": round(d, 1),
        "url": f"https://simbad.cds.unistra.fr/simbad/sim-id?Ident={quote(r['main_id'])}",
    }


@lru_cache(maxsize=256)
def wikipedia(name: str) -> dict | None:
    """Short Wikipedia summary for well-known objects (we only try names, never search)."""
    tries = [name]
    m = re.match(r"^(eps|alf|bet|gam|del)\s+(\w+)", name)
    if m:  # Bayer names: "eps Ind B" -> "Epsilon Indi"
        greek = {"eps": "Epsilon", "alf": "Alpha", "bet": "Beta", "gam": "Gamma", "del": "Delta"}[m.group(1)]
        const = {"Ind": "Indi", "Cen": "Centauri", "Eri": "Eridani", "Lyr": "Lyrae", "Ori": "Orionis"}.get(m.group(2), m.group(2))
        tries.append(f"{greek} {const}")
    if name.startswith("R Dra"):
        tries.append("R Draconis")
    if name.startswith("RW Aur"):
        tries.append("RW Aurigae")
    if name.startswith("WISE J0855") or "0855" in name:
        tries.append("WISE 0855−0714")
    for t in tries:
        try:
            r = SESSION.get(WIKI + quote(t.replace(" ", "_")), timeout=12,
                            headers={"User-Agent": "SkyShift/0.2 (NASA Space Apps educational viewer)"})
            if r.status_code != 200:
                continue
            d = r.json()
            if d.get("type") == "disambiguation" or not d.get("extract"):
                continue
            return {"title": d.get("title"), "extract": d.get("extract"),
                    "thumbnail": (d.get("thumbnail") or {}).get("source"),
                    "url": (d.get("content_urls") or {}).get("desktop", {}).get("page")}
        except Exception:
            continue
    return None


def details(ra: float, dec: float, year: float, name_hint: str | None = None) -> dict:
    out: dict = {"ra": ra, "dec": dec, "sources": [], "errors": []}
    try:
        out["simbad"] = simbad_near(round(ra, 5), round(dec, 5), round(year, 2))
        out["sources"].append("SIMBAD")
    except Exception as e:
        out["simbad"] = None
        out["errors"].append(f"SIMBAD: {e}")
    for key, fetch, rad in (("gaia", cat.gaia, 12.0), ("wise", cat.allwise, 15.0)):
        try:
            m = cat.crossmatch(ra, dec, year, fetch(round(ra, 2), round(dec, 2), 0.06), rad)
            out[key] = m[0] if m else None
            out["sources"].append("Gaia DR3" if key == "gaia" else "AllWISE")
        except Exception as e:
            out[key] = None
            out["errors"].append(f"{key}: {e}")
    g = out.get("gaia")
    if g and g.get("plx", 0) > 0:
        g["distance_ly"] = round(1000 / g["plx"] * LY_PER_PC, 2)
    w = out.get("wise")
    if w and w.get("mag") is not None and w.get("w2") is not None:
        w["w1_w2"] = round(w["mag"] - w["w2"], 2)  # > ~0.8 means a very cool object (brown dwarf)
    sim = out.get("simbad")
    wiki_name = name_hint or (sim["name"] if sim and (sim["main_id"].startswith(("NAME", "V*", "*")) or sim["n_references"] > 50) else None)
    out["wikipedia"] = wikipedia(wiki_name) if wiki_name else None
    out["summary"] = _summary(out)
    coord = f"{ra:.5f} {dec:+.5f}"
    out["links"] = [
        {"label": "SIMBAD", "url": sim["url"] if sim else f"https://simbad.cds.unistra.fr/simbad/sim-coo?Coord={quote(coord)}&Radius=12&Radius.unit=arcsec"},
        {"label": "ESASky", "url": f"https://sky.esa.int/esasky/?target={quote(coord)}&fov=0.1"},
        {"label": "Aladin", "url": f"https://aladin.cds.unistra.fr/AladinLite/?target={quote(coord)}&fov=0.1"},
        {"label": "IRSA Finder Chart", "url": f"https://irsa.ipac.caltech.edu/applications/finderchart/?locstr={quote(coord)}"},
    ]
    if sim:
        out["links"].append({"label": "Research papers (ADS)", "url": f"https://ui.adsabs.harvard.edu/search/q=object%3A%22{quote(sim['main_id'])}%22"})
    if out["wikipedia"] and out["wikipedia"].get("url"):
        out["links"].append({"label": "Wikipedia", "url": out["wikipedia"]["url"]})
    return out


def _summary(d: dict) -> str:
    sim, g, w = d.get("simbad"), d.get("gaia"), d.get("wise")
    parts = []
    if sim:
        s = f"This is {sim['name']}, a {sim['type']}"
        if sim.get("spectral_type"):
            s += f" (type {sim['spectral_type']})"
        dist = sim.get("distance_ly") or (g or {}).get("distance_ly")
        if dist:
            s += f", about {dist:,.1f} light-years away" if dist < 1000 else f", about {dist:,.0f} light-years away"
        parts.append(s + ".")
        if sim["n_references"]:
            parts.append(f"It appears in {sim['n_references']:,} scientific papers.")
    elif g:
        s = "Gaia catalogues a star here"
        if g.get("distance_ly"):
            s += f" about {g['distance_ly']:,.0f} light-years away"
        parts.append(s + ", but it has no entry in SIMBAD, so it's not well studied.")
    elif w:
        parts.append("Only the WISE infrared survey has seen something here: it's red or cold, or very faint.")
    else:
        parts.append("No catalogue lists anything exactly here. It could be faint, new, or an artefact.")
    if g and g.get("pm_total", 0) > 100:
        parts.append(f"It moves {g['pm_total'] / 1000:.2f}″ per year across the sky (Gaia).")
    if w and w.get("w1_w2") is not None and w["w1_w2"] > 0.8:
        parts.append("Its WISE colours are very red, typical of cold brown dwarfs.")
    return " ".join(parts)
