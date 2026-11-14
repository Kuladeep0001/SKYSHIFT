# Planet X & SPHEREx: catalogue verification

> **Merged into SkyShift.** This module came from the `verification` branch (Meenakshi K). Inside SkyShift it lives at
> `backend/routes/crossmatch.py` (endpoint `POST /api/verification/`), `backend/models/verification.py` and
> `backend/services/{gaia_match,twomass,allwise,simbad,crossmatch}.py`. The website shows it as the
> **🔬 Is it already known?** panel. Changes made while merging: the AllWISE search is centred on the position at the
> AllWISE epoch (2010.5) instead of J2000 (fast movers such as Barnard's Star were missed); SIMBAD reports
> `match_quality` so it can confirm a match and prefers a star over its own planet; 2MASS, AllWISE and SIMBAD are
> queried at the same time after Gaia; IRSA timeouts are retried once; candidates may carry their own proper motion
> (`pmra_mas_yr`, `pmdec_mas_yr`) for objects Gaia cannot see, e.g. WISE 0855.

A backend system for analysing SPHEREx observations, identifying astronomical sources, and verifying candidate detections against existing astronomical catalogues.

## Overview

Planet X & SPHEREx aims to make astronomical discoveries more accessible by analysing SPHEREx infrared observations and comparing detected sources with existing astronomical data.

The backend is being developed as a modular API. Its catalogue verification component cross-matches candidate detections against Gaia DR3, 2MASS, AllWISE, and SIMBAD to determine whether a detected source has a known counterpart.

The longer-term goal is to combine positional verification, photometric analysis, and astronomical object information into a single system.

## Current Features

### Catalogue Cross-Matching

Candidate detections can be checked against:

- **Gaia DR3** — astrometric measurements, parallax, proper motion, and stellar photometry.
- **2MASS** — near-infrared J, H, and Ks measurements.
- **AllWISE** — mid-infrared W1 and W2 measurements, along with quality and contamination flags.
- **SIMBAD** — astronomical object identifiers, classifications, spectral types, and available measurements.

### Epoch-Aware Position Matching

Catalogue positions are not necessarily measured at the same reference epoch. The backend accounts for this when comparing sources.

- Gaia positions can be propagated from their reference epoch using proper motion.
- 2MASS and AllWISE positions are compared at compatible epochs where sufficient information is available.
- Matches are classified according to their angular separation from the candidate.

### Cross-Catalogue Association

The backend compares catalogue sources against the Gaia reference position and reports whether their positions are consistent, borderline, or inconsistent.

### Positional Uncertainty Analysis

Where sufficient uncertainty information is available, the system estimates combined positional uncertainties and calculates a normalized positional separation.

This provides additional context beyond simply comparing angular distances.

### Evidence-Based Assessment

Each candidate receives an overall assessment based on the available catalogue evidence.

Possible assessments include:

- `confirmed_association`
- `potential_association`
- `no_association`
- `insufficient_evidence`
- `conflicting_evidence`

Catalogue failures and inconclusive results are kept distinct from genuine non-matches.

## Project Structure

```text
vita_777/
│
├── backend/
│   ├── __init__.py
│   │
│   ├── main.py
│   │
│   ├── models/
│   │   ├── __init__.py
│   │   └── verification.py
│   │
│   ├── routes/
│   │   ├── __init__.py
│   │   └── crossmatch.py        (in SkyShift; was routes/verification.py)
│   │
│   └── services/
│       ├── __init__.py
│       ├── gaia_match.py        (in SkyShift; was services/gaia.py)
│       ├── simbad.py
│       ├── twomass.py
│       ├── allwise.py
│       └── crossmatch.py
│
├── .venv/
├── README.md
└── ...
```

### Module Responsibilities

| Module | Responsibility |
|---|---|
| `main.py` | Initialises the FastAPI application |
| `models/verification.py` | Defines request and response models |
| `routes/crossmatch.py` | Handles catalogue verification requests |
| `services/gaia_match.py` | Queries Gaia DR3 and processes astrometric data |
| `services/simbad.py` | Queries SIMBAD for object information |
| `services/twomass.py` | Retrieves and processes 2MASS measurements |
| `services/allwise.py` | Retrieves and processes AllWISE measurements |
| `services/crossmatch.py` | Compares catalogue positions and evaluates associations |

## Technologies Used

- Python 3.10
- FastAPI
- Uvicorn
- Astropy
- Astroquery / HTTP-based catalogue queries
- HTTPX
- Pydantic

## Setup and Installation

### 1. Clone the repository

```bash
git clone <repository-url>
cd vita_777
```

### 2. Create a virtual environment

```bash
python3 -m venv .venv
```

### 3. Activate the environment

macOS / Linux:

```bash
source .venv/bin/activate
```

### 4. Install dependencies

```bash
pip install -r requirements.txt
```

### 5. Start the backend

From the project root:

```bash
uvicorn backend.main:app --reload
```

The backend should now be available at:

```text
http://127.0.0.1:8000
```

## API Documentation

FastAPI automatically generates interactive API documentation.

Once the server is running, visit:

- **Swagger UI:** http://127.0.0.1:8000/docs
- **ReDoc:** http://127.0.0.1:8000/redoc

### Current Verification Endpoint

`POST /api/verification/`

Accepts candidate coordinates, observation timestamps, catalogue selections, and a matching radius.

Example request:

```json
{
  "candidates": [
    {
      "candidate_id": "candidate_001",
      "ra": 269.4512801879,
      "dec": 4.7377039028,
      "observation_time": "2026-05-14T08:32:00Z"
    }
  ],
  "catalogues": [
    "gaia",
    "2mass",
    "allwise",
    "simbad"
  ],
  "search_radius_arcsec": 6.0
}
```

Coordinates are provided in decimal degrees, observation times in ISO 8601 UTC, and matching radii in arcseconds.

The response contains individual catalogue results, an overall candidate assessment, an evidence summary, and cross-catalogue association information.

## Planned Development

The following features are intended extensions and are not yet implemented:

- **Photometric validation:** Combine measurements from different catalogues, calculate colours, preserve upper limits, and prepare spectral energy distributions (SEDs).
- **Object identification:** Resolve identified sources into readable astronomical profiles containing object type, spectral classification, distance, temperature, and other available properties.
- **NASA Exoplanet Archive integration:** Retrieve known host-star properties and associated planetary systems.
- **NASA image integration:** Retrieve relevant astronomical images and media for identified objects.
- **Improved association analysis:** Extend cross-matching to additional catalogue pairs and improve uncertainty modelling.

## Data Sources

- [Gaia Archive](https://gea.esac.esa.int/archive/)
- [2MASS / IRSA](https://irsa.ipac.caltech.edu/Missions/2mass.html)
- [AllWISE / IRSA](https://irsa.ipac.caltech.edu/Missions/wise.html)
- [SIMBAD Astronomical Database](https://simbad.cds.unistra.fr/simbad/)
- [NASA Exoplanet Archive](https://exoplanetarchive.ipac.caltech.edu/)
- [NASA Image and Video Library](https://images.nasa.gov/)

## Notes

- A candidate ID is an identifier generated by this project; it is not a catalogue source ID.
- A nearby catalogue source is not automatically considered a confirmed counterpart.
- Missing catalogue responses are treated as inconclusive rather than as non-detections.
- Cross-catalogue consistency does not necessarily imply independent confirmation, since different catalogues may contain measurements of the same underlying astronomical source.
- Derived quantities and positional comparisons should be interpreted with their associated uncertainties and assumptions.

---

*Planet X & SPHEREx — Exploring infrared observations and the objects behind them.*
