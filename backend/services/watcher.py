"""Background watcher: keeps SkyShift in step with NASA.

IRSA has no "new data" notification, so every WATCH_HOURS we:
  1. re-detect the SPHEREx releases (a new spherex_dr2 / qr4 appears here automatically),
  2. re-check which Gaia release is online (DR4 is picked up when ESA publishes it),
  3. re-ask IRSA about every cached spot and rebuild the ones whose image list changed.

Set SKYSHIFT_WATCH_HOURS=0 to switch it off. Owner: Integration lead.
"""
from __future__ import annotations

import os
import threading
import time
import traceback
from collections import deque

from . import jobs, sky_catalogs, spherex

WATCH_HOURS = float(os.environ.get("SKYSHIFT_WATCH_HOURS", 6))
STATE: dict = {"enabled": WATCH_HOURS > 0, "every_hours": WATCH_HOURS, "running": False, "last_run": None,
               "next_run": None, "log": deque(maxlen=60)}
_lock = threading.Lock()


def _log(msg: str) -> None:
    STATE["log"].appendleft({"at": time.time(), "message": msg})


def run_once() -> dict:
    """One full freshness pass. Safe to call from the API (only one runs at a time)."""
    if not _lock.acquire(blocking=False):
        return {"started": False, "reason": "a check is already running"}
    STATE["running"] = True
    summary = {"started": True, "spots_checked": 0, "spots_updating": 0, "new_releases": []}
    try:
        before = {r["id"] for r in (spherex._rel_mem["data"] or {}).get("releases", [])}
        rel = spherex.releases(force=True)
        after = {r["id"] for r in rel["releases"]}
        if before and after - before:
            summary["new_releases"] = sorted(after - before)
            _log(f"New SPHEREx release found: {', '.join(summary['new_releases'])}")
        try:
            g = sky_catalogs.gaia_release(force=True)
            summary["gaia"] = g["release"]
        except Exception:
            pass
        for jid in jobs.cached_ids():
            try:
                job = jobs.get(jid)
                if not job:
                    continue
                r = jobs.check(job, min_age=0)
                summary["spots_checked"] += 1
                if r.get("changed"):
                    summary["spots_updating"] += 1
                    _log(f"Spot {job.ra:.4f}, {job.dec:.4f}: {r['new_exposures']} new exposures, "
                         f"{r['reprocessed']} reprocessed; updating")
            except Exception as e:
                _log(f"Spot {jid}: check failed ({e})")
        _log(f"Checked {summary['spots_checked']} spots; {summary['spots_updating']} updating; "
             f"releases: {', '.join(rel['best'])}")
    except Exception as e:
        traceback.print_exc()
        _log(f"Watcher error: {e}")
    finally:
        STATE["running"] = False
        STATE["last_run"] = time.time()
        _lock.release()
    return summary


def _loop() -> None:
    time.sleep(60)  # let the server start first
    while True:
        run_once()
        STATE["next_run"] = time.time() + WATCH_HOURS * 3600
        time.sleep(WATCH_HOURS * 3600)


def start() -> None:
    if WATCH_HOURS > 0:
        threading.Thread(target=_loop, daemon=True, name="skyshift-watcher").start()


def status() -> dict:
    return {**{k: v for k, v in STATE.items() if k != "log"}, "log": list(STATE["log"]),
            "releases": spherex.releases(), "gaia": sky_catalogs.gaia_release()["release"],
            "cached_spots": len(jobs.cached_ids())}
