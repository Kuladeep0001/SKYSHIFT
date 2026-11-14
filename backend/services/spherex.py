"""SPHEREx data access through NASA/IPAC IRSA.

- releases(): discovers every SPHEREx data release IRSA has (dr1, qr3, ...),
  so new releases show up in the app automatically.
- search(): lists every SPHEREx exposure that covers a sky position.
- fetch_cutout(): downloads a small cutout of one exposure (cached on disk).
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import time
import warnings
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests
from astropy.io import fits

warnings.filterwarnings("ignore", module="astropy")  # SPHEREx headers trigger harmless SIP notices

IRSA_TAP = "https://irsa.ipac.caltech.edu/TAP/sync"
IRSA_SIA = "https://irsa.ipac.caltech.edu/SIA"
ROOT = Path(__file__).resolve().parents[2]  # project root
CACHE = Path(os.environ.get("SKYSHIFT_CACHE", ROOT / "data" / "cache"))
CUTS = CACHE / "cutouts"
CUTS.mkdir(parents=True, exist_ok=True)

SESSION = requests.Session()
SESSION.headers["User-Agent"] = "SkyShift/0.1 (NASA Space Apps SPHEREx viewer)"

# Used only if IRSA can't be reached when the app starts.
FALLBACK_RELEASES = ["spherex_dr1", "spherex_qr3"]
REL_RE = re.compile(r"spherex_(dr|qr)(\d*)$")  # per-exposure collections only (not _cube/_deep/_cal)
_REL_FILE = CACHE / "releases.json"
_rel_mem: dict = {"t": 0.0, "data": None}

KEEP_HDUS = ("IMAGE", "FLAGS", "VARIANCE", "ZODI", "WCS-WAVE")  # drop the big PSF table
SIZE_TIERS = [0.08, 0.15, 0.25, 0.4, 0.6]  # cutout sizes in degrees (snapped so the cache is reused)


def tap(query: str, timeout: int = 120) -> list[dict]:
    r = SESSION.get(IRSA_TAP, params={"LANG": "ADQL", "FORMAT": "csv", "QUERY": query}, timeout=timeout)
    r.raise_for_status()
    return list(csv.DictReader(io.StringIO(r.text)))


def _rank(name: str):
    kind, num = REL_RE.match(name).groups()
    return (kind == "dr", int(num or 0))


# The SPHEREx deep field at the north ecliptic pole is observed constantly, so every release covers it.
PROBE_RA, PROBE_DEC = 270.0, 66.56
CANDIDATES = [f"spherex_dr{i}" for i in range(1, 7)] + [f"spherex_qr{i}" for i in range(1, 13)] + ["spherex_qr"]


def sia(collection: str, ra: float, dec: float, radius: float = 0.0001, maxrec: int | None = None,
        timeout: int = 90) -> list[dict]:
    """IRSA Simple Image Access query (much faster than a general TAP query)."""
    params = {"COLLECTION": collection, "POS": f"circle {ra:.6f} {dec:.6f} {radius}", "RESPONSEFORMAT": "CSV"}
    if maxrec:
        params["MAXREC"] = str(maxrec)
    r = SESSION.get(IRSA_SIA, params=params, timeout=timeout)
    r.raise_for_status()
    return list(csv.DictReader(io.StringIO(r.text)))


def _exists(name: str) -> bool:
    try:
        return len(sia(name, PROBE_RA, PROBE_DEC, maxrec=1, timeout=45)) > 0
    except Exception:
        return False


def releases(force: bool = False) -> dict:
    """All SPHEREx releases at IRSA, newest first, plus the default 'best' combo.

    We probe likely release names (dr1..dr6, qr1..qr12), so when NASA publishes 'spherex_dr2'
    it appears in the app with no code change.
    """
    now = time.time()
    if not force and _rel_mem["data"] and now - _rel_mem["t"] < 6 * 3600:
        return _rel_mem["data"]
    if not force and _rel_mem["data"] is None and _REL_FILE.exists():
        data = json.loads(_REL_FILE.read_text())
        if now - data.get("checked", 0) < 6 * 3600:
            _rel_mem.update(t=now, data=data)
            return data
    with ThreadPoolExecutor(max_workers=len(CANDIDATES)) as ex:
        found = [n for n, ok in zip(CANDIDATES, ex.map(_exists, CANDIDATES)) if ok]
    if not found:  # IRSA unreachable: use what we knew last time
        if _REL_FILE.exists():
            return json.loads(_REL_FILE.read_text())
        found = FALLBACK_RELEASES
    names = sorted(found, key=_rank, reverse=True)
    drs = [n for n in names if "_dr" in n]
    qrs = [n for n in names if "_qr" in n]
    data = {
        "releases": [{"id": n} for n in names],
        # Best = newest full data release + newest quick release (which has the most recent weeks)
        "best": drs[:1] + qrs[:1],
        "checked": now,
    }
    _rel_mem.update(t=now, data=data)
    try:
        _REL_FILE.write_text(json.dumps(data))
    except OSError:
        pass
    return data


def search(ra: float, dec: float, collections: list[str] | None = None) -> list[dict]:
    """Every SPHEREx exposure covering (ra, dec). One entry per exposure per detector."""
    rel = releases()
    valid = {r["id"] for r in rel["releases"]}
    cols = [c for c in (collections or []) if c in valid] or rel["best"]
    with ThreadPoolExecutor(max_workers=len(cols)) as ex:
        results = list(ex.map(lambda c: sia(c, ra, dec), cols))
    rows = [r for res in results for r in res]
    # Full data releases (dr) win over quick releases (qr) when both have the same exposure.
    prio = {c: (0 if "_dr" in c else 1, -_rank(c)[1]) for c in cols}
    best: dict[tuple, dict] = {}
    for r in rows:
        try:
            det = int(r["energy_bandpassname"].strip()[-1])
            item = {
                "obs_id": r["obs_id"],
                "det": det,
                "mjd": float(r["t_min"]),
                "em_min": float(r["em_min"]) * 1e6,  # metres -> microns
                "em_max": float(r["em_max"]) * 1e6,
                "url": r["access_url"],
                "release": r["obs_collection"],
            }
        except (ValueError, IndexError, KeyError):
            continue
        if item["release"] not in prio:
            continue
        key = (item["obs_id"], det)
        if key not in best or prio[item["release"]] < prio[best[key]["release"]]:
            best[key] = item
    return sorted(best.values(), key=lambda x: (x["mjd"], x["det"]))


def cutout_size(fov_arcmin: float) -> float:
    need = fov_arcmin / 60 * 1.45 + 0.01  # diagonal of the view + margin, since frames are rotated
    return next((s for s in SIZE_TIERS if s >= need), SIZE_TIERS[-1])


def fetch_cutout(url: str, ra: float, dec: float, size: float) -> Path:
    """Download (or reuse) a cutout centred on (ra, dec). Returns the cached FITS path."""
    key = hashlib.sha1(f"{url}|{ra:.4f}|{dec:.4f}|{size}".encode()).hexdigest()[:24]
    path = CUTS / f"{key}.fits"
    if path.exists():
        return path
    last: Exception | None = None
    for attempt in range(3):
        try:
            r = SESSION.get(url, params={"center": f"{ra:.6f},{dec:.6f}", "size": f"{size}"}, timeout=180)
            r.raise_for_status()
            if len(r.content) < 2880:
                raise IOError(f"IRSA returned a tiny response: {r.content[:80]!r}")
            with fits.open(io.BytesIO(r.content)) as h:
                out = fits.HDUList(
                    [fits.PrimaryHDU(header=h[0].header)] + [h[n].copy() for n in KEEP_HDUS if n in h]
                )
                tmp = path.with_suffix(f".{os.getpid()}.tmp")
                out.writeto(tmp, overwrite=True)
                os.replace(tmp, path)
            return path
        except Exception as e:  # network hiccups are common; retry a couple of times
            last = e
            time.sleep(1 + 2 * attempt)
    raise last  # type: ignore[misc]
