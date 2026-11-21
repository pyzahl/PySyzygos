# PySyzygos

<img src="https://raw.githubusercontent.com/pyzahl/PySyzygos/main/src/pysyzygos/pysyzygos_logo.png" alt="PySyzygos logo" width="96" align="right">

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.23149371.svg)](https://doi.org/10.5281/zenodo.23149371)

**Stellar occultations by asteroids, planets and moons, predicted for your own observing site.** PySyzygos finds the
events your telescope can catch: JPL orbits (or Lucky Star's NIMA for TNOs), a local Gaia DR3 star catalog, the exact
geometry in a fundamental plane through your site, and a local web interface to plan, run and keep track of it all.
Free software (GPL-3.0-or-later), for Linux, macOS and Windows; works offline in the field once set up.

*Syzygos* (Greek σύζυγος, "yoked together"): for a few seconds the observer, the asteroid and the star stand in
one line.

**The full documentation is on GitHub: [README](https://github.com/pyzahl/PySyzygos#readme).** This page is a short
summary for PyPI.

## What it does

- **Pick** the best events among all ~465,000 asteroids with H < 17 for a site and a time window (optionally from a
  shared whole-Earth pre-screen), by asteroid group (NEOs, Trojans, TNOs, ...) and your telescope's star limit.
- **Search** them exactly: Gaia DR3 astrometry with parallax, proper-motion corrections and light deflection, the
  light time from your site, your height and horizon, the path uncertainty across the track and the chance that the
  shadow covers you.
- **Results and favorites**: a filterable table, maps (KML for Google Earth), star-field previews, a globe view,
  KStars / Stellarium pointing, known satellites, double and variable stars (WDS, AAVSO VSX), cloud forecast,
  OccultWatcher Cloud feeds, an SQL filter.
- **Observations**: IOTA report forms, chord plots of observed events, the IOTA observation archive with our
  predictions checked against 27,000 observed chords.
- Validated against Occult and OccultWatcher: see
  [VERIFICATION.md](https://github.com/pyzahl/PySyzygos/blob/main/VERIFICATION.md).

## Install

```bash
pipx install pysyzygos          # or: uv tool install pysyzygos   (or pip install pysyzygos in a venv)
pysyzygos setup                 # once: kernels, the star catalog, your site (asks where to keep the data)
pysyzygos                       # the web interface in your browser
```

Python 3.11 or newer. The first setup downloads the JPL kernels and a ready-made Gaia catalog (G ≤ 16,
from Zenodo); see [Install](https://github.com/pyzahl/PySyzygos#install) and
[Getting started](https://github.com/pyzahl/PySyzygos/blob/main/GETTING_STARTED.md).

## Updates

PyPI carries the releases (x.y.0, each archived on Zenodo with a DOI): `pysyzygos update` (or the System tab's
**Update**) upgrades with the tool you installed with (pipx, uv tool or pip). The **developer version**, with every
fix between releases, is the GitHub repository: clone it and run `uv run pysyzygos`; updates are then a `git pull`
(also from the System tab). Details: [README, Install](https://github.com/pyzahl/PySyzygos#install).

## Documentation

- [README](https://github.com/pyzahl/PySyzygos#readme): everything, section by section
- [Getting started](https://github.com/pyzahl/PySyzygos/blob/main/GETTING_STARTED.md): a first night, step by step
- [ABOUT](https://github.com/pyzahl/PySyzygos/blob/main/ABOUT.md): how the predictions are computed, and the sources
- [The mathematics](https://github.com/pyzahl/PySyzygos/tree/main/docs/math): slides with numbered formulas (PDF with
  each release)
- [Verification](https://github.com/pyzahl/PySyzygos/blob/main/VERIFICATION.md) and
  [Changelog](https://github.com/pyzahl/PySyzygos/blob/main/CHANGELOG.md)

## Citing

Please cite the Zenodo record: [doi:10.5281/zenodo.23149371](https://doi.org/10.5281/zenodo.23149371) (all versions;
each release has its own DOI). See
[CITATION.cff](https://github.com/pyzahl/PySyzygos/blob/main/CITATION.cff).

## License

GNU General Public License v3 or later. Copyright (C) 2026 Percy Zahl.
