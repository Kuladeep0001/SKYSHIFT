
import csv
import io
import math

import httpx
from astropy.time import Time

from backend.services.irsa_gator import gator_rows


IRSA_TAP = "https://irsa.ipac.caltech.edu/TAP/sync"

GATOR_COLUMNS = [
    "designation", "ra", "dec", "jdate", "err_maj", "err_min",
    "j_m", "j_msigcom", "h_m", "h_msigcom", "k_m", "k_msigcom",
    "ph_qual", "rd_flg", "bl_flg", "cc_flg",
]

# 2MASS photometric zero points in Jy
ZERO_POINTS_JY = {
    "J": 1594.0,
    "H": 1024.0,
    "Ks": 666.7,
}

# Approximate mean epoch, used only for the initial search position.
# Individual sources are compared using their own jdate values.
TWOMASS_EPOCH = 2000.0


def safe_float(value):
    """Convert a value to float, returning None for invalid values."""
    try:
        number = float(value)

        if not math.isfinite(number):
            return None

        return number

    except (TypeError, ValueError):
        return None


def julian_date_to_year(jdate):
    """Convert Julian Date into decimal Julian year."""
    jdate = safe_float(jdate)

    if jdate is None:
        return None

    return float(Time(jdate, format="jd").jyear)


def angular_separation(ra1, dec1, ra2, dec2):
    """Calculate angular separation between two sky positions in arcseconds."""

    ra1 = math.radians(ra1)
    dec1 = math.radians(dec1)
    ra2 = math.radians(ra2)
    dec2 = math.radians(dec2)

    cos_angle = (
        math.sin(dec1) * math.sin(dec2)
        + math.cos(dec1) * math.cos(dec2) * math.cos(ra1 - ra2)
    )

    cos_angle = max(-1.0, min(1.0, cos_angle))

    angle = math.acos(cos_angle)

    return math.degrees(angle) * 3600.0


def propagate_gaia_to_epoch(gaia_result, target_epoch):
    """
    Propagate a confirmed Gaia DR3 position to a specified epoch.

    Gaia DR3 positions are referenced to J2016.0.
    pmra is mu_alpha*cos(dec), and proper motions are in mas/year.

    This is a linear proper-motion propagation. It does not account
    for perspective acceleration or other higher-order effects.
    """

    if not gaia_result:
        return None

    if (
        gaia_result.get("status") != "match_found"
        or gaia_result.get("match_quality") != "within_radius"
    ):
        return None

    nearest = gaia_result.get("nearest_source") or {}
    position = nearest.get("catalogue_position") or {}
    proper_motion = nearest.get("proper_motion") or {}

    ra = safe_float(position.get("ra"))
    dec = safe_float(position.get("dec"))
    pmra = safe_float(proper_motion.get("pmra_mas_yr"))
    pmdec = safe_float(proper_motion.get("pmdec_mas_yr"))
    reference_epoch = safe_float(position.get("reference_epoch"))
    target_epoch = safe_float(target_epoch)

    if None in (ra, dec, pmra, pmdec, reference_epoch, target_epoch):
        return None

    cos_dec = math.cos(math.radians(dec))

    if abs(cos_dec) < 1e-8:
        return None

    years = target_epoch - reference_epoch

    propagated_ra = ra + (
        pmra * years / (3_600_000.0 * cos_dec)
    )

    propagated_dec = dec + (
        pmdec * years / 3_600_000.0
    )

    if not -90 <= propagated_dec <= 90:
        return None

    return propagated_ra % 360.0, propagated_dec


def magnitude_to_mjy(magnitude, band):
    """Convert a 2MASS magnitude into flux density in mJy."""

    if magnitude is None or magnitude <= -90:
        return None

    zero_point = ZERO_POINTS_JY[band]
    flux_jy = zero_point * (10 ** (-0.4 * magnitude))

    return flux_jy * 1000.0


async def query_2mass(ra, dec, radius_arcsec):
    """Query IRSA TAP; IRSA is sometimes slow, so a timeout or dropped connection is tried once more."""

    # Fast path: IRSA Gator cone search on the same table (TAP can take a minute when busy).
    rows = await gator_rows("fp_psc", ra, dec, radius_arcsec, GATOR_COLUMNS)

    if rows is not None:
        return rows

    for attempt in range(2):
        rows = await _query_2mass_once(ra, dec, radius_arcsec)

        if rows != "retry":
            return rows

    return None


async def _query_2mass_once(ra, dec, radius_arcsec):
    """Query the 2MASS Point Source Catalog through IRSA TAP."""

    radius_deg = radius_arcsec / 3600.0

    columns = """
        designation,
        ra,
        dec,
        jdate,
        err_maj,
        err_min,
        j_m,
        j_msigcom,
        h_m,
        h_msigcom,
        k_m,
        k_msigcom,
        ph_qual,
        rd_flg,
        bl_flg,
        cc_flg
    """

    query = f"""
        SELECT {columns}
        FROM fp_psc
        WHERE CONTAINS(
            POINT(ra, dec),
            CIRCLE({ra:.8f}, {dec:.8f}, {radius_deg:.8f})
        ) = 1
    """

    params = {
        "REQUEST": "doQuery",
        "LANG": "ADQL",
        "FORMAT": "csv",
        "QUERY": query,
    }

    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            response = await client.get(
                IRSA_TAP,
                params=params,
            )

            response.raise_for_status()

            return list(
                csv.DictReader(io.StringIO(response.text))
            )

    except httpx.HTTPStatusError as error:
        print("2MASS HTTP STATUS ERROR:", error.response.status_code)
        print("2MASS RESPONSE:", error.response.text[:2000])
        return None

    except httpx.TimeoutException as error:
        print("2MASS TIMEOUT ERROR:", repr(error))
        return "retry"

    except httpx.RequestError as error:
        print("2MASS CONNECTION ERROR:", repr(error))
        return "retry"

    except csv.Error as error:
        print("2MASS CSV ERROR:", repr(error))
        return None

def format_photometry(row):
    """Extract 2MASS magnitudes, uncertainties, flags and fluxes."""

    bands = {
        "J": ("j_m", "j_msigcom", 0),
        "H": ("h_m", "h_msigcom", 1),
        "Ks": ("k_m", "k_msigcom", 2),
    }

    photometry = {}

    quality = row.get("ph_qual") or "???"
    read_flags = row.get("rd_flg") or "???"

    for band, (mag_column, error_column, index) in bands.items():

        magnitude = safe_float(row.get(mag_column))
        uncertainty = safe_float(row.get(error_column))

        if magnitude is not None and magnitude <= -90:
            magnitude = None

        band_quality = (
            quality[index] if len(quality) > index else None
        )

        read_flag = (
            read_flags[index] if len(read_flags) > index else None
        )

        is_upper_limit = band_quality == "U"

        is_valid_measurement = (
            magnitude is not None
            and band_quality in ("A", "B", "C", "D", "E", "F")
            and read_flag in ("1", "2", "3", "4")
        )

        flux = (
            magnitude_to_mjy(magnitude, band)
            if is_valid_measurement
            else None
        )

        upper_limit_flux = (
            magnitude_to_mjy(magnitude, band)
            if is_upper_limit and magnitude is not None
            else None
        )

        photometry[band] = {
            "magnitude": magnitude,
            "uncertainty": uncertainty,
            "quality_flag": band_quality,
            "read_flag": read_flag,
            "is_detection": is_valid_measurement,
            "is_upper_limit": is_upper_limit,
            "flux_mjy": flux,
            "upper_limit_flux_mjy": upper_limit_flux,
        }

    return photometry


async def twomass_match(
    ra,
    dec,
    observation_time,
    search_radius_arcsec=6.0,
    gaia_result=None,
):
    """
    Find a 2MASS counterpart to a candidate.

    If a Gaia association is confirmed, Gaia proper motion is used
    to compare the candidate and each 2MASS source at the 2MASS
    source's observation epoch.

    Without a confirmed Gaia association, an epoch-consistent
    separation cannot be calculated. Such results are inconclusive.
    """

    candidate_epoch = float(Time(observation_time).jyear)

    # Use Gaia to estimate the candidate's position around J2000
    # for the initial 2MASS cone search, but only if the Gaia
    # association is confirmed.
    search_position_2000 = propagate_gaia_to_epoch(
        gaia_result,
        TWOMASS_EPOCH,
    )

    if search_position_2000 is not None:
        search_ra, search_dec = search_position_2000
        gaia_available = True
        position_basis = "confirmed_gaia_propagation"
        search_position_epoch = TWOMASS_EPOCH

    else:
        search_ra, search_dec = ra, dec
        gaia_available = False
        position_basis = "candidate_coordinates_unpropagated"
        search_position_epoch = candidate_epoch

    # This is the initial cone-search radius, not the final
    # counterpart matching threshold.
    query_radius = min(
        max(search_radius_arcsec + 1.0, 60.0),
        120.0,
    )

    rows = await query_2mass(
        search_ra,
        search_dec,
        query_radius,
    )

    if rows is None:
        return {
            "status": "inconclusive",
            "message": "The IRSA 2MASS service could not be reached.",
            "candidate_epoch_jyear": candidate_epoch,
            "position_basis": position_basis,
        }

    if not rows:
        if gaia_available:
            status = "no_match"
            message = (
                "No 2MASS source was found in the search region "
                "around the Gaia-propagated position."
            )
        else:
            status = "inconclusive"
            message = (
                "No 2MASS source was found, but without a confirmed "
                "Gaia proper motion the candidate position cannot "
                "be reliably compared with the older 2MASS epoch."
            )

        return {
            "status": status,
            "match_quality": "no_source_in_search_region",
            "matching_radius_arcsec": search_radius_arcsec,
            "candidate_epoch_jyear": candidate_epoch,
            "position_basis": position_basis,
            "epoch_correction_available": gaia_available,
            "search_position": {
                "ra": search_ra,
                "dec": search_dec,
                "epoch": search_position_epoch,
            },
            "nearest_source": None,
            "message": message,
        }

    # Calculate source separations. When Gaia is confirmed,
    # propagate its position to each 2MASS source's own epoch.
    valid_rows = []

    for row in rows:

        source_ra = safe_float(row.get("ra"))
        source_dec = safe_float(row.get("dec"))
        jdate = safe_float(row.get("jdate"))

        if source_ra is None or source_dec is None:
            continue

        source_epoch = julian_date_to_year(jdate)

        if gaia_available and source_epoch is not None:

            propagated_position = propagate_gaia_to_epoch(
                gaia_result,
                source_epoch,
            )

            if propagated_position is None:
                continue

            comparison_ra, comparison_dec = propagated_position

            separation = angular_separation(
                comparison_ra,
                comparison_dec,
                source_ra,
                source_dec,
            )

            epoch_corrected = True

        else:
            # This raw separation is diagnostic only. It compares
            # positions that may refer to different epochs.
            separation = angular_separation(
                ra,
                dec,
                source_ra,
                source_dec,
            )

            epoch_corrected = False

        row["_separation_arcsec"] = separation
        row["_source_epoch"] = source_epoch
        row["_epoch_corrected"] = epoch_corrected

        valid_rows.append(row)

    if not valid_rows:
        return {
            "status": "inconclusive",
            "message": "2MASS returned no sources with usable coordinates and epochs.",
            "candidate_epoch_jyear": candidate_epoch,
            "position_basis": position_basis,
        }

    # Select the nearest source using the available separation.
    nearest = min(
        valid_rows,
        key=lambda row: row["_separation_arcsec"],
    )

    separation = nearest["_separation_arcsec"]
    epoch_corrected = nearest["_epoch_corrected"]
    source_epoch = nearest["_source_epoch"]

    if not epoch_corrected:

        status = "inconclusive"
        match_quality = "epoch_correction_unavailable"
        message = (
            "A nearby 2MASS source was found, but its separation "
            "could not be reliably compared at a common epoch."
        )

    elif separation <= search_radius_arcsec:

        status = "match_found"
        match_quality = "within_radius"
        message = (
            "A 2MASS counterpart was found within the matching radius."
        )

    elif separation <= search_radius_arcsec + 1.0:

        status = "no_match"
        match_quality = "borderline"
        message = (
            "The nearest 2MASS source is just outside the matching radius."
        )

    else:

        status = "no_match"
        match_quality = "outside_radius"
        message = (
            "The nearest 2MASS source is outside the matching radius."
        )

    photometry = format_photometry(nearest)

    nearest_source = {
        "designation": nearest.get("designation"),
        "position": {
            "ra": safe_float(nearest.get("ra")),
            "dec": safe_float(nearest.get("dec")),
            "reference_epoch_jyear": source_epoch,
            "jdate": safe_float(nearest.get("jdate")),
        },
        # Only report a true common-epoch separation as separation_arcsec.
        "separation_arcsec": (
            round(separation, 4) if epoch_corrected else None
        ),
        "epoch_corrected_separation_arcsec": (
            round(separation, 4) if epoch_corrected else None
        ),
        "uncorrected_separation_arcsec": (
            round(separation, 4) if not epoch_corrected else None
        ),
        "epoch_correction_available": epoch_corrected,
        "photometry": photometry,
        "quality_flags": {
            "ph_qual": nearest.get("ph_qual"),
            "rd_flg": nearest.get("rd_flg"),
            "bl_flg": nearest.get("bl_flg"),
            "cc_flg": nearest.get("cc_flg"),
        },
        "position_error": {
            "major_axis_arcsec": safe_float(nearest.get("err_maj")),
            "minor_axis_arcsec": safe_float(nearest.get("err_min")),
        },
    }

    return {
        "status": status,
        "match_quality": match_quality,
        "matching_radius_arcsec": search_radius_arcsec,
        "candidate_epoch_jyear": candidate_epoch,
        "position_basis": position_basis,
        "epoch_correction_available": epoch_corrected,
        "search_position": {
            "ra": search_ra,
            "dec": search_dec,
            "epoch": search_position_epoch,
            "position_basis": position_basis,
        },
        "nearest_source": nearest_source,
        "message": message,
    }
