"""Other telescopes: Gaia DR3 (ESA) and AllWISE (NASA), for overlays and for checking candidates."""
from __future__ import annotations

import csv
import io
import math
from functools import lru_cache

from .spherex import SESSION, tap

GAIA_TAP = "https://gea.esac.esa.int/tap-server/tap/sync"
VIZIER_TAP = "https://tapvizier.cds.unistra.fr/TAPVizieR/tap/sync"
GAIA_EPOCH = 2016.0
ALLWISE_EPOCH = 2010.5


def _csv(text: str) -> list[dict]:
    return list(csv.DictReader(io.StringIO(text)))


@lru_cache(maxsize=256)
def gaia(ra: float, dec: float, radius: float, gmax: float = 19.0) -> dict:
    """Gaia DR3 stars with proper motions (positions at epoch 2016.0)."""
    q = ("SELECT TOP 3000 source_id, ra, dec, pmra, pmdec, parallax, phot_g_mean_mag "
         "FROM gaiadr3.gaia_source WHERE 1=CONTAINS(POINT('ICRS', ra, dec), "
         f"CIRCLE('ICRS', {ra:.6f}, {dec:.6f}, {radius:.5f})) AND phot_g_mean_mag < {gmax} "
         "ORDER BY phot_g_mean_mag")
    try:
        r = SESSION.post(GAIA_TAP, data={"REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "csv", "QUERY": q},
                         timeout=60)
        r.raise_for_status()
        rows = _csv(r.text)
        src = "ESA Gaia archive"
    except Exception:  # fall back to the CDS copy of Gaia DR3
        q2 = ('SELECT TOP 3000 Source AS source_id, RA_ICRS AS ra, DE_ICRS AS dec, pmRA AS pmra, pmDE AS pmdec, '
              'Plx AS parallax, Gmag AS phot_g_mean_mag FROM "I/355/gaiadr3" WHERE 1=CONTAINS(POINT(\'ICRS\', '
              f"RA_ICRS, DE_ICRS), CIRCLE('ICRS', {ra:.6f}, {dec:.6f}, {radius:.5f})) AND Gmag < {gmax}")
        r = SESSION.post(VIZIER_TAP, data={"REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "csv", "QUERY": q2},
                         timeout=60)
        r.raise_for_status()
        rows = _csv(r.text)
        src = "CDS VizieR (Gaia DR3)"
    out = []
    for x in rows:
        try:
            out.append({"id": x["source_id"], "ra": float(x["ra"]), "dec": float(x["dec"]),
                        "pmra": float(x["pmra"] or 0), "pmdec": float(x["pmdec"] or 0),
                        "plx": float(x["parallax"] or 0), "mag": round(float(x["phot_g_mean_mag"]), 2)})
        except (ValueError, KeyError):
            continue
    return {"catalog": "Gaia DR3", "epoch": 2016.0, "source": src, "band": "G", "stars": out}


@lru_cache(maxsize=256)
def allwise(ra: float, dec: float, radius: float) -> dict:
    """AllWISE sources (positions measured around 2010.5; no proper-motion correction)."""
    rows = tap("SELECT TOP 3000 designation, ra, dec, w1mpro, w2mpro FROM allwise_p3as_psd "
               f"WHERE CONTAINS(POINT('ICRS', ra, dec), CIRCLE('ICRS', {ra:.6f}, {dec:.6f}, {radius:.5f})) = 1",
               timeout=60)
    out = []
    for x in rows:
        try:
            out.append({"id": x["designation"], "ra": float(x["ra"]), "dec": float(x["dec"]), "pmra": 0, "pmdec": 0,
                        "mag": round(float(x["w1mpro"]), 2) if x["w1mpro"] else None,
                        "w2": round(float(x["w2mpro"]), 2) if x["w2mpro"] else None})
        except (ValueError, KeyError):
            continue
    return {"catalog": "AllWISE", "epoch": 2010.5, "source": "NASA IRSA", "band": "W1", "stars": out}


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
