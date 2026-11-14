"""Alignment, stacking, channels, background, PNG rendering."""
import numpy as np
import pytest

from backend.services import image_processing as im


def test_grid_is_north_up_east_left():
    w, n, gra, gdec = im.make_grid(100.0, 20.0, 6.0)
    assert n == round(6 * 60 / im.PIX_ARCSEC)
    assert gdec[-1, n // 2] > gdec[0, n // 2]          # row index grows to the north
    assert gra[n // 2, 0] > gra[n // 2, -1]            # column index grows to the west


def test_bilinear_and_nan_outside():
    img = np.arange(16, dtype=float).reshape(4, 4)
    out = im._bilinear(img, np.array([1.5, 10.0]), np.array([1.0, 1.0]))
    assert out[0] == pytest.approx(5.5)
    assert np.isnan(out[1])


def test_visits_split_on_gaps():
    v = im.assign_visits(np.array([0, 1, 2, 200, 201, 400.0]))
    assert list(v) == [0, 0, 0, 1, 1, 2]


def test_channel_numbers_cover_1_to_102():
    ranges = {d: (0.75 * 1.4 ** (d - 1), 0.75 * 1.4 ** d) for d in range(1, 7)}
    assert im.channel_of(1, ranges[1][0] * 1.001, ranges) == 1
    assert im.channel_of(6, ranges[6][1] * 0.999, ranges) == 102
    lo, hi = im.channel_wave(40, ranges)
    assert im.channel_of(3, (lo + hi) / 2, ranges) == 40


def test_weighted_stack_prefers_low_noise():
    flux = np.stack([np.full((3, 3), 1.0), np.full((3, 3), 3.0)]).astype(np.float32)
    var = np.stack([np.full((3, 3), 1.0), np.full((3, 3), 100.0)]).astype(np.float32)
    mean, _ = im.weighted_stack(flux, var, np.zeros_like(flux, dtype=np.int32))
    assert mean[1, 1] == pytest.approx((1 + 3 / 100) / (1 + 1 / 100), rel=1e-4)


def test_background_removal_keeps_stars():
    y, x = np.mgrid[0:60, 0:60]
    img = (0.05 * x + 0.02 * y).astype(np.float32)   # a sky gradient
    img[30, 30] += 50                                 # a star
    out = im.subtract_background(img)
    assert abs(np.median(out)) < 0.2
    assert out[30, 30] > 45


def test_saturated_core_filled():
    img = np.ones((5, 5), np.float32)
    img[2, 2] = np.nan
    flg = np.zeros((5, 5), np.int64)
    flg[2, 2] = 1 << im.FLAG_BITS["OVERFLOW"]
    img[1, 2] = 9
    im._fill_saturated_cores(img, flg)
    assert img[2, 2] == 9


def test_render_png():
    png = im.render_png(np.random.default_rng(0).normal(size=(20, 20)))
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
