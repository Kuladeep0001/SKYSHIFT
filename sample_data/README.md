# Sample data

- `fits/` — six real SPHEREx Level-2 cutouts of Barnard's Star (one per detector, D1–D6), as SkyShift stores
  them (IMAGE, FLAGS, VARIANCE, ZODI, WCS-WAVE; the large PSF table removed). Open with astropy:
  ```python
  from astropy.io import fits
  from astropy.wcs import WCS
  h = fits.open("sample_data/fits/barnard_D3_2025W33_2C_0321_1.fits")
  sky = WCS(h["IMAGE"].header)                       # pixel -> RA/Dec
  wave = WCS(h["IMAGE"].header, fobj=h, key="W")     # pixel -> wavelength, bandwidth (µm)
  ```
- Mock API responses for the frontend live in `frontend/public/mock/` (open the site with `?mock=1`).
  Refresh both with `python -m scripts.make_mocks`.
