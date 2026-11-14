
import math


def is_accepted_match(catalogue, result):
    """Return True only for a catalogue association accepted by verification."""
    if not result:
        return False

    if (
        result.get("status") != "match_found"
        or result.get("match_quality") != "within_radius"
    ):
        return False

    # 2MASS and AllWISE require a reliable common-epoch comparison.
    if catalogue in ("2mass", "allwise"):
        return result.get("epoch_correction_available") is True

    return True


def get_source_identifier(catalogue, source):
    """Extract a readable identifier from a catalogue source."""
    if not source:
        return None

    if catalogue == "gaia":
        return source.get("source_id")

    if catalogue == "simbad":
        return source.get("main_id") or source.get("oid")

    if catalogue == "2mass":
        return source.get("designation")

    if catalogue == "allwise":
        return source.get("source_id") or source.get("designation")

    return None


def _gaia_astrometry(source):
    """Format Gaia astrometry, retaining Gaia as the explicit source."""
    position = source.get("propagated_position") or {}
    catalogue_position = source.get("catalogue_position") or {}
    proper_motion = source.get("proper_motion") or {}
    astrometry = source.get("astrometry") or {}

    return {
        "reference_catalogue": "Gaia DR3",

        "position_at_observation_epoch": {
            "ra_deg": position.get("ra"),
            "dec_deg": position.get("dec"),
            "epoch": position.get("observation_epoch"),
        },

        "catalogue_position": {
            "ra_deg": catalogue_position.get("ra"),
            "dec_deg": catalogue_position.get("dec"),
            "reference_epoch": catalogue_position.get(
                "reference_epoch"
            ),
            "reference_epoch_assumed": False,
        },

        "proper_motion": {
            "pmra_mas_yr": proper_motion.get("pmra_mas_yr"),
            "pmdec_mas_yr": proper_motion.get("pmdec_mas_yr"),
            "total_mas_yr": proper_motion.get("total_mas_yr"),
        },

        "parallax_mas": astrometry.get("parallax_mas"),
        "parallax_error_mas": astrometry.get("parallax_error_mas"),
        "distance": source.get("distance"),
        "ruwe": astrometry.get("ruwe"),
        "radial_velocity_km_s": astrometry.get(
            "radial_velocity_km_s"
        ),
    }


def _simbad_astrometry(source):
    """
    Format SIMBAD astrometry when Gaia has no accepted association.

    SIMBAD does not currently provide parallax uncertainty through
    our query, so distance is deliberately left unavailable.
    """
    position = source.get("position") or {}
    propagated = source.get("propagated_position") or {}
    proper_motion = source.get("proper_motion") or {}

    pmra = proper_motion.get("pmra_mas_yr")
    pmdec = proper_motion.get("pmdec_mas_yr")

    total_pm = None

    if pmra is not None and pmdec is not None:
        try:
            total_pm = math.hypot(float(pmra), float(pmdec))
        except (TypeError, ValueError):
            total_pm = None

    return {
        "reference_catalogue": "SIMBAD",

        "position_at_observation_epoch": {
            "ra_deg": propagated.get("ra"),
            "dec_deg": propagated.get("dec"),
            "epoch": propagated.get("observation_epoch"),
            "proper_motion_applied": propagated.get(
                "proper_motion_applied"
            ),
        },

        "catalogue_position": {
            "ra_deg": position.get("ra"),
            "dec_deg": position.get("dec"),
            "reference_epoch": position.get("reference_epoch"),
            "reference_epoch_assumed": position.get(
                "reference_epoch_assumed"
            ),
        },

        "proper_motion": {
            "pmra_mas_yr": pmra,
            "pmdec_mas_yr": pmdec,
            "total_mas_yr": (
                round(total_pm, 6)
                if total_pm is not None
                else None
            ),
        },

        "parallax_mas": source.get("parallax_mas"),

        # The current SIMBAD query does not retrieve this uncertainty.
        "parallax_error_mas": None,

        # Do not infer a distance without a usable parallax uncertainty.
        "distance": None,

        "ruwe": None,
        "radial_velocity_km_s": None,
    }


def build_object_profile(
    candidate_id,
    catalogue_results,
    evidence_summary,
    photometric_assessment,
):
    """
    Build a human-readable profile from accepted catalogue evidence.

    Gaia astrometry is preferred. Accepted SIMBAD astrometry is used
    as a fallback when Gaia is unavailable.

    This function does not independently perform catalogue matching
    or infer an astrophysical class from photometric colours.
    """

    catalogue_results = catalogue_results or {}
    evidence_summary = evidence_summary or {}
    photometric_assessment = photometric_assessment or {}

    gaia_result = catalogue_results.get("gaia") or {}
    simbad_result = catalogue_results.get("simbad") or {}

    gaia_source = gaia_result.get("nearest_source") or {}
    simbad_source = simbad_result.get("nearest_source") or {}

    gaia_accepted = is_accepted_match("gaia", gaia_result)
    simbad_accepted = is_accepted_match("simbad", simbad_result)

    # ---------------------------------------------------------
    # Identity
    # ---------------------------------------------------------

    if simbad_accepted:

        identity = {
            "display_name": (
                simbad_source.get("name")
                or simbad_source.get("main_id")
                or f"Candidate {candidate_id}"
            ),

            "identifier": (
                simbad_source.get("main_id")
                or simbad_source.get("oid")
            ),

            "identifier_source": "SIMBAD",

            "alternative_names": (
                simbad_source.get("alternative_names") or []
            ),

            "object_type": simbad_source.get("object_type"),
            "object_type_code": simbad_source.get("object_type_code"),
            "spectral_type": simbad_source.get("spectral_type"),
            "simbad_url": simbad_source.get("url"),

            "classification_status": (
                "catalogue_classification_available"
                if (
                    simbad_source.get("object_type")
                    or simbad_source.get("spectral_type")
                )
                else "catalogue_classification_unavailable"
            ),
        }

    elif gaia_accepted:

        gaia_id = gaia_source.get("source_id")

        identity = {
            "display_name": (
                f"Gaia DR3 {gaia_id}"
                if gaia_id
                else f"Candidate {candidate_id}"
            ),

            "identifier": gaia_id,
            "identifier_source": "Gaia DR3",
            "alternative_names": [],
            "object_type": None,
            "object_type_code": None,
            "spectral_type": None,
            "simbad_url": None,
            "classification_status": "not_available",
        }

    else:

        identity = {
            "display_name": f"Candidate {candidate_id}",
            "identifier": None,
            "identifier_source": None,
            "alternative_names": [],
            "object_type": None,
            "object_type_code": None,
            "spectral_type": None,
            "simbad_url": None,
            "classification_status": "unidentified",
        }

    # ---------------------------------------------------------
    # Astrometry
    # ---------------------------------------------------------

    # Prefer Gaia if its association was accepted.
    if gaia_accepted:

        astrometric_information = _gaia_astrometry(
            gaia_source
        )

    # Otherwise, use SIMBAD if its association was accepted.
    elif simbad_accepted:

        astrometric_information = _simbad_astrometry(
            simbad_source
        )

    else:

        astrometric_information = {
            "reference_catalogue": None,
            "position_at_observation_epoch": None,
            "catalogue_position": None,
            "proper_motion": None,
            "parallax_mas": None,
            "parallax_error_mas": None,
            "distance": None,
            "ruwe": None,
            "radial_velocity_km_s": None,
        }

    # ---------------------------------------------------------
    # Photometric summary
    # ---------------------------------------------------------

    measurements = (
        photometric_assessment.get("measurements") or []
    )

    colours = photometric_assessment.get("colours") or {}

    sed = photometric_assessment.get("sed") or {}

    sed_points = sed.get("points") or []
    upper_limits = sed.get("upper_limits") or []

    bands = sorted({
        measurement.get("band")
        for measurement in measurements
        if measurement.get("band")
    })

    photometry_summary = {
        "status": photometric_assessment.get(
            "status",
            "not_available"
        ),

        "measurement_count": len(measurements),
        "sed_detection_count": len(sed_points),
        "upper_limit_count": len(upper_limits),

        "available_bands": bands,
        "colours": colours,

        "quality_flags": (
            photometric_assessment.get("quality_flags") or []
        ),

        "excluded_catalogues": (
            photometric_assessment.get("excluded_catalogues") or []
        ),
    }

    # ---------------------------------------------------------
    # Catalogue association evidence
    # ---------------------------------------------------------

    evidence = {
        "overall_assessment": evidence_summary.get(
            "assessment",
            "insufficient_evidence"
        ),

        "explanation": evidence_summary.get("explanation"),

        "confirmed_associations": evidence_summary.get(
            "confirmed_associations",
            0
        ),

        "potential_associations": evidence_summary.get(
            "potential_associations",
            0
        ),

        "no_associations": evidence_summary.get(
            "no_associations",
            0
        ),

        "conflicts_detected": (
            evidence_summary.get("conflicts_detected") or []
        ),
    }

    accepted_catalogues = [
        name
        for name, result in catalogue_results.items()
        if is_accepted_match(name, result)
    ]

    # ---------------------------------------------------------
    # Warnings and limitations
    # ---------------------------------------------------------

    warnings = []

    if not simbad_accepted:

        if simbad_source:
            warnings.append(
                "A nearby SIMBAD source was returned but was not "
                "accepted as the candidate's identity."
            )
        else:
            warnings.append(
                "No accepted SIMBAD identification is available."
            )

    if not gaia_accepted:

        if simbad_accepted:
            warnings.append(
                "Gaia was not accepted; astrometry is therefore "
                "sourced from SIMBAD where available."
            )
        else:
            warnings.append(
                "No accepted Gaia association is available for "
                "astrometric enrichment."
            )

    if not measurements:
        warnings.append(
            "No usable photometric measurements are available."
        )

    if evidence_summary.get("conflicts_detected"):
        warnings.append(
            "Catalogue association conflicts require manual review."
        )

    # ---------------------------------------------------------
    # Profile status
    # ---------------------------------------------------------

    if simbad_accepted:
        profile_status = "identified"

    elif gaia_accepted or accepted_catalogues:
        profile_status = "partially_identified"

    else:
        profile_status = "unidentified"

    return {
        "profile_status": profile_status,

        "identity": identity,

        "astrometry": astrometric_information,

        "photometry": photometry_summary,

        "association_evidence": evidence,

        "accepted_catalogues": accepted_catalogues,

        "warnings": warnings,

        "notes": [
            "Object classifications are taken from accepted catalogue associations only.",

            "Gaia DR3 astrometry is preferred; accepted SIMBAD astrometry is used only as a fallback.",

            "SIMBAD parallax uncertainty is not available from the current query, so no distance is inferred from SIMBAD parallax.",

            "Photometric colours are supporting evidence and are not used here to assign an astrophysical class.",

            "SIMBAD magnitudes are retained as catalogue magnitudes and are not converted into flux without a confirmed photometric system and calibration.",

            "Missing catalogue properties are represented as null or unavailable rather than inferred.",
        ],
    }
