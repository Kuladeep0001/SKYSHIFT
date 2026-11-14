# SkyShift API

Base URL: `http://localhost:8000` locally (same origin as the website when deployed).
Interactive docs with a "Try it out" button: **`/docs`**.

All responses are JSON unless noted. Coordinates are in **degrees** (ICRS). Fields called `x, y` are
**pixels on SkyShift's aligned grid**: north-up, east-left, 6.15″ per pixel, with `x` increasing to the right
(west), `y` increasing **upward** (north), and `(0, 0)` at the bottom-left.

## Typical flow

```
POST /api/images/query      → {status: "pending", query_id}        (first time a spot is asked for)
GET  /api/images/{query_id} → poll every 1–2 s until status: "success"
GET  /api/metadata/{query_id}                     → visits, exposures, the 102 channels, flag meanings
GET  /api/images/{query_id}/frames?mode=visit     → pixels for the player (or use image_url PNGs)
POST /api/detections/run    → candidates
POST /api/verification/gaia → is each candidate known?
```

## Errors

Every error has this shape (inside FastAPI's `detail`):

```json
{ "detail": { "status": "error", "error": "unknown_query", "message": "Unknown query_id. Send POST /api/images/query again." } }
```

| HTTP | `error` | When |
|---|---|---|
| 400 | `bad_request`, `bad_epoch`, `missing_mjd` | a parameter has the wrong value |
| 404 | `unknown_query`, `no_such_frame`, `no_such_exposure`, `not_found`, `unknown_catalog` | the thing doesn't exist |
| 409 | `not_ready` | images are still downloading (includes `progress`) |
| 422 | (FastAPI validation list) / `missing_position` | the body or query string is malformed |
| 502 | `upstream` | NASA/ESA/CDS service failed — try again |

---

## Images  (`routes/images.py`, owner: Feature developer 1)

### `POST /api/images/query`
Start (or reuse) gathering every SPHEREx exposure that covers a patch of sky.

Request:
```json
{ "ra": 269.44627, "dec": 4.7682, "fov": 6, "bands": [0, 6], "release": null }
```
| field | type | default | meaning |
|---|---|---|---|
| `ra`, `dec` | float | required | centre, degrees |
| `fov` | float | 6 | field of view in **arcminutes** (2–20). Bigger = slower |
| `bands` | int[] | `[]` → `[0]` | detector arrays to list images for: `0` = all six stacked, `1`–`6` = one detector |
| `release` | string[] | newest | e.g. `["spherex_dr1"]`. See `/api/releases` |

Response (first time — keep polling):
```json
{ "status": "pending", "query_id": "4c0040ed821b835e", "message": "Downloading 358 SPHEREx exposures...",
  "progress": { "done": 120, "total": 358, "failed": 0 }, "images": [] }
```
Response (ready): one stacked image per **visit** (SPHEREx revisits each spot every ~6 months) per band:
```json
{
  "status": "success", "query_id": "4c0040ed821b835e", "message": "358 exposures ready",
  "progress": { "done": 358, "total": 358, "failed": 0 },
  "images": [
    { "id": "4c0040ed821b835e-b0-v0", "epoch": "2025-08-26", "date_range": ["2025-08-15", "2025-09-05"],
      "band": 0, "visit": 0, "n_exposures": 108, "wavelength_um": 2.3788,
      "image_url": "/api/images/4c0040ed821b835e/frames/0.png?mode=visit&det=0" }
  ]
}
```

### `GET /api/images/{query_id}?bands=0,6`
Same response as above. Use it to poll.

### Keeping data fresh, and cancelling

Every image response carries a `freshness` block:
```json
"freshness": { "version": 2, "built_at": 1794637873.3, "checked_at": 1794637890.1, "refreshing": false,
               "refresh_progress": { "done": 0, "total": 0 },
               "last_update": { "at": 1794637873.3, "new_exposures": 25, "reprocessed": 0, "new_releases": [], "total": 358 },
               "releases": ["spherex_dr1", "spherex_qr3"], "follows_newest": true }
```
`version` goes up by one each time NASA data for this spot changed and SkyShift rebuilt it. The website polls
`GET /api/images/{query_id}` every 2 minutes and offers "show new pictures" when `version` increases.

| Endpoint | What it does |
|---|---|
| `POST /api/images/{query_id}/check` | Ask IRSA **now** if this spot has new/reprocessed images (max once per 2 min). Returns `{ "result": { "checked": true, "changed": true, "new_exposures": 25, "reprocessed": 0, "new_releases": [] }, "freshness": {…} }`. If changed, the rebuild runs in the background. |
| `POST /api/images/{query_id}/cancel` | Stop a download (or a background update). `{ "cancelled": true, "kept": 120, "status": "cancelled" }`. Cutouts already downloaded stay cached, so a new query resumes. Status `cancelled` is then returned by `GET /api/images/{query_id}`. |
| `GET /api/updates` | Watcher feed: `{ enabled, every_hours, running, last_run, next_run, releases, gaia, cached_spots, log: [{at, message}] }` |
| `POST /api/updates/run` | Run the watcher now for every cached spot (max once per 10 min; `429 too_soon` otherwise). |

### `GET /api/images/{query_id}/frames`
Aligned pixel data for the interactive viewer.

| param | values | meaning |
|---|---|---|
| `mode` | `visit` (default) | one stacked frame per visit |
| | `exposure` | every single exposure (best for asteroids) |
| | `channel` | per visit, only exposures in one of the **102 channels** (same wavelength over time) |
| | `visitdet` | per visit **and** per detector (for the 6-detector wall / colour image) |
| | `planes` | all 102 channels for **one** visit |
| `det` | 0–7 | 0 = all detectors, 1–6 = one detector, 7 = D5+D6 (reddest light: cold brown dwarfs) |
| `channel` | 1–102 | with `mode=channel` or `exposure` |
| `visit` | int | with `mode=planes` (or to filter) |

```json
{
  "mode": "visit", "n": 59, "count": 6,
  "frames": [
    { "visit": 0, "det": 0, "channel": 0, "n_exp": 108, "mjd": 60911.7, "date": "2025-08-26 16:10",
      "date_range": ["2025-08-15", "2025-09-05"], "wave": 2.3788, "members": [0, 1, 2] }
  ],
  "data": "<base64 float32, count × n × n, row 0 = south>",
  "warn": "<base64 uint8, count × n × n, 1 = contaminated pixel (ghost/streak/halo/...)>"
}
```
Decode in JS: `new Float32Array(bytes.buffer, k*n*n*4, n*n)` (see `frontend/src/lib/frames.js`).

### `GET /api/images/{query_id}/frames/{k}.png`
Frame `k` of the same list as a PNG (north up). Same `mode/det/channel/visit` params, plus `contrast` (0–1).

### `GET /api/images/{query_id}/spectrum?x=29&y=29&r=1`
Brightness of a (2r+1)² box (local sky removed) in **every** exposure → spectrum and light curve.
```json
{ "x": 29, "y": 29, "r": 1, "unit": "uJy",
  "points": [ { "i": 0, "wave": 4.9262, "flux": 152.7, "err": 160.3, "mjd": 60902.865, "date": "2025-08-15",
                "visit": 0, "det": 6, "channel": 100, "flags": ["SOURCE"], "saturated": false } ] }
```

Also returned (for the continuous spectrum and molecule finder):
```json
{ "ra": 331.09664, "dec": -56.80066, "saturated_fraction": 0.32,
  "binned": [ { "channel": 1, "wave": 0.7581, "flux": 812.4, "err": 35.1, "n": 4, "saturated": false } ],
  "binned_by_visit": { "0": [ ...same per channel, visit 0 only... ] },
  "features": [ { "name": "H₂O vapour 1.9 µm", "species": "H2O", "category": "water", "center_um": 1.88,
                  "half_width_um": 0.08, "kind": "absorption", "change_pct": -61.6, "significance": 7.4,
                  "status": "likely", "plain_english": "Dip of 62% at 1.88 µm (7.4σ). Water vapour absorbing light.",
                  "seen_in": "cool stars, brown dwarfs", "n_channels": 3 } ] }
```
`status`: `likely` (≥5σ, right sign) · `possible` (≥3σ) · `ambiguous` (an emission bump that is really the gap between two absorption dips) · `not seen`. Bands covered: water vapour/ice, hydrated
minerals, olivine/pyroxene (rock), CO₂ ice, CO, CH₄, PAH, hydrogen lines (Paβ, Brγ, Brα), H₂.

### `GET /api/images/{query_id}/cube?visit=-1`
**Spectral cube**: 102 planes x n x n. Each plane holds ONE wavelength band over the whole area. SPHEREx's filter
changes colour across every snapshot, so every *pixel* of every snapshot is sent to the plane matching the
wavelength that pixel saw, then averaged (1/variance weights). `visit=-1` = all dates (deepest); a visit number =
that visit only (compare the same colour at different dates).
```json
{ "n": 59, "planes": 102, "visit": -1, "version": 1, "pix_arcsec": 6.15, "exposures_used": 458, "dtype": "float16",
  "channels": [ { "channel": 41, "det": 3, "wave": 1.8995, "wave_lo": 1.877, "wave_hi": 1.922, "coverage": 1.0, "snapshots_per_pixel": 6.1 } ],
  "data": "<base64 float16, planes x n x n, MJy/sr, row 0 = south>", "err": "<base64 float16, 1-sigma>" }
```
Pick a pixel or box and read it through all 102 planes to get its spectrum (done in the browser:
`frontend/src/components/SpectralCube.jsx`, `boxSpectrum`).

### `POST /api/detections/features`
Find water/CO2/CO/CH4/hydrogen/mineral bands in any spectrum (e.g. an area from the cube).
Body `{ "spectrum": [ { "wave": 1.40, "flux": 812.4, "err": 35.1 }, ... ] }` → `{ "features": [ ...same format as above... ] }`

### `GET /api/images/{query_id}/history?ra=&dec=&fov=`
**Time machine**: the area in POSS-I (1950s plates), POSS-II (1990s), 2MASS Ks (~2000), WISE W1 (2010) and SPHEREx,
all on one 240 x 240 north-up grid. `frames[]`: `{survey, label, band, date, year, mjd, coverage}`; `data`: base64 float32.

### `GET /api/images/{query_id}/asteroids`
Known asteroids/comets (IMCCE SkyBoT, one search per observing day, propagated to each snapshot) inside the picture:
`{ "objects": [ { "name": "2000 CW34", "number": "103643", "class": "MB>Outer", "mag": 19.9, "rate_arcsec_h": 25.7,
"visible_guess": false, "appearances": [ { "i": 120, "date": "2026-09-15 08:03", "det": 5, "x": 41.2, "y": 30.9 } ] } ] }`

### `POST /api/images/compare`
```json
{ "query_id": "4c0040ed821b835e", "epoch_a": null, "epoch_b": null, "band": 0, "op": "subtract" }
```
`epoch_a/b` are visit numbers (default: first and last big visit). `op`: `subtract` or `add`.
```json
{ "status": "success", "query_id": "4c0040ed821b835e", "op": "subtract", "band": 0,
  "epoch_a": { "visit": 0, "start": "2025-08-15", "end": "2025-09-05", "n_exposures": 108 },
  "epoch_b": { "visit": 4, "start": "2026-08-16", "end": "2026-09-02", "n_exposures": 117 },
  "image_url": "/api/images/4c0040ed821b835e/compare.png?a=0&b=4&band=0&op=subtract",
  "explanation": "Later visit minus earlier visit. Orange = brighter now ..." }
```

## Analysis  (`routes/analysis.py`, owner: Feature developer 2)

### `POST /api/detections/run`
```json
{ "query_id": "4c0040ed821b835e", "band": 0, "threshold": 5.0, "include_transients": false }
```
`band` 5 or 6 is best for cold brown dwarfs. Response (best first; movers before brightness changes):
```json
{ "status": "success", "query_id": "4c0040ed821b835e", "band": 0,
  "candidates": [
    { "candidate_id": "C001", "kind": "mover", "ra": 269.446244, "dec": 4.768153, "epoch": "2026-08-24",
      "mjd": 61276.4, "x": 29.11, "y": 30.37, "snr": 319.2, "score": 0.209, "saturated": true,
      "x_from": 29.15, "y_from": 28.7, "ra_from": 269.44624, "dec_from": 4.76787, "visit_a": 0, "visit_b": 4,
      "motion": { "dx_px": -0.03, "dy_px": 1.67, "years": 0.997, "pmra_mas_yr": 187.0, "pmdec_mas_yr": 10295.0,
                  "total_arcsec_yr": 10.363, "pa_deg": 351.8 },
      "plain_english": "Something here moved toward the north between 2025-08 and 2026-08, at about 10.4 arcseconds per year. ..." },
    { "candidate_id": "C002", "kind": "variable", "flux_change": { "direction": "fainter", "before_mjysr": 120.3,
      "after_mjysr": 43.1, "ratio": 0.358 }, "plain_english": "This object got about 2.8× fainter between ...", "...": "..." }
  ],
  "note": "Movers: dark→bright pairs between visits. ..." }
```
`kind`: `mover` | `variable` | `appeared` | `vanished` | `transient` (only with `include_transients`).

## Website checks  (`routes/checks.py`, SkyShift; uses `services/sky_catalogs.py`)

### `POST /api/verification/gaia`
One candidate (format from the team plan) → one result:
```json
{ "candidate_id": "C001", "ra": 269.4462, "dec": 4.7681, "epoch": "2026-03-20", "kind": "mover",
  "motion": { "total_arcsec_yr": 10.36 } }
```
```json
{ "candidate_id": "C001",
  "matches": [ { "catalog": "Gaia DR3", "id": "4472832130942575872", "ra": 269.4485, "dec": 4.7394, "mag": 8.19,
                 "sep_arcsec": 2.6, "pm_total": 10393.3 } ],
  "verification_status": "known_mover",
  "plain_english": "✓ Confirmed: a known fast-moving star in Gaia. Gaia says it moves 10.39″ per year; SkyShift measured 10.36″ per year from SPHEREx alone." }
```
Many at once: `{ "candidates": [ ...candidates from /api/detections/run... ] }` → a list of results.
Optional `radius_arcsec` (default 12).

`verification_status`: `known_mover` (SIMBAD or Gaia, >100 mas/yr) · `known_star` (Gaia or WISE) · `likely_artefact` (glare next to a very bright star, or a saturated star) · `known_asteroid`
(SkyBoT, for `transient`/`appeared`) · `unmatched` (not in any catalogue — worth a human look!) · `pending`
(archives unreachable). Gaia positions are moved to the candidate's date using proper motion.

### `GET /api/object?ra=&dec=&mjd=&name=`
Details card for whatever is at a position (fast-moving stars are matched at the given date):
```json
{ "summary": "This is Barnard's star, a red dwarf with starspots (BY Draconis variable) (type M4V), about 6.0 light-years away. It appears in 924 scientific papers. It moves 10.39″ per year across the sky (Gaia).",
  "simbad": { "main_id": "NAME Barnard's star", "type": "...", "spectral_type": "M4V", "distance_ly": 5.96, "n_references": 924, "url": "..." },
  "gaia": { "id": "4472832130942575872", "mag": 8.19, "pm_total": 10393.3, "distance_ly": 5.96, "sep_arcsec": 2.6 },
  "wise": { "id": "J175749.21+044635.6", "mag": 4.03, "w2": 3.76, "w1_w2": 0.27 },
  "wikipedia": { "title": "Barnard's Star", "extract": "...", "thumbnail": "https://...", "url": "https://en.wikipedia.org/wiki/Barnard%27s_Star" },
  "links": [ { "label": "SIMBAD", "url": "..." }, { "label": "ESASky", "url": "..." } ],
  "sources": ["SIMBAD", "Gaia DR3", "AllWISE"], "errors": [] }
```

### `GET /api/catalog/{gaia|allwise|skybot}?ra=&dec=&radius=&mjd=`
Overlay data. `radius` in degrees (≤ 0.5). `skybot` needs `mjd`.
```json
{ "catalog": "Gaia DR3", "epoch": 2016.0, "source": "ESA Gaia archive", "band": "G",
  "stars": [ { "id": "4472832130942575872", "ra": 269.4485, "dec": 4.7394, "pmra": -801.55, "pmdec": 10362.39,
               "plx": 546.98, "mag": 8.19 } ] }
```
SkyBoT returns `{ "catalog": "SkyBoT", "mjd": ..., "objects": [ { "name", "ra", "dec", "class", "mag", "dra", "ddec" } ] }`.

### `POST /api/verification/`: full catalogue verification  (`routes/verification.py`, owner: Meenakshi K)
Same request and result as the cross-check below, plus three extra sections in each result:
`photometric_assessment` (measurements, colours such as BP−RP / J−H / W1−W2, SED, quality warnings),
`object_profile` (identity, other names, astrometry) and `exoplanet_association` (known planets from the
NASA Exoplanet Archive, matched by Gaia DR3 id or position). The website's **🔬 Is it already known?** panel uses this.

### `POST /api/crossmatch/`: four-catalogue cross-check only  (`routes/crossmatch.py`, owner: Meenakshi K)
Is an object already known? Checks **Gaia DR3, 2MASS, AllWISE and SIMBAD**, each at its own observing date.
Gaia runs first; its proper motion is used to move the position to the 2MASS (~1999) and AllWISE (2010.5)
epochs, and the other three catalogues are then queried at the same time. Takes 5–30 s. The website shows it
as the **🔬 Is it already known?** panel. Full design notes: [backend/VERIFICATION.md](backend/VERIFICATION.md).
```json
{ "candidates": [ { "candidate_id": "WISE 0855", "ra": 133.7598, "dec": -7.2422,
                    "observation_time": "2026-01-01T00:00:00Z",
                    "pmra_mas_yr": -8118.0, "pmdec_mas_yr": 673.0 } ],
  "catalogues": ["gaia", "2mass", "allwise", "simbad"],
  "search_radius_arcsec": 6.0 }
```
- `observation_time` must include a time zone. 1–10 candidates per request.
- `pmra_mas_yr` / `pmdec_mas_yr` are optional: the object's own motion, used instead of Gaia when Gaia has no match
  (brown dwarfs such as WISE 0855 are too faint for Gaia).

Response, one entry per candidate:
```json
{ "results": [ { "candidate_id": "WISE 0855",
    "assessment": "confirmed_association",
    "catalogue_results": { "gaia": { "status": "no_match", "match_quality": "borderline", "nearest_source": { ... } },
                           "allwise": { "status": "match_found", "match_quality": "within_radius", "epoch_correction_available": true,
                                        "nearest_source": { "designation": "J085510.74-071442.5", "photometry": { "W1": { ... }, "W2": { ... } },
                                                            "contamination_summary": { ... }, "motion_fit": { ... } } },
                           "2mass": { ... }, "simbad": { ... } },
    "evidence_summary": { "explanation": "...", "confirmed_associations": 2, "catalogues": { "allwise": { "evidence": "confirmed_association",
                          "separation_arcsec": 0.55, "reasons": [ ... ], "photometric_caveats": [ ... ] }, ... } },
    "cross_catalogue_association": { "status": "consistent | borderline | inconsistent | mixed_evidence | not_assessable", ... } } ] }
```
`assessment`: `confirmed_association` · `potential_association` · `no_association` · `insufficient_evidence`
(a catalogue didn't answer: never treated as "not there") · `conflicting_evidence`.

## Metadata  (`routes/metadata.py`, owner: Integration lead)

### `GET /api/metadata/{query_id}`
```json
{ "status": { "id": "...", "state": "done", "ra": 269.44627, "dec": 4.7682, "fov": 6.0, "releases": ["spherex_dr1", "spherex_qr3"] },
  "n_pix": 59, "pix_arcsec": 6.15,
  "exposures": [ { "i": 0, "det": 6, "obs_id": "2025W33_2C_0321_1", "mjd": 60902.865, "date": "2025-08-15 20:45",
                   "visit": 0, "wave": 4.9262, "channel": 100, "em_min": 4.41, "em_max": 5.01,
                   "release": "spherex_dr1", "coverage": 1.0 } ],
  "visits": [ { "visit": 0, "start": "2025-08-15", "end": "2025-09-05", "n": 108 } ],
  "channels": [ { "channel": 1, "det": 1, "wave": [0.75, 0.767], "n": 3 } ],
  "detectors": { "1": [0.75, 1.11], "6": [4.41, 5.01] },
  "flag_defs": { "OVERFLOW": { "bit": 1, "value": 2, "meaning": "Overflow detected during SUR" } },
  "warn_flags": ["PERSIST", "CROSSTALK", "GHOST", "..."], "hard_flags": ["NONFUNC", "..."], "sat_flags": ["OVERFLOW", "..."] }
```

### `GET /api/metadata/{query_id}/exposure/{i}`
One exposure plus the % of its pixels carrying each flag:
```json
{ "i": 5, "det": 6, "obs_id": "2025W33_2C_0321_3", "date": "2025-08-15 20:50", "wave": 4.9959, "channel": 102,
  "flag_percent": { "TRANSIENT": 2.64, "SOURCE": 97.7, "HALO": 5.89 },
  "flag_meanings": { "TRANSIENT": "Transient detected during SUR", "...": "..." } }
```

### `GET /api/releases`
```json
{ "releases": [ { "id": "spherex_dr1" }, { "id": "spherex_qr3" } ], "best": ["spherex_dr1", "spherex_qr3"], "checked": 1794633610.6 }
```
Found by probing IRSA, so a future `spherex_dr2` appears with no code change.

### `GET /api/resolve?q=Barnard's Star`
```json
{ "ra": 269.44627, "dec": 4.76820, "name": "Barnard's Star", "source": "built-in (SIMBAD)",
  "pm_corrected": true, "pmra": -801.551, "pmdec": 10362.394 }
```
Accepts names (CDS Sesame), `133.795 -7.245`, `08h55m10.8s -7d14m42s`, `08:55:10.8 -07:14:42`.
Stars with known motion are moved to where they are in 2026.

### `GET /api/health` → `{ "status": "ok" }`

## Website URL parameters (for sharing and embedding)

`/?q=Barnard's Star` · `/?ra=133.76&dec=-7.24&fov=8` · plus `view=blink|timecolours|compare|wall|color|planes`,
`mode=visit|exposure|channel`, `det=0-6`, `ch=1-102`, `math=none|first|prev|sum`, `expert=1`, `embed=1`
(bare player for an `<iframe>`), `listen=1` (Listen mode on), `mock=1` (sample data, no backend).


## Discovery board  (`routes/finds.py`)

| Endpoint | Purpose |
|---|---|
| `POST /api/finds` | report `{ra, dec, fov, query_id, x, y, kind, verification, summary, note, nickname, target, voter}`; the same spot+kind within 6″ is merged (counts as a vote). Max 15 reports/hour per IP. |
| `GET /api/finds?sort=top\|new&voter=` | list (with `my_vote` for this browser) |
| `POST /api/finds/{id}/vote` | `{voter, value: 1 \| -1 \| 0}`, one vote per browser id |

## Assistant  (`routes/ask.py`)

`POST /api/ask {question, context}` → `{answer, source: "llm" | "built-in", model}`. `GET /api/ask/status`.
Uses any OpenAI-compatible endpoint (e.g. Qwen) when `SKYSHIFT_LLM_URL` (+ `SKYSHIFT_LLM_MODEL`, `SKYSHIFT_LLM_KEY`
or `HF_TOKEN`) is set; otherwise a built-in answerer replies from the same context. The context contains only
what SkyShift loaded (details card, measured motion, spectral features, visits), never personal data.
