# SkyShift 🌌 — watch the infrared sky move

**SkyShift** is a public website for NASA's **SPHEREx** mission. Type a star's name or sky coordinates and
SkyShift gathers every SPHEREx picture of that spot, lines them up, and plays them like a **flipbook**.
Anything that **moves** (nearby stars, brown dwarfs, asteroids) or **changes brightness** (variable stars)
jumps out — the same trick that found Pluto.

It is built for **everyone first**: a *Simple* mode explains every picture in plain English, and an
*Expert* mode adds the science tools (all 6 detectors, all 102 infrared colours, spectra, flags…).

Built for the **NASA Space Apps Challenge 2026**.

**Want to try it on your own laptop?** Follow [Run SkyShift on your own computer](#run-skyshift-on-your-own-computer).
It takes about 10 minutes the first time.

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
- [x] Explore the 102 infrared bands: a true **spectral cube** (each plane = one wavelength over the whole area), 3D stack, fly-through, area spectrum
- [x] Combine data from the six detector arrays (stacked per visit, 6-panel wall, RGB colour grading in the flipbook)
- [x] Gaia and WISE overlays (Gaia moved to each picture's date)
- [x] Metadata and contamination flags
- [x] URL-based coordinate queries + embed mode
- [x] Detection and analysis: finds movers/brightness changes, checks them against Gaia/WISE/asteroids
- [x] 🔬 **Is it already known?** four-catalogue cross-check (Gaia DR3, 2MASS, AllWISE, SIMBAD), each compared at its own
  observing date, with contamination flags and an overall verdict (verification module by Meenakshi K)

**Extra features**
- [x] 🗺 **Live sky map on the home page** (Aladin Lite): the whole sky in SPHEREx false colour (dust, hot gas, stars), zoomable,
  with the challenge targets marked. 📍 Pick a spot or ⬚ draw a square and SkyShift loads every SPHEREx picture of it
- [x] ⏳ **Time machine**: 1950 and 1991 photographic plates, 2MASS (2000), WISE (2010), SPHEREx, with the predicted path
- [x] 🧊 Spectral cube, 💧 molecule/mineral finder, 🃏 details card (SIMBAD, Gaia, WISE, Wikipedia)
- [x] ☄️ **Asteroid hunter**: where each known asteroid was in every snapshot
- [x] 🔭 **Discovery board**: report finds, vote (citizen science)
- [x] 💬 **Ask about this object** (Qwen or any OpenAI-compatible model; built-in answers otherwise)
- [x] ✨ **Guided tour**, 👁 **colour-blind-safe mode**
- [x] 🔊 **Listen tab** for blind and low-vision visitors: the brightness-vs-wavelength graph is shown big *and* played as sound
  (higher, louder note = brighter; left ear = short wavelength, right ear = long), arrow keys read it point by point,
  pick any star from a spoken list, hear how the object moves, everything keyboard and screen-reader friendly
- [x] 📤 Share as animated GIF, picture card, link or embed
- [x] 🛰 Stays up to date with new NASA releases automatically; download task bar with Cancel

**Results on the challenge targets** (SPHEREx only, then checked against Gaia):

| Target | SkyShift measured | Known |
|---|---|---|
| Barnard's Star | 10.36″/yr toward 352° | 10.39″/yr toward 356° (Gaia) |
| Epsilon Indi B | 4.52″/yr toward 129° (D5+D6) | 4.68″/yr toward 122° |
| RW Aurigae | brightness changed ×2.0 between visits | known variable (young star) |
| R Draconis | brightness changed ×1.8 (4.4–5 µm) | known variable (Mira) |
| WISE 0855 | 5.87″/yr toward 269° (D5+D6; faint, so less exact) | 8.15″/yr toward 275° |

## How SkyShift stays up to date

NASA's archive (IRSA) adds SPHEREx data every week and publishes new releases, but it does not notify anyone.
So SkyShift **asks**, cheaply and often:

```
 every 6 h   watcher ──► re-detect releases (dr1, qr3, future dr2/qr4…)  ──► new one? use it automatically
 (and when   │        ──► for every cached spot: 2-second IRSA search ──► same image list?  nothing to do
 a spot is   │                                                        └─► list changed?  download ONLY the new
 opened, or  │                                                            cutouts, rebuild, version + 1
 "check now")└──► open browsers poll every 2 min ──► "🆕 NASA added 25 new pictures. Show them"
```

- Each cached spot stores a **fingerprint** of the exact IRSA files it was built from. New exposures, a new
  release, or reprocessed files all change the fingerprint.
- Visitors keep seeing the old version until the new one is ready, then it is swapped in one step.
- Gaia: the newest release online is detected daily (DR4 will be used as soon as ESA publishes it).
  SIMBAD and Wikipedia answers are refreshed daily. Asteroid positions are always computed live.
- Settings: `SKYSHIFT_WATCH_HOURS` (default 6, 0 = off), `SKYSHIFT_CHECK_MINUTES` (default 60).
- A **task bar** shows every download/update with progress, time left and a **Cancel** button; cancelling keeps
  what was already downloaded.

## Optional: AI answers with Qwen

```bash
# Hugging Face (needs a free token): 
set HF_TOKEN=hf_...                         # PowerShell: $env:HF_TOKEN="hf_..."   macOS/Linux: export HF_TOKEN=hf_...
# or a local model with Ollama:
set SKYSHIFT_LLM_URL=http://localhost:11434/v1
set SKYSHIFT_LLM_MODEL=qwen2.5:7b
```
Without either, "Ask about this object" uses built-in answers from SkyShift's own data.

## Tech stack

| Part | Tools |
|---|---|
| Frontend | React 18 + Vite, Chart.js, Aladin Lite v3 (CDS) |
| Backend | Python 3.12+, FastAPI, astropy, numpy, Pillow |
| Data | NASA IRSA SIA + cutout service (SPHEREx), ESA Gaia TAP, IRSA Gator (AllWISE), IMCCE SkyBoT, CDS Sesame |
| Deploy | Docker (one container serves the API and the built website) |

## Run SkyShift on your own computer

Anyone can run the whole website on their own laptop. Nothing has to be running anywhere else: your
computer downloads the pictures straight from NASA.

### 1. Install these once

| Program | Where to get it | Notes |
|---|---|---|
| **Git** | https://git-scm.com/downloads | To download the code |
| **Python 3.12 or newer** | https://www.python.org/downloads | Windows: tick **"Add python.exe to PATH"** in the installer |
| **Node.js 18 or newer** (LTS) | https://nodejs.org | Builds the website |

You also need an **internet connection**, because the pictures come live from NASA's archive.
Close and reopen your terminal after installing so it finds the new programs.

### 2. Download and set up (first time only, about 5 minutes)

**Windows** (PowerShell or Command Prompt):
```bat
git clone https://github.com/Kuladeep0001/SKYSHIFT.git
cd SKYSHIFT
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
cd frontend
npm install
npm run build
cd ..
```

**macOS / Linux** (Terminal):
```bash
git clone https://github.com/Kuladeep0001/SKYSHIFT.git
cd SKYSHIFT
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cd frontend && npm install && npm run build && cd ..
```

### 3. Start the website (every time)

From inside the `SKYSHIFT` folder:

| Windows | macOS / Linux |
|---|---|
| `.venv\Scripts\python -m uvicorn backend.main:app --port 8000` | `.venv/bin/python -m uvicorn backend.main:app --port 8000` |

Wait until it prints `Application startup complete`, then open **http://localhost:8000** in Chrome, Edge or Firefox.
Keep the terminal window open while you use the site. Press **Ctrl + C** in it to stop the website.

### Good to know

- **The first time you open a star, it takes 2–7 minutes.** SkyShift downloads every SPHEREx picture of
  that spot from NASA (100–550 pictures), and the task bar at the bottom shows the progress. After that the
  star is saved on your computer in `data/cache/` and opens instantly.
- **Want the 5 challenge stars ready before a demo?** Run this once and let it finish (about 20–30 minutes):
  `.venv\Scripts\python -m scripts.prewarm` (macOS/Linux: `.venv/bin/python -m scripts.prewarm`).
- **Disk space:** about 250 MB per star.
- **Each computer keeps its own copy.** Your friends' laptops download their own pictures. Discovery board
  reports are saved only on the computer that made them.
- **Get the newest version:** run `git pull`, then `cd frontend`, `npm run build`, `cd ..`, then start the
  website again. If `requirements.txt` changed, also run the `pip install` line from step 2 again.

### If something goes wrong

| What you see | What to do |
|---|---|
| `python` is not recognised, or the Microsoft Store opens | Reinstall Python and tick **"Add python.exe to PATH"**, or type `py` instead of `python` |
| `npm` or `git` is not recognised | Install it (step 1), then open a **new** terminal |
| http://localhost:8000 shows `{"detail":"Not Found"}` or a blank page | You skipped `npm run build`. Run step 2's `frontend` lines again |
| `address already in use` / `error while attempting to bind` | SkyShift is already running in another window. Use that one, or start with `--port 8001` and open http://localhost:8001 |
| "IRSA may be busy, please try again" | NASA's archive is overloaded. Wait a minute and search again; pictures already downloaded are kept |
| The sky map on the home page stays black | Wait a few seconds the first time (the colour sky is built from NASA's tiles), or pick another sky in the map's menu. If it never appears, your browser needs WebGL 2: update Chrome, Edge or Firefox, or turn on hardware acceleration (you then get a still picture instead) |
| The assistant (💬 Ask) gives short answers | That's the built-in helper. For full answers, connect Qwen (see [Optional: AI answers with Qwen](#optional-ai-answers-with-qwen)) |

### For developers

Live-reloading development uses two terminals:
```bash
pip install -r requirements-dev.txt
uvicorn backend.main:app --reload --port 8000      # API docs: http://localhost:8000/docs
```
```bash
cd frontend
npm install
npm run dev          # http://localhost:5173  (forwards /api to port 8000)
```
No backend yet? Open **http://localhost:5173/?mock=1**. The site then runs on saved sample responses.

**Docker** (what we deploy: one container serves the API and the built website):
```bash
docker build -t skyshift .
docker run -p 7860:7860 skyshift      # http://localhost:7860
```

**Tests:** `python -m pytest tests`

## Project structure

```
backend/
  main.py                   app, routers, serves the built website
  routes/
    images.py               /api/images/*      query, frames, PNGs, spectrum, compare
    analysis.py             /api/detections/*  moving-object detection
    verification.py         /api/verification/gaia, /api/catalog/*   Gaia/WISE/asteroid checks + overlays
    crossmatch.py           /api/verification/   Gaia + 2MASS + AllWISE + SIMBAD cross-check (see backend/VERIFICATION.md)
    metadata.py             /api/metadata/*, /api/releases, /api/resolve, /api/health
  services/
    spherex.py              IRSA: release discovery, image search, cutout download + cache
    image_processing.py     alignment, background removal, stacking, 102 channels, frames, spectra, compare, PNG
    jobs.py                 background download jobs, cache, versions, cancel, update checks
    watcher.py              background loop that keeps every cached spot in step with NASA
    spectral_features.py    102-channel spectrum binning + water/CO2/CO/CH4/mineral band finder
    object_info.py          details card: SIMBAD, Gaia, WISE, Wikipedia
    detection.py            movers / brightness changes / transients
    gaia.py                 Gaia DR3 + AllWISE queries, cross-matching
    solar_system.py         known asteroids (SkyBoT)
    resolver.py             names & coordinates → RA/Dec (proper-motion corrected)
  models/schemas.py         request/response models (the API contract)
frontend/
  src/App.jsx               header, Simple/Expert switch, pages
  src/pages/                Explorer (main dashboard), About (how it works)
  src/components/           ImageViewer, Timeline, CoordinateInput, Controls, BeforeAfter, Explainer,
                            CandidatesPanel, DetectorWall, SpectralCube, SpectrumPanel, MetadataPanel, SkyHome, SkyMap…
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
