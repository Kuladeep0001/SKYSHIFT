"""Turn what the user typed into sky coordinates.

Accepts decimal degrees, sexagesimal (08h55m10.8s -7d14m42s, 08:55:10.8 -07:14:42) or an object
name. Names are looked up with CDS Sesame (SIMBAD/NED/VizieR). Stars with a known proper motion
are moved to where they are today, so fast movers like Barnard's Star stay centred.
"""
from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from functools import lru_cache
from urllib.parse import quote

import astropy.units as u
from astropy.coordinates import SkyCoord

from .spherex import SESSION

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
            r = SESSION.get(base + "?" + quote(text.strip()), timeout=15)
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
