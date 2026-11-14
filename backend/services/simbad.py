
import csv
import io
import math

import httpx
import astropy.units as u

from astropy.coordinates import SkyCoord
from astropy.time import Time


SIMBAD_SERVERS = [
    "https://simbad.cds.unistra.fr/simbad/sim-tap/sync",
    "https://simbad.harvard.edu/simbad/sim-tap/sync"
]

SIMBAD_EPOCH = 2000.0

# Search radius for retrieving possible SIMBAD objects.
# Final matching is performed separately.
SEARCH_RADIUS_DEG = 5.0 / 60.0


OBJECT_TYPES = {
    "*": "Star",
    "PM*": "High proper-motion star",
    "BD*": "Brown dwarf",
    "BD?": "Brown dwarf candidate",
    "LM*": "Low-mass star",
    "V*": "Variable star",
    "TT*": "T Tauri star",
    "Y*O": "Young stellar object",
    "**": "Double or multiple star",
    "WD*": "White dwarf",
    "G": "Galaxy",
    "QSO": "Quasar",
    "AGN": "Active galactic nucleus",
    "SN*": "Supernova",
    "PN": "Planetary nebula",
    "HII": "HII region",
    "IR": "Infrared source",
    "Cl*": "Star cluster"
}


def safe_float(value):
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def angular_separation(ra1, dec1, ra2, dec2):
    first = SkyCoord(ra=ra1 * u.deg, dec=dec1 * u.deg)
    second = SkyCoord(ra=ra2 * u.deg, dec=dec2 * u.deg)

    return first.separation(second).arcsecond


def propagate_simbad_position(source, target_year):
    """
    SIMBAD coordinates are treated as J2000 for this lookup.

    Proper motions are in mas/year. SIMBAD pmra is mu_alpha*cos(dec).
    """

    ra = source["ra"]
    dec = source["dec"]

    pmra = source["pmra"]
    pmdec = source["pmdec"]

    if pmra is None or pmdec is None:
        return ra, dec, False

    coordinate = SkyCoord(
        ra=ra * u.deg,
        dec=dec * u.deg,
        pm_ra_cosdec=pmra * u.mas / u.yr,
        pm_dec=pmdec * u.mas / u.yr,
        obstime=Time(SIMBAD_EPOCH, format="jyear")
    )

    moved = coordinate.apply_space_motion(
        new_obstime=Time(target_year, format="jyear")
    )

    return moved.ra.deg, moved.dec.deg, True


async def tap_query(client, server, adql):
    response = await client.post(
        server,
        data={
            "REQUEST": "doQuery",
            "LANG": "ADQL",
            "FORMAT": "csv",
            "QUERY": adql
        },
        timeout=45
    )

    response.raise_for_status()

    return list(
        csv.DictReader(io.StringIO(response.text))
    )


async def query_simbad_rows(client, adql):
    """
    Try SIMBAD Strasbourg first, then the Harvard mirror.
    """

    last_error = None

    for server in SIMBAD_SERVERS:
        try:
            rows = await tap_query(client, server, adql)
            return rows, server

        except httpx.HTTPError as error:
            last_error = error

    raise last_error or RuntimeError("SIMBAD servers unavailable")


async def get_alternative_names(client, server, oid):
    """
    Retrieve alternative identifiers for a SIMBAD object.
    """

    try:
        rows = await tap_query(
            client,
            server,
            f"""
                SELECT id
                FROM ident
                WHERE oidref = {int(oid)}
            """
        )

        return [
            row["id"].strip()
            for row in rows
            if row.get("id")
        ]

    except (httpx.HTTPError, ValueError, TypeError):
        return []


async def simbad_match(
    ra,
    dec,
    observation_time,
    search_radius_arcsec=6.0
):
    """
    Find the closest SIMBAD object to a candidate.

    Checks both:
    - Position propagated from J2000 to observation epoch.
    - Original SIMBAD catalogue position.

    Returns the nearest valid result.
    """

    if observation_time.tzinfo is None:
        from datetime import timezone
        observation_time = observation_time.replace(
            tzinfo=timezone.utc
        )

    target_year = Time(observation_time).jyear

    adql = f"""
        SELECT TOP 300
            b.oid,
            b.main_id,
            b.ra,
            b.dec,
            b.otype,
            b.sp_type,
            b.pmra,
            b.pmdec,
            b.plx_value,
            d.description,
            f."V",
            f."J",
            f."H",
            f."K"
        FROM basic AS b
        LEFT JOIN otypedef AS d
            ON d.otype = b.otype
        LEFT JOIN allfluxes AS f
            ON f.oidref = b.oid
        WHERE 1 = CONTAINS(
            POINT('ICRS', b.ra, b.dec),
            CIRCLE(
                'ICRS',
                {ra},
                {dec},
                {SEARCH_RADIUS_DEG}
            )
        )
    """

    try:
        async with httpx.AsyncClient() as client:
            rows, server = await query_simbad_rows(
                client,
                adql
            )

    except httpx.HTTPError as error:
        return {
            "status": "inconclusive",
            "message": f"SIMBAD query failed: {str(error)}",
            "nearest_source": None
        }

    if not rows:
        return {
            "status": "no_match",
            "message": "No SIMBAD objects found in the search region.",
            "nearest_source": None
        }

    best = None
    best_separation = float("inf")
    best_match_type = None

    for row in rows:

        source_ra = safe_float(row.get("ra"))
        source_dec = safe_float(row.get("dec"))

        if source_ra is None or source_dec is None:
            continue

        source = {
            "ra": source_ra,
            "dec": source_dec,
            "pmra": safe_float(row.get("pmra")),
            "pmdec": safe_float(row.get("pmdec"))
        }

        try:
            moved_ra, moved_dec, propagated = (
                propagate_simbad_position(
                    source,
                    target_year
                )
            )

            propagated_separation = angular_separation(
                ra, dec, moved_ra, moved_dec
            )

            original_separation = angular_separation(
                ra, dec, source_ra, source_dec
            )

        except (ValueError, TypeError):
            continue

        # A catalogue coordinate may itself have been supplied
        # by the user, so consider both positions.
        if not propagated:
            separation = original_separation
            match_type = "catalogue_position_no_proper_motion"

        elif original_separation < propagated_separation:
            separation = original_separation
            match_type = "original_catalogue_position"

        else:
            separation = propagated_separation
            match_type = "propagated_position"

        if separation < best_separation:
            best_separation = separation
            best = row
            best["propagated_ra"] = moved_ra
            best["propagated_dec"] = moved_dec
            best["proper_motion_applied"] = propagated
            best_match_type = match_type

    if best is None:
        return {
            "status": "inconclusive",
            "message": "SIMBAD returned objects but no valid coordinates.",
            "nearest_source": None
        }

    oid = best.get("oid")

    async with httpx.AsyncClient() as client:
        names = await get_alternative_names(
            client,
            server,
            oid
        )

    common_name = next(
        (
            name[5:].strip()
            for name in names
            if name.startswith("NAME ")
        ),
        None
    )

    object_code = (best.get("otype") or "").strip()

    magnitudes = {}

    for band in ["V", "J", "H", "K"]:
        magnitude = safe_float(best.get(band))

        if magnitude is not None:
            magnitudes[band] = magnitude

    source = {
        "oid": oid,
        "main_id": (best.get("main_id") or "").strip(),
        "name": common_name or (best.get("main_id") or "").strip(),

        "alternative_names": names[:15],

        "object_type_code": object_code,
        "object_type": (
            OBJECT_TYPES.get(object_code)
            or (best.get("description") or "").strip()
            or object_code
            or None
        ),

        "spectral_type": (
            (best.get("sp_type") or "").strip() or None
        ),

        "position": {
            "ra": safe_float(best.get("ra")),
            "dec": safe_float(best.get("dec")),
            "reference_epoch": SIMBAD_EPOCH
        },

        "propagated_position": {
            "ra": best["propagated_ra"],
            "dec": best["propagated_dec"],
            "observation_epoch": round(target_year, 5),
            "proper_motion_applied": best["proper_motion_applied"]
        },

        "proper_motion": {
            "pmra_mas_yr": safe_float(best.get("pmra")),
            "pmdec_mas_yr": safe_float(best.get("pmdec"))
        },

        "parallax_mas": safe_float(best.get("plx_value")),

        "magnitudes": magnitudes,

        "separation_arcsec": round(best_separation, 3),
        "matched_position": best_match_type,

        "url": (
            "https://simbad.cds.unistra.fr/simbad/sim-id?Ident="
            + (best.get("main_id") or "").replace(" ", "+")
        ),

        "server": server
    }

    if best_separation <= search_radius_arcsec:
        return {
            "status": "match_found",
            "matching_radius_arcsec": search_radius_arcsec,
            "nearest_source": source,
            "message": "A SIMBAD object was found within the matching radius."
        }

    return {
        "status": "no_match",
        "matching_radius_arcsec": search_radius_arcsec,
        "nearest_source": source,
        "message": "The nearest SIMBAD object is outside the matching radius."
    }
