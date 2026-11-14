"""Request/response shapes shared by the API and documented in API_DOCUMENTATION.md.

Keep these in sync with the docs: the frontend team builds against them.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


# ------------------------------------------------------------------ images ---
class ImageQuery(BaseModel):
    ra: float = Field(..., ge=0, lt=360, description="Right Ascension in degrees")
    dec: float = Field(..., ge=-90, le=90, description="Declination in degrees")
    fov: float = Field(6.0, ge=2, le=20, description="Field of view in arcminutes")
    bands: list[int] = Field(default_factory=list,
                             description="Detector arrays 1-6 to list images for (empty = all six stacked together)")
    release: Optional[list[str]] = Field(None, description="SPHEREx releases, e.g. ['spherex_dr1']. Default: newest")


class Progress(BaseModel):
    done: int = 0
    total: int = 0
    failed: int = 0


class ImageInfo(BaseModel):
    id: str
    epoch: str
    date_range: list[str]
    band: int
    visit: int
    n_exposures: int
    wavelength_um: Optional[float] = None
    image_url: str


class ImageQueryResponse(BaseModel):
    status: Literal["pending", "success", "error"]
    query_id: str
    message: str = ""
    progress: Progress = Progress()
    images: list[ImageInfo] = []


class CompareRequest(BaseModel):
    query_id: str
    epoch_a: Optional[int] = Field(None, description="Visit number to compare from (default: first)")
    epoch_b: Optional[int] = Field(None, description="Visit number to compare to (default: last)")
    band: int = Field(0, ge=0, le=6, description="0 = all detectors stacked, 1-6 = one detector")
    op: Literal["subtract", "add"] = "subtract"


class CompareResponse(BaseModel):
    status: Literal["success"]
    query_id: str
    op: str
    band: int
    epoch_a: dict
    epoch_b: dict
    image_url: str
    explanation: str


# --------------------------------------------------------------- analysis ---
class DetectionRequest(BaseModel):
    query_id: str
    band: int = Field(0, ge=0, le=6, description="0 = all detectors stacked; 5/6 are best for cold brown dwarfs")
    threshold: float = Field(5.0, ge=3, le=50, description="How many noise-sigmas a change must stand out by")
    include_transients: bool = Field(False, description="Also look for one-off spots (possible asteroids). Noisy.")


class Candidate(BaseModel):
    candidate_id: str
    ra: float
    dec: float
    epoch: Optional[str] = None
    mjd: Optional[float] = None
    kind: Optional[str] = Field(None, description="mover | variable | appeared | vanished | transient")
    x: Optional[float] = None
    y: Optional[float] = None
    snr: Optional[float] = None
    score: Optional[float] = None
    saturated: Optional[bool] = None
    motion: Optional[dict] = None
    flux_change: Optional[dict] = None
    plain_english: Optional[str] = None

    model_config = {"extra": "allow"}


class DetectionResponse(BaseModel):
    status: Literal["success"]
    query_id: str
    band: int
    candidates: list[Candidate]
    note: str = ""


# ----------------------------------------------------------- verification ---
class VerificationRequest(BaseModel):
    """Either one candidate (fields at the top level, as in the team doc) or a list of them."""
    candidate_id: Optional[str] = None
    ra: Optional[float] = None
    dec: Optional[float] = None
    epoch: Optional[str] = None
    kind: Optional[str] = None
    motion: Optional[dict] = None
    candidates: Optional[list[Candidate]] = None
    radius_arcsec: float = Field(12.0, gt=0, le=60)


class VerificationResult(BaseModel):
    candidate_id: str
    matches: list[dict]
    verification_status: Literal["known_mover", "known_star", "known_asteroid", "unmatched", "pending"]
    plain_english: str = ""
