
import math

from astropy.coordinates import SkyCoord
from astropy.time import Time
import astropy.units as u


def safe_float(value):
    """Convert a value to a finite float, or return None."""

    try:
        number = float(value)

        if math.isfinite(number):
            return number

    except (TypeError, ValueError):
        pass

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

    if (
        ra is None
        or dec is None
        or pmra is None
        or pmdec is None
        or from_epoch is None
        or to_epoch is None
    ):
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

        return (
            propagated.ra.deg,
            propagated.dec.deg,
        )

    except (ValueError, TypeError, u.UnitConversionError):
        return None


def angular_separation_arcsec(ra1, dec1, ra2, dec2):
    """Calculate angular separation between two sky positions."""

    first = SkyCoord(
        ra=ra1 * u.deg,
        dec=dec1 * u.deg,
    )

    second = SkyCoord(
        ra=ra2 * u.deg,
        dec=dec2 * u.deg,
    )

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
    """Extract a confirmed Gaia source and its astrometry."""

    if not gaia_result:
        return None

    if gaia_result.get("status") != "match_found":
        return None

    if gaia_result.get("match_quality") != "within_radius":
        return None

    source = gaia_result.get("nearest_source") or {}

    catalogue_position = source.get("catalogue_position") or {}
    proper_motion = source.get("proper_motion") or {}

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
    }


def compare_with_gaia(
    catalogue,
    catalogue_result,
    gaia_reference,
    matching_radius_arcsec,
):
    """
    Compare one catalogue source with the confirmed Gaia source.

    The Gaia position is propagated to the epoch of the other
    catalogue's position whenever that epoch is known.
    """

    if not catalogue_result:
        return {
            "status": "not_checked",
            "reason": "This catalogue was not queried.",
        }

    if gaia_reference is None:
        return {
            "status": "not_assessable",
            "reason": (
                "A confirmed Gaia match with usable proper motion "
                "is required as the astrometric reference."
            ),
        }

    source = catalogue_result.get("nearest_source") or {}

    if not source:
        return {
            "status": "no_source_to_compare",
            "reason": (
                "The catalogue did not return a source with "
                "coordinates for cross-catalogue comparison."
            ),
        }

    gaia_ra = gaia_reference["ra"]
    gaia_dec = gaia_reference["dec"]
    gaia_epoch = gaia_reference["epoch"]

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

    # SIMBAD: use its J2000 position. We only compare it if its
    # coordinates and reference epoch are available.
    elif catalogue == "simbad":

        position = source.get("position") or {}

        source_ra = safe_float(position.get("ra"))
        source_dec = safe_float(position.get("dec"))
        comparison_epoch = safe_float(
            position.get("reference_epoch")
        )

        position_description = "SIMBAD catalogue position"

        # SIMBAD positional uncertainties are not currently
        # included in the service response.
        position_uncertainty = None

    else:
        return {
            "status": "unsupported_catalogue",
            "reason": f"Unsupported catalogue: {catalogue}",
        }

    if None in (source_ra, source_dec, comparison_epoch):
        return {
            "status": "not_assessable",
            "reason": (
                "The catalogue source does not provide a usable "
                "position and reference epoch."
            ),
        }

    # Propagate Gaia to the epoch of the catalogue position.
    propagated_gaia = propagate_position(
        gaia_ra,
        gaia_dec,
        gaia_reference["pmra"],
        gaia_reference["pmdec"],
        gaia_epoch,
        comparison_epoch,
    )

    if propagated_gaia is None:
        return {
            "status": "not_assessable",
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

    return {
        "status": classification,
        "catalogue": catalogue,
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
        "uncertainty_weighted": False,
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

    Gaia is used as the astrometric reference. This is not a
    complete all-pairs cross-identification algorithm.
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

    assessed = [
        item.get("status")
        for item in comparisons.values()
        if item.get("status") in (
            "consistent",
            "borderline",
            "inconsistent",
        )
    ]

    if not assessed:
        overall_status = "not_assessable"

    elif "inconsistent" in assessed and "consistent" in assessed:
        overall_status = "mixed_evidence"

    elif "consistent" in assessed:
        overall_status = "consistent"

    elif "borderline" in assessed:
        overall_status = "borderline"

    else:
        overall_status = "inconsistent"

    return {
        "status": overall_status,
        "reference_catalogue": "gaia",
        "reference_source_id": gaia_reference["source_id"],
        "reference_epoch_jyear": gaia_reference["epoch"],
        "comparisons": comparisons,
        "uncertainty_weighted": False,
        "method": (
            "Geometric positional comparison using Gaia proper "
            "motion to propagate the Gaia position to each "
            "catalogue source epoch. No statistical uncertainty "
            "weighting is applied."
        ),
    }
