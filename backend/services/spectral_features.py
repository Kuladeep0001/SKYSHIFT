"""Spectral features SPHEREx can see (0.75–5 µm): water, CO2, CO, methane, hydrogen lines, minerals...

Bins all measurements of a spot into the 102 channels to make one continuous spectrum, then measures
how deep each known band is compared with the continuum on either side.
SPHEREx's resolution is low (R ~ 40-130), so these are broad-band hints, not line identifications:
we say "possible" / "likely" and show the numbers so technical users can judge.

Owner: Feature developer 2 (analysis) / Verification.
"""
from __future__ import annotations

import math

import numpy as np

# name, species, category, centre µm, half-width µm, absorption|emission, plain-English meaning, where it's seen
FEATURES = [
    ("H₂O vapour 1.4 µm", "H2O", "water", 1.40, 0.07, "absorption",
     "Water vapour in the atmosphere of a cool star or brown dwarf.", "cool stars, brown dwarfs, giant planets"),
    ("H₂O vapour 1.9 µm", "H2O", "water", 1.88, 0.08, "absorption",
     "Water vapour absorbing light.", "cool stars, brown dwarfs"),
    ("H₂O vapour 2.7 µm", "H2O", "water", 2.70, 0.12, "absorption",
     "Strong water band seen in very cool atmospheres.", "brown dwarfs, M dwarfs"),
    ("H₂O ice 3.05 µm", "H2O ice", "water", 3.05, 0.18, "absorption",
     "Frozen water on dust grains, the main thing SPHEREx's ice survey looks for.", "dense clouds, young stars, comets"),
    ("Hydrated minerals 2.75 µm", "OH/H2O in rock", "minerals", 2.75, 0.10, "absorption",
     "Water locked inside rocks (hydrated minerals).", "asteroids, rocky dust"),
    ("Olivine / pyroxene 1 µm", "silicate rock", "minerals", 1.00, 0.12, "absorption",
     "Iron-bearing rock minerals: the signature of rocky surfaces.", "S-type asteroids, rocky bodies"),
    ("Pyroxene 2 µm", "silicate rock", "minerals", 2.00, 0.18, "absorption",
     "Second band of pyroxene rock.", "asteroids"),
    ("CO₂ ice 4.27 µm", "CO2 ice", "carbon", 4.27, 0.05, "absorption",
     "Frozen carbon dioxide on dust grains.", "dense clouds, protostars, comets"),
    ("CO ice / gas 4.67 µm", "CO", "carbon", 4.67, 0.07, "absorption",
     "Carbon monoxide, frozen or as gas.", "dense clouds, cool stars, brown dwarfs"),
    ("CO band head 2.3 µm", "CO gas", "carbon", 2.33, 0.08, "absorption",
     "Carbon monoxide in the atmosphere of a cool giant or dwarf star.", "red giants, M dwarfs"),
    ("CH₄ methane 1.65 µm", "CH4", "carbon", 1.65, 0.06, "absorption",
     "Methane: appears only in very cold brown dwarfs and giant planets.", "T and Y brown dwarfs, Jupiter"),
    ("CH₄ methane 2.2 µm", "CH4", "carbon", 2.20, 0.08, "absorption",
     "Methane band.", "T and Y brown dwarfs"),
    ("CH₄ methane 3.3 µm", "CH4", "carbon", 3.30, 0.10, "absorption",
     "Strongest methane band in SPHEREx's range.", "T and Y brown dwarfs (e.g. WISE 0855)"),
    ("PAH 3.29 µm", "organic molecules", "organics", 3.29, 0.05, "emission",
     "Glow from large carbon (organic) molecules heated by starlight.", "star-forming regions, galaxies"),
    ("Paschen β 1.28 µm", "H", "hydrogen", 1.282, 0.02, "emission",
     "Hot hydrogen gas glowing: a sign of gas falling onto a young star.", "young stars, nebulae"),
    ("Brackett γ 2.17 µm", "H", "hydrogen", 2.166, 0.03, "emission",
     "Hot hydrogen gas glowing (accretion or a nebula).", "young stars like RW Aurigae"),
    ("Brackett α 4.05 µm", "H", "hydrogen", 4.052, 0.04, "emission",
     "Hydrogen emission line.", "young stars, H II regions"),
    ("H₂ 2.12 µm", "H2", "hydrogen", 2.122, 0.02, "emission",
     "Molecular hydrogen heated by shocks, e.g. in jets.", "jets from young stars"),
]

CATEGORY_LABEL = {"water": "Water", "minerals": "Rock / minerals", "carbon": "Carbon gases & ices",
                  "organics": "Organic molecules", "hydrogen": "Hot hydrogen"}


def bin_spectrum(points: list[dict], channels_wave: dict[int, tuple[float, float]] | None = None) -> list[dict]:
    """Combine many measurements into one value per channel (1..102): median flux + robust error."""
    by: dict[int, list[dict]] = {}
    for p in points:
        if p.get("channel"):
            by.setdefault(p["channel"], []).append(p)
    out = []
    for ch in sorted(by):
        ps = by[ch]
        f = np.array([p["flux"] for p in ps], float)
        e = np.array([p["err"] for p in ps], float)
        w = np.array([p["wave"] for p in ps], float)
        med = float(np.median(f))
        if len(f) >= 3:
            scatter = 1.4826 * float(np.median(np.abs(f - med))) / math.sqrt(len(f)) * 1.253
            err = max(scatter, float(np.sqrt(np.sum(e ** 2))) / len(f))
        else:
            err = float(np.sqrt(np.sum(e ** 2))) / len(f)
        out.append({"channel": ch, "wave": round(float(np.median(w)), 4), "flux": round(med, 3), "err": round(err, 3),
                    "n": len(ps), "saturated": any(p.get("saturated") for p in ps)})
    return out


def measure_features(binned: list[dict], min_sigma: float = 3.0) -> list[dict]:
    """Depth of each known band relative to a straight-line continuum fitted on both sides."""
    if len(binned) < 8:
        return []
    w = np.array([b["wave"] for b in binned])
    f = np.array([b["flux"] for b in binned])
    e = np.array([max(b["err"], 1e-6) for b in binned])
    out = []
    for name, species, cat, c, hw, kind, plain, where in FEATURES:
        inb = np.abs(w - c) <= hw
        cont = (np.abs(w - c) > hw) & (np.abs(w - c) <= hw + max(0.15, 2.5 * hw))
        left, right = cont & (w < c), cont & (w > c)
        if inb.sum() < 1 or left.sum() < 1 or right.sum() < 1:
            continue  # not enough channels around this band
        A = np.vstack([w[cont], np.ones(cont.sum())]).T
        coef, *_ = np.linalg.lstsq(A / e[cont, None], f[cont] / e[cont], rcond=None)
        cont_in = coef[0] * w[inb] + coef[1]
        level = float(np.mean(cont_in))
        if level <= 0:
            continue
        obs = float(np.average(f[inb], weights=1 / e[inb] ** 2))
        obs_err = float(1 / math.sqrt(np.sum(1 / e[inb] ** 2)))
        cont_err = float(np.std(f[cont] - (coef[0] * w[cont] + coef[1])) / math.sqrt(cont.sum())) if cont.sum() > 2 else obs_err
        change = (obs - level) / level            # negative = dip, positive = bump
        sig = abs(obs - level) / math.hypot(obs_err, cont_err or obs_err)
        expected_sign = -1 if kind == "absorption" else 1
        matches = np.sign(change) == expected_sign
        status = ("likely" if sig >= 5 else "possible" if sig >= min_sigma else "not seen") if matches else "not seen"
        pct = abs(change) * 100
        if status == "not seen":
            text = f"No clear {('dip' if kind == 'absorption' else 'bump')} at {c:.2f} µm."
        else:
            text = (f"{'Dip' if change < 0 else 'Bump'} of {pct:.0f}% at {c:.2f} µm ({sig:.1f}σ). {plain}")
        out.append({"name": name, "species": species, "category": cat, "category_label": CATEGORY_LABEL[cat],
                    "center_um": c, "half_width_um": hw, "kind": kind, "change_pct": round(change * 100, 1),
                    "significance": round(sig, 1), "status": status, "plain_english": text, "seen_in": where,
                    "n_channels": int(inb.sum())})
    # A narrow emission line can't be told apart from the bright gap between two deep absorption bands
    # (e.g. the 1.28 µm peak of a brown dwarf sits between water dips at 1.15 and 1.4 µm).
    dips = [f for f in out if f["kind"] == "absorption" and f["status"] != "not seen"]
    for f in out:
        if f["kind"] != "emission" or f["status"] == "not seen":
            continue
        reach = f["half_width_um"] + max(0.15, 2.5 * f["half_width_um"])
        near = [d for d in dips if abs(d["center_um"] - f["center_um"]) - d["half_width_um"] < reach]
        broad_peak = _is_broad_peak(w, f, binned)
        if near or broad_peak:
            f["status"] = "ambiguous"
            f["plain_english"] = (f"Bump at {f['center_um']:.2f} µm, but it sits between absorption dips "
                                  f"({', '.join(d['name'] for d in near) or 'a broad hump'}), so it is probably just "
                                  "the bright gap between them, not glowing gas.")
    order = {"likely": 0, "possible": 1, "ambiguous": 2, "not seen": 3}
    return sorted(out, key=lambda x: (order[x["status"]], -x["significance"]))


def _is_broad_peak(w: np.ndarray, f: dict, binned: list[dict]) -> bool:
    """True when the 'line' is really a wide hump: neighbours just outside the band are also well above
    the continuum ends (a real unresolved line drops back quickly)."""
    c, hw = f["center_um"], f["half_width_um"]
    fl = np.array([b["flux"] for b in binned])
    inner = (np.abs(w - c) > hw) & (np.abs(w - c) <= hw + 0.08)
    outer = (np.abs(w - c) > hw + 0.15) & (np.abs(w - c) <= hw + 0.3)
    if inner.sum() < 2 or outer.sum() < 2:
        return False
    return float(np.mean(fl[inner])) > 1.3 * float(np.mean(fl[outer]))
