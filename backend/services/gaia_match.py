
import csv
import io
import math
from datetime import timezone

import httpx
import astropy.units as u
from astropy.coordinates import SkyCoord
from astropy.time import Time


GAIA_TAP = "https://gea.esac.esa.int/tap-server/tap/sync"

GAIA_EPOCH = 2016.0

# Search region: 0.04 degrees = 2.4 arcminutes.
# This is deliberately wider than the final matching radius.
GAIA_QUERY_RADIUS_DEG = 0.04


def safe_float(value):
    """Convert a catalogue value to a finite float."""
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def observation_year(observation_time):
    """Convert an ISO timestamp to decimal Julian year."""
    if observation_time.tzinfo is None:
        observation_time = observation_time.replace(
            tzinfo=timezone.utc
        )

    return Time(observation_time).jyear


def propagate_position(source, target_year):
    """Propagate Gaia DR3 coordinates from J2016.0 to target epoch."""

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
        obstime=Time(GAIA_EPOCH, format="jyear")
    )

    moved = coordinate.apply_space_motion(
        new_obstime=Time(target_year, format="jyear")
    )

    return moved.ra.deg, moved.dec.deg, True


def angular_separation(ra1, dec1, ra2, dec2):
    """Angular separation in arcseconds."""
    first = SkyCoord(ra=ra1 * u.deg, dec=dec1 * u.deg)
    second = SkyCoord(ra=ra2 * u.deg, dec=dec2 * u.deg)

    return first.separation(second).arcsecond


async def query_gaia(ra, dec):
    """Retrieve Gaia DR3 sources in the wider search region."""

    adql = f"""
        SELECT
            source_id,
            ra,
            dec,
            parallax,
            parallax_error,
            pmra,
            pmdec,
            phot_g_mean_mag,
            bp_rp,
            teff_gspphot,
            ruwe,
            radial_velocity
        FROM gaiadr3.gaia_source
        WHERE 1 = CONTAINS(
            POINT('ICRS', ra, dec),
            CIRCLE(
                'ICRS',
                {ra},
                {dec},
                {GAIA_QUERY_RADIUS_DEG}
            )
        )
    """

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                GAIA_TAP,
                data={
                    "REQUEST": "doQuery",
                    "LANG": "ADQL",
                    "FORMAT": "csv",
                    "QUERY": adql
                },
                timeout=90
            )

            response.raise_for_status()

            return list(
                csv.DictReader(io.StringIO(response.text))
            )

    except httpx.HTTPError as error:
        print("Gaia query failed:", error)
        return None


def calculate_distance(source):
    """
    Estimate distance from Gaia parallax only when the parallax
    is positive and has signal-to-noise ratio greater than five.
    """

    parallax = source["parallax"]
    error = source["parallax_error"]

    if (
        parallax is None
        or error is None
        or parallax <= 0
        or error <= 0
        or parallax / error <= 5
    ):
        return None

    distance_pc = 1000.0 / parallax

    return {
        "parsecs": round(distance_pc, 3),
        "light_years": round(distance_pc * 3.26156, 2),
        "method": "inverse_parallax",
        "parallax_mas": parallax,
        "parallax_error_mas": error
    }


def format_source(source, separation, target_year, propagated):
    """Format the nearest Gaia source and its properties."""

    pmra = source["pmra"]
    pmdec = source["pmdec"]

    proper_motion = None

    if pmra is not None and pmdec is not None:
        proper_motion = math.hypot(pmra, pmdec)

    return {
        "source_id": source["source_id"],
        "separation_arcsec": round(separation, 3),

        "catalogue_position": {
            "ra": source["ra"],
            "dec": source["dec"],
            "reference_epoch": GAIA_EPOCH
        },

        "propagated_position": {
            "ra": source["propagated_ra"],
            "dec": source["propagated_dec"],
            "observation_epoch": round(target_year, 5),
            "proper_motion_applied": propagated
        },

        "proper_motion": {
            "pmra_mas_yr": pmra,
            "pmdec_mas_yr": pmdec,
            "total_mas_yr": (
                round(proper_motion, 3)
                if proper_motion is not None else None
            )
        },

        "photometry": {
            "g_magnitude": source["g_mag"],
            "bp_rp": source["bp_rp"],
            "temperature_k": source["teff"]
        },

        "astrometry": {
            "parallax_mas": source["parallax"],
            "parallax_error_mas": source["parallax_error"],
            "ruwe": source["ruwe"],
            "radial_velocity_km_s": source["radial_velocity"]
        },

        "distance": calculate_distance(source)
    }


async def gaia_match(
    ra,
    dec,
    observation_time,
    search_radius_arcsec=6.0
):
    """
    Find the nearest Gaia DR3 source.

    A source is a match only if its propagated position is inside
    search_radius_arcsec. The nearest source is returned regardless
    of whether it qualifies as a match.
    """

    year = observation_year(observation_time)

    rows = await query_gaia(ra, dec)

    if rows is None:
        return {
            "status": "inconclusive",
            "message": "Gaia DR3 could not be reached.",
            "nearest_source": None
        }

    if not rows:
        return {
            "status": "no_match",
            "message": "No Gaia sources were returned in the wider search region.",
            "nearest_source": None
        }

    nearest_source = None
    nearest_separation = float("inf")
    nearest_propagated = False

    for row in rows:

        source = {
            "source_id": row.get("source_id"),
            "ra": safe_float(row.get("ra")),
            "dec": safe_float(row.get("dec")),
            "parallax": safe_float(row.get("parallax")),
            "parallax_error": safe_float(row.get("parallax_error")),
            "pmra": safe_float(row.get("pmra")),
            "pmdec": safe_float(row.get("pmdec")),
            "g_mag": safe_float(row.get("phot_g_mean_mag")),
            "bp_rp": safe_float(row.get("bp_rp")),
            "teff": safe_float(row.get("teff_gspphot")),
            "ruwe": safe_float(row.get("ruwe")),
            "radial_velocity": safe_float(row.get("radial_velocity"))
        }

        if source["ra"] is None or source["dec"] is None:
            continue

        try:
            moved_ra, moved_dec, propagated = propagate_position(
                source,
                year
            )

            separation = angular_separation(
                ra,
                dec,
                moved_ra,
                moved_dec
            )

        except (ValueError, TypeError, u.UnitConversionError):
            continue

        if separation < nearest_separation:
            nearest_separation = separation
            nearest_source = source.copy()

            nearest_source["propagated_ra"] = moved_ra
            nearest_source["propagated_dec"] = moved_dec

            nearest_propagated = propagated

    if nearest_source is None:
        return {
            "status": "inconclusive",
            "message": "Gaia returned rows, but no valid source positions could be evaluated.",
            "nearest_source": None
        }

    nearest_result = format_source(
        nearest_source,
        nearest_separation,
        year,
        nearest_propagated
    )

    
    borderline_margin_arcsec = 1.0

    if nearest_separation <= search_radius_arcsec:
        status = "match_found"
        match_quality = "within_radius"
        message = "A Gaia source was found within the matching radius."

    elif nearest_separation <= (
        search_radius_arcsec + borderline_margin_arcsec
    ):
        status = "no_match"
        match_quality = "borderline"
        message = (
            "The nearest Gaia source is just outside the matching radius. "
            "Manual review is recommended."
        )

    else:
        status = "no_match"
        match_quality = "outside_radius"
        message = "The nearest Gaia source is outside the matching radius."

    return {
        "status": status,
        "match_quality": match_quality,
        "matching_radius_arcsec": search_radius_arcsec,
        "nearest_source": nearest_result,
        "message": message
    }
