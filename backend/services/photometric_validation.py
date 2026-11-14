
import math


# Approximate effective/pivot wavelengths in micrometres.
EFFECTIVE_WAVELENGTHS = {
    "G": 0.62179,
    "BP": 0.51097,
    "RP": 0.77691,

    "V": 0.55,
    "J": 1.235,
    "H": 1.662,
    "K": 2.159,
    "Ks": 2.159,

    "W1": 3.4,
    "W2": 4.6,
}


GAIA_MAGNITUDE_SYSTEM = "Gaia Vega"
GAIA_FLUX_CONVENTION = "AB-equivalent flux density"
GAIA_MAGNITUDE_ERROR_METHOD = "derived from flux uncertainty"


def safe_float(value):
    """Convert a value to a finite float, or return None."""
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def estimate_magnitude_uncertainty(flux, flux_error):
    """
    Approximate magnitude uncertainty:

        sigma_mag = 1.0857 * sigma_flux / flux
    """
    flux = safe_float(flux)
    flux_error = safe_float(flux_error)

    if (
        flux is None
        or flux <= 0
        or flux_error is None
        or flux_error < 0
    ):
        return None

    return 1.0857362047581294 * flux_error / flux


def accepted_match(catalogue, result):
    """Only use catalogue sources accepted by positional verification."""

    if not result:
        return False

    if (
        result.get("status") != "match_found"
        or result.get("match_quality") != "within_radius"
    ):
        return False

    # Infrared matches must have a common-epoch comparison.
    if catalogue in ("2mass", "allwise"):
        if result.get("epoch_correction_available") is not True:
            return False

    return bool(result.get("nearest_source"))


def add_measurement(
    measurements,
    sed_points,
    upper_limits,
    *,
    catalogue,
    band,
    wavelength,
    flux,
    flux_error=None,
    magnitude=None,
    magnitude_error=None,
    magnitude_error_method=None,
    magnitude_system=None,
    flux_convention=None,
    epoch=None,
    quality_flag=None,
    detection=True,
    upper_limit=False,
    warnings=None,
    include_in_sed=True,
):
    """Add a normalized measurement and, where valid, an SED point."""

    flux = safe_float(flux)
    flux_error = safe_float(flux_error)
    magnitude = safe_float(magnitude)
    magnitude_error = safe_float(magnitude_error)

    band_warnings = list(warnings or [])

    measurement = {
        "catalogue": catalogue,
        "band": band,
        "wavelength_um": wavelength,

        "flux_mjy": flux,
        "flux_uncertainty_mjy": flux_error,
        "flux_convention": flux_convention,

        "magnitude": magnitude,
        "magnitude_uncertainty": magnitude_error,
        "magnitude_uncertainty_method": magnitude_error_method,
        "magnitude_system": magnitude_system,

        "epoch": epoch,
        "quality_flag": quality_flag,

        "is_detection": detection,
        "is_upper_limit": upper_limit,

        "included_in_sed": bool(
            include_in_sed and detection and flux is not None
        ),

        "warnings": band_warnings,
    }

    measurements.append(measurement)

    if detection and flux is not None and include_in_sed:

        sed_points.append({
            "catalogue": catalogue,
            "band": band,
            "wavelength_um": wavelength,

            "flux_mjy": flux,
            "flux_uncertainty_mjy": flux_error,
            "flux_convention": flux_convention,

            "epoch": epoch,
            "quality_flag": quality_flag,
            "warnings": band_warnings,
        })

    elif upper_limit and flux is not None:

        upper_limits.append({
            "catalogue": catalogue,
            "band": band,
            "wavelength_um": wavelength,

            "upper_limit_flux_mjy": flux,
            "flux_convention": flux_convention,

            "epoch": epoch,
            "quality_flag": quality_flag,
            "warnings": band_warnings,
        })


def calculate_colour(
    name,
    first,
    second,
    first_band,
    second_band,
):
    """Calculate a colour only when both measurements share a system."""

    if first is None or second is None:
        return None

    first_mag = safe_float(first.get("magnitude"))
    second_mag = safe_float(second.get("magnitude"))

    if first_mag is None or second_mag is None:
        return None

    first_system = first.get("magnitude_system")
    second_system = second.get("magnitude_system")

    # Never subtract magnitudes from incompatible or unknown systems.
    if not first_system or first_system != second_system:
        return None

    first_error = safe_float(
        first.get("magnitude_uncertainty")
    )

    second_error = safe_float(
        second.get("magnitude_uncertainty")
    )

    colour_error = None

    if first_error is not None and second_error is not None:
        colour_error = math.sqrt(
            first_error ** 2 + second_error ** 2
        )

    colour_warnings = list(first.get("warnings") or [])
    colour_warnings.extend(second.get("warnings") or [])

    colour_warnings = list(dict.fromkeys(colour_warnings))

    return {
        "name": name,

        "value": round(first_mag - second_mag, 5),

        "uncertainty": (
            round(colour_error, 5)
            if colour_error is not None
            else None
        ),

        "bands": [first_band, second_band],

        "magnitude_system": first_system,

        "quality": (
            "quality_limited"
            if colour_warnings
            else "usable"
        ),

        "warnings": colour_warnings,
    }


def validate_gaia(
    source,
    measurements,
    sed_points,
    upper_limits,
    warnings,
):
    photometry = source.get("photometry") or {}

    band_fields = {
        "G": (
            "g_flux_mjy",
            "g_flux_error_mjy",
            "g_magnitude",
            "g_magnitude_error",
        ),

        "BP": (
            "bp_flux_mjy",
            "bp_flux_error_mjy",
            "bp_magnitude",
            "bp_magnitude_error",
        ),

        "RP": (
            "rp_flux_mjy",
            "rp_flux_error_mjy",
            "rp_magnitude",
            "rp_magnitude_error",
        ),
    }

    valid = {}

    for band, fields in band_fields.items():

        flux = safe_float(photometry.get(fields[0]))
        flux_error = safe_float(photometry.get(fields[1]))
        magnitude = safe_float(photometry.get(fields[2]))
        magnitude_error = safe_float(photometry.get(fields[3]))

        if flux is None:
            continue

        error_method = None

        if magnitude_error is None:

            magnitude_error = estimate_magnitude_uncertainty(
                flux,
                flux_error,
            )

            if magnitude_error is not None:
                error_method = GAIA_MAGNITUDE_ERROR_METHOD

        valid[band] = {
            "magnitude": magnitude,
            "magnitude_uncertainty": magnitude_error,
            "magnitude_system": GAIA_MAGNITUDE_SYSTEM,
            "warnings": [],
        }

        add_measurement(
            measurements,
            sed_points,
            upper_limits,

            catalogue="Gaia DR3",
            band=band,
            wavelength=EFFECTIVE_WAVELENGTHS[band],

            flux=flux,
            flux_error=flux_error,

            magnitude=magnitude,
            magnitude_error=magnitude_error,
            magnitude_error_method=error_method,

            magnitude_system=GAIA_MAGNITUDE_SYSTEM,
            flux_convention=GAIA_FLUX_CONVENTION,
        )

    return valid


def validate_2mass(
    source,
    measurements,
    sed_points,
    upper_limits,
    warnings,
):
    photometry = source.get("photometry") or {}
    position = source.get("position") or {}

    epoch = position.get("jdate")

    valid = {}

    for band in ("J", "H", "Ks"):

        item = photometry.get(band) or {}

        detected = item.get("is_detection") is True
        upper_limit = item.get("is_upper_limit") is True

        quality = item.get("quality_flag")

        band_warnings = []

        if quality in ("C", "D", "E", "F"):
            band_warnings.append(
                f"2MASS {band} has photometric quality flag {quality}."
            )

        if detected:

            valid[band] = {
                "magnitude": item.get("magnitude"),
                "magnitude_uncertainty": item.get("uncertainty"),
                "magnitude_system": "Vega",
                "warnings": band_warnings,
            }

        if upper_limit:
            band_warnings.append(
                "This measurement is an upper limit, not a detection."
            )

        flux = (
            item.get("flux_mjy")
            if detected
            else item.get("upper_limit_flux_mjy")
        )

        add_measurement(
            measurements,
            sed_points,
            upper_limits,

            catalogue="2MASS",
            band=band,
            wavelength=EFFECTIVE_WAVELENGTHS[band],

            flux=flux,

            magnitude=item.get("magnitude"),
            magnitude_error=item.get("uncertainty"),
            magnitude_system="Vega",

            epoch=epoch,
            quality_flag=quality,

            detection=detected,
            upper_limit=upper_limit,
            warnings=band_warnings,
        )

        warnings.extend(band_warnings)

    return valid


def validate_allwise(
    source,
    measurements,
    sed_points,
    upper_limits,
    warnings,
):
    photometry = source.get("photometry") or {}

    epochs = source.get("observation_epochs_mjd") or {}

    valid = {}

    for band in ("W1", "W2"):

        item = photometry.get(band) or {}

        detected = item.get("is_detection") is True
        upper_limit = item.get("is_upper_limit") is True

        contamination = item.get("contamination_flag") or {}

        contamination_assessment = contamination.get(
            "assessment"
        )

        band_warnings = []

        if contamination_assessment == "possibly_spurious":

            band_warnings.append(
                f"{band} may be a spurious detection due to an image artifact."
            )

        elif contamination_assessment == (
            "real_detection_potentially_contaminated"
        ):

            band_warnings.append(
                f"{band} is a real detection but may be contaminated."
            )

        variability_flag = item.get("variability_flag")

        if variability_flag not in (None, "0", "n"):

            band_warnings.append(
                f"{band} has a non-zero variability flag."
            )

        possibly_spurious = (
            contamination_assessment == "possibly_spurious"
        )

        if detected and not possibly_spurious:

            valid[band] = {
                "magnitude": item.get("magnitude_vega"),
                "magnitude_uncertainty": item.get(
                    "magnitude_uncertainty"
                ),
                "magnitude_system": "Vega",
                "warnings": band_warnings,
            }

        if upper_limit:

            band_warnings.append(
                "This measurement is an upper limit, not a detection."
            )

        epoch = epochs.get(f"{band}_mean")

        flux = (
            item.get("flux_mjy")
            if detected
            else item.get("upper_limit_flux_mjy")
        )

        add_measurement(
            measurements,
            sed_points,
            upper_limits,

            catalogue="AllWISE",
            band=band,
            wavelength=EFFECTIVE_WAVELENGTHS[band],

            flux=flux,
            flux_error=item.get("flux_uncertainty_mjy"),

            magnitude=item.get("magnitude_vega"),
            magnitude_error=item.get("magnitude_uncertainty"),
            magnitude_system="Vega",

            epoch=epoch,
            quality_flag=item.get("quality_flag"),

            detection=detected,
            upper_limit=upper_limit,

            warnings=band_warnings,
            include_in_sed=not possibly_spurious,
        )

        warnings.extend(band_warnings)

    return valid


def validate_simbad(source, measurements, warnings):
    """
    Add SIMBAD allfluxes magnitudes without inventing fluxes or errors.

    The current SIMBAD service returns magnitudes in an allfluxes row,
    but does not return the individual measurement system, epoch,
    uncertainty, or bibliography for each band.

    Therefore these values are retained as magnitude-only catalogue
    measurements. They are not converted to flux, included in the
    flux SED, or used to form colours.
    """

    magnitudes = source.get("magnitudes") or {}

    valid_bands = []

    for band in ("V", "J", "H", "K"):

        magnitude = safe_float(magnitudes.get(band))

        if magnitude is None:
            continue

        valid_bands.append(band)

        measurements.append({
            "catalogue": "SIMBAD",
            "band": band,

            "wavelength_um": EFFECTIVE_WAVELENGTHS.get(band),

            "flux_mjy": None,
            "flux_uncertainty_mjy": None,
            "flux_convention": None,

            "magnitude": magnitude,
            "magnitude_uncertainty": None,
            "magnitude_uncertainty_method": None,

            "magnitude_system": (
                "SIMBAD allfluxes; band-specific system "
                "not specified by current query"
            ),

            "epoch": None,
            "quality_flag": None,

            "is_detection": True,
            "is_upper_limit": False,

            "included_in_sed": False,

            "warnings": [
                "SIMBAD allfluxes magnitude retained as reported; "
                "the current query does not provide its individual "
                "photometric system, epoch, uncertainty, or "
                "bibliographic reference."
            ],
        })

    if valid_bands:

        warnings.append(
            "SIMBAD magnitudes are included as magnitude-only "
            "measurements; they are excluded from colours and the "
            "flux-based SED because their individual systems, "
            "epochs, uncertainties, and references are unavailable "
            "in the current query."
        )

    return valid_bands


def build_photometric_validation(catalogue_results):
    """
    Build an SED-ready assessment from accepted catalogue associations.
    """

    catalogue_results = catalogue_results or {}

    measurements = []
    sed_points = []
    upper_limits = []

    colours = {}
    warnings = []
    excluded = []

    # ---------------------------------------------------------
    # Gaia
    # ---------------------------------------------------------

    gaia = catalogue_results.get("gaia")

    if accepted_match("gaia", gaia):

        gaia_photometry = validate_gaia(
            gaia["nearest_source"],
            measurements,
            sed_points,
            upper_limits,
            warnings,
        )

        colour = calculate_colour(
            "BP-RP",
            gaia_photometry.get("BP"),
            gaia_photometry.get("RP"),
            "BP",
            "RP",
        )

        if colour:
            colours["BP-RP"] = colour

    else:

        excluded.append(
            "Gaia photometry was not included because no accepted "
            "Gaia positional association was available."
        )

    # ---------------------------------------------------------
    # 2MASS
    # ---------------------------------------------------------

    twomass = catalogue_results.get("2mass")

    if accepted_match("2mass", twomass):

        two_photometry = validate_2mass(
            twomass["nearest_source"],
            measurements,
            sed_points,
            upper_limits,
            warnings,
        )

        colour_definitions = [
            ("J-H", "J", "H", "J", "H"),
            ("H-Ks", "H", "Ks", "H", "Ks"),
        ]

        for name, first, second, first_band, second_band in colour_definitions:

            colour = calculate_colour(
                name,
                two_photometry.get(first),
                two_photometry.get(second),
                first_band,
                second_band,
            )

            if colour:
                colours[name] = colour

    else:

        excluded.append(
            "2MASS photometry was excluded because no accepted "
            "epoch-compatible positional association was available."
        )

    # ---------------------------------------------------------
    # AllWISE
    # ---------------------------------------------------------

    allwise = catalogue_results.get("allwise")

    if accepted_match("allwise", allwise):

        wise_photometry = validate_allwise(
            allwise["nearest_source"],
            measurements,
            sed_points,
            upper_limits,
            warnings,
        )

        colour = calculate_colour(
            "W1-W2",
            wise_photometry.get("W1"),
            wise_photometry.get("W2"),
            "W1",
            "W2",
        )

        if colour:
            colours["W1-W2"] = colour

    else:

        excluded.append(
            "AllWISE photometry was excluded because no accepted "
            "epoch-compatible positional association was available."
        )

    # ---------------------------------------------------------
    # SIMBAD
    # ---------------------------------------------------------

    simbad = catalogue_results.get("simbad")

    if accepted_match("simbad", simbad):

        validate_simbad(
            simbad["nearest_source"],
            measurements,
            warnings,
        )

    else:

        excluded.append(
            "SIMBAD magnitudes were excluded because no accepted "
            "SIMBAD positional association was available."
        )

    # ---------------------------------------------------------
    # Overall status
    # ---------------------------------------------------------

    if not measurements:

        status = "no_usable_photometry"

    elif warnings or excluded or upper_limits:

        status = "quality_limited"

    else:

        status = "usable"

    # ---------------------------------------------------------
    # Return
    # ---------------------------------------------------------

    return {
        "status": status,

        "measurements": measurements,

        "colours": colours,

        "sed": {
            "points": sorted(
                sed_points,
                key=lambda point: point["wavelength_um"],
            ),

            "upper_limits": sorted(
                upper_limits,
                key=lambda point: point["wavelength_um"],
            ),
        },

        "quality_flags": warnings,
        "warnings": warnings,

        "excluded_catalogues": excluded,

        "metadata": {
            "flux_unit": "mJy",

            "gaia_flux_convention": GAIA_FLUX_CONVENTION,

            "gaia_magnitude_system": GAIA_MAGNITUDE_SYSTEM,

            "gaia_magnitude_uncertainty_method": (
                GAIA_MAGNITUDE_ERROR_METHOD
            ),

            "simbad_photometry_policy": (
                "Magnitude-only; no flux conversion, colours, "
                "or SED points without band-specific system, "
                "epoch, uncertainty, and reference metadata."
            ),
        },

        "notes": [
            "Only accepted positional associations are included.",

            "Upper limits are kept separate from detections.",

            "Photometry from different catalogues may have been "
            "collected at different epochs.",

            "Gaia magnitudes are in the Gaia Vega system; Gaia flux "
            "densities are AB-equivalent flux densities.",

            "Gaia magnitude uncertainties derived from flux errors "
            "are approximations, not official catalogue magnitude errors.",

            "Potentially spurious AllWISE measurements are retained "
            "in measurements but excluded from colours and SED points.",

            "SIMBAD allfluxes magnitudes are retained as magnitude-only "
            "measurements because the current query does not return "
            "per-band system, epoch, uncertainty, or bibliographic reference.",

            "SIMBAD magnitudes are not converted into fluxes or "
            "included in the flux-based SED.",

            "Flux points are observed measurements, not corrected "
            "for extinction or converted into a stellar spectrum.",
        ],
    }
