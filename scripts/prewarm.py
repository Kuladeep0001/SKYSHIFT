"""Download and cache the challenge targets ahead of a demo, so they load instantly.

    python -m scripts.prewarm            # all 5 targets, 6 arcmin view
    python -m scripts.prewarm --fov 10   # bigger view
"""
import argparse
import time

from backend import catalogs, jobs

TARGETS = ["Barnard's Star", "eps Ind B", "WISE J085510.83-071442.5", "RW Aur", "R Dra"]

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--fov", type=float, default=6.0)
    args = ap.parse_args()
    for name in TARGETS:
        t = catalogs.resolve(name)
        t0 = time.time()
        job = jobs.start(t["ra"], t["dec"], args.fov, None)
        while job.state not in ("done", "error"):
            time.sleep(2)
            print(f"\r{name}: {job.state} {job.done}/{job.total}", end="", flush=True)
        print(f"\r{name}: {job.state} - {job.message} ({time.time() - t0:.0f}s)")
