"""Forgiving coordinate reading: whatever people type, turn it into a sky position (RA/Dec, degrees).

One box at a time (`parse_angle`) or both numbers in one box (`parse_pair`). It copes with:
  - decimal degrees or sexagesimal: 269.452 · 17 57 48.5 · 17:57:48.5 · 17h57m48.5s · +04°41′36″ · 4d41m36s
  - stray or missing spaces: "+ 04 41 36", "48. 5", "17h 57 m 48.5 s", "269 .452"
  - typographic signs and marks: − – — ’ ″ º, and decimal commas (269,452)
  - words: 17 hours 57 minutes, 4 degrees 41 arcmin
  - N/S/E/W: 12.97 N, 77.59 E, 7.2S
  - both numbers pasted in one box: "269.452, 4.693" or "17 57 48.5 +04 41 36"

Three kinds of position (`position`):
  icrs      RA / Dec on the sky
  galactic  galactic longitude / latitude
  earth     latitude / longitude of a place on Earth: the sky straight above it right now
"""
from __future__ import annotations

import re
import time

import astropy.units as u
from astropy.coordinates import FK5, SkyCoord
from astropy.time import Time

KINDS = {  # kind -> (plain name, lowest, highest)
    "ra": ("RA", 0.0, 360.0), "dec": ("Dec", -90.0, 90.0),
    "glon": ("galactic longitude", -360.0, 360.0), "glat": ("galactic latitude", -90.0, 90.0),
    "lat": ("latitude", -90.0, 90.0), "lon": ("longitude", -180.0, 360.0),
}
FRAMES = {"icrs": ("ra", "dec"), "galactic": ("glon", "glat"), "earth": ("lat", "lon")}
_WORDS = [  # "arcmin" before "min", or it would be split into "arc m"
    (r"arc ?min(?:ute)?s?", "'"), (r"arc ?sec(?:ond)?s?", '"'),
    (r"hours?|hrs?", "h"), (r"minutes?|mins?", "m"), (r"seconds?|secs?", "s"), (r"degrees?|degs?", "d"),
    (r"north", "n"), (r"south", "s_"), (r"east", "e"), (r"west", "w"),
]


class CoordError(ValueError):
    """A friendly message saying what is wrong with what was typed."""


def _clean(text: str) -> str:
    s = str(text or "").strip().lower()
    for a, b in (("−–—‒﹣－", "-"), ("＋", "+"), ("′’‘`´", "'"), ("″”“", '"'), ("º˚", "°"), ("   ", " ")):
        for ch in a:
            s = s.replace(ch, b)
    s = s.replace("''", '"')
    for pat, rep in _WORDS:
        s = re.sub(rf"(?<![a-z]){pat}(?![a-z])", f" {rep} ", s)
    s = re.sub(r"(\d)\s*\.\s*(\d)", r"\1.\2", s)                    # "48. 5" -> "48.5"
    s = re.sub(r"(?<![\d.])\.\s*(\d)", r"0.\1", s)                   # ".5" -> "0.5"
    s = re.sub(r"([+-])\s+(?=[\d.])", r"\1", s)                      # "+ 04" -> "+04"
    s = re.sub(r"[;:/|_]+(?!_)", " ", s.replace("s_", "S"))          # separators -> space ("s_" = the word south)
    return re.sub(r"\s+", " ", s).strip()


def _fmt(deg: float, kind: str) -> str:
    if kind == "ra":
        h = deg / 15
        hh, rem = int(h), (h - int(h)) * 60
        mm, ss = int(rem), (rem - int(rem)) * 60
        return f"{deg:.4f}° ({hh}h {mm:02d}m {ss:04.1f}s)"
    return f"{deg:+.4f}°"


def parse_angle(text: str, kind: str) -> tuple[float, str]:
    """One box -> degrees, plus how it was read (shown to the user). Raises CoordError with a plain message."""
    name, lo, hi = KINDS[kind]
    raw = str(text or "").strip()
    if not raw:
        raise CoordError(f"Type the {name}.")
    s = _clean(raw)
    # hemisphere letters: N/S for dec/lat, E/W for longitudes (only when no d/m/s units are used, so 's' isn't seconds)
    sign = 1.0
    hemi = re.fullmatch(r"([nsewS])?\s*([^nsewS]*?)\s*([nsewS])?", s)
    if hemi and (hemi.group(1) or hemi.group(3)) and not (hemi.group(1) and hemi.group(3)):
        letter = (hemi.group(1) or hemi.group(3))
        body = hemi.group(2)
        units_used = re.search(r"[hdm°'\"]", body)
        if letter == "S" or (letter == "s" and not units_used and kind in ("dec", "lat", "glat")):
            sign, s = -1.0, body
        elif letter == "n" and kind in ("dec", "lat", "glat"):
            s = body
        elif letter in "ew" and kind in ("lon", "glon"):
            sign, s = (-1.0 if letter == "w" else 1.0), body
        elif letter in "nsew" and letter != "s":
            raise CoordError(f"'{letter.upper()}' doesn't fit a {name}.")
    # decimal comma: "269,452" (one comma between digits and no dot)
    if re.fullmatch(r"[+-]?\d+,\d+\s*[a-z°'\"]*", s) and "." not in s:
        s = s.replace(",", ".")
    s = s.replace(",", " ")
    m = re.match(r"^([+-])?\s*(.*)$", s)
    if m.group(1) == "-":
        sign = -sign
    body = m.group(2)
    tokens = re.findall(r"\d+(?:\.\d*)?|\.\d+|[hmsd°'\"]", body)
    if not tokens or re.sub(r"\d+(?:\.\d*)?|\.\d+|[hmsd°'\"]|\s", "", body):
        raise CoordError(f"I couldn't read “{raw}” as a {name}. Try a number like 269.45, or 17 57 48.5.")
    nums, units = [], []
    for t in tokens:
        if t[0].isdigit() or t[0] == ".":
            nums.append(float(t))
            units.append(None)
        elif units and units[-1] is None:
            units[-1] = t
        else:
            raise CoordError(f"I couldn't read “{raw}” as a {name}: a unit is in the wrong place.")
    if len(nums) > 3:
        raise CoordError(f"Too many numbers in the {name}: use at most three (like 17 57 48.5).")
    for k, v in enumerate(nums[1:], 1):
        if v >= 60:
            raise CoordError(f"In the {name}, the {'minutes' if k == 1 else 'seconds'} must be under 60 (you typed {v:g}).")
    value = nums[0] + (nums[1] / 60 if len(nums) > 1 else 0) + (nums[2] / 3600 if len(nums) > 2 else 0)
    hours = "h" in units or (kind == "ra" and len(nums) > 1 and not ({"d", "°"} & set(units)))
    note = ""
    if hours and "h" not in units and value > 24:     # "269 27 07" can't be hours: it was meant as degrees
        hours, note = False, " (read as degrees)"
    if hours:
        if kind != "ra":
            raise CoordError(f"Hours (h) only make sense for RA, not for the {name}.")
        if value > 24:
            raise CoordError(f"RA in hours must be 0 to 24 (you typed {value:g}h).")
        deg = value * 15
    else:
        deg = value
        if kind == "ra" and len(nums) == 1 and deg <= 24 and "d" not in units and "°" not in units:
            note = " (read as degrees; for hours add h, like 17.96h)"
    deg *= sign
    if kind == "ra" and -360 < deg < 0:
        deg += 360
    if kind == "ra" and deg == 360:
        deg = 0.0
    if not (lo <= deg <= hi) or (kind == "ra" and deg >= 360):
        rng = "0 to 360° (or 0 to 24h)" if kind == "ra" else f"{lo:g}° to {hi:+g}°"
        raise CoordError(f"The {name} must be between {rng}; you typed {raw}.")
    return deg, _fmt(deg, kind) + note


def split_pair(text: str) -> tuple[str, str] | None:
    """Both numbers in one box -> the two halves (as typed), or None if it doesn't look like a pair."""
    raw = str(text or "").strip()
    if not raw or re.search(r"[a-z]{3,}", _clean(raw).replace("arc", "")) and not re.search(r"\d", raw):
        return None
    s = _clean(raw)
    if re.fullmatch(r"[+-]?\d+,\d+\s+[+-]?\d+,\d+", s):                # decimal commas: "269,452 4,693"
        a, b = s.split()
        return a, b
    parts = [p.strip() for p in re.split(r"\s*,\s*", s) if p.strip()]
    if len(parts) == 2:
        return parts[0], parts[1]
    toks = s.split()
    if len(toks) < 2:
        return None
    for k in range(1, len(toks)):                                         # a sign starts the second number
        if toks[k][0] in "+-":
            return " ".join(toks[:k]), " ".join(toks[k:])
    for k in range(len(toks) - 1):                                        # N/S/E/W ends the first number
        if toks[k] in ("n", "S", "e", "w") or (toks[k][-1:] in ("n", "w") and re.search(r"\d", toks[k])):
            return " ".join(toks[:k + 1]), " ".join(toks[k + 1:])
    for k in range(1, len(toks)):                                         # 17h57m48.5s 4d41m36s
        if re.search(r"[d°]", toks[k]) and not re.search(r"[d°]", " ".join(toks[:k])):
            return " ".join(toks[:k]), " ".join(toks[k:])
    n = len(toks)
    if n in (2, 4, 6):
        return " ".join(toks[:n // 2]), " ".join(toks[n // 2:])
    if n == 5:
        return " ".join(toks[:3]), " ".join(toks[3:])
    return None


def parse_pair(text: str, kinds=("ra", "dec")) -> tuple[float, float, str, str] | None:
    """Both numbers in one box -> (a_deg, b_deg, a_note, b_note), or None if it isn't a readable pair."""
    halves = split_pair(text)
    if not halves:
        return None
    try:
        a, na = parse_angle(halves[0], kinds[0])
        b, nb = parse_angle(halves[1], kinds[1])
    except CoordError:
        return None
    return a, b, na, nb


def _sidereal_deg(lon_east: float, unix: float) -> float:
    """Local mean sidereal time in degrees (standard formula, good to well under a second)."""
    jd = unix / 86400.0 + 2440587.5
    d = jd - 2451545.0
    t = d / 36525.0
    gmst = 280.46061837 + 360.98564736629 * d + 0.000387933 * t * t - t ** 3 / 38710000.0
    return (gmst + lon_east) % 360.0


def position(a: str, b: str, frame: str = "icrs", now: float | None = None) -> dict:
    """Two boxes (or a pair pasted into the first) in any frame -> RA/Dec (ICRS degrees) and how it was read.
    Errors raise CoordError with `.field` = "a" or "b"."""
    if frame not in FRAMES:
        raise CoordError(f"Unknown kind of position '{frame}'.")
    ka, kb = FRAMES[frame]
    split = None
    if str(a or "").strip() and not str(b or "").strip():
        halves = split_pair(a)
        if halves:
            split, (a, b) = halves, halves
    out = {}
    for field, text, kind in (("a", a, ka), ("b", b, kb)):
        try:
            out[field] = parse_angle(text, kind)
        except CoordError as e:
            e.field = field
            raise
    (va, na), (vb, nb) = out["a"], out["b"]
    res = {"frame": frame, "read_a": na, "read_b": nb, "split": list(split) if split else None}
    if frame == "icrs":
        ra, dec = va, vb
        res["label"] = None
    elif frame == "galactic":
        c = SkyCoord(l=va * u.deg, b=vb * u.deg, frame="galactic").icrs
        ra, dec = float(c.ra.deg), float(c.dec.deg)
        res["label"] = f"galactic l {va:.3f}°, b {vb:+.3f}°"
    else:  # the sky straight above a place on Earth, now: RA = local sidereal time, Dec = latitude (of date -> ICRS)
        t = time.time() if now is None else now
        lon = vb if vb <= 180 else vb - 360
        ra_now, dec_now = _sidereal_deg(lon, t), va
        c = SkyCoord(ra=ra_now * u.deg, dec=dec_now * u.deg, frame=FK5(equinox=Time(t, format="unix"))).icrs
        ra, dec = float(c.ra.deg), float(c.dec.deg)
        ns, ew = ("N" if va >= 0 else "S"), ("E" if lon >= 0 else "W")
        res["label"] = f"overhead at {abs(va):.2f}° {ns}, {abs(lon):.2f}° {ew} at {time.strftime('%H:%M', time.gmtime(t))} UTC"
        res["read_b"] = f"{abs(lon):.4f}° {ew}"
        res["read_a"] = f"{abs(va):.4f}° {ns}"
    res.update({"ra": ra, "dec": dec, "read": f"RA {_fmt(ra, 'ra')}, Dec {dec:+.4f}°"})
    return res


SOLAR_SYSTEM = {"sun", "moon", "mercury", "venus", "earth", "mars", "jupiter", "saturn", "uranus", "neptune", "pluto", "ceres"}


def tidy_name(text: str) -> list[str]:
    """Other spellings to try when a name isn't found: 'the vega star' -> 'vega', "barnards" -> "barnard's"."""
    s = re.sub(r"\s+", " ", str(text or "").strip())
    bare = re.sub(r"^(the|star|planet)\s+", "", s, flags=re.I)
    bare = re.sub(r"\s+(the\s+)?(star|planet)$", "", bare, flags=re.I)
    out = []
    for t in (s, bare):                                                     # with the filler words, then without
        tries = [t]
        if "'" not in t:
            tries.append(re.sub(r"^([a-z]+)s\b", r"\1's", t, flags=re.I))  # barnards star -> barnard's star
        tries.append(t.replace("'", ""))
        tries.append(re.sub(r"([a-z])(\d)", r"\1 \2", t, flags=re.I))      # hd209458 -> hd 209458
        for v in tries:
            if v and v.lower() != s.lower() and v.lower() not in (o.lower() for o in out):
                out.append(v)
    return out
