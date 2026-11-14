"""Name/coordinate parsing (no network needed)."""
import pytest

from backend.services import resolver


@pytest.mark.parametrize("text,ra,dec", [
    ("133.795 -7.245", 133.795, -7.245),
    ("08h55m10.831s -7d14m42.53s", 133.79513, -7.24515),
    ("08:55:10.831 -07:14:42.53", 133.79513, -7.24515),
])
def test_parse_coords(text, ra, dec):
    r = resolver.parse_coords(text)
    assert r is not None
    assert r[0] == pytest.approx(ra, abs=1e-4)
    assert r[1] == pytest.approx(dec, abs=1e-4)


def test_bad_coords():
    assert resolver.parse_coords("400 100") is None
    assert resolver.parse_coords("not a place") is None


def test_challenge_targets_are_built_in_and_moved_to_today():
    b = resolver.resolve("Barnard's Star")
    assert b["source"].startswith("built-in")
    # Barnard's Star has moved ~4.5 arcmin north since 2000
    assert b["dec"] == pytest.approx(4.693 + 10.362 * 26 / 3600, abs=1e-3)
    assert resolver.resolve("wise 0855")["name"] == "WISE 0855-0714"
