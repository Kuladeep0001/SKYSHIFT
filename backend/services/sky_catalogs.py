"""SkyShift star catalogues for overlays and quick checks (kept apart from the verification module's
services/gaia.py, which is owned by the verification role).

Other telescopes: Gaia DR3 (ESA) and AllWISE (NASA), for overlays and for checking candidates."""
from __future__ import annotations

import csv
import io
import math
import re
import xml.etree.ElementTree as ET
from functools import lru_cache

from .spherex import SESSION

GAIA_TAP = "https://gea.esac.esa.int/tap-server/tap/sync"
AIP_TAP = "https://gaia.aip.de/tap/sync"          # full Gaia DR3 mirror (same table and column names as ESA)
VIZIER_TAP = "https://tapvizier.cds.unistra.fr/TAPVizieR/tap/sync"
# Tried in order. Some networks can't reach ESA or CDS at all, so give up on connecting after 5 s and move on.
GAIA_MIRRORS = [(GAIA_TAP, "ESA Gaia archive"), (AIP_TAP, "Gaia DR3 mirror (AIP Potsdam)")]
TIMEOUT = (5, 60)   # seconds: connect, read


def _votable_rows(text: str) -> list[dict]:
    """Rows of a VOTable (what the AIP mirror returns even when CSV is asked for), as csv.DictReader would give them."""
    root = ET.fromstring(text)
    ns = root.tag.split("}")[0] + "}" if root.tag.startswith("{") else ""
    for info in root.iter(f"{ns}INFO"):
        if info.get("name") == "QUERY_STATUS" and info.get("value", "").upper() == "ERROR":
            raise IOError((info.text or "TAP query error").strip())
    table = next(root.iter(f"{ns}TABLE"), None)
    if table is None:
        return []
    names = [f.get("name") for f in table.iter(f"{ns}FIELD")]
    rows = []
    for tr in table.iter(f"{ns}TR"):
        vals = [(td.text or "") for td in tr.findall(f"{ns}TD")]
        rows.append(dict(zip(names, vals)))
    return rows


def tap_rows(url: str, query: str, timeout=TIMEOUT) -> list[dict]:
    """One synchronous TAP query -> rows (CSV or VOTable answer)."""
    r = SESSION.post(url, data={"REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "csv", "QUERY": query}, timeout=timeout)
    r.raise_for_status()
    text = r.text
    if text.lstrip().startswith("<"):
        return _votable_rows(text)
    return _csv(text)


def gaia_query(query: str, timeout=TIMEOUT) -> tuple[list[dict], str]:
    """Run an ADQL query against gaiadr3.gaia_source at the first Gaia server that answers. Returns (rows, server)."""
    last = None
    for url, name in GAIA_MIRRORS:
        q, order = query, None
        if url != GAIA_TAP:   # the mirror times out on sorted queries: fetch unsorted, sort here
            m = re.search(r"\s+ORDER\s+BY\s+(\w+)\s*(ASC|DESC)?\s*$", q, re.I)
            if m:
                order, q = (m.group(1), (m.group(2) or "").upper() == "DESC"), q[: m.start()]
        try:
            rows = tap_rows(url, q, timeout)
        except Exception as e:
            last = e
            continue
        if order and rows and order[0] in rows[0]:
            def key(r, col=order[0]):
                try:
                    return float(r[col])
                except (TypeError, ValueError):
                    return math.inf
            rows.sort(key=key, reverse=order[1])
        return rows, name
    raise IOError(f"no Gaia server could be reached ({last})")
GAIA_EPOCH = 2016.0
_GAIA = {"table": "gaiadr3.gaia_source", "release": "Gaia DR3", "epoch": 2016.0, "t": 0.0}
_NEWER = [("gaiadr4.gaia_source", "Gaia DR4")]  # tried in order; used as soon as ESA publishes them


def gaia_release(force: bool = False) -> dict:
    """Which Gaia release to use. Re-checked once a day, so a new release is picked up automatically."""
    import time as _t
    if not force and _t.time() - _GAIA["t"] < 86400:
        return _GAIA
    for table, name in _NEWER:
        try:
            r = SESSION.post(GAIA_TAP, data={"REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "csv",
                                             "QUERY": f"SELECT TOP 1 source_id, ref_epoch FROM {table}"}, timeout=(5, 20))
            lines = r.text.strip().splitlines()
            if r.ok and lines and lines[0].startswith("source_id") and len(lines) > 1:
                _GAIA.update(table=table, release=name, epoch=float(lines[1].split(",")[1]))
                break
        except Exception:
            pass
    _GAIA["t"] = _t.time()
    return _GAIA
ALLWISE_EPOCH = 2010.5


def _csv(text: str) -> list[dict]:
    return list(csv.DictReader(io.StringIO(text)))


def gaia(ra: float, dec: float, radius: float, gmax: float = 19.0) -> dict:
    """Gaia stars with proper motions, from the newest release that is online."""
    rel = gaia_release()
    return _gaia(rel["table"], rel["release"], rel["epoch"], ra, dec, radius, gmax)


@lru_cache(maxsize=256)
def _gaia(table: str, release: str, epoch: float, ra: float, dec: float, radius: float, gmax: float) -> dict:
    q = ("SELECT TOP 3000 source_id, ra, dec, pmra, pmdec, parallax, phot_g_mean_mag "
         f"FROM {table} WHERE 1=CONTAINS(POINT('ICRS', ra, dec), "
         f"CIRCLE('ICRS', {ra:.6f}, {dec:.6f}, {radius:.5f})) AND phot_g_mean_mag < {gmax} "
         "ORDER BY phot_g_mean_mag")
    try:
        rows, src = gaia_query(q)
        used, used_epoch = release, epoch
    except Exception:  # fall back to the CDS copy of Gaia DR3
        q2 = ('SELECT TOP 3000 Source AS source_id, RA_ICRS AS ra, DE_ICRS AS dec, pmRA AS pmra, pmDE AS pmdec, '
              'Plx AS parallax, Gmag AS phot_g_mean_mag FROM "I/355/gaiadr3" WHERE 1=CONTAINS(POINT(\'ICRS\', '
              f"RA_ICRS, DE_ICRS), CIRCLE('ICRS', {ra:.6f}, {dec:.6f}, {radius:.5f})) AND Gmag < {gmax}")
        rows = tap_rows(VIZIER_TAP, q2)
        src = "CDS VizieR (Gaia DR3)"
        used, used_epoch = "Gaia DR3", 2016.0
    out = []
    for x in rows:
        try:
            out.append({"id": x["source_id"], "ra": float(x["ra"]), "dec": float(x["dec"]),
                        "pmra": float(x["pmra"] or 0), "pmdec": float(x["pmdec"] or 0),
                        "plx": float(x["parallax"] or 0), "mag": round(float(x["phot_g_mean_mag"]), 2)})
        except (ValueError, KeyError):
            continue
    return {"catalog": used, "epoch": used_epoch, "source": src, "band": "G", "stars": out}


GATOR = "https://irsa.ipac.caltech.edu/cgi-bin/Gator/nph-query"


@lru_cache(maxsize=256)
def allwise(ra: float, dec: float, radius: float) -> dict:
    """AllWISE sources (positions measured around 2010.5; no proper-motion correction).

    Uses IRSA's Gator cone search, which is much faster than a general TAP query.
    """
    r = SESSION.get(GATOR, params={"catalog": "allwise_p3as_psd", "spatial": "cone", "radius": f"{radius * 3600:.1f}",
                                   "radunits": "arcsec", "objstr": f"{ra:.6f} {dec:+.6f}", "outfmt": "1",
                                   "selcols": "designation,ra,dec,w1mpro,w2mpro"}, timeout=(5, 60))
    r.raise_for_status()
    cols, out = None, []
    for line in r.text.splitlines():
        if line.startswith("\\"):
            continue
        if line.startswith("|"):
            cols = cols or [c.strip() for c in line.strip("|").split("|")]
            continue
        if not cols or not line.strip():
            continue
        x = dict(zip(cols, line.split()))
        try:
            num = lambda k: None if x.get(k) in (None, "null") else round(float(x[k]), 2)
            out.append({"id": x["designation"], "ra": float(x["ra"]), "dec": float(x["dec"]), "pmra": 0, "pmdec": 0,
                        "mag": num("w1mpro"), "w2": num("w2mpro")})
        except (ValueError, KeyError):
            continue
    return {"catalog": "AllWISE", "epoch": ALLWISE_EPOCH, "source": "NASA IRSA", "band": "W1", "stars": out}


def mjd_to_year(mjd: float) -> float:
    return 2000.0 + (mjd - 51544.5) / 365.25


def move_to_epoch(star: dict, year: float, from_epoch: float) -> tuple[float, float]:
    """Apply proper motion (mas/yr) to get a star's position at another date."""
    dt = year - from_epoch
    dec = star["dec"] + star.get("pmdec", 0) * dt / 3.6e6
    ra = star["ra"] + star.get("pmra", 0) * dt / 3.6e6 / max(1e-6, math.cos(math.radians(star["dec"])))
    return ra, dec


def sep_arcsec(ra1: float, dec1: float, ra2: float, dec2: float) -> float:
    """Angular distance (small-angle approximation, fine for arcsecond scales)."""
    dra = (ra1 - ra2 + 180) % 360 - 180
    return 3600 * math.hypot(dra * math.cos(math.radians((dec1 + dec2) / 2)), dec1 - dec2)


def crossmatch(ra: float, dec: float, year: float, catalog: dict, radius_arcsec: float) -> list[dict]:
    """Catalogue stars within radius of (ra, dec) at a given date, nearest first."""
    out = []
    for st in catalog["stars"]:
        sra, sdec = move_to_epoch(st, year, catalog["epoch"])
        d = sep_arcsec(ra, dec, sra, sdec)
        if d <= radius_arcsec:
            out.append({**st, "catalog": catalog["catalog"], "sep_arcsec": round(d, 2),
                        "pm_total": round(math.hypot(st.get("pmra", 0), st.get("pmdec", 0)), 1)})
    return sorted(out, key=lambda m: m["sep_arcsec"])
