
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
GAIA_QUERY_RADIUS_DEG = 0.04


def safe_float(value):
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


# Gaia DR3 AB magnitude zero points.
GAIA_AB_ZERO_POINTS = {
    "G": 25.8010,
    "BP": 25.3540,
    "RP": 25.1040,
}


def gaia_flux_to_mjy(flux_e_s, band):
    """
    Convert Gaia DR3 mean flux (electrons/second) into
    an AB-equivalent flux density in mJy.
    """

    if flux_e_s is None or flux_e_s <= 0:
        return None

    ab_magnitude = (
        GAIA_AB_ZERO_POINTS[band]
        - 2.5 * math.log10(flux_e_s)
    )

    return 3631.0 * (10 ** (-0.4 * ab_magnitude)) * 1000.0



def observation_year(observation_time):
    if observation_time.tzinfo is None:
        observation_time = observation_time.replace(
            tzinfo=timezone.utc
        )

    return Time(observation_time).jyear


def propagate_position(source, target_year):

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

    first = SkyCoord(ra=ra1 * u.deg, dec=dec1 * u.deg)
    second = SkyCoord(ra=ra2 * u.deg, dec=dec2 * u.deg)

    return first.separation(second).arcsecond


async def query_gaia(ra, dec):

    adql = f"""
        SELECT
            source_id,
            ra,
            dec,
            ra_error,
            dec_error,
            parallax,
            parallax_error,
            pmra,
            pmdec,
            pmra_error,
            pmdec_error,
            phot_g_mean_mag,
            bp_rp,
            teff_gspphot,
            ruwe,
            radial_velocity,
            phot_g_mean_flux,
            phot_g_mean_flux_error,
            phot_bp_mean_flux,
            phot_bp_mean_flux_error,
            phot_rp_mean_flux,
            phot_rp_mean_flux_error,
            phot_bp_mean_mag,
            phot_rp_mean_mag
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

    # ESA first, then a full mirror (AIP Potsdam): some networks can't reach ESA at all,
    # so connecting gives up after 5 seconds instead of hanging for a minute and a half.
    from .sky_catalogs import GAIA_MIRRORS, _votable_rows

    for url, _name in GAIA_MIRRORS:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(90, connect=5)) as client:

                response = await client.post(
                    url,
                    data={
                        "REQUEST": "doQuery",
                        "LANG": "ADQL",
                        "FORMAT": "csv",
                        "QUERY": adql
                    },
                )

                response.raise_for_status()
                text = response.text
                if text.lstrip().startswith("<"):          # the mirror answers in VOTable
                    return _votable_rows(text)

                return list(
                    csv.DictReader(io.StringIO(text))
                )

        except (httpx.HTTPError, OSError, ValueError) as error:
            print("Gaia query failed at", url, ":", error)
    return None


def calculate_distance(source):

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
            "temperature_k": source["teff"],

            "bp_magnitude": source["bp_mag"],
            "rp_magnitude": source["rp_mag"],

            "g_flux_mjy": gaia_flux_to_mjy(source["g_flux"], "G"),
            "g_flux_error_mjy": (
                gaia_flux_to_mjy(source["g_flux_error"], "G")
                if source["g_flux_error"] is not None
                else None
            ),

            "bp_flux_mjy": gaia_flux_to_mjy(source["bp_flux"], "BP"),
            "bp_flux_error_mjy": (
                gaia_flux_to_mjy(source["bp_flux_error"], "BP")
                if source["bp_flux_error"] is not None
                else None
            ),

            "rp_flux_mjy": gaia_flux_to_mjy(source["rp_flux"], "RP"),
            "rp_flux_error_mjy": (
                gaia_flux_to_mjy(source["rp_flux_error"], "RP")
                if source["rp_flux_error"] is not None
                else None
            ),
        },


        "astrometry": {
            "parallax_mas": source["parallax"],
            "parallax_error_mas": source["parallax_error"],
            "ruwe": source["ruwe"],
            "radial_velocity_km_s": source["radial_velocity"]
        },

        "astrometric_uncertainties": {
            "ra_error_mas": source["ra_error"],
            "dec_error_mas": source["dec_error"],
            "pmra_error_mas_yr": source["pmra_error"],
            "pmdec_error_mas_yr": source["pmdec_error"],
            "parallax_error_mas": source["parallax_error"]
        },

        "distance": calculate_distance(source)
    }


async def gaia_match(
    ra,
    dec,
    observation_time,
    search_radius_arcsec=6.0
):

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
            "message": (
                "No Gaia sources were returned in the wider search region."
            ),
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
            "ra_error": safe_float(row.get("ra_error")),
            "dec_error": safe_float(row.get("dec_error")),
            "parallax": safe_float(row.get("parallax")),
            "parallax_error": safe_float(row.get("parallax_error")),
            "pmra": safe_float(row.get("pmra")),
            "pmdec": safe_float(row.get("pmdec")),
            "pmra_error": safe_float(row.get("pmra_error")),
            "pmdec_error": safe_float(row.get("pmdec_error")),
            "g_mag": safe_float(row.get("phot_g_mean_mag")),
            "bp_rp": safe_float(row.get("bp_rp")),
            "teff": safe_float(row.get("teff_gspphot")),
            "ruwe": safe_float(row.get("ruwe")),
            "radial_velocity": safe_float(row.get("radial_velocity")),
            "g_flux": safe_float(row.get("phot_g_mean_flux")),
            "g_flux_error": safe_float(row.get("phot_g_mean_flux_error")),
            "bp_flux": safe_float(row.get("phot_bp_mean_flux")),
            "bp_flux_error": safe_float(row.get("phot_bp_mean_flux_error")),
            "rp_flux": safe_float(row.get("phot_rp_mean_flux")),
            "rp_flux_error": safe_float(row.get("phot_rp_mean_flux_error")),
            "bp_mag": safe_float(row.get("phot_bp_mean_mag")),
            "rp_mag": safe_float(row.get("phot_rp_mean_mag"))

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
            "message": (
                "Gaia returned rows, but no valid source positions "
                "could be evaluated."
            ),
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
        message = (
            "A Gaia source was found within the matching radius."
        )

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
        message = (
            "The nearest Gaia source is outside the matching radius."
        )

    return {
        "status": status,
        "match_quality": match_quality,
        "matching_radius_arcsec": search_radius_arcsec,
        "nearest_source": nearest_result,
        "message": message
    }
