# Integration plan

A first working version of every module already exists on `main`, so **nobody starts from zero**.
Each person takes ownership of their files, improves them on their own branch, and merges through a Pull Request.

## Who owns what

| Role | Branch | Files | Already works | Next improvements |
|---|---|---|---|---|
| **UI 1**: dashboard, layout, input | `frontend-dashboard` | `src/App.jsx`, `src/pages/*`, `components/CoordinateInput.jsx`, `components/Explainer.jsx` | Simple/Expert modes, search, target cards, welcome page, URL sharing | Mobile polish, onboarding tour, accessibility pass, "share to social" image |
| **UI 2**: viewer, timeline, playback | `frontend-viewer` | `components/ImageViewer.jsx`, `Timeline.jsx`, `Controls.jsx`, `BeforeAfter.jsx`, `DetectorWall.jsx`, `SpectralCube.jsx`, `SpectrumPanel.jsx` | Flipbook, overlays, before/after slider, 6 detectors, 102 planes, spectra | Zoom/pan on the picture, GIF export, smoother blink transitions |
| **Feature dev 1**: SPHEREx retrieval and processing | `feature-spherex-retrieval`, `feature-image-processing` | `services/spherex.py`, `services/image_processing.py`, `services/jobs.py`, `routes/images.py` | IRSA search, parallel cutouts, cache, alignment, background removal, stacking, compare | Faster loads (fewer/larger cutouts, progressive frames), PSF-matched subtraction |
| **Feature dev 2**: detection and analysis | `feature-detection` | `services/detection.py`, `routes/analysis.py` | Movers + brightness changes; Barnard 10.36″/yr, Eps Ind B 4.45″/yr | Use all visit pairs, asteroid tracklets, ML artefact filter (XGBoost) |
| **Verification** (Meenakshi K) | `verification` (merged) | `services/gaia.py`, `routes/verification.py` (/api/verification/), `routes/crossmatch.py` (/api/crossmatch/), `services/{photometric_validation,object_profile,exoplanet_archive}.py`; SkyShift's own overlay/candidate checks live in `services/sky_catalogs.py` + `routes/checks.py` (Integration lead) so the two never overwrite each other; also `models/verification.py`, `services/{gaia_match,twomass,allwise,simbad,crossmatch}.py` | Gaia DR3 (moved to the date), AllWISE, SkyBoT; four-catalogue epoch-aware cross-check with evidence summary | CatWISE2020 motions, photometric SEDs from 2MASS + AllWISE + SPHEREx, NASA Exoplanet Archive |
| **Integration lead** | `main` | `backend/main.py`, `models/schemas.py`, `routes/metadata.py`, `tests/`, `Dockerfile`, docs | Routes wired, 20 tests, Docker, mock data | Deployment, CI (run tests on every PR), keep API docs in sync |

## How the pieces depend on each other

```
resolver ─┐
          ▼
spherex.py ──► jobs.py ──► image_processing.py ──► routes/images.py ──► frontend viewer
                                     │
                                     ├──► detection.py ──► routes/analysis.py ──► CandidatesPanel
                                     │                          │
sky_catalogs.py / solar_system.py ───┴──► routes/checks.py ◄───────────────────┘
```

- The **frontend never waits for the backend**: `?mock=1` serves saved responses from `frontend/public/mock/`.
  Regenerate them after an API change with `python -m scripts.make_mocks`.
- **Backend devs** can test on real cutouts in `sample_data/fits/` without hitting NASA.
- **The API contract is `backend/models/schemas.py` + `API_DOCUMENTATION.md`.** Change both in the same PR,
  and tell the UI team.

## Rules

1. `git pull origin main` before starting; work on your branch; open a PR into `main`.
2. Run `python -m pytest tests` (backend) and `npm run build` (frontend) before opening a PR.
3. Never commit `data/`, `node_modules/`, `frontend/dist/`.
4. Small PRs, merged often. The integration lead merges.

## Milestones (48 hours)

| When | Milestone | Status |
|---|---|---|
| Hour 0–4 | Repo, structure, docs, API contract, mock data | ✅ done |
| Hour 4–12 | Must-haves end to end: coordinates → SPHEREx images → flipbook | ✅ done |
| Hour 12–16 | **Deploy a public link** (Hugging Face Spaces / Render); pre-cache the 5 targets | ⏳ next |
| Hour 16–30 | Good-to-haves polished (each owner's "next improvements" column) | |
| Hour 30–36 | Freeze features. Test on phones and slow connections; fix bugs | |
| Hour 36–42 | Demo video (2–3 min) and slides; screenshots of each challenge target | |
| Hour 42–48 | Buffer. Final deploy, submit link + video | |

## Demo script (for the video)

1. Simple mode → **Barnard's Star** → press play: "the dot moves north".
2. **Before / after** slider.
3. **Find moving things** → "✓ Confirmed by Gaia: 10.39″/yr; SkyShift measured 10.36″/yr from SPHEREx alone."
4. **Epsilon Indi B** in the reddest colours: two brown dwarfs drifting.
5. **R Draconis**: brightness changes; switch to Expert → light curve and spectrum.
6. Expert → **102 colours** grid → click a plane → same-colour blink.
7. Copy the link / embed code: works on any website.
