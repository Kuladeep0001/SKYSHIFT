"""Kept for routes/crossmatch.py: the Gaia DR3 matcher now lives in services/gaia.py (verification role)."""
from backend.services.gaia import *  # noqa: F401,F403
from backend.services.gaia import gaia_match  # noqa: F401
