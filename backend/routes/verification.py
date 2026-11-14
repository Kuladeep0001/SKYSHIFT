
from fastapi import APIRouter

from backend.models.verification import (
    VerificationRequest,
    VerificationResponse,
    CandidateVerificationResult,
)

from backend.services.gaia import gaia_match
from backend.services.simbad import simbad_match
from backend.services.twomass import twomass_match
from backend.services.allwise import allwise_match
from backend.services.crossmatch import crossmatch_catalogues
from backend.services.photometric_validation import (
    build_photometric_validation,
)
from backend.services.object_profile import build_object_profile
from backend.services.exoplanet_archive import exoplanet_host_match



router = APIRouter(
    prefix="/api/verification",
    tags=["Catalogue Verification"],
)


def get_source_identifier(catalogue, nearest_source):
    """Get the most useful source identifier for a catalogue."""

    if not nearest_source:
        return None

    if catalogue == "gaia":
        return nearest_source.get("source_id")

    if catalogue == "2mass":
        return (
            nearest_source.get("designation")
            or nearest_source.get("id")
        )

    if catalogue == "allwise":
        return (
            nearest_source.get("source_id")
            or nearest_source.get("designation")
        )

    if catalogue == "simbad":
        return (
            nearest_source.get("main_id")
            or nearest_source.get("oid")
        )

    return (
        nearest_source.get("source_id")
        or nearest_source.get("designation")
        or nearest_source.get("main_id")
    )



def get_separation(result, nearest_source):
    """Return the best available separation for display."""

    separation = nearest_source.get("separation_arcsec")

    if separation is None:
        separation = nearest_source.get(
            "epoch_corrected_separation_arcsec"
        )

    if separation is None:
        separation = result.get("separation_arcsec")

    if separation is None:
        separation = nearest_source.get(
            "uncorrected_separation_arcsec"
        )

    return separation


def get_propagated_coordinates(nearest_source):
    """Extract propagated RA/Dec from a catalogue source, if available."""

    if not nearest_source:
        return None

    position = nearest_source.get("propagated_position")

    if not isinstance(position, dict):
        return None

    ra = position.get("ra")
    dec = position.get("dec")

    if ra is None:
        ra = position.get("ra_deg")

    if dec is None:
        dec = position.get("dec_deg")

    try:
        ra = float(ra)
        dec = float(dec)
    except (TypeError, ValueError):
        return None

    if not (0 <= ra < 360 and -90 <= dec <= 90):
        return None

    return ra, dec


def get_photometry_caveats(catalogue, nearest_source):
    """
    Extract photometric warnings without treating them as
    positional-match failures.
    """

    caveats = []

    if catalogue != "allwise":
        return caveats

    photometry = nearest_source.get("photometry", {})

    for band, measurement in photometry.items():

        contamination = measurement.get("contamination_flag", {})
        contamination_assessment = contamination.get("assessment")

        if contamination_assessment == "possibly_spurious":
            caveats.append(
                f"{band} may be a spurious detection "
                "because of an image artifact."
            )

        elif contamination_assessment == (
            "real_detection_potentially_contaminated"
        ):
            caveats.append(
                f"{band} is considered a real detection, "
                "but its measurement may be contaminated."
            )

    return caveats


def classify_catalogue_evidence(catalogue, result):
    """
    Apply catalogue-specific criteria to a catalogue result.

    Returns:
        evidence classification
        reasons explaining the classification
        photometric caveats
    """

    status = result.get("status")
    match_quality = result.get("match_quality")

    nearest_source = result.get("nearest_source") or {}

    separation = get_separation(result, nearest_source)
    matching_radius = result.get("matching_radius_arcsec")

    reasons = []
    caveats = get_photometry_caveats(
        catalogue,
        nearest_source,
    )

    # A borderline result is never a confirmed association.
    if match_quality == "borderline":
        return (
            "potential_association",
            [
                "The nearest source is outside the accepted "
                "matching radius but close enough to warrant review."
            ],
            caveats,
        )

    # No source was accepted by the catalogue service.
    if status == "no_match":
        return (
            "no_association",
            [
                "The catalogue did not find a source satisfying "
                "its matching criteria."
            ],
            caveats,
        )

    # The catalogue could not make a reliable comparison.
    if status == "inconclusive":

        if nearest_source:
            reasons.append(
                "A nearby source was found, but the catalogue "
                "could not establish a reliable association."
            )

            if (
                result.get("epoch_correction_available") is False
                or match_quality == "epoch_correction_unavailable"
            ):
                reasons.append(
                    "A reliable common-epoch positional comparison "
                    "was unavailable."
                )

            return (
                "potential_association",
                reasons,
                caveats,
            )

        return (
            "insufficient_evidence",
            [
                "The catalogue could not determine whether "
                "a matching source exists."
            ],
            caveats,
        )

    # A service must explicitly return match_found.
    if status != "match_found":
        return (
            "insufficient_evidence",
            [
                f"Catalogue returned status '{status}', "
                "which is not sufficient to establish an association."
            ],
            caveats,
        )

    # All accepted matches must have an accepted positional quality.
    if match_quality != "within_radius":
        return (
            "potential_association",
            [
                "The service returned match_found, but the "
                "match quality is not within_radius."
            ],
            caveats,
        )

    # Check the actual separation where the service provides it.
    if separation is not None and matching_radius is not None:
        if separation > matching_radius:
            return (
                "potential_association",
                [
                    "The reported separation exceeds the "
                    "matching radius."
                ],
                caveats,
            )

    # 2MASS and AllWISE require an epoch-compatible comparison.
    if catalogue in ("2mass", "allwise"):

        epoch_correction_available = result.get(
            "epoch_correction_available"
        )

        if epoch_correction_available is not True:
            return (
                "potential_association",
                [
                    "The catalogue returned a possible match, "
                    "but a reliable common-epoch comparison "
                    "was not confirmed."
                ],
                caveats,
            )

        if separation is None:
            return (
                "potential_association",
                [
                    "The catalogue did not provide a usable "
                    "common-epoch separation."
                ],
                caveats,
            )
    #____

    
    if catalogue in ("2mass", "allwise"):

        epoch_correction_available = result.get(
            "epoch_correction_available"
        )

        if epoch_correction_available is not True:
            return (
                "potential_association",
                [
                    "The catalogue returned a possible match, "
                    "but a reliable common-epoch comparison "
                    "was not confirmed."
                ],
                caveats,
            )

        common_epoch_separation = (
            nearest_source.get("epoch_corrected_separation_arcsec")
            or nearest_source.get("separation_arcsec")
            or result.get("separation_arcsec")
        )

        if common_epoch_separation is None:
            return (
                "potential_association",
                [
                    "The catalogue did not provide a usable "
                    "common-epoch separation."
                ],
                caveats,
            )

        if matching_radius is not None:
            if common_epoch_separation > matching_radius:
                return (
                    "potential_association",
                    [
                        "The common-epoch separation exceeds "
                        "the matching radius."
                    ],
                    caveats,
                )




    reasons.append(
        "The catalogue returned match_found with an accepted "
        "positional match quality."
    )

    if catalogue in ("2mass", "allwise"):
        reasons.append(
            "The positional comparison was made using "
            "epoch-corrected coordinates."
        )

    return (
        "confirmed_association",
        reasons,
        caveats,
    )


def build_evidence_summary(catalogue_results):
    """Combine catalogue evidence into an overall assessment."""

    catalogue_evidence = {}

    for catalogue, result in catalogue_results.items():

        evidence, reasons, caveats = classify_catalogue_evidence(
            catalogue,
            result,
        )

        nearest_source = result.get("nearest_source") or {}

        catalogue_evidence[catalogue] = {
            "evidence": evidence,
            "status": result.get("status"),
            "match_quality": result.get("match_quality"),
            "source_identifier": get_source_identifier(
                catalogue,
                nearest_source,
            ),
            "separation_arcsec": get_separation(
                result,
                nearest_source,
            ),
            "reasons": reasons,
            "photometric_caveats": caveats,
        }

    evidence_types = [
        item["evidence"]
        for item in catalogue_evidence.values()
    ]

    confirmed_count = evidence_types.count(
        "confirmed_association"
    )

    potential_count = evidence_types.count(
        "potential_association"
    )

    no_association_count = evidence_types.count(
        "no_association"
    )

    insufficient_count = evidence_types.count(
        "insufficient_evidence"
    )

    # Only report a conflict if a catalogue service explicitly
    # provides evidence of an association conflict.
    conflicts = [
        catalogue
        for catalogue, result in catalogue_results.items()
        if result.get("association_conflict") is True
    ]

    if conflicts:
        assessment = "conflicting_evidence"
        explanation = (
            "One or more catalogue services explicitly reported "
            "conflicting association evidence. Manual investigation "
            "is required."
        )

    elif confirmed_count > 0:
        assessment = "confirmed_association"
        explanation = (
            "At least one catalogue returned an accepted positional "
            "association. Review the individual catalogue results "
            "and photometric caveats before treating the source "
            "identification as definitive."
        )

    elif potential_count > 0:
        assessment = "potential_association"
        explanation = (
            "One or more catalogues found a potentially relevant "
            "source, but the available evidence is insufficient "
            "to confirm the association."
        )

    elif (
        evidence_types
        and no_association_count == len(evidence_types)
    ):
        assessment = "no_association"
        explanation = (
            "None of the queried catalogues found a source "
            "satisfying the applied matching criteria."
        )

    else:
        assessment = "insufficient_evidence"
        explanation = (
            "The available catalogue results are insufficient "
            "to determine whether the candidate is a known source."
        )

    return assessment, {
        "assessment": assessment,
        "explanation": explanation,
        "catalogues_checked": len(catalogue_evidence),
        "confirmed_associations": confirmed_count,
        "potential_associations": potential_count,
        "no_associations": no_association_count,
        "insufficient_evidence": insufficient_count,
        "conflicts_detected": conflicts,
        "conflict_assessment_available": False,
        "catalogues": catalogue_evidence,
    }


@router.post("/", response_model=VerificationResponse)
async def verify_candidates(request: VerificationRequest):

    results = []

    for candidate in request.candidates:

        catalogue_results = {}

        # Gaia runs first because the infrared services may use
        # its confirmed proper motion for epoch-aware matching.
        catalogue_order = sorted(
            request.catalogues,
            key=lambda name: name != "gaia",
        )

        for catalogue in catalogue_order:

            if catalogue == "gaia":

                result = await gaia_match(
                    ra=candidate.ra,
                    dec=candidate.dec,
                    observation_time=candidate.observation_time,
                    search_radius_arcsec=request.search_radius_arcsec,
                )

                catalogue_results["gaia"] = result

            elif catalogue == "2mass":

                result = await twomass_match(
                    ra=candidate.ra,
                    dec=candidate.dec,
                    observation_time=candidate.observation_time,
                    search_radius_arcsec=request.search_radius_arcsec,
                    gaia_result=catalogue_results.get("gaia"),
                )

                catalogue_results["2mass"] = result

            elif catalogue == "allwise":

                result = await allwise_match(
                    ra=candidate.ra,
                    dec=candidate.dec,
                    observation_time=candidate.observation_time,
                    search_radius_arcsec=request.search_radius_arcsec,
                    gaia_result=catalogue_results.get("gaia"),
                )

                catalogue_results["allwise"] = result

            elif catalogue == "simbad":

                result = await simbad_match(
                    ra=candidate.ra,
                    dec=candidate.dec,
                    observation_time=candidate.observation_time,
                    search_radius_arcsec=request.search_radius_arcsec,
                )

                catalogue_results["simbad"] = result

        cross_catalogue_association = crossmatch_catalogues(
            catalogue_results=catalogue_results,
            matching_radius_arcsec=request.search_radius_arcsec,
        )

        assessment, evidence_summary = build_evidence_summary(
            catalogue_results
        )
        
        photometric_assessment = build_photometric_validation(
            catalogue_results
        )

        object_profile = build_object_profile(
            candidate_id=candidate.candidate_id,
            catalogue_results=catalogue_results,
            evidence_summary=evidence_summary,
            photometric_assessment=photometric_assessment,
        )

        
        # -----------------------------------------------------
        # NASA Exoplanet Archive lookup
        # -----------------------------------------------------

        accepted_gaia = catalogue_results.get("gaia") or {}
        accepted_simbad = catalogue_results.get("simbad") or {}

        gaia_source = accepted_gaia.get("nearest_source") or {}
        simbad_source = accepted_simbad.get("nearest_source") or {}

        gaia_is_accepted = (
            accepted_gaia.get("status") == "match_found"
            and accepted_gaia.get("match_quality") == "within_radius"
        )

        simbad_is_accepted = (
            accepted_simbad.get("status") == "match_found"
            and accepted_simbad.get("match_quality") == "within_radius"
        )

        if gaia_is_accepted or simbad_is_accepted:

            # Prefer Gaia's propagated position.
            query_coordinates = (
                get_propagated_coordinates(gaia_source)
                if gaia_is_accepted
                else None
            )

            position_source = "gaia_propagated_position"

            # If Gaia's propagated position is unavailable, use
            # accepted SIMBAD astrometry when it is available.
            if query_coordinates is None and simbad_is_accepted:
                query_coordinates = get_propagated_coordinates(
                    simbad_source
                )
                position_source = "simbad_propagated_position"

            # Fall back to the original candidate coordinates.
            if query_coordinates is None:
                query_ra = candidate.ra
                query_dec = candidate.dec
                position_source = "candidate_input"
            else:
                query_ra, query_dec = query_coordinates

            exoplanet_association = await exoplanet_host_match(
                ra=query_ra,
                dec=query_dec,
                gaia_dr3_id=(
                    gaia_source.get("source_id")
                    if gaia_is_accepted
                    else None
                ),
                position_source=position_source,
                position_epoch=candidate.observation_time.isoformat(),
            )

        else:

            exoplanet_association = {
                "status": "not_checked",
                "association_method": None,
                "match_radius_arcsec": 3.0,
                "search_radius_arcsec": 10.0,
                "separation_arcsec": None,
                "host_name": None,
                "host_names": [],
                "planet_count": 0,
                "planets": [],
                "message": (
                    "Exoplanet Archive lookup was skipped because "
                    "neither Gaia nor SIMBAD produced an accepted "
                    "positional association."
                ),
                "archive": "NASA Exoplanet Archive",
                "table": "pscomppars",
                "query_position": None,
            }

        results.append(
            CandidateVerificationResult(
                candidate_id=candidate.candidate_id,
                catalogue_results=catalogue_results,
                assessment=assessment,
                evidence_summary=evidence_summary,
                cross_catalogue_association=cross_catalogue_association,
                photometric_assessment=photometric_assessment,
                object_profile=object_profile,
                exoplanet_association=exoplanet_association
            )
        )

    return VerificationResponse(results=results)
