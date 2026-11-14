"""Known asteroids and comets in a field at a given time (IMCCE SkyBoT)."""
from __future__ import annotations

import time
from functools import lru_cache

from .spherex import SESSION

SKYBOT = "https://ssp.imcce.fr/webservices/skybot/api/conesearch.php"


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
