
import csv
import io
import math

import httpx
from astropy.time import Time


IRSA_TAP = "https://irsa.ipac.caltech.edu/TAP/sync"
ALLWISE_TABLE = "allwise_p3as_psd"

ZERO_POINTS_JY = {
    "W1": 309.540,
    "W2": 171.787,
}

# AllWISE motion-fit coordinates ra_pm/dec_pm are defined at MJD 55400.
ALLWISE_MOTION_EPOCH_MJD = 55400.0
ALLWISE_MOTION_EPOCH = float(
    Time(ALLWISE_MOTION_EPOCH_MJD, format="mjd").jyear
)


def safe_float(value):
    """Convert a value to float, returning None for invalid values."""
    try:
        number = float(value)

        if not math.isfinite(number):
            return None

        return number

    except (TypeError, ValueError):
        return None


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

    return math.degrees(math.acos(cos_angle)) * 3600.0


def propagate_gaia_to_epoch(gaia_result, target_epoch):
    """
    Propagate a confirmed Gaia DR3 position to a target Julian year.

    This is linear proper-motion propagation. It does not model
    perspective acceleration or parallax displacement.
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
    """Convert a WISE Vega magnitude into flux density in mJy."""

    if magnitude is None or magnitude <= -90:
        return None

    flux_jy = ZERO_POINTS_JY[band] * (10 ** (-0.4 * magnitude))

    return flux_jy * 1000.0



def interpret_contamination_flag(flag):
    """
    Interpret one AllWISE contamination flag.

    Lowercase: source is believed real, but its measurement may
    be contaminated.

    Uppercase: source may be a spurious artifact detection.
    """

    if flag is None:
        return {
            "flag": None,
            "assessment": "unknown",
            "artifact": None,
        }

    artifact_names = {
        "D": "diffraction_spike",
        "P": "persistence",
        "H": "halo",
        "O": "optical_ghost",
    }

    if flag == "0":
        return {
            "flag": flag,
            "assessment": "no_known_artifact",
            "artifact": None,
        }

    artifact = artifact_names.get(flag.upper())

    if artifact is None:
        return {
            "flag": flag,
            "assessment": "unknown",
            "artifact": None,
        }

    if flag.isupper():
        assessment = "possibly_spurious"
    else:
        assessment = "real_detection_potentially_contaminated"

    return {
        "flag": flag,
        "assessment": assessment,
        "artifact": artifact,
    }



def interpret_photometric_quality(flag, magnitude):
    """Interpret an individual AllWISE photometric quality flag."""

    if flag in ("A", "B", "C"):
        return {
            "is_detection": True,
            "is_upper_limit": False,
            "measurement_status": "detection",
        }

    if flag == "U":
        return {
            "is_detection": False,
            "is_upper_limit": True,
            "measurement_status": "upper_limit",
        }

    if flag == "Z":
        return {
            "is_detection": magnitude is not None,
            "is_upper_limit": False,
            "measurement_status": (
                "detection_without_measurable_uncertainty"
                if magnitude is not None
                else "flux_not_usable"
            ),
        }

    if flag == "X":
        return {
            "is_detection": False,
            "is_upper_limit": False,
            "measurement_status": "measurement_unavailable",
        }

    return {
        "is_detection": False,
        "is_upper_limit": False,
        "measurement_status": "unknown",
    }


def parse_pmcode(pmcode):
    """
    Decode the AllWISE five-character motion-fit code.

    Format: NQDDD
    N = original blend count
    Q = whether a blend swap occurred
    DDD = stationary/motion-position offset in units of 0.01 arcsec
    """

    if not pmcode or len(pmcode) != 5:
        return {
            "raw": pmcode,
            "valid_format": False,
        }

    blend_count = safe_float(pmcode[0])
    blend_swap_code = pmcode[1]
    offset_units = safe_float(pmcode[2:5])

    if (
        blend_count is None
        or blend_swap_code not in ("Y", "N")
        or offset_units is None
    ):
        return {
            "raw": pmcode,
            "valid_format": False,
        }

    return {
        "raw": pmcode,
        "valid_format": True,
        "original_blend_count": int(blend_count),
        "blend_swap_occurred": blend_swap_code == "Y",
        "stationary_motion_position_offset_arcsec": (
            offset_units * 0.01
        ),
    }


def format_photometry(row):
    """Extract W1/W2 photometry, uncertainties, flags and fluxes."""

    bands = {
        "W1": ("w1mpro", "w1sigmpro", "w1snr", 0),
        "W2": ("w2mpro", "w2sigmpro", "w2snr", 1),
    }

    quality = row.get("ph_qual") or "XXXX"
    contamination = row.get("cc_flags") or "????"
    variability = row.get("var_flg") or "????"

    photometry = {}

    for band, (mag_column, error_column, snr_column, index) in bands.items():

        magnitude = safe_float(row.get(mag_column))
        uncertainty = safe_float(row.get(error_column))
        snr = safe_float(row.get(snr_column))

        if magnitude is not None and magnitude <= -90:
            magnitude = None

        quality_flag = (
            quality[index] if len(quality) > index else None
        )

        contamination_flag = (
            contamination[index]
            if len(contamination) > index
            else None
        )

        variability_flag = (
            variability[index]
            if len(variability) > index
            else None
        )

        quality_info = interpret_photometric_quality(
            quality_flag,
            magnitude,
        )

        contamination_info = interpret_contamination_flag(
            contamination_flag,
        )

        is_detection = quality_info["is_detection"]
        is_upper_limit = quality_info["is_upper_limit"]

        flux_mjy = (
            magnitude_to_mjy(magnitude, band)
            if is_detection
            else None
        )

        flux_uncertainty_mjy = None

        if flux_mjy is not None and uncertainty is not None:
            flux_uncertainty_mjy = (
                flux_mjy * math.log(10.0) * 0.4 * uncertainty
            )

        upper_limit_flux_mjy = (
            magnitude_to_mjy(magnitude, band)
            if is_upper_limit and magnitude is not None
            else None
        )

        photometry[band] = {
            "magnitude_vega": magnitude,
            "magnitude_uncertainty": uncertainty,
            "signal_to_noise": snr,
            "quality_flag": quality_flag,
            "measurement_status": quality_info["measurement_status"],
            "is_detection": is_detection,
            "is_upper_limit": is_upper_limit,
            "flux_mjy": flux_mjy,
            "flux_uncertainty_mjy": flux_uncertainty_mjy,
            "upper_limit_flux_mjy": upper_limit_flux_mjy,
            "contamination_flag": contamination_info,
            "variability_flag": variability_flag,
        }

    return photometry


def format_motion_fit(row):
    """Extract and assess the available AllWISE motion-fit diagnostics."""

    ra_pm = safe_float(row.get("ra_pm"))
    dec_pm = safe_float(row.get("dec_pm"))

    pmra = safe_float(row.get("pmra"))
    pmdec = safe_float(row.get("pmdec"))

    sigpmra = safe_float(row.get("sigpmra"))
    sigpmdec = safe_float(row.get("sigpmdec"))

    sigra_pm = safe_float(row.get("sigra_pm"))
    sigdec_pm = safe_float(row.get("sigdec_pm"))

    motion_fit_available = (
        ra_pm is not None
        and dec_pm is not None
        and pmra is not None
        and pmdec is not None
    )

    pmcode_info = parse_pmcode(row.get("pmcode"))

    pmra_snr = (
        abs(pmra / sigpmra)
        if pmra is not None and sigpmra is not None and sigpmra > 0
        else None
    )

    pmdec_snr = (
        abs(pmdec / sigpmdec)
        if pmdec is not None and sigpmdec is not None and sigpmdec > 0
        else None
    )

    return {
        "motion_fit_available": motion_fit_available,
        "position_at_reference_epoch": {
            "ra": ra_pm,
            "dec": dec_pm,
            "reference_epoch_mjd": ALLWISE_MOTION_EPOCH_MJD,
            "reference_epoch_jyear": ALLWISE_MOTION_EPOCH,
            "ra_uncertainty_arcsec": sigra_pm,
            "dec_uncertainty_arcsec": sigdec_pm,
        },
        "apparent_motion": {
            "ra_mas_yr": pmra,
            "dec_mas_yr": pmdec,
            "ra_uncertainty_mas_yr": sigpmra,
            "dec_uncertainty_mas_yr": sigpmdec,
            "ra_component_snr": pmra_snr,
            "dec_component_snr": pmdec_snr,
            "interpretation": (
                "Apparent motion, not necessarily true proper motion. "
                "It may include parallax effects."
            ),
        },
        "fit_diagnostics": {
            "combined_reduced_chi_square": safe_float(
                row.get("rchi2_pm")
            ),
            "W1_reduced_chi_square": safe_float(
                row.get("w1rchi2_pm")
            ),
            "W2_reduced_chi_square": safe_float(
                row.get("w2rchi2_pm")
            ),
            "pmcode": pmcode_info,
            "number_of_blended_components": safe_float(row.get("nb")),
            "active_deblending_flag": safe_float(row.get("na")),
        },
    }


async def query_allwise(ra, dec, radius_arcsec):
    """Query the AllWISE Source Catalog through IRSA TAP."""

    radius_deg = radius_arcsec / 3600.0

    columns = """
        designation,
        source_id,
        ra,
        dec,
        sigra,
        sigdec,
        ra_pm,
        dec_pm,
        sigra_pm,
        sigdec_pm,
        pmra,
        sigpmra,
        pmdec,
        sigpmdec,
        rchi2_pm,
        w1rchi2_pm,
        w2rchi2_pm,
        pmcode,
        w1mpro,
        w1sigmpro,
        w1snr,
        w2mpro,
        w2sigmpro,
        w2snr,
        w1mjdmean,
        w2mjdmean,
        ph_qual,
        cc_flags,
        ext_flg,
        var_flg,
        nb,
        na
    """

    query = f"""
        SELECT {columns}
        FROM {ALLWISE_TABLE}
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
        async with httpx.AsyncClient(timeout=60.0) as client:

            response = await client.get(
                IRSA_TAP,
                params=params,
            )

            response.raise_for_status()

            return list(
                csv.DictReader(io.StringIO(response.text))
            )

    except httpx.HTTPStatusError as error:
        print("AllWISE HTTP STATUS ERROR:", error.response.status_code)
        print("AllWISE RESPONSE:", error.response.text[:2000])
        return None

    except httpx.TimeoutException as error:
        print("AllWISE TIMEOUT ERROR:", repr(error))
        return None

    except httpx.RequestError as error:
        print("AllWISE CONNECTION ERROR:", repr(error))
        return None

    except csv.Error as error:
        print("AllWISE CSV ERROR:", repr(error))
        return None


async def allwise_match(
    ra,
    dec,
    observation_time,
    search_radius_arcsec=6.0,
    gaia_result=None,
):
    """
    Find a possible AllWISE counterpart.

    A confirmed Gaia position is propagated to the AllWISE
    motion-fit reference epoch. AllWISE apparent motion itself
    is reported as a diagnostic and is not used as true proper motion.
    """

    candidate_epoch = float(Time(observation_time).jyear)

    # Use a confirmed Gaia association for the initial J2000 search.
    search_position_2000 = propagate_gaia_to_epoch(
        gaia_result,
        2000.0,
    )

    if search_position_2000 is not None:
        search_ra, search_dec = search_position_2000
        gaia_available = True
        position_basis = "confirmed_gaia_propagation"
    else:
        search_ra, search_dec = ra, dec
        gaia_available = False
        position_basis = "candidate_coordinates_unpropagated"

    query_radius = min(
        max(search_radius_arcsec + 1.0, 60.0),
        120.0,
    )

    rows = await query_allwise(
        search_ra,
        search_dec,
        query_radius,
    )

    if rows is None:
        return {
            "status": "inconclusive",
            "message": "The IRSA AllWISE service could not be reached.",
            "candidate_epoch_jyear": candidate_epoch,
            "position_basis": position_basis,
        }

    if not rows:
        return {
            "status": "inconclusive" if not gaia_available else "no_match",
            "match_quality": "no_source_in_search_region",
            "matching_radius_arcsec": search_radius_arcsec,
            "candidate_epoch_jyear": candidate_epoch,
            "position_basis": position_basis,
            "nearest_source": None,
            "message": (
                "No AllWISE source was found in the search region."
                if gaia_available
                else
                "No AllWISE source was found, but the candidate position "
                "could not be reliably propagated to the AllWISE reference epoch."
            ),
        }

    # Propagate the confirmed Gaia position to MJD 55400,
    # the epoch of AllWISE ra_pm/dec_pm.
    candidate_motion_epoch_position = None

    if gaia_available:
        candidate_motion_epoch_position = propagate_gaia_to_epoch(
            gaia_result,
            ALLWISE_MOTION_EPOCH,
        )

    valid_rows = []

    for row in rows:

        source_ra = safe_float(row.get("ra"))
        source_dec = safe_float(row.get("dec"))

        if source_ra is None or source_dec is None:
            continue

        motion_ra = safe_float(row.get("ra_pm"))
        motion_dec = safe_float(row.get("dec_pm"))

        epoch_corrected = False
        separation = None

        if (
            candidate_motion_epoch_position is not None
            and motion_ra is not None
            and motion_dec is not None
        ):

            comparison_ra, comparison_dec = (
                candidate_motion_epoch_position
            )

            separation = angular_separation(
                comparison_ra,
                comparison_dec,
                motion_ra,
                motion_dec,
            )

            epoch_corrected = True

        else:
            # Diagnostic only: the positions may refer to different epochs.
            separation = angular_separation(
                ra,
                dec,
                source_ra,
                source_dec,
            )

        row["_separation_arcsec"] = separation
        row["_epoch_corrected"] = epoch_corrected

        valid_rows.append(row)

    if not valid_rows:
        return {
            "status": "inconclusive",
            "message": "AllWISE returned rows without usable coordinates.",
            "candidate_epoch_jyear": candidate_epoch,
            "position_basis": position_basis,
        }

    # Prefer sources for which a common-epoch comparison is available.
    corrected_rows = [
        row for row in valid_rows
        if row["_epoch_corrected"]
    ]

    if corrected_rows:
        nearest = min(
            corrected_rows,
            key=lambda row: row["_separation_arcsec"],
        )
    else:
        nearest = min(
            valid_rows,
            key=lambda row: row["_separation_arcsec"],
        )

    separation = nearest["_separation_arcsec"]
    epoch_corrected = nearest["_epoch_corrected"]

    if not epoch_corrected:

        status = "inconclusive"
        match_quality = "epoch_correction_unavailable"
        message = (
            "A nearby AllWISE source was found, but a reliable "
            "common-epoch comparison could not be made."
        )

    elif separation <= search_radius_arcsec:

        status = "match_found"
        match_quality = "within_radius"
        message = (
            "An AllWISE counterpart was found within the matching radius."
        )

    elif separation <= search_radius_arcsec + 1.0:

        status = "no_match"
        match_quality = "borderline"
        message = (
            "The nearest AllWISE source is just outside the matching radius."
        )

    else:

        status = "no_match"
        match_quality = "outside_radius"
        message = (
            "The nearest AllWISE source is outside the matching radius."
        )

    photometry = format_photometry(nearest)
    motion_fit = format_motion_fit(nearest)

    cc_flags = nearest.get("cc_flags") or "????"

    contamination_summary = {
        "W1": interpret_contamination_flag(
            cc_flags[0] if len(cc_flags) > 0 else None
        ),
        "W2": interpret_contamination_flag(
            cc_flags[1] if len(cc_flags) > 1 else None
        ),
    }

    nearest_source = {
        "designation": nearest.get("designation"),
        "source_id": nearest.get("source_id"),
        "position": {
            "ra": safe_float(nearest.get("ra")),
            "dec": safe_float(nearest.get("dec")),
            "reference_frame": "J2000, 2MASS PSC reference frame",
        },
        "motion_fit": motion_fit,
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
        "observation_epochs_mjd": {
            "W1_mean": safe_float(nearest.get("w1mjdmean")),
            "W2_mean": safe_float(nearest.get("w2mjdmean")),
        },
        "quality_flags": {
            "ph_qual": nearest.get("ph_qual"),
            "cc_flags": nearest.get("cc_flags"),
            "ext_flg": safe_float(nearest.get("ext_flg")),
            "var_flg": nearest.get("var_flg"),
        },
        "contamination_summary": contamination_summary,
        "position_uncertainty": {
            "ra_arcsec": safe_float(nearest.get("sigra")),
            "dec_arcsec": safe_float(nearest.get("sigdec")),
            "motion_ra_arcsec": safe_float(nearest.get("sigra_pm")),
            "motion_dec_arcsec": safe_float(nearest.get("sigdec_pm")),
        },
    }

    return {
        "status": status,
        "match_quality": match_quality,
        "matching_radius_arcsec": search_radius_arcsec,
        "candidate_epoch_jyear": candidate_epoch,
        "position_basis": position_basis,
        "epoch_correction_available": epoch_corrected,
        "comparison_epoch_jyear": (
            ALLWISE_MOTION_EPOCH if epoch_corrected else None
        ),
        "search_position": {
            "ra": search_ra,
            "dec": search_dec,
            "epoch": 2000.0 if gaia_available else candidate_epoch,
            "position_basis": position_basis,
        },
        "nearest_source": nearest_source,
        "message": message,
    }
