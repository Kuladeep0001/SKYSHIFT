# SkyShift 🌌 — watch the infrared sky move

**SkyShift** is a public website for NASA's **SPHEREx** mission. Type a star's name or sky coordinates and
SkyShift gathers every SPHEREx picture of that spot, lines them up, and plays them like a **flipbook**.
Anything that **moves** (nearby stars, brown dwarfs, asteroids) or **changes brightness** (variable stars)
jumps out — the same trick that found Pluto.

It is built for **everyone first**: a *Simple* mode explains every picture in plain English, and an
*Expert* mode adds the science tools (all 6 detectors, all 102 infrared colours, spectra, flags…).

Built for the **NASA Space Apps Challenge 2026**.

```
 Frontend (React)       search · flipbook · before/after · explanations · expert tools
        │  REST API  (see API_DOCUMENTATION.md)
        ▼
 Backend (FastAPI)      SPHEREx data · image processing · detection · verification
        │
        ▼
 External data          NASA IRSA (SPHEREx DR1 + newest Quick Release) · ESA Gaia DR3 · NASA AllWISE
                        · IMCCE SkyBoT (asteroids) · CDS Sesame (names) & Aladin (sky map)
```

## Checklist (from the team plan)

**Must have**
- [x] Accept RA and declination coordinates (any format) — or a star's name
- [x] Retrieve SPHEREx images for the selected sky region
- [x] Display images from different observation times
- [x] Play through the images like a video

**Good to have**
- [x] Selectable field of view (2′–20′)
- [x] Compare or subtract images from different epochs (before/after slider, − first, − previous, add all)
- [x] Explore the 102 infrared bands (grid of all 102 + "same colour over time")
- [x] Combine data from the six detector arrays (stacked per visit, 6-panel wall, infrared colour)
- [x] Gaia and WISE overlays (Gaia moved to each picture's date)
- [x] Metadata and contamination flags
- [x] URL-based coordinate queries + embed mode
- [x] Detection and analysis: finds movers/brightness changes, checks them against Gaia/WISE/asteroids

**Results on the challenge targets** (SPHEREx only, then checked against Gaia):

| Target | SkyShift measured | Known |
|---|---|---|
| Barnard's Star | 10.36″/yr toward 352° | 10.39″/yr toward 356° (Gaia) |
| Epsilon Indi B | 4.45″/yr toward 128° | 4.68″/yr toward 122° |
| RW Aurigae | brightness changed ×2.0 between visits | known variable (young star) |
| R Draconis | brightness changed ×1.8 (4.4–5 µm) | known variable (Mira) |
| WISE 0855 | visible in detector D6; too faint in the first visit to measure motion | 8.1″/yr |

## Tech stack

| Part | Tools |
|---|---|
| Frontend | React 18 + Vite, Chart.js, Aladin Lite v3 (CDS) |
| Backend | Python 3.12+, FastAPI, astropy, numpy, Pillow |
| Data | NASA IRSA SIA + cutout service (SPHEREx), ESA Gaia TAP, IRSA Gator (AllWISE), IMCCE SkyBoT, CDS Sesame |
| Deploy | Docker (one container serves the API and the built website) |

## Run it locally

**Backend** (Python 3.11+):
```bash
git clone https://github.com/Kuladeep0001/SKYSHIFT.git
cd SKYSHIFT
python -m venv .venv
.venv\Scripts\activate            # Windows   (macOS/Linux: source .venv/bin/activate)
pip install -r requirements-dev.txt
uvicorn backend.main:app --reload --port 8000      # API docs: http://localhost:8000/docs
```

**Frontend** (Node 18+), in a second terminal:
```bash
cd frontend
npm install
npm run dev          # http://localhost:5173  (forwards /api to port 8000)
```
No backend yet? Open **http://localhost:5173/?mock=1** — the site runs on saved sample responses.

**Everything in one** (what we deploy): `cd frontend && npm run build`, then the backend serves the site at
http://localhost:8000. Or with Docker:
```bash
docker build -t skyshift .
docker run -p 7860:7860 skyshift
```

The first load of a new spot downloads 100–450 small images from NASA (1–4 minutes); after that it is cached in
`data/cache/`. Before a demo: `python -m scripts.prewarm` (caches the 5 challenge targets).

**Tests:** `python -m pytest tests`

## Project structure

```
backend/
  main.py                   app, routers, serves the built website
  routes/
    images.py               /api/images/*      query, frames, PNGs, spectrum, compare
    analysis.py             /api/detections/*  moving-object detection
    verification.py         /api/verification/*, /api/catalog/*   Gaia/WISE/asteroid checks + overlays
    metadata.py             /api/metadata/*, /api/releases, /api/resolve, /api/health
  services/
    spherex.py              IRSA: release discovery, image search, cutout download + cache
    image_processing.py     alignment, background removal, stacking, 102 channels, frames, spectra, compare, PNG
    jobs.py                 background download jobs + cache
    detection.py            movers / brightness changes / transients
    gaia.py                 Gaia DR3 + AllWISE queries, cross-matching
    solar_system.py         known asteroids (SkyBoT)
    resolver.py             names & coordinates → RA/Dec (proper-motion corrected)
  models/schemas.py         request/response models (the API contract)
frontend/
  src/App.jsx               header, Simple/Expert switch, pages
  src/pages/                Explorer (main dashboard), About (how it works)
  src/components/           ImageViewer, Timeline, CoordinateInput, Controls, BeforeAfter, Explainer,
                            CandidatesPanel, DetectorWall, PlanesGrid, SpectrumPanel, MetadataPanel, SkyMap…
  src/lib/                  api.js (all API calls + mock mode), frames.js, render.js, targets.js
  public/mock/              saved API responses for ?mock=1
tests/                      pytest: resolver, image processing, detection, API contract
sample_data/                real SPHEREx cutouts (one per detector) for backend experiments
scripts/                    prewarm.py (cache demo targets), make_mocks.py (refresh mock JSON)
API_DOCUMENTATION.md        every endpoint, inputs, outputs, errors
INTEGRATION_PLAN.md         who owns what, dependencies, milestones
```

## Team

| Role | Name | Owns |
|---|---|---|
| UI 1 — dashboard, layout, coordinate input | _add name_ | `App.jsx`, `pages/`, `CoordinateInput.jsx` |
| UI 2 — image viewer, timeline, playback | _add name_ | `components/` |
| Verification — Gaia/WISE cross-matching | _add name_ | `services/gaia.py`, `routes/verification.py` |
| Feature dev 1 — SPHEREx retrieval, processing, comparison | _add name_ | `services/spherex.py`, `routes/images.py`, `services/image_processing.py` |
| Feature dev 2 — detection and analysis | _add name_ | `services/detection.py`, `routes/analysis.py` |
| Integration lead — API, integration, tests, deployment | _add name_ | `main.py`, `models/`, `tests/`, Docker |

Git workflow: one branch per role (`frontend-dashboard`, `frontend-viewer`, `feature-spherex-retrieval`,
`feature-image-processing`, `feature-detection`, `feature-gaia-verification`) → Pull Request → integration lead
merges into `main`. Never commit `data/`. See INTEGRATION_PLAN.md.

## Credits

SPHEREx data: NASA/IPAC Infrared Science Archive · Gaia DR3: ESA/Gaia/DPAC · AllWISE: NASA/JPL/IPAC ·
SkyBoT: IMCCE · Sesame & Aladin Lite: CDS Strasbourg · astropy.
