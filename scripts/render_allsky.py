"""Render the SPHEREx colour sky as one oval (Mollweide) picture of the whole sky, in galactic coordinates
(the Milky Way runs across the middle), like NASA's SPHEREx all-sky image.

    python -m scripts.render_allsky                      -> frontend/public/spherex_allsky.jpg
    python -m scripts.render_allsky --width 1200 --variant 0 --out test.png

Uses the low-resolution "Allsky" tile sheet of the SkyShift colour mix (backend/services/colour_sky.py).
"""
import argparse
import io
from pathlib import Path

import numpy as np
from astropy import units as u
from astropy.coordinates import SkyCoord
from astropy_healpix import HEALPix
from PIL import Image

from backend.services import colour_sky

ORDER, TILE = 3, 64          # Allsky sheet: order-3 tiles, 64 x 64 px each
SUB = 6                      # 64 = 2^6 -> pixels inside a tile are HEALPix order 3 + 6 = 9


def _compact(v):
    v = v & 0x5555
    v = (v | (v >> 1)) & 0x3333
    v = (v | (v >> 2)) & 0x0F0F
    v = (v | (v >> 4)) & 0x00FF
    return v


def render(width: int = 1800, variant: int = 3) -> Image.Image:
    sheet = np.asarray(Image.open(io.BytesIO(colour_sky.tile(f"Norder{ORDER}/Allsky"))).convert("RGB"))
    per_row = sheet.shape[1] // TILE
    h = width // 2
    yy, xx = np.mgrid[0:h, 0:width].astype(np.float64)
    # inverse Mollweide (unit ellipse: x in [-2, 2], y in [-1, 1])
    X = (xx + 0.5) / width * 4 - 2
    Y = 1 - (yy + 0.5) / h * 2
    inside = (X / 2) ** 2 + Y ** 2 <= 1
    th = np.arcsin(np.clip(Y, -1, 1))
    lat = np.arcsin(np.clip((2 * th + np.sin(2 * th)) / np.pi, -1, 1))
    lon = -np.pi * X / (2 * np.cos(th) + 1e-12)          # galactic longitude increases to the LEFT
    lon, lat = lon[inside], lat[inside]
    c = SkyCoord(l=lon * u.rad, b=lat * u.rad, frame="galactic").icrs
    hp = HEALPix(nside=2 ** (ORDER + SUB), order="nested")
    idx = hp.lonlat_to_healpix(c.ra, c.dec).astype(np.int64)
    tile = idx >> (2 * SUB)
    sub = idx & ((1 << (2 * SUB)) - 1)
    a, b = _compact(sub), _compact(sub >> 1)
    col, row = [(a, TILE - 1 - b), (b, TILE - 1 - a), (a, b), (b, a)][variant]
    py = (tile // per_row) * TILE + row
    px = (tile % per_row) * TILE + col
    out = np.zeros((h, width, 3), np.uint8)
    out[inside] = sheet[np.clip(py, 0, sheet.shape[0] - 1), np.clip(px, 0, sheet.shape[1] - 1)]
    return Image.fromarray(out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--width", type=int, default=1800)
    ap.add_argument("--variant", type=int, default=3)  # 3 = correct HiPS tile orientation
    ap.add_argument("--out", default=str(Path(__file__).resolve().parents[1] / "frontend" / "public" / "spherex_allsky.jpg"))
    a = ap.parse_args()
    img = render(a.width, a.variant)
    img.save(a.out, quality=90)
    print("saved", a.out, img.size)
