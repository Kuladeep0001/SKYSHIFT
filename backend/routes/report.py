"""Technical report (PDF) for a loaded spot: GET /api/images/{query_id}/report.pdf. Owner: Integration lead."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response

from ..services import report
from .images import ready_or_409

router = APIRouter(tags=["report"])


@router.get("/api/images/{query_id}/report.pdf")
def technical_report(request: Request, query_id: str, x: Optional[int] = None, y: Optional[int] = None,
                     band: int = Query(0, ge=0, le=7), label: Optional[str] = Query(None, max_length=120),
                     pmra: Optional[float] = None, pmdec: Optional[float] = None, external: bool = True,
                     download: bool = False):
    """A technical report on this spot for researchers: data, processing, images, detections with motion fits,
    identification of the object of interest (Gaia DR3, 2MASS, AllWISE, SIMBAD, NASA Exoplanet Archive),
    its spectrum and light curve, method validation, references, and appendices (all channels, every
    exposure, quality flags). `x`, `y` = the object's pixel (default: the field centre).
    Takes 10-60 s when outside archives are queried (`external=false` skips them)."""
    job = ready_or_409(query_id)
    n = job.arrays["flux"].shape[-1]
    if (x is None) != (y is None) or (x is not None and not (0 <= x < n and 0 <= y < n)):
        raise HTTPException(400, {"status": "error", "error": "bad_request", "message": f"x and y must both be given, 0-{n - 1}"})
    pm = (pmra, pmdec) if pmra is not None and pmdec is not None else None
    pdf, number = report.build(job, x, y, band, label, pm, site=str(request.base_url), external=external)
    disp = "attachment" if download else "inline"
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'{disp}; filename="{number}.pdf"', "X-Report-Number": number})
