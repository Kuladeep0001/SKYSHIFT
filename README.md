# SkyShift 🌌

**Watch the infrared sky move.** SkyShift is a public web tool for NASA's **SPHEREx** mission.
Type a star's name or sky coordinates, and SkyShift collects every SPHEREx picture of that spot,
lines them up, and plays them like a flipbook. Anything that **moves** (nearby stars, brown dwarfs,
asteroids) or **changes brightness** (variable stars) jumps out.

Built for the **NASA Space Apps Challenge 2026**.

```
 Browser (flipbook player, spectra, overlays, Aladin sky map)
    │   /?q=Barnard's Star   or   /?ra=133.76&dec=-7.24&fov=8   ← shareable, embeddable
    ▼
 FastAPI backend (Python + astropy)
    │   finds images → downloads small cutouts in parallel → aligns them north-up → caches
    ▼
 NASA/IPAC IRSA (SPHEREx DR1 + newest Quick Release, detected automatically)
 + ESA Gaia DR3 · NASA AllWISE · IMCCE SkyBoT · CDS Sesame
```

## Features

| Feature | What it does |
|---|---|
| **Search** | Object name or RA/Dec in any format. Fast-moving stars are centred where they are *today* (Barnard's Star has moved 4.5′ since 2000). |
| **Blink player** | Play / pause / step / speed, with the date on every frame and a timeline of every exposure. |
| **Each visit / every exposure** | Stacked picture per visit (6 months apart, for stars) or every single exposure (minutes to days apart, for asteroids). |
| **6 detectors** | Six synced players, one per detector array (0.75–5 µm). Each is stacked for better signal-to-noise. |
| **Infrared colour** | Red = 3.8–5 µm, green = 1.6–3.8 µm, blue = 0.75–1.6 µm. |
| **102 planes** | Every one of the 102 spectral channels for a visit. Click one to blink that exact wavelength over time. |
| **Add / subtract** | Each frame minus the first or previous one (movers become dark/bright pairs), or add everything up. |
| **Spectrum on the fly** | Click any pixel to get its brightness at every wavelength and date, plus a light curve. |
| **Overlays** | Gaia DR3 stars moved to each frame's date (fast movers labelled), AllWISE (2010), known asteroids (SkyBoT), contamination flags. |
| **Field of view** | 2′ to 20′. Bigger views catch faster movers but take longer to download. |
| **Share & embed** | Every view has its own URL. `?embed=1` gives a bare player for iframes. |
| **Always current** | Data releases are discovered from IRSA at runtime (`spherex_dr1`, `spherex_qr3`, and future `dr2`, …). |

## Run it locally

```bash
git clone https://github.com/<owner>/spherex-skyshift.git
cd spherex-skyshift
python -m venv .venv
.venv\Scripts\activate          # Windows   (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
uvicorn backend.app:app --reload --port 8000
```

Open http://localhost:8000. API docs: http://localhost:8000/docs

The first load of a new spot downloads ~100–360 small images from NASA (1–4 minutes).
After that it is cached in `data/cache/` and loads instantly. To pre-load the 5 challenge targets:

```bash
python -m scripts.prewarm
```

## Run with Docker

```bash
docker build -t skyshift .
docker run -p 7860:7860 skyshift
```

## Project layout

```
backend/
  app.py        web server + API routes
  sphx.py       SPHEREx at IRSA: release discovery, image search, cutout download
  imaging.py    align cutouts to one grid, flags, 102-channel mapping, stacking
  jobs.py       background download jobs, frames, spectra
  catalogs.py   name lookup, Gaia DR3, AllWISE, SkyBoT asteroids
frontend/
  index.html, style.css, app.js   the whole website (no build step)
scripts/
  prewarm.py    cache the challenge targets before a demo
```

## API

| Endpoint | Purpose |
|---|---|
| `GET /api/releases` | SPHEREx releases available at IRSA |
| `GET /api/resolve?q=` | name or coordinates → RA/Dec (proper-motion corrected) |
| `GET /api/load?ra=&dec=&fov=&rel=` | start or reuse a job → `id` |
| `GET /api/job/{id}` | progress |
| `GET /api/job/{id}/summary` | exposures, visits, the 102 channels, flag definitions |
| `GET /api/job/{id}/frames?mode=visit\|exposure\|channel\|visitdet\|planes&det=&channel=&visit=` | aligned frames (base64 float32) |
| `GET /api/job/{id}/spectrum?x=&y=` | spectrum + light curve at a pixel |
| `GET /api/catalog/{gaia\|allwise\|skybot}?ra=&dec=&radius=&mjd=` | overlays |

## Team workflow

1. `git pull` before you start.
2. Make a branch: `git checkout -b feature/my-thing`
3. Commit small, push, and open a Pull Request into `main`.
4. Don't commit `data/` (it's in `.gitignore`).

## Credits

SPHEREx data: NASA/IPAC Infrared Science Archive · Gaia DR3: ESA/Gaia/DPAC · AllWISE: NASA/JPL/IPAC ·
SkyBoT: IMCCE · Sesame & Aladin Lite: CDS Strasbourg · astropy.
