# SkyShift — watch the infrared sky move

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
- [x] **Is it already known?** four-catalogue cross-check (Gaia DR3, 2MASS, AllWISE, SIMBAD), each compared at its own
  observing date, with contamination flags and an overall verdict (verification module by Meenakshi K)

**Extra features**
- [x] **Live sky map on the home page** (Aladin Lite): the whole sky in SPHEREx false colour (dust, hot gas, stars), zoomable,
  with the challenge targets marked. Pick a spot or draw a square and SkyShift loads every SPHEREx picture of it
- [x] **Time machine**: 1950 and 1991 photographic plates, 2MASS (2000), WISE (2010), SPHEREx, with the predicted path
- [x] Spectral cube, molecule/mineral finder, details card (SIMBAD, Gaia, WISE, Wikipedia)
- [x] **Asteroid hunter**: where each known asteroid was in every snapshot
- [x] **Discovery board**: report finds, vote (citizen science)
- [x] **Ask about this object** (Qwen or any OpenAI-compatible model; built-in answers otherwise)
- [x] **Technical report (PDF)** for researchers: data, processing, detections with motion fits, identification in 4 catalogues
  + exoplanets, spectrum, light curve, validation, references, and appendices (every channel, exposure and flag); view or download
- [x] **Guided tour**
- [x] **Listen mode** for blind and low-vision visitors: a **voice conversation**, no buttons. SkyShift says what you can
  say, then listens: *describe*, *play*, *motion*, *list*, *star 2*, *go to Vega*, *slower*, *stop*, *help*, or any
  question (answered from SkyShift's data). The brightness graph plays slowly as **3D sound** (short wavelengths in the
  left ear, long in the right; higher, louder = brighter), and a moving star's sound travels from one ear to the other
  the way it moves in the picture. Keys work too (T, P, D, M, L, N, R, H, Esc)
- [x] **Natural voice**: everything read aloud by a calm, deep English "butler" neural voice (or a friendlier one, or the
  device's own voice offline), with symbols spoken as words (µm → microns, ″ → arcseconds)
- [x] Share as animated GIF, picture card, link or embed
- [x] Stays up to date with new NASA releases automatically; download task bar with Cancel

**Results on the challenge targets** (SPHEREx pictures only, then compared with the catalogues; worked out live at
`/api/validation` and shown on the website's *How it works* page):

| Target | SkyShift measured | Known | Difference |
|---|---|---|---|
| Barnard's Star | 10.37 ± 0.43″/yr toward 353° (fit through 3 visits) | 10.39″/yr toward 356° | 0.3% (0.1σ) |
| Epsilon Indi B | 4.54 ± 0.38″/yr toward 125° (4 visits, D5+D6) | 4.68″/yr toward 122° | 3.2% (0.4σ) |
| WISE 0855 | 6.06 ± 1.36″/yr toward 268° (3 visits, D5+D6) | 8.15″/yr toward 275° | 26% (1.5σ, blended with a background star) |
| RW Aurigae | brightness changed 1.7× between visits, stayed in place | known T Tauri variable | agrees |
| R Draconis | brightness changed 1.38× (3.8–5 µm), stayed in place | known Mira variable | agrees |

## How SkyShift stays up to date

NASA's archive (IRSA) adds SPHEREx data every week and publishes new releases, but it does not notify anyone.
So SkyShift **asks**, cheaply and often:

```
 every 6 h   watcher ──re-detect releases (dr1, qr3, future dr2/qr4…)  ──new one? use it automatically
 (and when   │        ──for every cached spot: 2-second IRSA search ──same image list?  nothing to do
 a spot is   │                                                        └─list changed?  download ONLY the new
 opened, or  │                                                            cutouts, rebuild, version + 1
 "check now")└──open browsers poll every 2 min ──"NASA added 25 new pictures. Show them"
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
computer downloads the pictures straight from NASA. No accounts, keys or passwords are needed.

### What you need

**Your computer**

| | Minimum | Notes |
|---|---|---|
| Operating system | Windows 10/11, macOS 12+, or Linux | |
| Memory (RAM) | 4 GB (8 GB recommended) | A star's pictures are held in memory while you look at them |
| Free disk space | about 1 GB to start, plus about 250 MB per star you open | Pictures are saved in `data/cache/` so they open instantly next time |
| Internet | Needed | Pictures, catalogues and the natural voice all come from online archives |
| Browser | **Chrome or Edge** (recommended), Firefox or Safari | Voice commands in Listen mode need Chrome, Edge or Safari. The colour sky map needs WebGL 2 |
| For Listen mode | Headphones and a microphone | Headphones give the 3D sound (left ear to right ear); the microphone lets you talk to SkyShift |

**Programs to install once**

| Program | Version | Where to get it | Notes |
|---|---|---|---|
| **Git** | any recent | https://git-scm.com/downloads | Downloads the code |
| **Python** | **3.12, 3.13 or 3.14** | https://www.python.org/downloads | Windows: tick **"Add python.exe to PATH"** in the installer |
| **Node.js** | **20 LTS** recommended (18 or newer works) | https://nodejs.org | Builds the website (comes with `npm`) |

**Installed for you in step 2** (you don't download these yourself)

Python packages, from `requirements.txt`:

| Package | Version | What SkyShift uses it for |
|---|---|---|
| `fastapi` | 0.115+ | The web server and its API |
| `uvicorn[standard]` | 0.30+ | Runs the web server |
| `astropy` | 6.1+ | Sky coordinates, FITS images and the archive searches |
| `numpy` | 1.26+ | All the picture maths |
| `requests`, `httpx` | 2.31+, 0.27+ | Talking to NASA and the catalogues |
| `pillow` | 10+ | Making PNG pictures and the share cards |
| `reportlab` | 4.0+ | The technical report (PDF) |
| `edge-tts` | 7.0+ | The natural "butler" reading voice (without it, the browser's own voice is used) |

Extra packages for developers and tests, from `requirements-dev.txt`: `pytest` 8+, `pypdf` 4+ (reads the
report in the tests), `astropy-healpix` 1+ (only for `scripts/render_allsky.py`).

Website packages, from `frontend/package.json`: `react` and `react-dom` 18.3, `chart.js` 4.4 (graphs),
`gifenc` (animated GIFs), and `vite` 5.4 with `@vitejs/plugin-react` (builds the site). The sky map
(Aladin Lite) loads from CDS in the browser, so it needs no install.

**Online services SkyShift talks to** (all free, no sign-up)

| Service | Used for |
|---|---|
| NASA/IPAC IRSA (SIA and cutouts) | The SPHEREx pictures, DR1 and Quick Releases; also 2MASS and AllWISE |
| ESA Gaia archive | Star positions, motions and distances (Gaia DR3) |
| CDS Sesame and SIMBAD | Finding stars by name; what an object is |
| NASA Exoplanet Archive | Known planets around a star |
| IMCCE SkyBoT | Asteroids and comets in the picture |
| Wikipedia | The plain-English summary of an object |
| Microsoft neural voices (through `edge-tts`) | The reading voice. Only the sentence being spoken is sent |
| Your browser's speech recognition (Google in Chrome, Microsoft in Edge) | Hearing your voice commands in Listen mode |
| Hugging Face or Ollama (optional) | Full AI answers in "Ask" (see [Optional: AI answers with Qwen](#optional-ai-answers-with-qwen)) |

### 1. Install the programs, then check them

Install Git, Python and Node.js from the table above. Close and reopen your terminal, then check that it finds them:

```bash
git --version
python --version      # macOS/Linux: python3 --version   (needs 3.12 or newer)
node --version        # needs v18 or newer (v20 recommended)
npm --version
```

### 2. Download and set up (first time only, about 5 minutes)

**Windows** (PowerShell or Command Prompt):
```bat
git clone https://github.com/Kuladeep0001/SKYSHIFT.git
cd SKYSHIFT
python -m venv .venv
.venv\Scripts\python -m pip install --upgrade pip
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
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
cd frontend && npm install && npm run build && cd ..
```

Want a different branch (for example the `uiv` design)? Run `git checkout uiv` right after `cd SKYSHIFT`,
then carry on with the other lines.

### 3. Start the website (every time)

From inside the `SKYSHIFT` folder:

| Windows | macOS / Linux |
|---|---|
| `.venv\Scripts\python -m uvicorn backend.main:app --port 8000` | `.venv/bin/python -m uvicorn backend.main:app --port 8000` |

Wait until it prints `Application startup complete`, then open **http://localhost:8000** in Chrome or Edge.
Keep the terminal window open while you use the site. Press **Ctrl + C** in it to stop the website.

### 4. Using Listen mode (for blind and low-vision visitors)

1. Put on headphones, then press **Listen mode** at the top of the page (or open the **Listen** tab).
2. The first time, the browser asks to use your **microphone**: choose **Allow**.
3. SkyShift first reads out the commands you can give, then says which star you're at. A **soft chime** means
   it's listening: just talk. *describe*, *play*, *motion*, *list*, *star 2*, *go to Vega*, *slower*, *stop*,
   *repeat*, *help*, or ask any question. It reads nothing about the star until you ask, and after every answer
   it chimes and listens again. Press **Esc** to stop it talking.
4. No microphone, or using Firefox? Use the keys instead: **T** talk, **P** or **Space** play, **D** describe,
   **M** motion, **L** list, **N** next star, **R** repeat, **H** help, **Esc** stop.

### Settings (optional)

Set these before starting the website (Windows PowerShell: `$env:NAME="value"`; Command Prompt:
`set NAME=value`; macOS/Linux: `export NAME=value`).

| Setting | Default | What it does |
|---|---|---|
| `SKYSHIFT_CACHE` | `data/cache` | Where downloaded pictures are kept |
| `SKYSHIFT_VOICE_CACHE` | `data/voice` | Where spoken sentences are kept (so repeats play instantly) |
| `SKYSHIFT_WATCH_HOURS` | `6` | How often to check NASA for new releases (`0` = never) |
| `SKYSHIFT_CHECK_MINUTES` | `60` | Re-check a spot for new pictures when it was opened longer ago than this |
| `HF_TOKEN` | not set | A free Hugging Face token: full AI answers in "Ask" (Qwen) |
| `SKYSHIFT_LLM_URL`, `SKYSHIFT_LLM_MODEL`, `SKYSHIFT_LLM_KEY` | not set | Use another AI model instead (for example a local Ollama) |
| `PORT` | `7860` | Only for Docker: the port the container listens on |

### Good to know

- **The first time you open a star, it takes 2–7 minutes.** SkyShift downloads every SPHEREx picture of
  that spot from NASA (100–550 pictures), and the task bar at the bottom shows the progress. After that the
  star is saved on your computer in `data/cache/` and opens instantly.
- **Want the 5 challenge stars ready before a demo?** Run this once and let it finish (about 20–30 minutes):
  `.venv\Scripts\python -m scripts.prewarm` (macOS/Linux: `.venv/bin/python -m scripts.prewarm`).
- **Each computer keeps its own copy.** Your friends' laptops download their own pictures. Discovery board
  reports are saved only on the computer that made them.
- **Get the newest version:** run `git pull`, then the `pip install -r requirements.txt` line from step 2
  (new packages are sometimes added), then `cd frontend`, `npm install`, `npm run build`, `cd ..`, and start
  the website again.

### If something goes wrong

| What you see | What to do |
|---|---|
| `python` is not recognised, or the Microsoft Store opens | Reinstall Python and tick **"Add python.exe to PATH"**, or type `py` instead of `python` |
| `npm` or `git` is not recognised | Install it (step 1), then open a **new** terminal |
| http://localhost:8000 shows `{"detail":"Not Found"}` or a blank page | You skipped `npm run build`. Run step 2's `frontend` lines again |
| `address already in use` / `error while attempting to bind` | SkyShift is already running in another window. Use that one, or start with `--port 8001` and open http://localhost:8001 |
| "IRSA may be busy, please try again" | NASA's archive is overloaded. Wait a minute and search again; pictures already downloaded are kept |
| The sky map on the home page stays black | Wait a few seconds the first time (the colour sky is built from NASA's tiles), or pick another sky in the map's menu. If it never appears, your browser needs WebGL 2: update Chrome, Edge or Firefox, or turn on hardware acceleration (you then get a still picture instead) |
| The reading voice sounds robotic | The natural voice needs the `edge-tts` package and internet. Run the `pip install -r requirements.txt` line from step 2 again, then restart the website |
| Listen mode doesn't hear me | Use **Chrome or Edge** (Firefox can't hear voice commands). Allow the microphone: click the lock icon left of the address, set **Microphone** to **Allow**, reload, and press **T**. Check that the right microphone is chosen in your computer's sound settings |
| No 3D sound, or it's in both ears | Use headphones (speakers mix both sides) and make sure mono audio is turned off in your computer's accessibility settings |
| `npm install` fails with `EACCES` or `permission denied` | Don't use `sudo`. Make sure you're inside the `SKYSHIFT/frontend` folder you cloned, which you own |
| `pip install` fails building `astropy` or `numpy` | Your Python is too old or too new for the ready-made packages. Install Python 3.12 or 3.13 and repeat step 2 |
| The assistant (Ask) gives short answers | That's the built-in helper. For full answers, connect Qwen (see [Optional: AI answers with Qwen](#optional-ai-answers-with-qwen)) |

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
| Verification — catalogue cross-matching, photometry, exoplanets | Meenakshi K | `services/gaia.py`, `services/{twomass,allwise,simbad,crossmatch,photometric_validation,object_profile,exoplanet_archive}.py`, `routes/verification.py`, `routes/crossmatch.py` |
| Feature dev 1 — SPHEREx retrieval, processing, comparison | _add name_ | `services/spherex.py`, `routes/images.py`, `services/image_processing.py` |
| Feature dev 2 — detection and analysis | _add name_ | `services/detection.py`, `routes/analysis.py` |
| Integration lead — API, integration, tests, deployment | _add name_ | `main.py`, `models/`, `tests/`, Docker |

Git workflow: one branch per role (`frontend-dashboard`, `frontend-viewer`, `feature-spherex-retrieval`,
`feature-image-processing`, `feature-detection`, `feature-gaia-verification`) → Pull Request → integration lead
merges into `main`. Never commit `data/`. See INTEGRATION_PLAN.md.

## Credits

SPHEREx data: NASA/IPAC Infrared Science Archive · Gaia DR3: ESA/Gaia/DPAC · AllWISE: NASA/JPL/IPAC ·
SkyBoT: IMCCE · Sesame & Aladin Lite: CDS Strasbourg · astropy.
