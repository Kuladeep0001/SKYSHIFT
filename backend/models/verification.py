from datetime import datetime
from typing import List, Literal, Optional
from pydantic import BaseModel, Field, field_validator

CatalogueName = Literal["gaia", "allwise", "2mass", "simbad"]


class CandidateInput(BaseModel):
    candidate_id: str
    ra: float = Field(ge=0, lt=360)
    dec: float = Field(ge=-90, le=90)
    observation_time: datetime
    # Optional proper motion of the candidate (mas/yr, pmra = mu_alpha*cos(dec)).
    # Used for epoch-aware 2MASS/AllWISE matching when Gaia has no match,
    # e.g. for brown dwarfs too faint for Gaia such as WISE 0855.
    pmra_mas_yr: Optional[float] = Field(default=None, ge=-20000, le=20000)
    pmdec_mas_yr: Optional[float] = Field(default=None, ge=-20000, le=20000)

    @field_validator("observation_time")
    @classmethod
    def timestamp_must_have_timezone(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(
                "observation_time must include a timezone, preferably UTC"
            )
        return value


class VerificationRequest(BaseModel):
    candidates: List[CandidateInput] = Field(min_length=1, max_length=10)
    catalogues: List[CatalogueName] = Field(
        default=["gaia", "allwise", "2mass", "simbad"]
    )
    search_radius_arcsec: float = Field(
        default=3.0,
        gt=0,
        le=60
    )


class CatalogueResult(BaseModel):
    status: Literal[
        "match_found",
        "no_match",
        "inconclusive",
        "not_checked"
    ]
    source_id: Optional[str] = None
    separation_arcsec: Optional[float] = None
    details: dict = Field(default_factory=dict)


class CandidateVerificationResult(BaseModel):
    candidate_id: str
    catalogue_results: dict
    assessment: str
    evidence_summary: dict = Field(default_factory=dict)
    cross_catalogue_association: dict = Field(default_factory=dict)
    photometric_assessment: dict = Field(default_factory=dict)
    object_profile: dict = Field(default_factory=dict)
    exoplanet_association: dict = Field(default_factory=dict)
    

class VerificationResponse(BaseModel):
    results: List[CandidateVerificationResult]