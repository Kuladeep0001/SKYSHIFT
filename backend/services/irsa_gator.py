"""Fast IRSA catalogue cone search (Gator), used before the slower IRSA TAP service.

IRSA's TAP service can take a minute or more per query when it is busy, while the Gator cone search
on the same tables usually answers in 1-3 seconds. Rows are returned as {column: string} dicts, the
same shape as csv.DictReader gives for a TAP CSV response, so callers can use either source.
"""
from __future__ import annotations

import httpx
from astropy.io import ascii as astro_ascii

GATOR = "https://irsa.ipac.caltech.edu/cgi-bin/Gator/nph-query"


async def gator_rows(catalog: str, ra: float, dec: float, radius_arcsec: float, columns: list[str],
                     timeout: float = 30.0) -> list[dict] | None:
    """Cone search; returns rows, [] when nothing is there, or None if Gator failed (caller falls back)."""
    params = {
        "catalog": catalog,
        "spatial": "cone",
        "objstr": f"{ra:.8f} {dec:+.8f}",
        "radius": f"{radius_arcsec:.2f}",
        "radunits": "arcsec",
        "outfmt": "1",                      # IPAC table (typed, fixed width)
        "selcols": ",".join(c.strip() for c in columns),
    }
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.get(GATOR, params=params)
            r.raise_for_status()
    except httpx.HTTPError as error:
        print(f"Gator {catalog} failed:", repr(error))
        return None
    text = r.text
    if "|" not in text:                     # no table header: either an error message or no rows
        return [] if "No rows" in text or "no rows" in text else None
    try:
        table = astro_ascii.read(text, format="ipac", guess=False)
    except Exception as error:              # unexpected format: let the caller use TAP instead
        print(f"Gator {catalog} parse failed:", repr(error))
        return None
    rows = []
    for rec in table:
        row = {}
        for name in table.colnames:
            v = rec[name]
            row[name] = "" if getattr(v, "mask", False) is True or str(v) in ("--", "null") else str(v)
        rows.append(row)
    return rows
