"""Background jobs: find every SPHEREx exposure of a patch, download, align, serve frames,
and keep them up to date as NASA adds data.

Freshness
---------
Each cached spot keeps a *fingerprint*: the exact list of IRSA image URLs it was built from.
`check()` re-asks IRSA (a ~2 s search). If the list changed (new exposures, a new release, or
reprocessed files) the spot is rebuilt in the background: only new cutouts are downloaded, and
visitors keep the old version until the new one is ready (then `version` goes up by one).
Checks happen (1) when someone opens a spot not checked for CHECK_MINUTES, (2) when a user presses
"check now", (3) for every cached spot, from the background watcher (services/watcher.py).

Cancelling
----------
`cancel()` stops a download: queued cutouts are dropped, running ones finish. Cutouts already
downloaded stay in the cache, so starting the same spot again resumes quickly.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
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
CHECK_POOL = ThreadPoolExecutor(max_workers=2)
DL_POOL = ThreadPoolExecutor(max_workers=16)  # parallel downloads from IRSA
LOCK = threading.Lock()
MAX_FOV = 20.0  # arcmin
CHECK_EVERY = float(os.environ.get("SKYSHIFT_CHECK_MINUTES", 60)) * 60  # re-check a spot opened after this long
MIN_MANUAL_GAP = 120  # seconds between "check now" presses for the same spot


class Cancelled(Exception):
    pass


@dataclass
class Job:
    id: str
    ra: float
    dec: float
    fov: float
    releases: list
    auto: bool = True  # follow the newest releases automatically
    state: str = "queued"
    message: str = ""
    done: int = 0
    total: int = 0
    failed: int = 0
    started: float = field(default_factory=time.time)
    meta: list = field(default_factory=list)
    arrays: dict = field(default_factory=dict)
    flag_defs: dict = field(default_factory=dict)
    signature: str = ""
    urls: list = field(default_factory=list)
    version: int = 0
    built_at: float = 0.0
    checked_at: float = 0.0
    refreshing: bool = False
    refresh_done: int = 0
    refresh_total: int = 0
    last_update: dict = field(default_factory=dict)
    cancel_event: threading.Event = field(default_factory=threading.Event)

    def freshness(self) -> dict:
        return {"version": self.version, "built_at": self.built_at, "checked_at": self.checked_at,
                "refreshing": self.refreshing, "refresh_progress": {"done": self.refresh_done, "total": self.refresh_total},
                "last_update": self.last_update, "releases": self.releases, "follows_newest": self.auto}

    def status(self) -> dict:
        return {
            "id": self.id, "state": self.state, "message": self.message, "done": self.done,
            "total": self.total, "failed": self.failed, "ra": self.ra, "dec": self.dec, "fov": self.fov,
            "releases": self.releases, "elapsed": round(time.time() - self.started, 1), "freshness": self.freshness(),
        }


JOBS: dict[str, Job] = {}


def job_id(ra, dec, fov, rels_key: str) -> str:
    return hashlib.sha1(f"{ra:.4f}|{dec:.4f}|{fov:.1f}|{rels_key}".encode()).hexdigest()[:16]


def _sig(items: list[dict]) -> str:
    return hashlib.sha1("\n".join(sorted(it["url"] for it in items)).encode()).hexdigest()[:16]


def start(ra: float, dec: float, fov: float, rels: list[str] | None) -> Job:
    fov = float(min(max(fov, 2.0), MAX_FOV))
    auto = not rels
    jid = job_id(ra, dec, fov, "newest" if auto else ",".join(sorted(rels)))
    with LOCK:
        job = JOBS.get(jid)
        if job and job.state not in ("error", "cancelled"):
            maybe_check(job)
            return job
        job = Job(jid, ra, dec, fov, list(rels) if rels else sphx.releases()["best"], auto=auto)
        JOBS[jid] = job
        if _load(job):
            maybe_check(job)
            return job
        JOB_POOL.submit(_run, job)
    return job


def get(jid: str) -> Job | None:
    job = JOBS.get(jid)
    if job is None:
        meta_file = JOBDIR / f"{jid}.json"
        if meta_file.exists():
            m = json.loads(meta_file.read_text())
            job = Job(jid, m["ra"], m["dec"], m["fov"], m["releases"], auto=m.get("auto", True))
            if _load(job):
                JOBS[jid] = job
    return job


def cancel(job: Job) -> dict:
    """Stop downloading this spot (or stop its background update)."""
    if job.state in ("queued", "searching", "downloading", "processing") or job.refreshing:
        job.cancel_event.set()
        if not job.refreshing:
            job.state, job.message = "cancelled", "Cancelled. Pictures downloaded so far are kept, so trying again resumes."
        return {"cancelled": True, "kept": job.done}
    return {"cancelled": False, "reason": f"nothing to cancel ({job.state})"}


def cached_ids() -> list[str]:
    return sorted(p.stem for p in JOBDIR.glob("*.json") if not p.stem.endswith(".tmp"))


def _load(job: Job) -> bool:
    f, m = JOBDIR / f"{job.id}.npz", JOBDIR / f"{job.id}.json"
    if not (f.exists() and m.exists()):
        return False
    d = np.load(f)
    job.arrays = {k: d[k] for k in d.files}
    info = json.loads(m.read_text())
    job.meta, job.flag_defs = info["meta"], info.get("flag_defs", {})
    for k in ("signature", "urls", "version", "built_at", "checked_at", "last_update"):
        if k in info:
            setattr(job, k, info[k])
    job.total = job.done = len(job.meta)
    job.state, job.message = "done", "Loaded from cache"
    return True


def _save(job: Job) -> None:
    tmp = JOBDIR / f"{job.id}.tmp.npz"
    np.savez_compressed(tmp, **job.arrays)
    os.replace(tmp, JOBDIR / f"{job.id}.npz")
    _save_meta(job)


def _save_meta(job: Job) -> None:
    info = {"ra": job.ra, "dec": job.dec, "fov": job.fov, "releases": job.releases, "auto": job.auto,
            "n": int(job.arrays["flux"].shape[-1]), "meta": job.meta, "flag_defs": job.flag_defs,
            "signature": job.signature, "urls": job.urls, "version": job.version, "built_at": job.built_at,
            "checked_at": job.checked_at, "last_update": job.last_update}
    tmp = JOBDIR / f"{job.id}.tmp.json"
    tmp.write_text(json.dumps(info))
    os.replace(tmp, JOBDIR / f"{job.id}.json")


def _build(ra: float, dec: float, fov: float, items: list[dict], progress=None,
           cancel_event: threading.Event | None = None) -> dict:
    """Download (cached) cutouts for `items`, align them, return arrays + per-exposure metadata."""
    size = sphx.cutout_size(fov)
    _w, n, gra, gdec = im.make_grid(ra, dec, fov)
    flag_defs: dict = {}

    def work(it):
        if cancel_event is not None and cancel_event.is_set():
            raise Cancelled()
        p = sphx.fetch_cutout(it["url"], ra, dec, size)
        if not flag_defs:
            flag_defs.update(im.read_flag_names(p))
        d = im.process_cutout(p, gra, gdec)
        d.update(det=it["det"], em_min=it["em_min"], em_max=it["em_max"], release=it["release"], obs_id=it["obs_id"])
        return d

    futs = [DL_POOL.submit(work, it) for it in items]
    results, failed = [], 0
    for f in as_completed(futs):
        if cancel_event is not None and cancel_event.is_set():
            for g in futs:
                g.cancel()  # drop everything still waiting in the queue
            raise Cancelled()
        ok = True
        try:
            d = f.result()
            if np.isfinite(d["flux"]).mean() > 0.05:
                results.append(d)
        except Cancelled:
            raise
        except Exception:
            ok = False
            failed += 1
        if progress:
            progress(ok)
    if not results:
        raise IOError("Downloads failed. IRSA may be busy, please try again.")
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
    return {"arrays": arrays, "meta": meta, "flag_defs": flag_defs, "failed": failed}


def _run(job: Job) -> None:
    try:
        job.state, job.message = "searching", "Asking NASA IRSA which SPHEREx images cover this spot..."
        items = sphx.search(job.ra, job.dec, job.releases)
        if job.cancel_event.is_set():
            raise Cancelled()
        if not items:
            job.state, job.message = "error", "No SPHEREx images cover this position yet."
            return
        job.total = len(items)
        job.state, job.message = "downloading", f"Downloading {len(items)} SPHEREx exposures..."

        def progress(ok):
            job.done += 1
            job.failed += 0 if ok else 1

        res = _build(job.ra, job.dec, job.fov, items, progress, job.cancel_event)
        job.state, job.message = "processing", "Aligning frames..."
        now = time.time()
        job.arrays, job.meta, job.flag_defs = res["arrays"], res["meta"], res["flag_defs"]
        job.signature, job.urls = _sig(items), sorted(it["url"] for it in items)
        job.version, job.built_at, job.checked_at = 1, now, now
        _save(job)
        job.state, job.message = "done", f"{len(job.meta)} exposures ready"
    except Cancelled:
        job.state, job.message = "cancelled", "Cancelled. Pictures downloaded so far are kept, so trying again resumes."
    except Exception as e:
        traceback.print_exc()
        job.state, job.message = "error", f"Something went wrong: {e}"


# ------------------------------------------------------------ freshness ---

def maybe_check(job: Job) -> None:
    """Called when someone opens a spot: re-check NASA in the background if it's been a while."""
    if job.state == "done" and not job.refreshing and time.time() - job.checked_at > CHECK_EVERY:
        CHECK_POOL.submit(_safe_check, job)


def _safe_check(job: Job) -> None:
    try:
        check(job, min_age=CHECK_EVERY)
    except Exception:
        traceback.print_exc()


def check(job: Job, min_age: float = MIN_MANUAL_GAP) -> dict:
    """Ask IRSA whether this spot has new or reprocessed SPHEREx images; rebuild in the background if so."""
    now = time.time()
    if job.state != "done":
        return {"checked": False, "reason": "not ready yet"}
    if job.refreshing:
        return {"checked": False, "reason": "already updating"}
    if now - job.checked_at < min_age:
        return {"checked": False, "reason": f"checked {int(now - job.checked_at)} s ago"}
    rels = sphx.releases()["best"] if job.auto else job.releases
    items = sphx.search(job.ra, job.dec, rels)
    job.checked_at = now
    if not items or _sig(items) == job.signature:
        _save_meta(job)
        return {"checked": True, "changed": False, "releases": rels}
    old_ids = {(m["obs_id"], m["det"]) for m in job.meta}
    new_ids = {(it["obs_id"], it["det"]) for it in items}
    n_new = len(new_ids - old_ids)
    info = {"new_exposures": n_new,
            "reprocessed": max(0, len(set(it["url"] for it in items) - set(job.urls)) - n_new),
            "new_releases": sorted(set(rels) - set(job.releases)), "releases": rels}
    job.refreshing, job.refresh_done, job.refresh_total = True, 0, len(items)
    job.cancel_event.clear()
    JOB_POOL.submit(_refresh, job, items, rels, info)
    return {"checked": True, "changed": True, **info}


def _refresh(job: Job, items: list[dict], rels: list[str], info: dict) -> None:
    try:
        def progress(_ok):
            job.refresh_done += 1

        res = _build(job.ra, job.dec, job.fov, items, progress, job.cancel_event)
        with LOCK:  # swap in the new data all at once
            job.arrays, job.meta, job.flag_defs = res["arrays"], res["meta"], res["flag_defs"]
            job.releases, job.signature, job.urls = rels, _sig(items), sorted(it["url"] for it in items)
            job.version += 1
            job.built_at = time.time()
            job.total = job.done = len(job.meta)
            job.last_update = {"at": job.built_at, "total": len(job.meta), **info}
            job.message = f"Updated: {info['new_exposures']} new exposures"
        _save(job)
    except Cancelled:
        job.checked_at = 0  # try again next time
    except Exception:
        traceback.print_exc()
    finally:
        job.refreshing = False
        job.cancel_event.clear()


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
        "version": job.version, "data": _b64(imgs) if len(infos) else "", "warn": _b64(warns) if len(infos) else "",
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
