"""The technical report builds a valid PDF from a spot's data (no network: external=False)."""
import numpy as np

from backend.services import image_processing as im
from backend.services import jobs, report


def fake_job():
    """Three visits a year apart (half-year steps), one star moving north, 6 detectors."""
    rng = np.random.default_rng(3)
    n = 41
    yy, xx = np.mgrid[0:n, 0:n]
    flux, meta = [], []
    for v, (mjd, dy) in enumerate([(60900.0, 0.0), (61082.6, 0.75), (61265.25, 1.5)]):
        for k in range(24):
            det = 1 + k % 6
            star = 300 * np.exp(-((xx - 20) ** 2 + (yy - 20 - dy) ** 2) / 2.0) + 80 * np.exp(-((xx - 8) ** 2 + (yy - 30) ** 2) / 2.0)
            flux.append(star + rng.normal(0, 1, (n, n)))
            lo = 0.75 + (det - 1) * 0.72
            meta.append({"i": len(meta), "det": det, "obs_id": f"TEST_{v}_{k}", "mjd": mjd + k * 0.05, "date": im.mjd_to_iso(mjd + k * 0.05),
                         "visit": v, "wave": lo + 0.3, "channel": (det - 1) * 17 + 5, "em_min": lo, "em_max": lo + 0.7,
                         "release": "spherex_dr1", "coverage": 1.0})
    f = np.stack(flux).astype(np.float32)
    wave = np.stack([np.full((n, n), m["wave"], np.float32) for m in meta])
    job = jobs.Job(id="testreport0001", ra=100.0, dec=10.0, fov=n * im.PIX_ARCSEC / 60, releases=["spherex_dr1"])
    job.state, job.meta, job.version = "done", meta, 1
    job.arrays = {"flux": f, "var": np.ones_like(f), "flags": np.zeros(f.shape, np.int32), "wave": wave}
    job.flag_defs = {"HOT": {"bit": 10, "meaning": "Hot pixel"}, "OVERFLOW": {"bit": 1, "meaning": "Overflow"}}
    return job


def test_report_is_a_pdf_with_the_key_sections():
    pdf, number = report.build(fake_job(), None, None, 0, "Test star", None, site="http://example.test/", external=False)
    assert pdf.startswith(b"%PDF")
    assert number.startswith("SKYSHIFT-TR-")
    assert len(pdf) > 20000
    from pypdf import PdfReader  # noqa: optional dev dependency
    import io
    text = "".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf)).pages)
    for part in ("Abstract", "Observations and data", "Processing", "Detections", "Object of interest",
                 "References", "Appendix A", "Appendix B", "Appendix C", "SKYSHIFT"):
        assert part in text, part
