"""Serves the SPHEREx colour sky as a HiPS (tiles for Aladin Lite). Owner: Feature developer 1."""
from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse, Response

from ..services import colour_sky

router = APIRouter(prefix="/hips/spherex-colour", tags=["colour sky"])
CACHE_HDR = {"Cache-Control": "public, max-age=604800"}


@router.get("/properties", response_class=PlainTextResponse)
def properties():
    return PlainTextResponse(colour_sky.PROPERTIES, headers=CACHE_HDR)


def _full_sky_moc() -> bytes:
    """MOC (sky coverage) file saying "the whole sky": the 12 order-0 HEALPix cells.
    Aladin uses it to decide which tiles exist; without one it drew only a single tile."""
    import io

    import numpy as np
    from astropy.io import fits

    col = fits.Column(name="UNIQ", format="J", array=np.arange(4, 16, dtype=np.int32))
    hdu = fits.BinTableHDU.from_columns([col])
    hdu.header.update(PIXTYPE="HEALPIX", ORDERING="NUNIQ", COORDSYS="C", MOCORDER=0, MOCORD_S=0,
                      MOCDIM="SPACE", MOCVERS="2.0", MOCTOOL="SkyShift", MOCTYPE="IMAGE")
    buf = io.BytesIO()
    fits.HDUList([fits.PrimaryHDU(), hdu]).writeto(buf)
    return buf.getvalue()


_MOC = None


@router.get("/Moc.fits")
def moc():
    global _MOC
    _MOC = _MOC or _full_sky_moc()
    return Response(_MOC, media_type="application/fits", headers=CACHE_HDR)


@router.get("/Norder{order}/Allsky.png")
def allsky(order: int):
    if not 0 <= order <= 3:
        raise HTTPException(404)
    png = colour_sky.tile(f"Norder{order}/Allsky")
    if png is None:
        raise HTTPException(404)
    return Response(png, media_type="image/png", headers=CACHE_HDR)


@router.get("/Norder{order}/Dir{d}/{name}")
def tile(order: int, d: int, name: str):
    m = re.fullmatch(r"Npix(\d+)\.png", name)
    if not m or not 0 <= order <= 5:
        raise HTTPException(404)
    png = colour_sky.tile(f"Norder{order}/Dir{d}/Npix{m.group(1)}")
    if png is None:
        raise HTTPException(404)
    return Response(png, media_type="image/png", headers=CACHE_HDR)
