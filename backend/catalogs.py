"""Name lookup and overlays from other surveys: Gaia DR3, AllWISE, and known asteroids (SkyBoT)."""
from __future__ import annotations

import csv
import io
import math
import re
import time
import xml.etree.ElementTree as ET
from functools import lru_cache

import astropy.units as u
from astropy.coordinates import SkyCoord

from .sphx import SESSION, tap

GAIA_TAP = "https://gea.esac.esa.int/tap-server/tap/sync"
VIZIER_TAP = "https://tapvizier.cds.unistra.fr/TAPVizieR/tap/sync"
SKYBOT = "https://ssp.imcce.fr/webservices/skybot/api/conesearch.php"

# Middle of the SPHEREx data so far. Fast-moving stars are centred where they are *now*, not in 2000.
DATA_EPOCH = 2026.0


def parse_coords(text: str) -> tuple[float, float] | None:
    s = text.strip().replace(",", " ")
    if not s:
        return None
    nums = re.fullmatch(r"\s*([+-]?\d+(?:\.\d+)?)\s+([+-]?\d+(?:\.\d+)?)\s*", s)
    try:
        if nums:  # plain decimal degrees
            ra, dec = float(nums.group(1)), float(nums.group(2))
            if 0 <= ra < 360 and -90 <= dec <= 90:
                return ra, dec
            return None
        if re.search(r"\d", s) and (re.search(r"[hms:d°'\"]", s) or len(s.split()) == 6):
            c = SkyCoord(s, unit=(u.hourangle, u.deg))
            return float(c.ra.deg), float(c.dec.deg)
    except Exception:
        return None
    return None


# The challenge's test targets, built in so the demo never depends on a name server.
# J2000 positions and proper motions (mas/yr) from SIMBAD via Sesame.
PRESETS = {
    "barnard's star": ("Barnard's Star", 269.45207696, 4.69336497, -801.551, 10362.394),
    "eps ind b": ("Epsilon Indi B (Ba/Bb)", 331.04414659, -56.7828442, 3981.977, -2466.832),
    "wise j085510.83-071442.5": ("WISE 0855-0714", 133.81890825, -7.247048, -8123.7, 673.2),
    "rw aur": ("RW Aurigae", 76.95652603, 30.40143817, 7.23, -20.33),
    "r dra": ("R Draconis", 248.16761083, 66.75497942, -20.643, 6.149),
}
ALIASES = {
    "barnards star": "barnard's star", "barnard star": "barnard's star", "barnard": "barnard's star",
    "epsilon indi b": "eps ind b", "eps indi b": "eps ind b", "epsilon ind b": "eps ind b",
    "wise 0855": "wise j085510.83-071442.5", "wise 0855-0714": "wise j085510.83-071442.5",
    "wise0855": "wise j085510.83-071442.5", "rw aurigae": "rw aur", "r draconis": "r dra",
}
SESAME_MIRRORS = [
    "https://cds.unistra.fr/cgi-bin/nph-sesame/-oxp/SNV",
    "https://vizier.cfa.harvard.edu/viz-bin/nph-sesame/-oxp/SNV",
]


def _to_now(ra: float, dec: float, pmra: float, pmde: float) -> tuple[float, float]:
    """Move a star from its J2000 position to where it is at DATA_EPOCH."""
    dt = DATA_EPOCH - 2000.0
    ra2 = ra + pmra * dt / 3.6e6 / max(1e-6, abs(math.cos(math.radians(dec))))
    return ra2 % 360, dec + pmde * dt / 3.6e6


def _sesame(text: str) -> tuple[str, float, float, float, float]:
    last: Exception | None = None
    for base in SESAME_MIRRORS:
        try:
            r = SESSION.get(base + "?" + requests_quote(text), timeout=15)
            r.raise_for_status()
            res = ET.fromstring(r.content).find(".//Resolver")
            if res is None or res.find("jradeg") is None:
                raise LookupError(f"Could not find '{text}'. Try coordinates instead.")
            return (res.findtext("oname") or text, float(res.findtext("jradeg")), float(res.findtext("jdedeg")),
                    float(res.findtext("pm/pmRA") or 0), float(res.findtext("pm/pmDE") or 0))
        except LookupError:
            raise
        except Exception as e:  # mirror down or slow: try the next one
            last = e
    raise RuntimeError(f"name servers unreachable ({last})")


@lru_cache(maxsize=512)
def resolve(text: str) -> dict:
    """Coordinates in any format, or an object name (via CDS Sesame: SIMBAD, NED, VizieR)."""
    c = parse_coords(text)
    if c:
        return {"ra": c[0], "dec": c[1], "name": None, "source": "coordinates", "pm_corrected": False}
    key = re.sub(r"\s+", " ", text.strip().lower())
    key = ALIASES.get(key, key)
    if key in PRESETS:
        name, ra, dec, pmra, pmde = PRESETS[key]
        source = "built-in (SIMBAD)"
    else:
        name, ra, dec, pmra, pmde = _sesame(text)
        name = re.sub(r"^(NAME|\*+)\s+", "", name)
        source = "Sesame/SIMBAD"
    moved = bool(pmra or pmde)
    if moved:  # e.g. Barnard's Star has moved ~4.5 arcmin since 2000
        ra, dec = _to_now(ra, dec, pmra, pmde)
    return {"ra": ra, "dec": dec, "name": name, "source": source, "pm_corrected": moved, "pmra": pmra, "pmdec": pmde}


def requests_quote(s: str) -> str:
    from urllib.parse import quote
    return quote(s.strip())


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


def _sexa_ra(s: str) -> float:
    h, m, sec = (float(p) for p in s.split())
    return 15 * (h + m / 60 + sec / 3600)


def _sexa_dec(s: str) -> float:
    s = s.strip()
    sign = -1 if s.startswith("-") else 1
    d, m, sec = (abs(float(p)) for p in s.lstrip("+-").split())
    return sign * (d + m / 60 + sec / 3600)


@lru_cache(maxsize=1024)
def skybot(ra: float, dec: float, radius: float, mjd: float) -> dict:
    """Known asteroids and comets in the field at a given time (IMCCE SkyBoT, seen from Earth's centre)."""
    jd = mjd + 2400000.5
    params = {"-ep": f"{jd:.5f}", "-ra": f"{ra:.6f}", "-dec": f"{dec:.6f}", "-rd": f"{radius:.4f}",
              "-mime": "text", "-output": "basic", "-loc": "500", "-filter": "0", "-objFilter": "111",
              "-refsys": "EQJ2000", "-from": "SkyShift"}
    r = SESSION.get(SKYBOT, params=params, timeout=60)
    r.raise_for_status()
    out = []
    for line in r.text.splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        p = [x.strip() for x in line.split("|")]
        if len(p) < 10:
            continue
        try:
            out.append({"num": p[0], "name": p[1], "ra": _sexa_ra(p[2]), "dec": _sexa_dec(p[3]), "class": p[4],
                        "mag": float(p[5]), "dra": float(p[8]), "ddec": float(p[9])})  # motion in arcsec/hour
        except ValueError:
            continue
    return {"catalog": "SkyBoT", "mjd": mjd, "source": "IMCCE SkyBoT", "objects": out, "t": time.time()}
