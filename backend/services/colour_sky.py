"""SPHEREx colour sky: a false-colour all-sky map mixed on the fly from IRSA's SPHEREx DR1 HiPS cube.

IRSA publishes the whole sky in all 102 SPHEREx colours as HiPS tiles (one greyscale PNG per colour).
We pick a few colours, mix them into an RGB picture (like NASA's SPHEREx all-sky image), and serve the
result as a normal HiPS that Aladin Lite can show. Infrared is invisible, so the colours are assigned:

  dust      (glowing organic molecules, PAH, 3.29 µm)   -> orange-red
  hot gas   (hydrogen Brackett-alpha 4.05 µm, starlight removed) -> cyan
  starlight (1.0 µm and 1.6 µm)                         -> white / blue
Owner: Feature developer 1.
"""
from __future__ import annotations

import hashlib
import io
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image

from .spherex import CACHE, SESSION

SRC = "https://irsa.ipac.caltech.edu/data/hips/SPHEREx/spherex_allsky_cube"
OUT = CACHE / "colour_sky"
OUT.mkdir(parents=True, exist_ok=True)
POOL = ThreadPoolExecutor(max_workers=16)  # each RGB tile needs 8 IRSA tiles

# wavelengths of the 102 frames (from the HiPS properties); frame number = index + 1
WAVES = [0.753, 0.771, 0.790, 0.809, 0.828, 0.848, 0.868, 0.889, 0.910, 0.932, 0.955, 0.978, 1.001, 1.025, 1.050, 1.075,
         1.102, 1.113, 1.139, 1.167, 1.195, 1.224, 1.254, 1.284, 1.315, 1.346, 1.378, 1.412, 1.446, 1.481, 1.517, 1.554,
         1.592, 1.631, 1.656, 1.695, 1.735, 1.775, 1.818, 1.861, 1.905, 1.949, 1.995, 2.041, 2.089, 2.139, 2.189, 2.240,
         2.292, 2.345, 2.399, 2.445, 2.506, 2.575, 2.646, 2.719, 2.794, 2.871, 2.951, 3.033, 3.118, 3.204, 3.293, 3.383,
         3.476, 3.570, 3.667, 3.768, 3.833, 3.867, 3.901, 3.935, 3.970, 4.005, 4.040, 4.076, 4.112, 4.148, 4.184, 4.220,
         4.257, 4.294, 4.331, 4.368, 4.405, 4.435, 4.467, 4.500, 4.533, 4.566, 4.600, 4.635, 4.669, 4.704, 4.739, 4.773,
         4.808, 4.843, 4.879, 4.915, 4.951, 4.988]


def frame(um: float) -> int:
    return int(np.argmin([abs(w - um) for w in WAVES])) + 1


LAYERS = {"blue": frame(1.001), "stars": frame(1.592), "pah": frame(3.293), "pah_lo": frame(3.033), "pah_hi": frame(3.570),
          "bra": frame(4.040), "bra_lo": frame(3.935), "bra_hi": frame(4.148)}


def _fetch(rel: str, f: int) -> np.ndarray | None:
    """One greyscale tile (0-1) of frame f, cached."""
    path = OUT / "src" / f"{rel.replace('/', '_')}_{f}.png"
    if not path.exists():
        for attempt in range(3):  # IRSA sometimes answers "busy": wait a moment and try again
            r = SESSION.get(f"{SRC}/{rel}_{f}.png", timeout=60)
            if r.status_code == 200 or r.status_code == 404:
                break
            time.sleep(1 + 2 * attempt)
        if r.status_code != 200:
            return None
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(r.content)
    with Image.open(path) as im:
        a = np.asarray(im.convert("L" if im.mode != "LA" else "LA"), dtype=np.float32)
    return (a[..., 0] if a.ndim == 3 else a) / 255.0


def mix(t: dict[str, np.ndarray]) -> np.ndarray:
    """The colour recipe. Inputs are IRSA's display-stretched (asinh) greyscale tiles, 0-1."""
    stars = 0.5 * t["stars"] + 0.5 * t["blue"]
    # emission above the neighbouring colours = glowing dust / glowing gas (not starlight)
    dust = np.clip(t["pah"] - 0.5 * (t["pah_lo"] + t["pah_hi"]), 0, None) * 4.5 + 0.9 * t["pah"]
    gas = np.clip(t["bra"] - 0.5 * (t["bra_lo"] + t["bra_hi"]), 0, None) * 6.0
    r = 1.30 * dust + 0.50 * stars + 0.05 * gas
    g = 0.52 * dust + 0.55 * stars + 0.85 * gas
    b = 0.16 * dust + 0.72 * stars + 1.05 * gas
    rgb = np.stack([r, g, b], axis=-1)
    rgb = 1 - np.exp(-1.6 * rgb)  # soft shoulder: bright parts stay light, not clipped flat
    return (np.clip(rgb, 0, 1) * 255).astype(np.uint8)


def tile(rel: str) -> bytes | None:
    """RGB PNG for a HiPS path like 'Norder5/Dir0/Npix1234' or 'Norder3/Allsky' (cached)."""
    key = hashlib.sha1(rel.encode()).hexdigest()[:16]
    out = OUT / "rgb" / f"{key}.png"
    if out.exists():
        return out.read_bytes()
    futs = {name: POOL.submit(_fetch, rel, f) for name, f in LAYERS.items()}
    t = {name: fu.result() for name, fu in futs.items()}
    if any(v is None for v in t.values()):
        return None
    shape = min(v.shape for v in t.values())
    t = {k: v[: shape[0], : shape[1]] for k, v in t.items()}
    buf = io.BytesIO()
    Image.fromarray(mix(t), "RGB").save(buf, format="PNG", optimize=False)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(buf.getvalue())
    return buf.getvalue()


PROPERTIES = """creator_did          = ivo://SkyShift/P/SPHEREx/DR1/colour
obs_title            = SPHEREx colour sky (SkyShift mix of IRSA's SPHEREx DR1 all-sky cube)
obs_description      = False colour: orange-red = glowing dust (PAH 3.29 um), cyan = hot hydrogen gas (Br-alpha 4.05 um), white/blue = starlight (1.0-1.6 um)
obs_copyright        = NASA/SPHEREx, Caltech/IPAC
hips_version         = 1.4
hips_frame           = equatorial
hips_order           = 5
hips_order_min       = 0
hips_tile_width      = 512
hips_tile_format     = png
dataproduct_type     = image
hips_initial_fov     = 180
hips_initial_ra      = 266.4
hips_initial_dec     = -28.9
moc_sky_fraction     = 1.0
em_min               = 1.0e-06
em_max               = 4.2e-06
"""
