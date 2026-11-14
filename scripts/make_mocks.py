"""Save real API responses as mock JSON so the UI team can work without the backend.

    python -m scripts.make_mocks           # needs Barnard's Star cached (python -m scripts.prewarm)

Writes frontend/public/mock/*.json (open the site with ?mock=1 to use them) and copies a few small
FITS cutouts into sample_data/fits/ for backend developers.
"""
import json
import shutil
from pathlib import Path

from fastapi.testclient import TestClient

from backend.main import app
from backend.services import jobs, resolver

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "frontend" / "public" / "mock"
FITS_OUT = ROOT / "sample_data" / "fits"


def save(name, data):
    (OUT / f"{name}.json").write_text(json.dumps(data, separators=(",", ":")))
    print(f"  {name}.json  {(OUT / f'{name}.json').stat().st_size // 1024} KB")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    c = TestClient(app)
    t = resolver.resolve("Barnard's Star")
    save("resolve", t)
    save("releases", c.get("/api/releases").json())
    q = c.post("/api/images/query", json={"ra": t["ra"], "dec": t["dec"], "fov": 6}).json()
    assert q["status"] == "success", "Run `python -m scripts.prewarm` first so Barnard's Star is cached."
    qid = q["query_id"]
    save("images_query", q)
    save("metadata", c.get(f"/api/metadata/{qid}").json())
    for det in range(7):
        save(f"frames_visit_det{det}_ch0_v-1", c.get(f"/api/images/{qid}/frames?mode=visit&det={det}").json())
    save("frames_visitdet_det0_ch0_v-1", c.get(f"/api/images/{qid}/frames?mode=visitdet").json())
    save("frames_planes_det0_ch0_v0", c.get(f"/api/images/{qid}/frames?mode=planes&visit=0").json())
    save("frames_channel_det0_ch40_v-1", c.get(f"/api/images/{qid}/frames?mode=channel&channel=40").json())
    n = c.get(f"/api/metadata/{qid}").json()["n_pix"]
    save("spectrum", c.get(f"/api/images/{qid}/spectrum?x={n // 2}&y={n // 2}").json())
    save("compare", c.post("/api/images/compare", json={"query_id": qid}).json())
    det = c.post("/api/detections/run", json={"query_id": qid}).json()
    save("detections", det)
    save("verification", c.post("/api/verification/gaia", json={"candidates": det["candidates"][:8]}).json())
    save("cube", c.get(f"/api/images/{qid}/cube").json())
    save("object", c.get(f"/api/object?ra={t['ra']}&dec={t['dec']}&mjd=61100&name=Barnard's Star").json())
    for name in ("gaia", "allwise"):
        save(f"catalog_{name}", c.get(f"/api/catalog/{name}?ra={t['ra']}&dec={t['dec']}&radius=0.085").json())

    # A few real cutouts (one per detector) for backend tests.
    FITS_OUT.mkdir(parents=True, exist_ok=True)
    job = jobs.get(qid)
    from backend.services import spherex
    picked = {}
    for m in job.meta:
        picked.setdefault(m["det"], m)
    items = {(it["obs_id"], it["det"]): it for it in spherex.search(t["ra"], t["dec"])}
    for d, m in sorted(picked.items()):
        it = items.get((m["obs_id"], d))
        if not it:
            continue
        p = spherex.fetch_cutout(it["url"], job.ra, job.dec, spherex.cutout_size(job.fov))
        dst = FITS_OUT / f"barnard_D{d}_{m['obs_id']}.fits"
        shutil.copy(p, dst)
        print(f"  {dst.name}  {dst.stat().st_size // 1024} KB")
