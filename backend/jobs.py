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

from . import imaging as im
from . import sphx

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
    """Build the frames for the player.

    mode = exposure : every single exposure (optionally one detector or one channel)
           visit    : one stacked frame per visit (one detector, or det=0 for all detectors combined)
           visitdet : one stacked frame per visit per detector (for the 6-detector wall and colour)
           channel  : one stacked frame per visit using only one of the 102 channels (same wavelength)
           planes   : all 102 channels for one visit
    """
    flux, var, flags = job.arrays["flux"], job.arrays["var"], job.arrays["flags"]
    meta = job.meta
    idx = list(range(len(meta)))
    if det:
        idx = [i for i in idx if meta[i]["det"] == det]
    if channel and mode in ("exposure", "channel"):
        idx = [i for i in idx if meta[i]["channel"] == channel]
    if visit >= 0:
        idx = [i for i in idx if meta[i]["visit"] == visit]

    groups: list[tuple[dict, list[int]]] = []
    if mode == "exposure":
        groups = [({"det": meta[i]["det"], "channel": meta[i]["channel"], "wave": meta[i]["wave"],
                    "obs_id": meta[i]["obs_id"], "visit": meta[i]["visit"]}, [i]) for i in idx]
    elif mode in ("visit", "channel"):
        for v in sorted({meta[i]["visit"] for i in idx}):
            groups.append(({"visit": v, "det": det, "channel": channel}, [i for i in idx if meta[i]["visit"] == v]))
    elif mode == "visitdet":
        for v in sorted({meta[i]["visit"] for i in idx}):
            for d in range(1, 7):
                g = [i for i in idx if meta[i]["visit"] == v and meta[i]["det"] == d]
                if g:
                    groups.append(({"visit": v, "det": d}, g))
    elif mode == "planes":
        for ch in range(1, 103):
            g = [i for i in idx if meta[i]["channel"] == ch]
            if g:
                groups.append(({"channel": ch, "det": (ch - 1) // 17 + 1, "visit": visit}, g))
    else:
        raise ValueError(f"unknown mode {mode}")

    imgs, warns, out = [], [], []
    for info, g in groups:
        if len(g) == 1:
            img = flux[g[0]]
            warn = (flags[g[0]] & im.WARN_MASK) != 0
        else:
            img, warn = im.weighted_stack(flux[g], var[g], flags[g])
        mj = [meta[i]["mjd"] for i in g]
        waves = [meta[i]["wave"] for i in g if meta[i]["wave"] == meta[i]["wave"]]
        info.update(n_exp=len(g), mjd=float(np.mean(mj)), date=im.mjd_to_iso(float(np.mean(mj))),
                    date_range=[im.mjd_to_iso(min(mj))[:10], im.mjd_to_iso(max(mj))[:10]],
                    wave=round(float(np.median(waves)), 4) if waves else None, members=g)
        imgs.append(img.astype(np.float32))
        warns.append(warn.astype(np.uint8))
        out.append(info)
    n = int(flux.shape[-1])
    return {
        "mode": mode, "n": n, "count": len(out), "frames": out,
        "data": _b64(np.stack(imgs)) if imgs else "", "warn": _b64(np.stack(warns)) if warns else "",
    }


def spectrum(job: Job, x: int, y: int, r: int = 1) -> dict:
    """Brightness of a small box at pixel (x, y) in every exposure: a spectrum + light curve."""
    flux, var, flags, wave = (job.arrays[k] for k in ("flux", "var", "flags", "wave"))
    n = flux.shape[-1]
    x, y, r = int(x), int(y), int(min(max(r, 0), 4))
    if not (0 <= x < n and 0 <= y < n):
        raise ValueError("pixel outside the image")
    y0, y1, x0, x1 = max(0, y - r), min(n, y + r + 1), max(0, x - r), min(n, x + r + 1)
    # Local background ring a few pixels out from the box.
    R = r + 4
    by0, by1, bx0, bx1 = max(0, y - R), min(n, y + R + 1), max(0, x - R), min(n, x + R + 1)
    ring = np.ones((by1 - by0, bx1 - bx0), bool)
    ring[(y0 - by0):(y1 - by0), (x0 - bx0):(x1 - bx0)] = False
    ranges = im.det_ranges(job.meta)
    pts = []
    for i, m in enumerate(job.meta):
        box = flux[i, y0:y1, x0:x1]
        good = np.isfinite(box)
        if good.mean() < 0.6:
            continue
        bg = np.nanmedian(flux[i, by0:by1, bx0:bx1][ring])
        bg = 0.0 if not np.isfinite(bg) else bg
        s = (np.nansum(box - bg) / good.mean()) * im.MJYSR_TO_UJY
        e = np.sqrt(np.nansum(var[i, y0:y1, x0:x1])) * im.MJYSR_TO_UJY
        w = float(wave[i, y, x])
        if not np.isfinite(w):
            continue
        fl = int(np.bitwise_or.reduce(flags[i, y0:y1, x0:x1].ravel()))
        names = [k for k, b in im.FLAG_BITS.items() if fl & (1 << b)]
        saturated = bool(fl & im.SAT_MASK)
        pts.append({"i": i, "wave": round(w, 4), "flux": round(float(s), 3), "err": round(float(e), 3),
                    "mjd": m["mjd"], "date": m["date"][:10], "visit": m["visit"], "det": m["det"],
                    "channel": im.channel_of(m["det"], w, ranges), "flags": names, "saturated": saturated})
    return {"x": x, "y": y, "r": r, "unit": "uJy", "points": pts}
