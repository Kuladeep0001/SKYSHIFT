"""Background jobs: find all SPHEREx exposures of a patch, download, align, and serve frames."""
from __future__ import annotations

import base64
import hashlib
import json
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

import numpy as np

from . import image_processing as im
from . import spherex as sphx

JOBDIR = sphx.CACHE / "jobs"
JOBDIR.mkdir(parents=True, exist_ok=True)
JOB_POOL = ThreadPoolExecutor(max_workers=2)
DL_POOL = ThreadPoolExecutor(max_workers=16)  # parallel downloads from IRSA
LOCK = threading.Lock()
MAX_FOV = 20.0  # arcmin


@dataclass
class Job:
    id: str
    ra: float
    dec: float
    fov: float
    releases: list
    state: str = "queued"
    message: str = ""
    done: int = 0
    total: int = 0
    failed: int = 0
    started: float = field(default_factory=time.time)
    meta: list = field(default_factory=list)
    arrays: dict = field(default_factory=dict)
    flag_defs: dict = field(default_factory=dict)

    def status(self) -> dict:
        return {
            "id": self.id, "state": self.state, "message": self.message, "done": self.done,
            "total": self.total, "failed": self.failed, "ra": self.ra, "dec": self.dec, "fov": self.fov,
            "releases": self.releases, "elapsed": round(time.time() - self.started, 1),
        }


JOBS: dict[str, Job] = {}


def job_id(ra, dec, fov, rels) -> str:
    return hashlib.sha1(f"{ra:.4f}|{dec:.4f}|{fov:.1f}|{','.join(sorted(rels))}".encode()).hexdigest()[:16]


def start(ra: float, dec: float, fov: float, rels: list[str] | None) -> Job:
    fov = float(min(max(fov, 2.0), MAX_FOV))
    rels = rels or sphx.releases()["best"]
    jid = job_id(ra, dec, fov, rels)
    with LOCK:
        job = JOBS.get(jid)
        if job and job.state != "error":
            return job
        job = Job(jid, ra, dec, fov, rels)
        JOBS[jid] = job
        if _load(job):
            return job
        JOB_POOL.submit(_run, job)
    return job


def get(jid: str) -> Job | None:
    job = JOBS.get(jid)
    if job is None:
        meta_file = JOBDIR / f"{jid}.json"
        if meta_file.exists():
            m = json.loads(meta_file.read_text())
            job = Job(jid, m["ra"], m["dec"], m["fov"], m["releases"])
            if _load(job):
                JOBS[jid] = job
    return job


def _load(job: Job) -> bool:
    f, m = JOBDIR / f"{job.id}.npz", JOBDIR / f"{job.id}.json"
    if not (f.exists() and m.exists()):
        return False
    d = np.load(f)
    job.arrays = {k: d[k] for k in d.files}
    info = json.loads(m.read_text())
    job.meta, job.flag_defs = info["meta"], info.get("flag_defs", {})
    job.total = job.done = len(job.meta)
    job.state, job.message = "done", "Loaded from cache"
    return True


def _run(job: Job) -> None:
    try:
        job.state, job.message = "searching", "Asking NASA IRSA which SPHEREx images cover this spot..."
        items = sphx.search(job.ra, job.dec, job.releases)
        if not items:
            job.state, job.message = "error", "No SPHEREx images cover this position yet."
            return
        job.total = len(items)
        job.state = "downloading"
        job.message = f"Downloading {len(items)} SPHEREx exposures..."
        size = sphx.cutout_size(job.fov)
        _w, n, gra, gdec = im.make_grid(job.ra, job.dec, job.fov)
        flag_defs: dict = {}

        def work(it):
            p = sphx.fetch_cutout(it["url"], job.ra, job.dec, size)
            if not flag_defs:
                flag_defs.update(im.read_flag_names(p))
            d = im.process_cutout(p, gra, gdec)
            d.update(det=it["det"], em_min=it["em_min"], em_max=it["em_max"], release=it["release"],
                     obs_id=it["obs_id"])
            return d

        results = []
        futs = [DL_POOL.submit(work, it) for it in items]
        for f in as_completed(futs):
            try:
                d = f.result()
                if np.isfinite(d["flux"]).mean() > 0.05:
                    results.append(d)
            except Exception:
                job.failed += 1
            job.done += 1
        if not results:
            job.state, job.message = "error", "Downloads failed. IRSA may be busy, please try again."
            return
        job.state, job.message = "processing", "Aligning frames..."
        results.sort(key=lambda d: (d["mjd"], d["det"]))
        arrays = {k: np.stack([d[k] for d in results]) for k in ("flux", "var", "flags", "wave")}
        arrays["flux"] = arrays["flux"].astype(np.float32)
        arrays["var"] = arrays["var"].astype(np.float32)
        visits = im.assign_visits(np.array([d["mjd"] for d in results]))
        ranges = im.det_ranges(results)
        c = n // 2
        meta = []
        for i, d in enumerate(results):
            wc = float(d["wave"][c, c]) if np.isfinite(d["wave"][c, c]) else float(np.nanmedian(d["wave"]))
            meta.append({
                "i": i, "det": d["det"], "obs_id": d["obs_id"], "mjd": d["mjd"], "date": im.mjd_to_iso(d["mjd"]),
                "visit": int(visits[i]), "wave": round(wc, 4), "channel": im.channel_of(d["det"], wc, ranges),
                "em_min": d["em_min"], "em_max": d["em_max"], "release": d["release"],
                "coverage": round(float(np.isfinite(d["flux"]).mean()), 3),
            })
        np.savez_compressed(JOBDIR / f"{job.id}.npz", **arrays)
        (JOBDIR / f"{job.id}.json").write_text(json.dumps({
            "ra": job.ra, "dec": job.dec, "fov": job.fov, "releases": job.releases, "n": n,
            "meta": meta, "flag_defs": flag_defs,
        }))
        job.arrays, job.meta, job.flag_defs = arrays, meta, flag_defs
        job.state, job.message = "done", f"{len(meta)} exposures ready"
    except Exception as e:
        traceback.print_exc()
        job.state, job.message = "error", f"Something went wrong: {e}"


# ------------------------------------------------------------- serving ---

def _b64(a: np.ndarray) -> str:
    return base64.b64encode(np.ascontiguousarray(a).tobytes()).decode()


def summary(job: Job) -> dict:
    ranges = im.det_ranges(job.meta)
    visits = sorted({m["visit"] for m in job.meta})
    vinfo = []
    for v in visits:
        ms = [m for m in job.meta if m["visit"] == v]
        vinfo.append({"visit": v, "start": ms[0]["date"][:10], "end": ms[-1]["date"][:10], "n": len(ms)})
    chans = []
    for ch in range(1, 103):
        w = im.channel_wave(ch, ranges)
        n = sum(1 for m in job.meta if m["channel"] == ch)
        chans.append({"channel": ch, "det": (ch - 1) // 17 + 1,
                      "wave": None if w is None else [round(w[0], 4), round(w[1], 4)], "n": n})
    return {"status": job.status(), "n_pix": int(job.arrays["flux"].shape[-1]), "pix_arcsec": im.PIX_ARCSEC,
            "exposures": job.meta, "visits": vinfo, "channels": chans,
            "detectors": {str(k): [round(a, 3), round(b, 3)] for k, (a, b) in sorted(ranges.items())},
            "flag_defs": job.flag_defs, "warn_flags": im.WARN, "hard_flags": im.HARD, "sat_flags": im.SAT}


def frames(job: Job, mode: str, det: int = 0, channel: int = 0, visit: int = -1) -> dict:
    """Frames for the player, encoded for JSON (float32 pixels as base64)."""
    infos, imgs, warns = im.group_frames(job.arrays, job.meta, mode, det, channel, visit)
    return {
        "mode": mode, "n": int(job.arrays["flux"].shape[-1]), "count": len(infos), "frames": infos,
        "data": _b64(imgs) if len(infos) else "", "warn": _b64(warns) if len(infos) else "",
    }


def spectrum(job: Job, x: int, y: int, r: int = 1) -> dict:
    return im.measure_spectrum(job.arrays, job.meta, x, y, r)


def visit_members(job: Job, visit: int, det: int = 0) -> list[int]:
    return [m["i"] for m in job.meta if m["visit"] == visit and (not det or m["det"] == det)]


def main_visits(job: Job, min_exposures: int = 20) -> list[int]:
    """Visits with enough exposures to make a clean stack (the twice-a-year all-sky passes)."""
    counts: dict[int, int] = {}
    for m in job.meta:
        counts[m["visit"]] = counts.get(m["visit"], 0) + 1
    big = [v for v, c in sorted(counts.items()) if c >= min_exposures]
    return big or sorted(counts)
