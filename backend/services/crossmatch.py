
import math

from astropy.coordinates import SkyCoord
from astropy.time import Time
import astropy.units as u


def safe_float(value):
    """Convert a value to a finite float, or return None."""
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def propagate_position(
    ra,
    dec,
    pmra,
    pmdec,
    from_epoch,
    to_epoch,
):
    """
    Propagate a position using proper motion.

    pmra is assumed to be mu_alpha*cos(dec), in mas/year.
    No parallax or radial-velocity correction is applied.
    """
    if None in (ra, dec, pmra, pmdec, from_epoch, to_epoch):
        return None

    try:
        coordinate = SkyCoord(
            ra=ra * u.deg,
            dec=dec * u.deg,
            pm_ra_cosdec=pmra * u.mas / u.yr,
            pm_dec=pmdec * u.mas / u.yr,
            obstime=Time(from_epoch, format="jyear"),
        )

        propagated = coordinate.apply_space_motion(
            new_obstime=Time(to_epoch, format="jyear")
        )

        return propagated.ra.deg, propagated.dec.deg

    except (ValueError, TypeError, u.UnitConversionError):
        return None


def angular_separation_arcsec(ra1, dec1, ra2, dec2):
    """Calculate angular separation between two sky positions."""
    first = SkyCoord(ra=ra1 * u.deg, dec=dec1 * u.deg)
    second = SkyCoord(ra=ra2 * u.deg, dec=dec2 * u.deg)

    return first.separation(second).arcsec


def classify_separation(separation_arcsec, radius_arcsec):
    """
    Apply a geometric screening threshold.

    These are screening categories, not statistical confidence levels.
    """
    if separation_arcsec <= radius_arcsec:
        return "consistent"

    if separation_arcsec <= 2 * radius_arcsec:
        return "borderline"

    return "inconsistent"


def get_gaia_reference(gaia_result):
    """Extract a confirmed Gaia source, proper motion and uncertainties."""
    if not gaia_result:
        return None

    if gaia_result.get("status") != "match_found":
        return None

    if gaia_result.get("match_quality") != "within_radius":
        return None

    source = gaia_result.get("nearest_source") or {}

    catalogue_position = source.get("catalogue_position") or {}
    proper_motion = source.get("proper_motion") or {}
    uncertainties = source.get("astrometric_uncertainties") or {}

    ra = safe_float(catalogue_position.get("ra"))
    dec = safe_float(catalogue_position.get("dec"))
    epoch = safe_float(catalogue_position.get("reference_epoch"))

    pmra = safe_float(proper_motion.get("pmra_mas_yr"))
    pmdec = safe_float(proper_motion.get("pmdec_mas_yr"))

    if None in (ra, dec, epoch, pmra, pmdec):
        return None

    return {
        "source_id": source.get("source_id"),
        "ra": ra,
        "dec": dec,
        "epoch": epoch,
        "pmra": pmra,
        "pmdec": pmdec,
        "ra_error_mas": safe_float(
            uncertainties.get("ra_error_mas")
        ),
        "dec_error_mas": safe_float(
            uncertainties.get("dec_error_mas")
        ),
        "pmra_error_mas_yr": safe_float(
            uncertainties.get("pmra_error_mas_yr")
        ),
        "pmdec_error_mas_yr": safe_float(
            uncertainties.get("pmdec_error_mas_yr")
        ),
    }


def propagate_gaia_uncertainty(gaia_reference, target_epoch):
    """
    Approximate Gaia positional uncertainty at a target epoch.

    Variance = position variance + (time difference)^2 * PM variance.

    Assumes independent position and proper-motion errors.
    Gaia covariance terms are not included.
    """
    required = (
        gaia_reference.get("ra_error_mas"),
        gaia_reference.get("dec_error_mas"),
        gaia_reference.get("pmra_error_mas_yr"),
        gaia_reference.get("pmdec_error_mas_yr"),
    )

    if any(value is None for value in required):
        return None

    delta_years = target_epoch - gaia_reference["epoch"]

    ra_variance = (
        gaia_reference["ra_error_mas"] ** 2
        + (delta_years * gaia_reference["pmra_error_mas_yr"]) ** 2
    )

    dec_variance = (
        gaia_reference["dec_error_mas"] ** 2
        + (delta_years * gaia_reference["pmdec_error_mas_yr"]) ** 2
    )

    return {
        "ra_arcsec": math.sqrt(ra_variance) / 1000.0,
        "dec_arcsec": math.sqrt(dec_variance) / 1000.0,
        "epoch_jyear": target_epoch,
        "method": "position_and_proper_motion_error_propagation",
        "covariance_included": False,
    }


def calculate_normalized_separation(
    ra1,
    dec1,
    ra2,
    dec2,
    sigma_ra_arcsec,
    sigma_dec_arcsec,
):
    """
    Calculate a two-dimensional normalized positional separation.

    RA offset is projected onto the local tangent plane using
    cos(mean declination).

    Assumes independent RA and Dec errors.
    """
    if (
        sigma_ra_arcsec is None
        or sigma_dec_arcsec is None
        or sigma_ra_arcsec <= 0
        or sigma_dec_arcsec <= 0
    ):
        return None

    delta_ra_deg = (ra2 - ra1 + 180.0) % 360.0 - 180.0
    mean_dec_rad = math.radians((dec1 + dec2) / 2.0)

    delta_ra_arcsec = (
        delta_ra_deg * math.cos(mean_dec_rad) * 3600.0
    )
    delta_dec_arcsec = (dec2 - dec1) * 3600.0

    chi_square = (
        (delta_ra_arcsec / sigma_ra_arcsec) ** 2
        + (delta_dec_arcsec / sigma_dec_arcsec) ** 2
    )

    return {
        "delta_ra_tangent_plane_arcsec": delta_ra_arcsec,
        "delta_dec_arcsec": delta_dec_arcsec,
        "chi_square": chi_square,
        "normalized_separation": math.sqrt(chi_square),
        "degrees_of_freedom": 2,
        "interpretation": (
            "Two-dimensional positional discrepancy in combined "
            "standard-error units. Assumes independent coordinate "
            "errors and does not include astrometric covariance."
        ),
    }


def compare_with_gaia(
    catalogue,
    catalogue_result,
    gaia_reference,
    matching_radius_arcsec,
):
    """
    Compare one catalogue source with the confirmed Gaia source.

    The geometric comparison is retained as a diagnostic even if
    the catalogue's own matcher rejected the source.

    association_accepted indicates whether the catalogue's own
    matching service accepted the source.
    """
    if not catalogue_result:
        return {
            "status": "not_checked",
            "association_accepted": False,
            "reason": "This catalogue was not queried.",
        }

    if gaia_reference is None:
        return {
            "status": "not_assessable",
            "association_accepted": False,
            "reason": (
                "A confirmed Gaia match with usable proper motion "
                "is required as the astrometric reference."
            ),
        }

    catalogue_match_status = catalogue_result.get("status")
    catalogue_match_quality = catalogue_result.get("match_quality")

    # Only an explicit match_found from the catalogue service
    # counts as an accepted catalogue association.
    association_accepted = (
        catalogue_match_status == "match_found"
        and catalogue_match_quality in (None, "within_radius")
    )

    source = catalogue_result.get("nearest_source") or {}

    if not source:
        return {
            "status": "no_source_to_compare",
            "catalogue_match_status": catalogue_match_status,
            "catalogue_match_quality": catalogue_match_quality,
            "association_accepted": False,
            "reason": (
                "The catalogue did not return a source with "
                "coordinates for cross-catalogue comparison."
            ),
        }

    comparison_epoch = None
    source_ra = None
    source_dec = None
    position_description = None
    position_uncertainty = None

    # 2MASS: compare at the individual source's observation epoch.
    if catalogue == "2mass":
        position = source.get("position") or {}

        source_ra = safe_float(position.get("ra"))
        source_dec = safe_float(position.get("dec"))

        comparison_epoch = safe_float(
            position.get("reference_epoch_jyear")
        )

        position_description = "2MASS source position"

        errors = source.get("position_error") or {}

        position_uncertainty = {
            "major_axis_arcsec": safe_float(
                errors.get("major_axis_arcsec")
            ),
            "minor_axis_arcsec": safe_float(
                errors.get("minor_axis_arcsec")
            ),
        }

    # AllWISE: use its fitted position at the motion-fit reference
    # epoch. Do not use its apparent motion as true proper motion.
    elif catalogue == "allwise":
        motion_fit = source.get("motion_fit") or {}

        reference_position = (
            motion_fit.get("position_at_reference_epoch") or {}
        )

        source_ra = safe_float(reference_position.get("ra"))
        source_dec = safe_float(reference_position.get("dec"))

        comparison_epoch = safe_float(
            reference_position.get("reference_epoch_jyear")
        )

        position_description = (
            "AllWISE motion-fit position at its reference epoch"
        )

        position_uncertainty = {
            "ra_arcsec": safe_float(
                reference_position.get("ra_uncertainty_arcsec")
            ),
            "dec_arcsec": safe_float(
                reference_position.get("dec_uncertainty_arcsec")
            ),
        }

    # SIMBAD: use its original catalogue position and assumed epoch.
    elif catalogue == "simbad":
        position = source.get("position") or {}

        source_ra = safe_float(position.get("ra"))
        source_dec = safe_float(position.get("dec"))

        comparison_epoch = safe_float(
            position.get("reference_epoch")
        )

        position_description = "SIMBAD catalogue position"

        position_uncertainty = None

    else:
        return {
            "status": "unsupported_catalogue",
            "catalogue_match_status": catalogue_match_status,
            "catalogue_match_quality": catalogue_match_quality,
            "association_accepted": False,
            "reason": f"Unsupported catalogue: {catalogue}",
        }

    if None in (source_ra, source_dec, comparison_epoch):
        return {
            "status": "not_assessable",
            "catalogue_match_status": catalogue_match_status,
            "catalogue_match_quality": catalogue_match_quality,
            "association_accepted": False,
            "reason": (
                "The catalogue source does not provide a usable "
                "position and reference epoch."
            ),
        }

    propagated_gaia = propagate_position(
        gaia_reference["ra"],
        gaia_reference["dec"],
        gaia_reference["pmra"],
        gaia_reference["pmdec"],
        gaia_reference["epoch"],
        comparison_epoch,
    )

    if propagated_gaia is None:
        return {
            "status": "not_assessable",
            "catalogue_match_status": catalogue_match_status,
            "catalogue_match_quality": catalogue_match_quality,
            "association_accepted": False,
            "reason": (
                "Gaia's position could not be propagated to "
                "the catalogue source epoch."
            ),
        }

    comparison_ra, comparison_dec = propagated_gaia

    separation = angular_separation_arcsec(
        comparison_ra,
        comparison_dec,
        source_ra,
        source_dec,
    )

    classification = classify_separation(
        separation,
        matching_radius_arcsec,
    )

    uncertainty_comparison = None

    if catalogue == "allwise":
        gaia_uncertainty = propagate_gaia_uncertainty(
            gaia_reference,
            comparison_epoch,
        )

        allwise_ra_error = position_uncertainty.get("ra_arcsec")
        allwise_dec_error = position_uncertainty.get("dec_arcsec")

        if (
            gaia_uncertainty is not None
            and allwise_ra_error is not None
            and allwise_dec_error is not None
        ):
            combined_ra_error = math.hypot(
                gaia_uncertainty["ra_arcsec"],
                allwise_ra_error,
            )

            combined_dec_error = math.hypot(
                gaia_uncertainty["dec_arcsec"],
                allwise_dec_error,
            )

            normalized = calculate_normalized_separation(
                comparison_ra,
                comparison_dec,
                source_ra,
                source_dec,
                combined_ra_error,
                combined_dec_error,
            )

            if normalized is not None:
                uncertainty_comparison = {
                    "gaia_position_uncertainty": gaia_uncertainty,
                    "catalogue_position_uncertainty": {
                        "ra_arcsec": allwise_ra_error,
                        "dec_arcsec": allwise_dec_error,
                    },
                    "combined_uncertainty": {
                        "ra_arcsec": combined_ra_error,
                        "dec_arcsec": combined_dec_error,
                    },
                    **normalized,
                    "method": (
                        "Approximate two-dimensional normalized "
                        "separation using propagated Gaia and "
                        "AllWISE positional uncertainties."
                    ),
                    "covariance_included": False,
                }

    return {
        # Geometric result, not the catalogue's acceptance decision.
        "status": classification,
        "geometric_status": classification,

        "catalogue": catalogue,
        "catalogue_match_status": catalogue_match_status,
        "catalogue_match_quality": catalogue_match_quality,
        "association_accepted": association_accepted,

        "source_identifier": (
            source.get("source_id")
            or source.get("designation")
            or source.get("main_id")
            or source.get("oid")
        ),

        "position_description": position_description,
        "comparison_epoch_jyear": comparison_epoch,

        "gaia_position_at_comparison_epoch": {
            "ra": comparison_ra,
            "dec": comparison_dec,
        },

        "catalogue_position": {
            "ra": source_ra,
            "dec": source_dec,
        },

        "separation_arcsec": round(separation, 4),
        "matching_radius_arcsec": matching_radius_arcsec,
        "position_uncertainty": position_uncertainty,
        "uncertainty_comparison": uncertainty_comparison,
        "uncertainty_weighted": uncertainty_comparison is not None,

        "reason": (
            "Positions are geometrically consistent within the "
            "matching radius."
            if classification == "consistent"
            else
            "Positions are close but outside the matching radius."
            if classification == "borderline"
            else
            "Positions are separated by more than twice the "
            "matching radius."
        ),
    }


def crossmatch_catalogues(
    catalogue_results,
    matching_radius_arcsec,
):
    """
    Compare available catalogue sources against a confirmed Gaia source.

    Gaia is the astrometric reference. This is not a complete
    all-pairs cross-identification algorithm.

    Geometric comparisons are retained as diagnostics, but only
    catalogue-accepted matches contribute to the overall status.
    """
    gaia_result = catalogue_results.get("gaia")
    gaia_reference = get_gaia_reference(gaia_result)

    if gaia_reference is None:
        return {
            "status": "not_assessable",
            "reference_catalogue": "gaia",
            "reason": (
                "A confirmed Gaia match with usable proper motion "
                "is required as the astrometric reference."
            ),
            "comparisons": {},
            "uncertainty_weighted": False,
        }

    comparisons = {}

    for catalogue in ("2mass", "allwise", "simbad"):
        if catalogue not in catalogue_results:
            continue

        comparisons[catalogue] = compare_with_gaia(
            catalogue=catalogue,
            catalogue_result=catalogue_results[catalogue],
            gaia_reference=gaia_reference,
            matching_radius_arcsec=matching_radius_arcsec,
        )

    # Only accepted catalogue matches contribute to the overall
    # cross-catalogue consistency assessment.
    accepted_comparisons = [
        item
        for item in comparisons.values()
        if item.get("association_accepted") is True
        and item.get("status") in (
            "consistent",
            "borderline",
            "inconsistent",
        )
    ]

    assessed_statuses = [
        item.get("status")
        for item in accepted_comparisons
    ]

    if not assessed_statuses:
        overall_status = "not_assessable"

    elif (
        "inconsistent" in assessed_statuses
        and "consistent" in assessed_statuses
    ):
        overall_status = "mixed_evidence"

    elif "inconsistent" in assessed_statuses:
        overall_status = "inconsistent"

    elif "consistent" in assessed_statuses:
        overall_status = "consistent"

    else:
        overall_status = "borderline"

    rejected_catalogues = [
        catalogue
        for catalogue, item in comparisons.items()
        if item.get("association_accepted") is False
    ]

    uncertainty_weighted = any(
        item.get("uncertainty_weighted", False)
        for item in comparisons.values()
    )

    return {
        "status": overall_status,
        "reference_catalogue": "gaia",
        "reference_source_id": gaia_reference["source_id"],
        "reference_epoch_jyear": gaia_reference["epoch"],
        "comparisons": comparisons,
        "accepted_catalogue_comparisons": len(accepted_comparisons),
        "rejected_catalogues": rejected_catalogues,
        "uncertainty_weighted": uncertainty_weighted,
        "method": (
            "Geometric positional comparison using Gaia proper "
            "motion to propagate the Gaia position to each "
            "catalogue source epoch. Geometric comparisons are "
            "retained as diagnostics, but only catalogue-accepted "
            "matches contribute to the overall status. Where "
            "positional uncertainties are available, an approximate "
            "normalized separation is also calculated. The "
            "uncertainty calculation assumes independent coordinate "
            "errors and ignores covariance."
        ),
    }
