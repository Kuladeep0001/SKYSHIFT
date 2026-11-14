"""
NASA Exoplanet Archive host-star crossmatching.

Matching priority:
1. Exact Gaia DR3 identifier match.
2. Positional cone search if identifier matching is unavailable
   or returns no records.

The positional search radius is 10 arcseconds.
Matches within 3 arcseconds are accepted.
Matches between 3 and 10 arcseconds are potential associations.
"""

import math
import re

import httpx


TAP_URL = "https://exoplanetarchive.ipac.caltech.edu/TAP/sync"

MATCH_RADIUS_ARCSEC = 3.0
SEARCH_RADIUS_ARCSEC = 10.0
REQUEST_TIMEOUT_SECONDS = 30.0


COLUMNS = [
    "pl_name",
    "hostname",
    "gaia_dr3_id",
    "hip_name",
    "tic_id",
    "ra",
    "dec",
    "pl_orbper",
    "pl_rade",
    "pl_bmassj",
    "pl_orbsmax",
    "pl_eqt",
    "discoverymethod",
    "disc_year",
    "disc_facility",
    "sy_snum",
    "sy_pnum",
    "st_teff",
    "st_mass",
    "st_rad",
]


def safe_float(value):
    """Convert a value to a finite float, or return None."""

    try:
        if value is None or value == "":
            return None

        number = float(value)

        return number if math.isfinite(number) else None

    except (TypeError, ValueError):
        return None


def normalise_gaia_dr3_id(value):
    """
    Extract the numeric Gaia DR3 source ID.

    Accepts:
        2127941757262806656
        "2127941757262806656"
        "Gaia DR3 2127941757262806656"

    Returns None for values that cannot be recognised safely.
    """

    if value is None:
        return None

    text = str(value).strip()

    if text.isdigit():
        return text

    match = re.fullmatch(
        r"Gaia\s+DR3\s+(\d+)",
        text,
        flags=re.IGNORECASE,
    )

    if match:
        return match.group(1)

    return None


def angular_separation_arcsec(ra1, dec1, ra2, dec2):
    """Calculate great-circle angular separation in arcseconds."""

    radians = math.pi / 180.0

    ra1, dec1, ra2, dec2 = [
        value * radians
        for value in (ra1, dec1, ra2, dec2)
    ]

    delta_ra = ra2 - ra1
    delta_dec = dec2 - dec1

    a = (
        math.sin(delta_dec / 2.0) ** 2
        + math.cos(dec1)
        * math.cos(dec2)
        * math.sin(delta_ra / 2.0) ** 2
    )

    a = min(1.0, max(0.0, a))

    angle = 2.0 * math.asin(math.sqrt(a))

    return angle * (180.0 / math.pi) * 3600.0


def parse_tap_json(payload):
    """
    Parse NASA Exoplanet Archive TAP JSON responses.

    The standard response is a list of row dictionaries.
    An empty list means that the query returned no records.

    A metadata/data dictionary response is also supported.
    """

    if isinstance(payload, list):

        if not payload:
            return []

        if not all(isinstance(row, dict) for row in payload):
            raise ValueError(
                "TAP returned a list containing unexpected row types. "
                f"Response preview: {str(payload)[:1000]}"
            )

        return payload

    if isinstance(payload, dict):

        metadata = payload.get("metadata")
        data = payload.get("data")

        if not isinstance(metadata, list) or not isinstance(data, list):
            raise ValueError(
                "Unexpected TAP JSON dictionary structure. "
                f"Response keys: {list(payload.keys())}. "
                f"Response preview: {str(payload)[:1000]}"
            )

        column_names = [
            column.get("name")
            for column in metadata
        ]

        if not column_names or any(
            not name for name in column_names
        ):
            raise ValueError("Could not read TAP column names.")

        return [
            {
                name: row[index] if index < len(row) else None
                for index, name in enumerate(column_names)
            }
            for row in data
        ]

    raise ValueError(
        "Unexpected TAP JSON response type: "
        f"{type(payload).__name__}. "
        f"Response preview: {str(payload)[:1000]}"
    )


async def tap_query(client, adql):
    """Execute an ADQL query against the NASA Exoplanet Archive."""

    adql = " ".join(adql.split())

    response = await client.post(
        TAP_URL,
        data={
            "query": adql,
            "format": "json",
        },
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    if response.is_error:
        raise RuntimeError(
            f"Archive HTTP {response.status_code}: "
            f"{response.text[:2000]}"
        )

    try:
        payload = response.json()
    except ValueError as error:
        raise RuntimeError(
            "Exoplanet Archive returned a non-JSON response: "
            f"{response.text[:1000]}"
        ) from error

    return parse_tap_json(payload)


def normalise_planet(row, separation_arcsec=None):
    """Convert an Archive row into the API response structure."""

    return {
        "planet_name": row.get("pl_name"),

        "host_name": row.get("hostname"),

        "host_identifiers": {
            "gaia_dr3_id": row.get("gaia_dr3_id"),
            "hip_name": row.get("hip_name"),
            "tic_id": row.get("tic_id"),
        },

        "host_position": {
            "ra_deg": safe_float(row.get("ra")),
            "dec_deg": safe_float(row.get("dec")),
            "separation_arcsec": separation_arcsec,
        },

        "planet_parameters": {
            "orbital_period_days": safe_float(
                row.get("pl_orbper")
            ),

            "radius_earth_radii": safe_float(
                row.get("pl_rade")
            ),

            "mass_jupiter_masses": safe_float(
                row.get("pl_bmassj")
            ),

            "semi_major_axis_au": safe_float(
                row.get("pl_orbsmax")
            ),

            "equilibrium_temperature_k": safe_float(
                row.get("pl_eqt")
            ),
        },

        "discovery": {
            "method": row.get("discoverymethod"),
            "year": row.get("disc_year"),
            "facility": row.get("disc_facility"),
        },


        "system": {
            "number_of_stars": row.get("sy_snum"),
            "number_of_confirmed_planets": row.get("sy_pnum"),
        },

        "host_star": {
            "effective_temperature_k": safe_float(
                row.get("st_teff")
            ),

            "mass_solar_masses": safe_float(
                row.get("st_mass")
            ),

            "radius_solar_radii": safe_float(
                row.get("st_rad")
            ),
        },
    }


def build_query_position(
    ra,
    dec,
    position_source,
    position_epoch,
):
    """Describe the coordinates used for the Archive search."""

    return {
        "ra_deg": ra,
        "dec_deg": dec,
        "source": position_source,
        "epoch": position_epoch,
    }


def empty_result(
    status,
    message,
    method=None,
    query_position=None,
    warnings=None,
):
    """Return a consistent response when no planet records are available."""

    result = {
        "status": status,
        "association_method": method,

        "match_radius_arcsec": MATCH_RADIUS_ARCSEC,
        "search_radius_arcsec": SEARCH_RADIUS_ARCSEC,

        "separation_arcsec": None,

        "host_name": None,
        "host_names": [],

        "planet_count": 0,
        "planets": [],

        "message": message,

        "archive": "NASA Exoplanet Archive",
        "table": "pscomppars",

        "data_url": (
            "https://exoplanetarchive.ipac.caltech.edu/"
        ),
    }

    if query_position is not None:
        result["query_position"] = query_position

    if warnings:
        result["warnings"] = warnings

    return result


async def exoplanet_host_match(
    ra,
    dec,
    gaia_dr3_id=None,
    position_source="candidate_input",
    position_epoch=None,
):
    """
    Check whether a candidate is a known exoplanet host.

    Parameters
    ----------
    ra, dec:
        Candidate coordinates in decimal degrees.

    gaia_dr3_id:
        Optional Gaia DR3 source ID. May be supplied as a numeric
        string or as "Gaia DR3 <source_id>".

    position_source:
        Description of the origin of the supplied coordinates.
        For example: "gaia_propagated_position".

    position_epoch:
        Epoch associated with the supplied coordinates.

    Matching priority
    -----------------
    1. Exact Gaia DR3 identifier match.
    2. Positional search within 10 arcseconds.

    Positional matches within 3 arcseconds are accepted.
    Matches between 3 and 10 arcseconds are potential associations.
    """

    ra = safe_float(ra)
    dec = safe_float(dec)

    if (
        ra is None
        or dec is None
        or not 0 <= ra < 360
        or not -90 <= dec <= 90
    ):
        return empty_result(
            "not_checked",
            "Valid candidate coordinates were unavailable.",
        )

    query_position = build_query_position(
        ra=ra,
        dec=dec,
        position_source=position_source,
        position_epoch=position_epoch,
    )

    columns = ", ".join(COLUMNS)

    rows = []
    association_method = None
    warnings = []

    clean_id = normalise_gaia_dr3_id(gaia_dr3_id)

    async with httpx.AsyncClient() as client:

        # -----------------------------------------------------
        # 1. Exact Gaia DR3 identifier search
        # -----------------------------------------------------

        if clean_id is not None:

            # The Archive stores Gaia identifiers in the form
            # "Gaia DR3 2127941757262806656".
            #
            # Use exact equality rather than LIKE. The wildcard
            # query caused URL-encoding errors in the TAP request.

            adql = (
                f"SELECT {columns} "
                f"FROM pscomppars "
                f"WHERE gaia_dr3_id = 'Gaia DR3 {clean_id}'"
            )

            try:
                identifier_rows = await tap_query(
                    client,
                    adql,
                )

                # Verify the identifier after retrieval as well.
                rows = [
                    row
                    for row in identifier_rows
                    if normalise_gaia_dr3_id(
                        row.get("gaia_dr3_id")
                    ) == clean_id
                ]

                if rows:
                    association_method = "gaia_dr3_identifier"

            except (
                httpx.HTTPError,
                RuntimeError,
                ValueError,
            ) as error:

                # An identifier-query failure should not prevent
                # the positional search from being attempted.
                warnings.append(
                    "The Gaia DR3 identifier query failed; "
                    "a positional search was attempted instead. "
                    f"Identifier query error: {str(error)}"
                )

        # -----------------------------------------------------
        # 2. Positional cone search
        # -----------------------------------------------------

        if not rows:

            radius_deg = SEARCH_RADIUS_ARCSEC / 3600.0

            adql = (
                f"SELECT {columns} "
                f"FROM pscomppars "
                f"WHERE CONTAINS("
                f"POINT('ICRS', ra, dec), "
                f"CIRCLE('ICRS', {ra}, {dec}, {radius_deg})"
                f") = 1"
            )

            try:
                rows = await tap_query(
                    client,
                    adql,
                )

                association_method = "positional"

            except (
                httpx.HTTPError,
                RuntimeError,
                ValueError,
            ) as error:

                return empty_result(
                    "inconclusive",
                    (
                        "NASA Exoplanet Archive positional query "
                        f"failed: {str(error)}"
                    ),
                    method="positional",
                    query_position=query_position,
                    warnings=warnings,
                )

    # ---------------------------------------------------------
    # 3. No records
    # ---------------------------------------------------------

    if not rows:

        return empty_result(
            "no_match",
            (
                "No known exoplanet host was found by Gaia DR3 "
                "identifier or in the queried positional region."
            ),
            method=association_method,
            query_position=query_position,
            warnings=warnings,
        )

    # ---------------------------------------------------------
    # 4. Calculate positional separations
    # ---------------------------------------------------------

    prepared = []

    for row in rows:

        host_ra = safe_float(row.get("ra"))
        host_dec = safe_float(row.get("dec"))

        if host_ra is None or host_dec is None:
            continue

        separation = angular_separation_arcsec(
            ra,
            dec,
            host_ra,
            host_dec,
        )

        prepared.append((separation, row))

    if not prepared:

        return empty_result(
            "inconclusive",
            (
                "The Archive returned rows, but usable host "
                "coordinates were unavailable."
            ),
            method=association_method,
            query_position=query_position,
            warnings=warnings,
        )

    # ---------------------------------------------------------
    # 5. Verify identifier association
    # ---------------------------------------------------------

    if association_method == "gaia_dr3_identifier":

        prepared = [
            item
            for item in prepared
            if normalise_gaia_dr3_id(
                item[1].get("gaia_dr3_id")
            ) == clean_id
        ]

        if not prepared:

            return empty_result(
                "inconclusive",
                (
                    "The Archive returned rows, but none retained "
                    "the requested Gaia DR3 identifier."
                ),
                method=association_method,
                query_position=query_position,
                warnings=warnings,
            )

    prepared.sort(key=lambda item: item[0])

    closest_separation = prepared[0][0]

    # ---------------------------------------------------------
    # 6. Determine association confidence
    # ---------------------------------------------------------

    if association_method == "gaia_dr3_identifier":

        status = "match_found"

        message = (
            "The candidate's accepted Gaia DR3 identifier "
            "matches a host identifier in the NASA Exoplanet Archive."
        )

    elif closest_separation <= MATCH_RADIUS_ARCSEC:

        status = "match_found"

        message = (
            "A known exoplanet host was found within the positional "
            "matching radius. This is a positional association, "
            "not an independent Gaia identifier confirmation."
        )

    else:

        status = "potential_association"

        message = (
            "A known exoplanet host was found within the wider "
            "search region, but it is outside the accepted "
            "matching radius."
        )

    # ---------------------------------------------------------
    # 7. Format planet records
    # ---------------------------------------------------------

    planets = [
        normalise_planet(row, separation)
        for separation, row in prepared
    ]

    host_names = sorted({
        row.get("hostname")
        for _, row in prepared
        if row.get("hostname")
    })

    return {
        "status": status,

        "association_method": association_method,

        "match_radius_arcsec": MATCH_RADIUS_ARCSEC,
        "search_radius_arcsec": SEARCH_RADIUS_ARCSEC,

        "separation_arcsec": round(
            closest_separation,
            4,
        ),

        "host_name": (
            host_names[0]
            if len(host_names) == 1
            else None
        ),

        "host_names": host_names,

        "planet_count": len(planets),
        "planets": planets,

        "message": message,

        "archive": "NASA Exoplanet Archive",
        "table": "pscomppars",

        "data_url": (
            "https://exoplanetarchive.ipac.caltech.edu/"
        ),

        "query_position": query_position,

        "warnings": warnings,
    }