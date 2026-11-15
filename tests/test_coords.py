"""Forgiving coordinate reading (services/coords.py) and the /api/resolve/position route. No network."""
import astropy.units as u
import pytest
from astropy.coordinates import AltAz, EarthLocation, SkyCoord
from astropy.time import Time
from fastapi.testclient import TestClient

from backend.main import app
from backend.services import coords

client = TestClient(app)
BARNARD = (269.4521, 4.6933)


@pytest.mark.parametrize("a, b", [
    ("17 57 48.5", "+04 41 36"), ("17:57:48.5", "+4:41:36"), ("17h57m48.5s", "4d41m36s"),
    ("17h 57 m 48.5 s", "+ 04° 41′ 36″"), ("17 hours 57 minutes 48.5 seconds", "4 degrees 41 arcmin 36 arcsec"),
    ("269.452", "4.693"), ("269,452", "4,693"), ("269 .452", "4. 693"), ("269 27 07.5", "4.6933"),
])
def test_many_ways_to_write_the_same_spot(a, b):
    ra, dec, _, _ = coords.parse_pair(f"{a} {b}") if False else (*coords.parse_angle(a, "ra")[:1], *coords.parse_angle(b, "dec")[:1], None, None)
    assert ra == pytest.approx(BARNARD[0], abs=2e-3)
    assert dec == pytest.approx(BARNARD[1], abs=2e-3)


@pytest.mark.parametrize("text", ["269.452, 4.693", "17 57 48.5 +04 41 36", "17 57 48.5 - 04 41 36", "269,452 4,693", "17h57m48.5s 4d41m36s"])
def test_both_numbers_in_one_box(text):
    r = coords.position(text, "", "icrs")
    assert r["ra"] == pytest.approx(BARNARD[0], abs=2e-3) and abs(r["dec"]) == pytest.approx(BARNARD[1], abs=2e-3)
    assert r["split"] and len(r["split"]) == 2


def test_minus_sign_and_hemisphere_letters():
    assert coords.parse_angle("−4.69", "dec")[0] == pytest.approx(-4.69)
    assert coords.parse_angle("7.2 S", "dec")[0] == pytest.approx(-7.2)
    assert coords.parse_angle("12.97S", "lat")[0] == pytest.approx(-12.97)
    assert coords.parse_angle("77.59 W", "lon")[0] == pytest.approx(-77.59)
    assert coords.parse_angle("77.59E", "lon")[0] == pytest.approx(77.59)


@pytest.mark.parametrize("a, b, field, words", [
    ("25h", "0", "a", "0 to 24"), ("17 61 0", "0", "a", "minutes must be under 60"), ("abc", "4", "a", "couldn't read"),
    ("10", "95", "b", "between"), ("", "4", "a", "Type the RA"), ("10", "", "b", "Type the Dec"), ("1 2 3 4", "0", "a", "at most three"),
])
def test_plain_error_messages_name_the_box(a, b, field, words):
    with pytest.raises(coords.CoordError) as e:
        coords.position(a, b, "icrs")
    assert e.value.field == field and words in str(e.value)


def test_small_ra_read_as_degrees_with_a_hint():
    deg, note = coords.parse_angle("17.96", "ra")
    assert deg == pytest.approx(17.96) and "add h" in note
    assert coords.parse_angle("17.96h", "ra")[0] == pytest.approx(269.4)


def test_galactic_and_earth_frames():
    g = coords.position("31.0", "+14.1", "galactic")
    assert g["ra"] == pytest.approx(269.4, abs=0.2) and g["dec"] == pytest.approx(4.7, abs=0.2)
    # the sky straight above Bengaluru at a fixed moment, against astropy's zenith (alt 90°) in ICRS
    now = 1_700_000_000.0
    b = coords.position("12.9716° N, 77.5946° E", "", "earth", now=now)
    here = EarthLocation(lat=12.9716 * u.deg, lon=77.5946 * u.deg)
    zenith = SkyCoord(alt=90 * u.deg, az=0 * u.deg, frame=AltAz(obstime=Time(now, format="unix"), location=here)).icrs
    assert b["ra"] == pytest.approx(zenith.ra.deg, abs=0.05) and b["dec"] == pytest.approx(zenith.dec.deg, abs=0.05)
    assert "77.59° E" in b["label"] and b["split"]


def test_route():
    r = client.get("/api/resolve/position", params={"a": "17 57 48.5", "b": "+ 04 41 36"})
    assert r.status_code == 200 and r.json()["ra"] == pytest.approx(BARNARD[0], abs=2e-3)
    bad = client.get("/api/resolve/position", params={"a": "17 57 48.5", "b": "95"})
    assert bad.status_code == 400 and bad.json()["detail"]["field"] == "b"
    assert client.get("/api/resolve/position", params={"a": "1", "b": "2", "frame": "moon"}).status_code == 422


def test_name_tidying_suggestions():
    assert "vega" in [t.lower() for t in coords.tidy_name("vega star")]
    assert "barnard's star" in [t.lower() for t in coords.tidy_name("barnards star")]
    assert "hd 209458" in [t.lower() for t in coords.tidy_name("hd209458")]
