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

### `GET /api/images/{query_id}/frames`
Aligned pixel data for the interactive viewer.

| param | values | meaning |
|---|---|---|
| `mode` | `visit` (default) | one stacked frame per visit |
| | `exposure` | every single exposure (best for asteroids) |
| | `channel` | per visit, only exposures in one of the **102 channels** (same wavelength over time) |
| | `visitdet` | per visit **and** per detector (for the 6-detector wall / colour image) |
| | `planes` | all 102 channels for **one** visit |
| `det` | 0–6 | 0 = all detectors |
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

## Verification  (`routes/verification.py`, owner: Verification developer)

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

`verification_status`: `known_mover` (Gaia, >100 mas/yr) · `known_star` (Gaia or WISE) · `known_asteroid`
(SkyBoT, for `transient`/`appeared`) · `unmatched` (not in any catalogue — worth a human look!) · `pending`
(archives unreachable). Gaia positions are moved to the candidate's date using proper motion.

### `GET /api/catalog/{gaia|allwise|skybot}?ra=&dec=&radius=&mjd=`
Overlay data. `radius` in degrees (≤ 0.5). `skybot` needs `mjd`.
```json
{ "catalog": "Gaia DR3", "epoch": 2016.0, "source": "ESA Gaia archive", "band": "G",
  "stars": [ { "id": "4472832130942575872", "ra": 269.4485, "dec": 4.7394, "pmra": -801.55, "pmdec": 10362.39,
               "plx": 546.98, "mag": 8.19 } ] }
```
SkyBoT returns `{ "catalog": "SkyBoT", "mjd": ..., "objects": [ { "name", "ra", "dec", "class", "mag", "dra", "ddec" } ] }`.

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

`/?q=Barnard's Star` · `/?ra=133.76&dec=-7.24&fov=8` · plus `view=blink|compare|wall|color|planes`,
`mode=visit|exposure|channel`, `det=0-6`, `ch=1-102`, `math=none|first|prev|sum`, `expert=1`, `embed=1`
(bare player for an `<iframe>`), `mock=1` (sample data, no backend).
