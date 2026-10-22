# PySyzygos: computation reference

How PySyzygos computes its predictions, where its data comes from, how it was validated ([VERIFICATION.md](VERIFICATION.md)) and what is still under active development.
Data comes from Gaia DR3 (stars), JPL Horizons and SBDB (asteroid orbits and sizes) and NAIF SPICE kernels
(planets, Earth orientation); see Part 4. Usage is in `README.md`; to contribute, see `CONTRIBUTING.md`.
Updated 2026-10-08.

PySyzygos is a portable occultation predictor in Python. It finds asteroid occultations of Gaia stars for one
observer site. Its name comes from Greek *sýzygos* (σύζυγος), "yoked together" (*syn* "together", *zygón* "yoke"),
the root of the astronomers' *syzygy*, three celestial bodies in a straight line, as observer, asteroid and star are
during an occultation. Up to version 0.18 it was called PyOccult.

---

## Contents

- [Part 1: The tools and how they fit together](#part-1-the-tools-and-how-they-fit-together)
- [Part 2: The prediction (pysyzygos/search.py)](#part-2-the-prediction-pysyzygossearchpy)
  - [2.1 Pipeline (corridor mode, the default)](#21-pipeline-corridor-mode-the-default)
  - [2.2 Fundamental (Besselian) plane, frames and time scales: besselian_offsets](#22-fundamental-besselian-plane-frames-and-time-scales-besselian_offsets)
  - [2.3 Star magnitude cap and corridor width: plan_corridor](#23-star-magnitude-cap-and-corridor-width-plan_corridor)
  - [2.4 Star catalog: pysyzygos/starcat.py](#24-star-catalog-pysyzygosstarcatpy)
    - [2.4.1 Proper motions: sources and the choice per star](#241-proper-motions-sources-and-the-choice-per-star)
  - [2.5 Candidate scan: find_candidates](#25-candidate-scan-find_candidates)
  - [2.6 Exact closest approach: star_test](#26-exact-closest-approach-star_test)
  - [2.7 Checks before logging: handle_star](#27-checks-before-logging-handle_star)
  - [2.8 Asteroid size: get_asteroid_size](#28-asteroid-size-get_asteroid_size)
  - [2.9 Event metrics: event_metrics, apparent_mag_HG, moon_info](#29-event-metrics-event_metrics-apparent_mag_hg-moon_info)
  - [2.10 Shadow ground track: pysyzygos/paths.py](#210-shadow-ground-track-pysyzygospathspy)
  - [2.11 Event preview: pysyzygos/preview.py](#211-event-preview-pysyzygospreviewpy)
  - [2.12 Globe plot: pysyzygos/globe.py (0.11.0)](#212-globe-plot-pysyzygosglobepy-0110)
- [Part 3: Choosing targets (pysyzygos/pick.py)](#part-3-choosing-targets-pysyzygospickpy)
  - [3.1 Orbits: pysyzygos/orbits.py](#31-orbits-pysyzygosorbitspy)
  - [3.2 The screen: pysyzygos/screen.py](#32-the-screen-pysyzygosscreenpy)
  - [3.3 Detection rule](#33-detection-rule)
  - [3.4 Stars for the screen](#34-stars-for-the-screen)
  - [3.5 Speed and output](#35-speed-and-output)
  - [3.6 Saved picks: pysyzygos/picks.py](#36-saved-picks-pysyzygospickspy)
  - [3.7 Pre-screens: pysyzygos/prescreen.py, pysyzygos/shadowtrack.py (0.16.0)](#37-pre-screens-pysyzygosprescreenpy-pysyzygosshadowtrackpy-0160)
  - [3.8 Notes: where a prediction's time goes, and a live search engine](#38-notes-where-a-predictions-time-goes-and-a-live-search-engine)
- [Part 4: Data sources](#part-4-data-sources)
  - [4.1 Sizes: what Horizons/SBDB has, and what occultations measured](#41-sizes-what-horizonssbdb-has-and-what-occultations-measured)
  - [4.2 Asteroid satellites](#42-asteroid-satellites)
- [Part 5: Validation](#part-5-validation) (summary; all checks in [VERIFICATION.md](VERIFICATION.md))
- [Part 6: Open items](#part-6-open-items)
  - [Gravitational light deflection and stellar parallax (built in 0.10.0, 2026-10-04)](#gravitational-light-deflection-and-stellar-parallax-built-in-0100-2026-10-04)
- [Part 7: Future plans](#part-7-future-plans)
  - [Major solar-system bodies as targets (planets and moons built in 0.14.0; Earth's Moon open)](#major-solar-system-bodies-as-targets-planets-and-moons-built-in-0140-earths-moon-open)
- [Supplemental: related tools (notes for later)](#supplemental-related-tools-notes-for-later)

---

## Part 1: The tools and how they fit together

| Step | Tool | What it does |
|---|---|---|
| once | `pysyzygos/setup.py` | downloads the SPICE kernels, installs the star catalog (ready-made G <= 16 from Zenodo, or built from ESA's files) |
| choose | `pysyzygos/pick.py` | screens all asteroids for actual events at the site in a window, writes `targets.py` and saves the pick per site and window in `picks/` |
| pre-screen | `pysyzygos/prescreen.py`, `pysyzygos/shadowtrack.py` | once per window: the asteroids with possible events in a region, or the shadow elements of every event on the Earth, so picks there take seconds |
| predict | `pysyzygos/search.py` | computes the events of the target asteroids exactly, appends them to `hits_log.csv`, writes KML maps |
| present | `pysyzygos/report.py` | turns `hits_log.csv` into an HTML or Markdown event list with an embedded map |
| operate | `pysyzygos/gui.py` (+ `gui_<tab>.py`, `gui_common.py`) | local web interface (NiceGUI): sites on a map, runs, live log, results |
| check | `pysyzygos/owc_check.py` | reruns an OWC search result you saved (`owc_reference.txt`, private) and compares event by event |

Supporting modules: `pysyzygos/corridor.py` (per-asteroid star corridor and candidate scan), `pysyzygos/starcat.py`
(the star catalog; `gaia_local.py` reads the earlier format), `pysyzygos/screen.py` (the pick tool's event screen),
`pysyzygos/orbits.py` (fast orbit integration), `pysyzygos/paths.py` (shadow ground track), `pysyzygos/sbdb.py` (shared
asteroid size cache), `pysyzygos/kernels.py` (kernel download, Earth orientation coverage), `pysyzygos/picks.py` (saved
picks: which one a search uses), `pysyzygos/kstars.py` (points KStars at an event over D-Bus, Linux), `pysyzygos/favorites.py` (starred events with their
own copies of map and preview).

---

## Part 2: The prediction (`pysyzygos/search.py`)

### 2.1 Pipeline (corridor mode, the default)

1. Kernels are checked and loaded at start-up (`pysyzygos/kernels.py`). The local Gaia catalog is opened before any
   other work; a missing or incomplete catalog stops the run.
2. Pass 1, per target: size, H and G (`get_asteroid_size`, 2.8), the asteroid's orbit file from JPL Horizons
   (`fetch_target_orbit`), and a corridor plan (`pysyzygos.corridor.plan_corridor`): the astrometric path every
   `corridor_step_s` over the whole run, the strip half-width and the star magnitude cap (2.3).
3. Pass 2, per target: stars in the strip from the local catalog (2.4), all star/time pairs scanned at once for
   closest approaches to the Earth's centre (2.5), then each candidate solved exactly for the site (2.6) and checked
   (2.7). Hits are appended to `hits_log.csv`; a KML ground track is written for hits close enough to matter (2.10).

The old `"windows"` mode (`search_mode = "windows"`) queries the Gaia archive per hourly window instead. It is kept for
comparison; it shares the per-star solve and checks (`handle_star`).

### 2.2 Fundamental (Besselian) plane, frames and time scales: `besselian_offsets`

- **Axes:** in J2000, **z** = unit vector to the star; **x** = (0,0,1) × z, normalised (east); **y** = z × x (north).
- **Reference frame:** ICRS/ICRF throughout. "J2000" is SPICE's name for its inertial frame, which NAIF treats as the
  ICRF (the ~20 mas frame bias of the old FK5 J2000 is not applied anywhere). JPL's ephemerides (DE440, Horizons SPK
  files) are ICRF-aligned, and Gaia DR3 positions are ICRS (Gaia-CRF3) at the reference epoch J2016.0: stars are moved
  by their proper motion from 2016.0 to the event date (plus parallax and light deflection, see "Gravitational light
  deflection and stellar parallax" in Part 6), so star and asteroid
  directions share one frame. "J2000.0" as a time is only the origin of ET (2000-01-01 12:00 TDB). Apparent positions
  (TETE, true equator and equinox of date) appear only in displays (favorites, globe).
- **Time scales:** the computation runs in TDB (SPICE's ET); UTC appears only at input and output, converted with
  NAIF's leap-second kernel `naif0012.tls` (all leap seconds to the last one, end of 2016: TAI - UTC = 37 s). The
  Earth's rotation does not come from UTC: NAIF's Earth orientation file holds IERS's measured UT1 and polar motion
  against atomic time (the same model as Occult: UT1 from IERS EOP data since 1962, polar motion since 1846). So the
  end of leap seconds (CGPM 2026 draft resolution: UTC continuous from 2027-05-20, a leap hour possible in the far
  future) needs no change: without new leap seconds `naif0012.tls` stays valid (UTC = TAI - 37 s), and UT1 - UTC may
  grow beyond 0.9 s (about a minute per century) without affecting the geometry. Should a last leap second come
  before the change, NAIF publishes it as a new file (naif0013.tls, ...): `kernels.refresh_lsk` looks at NAIF's
  leap-second directory with the weekly Earth orientation refresh and fetches a newer file, and the newest local
  naifNNNN.tls is loaded (`kernels.lsk_file`). The star's azimuth (the report's compass direction) is computed by the
  search with SPICE and the measured UT1 (record `star_az`, since 2026-10-16; equal to astropy/IERS to 0.0001 deg);
  the report's own `alt_az`, which takes UT1 as UTC, remains only for older records.
- **Observer:** `georec(lon, lat, alt_km, a, f)` with the WGS84 ellipsoid (`pysyzygos/earth.py`), fixed in ITRF93.
  Longitude east-positive, geodetic, radians. The height is above the ellipsoid: sites.py's `ele` (above mean sea
  level) plus `geoid_m`, the EGM96 geoid's height there (`geoid.py`, a 0.5 deg grid; filled in when a site is saved),
  unless the site's height is above the ellipsoid already (`ele_ref="ellipsoid"`, e.g. MPC codes). Before
  2026-10-16 `ele` was used as an ellipsoid height, off by the geoid (-107 to +85 m; for the test sites -32 to +48 m),
  which moves the path relative to the site by that over tan(star altitude).
- **Asteroid as the observer sees it:** `spkcpo(target, et, 'J2000', 'OBSERVER', 'CN', site_itrf, '399', 'ITRF93')`, the
  asteroid at et minus the light time from the observer (not from the Earth's centre), relative to the observer at et.
  `CN` is converged light time without stellar aberration: astrometric, like Gaia positions. Aberration is left out
  on purpose: it shifts the star and the asteroid by the same amount, so the occultation condition (both in the same
  direction) is the same with or without it. The light time must be the observer's own: an observer closer to the
  asteroid by z = R sin(star altitude) gets its light z/c sooner (up to 21 ms), during which the asteroid moves with
  its barycentric velocity; with the Earth-centre light time for everyone (up to 1.1.0) the shadow was up to
  (v/c) R sin(alt), ~0.4-0.9 km, off at the surface (in the Earth's frame: the shadow runs along the star's aberrated
  direction). The path lines (`paths.shadow_path`) apply the same per ground point. Elsewhere (scans, pick,
  pre-screens) the asteroid is geocentric, `spkpos(target, et, 'J2000', 'CN', '399')` (399 = the Earth's centre;
  3 would be the Earth-Moon barycentre); their margins are many km.
- **Offsets:** `(dx, dy)` = the first two components of `M @ (r_asteroid - r_observer)` (that `spkcpo` vector), km east and
  north. Miss distance = `hypot(dx, dy)`.

### 2.3 Star magnitude cap and corridor width: `plan_corridor`

- A drop of at least `d` needs the star no fainter than `m_ast + 2.5*log10(1/(10^(0.4 d) - 1))`: 2.54 mag for 0.1.
  The cap is `min(MAG_MIN, faintest m_ast in the run + that + 0.5)`. A 15.5 mag asteroid never needs stars past ~18.5.
- Strip half-width per path sample: `margin_km / distance + pad`, with `margin_km = Earth radius + r_max + max_shadow_dist`
  (the observer can be anywhere on the Earth's disc) and a proper-motion pad for stars up to 1500 mas/yr over the time
  since Gaia's epoch 2016.0. Faster stars are added from an all-sky list kept with the catalog.

### 2.4 Star catalog: `pysyzygos/starcat.py`

- Built from ESA's bulk Gaia DR3 `gaia_source` files (3386 gzipped CSV files, 753 GB, streamed and not kept): every
  star with G <= `gaia_local_gmax` and a position. G <= 16: 78.0 M of 1811.7 M stars, 1 h 49 min at ~1.4 Gbit/s with
  6 workers (CPU-bound: 30 columns are parsed); each source file becomes a part file first (written last,
  atomically: the build resumes), then all parts are merged.
- One sort order for every lookup: sky cells of 0.25 x 0.25 deg (plain ra/dec grid, no HEALPix library; whole dec
  bands near a pole) and, within a cell, G. `offsets.npy` gives each cell's rows, so a lookup with a magnitude cap
  reads only the bright end of the cells it touches. Positions are stored as 32-bit offsets inside the cell (steps
  of 0.25 deg / 2^32 = 0.0002 mas), G in millimag; parallax and proper motion as Gaia's 4-byte values.
- Parts, the same rows in separate files: **core** (31 bytes per star, 2.4 GB for G <= 16: `source_id`, position,
  parallax, proper motion, G, flags: astrometry kind, duplicated source, non-single star), **quality** (20 bytes, 1.6
  GB: RUWE, the five errors as 2-byte floats, the six position/motion correlations x127 as bytes, non-single-star code,
  multi-peak fraction) and **extras** (10 bytes, 0.8 GB: BP and RP in millimag, radial velocity and its error, Teff).
  Each optional part carries the build id of its core (`<part>.json`), so a part of another build is never joined.
  Stars faster than 1500 mas/yr (can leave a strip's pad) are listed in `hpm.npy`.
- Lookup for a corridor (`StarCatalog.corridor_stars`): the cells within 1.5 x the strip's half-width of the path,
  sampled every 0.05 deg, then coarse discs along the path (0.05 deg chunks), a superset that the candidate scan
  narrows down; plus the fast movers. Cones (`cone`, for companions, previews and the globe's star field) return the
  quality and extras columns under Gaia's names, so the double-star check reads the star's flags and error ellipse
  locally (`doubles.star_flags`, the same code as the online check).
- Checked against the earlier format (2026-10-16): the same 69,993,732 main and 7,958,666 high-RUWE / 2-parameter
  stars, positions within 0.0001 mas, parallaxes and proper motions bit-identical, 60 random cones with the same
  stars; a 20-day search of 19 asteroids and a 4-day pick of 464,740 asteroids gave the same events (times within
  1 ms); search strips 2-7x faster (one sort order, no per-file reads), the pick as fast without its 1.3-2.8 GB index.
- Why local: the Gaia archive took 12-14 min per strip query (or never answered) in October 2026 and warns it is
  unstable while DR4 is prepared.
- Ready-made for G <= 16 on Zenodo, [doi:10.5281/zenodo.23113337](https://doi.org/10.5281/zenodo.23113337) (CC BY-NC
  4.0, the terms of the Gaia data it contains): `gaia_dr3_g16_v2_core.tar.xz`, `..._quality.tar.xz`,
  `..._extras.tar.xz`, each with a `.sha256` (`fetch`, resumable, unpacks into any folder). Other limits are built
  locally (`pysyzygos catalog build --gmax 18`): deep catalogs serve few amateur set-ups.
- **High-RUWE and 2-parameter stars** are in the catalog, flagged by kind: RUWE >= 1.4 (kind 1; often unresolved
  doubles: 7.38 M to G 16) and 2-parameter sources without parallax or proper motion (kind 2; stored as 0, so their
  position is that of 2016: 0.57 M), about 10 % of the stars (one in five at G < 12). The GUI switch / `use_supplement()`
  (env `PYSYZYGOS_SUPPLEMENT`, else config `gaia_supplement`, default on) keeps or drops them. Events on such stars
  carry `star_kind`, `star_ruwe`, `star_flag` ("RUWE 1.65", "2-param") at the end of the record and the pick's events,
  shown as ⚑ after the star magnitude.
  **2-parameter stars have no proper motion in Gaia DR3**: where theirs comes from, and how the best one is chosen,
  is in [2.4.1](#241-proper-motions-sources-and-the-choice-per-star). Found with (86288) 1999 UC45, 2026-09-30: its G 11.73
  target (RUWE 1.65), observed by three stations, was not in the first local catalog, so the event was not
  predictable.
- **The earlier format** (`pysyzygos/gaia_local.py`, PySyzygos before 1.3.0; still read): one `.npy` per source file
  with 7 columns (40 bytes per star, only RUWE < 1.4 with 5-parameter astrometry), a 1 x 1 deg cell list per file, a
  separate supplement (`<catalog>/supplement/`) and a bright-star index for the pick (3.4). `LocalGaia`, `open_index`
  and `status` hand a format-2 folder over to `starcat.StarCatalog`, so the search, pick, pre-screens and previews do
  not care which format a catalog has. `pysyzygos setup --upgrade-catalog` installs the new one next to an old one and
  swaps it in.

### 2.4.1 Proper motions: sources and the choice per star

A star's position at the event is its Gaia DR3 position (epoch 2016.0) moved by its proper motion over the years
since (~10.8 years for an event in late 2026); parallax and, for fast nearby stars, the radial velocity are applied
too (2.2, `corridor.propagate_exact`). An error of 1 mas/yr in the proper motion moves the star by ~11 mas by 2026,
about 15-20 km on the ground for a main-belt asteroid (1 mas = 0.725 km x its distance in AU). So the proper motion is as
important as the position itself, and for the stars without a Gaia proper motion it is the largest error of the
whole prediction.

**Which stars get which proper motion** (kind = bits 0-2 of the core's `flags`, shown as ⚑ after the magnitude):

| Kind | Stars (G <= 16) | Proper motion | Its error (1 sigma) |
|---|---|---|---|
| 0 | 5/6-parameter, RUWE < 1.4 (~70 M) | Gaia DR3; for G < 13 corrected for the bright stars' frame spin (Cantat-Gaudin & Brandt 2021, `astrometry.gaia_pm_bias`) | Gaia's (quality part / online check), typically 0.02-0.1 mas/yr |
| 1 | 5/6-parameter, RUWE >= 1.4 (7.38 M; often unresolved doubles) | Gaia DR3 (as kind 0) | Gaia's x RUWE (Gaia underestimates them for such stars) |
| 3 | 2-parameter, matched in UCAC5 | UCAC5 | UCAC5's e_pmRA / e_pmDE (the larger one) |
| 4 | 2-parameter, not in UCAC5, matched in UCAC4 | UCAC4's own | UCAC4's e_pmRA / e_pmDE (the larger one) |
| 5 | 2-parameter, with a UCAC4 measurement (1.3.2) | from UCAC4's measured position to Gaia's (below) | position errors / interval |
| 2 | 2-parameter, none of the above | none: the 2016.0 position is used | 10 mas/yr per axis assumed (`PM_UNKNOWN_MAS_YR`) |

**The three sources for 2-parameter stars** (573,735 stars to G 16; Gaia DR3 solved only their position, mostly
because the source is a close double, very bright or has too few observations):

1. **UCAC5** (Zacharias, Finch & Frouard 2017, AJ 153, 166; VizieR I/340): UCAC's CCD positions (epochs ~1998-2004)
   re-reduced against Gaia DR1, combined with Gaia DR1's 2015.0 positions: a ~15-year baseline. Matched through
   CDS XMatch by the Gaia DR1 position UCAC5 lists: within 0.2" of the DR3 one and G within 0.5 mag, so a close
   neighbour cannot be taken by mistake (`gaia_local.pick_ucac5`). 294,496 stars.
2. **UCAC4** (Zacharias et al. 2013, AJ 145, 44; VizieR I/322A): its own proper motions, from its CCD positions
   combined with earlier catalogues of older epochs. Matched
   by its J2000 position moved with its motion to 2016: within 0.5" and 1 mag (`gaia_local.pick_ucac4`). Used for
   the stars UCAC5 does not have: 171,094.
3. **Epoch proper motion** (1.3.2, `starcat.epoch_pm`): the motion between UCAC4's MEASURED position and Gaia DR3's,
   typically over 15-20 years. UCAC4's catalogue position is given for J2000, but it is not a measurement: it is the
   position at the star's central epochs (`cepra`/`cepdc` in the zone files, typically 1997-2001) carried to J2000
   with UCAC4's own proper motion. So it is first taken back to those epochs, then

       pm = (Gaia 2016.0 position - UCAC4 central-epoch position) / (2016.0 - central epoch)    (per axis)
       error = sqrt(sigma_UCAC4(central epoch)^2 + sigma_Gaia(2016)^2) / (2016.0 - central epoch)

   with UCAC4's position errors at the central epochs (`sigra`/`sigdc`, typically 15-60 mas) and Gaia's
   (`ra_error`/`dec_error`). Used only over at least 8 years (`EPOCH_MIN_YEARS`). The UCAC4 star is the one the
   `xref` part names for the Gaia star (2.4: within 1" and 1.5 mag at J2000, one Gaia star per UCAC4 star).
   428,251 2-parameter stars have such a UCAC4 measurement.

**The choice** (`starcat.choose_pm`, run with the `xref` part or by `pysyzygos catalog pm-epoch`): each star keeps the
estimate with the smallest error, compared as the larger of the two axis errors (UCAC5's and UCAC4's are stored
that way). A star with none so far takes the epoch motion whenever it exists. The estimates are not averaged: UCAC5
and the epoch motion both rest on UCAC's CCD positions, so they are not independent. The chosen motion and its
errors go into the core (`pmra`, `pmdec`, kind) and the quality part (`pmra_error`, `pmdec_error`); Gaia's 2016.0
position is always kept. Checked on one UCAC4 zone (573, 492 stars): UCAC5 and epoch motions agree within their
quoted errors (median difference 0.8 sigma), so both error estimates are realistic; UCAC4's own motions do not
(median 2 sigma, 23 % beyond 3 sigma: their errors are too small). Over the whole catalog (2026-10-17, G <= 16) the
epoch motion replaced 354,695 of the 428,251 it was computed for: 220,082 UCAC5, 122,440 UCAC4 and 12,173 stars
without any; 73,556 kept their UCAC5/UCAC4 motion. The 573,735 2-parameter stars now have: epoch motion 354,695
(kind 5), UCAC5 74,414 (kind 3), UCAC4 48,654 (kind 4), none 95,972 (kind 2). The counts are in the catalog's
`catalog.json` (`pm_xmatch`: before; `pm_epoch`: the replacements).

**The other estimates, per event** (1.3.2, `pmcheck.py`, config `pm_alternatives`, default on): for an event on a
2-parameter star the search asks VizieR for its UCAC5 and UCAC4 rows (two queries, ~1 s) and computes all four
estimates: UCAC5, UCAC4's own, the epoch motion, and UCAC4 J2000 -> Gaia (the motion Occult uses). Each puts the
star somewhere else at the event; their RMS distance from the position used is the star's realistic 1-sigma
whenever it is larger than the quoted error (for close doubles the quoted errors are too small: the estimates
disagree by more). The map shows the centre line for each other estimate (thin, pink, dashed, "Proper motion ...";
`pmcheck.shifted_dir` moves the star direction, then the normal `shadow_path`); the record keeps `star_pm_alts`,
`star_pm_spread_mas`, `star_pm_spread_km`. (4089) Galbraith, 2026-10-13: spread 31.4 mas = ±46 km (quoted error:
±27 km); the line "as Occult" lies on Occult's published centre line to 0.19 km (0.10 km scatter, 56 points), ours
72.6 km from it: the whole difference between the two predictions is this choice of proper motion.

**What the prediction does with the error**: `gaia_local.star_sigma_mas` gives the star's 1-sigma position at the
event, sqrt(position error^2 + (pm error x years since 2016)^2), or the estimates' spread when larger; in km at the asteroid it is combined with the
orbit's sigma into the path's sigma lines and the chance at the site, and the report shows a red **⚠ star ±… km**
where it is larger than the asteroid's radius, an amber **star ±… km** where it is more than half the radius.

**Compared with other programs**: Occult takes, for a star without a Gaia proper motion, the motion from UCAC4's
J2000 position to Gaia's (UCAC4 as the reference epoch, as D. Herald described it); with (4089) Galbraith's star (UCAC4 573-029535) that reproduces
Occult's star position to 0.4 mas (VERIFICATION.md). That motion carries UCAC4's own proper motion's error over the
years between the central epoch and 2000; the epoch motion above avoids it.

**Limits**: most 2-parameter stars are close doubles. For them every estimate describes a photocentre that moves
with the pair's orbit, and UCAC (seeing-limited, ~1-2") may have measured the blend while Gaia measured one
component. (4089) Galbraith's star (WDS AG 112 AB, 2.8", nearly equal): its two best estimates, UCAC5 (-4.0, -13.0
+- 1.7) and the epoch motion (-3.3, -10.5 +- 1.0/2.3), differ by 2.6 mas/yr, ~43 km on the ground by 2026, more
than either's quoted error; UCAC4's own (-5.6, -15.8) is 5.4 mas/yr from the epoch motion. Such events should be compared with other
predictions; the double-star check in the favorites panel (VizieR: WDS and Gaia's binarity indicators) shows what is
known about the pair. Gaia DR4 (expected December 2026) will give proper motions for most of these stars.

### 2.5 Candidate scan: `find_candidates`

- Stars are moved linearly by proper motion to the middle of the run. The plane distance of every star to every path
  sample is `chord x distance`; local minima below the margin (widened by half a step of motion) are kept.
- Each minimum is refined by quadratic interpolation of the path, giving an estimated time and Earth-centre miss.

### 2.6 Exact closest approach: `star_test`

- `minimize_scalar(method='bounded')` over a time interval around the estimate, solving for the **offset from the
  interval centre**, not the absolute time. The bounded solver's tolerance is `sqrt(eps)*|x| + xatol/3`; with the raw
  ephemeris time (~8.4e8 s) that was ~12 s, i.e. tens of km of miss distance (fixed 2026-10-01; earlier results were
  off by up to ~9 s and ~90 km, median 6 km).
- Interval width (`corridor.solver_bracket_s`): the scan estimates the Earth-centre closest approach, but the observer
  is up to `margin_km` from the centre in the plane, so the local closest approach can be `margin / speed` away
  (10-20 min). Width = 2 x clip(1.3 margin / speed, one path step, 2 h).
- The star is propagated to the event with astropy `apply_space_motion` (distance = 1000/parallax pc, parallax floored
  at 0.01 mas).

### 2.7 Checks before logging: `handle_star`

- Rejected if the minimum lies within 1 s of the interval edge (not a real minimum), outside the run, already logged
  (same asteroid and star within 300 s), not observable (star altitude < `MIN_STAR_ALT` or Sun above `MAX_SUN_ALT`), or
  the drop is below `min_mag_drop`.
- Logged if `min_distance < r_max + max_shadow_dist`; `observable` says "yes" inside `r_max`, "yes, in search range"
  outside it.

### 2.8 Asteroid size: `get_asteroid_size`

Order of precedence:
1. `SIZE_OVERRIDES` (curated values, e.g. from occultation chords or shape models).
2. SBDB `diameter` with its sigma (15 % if missing); bounds +/-3 sigma, widened by the tri-axial `extent`.
3. H plus SBDB albedo `p`.
4. H only, albedo 0.14 (bounds from albedo 0.30 and 0.05). The tables mark these asteroids with "*": the diameter
   is uncertain by a factor of about 1.7 (sqrt(0.30/0.14), sqrt(0.14/0.05)).

`D = 1329 / sqrt(p) * 10^(-H/5)` km. `r_min_km` is clamped at 0. The bounds describe size uncertainty only, not orbit
uncertainty. No diameter and no H gives no size (the target is skipped).

The raw SBDB data is cached per asteroid in `<cache_path>/PySyzygos_sbdb_phys.json` (`pysyzygos/sbdb.py`), refreshed
after `sbdb_max_age_days`; the pick tool fills it for its targets from its bulk download.

### 2.9 Event metrics: `event_metrics`, `apparent_mag_HG`, `moon_info`

- Shadow speed relative to the observer: finite difference of `(dx, dy)` over +/-1 s.
- Chord `2*sqrt(max(r^2 - b^2, 0))` for impact parameter `b`; duration = chord / speed (0 outside the shadow).
  `max_duration_s = 2r / speed` (centre line).
- Asteroid magnitude (H, G system): `V = H + 5 log10(r Delta) - 2.5 log10((1-G) Phi1 + G Phi2)`,
  `Phi1 = exp(-3.33 tan(a/2)^0.63)`, `Phi2 = exp(-1.87 tan(a/2)^1.22)`, `a` = phase angle at the asteroid; G = 0.15
  if unknown. Good to about +/-0.3 mag plus the lightcurve amplitude.
- Drop (star fully covered): `mag_drop = 2.5 log10(1 + 10^(0.4 (m_ast - m_star)))` = `m_ast - m_before`, the change in
  combined brightness (as OWC lists it); never smaller than `m_ast - m_star`. Star magnitude is Gaia G; OWC's star
  column shows the same G values.
- Moon: topocentric separation from the star, altitude, illumination `(1 + cos a)/2`, phase age (ecliptic longitude
  Moon minus Sun).
- `offset_east_km`, `offset_north_km`: shadow axis minus observer on the plane, i.e. how to move to the centre line.
- Observability (logged, not filtered): `airmass` (Kasten & Young), `extinction_mag` = extinction x (airmass - 1), and
  `mag_margin` = OWC limit (3.3, upper size bound) - star magnitude - extinction.
- Run statistics: `calc_s` per hit (from the candidate's start to the logged record, without the map); per run a
  summary (start-up, asteroid data loading = pass 1, search = pass 2, maps, per asteroid, per exact solve, counts,
  site, equipment, limits) printed and appended to `<hits log>.runs.jsonl` for the report header.

### 2.10 Shadow ground track: `pysyzygos/paths.py`

- About 1.3 Earth radii of track on each side of the event, ~100 km per step. Seven lines: centre, the shadow limits
  (+/-r), the 1-sigma limits (+/-(r + sigma)) and the 3-sigma limits (+/-(r + 3 sigma)); each plane point is projected onto the Earth ellipsoid
  (`surfpt`; a miss raises `NotFoundError` and the point is skipped), with the centre-line duration at each point.
- **The path is geodetic at height 0 m on the WGS84 ellipsoid** (a = 6378.137 km, f = 1/298.257223563;
  `pysyzygos/earth.py`), as Occult's default output and GPS positions, so it can be compared exactly. All geodetic
  conversions (sites, observer, globe plot) use WGS84 too; until 2026-10-11 they used the SPICE kernel's Earth radii
  (pck00010: 6378.1366 / 6356.7519 km, ~0.4 m off), which moved the path by 0.3 m (median), 1.2 m (95 %), up to
  3.6 m near the limb (checked on the 1999 UC45 event), the event time by 0.01 ms. Earth orientation: ITRF93
  (`earth_latest_high_prec.bpc`). `debug_save_paths` keeps every event's path as `<map_dir>/<event>_path.npz`.
- The 1- and 3-sigma lines describe the uncertainty of the asteroid's **position** (orbit), not of its size: the
  size enters only through r (the red shadow limits use the best radius); its uncertainty (r_min .. r_max) sets the
  search range and is not drawn.
- Sigma: `path_sigma3_km` asks JPL Horizons for the plane-of-sky 3-sigma position uncertainty at the event
  (`RSS_3sigma`, arcsec) and converts it to km at the asteroid's distance; sigma = that / 3. Without a Horizons
  covariance it uses `default_sigma3_km` (10 km, so sigma 3.3 km). Only the orbit counts: the star's position error is
  not added. Gaia DR3 positions carried from 2016 to 2026 with their proper-motion errors are good to about 1 mas
  for bright stars (~1 km at 1.2 AU) and several mas for faint ones (G 17-18: several km), so for faint stars the
  real band is wider than drawn.
- RSS is the size of the whole error ellipse, dominated by its long axis. What moves the path on the ground is the
  part across the track; the part along the track only shifts the time. So the 1- and 3-sigma lines are as wide as
  the long axis whichever way it points: right when the long axis lies across the track, too wide when it lies along
  it. Example, 172559 on 2026-10-19 (1.21 AU): long axis 0.03" (3 sigma) at position angle -4 deg, short axis 0.004",
  track to the east-north-east, so the long axis lies nearly across the track and sigma ~9 km is the real cross-track
  value there (3 sigma 26 km).
- Occult/OWC draw the same kind of diagram (shadow, then the 1-sigma band, then 2- and 3-sigma lines), but take the
  uncertainty from their own orbit data, not from Horizons, so their band can be narrower or wider than ours for the
  same event (e.g. an OWC event with a 9 km shadow and a 1-sigma band of ~2 km on each side).
- KML for Google Earth or Google My Maps; written for every logged event, i.e. when the miss distance is below
  `r_max + max_shadow_dist` (the shadow plus the distance you can travel), also when the site lies outside the
  3-sigma band: then the map shows where to go.

### 2.11 Event preview: `pysyzygos/preview.py`

- For every hit, an SVG next to its KML: the local-catalog stars (to `preview_mag_limit`) in a field
  `preview_field_factor` times the camera field (at least 10′), moved linearly by proper motion to the event date;
  gnomonic projection around the target star, north up and east left (as on the sky; a telescope may flip it).
- Camera field `2 atan(sensor / 2 focal)` from the site's `focal_mm` and `sensor_mm`; asteroid track from the SPK
  (`CN`, geocentric) over a span chosen so it covers about a quarter of the field (30 min to 12 h each side).

### 2.12 Globe plot: `pysyzygos/globe.py` (0.11.0)

- The whole Earth as seen from the star at the event time (orthographic, east right, north up): the
  shadow path from `shadow_path` (centre line, shadow limits, 1- and 3-sigma limits) with dots and labels
  at whole minutes, the shadow axis beyond the Earth (fundamental plane, dashed, minute ticks), the site, and either
  sea, land and the night side (`globe_style = "color"`, like OWC's globe) or a line drawing with the day side
  (`"lines"`). Land is drawn with an extended orthographic projection (r = sin c on the visible side, 2 - sin c
  beyond the limb) clipped to the disk; a land mass containing the far-side point is filled as the outside of its
  outline (detected by its orientation).
- Header with Occult's parameter set: star (Gaia id, G, RA/Dec as used and of date via astropy TETE, the applied
  parallax and deflection), maximum duration, time per km and per mas, drop, Sun and Moon distance and Moon
  illumination, 1-sigma error (Horizons RSS, in km and mas), asteroid magnitude, diameter (range, mas), horizontal
  parallax, hourly motion in RA (s) and Dec ("), distance. Inset: 2 deg chart to star G + 1.5 with the asteroid's
  motion in 24 h steps.
- Checked on 30819 (Oct 11 2026) against Occult's plot: star position, asteroid parallax 8.227" (equal), hourly
  motion -2.083 s / -28.67" (Occult -2.087 s / -28.62"), 1 km and 1 mas times, diameter, Sun and Moon all agree;
  the path crosses the same countries at the same minutes.
- Coastlines, borders and land: `data/ne_110m_earth.json` (Natural Earth 1:110m, public domain, 166 KB).
- **A4 page with the geometry** (1.3.2, `globe_page = "A4"`, the default; `"square"`: the view alone): below the
  view two panels, drawn from the event's own values (`system_data`). *True scale* (AU): the Earth, the target on
  the star's line, the Sun, Jupiter and Saturn in the plane of the star's direction and the Sun (the planets
  projected, their distance from the plane noted); the deflection is invisible at this scale. *Light paths*: the
  star's ray that reaches the Earth, computed with `astrometry.deflect` (Sun, Jupiter, Saturn, as the search applies
  it): a point at distance x on the ray is seen where the star is seen, so its true direction is the star's apparent
  one minus its own deflection, y(x) = x (d_star - d(x)). The target stands on that ray (the star is hidden); the
  same target without deflection stands on the straight line; the difference is the shift that moves the shadow
  (Phaethon 2019-07-29: 9.37 mas in all, 2.43 mas of it on the target's own light, shift 6.94 mas = 4.8 km; (4209)
  Briggs 2026-10-20: 0.56 mas = 0.9 km, equal to the header's "deflection applied"). Distances along the star's
  direction are true (AU, at least 2.6 AU or 1.5 x the target's distance); the y axis gives the rays' sideways
  offsets in mas as seen from the Earth at the target's distance, so the target stands at the shift itself; ticks
  at 1, 2, 2.5 or 5 x 10^n. The Sun is off scale there: a marker on the panel's edge at its distance along the
  star's line, with a broken line and its true distance from the line (AU); Jupiter and Saturn likewise when they
  deflect the star's light by at least 0.001 mas (e.g. (147223) 2002 XB29 on 2026-10-24, Saturn 1 deg from the
  star: 0.01 mas; (10514) Harlow on 2026-11-01, Jupiter 3 deg away: 0.03 mas). Lines at least 2 px (0.4 mm), labels
  placed around their points (farther out with a leader line). Plain SVG, sized 210 x 297 mm for printing.

---

## Part 3: Choosing targets (`pysyzygos/pick.py`)

An OWC-style event search over all asteroids (numbered, H < `pick_hmax`, or all with `--all`) for a window, at the site.

### 3.1 Orbits: `pysyzygos/orbits.py`

- SBDB bulk query with **full-precision** elements (`full-prec=true`). The default output is rounded (e.g. `a = 2.766`),
  which alone gave ~40" errors.
- Heliocentric ecliptic J2000 elements to an equatorial state, then integrated barycentrically with the Sun and the
  planet-system barycentres from DE440 (Earth-Moon as one body), RK4 with half-day steps, quintic Hermite interpolation
  between steps, one-step light-time correction (astrometric, as `CN`).
- Against the JPL Horizons orbit files of 102 asteroids over 21 days: worst 0.01", median 2 km. 102 asteroids in 0.2 s.
  Not for close Earth approaches (no Moon separately, fixed step).

### 3.2 The screen: `pysyzygos/screen.py`

Per chunk of asteroids, positions every 600 s over the window, then per asteroid:
1. Only samples when the asteroid is above `MIN_STAR_ALT - 3` at the site and the Sun below `MAX_SUN_ALT` (both from the
   site) are searched.
2. The faintest useful star follows from the drop rule (2.3) and the observability rule (3.3), so small or fast asteroids
   search only bright stars.
3. Stars along the visible path from the catalog (3.4), then the candidate scan (2.5).
4. Each candidate is solved for the site: Newton iteration on the plane offset of the shadow axis from the observer on
   the rotating Earth (asteroid positions by cubic interpolation, observer from `pxform`), within the bracket of 2.6.
5. Kept if the miss is below `r_max + reach`, the star is high enough and the Sun low enough at that time, and the
   detection rules pass.

Against `pysyzygos/search.py` on the same events: same stars, times within 5 s, the same drops and durations.
Stars are moved linearly by proper motion (no parallax), and stars faster than 1500 mas/yr are not searched.

### 3.3 Detection rule

OWC's General Observability Criterion (video recording, aperture and detection frames): an event is observable if
`StarMag < 5 log10(aperture_cm) + 2.5 log10(MaxDuration / frames) + 8.5 + MagAdjust`. With extinction enabled (site
key `extinction`, mag per airmass), the star counts as fainter by `extinction x (airmass - 1)` at its altitude (Kasten &
Young airmass). Hard limits: `min_dur_s` and `min_mag_drop`; OWC also found the drop itself has no significant effect.
All OWC reference events pass at 25 cm, 4 frames, MagAdjust 0 (and some would not if the aperture were in inches).
The site's star limit `MAG_MIN` is the magnitude that passes at the longest usable exposure `max_exp_s` (0.64 s gives
G 15.0 at 25 cm, as in the OWC search). For sizes estimated from H (uncertain by ~1.7x) the duration test uses the
upper size bound, so an event is kept if it *can* be observable; the reported duration is nominal. `mag_margin`
reports how far below the limit the star is.

### 3.4 Stars for the screen

The catalog itself (2.4): sorted by 0.25 deg sky cell and, within a cell, by magnitude, so a lookup with a bright
cap (the camera's limit) reads only the bright end of each cell; memory-mapped and shared by the worker processes. A
lookup takes 5-50 ms. Catalogs of the earlier format need a separate bright-star index (`BrightIndex`: the stars to
G 15, 32.4 M, 1.3 GB, or deeper in whole magnitudes: `bright_G16.0.v2.npy`, 2.8 GB, a copy of the whole G 16
catalog), built once by the first pick that needs it, with little memory (count per cell, write each file's stars
into their cell's slots of a memory-mapped file, sort each cell by G a block at a time).

### 3.5 Speed and output

465k asteroids (H < 17) over 8 days: 875 s in one process, 318 s with 4 worker processes (each loads its own SPICE
kernels).

**Memory.** Each worker screens the asteroids in chunks of 2000. For a chunk it holds, for every asteroid and every
10-minute step of the window (144 per day), its barycentric position and velocity, its direction and distance from
the Earth, its heliocentric vector, phase angle, shadow speed and visibility: about 200 bytes per asteroid and step.
So, per worker:

| part | size | grows with |
|---|---|---|
| Python, SPICE kernels, pandas | ~0.5 GB | fixed |
| chunk arrays | ~55-60 MB per day of window | days (linear) |
| stars near one asteroid's path | small, temporary | path length (days) and star limit (~2.5-3x per magnitude) |

That is about 0.7 GB per worker for 3 days, 1.6-2 GB for 20 days, ~4 GB for 60 days; the total is that times the
number of workers (seen: 4 workers at ~1.9 GB each). Rule of thumb, to stay out of swap:
workers x (0.5 GB + 55 MB x days) well below the free memory.

* **H limit**: almost no effect on memory, only on time. More asteroids are more chunks, and a worker handles one
  chunk at a time. Only the main process grows a little with the asteroid list (well under 1 GB, even for all
  numbered asteroids).
* **Star limit (G)**: mostly shared memory. The star catalog is memory-mapped, so the workers share it in the
  file cache (it shows as SHR in `top`, and the system can free it): 1.3 GB for G <= 15, ~3.7 GB for G <= 16. Per
  asteroid, the list of stars near its path grows ~2.5-3x per magnitude, but it is temporary and small next to the
  chunk arrays.
* **Days**: the per-worker chunk arrays (above) and longer star lists. For long windows use fewer workers, or split
  the window into several picks (each is saved and reused by searches).

**CPU.** NumPy's linear algebra (OpenBLAS) starts one thread per CPU in every process. With several workers that
oversubscribed the CPU (seen: 4 workers on 8 cores, load 24, each worker's own thread at ~40 % of a CPU), which cost
time rather than gaining it. Since 0.16.0 the pick and pre-screen workers start with one math thread each
(`OPENBLAS_NUM_THREADS`/`OMP_NUM_THREADS`/`MKL_NUM_THREADS` = 1 unless set): a pre-screen build ran 2.4x faster.
Workers up to the number of physical cores; the GUI default is half the logical CPUs.

Output: `pick_events.csv`, a ranked table (brightest star first by default) and `targets.py` with the
asteroids of the best events; their size data goes to the shared size cache.

### 3.6 Saved picks: `pysyzygos/picks.py`

The pick is the slow step, so each run for a named site is also saved as `picks/<site>__<start>_<days>d.py` (targets,
names and `pick_meta`: site, position, window, settings, time of the pick) plus the `.csv` of its events. With
`targets_source = "auto"` (default) `pysyzygos/search.py` takes the newest saved pick of its site whose window covers the
search window and that was made at the site's current position (within 0.01 deg); otherwise `targets.py` or the
config list. An explicit target list (GUI text field, a run override, the OWC check) always wins. The run summary
records which list was used, and the report header shows it.

### 3.7 Pre-screens: `pysyzygos/prescreen.py`, `pysyzygos/shadowtrack.py` (0.16.0)

A pick spends most of its time on a site-independent question: which asteroids pass close enough to a star that its
shadow touches the Earth at all. A pre-screen answers it once for a window and stores the answer; a pick then screens
only the asteroids that can matter at its site (`pick --prescreen FILE|auto`). Same parts as the pick (3.1-3.4), for
the whole Earth:

1. Per asteroid, the stars (G <= the build's limit and bright enough for a drop >= `min_drop`) within Earth radius +
   r_max + reach of its geocentric path, then the candidate scan (2.5): every star whose shadow can touch the Earth.
   The orbit grid reaches 12 h beyond the window, so an event whose ground track touches the window is found even when
   its Earth-centre time lies outside it (an event can take up to 6 h to cross the Earth).
2. Per candidate, the ground track of the shadow axis: the axis's plane position projected onto the Earth along the
   star direction (off the limb: the nearest limb point), the Earth's rotation from `pxform` every 10 min plus the
   spin in between, sampled at 161 points over +-half (half = 1.3 x (Earth radius + r_max + reach) / speed, at most 6 h).
3. Region build: kept if a sample is in the region box with the star up and the Sun down there; whole-Earth build:
   kept if a sample has the star up and the Sun down anywhere, and the event's shadow elements are stored (below).

**Strict superset.** Every test is widened so that nothing the pick would find can be dropped:
- *Between samples*: by half the distance to the neighbouring samples (on the ground for the box, in the plane for
  "on the Earth", and as an angle for the altitudes). Checked against 1281 samples: none missed, 13 % extra asteroids.
  The first version (41 samples, no widening) missed 21 % of the asteroids of a 500 km region.
- *The reach is a plane distance* (the pick's miss distance is measured across the shadow, in the fundamental plane).
  On the ground it is stretched: the plane is the orthographic projection of the Earth along the star, so a point at
  star altitude h lies at R cos h from the axis of the projection. An observer P within rho (plane) of the axis's
  ground point A therefore has cos h_P within cos h_A -+ rho/R, which bounds sin h_P, and the chord satisfies
  |PA|^2 = rho^2 + R^2 (sin h_P - sin h_A)^2 (`ground_reach`). For rho = 210 km: 210 km on the ground with the star
  overhead, ~280 km at 50 deg, ~730 km at 20 deg, ~1640 km at the horizon. This ground distance widens the region box
  and, divided by R, the star and Sun altitude tests (the observer's sky differs from the axis point's by that angle).

**Shadow elements** (whole Earth, `shadowtrack.DTYPE`, 80 bytes per event): number, star, Earth-centre time tc, G,
asteroid magnitude, geocentric miss, star direction (3 x float32), and the axis's plane position as a quadratic in
dt = t - tc over +-half, fitted to the integrated orbit at -half, 0, +half, with the largest misfit at 9 points (`err`;
measured at most 0.3 km, median 0.000 km), plus half and the radius. Sorted by tc in `<name>.global.npy`, so a window
is a binary search. The site test (`site_mask`) puts the site (`Site.at` on a 1-min grid, cubic interpolation) into
each event's plane at 81 times over +-half and computes the closest distance on each segment between them (the
relative motion is linear there); kept if it is below r_max + err + reach + 10 km with the star above the pick's
minimum altitude and the Sun below its limit (both widened by 1 deg) at either end of the segment.

**Index** (`<name>.global.idx.npy`, 24 bytes per event): the latitude range and the longitude arc of the track's
usable samples (widened by the half step + radius; a track near a pole, or with ambiguous longitudes, gets all
longitudes) and the star's altitude range along it. A site or region query widens each box by the largest
`ground_reach` over that altitude range for its own reach and minimum altitude (not monotonic in h: 33 points + 3 %)
and tests only the events whose box can reach it: 14-26 % of the events at the sites tried.

**Validation** (details in VERIFICATION.md): region pre-screen pick 38 of 39 events of the full pick at the observer's
site over 20 days (the 39th, 19 min after the window, is why the grid now reaches beyond it); whole Earth, 4 days,
all asteroids with H < 17: the pick with it gave the same 12 events as the full pick (14 s against 210 s); the site
test kept 40 of 2039 asteroids including all 39 with events; the index and the region test never dropped an event the
exact site test keeps (Test site 2 at three settings, 20 random sites in a 500 km box, sites in Iceland,
Sydney, Svalbard and Tierra del Fuego).

**Storage.** Region pre-screens: one SQLite file (`events`: number, star, Earth-centre time, G, asteroid magnitude,
geocentric miss, a ground point with its Sun and star altitude; `meta`: the settings as JSON; indexes on number and
time); a pick runs one `SELECT DISTINCT number ... WHERE et BETWEEN ... AND g <= ...`. Whole Earth: `<name>.global.npy`
(NumPy structured array of `shadowtrack.DTYPE`, 80 bytes per event, sorted by time), `<name>.global.json` (the
settings, `kind: global`, counts; required: a file is listed only with it) and `<name>.global.idx.npy` (IDX_DTYPE, 24
bytes per event, same order; optional). NumPy rather than SQLite because a query reads all events of a window and
computes on whole columns: memory-mapped, a window is `searchsorted` + a slice with no parsing or row conversion, and
it is about half the size (SQLite stores every number as an 8-byte REAL plus row overhead: ~150-200 bytes per event).
Both kinds are found by `list_files` in `prescreen/` of the data folder; copying them (all three files of a global
one, names unchanged) to another installation is all it takes to use them there.

**Build memory and progress.** Chunk size and workers follow the free memory: a chunk's arrays take ~12 x 3 x 8
bytes per asteroid and 10-min step (measured ~10), plus a fixed part; the candidate scan runs in blocks of 4 M
stars x steps (the corridor's default 25 M made a ~730 MB transient for 30-day paths) and the ground tracks in blocks
of 1024 candidates. After every chunk the results are committed to `<out>.partial` (SQLite: region events, or the
elements as blobs, plus the done asteroid numbers and the settings); a rerun with the same settings resumes, a
different format version is refused. A global build's chunks become one time-sorted file through memory maps, then
the index is computed in worker processes.

### 3.8 Notes: where a prediction's time goes, and a live search engine

Measured 2026-10-10 on the author's desktop (8 cores, 4 workers; a solid but not new machine), one site, H < 17:

| Step | Time | Depends on |
|---|---|---|
| Full pick, all 465k asteroids | ~5 min for 8 days (318 s), 210 s for 4 days | window length, H limit |
| Whole-Earth pre-screen build (once per window) | ~14 min for 4 days, ~1-2 h for a month; ~1 GB per month at G 16 | window length, star limit |
| Pick with a whole-Earth pre-screen, 7 days | ~12 s (less on a second run) | mostly fixed costs, see below |
| Search of the picked targets (7 asteroids, 7 events) | 19.2 s = start-up 5.4 + asteroid data 4.7 + search 3.2 (of it maps 1.9) | targets, network |

On an Apple M4 (32 GB, macOS, 8 workers), 2026-10-11: the full pick for 20 days (all asteroids, G <= 16, with the
supplement) took at most ~5 min; a 30-day whole-Earth pre-screen with the supplement 77 min (14.9 M events, 1.1 GB +
0.34 GB index); picks for 20 days with it (2,400-3,000 asteroids screened) under ~2 min each, same events; the search
of 40 targets for 20 days 94.5 s (start-up 13.5 + asteroid data 38.5 + search 24.7 s).

Split into phases (the pick prints `timing: total … = start-up + asteroid list + kernels + pre-screen + screen +
output`), on the author's desktop, Test site 2, 6 days, G <= 13, 4 workers, warm caches (cold in brackets):

| Phase | Full pick | Pick with a whole-Earth pre-screen |
|---|---|---|
| start-up (Python, imports) | 0.3 s | 0.5 s |
| asteroid list (465k rows from the SBDB cache) | 6.1 s (10.0) | 6.3 s (6.7) |
| kernels | 0.1 s | 0.1 s |
| choosing the asteroids | - | 2.4 s (4.6): site test of 29,180 of 200,240 events -> 203 asteroids |
| screen (worker processes included) | 247.8 s (256.5): 464,740 asteroids | 0.8 s: 203 asteroids |
| output | 1.1 s | 0.9 s |
| total | 255.4 s (268.1) | 11.1 s (13.4) |

Same 6 events. Overall ~23x faster; without the fixed loading (~7.5-8 s in both) the work itself goes from 247.8 s to
3.2 s, ~77x (cold ~47x). With a pre-screen the full asteroid list is now the largest part (~60 %): reading only the
pre-screen's asteroids from it would bring a pick to ~4-5 s.

So a complete 7-day prediction for a site takes about 30 s once a pre-screen exists, of which the actual
calculation (site test on the stored paths, exact screen of a few hundred asteroids, exact solves of the few
candidates) is only a few seconds. The rest is preparation that a permanently running service would have done
already:

1. **Process start-up, twice** (pick and search are separate runs): imports, SPICE kernels, config, opening the local
   Gaia catalog and the results database, ~5 s each. *Live:* one resident process with the kernels loaded and the
   catalog, the pre-screen and its index memory-mapped: 0 s. (Even locally, a combined pick + search run would save
   one start-up.)
2. **The SBDB list of all asteroids** (465k rows from the JSON cache) read in every pick, although a pre-screen
   already names the few hundred that matter. *Live:* kept in memory (or as a NumPy table), refreshed daily.
3. **The site-independent screen**: done by the pre-screen. *Live:* rolling builds (e.g. nightly for the coming
   weeks, ~1 GB per month), shared by all users; with new orbits the affected asteroids could be rebuilt alone.
4. **Site test** on the stored shadow paths: seconds with the index (14-26 % of the events tested). *Live:* the same,
   in memory; a finer index (a box per track segment instead of per track) would cut it further.
5. **Asteroid data for the search**: per target the JPL Horizons orbit file (network, the first time) and the size
   from SBDB. *Live:* a shared, prefetched orbit cache for the asteroids with events in the pre-screen's bright part,
   or the integrated SBDB orbits (good to ~0.01", 3.1) for the list and Horizons only for the final prediction of an
   event someone opens.
6. **Maps, previews and globes**: ~0.3 s per event, made for every event up front. *Live:* made on demand, when an
   event is opened.
7. **Online Gaia double-star check**: already asynchronous, after the search (not in the times above).

A live engine would thus answer "events at this site in the next weeks" in about a second or two: a resident process
holding the global shadow elements and index, the asteroid list and the orbits, testing the site against the stored
paths, solving the surviving candidates exactly, and drawing maps only for the events looked at. That is about the
setup of OccultWatcher Cloud, whose server keeps its predictions ready; locally, the pre-screen gives the same split of
"once per window" and "per site" work.

---

## Part 4: Data sources

| Item | Source | Used for |
|---|---|---|
| `naif0012.tls`, `pck00010.tpc`, `de440.bsp` | NAIF generic kernels | leap seconds, Earth radii, Sun/Moon/planets |
| `earth_latest_high_prec.bpc` | NAIF generic kernels | ITRF93 Earth orientation, refreshed after `earth_pck_max_age` days; measured to its "last datum", predicted ~3 months beyond (both shown at start-up and in the report header; a window past the coverage is refused) |
| `earth_1962_*_combined.bpc` (optional) | NAIF generic kernels | ITRF93 Earth orientation from 1962 (measured to its creation, then a long-term prediction), for windows before 2000 (historic events); loaded before `earth_latest_high_prec.bpc`, which rules from 2000 on; fetched by a search or pick before 2000, or `setup --historic-earth` (~31 MB) |
| Asteroid orbit files | JPL Horizons API (`EPHEM_TYPE=SPK`), cached in `cache_path`, downloaded again after `orbit_max_age_days` (7) | `pysyzygos/search.py` positions |
| Asteroid size, H, G | SBDB API (`sbdb.api`, `phys-par=1`), cached per asteroid | `get_asteroid_size` |
| Elements, sizes for all asteroids | SBDB Query API (`sbdb_query.api`, numbered, full precision), cached | `pysyzygos/pick.py` |
| Asteroid names | SBDB full name, from the same per-asteroid cache as the size | `get_asteroid_name` |
| Stars | Gaia DR3 bulk files, `cdn.gea.esac.esa.int/Gaia/gdr3/gaia_source/` | local catalog |
| Stars, ready-made | Zenodo [doi:10.5281/zenodo.23113337](https://doi.org/10.5281/zenodo.23113337) (G <= 16) | local catalog without the build |
| Path uncertainty | Horizons observer table, RSS 3-sigma position | 3-sigma map lines |
| Asteroid satellites | W. R. Johnston, Binary Minor Planets Compilation V3.0 (NASA PDS 2019, [doi:10.26033/bb68-pw96](https://doi.org/10.26033/bb68-pw96)) plus satellites seen in occultations (archive below); extract `pysyzygos/data/binaries.json` | "+moon" in the tables, satellite line in the favorites panel, satellite zone on the maps |
| Earlier occultations | NASA PDS Small Bodies Node, "Small Bodies Occultations" V4.0 (Herald, Dunham et al., [doi:10.26033/ehqs-jp27](https://doi.org/10.26033/ehqs-jp27)), extract shipped as `pysyzygos/data/occultations_pds.json` | reference line in the favorites panel (not used for the prediction) |
| Map | Leaflet 1.9.4 (cdnjs); OpenStreetMap tiles (`--tile-url` for others) | report |
| Reference | Occult / OWC search results, pasted as text into `owc_reference.txt` (private, not in git) | validation |

### 4.1 Sizes: what Horizons/SBDB has, and what occultations measured

Horizons and the Small-Body Database hold no occultation chords or profiles. Their physical data is one summary per
asteroid: `diameter` (+- sigma, mostly from NEOWISE, AKARI, IRAS or radar), `extent` (three axes, only for a few dozen
well-studied bodies), albedo, rotation period, pole, taxonomic type. Occultation results reach Horizons only through
the orbit: an occultation gives a precise position, reported to the Minor Planet Center as astrometry.

The accepted occultation results are archived by NASA's Planetary Data System, Small Bodies Node: "Small Bodies
Occultations" (D. Herald, D. W. Dunham et al., about yearly; https://sbn.psi.edu/pds/resource/occ.html). Version 4.0
(2024-04-22) holds 9645 asteroid events of 2907 asteroids, 1958 to 2023-12:

* `AsteroidSummary`: per event the fitted ellipse (major/minor axis, position angle, uncertainties), a flag when the
  diameter was assumed rather than measured, and a quality code: 0 no reliable position or size (399 events),
  1 astrometry only (7374), 2 limits on size but no shape (1261), 3 reliable size (521), 4 resolution better than
  shape models (77).
* `AsteroidDiameters`: for 512 asteroids, the volume-equivalent diameter from fitting all their events to 3-D shape
  models (DAMIT, ISAM), with uncertainty: the best sizes available.
* `AsteroidTimes`: the chords (every observer's disappearance and reappearance), with names and positions.

Reliable measured sizes (codes 3-4, size not assumed) exist for 343 asteroids, median 120 km (90 % above 52 km): the
archive improves the large asteroids, while the small typical targets (a few km) mostly have no measured size, or
only astrometry. PySyzygos ships a compact extract (`pysyzygos/occultations.py`, `data/occultations_pds.json`, 387 kB:
per asteroid the number of events and years, quality counts, the best measured profile and the shape-model diameter;
no chords, no observer data) and shows it as a reference line with the size in the favorites panel. Using it as a
size source (before NEOWISE) is a possible next step; Occult's own archive (D. Herald) is newer than the PDS version.

### 4.2 Asteroid satellites

About 650 asteroids and TNOs have known companions (W. R. Johnston, "Asteroids with satellites", kept current at
https://www.johnstonsarchive.net/astro/asteroidmoons.html). The citable, downloadable version is his Binary Minor
Planets Compilation in NASA's PDS (V3.0, complete to 2019-03-31: 370 companions in 351 systems): per companion the
primary's and the companion's diameter, the distance (semimajor axis, km) and the orbital period. The occultation
archive (4.1) adds satellites seen in occultations (57 events of 40 asteroids: date, separation in mas, position
angle, size), including old reports that were never confirmed (e.g. Hebe 1977, Juno 1978).

PySyzygos ships an extract of both (`pysyzygos/binaries.py`, `data/binaries.json`, 325 numbered systems, 43 kB) and
shows it as reference information: "+moon" (or "+2 moons"; "+moon?" when only reported in an occultation and not in
Johnston's list) after the asteroid in the Results and Favorites tables, a "Satellites" line in the favorites panel,
and on the event maps (KML, report map, globe plot) a dotted **satellite zone** at the primary's shadow edge plus
the largest known moon distance plus its radius: a satellite's own shadow passes somewhere inside it. The satellite's
position at the event is not predicted: that needs its orbit (orientation and phase), known well for only a few
systems. Moons found after 2019 are not in the extract (Johnston's Archive has them).

---

## Part 5: Validation

All checks, with their numbers and the discussion of the differences, are in
**[VERIFICATION.md](VERIFICATION.md)**. In short:

- **Against OWC** (five search results at two sites, Oct 2-11 2026, 6 to 50 events each): the same stars (our Gaia G
  equals OWC's magnitude column), times within a few seconds (mostly under 2 s), drops within 0.25 mag below 5 mag,
  durations within 10 % where both use the same diameter. Latest set (Oct 8-11, 0.14.0): 44 of 50; the rest are two
  Gaia 2-parameter stars missing from the local catalog, one small asteroid's orbit and three drops (asteroid
  brightness).
- **Against Occult's plots:** star positions agree within Occult's 1-sigma since stellar parallax and light deflection
  were added (0.10.0).
- **Internal and geometric checks:** the corridor search against the old windows search, the pick screen, the pick's
  orbits against Horizons, planet and moon ephemerides and contact times, and the test suite.

---

## Part 6: Open items

- **Close and double stars** (since 2026-10-06 partly handled, `pysyzygos/doubles.py`): every event checks the local
  catalog for neighbours within `companion_radius_arcsec` (4") that are at most 5 mag fainter; their light stays in
  the camera image when the star is covered, so the drop is recomputed with it (`mag_drop_blended`), and noted with
  a warning sign in the report when it is at least 0.1 mag smaller. With `gaia_online_check` (default on) one query
  per run to the Gaia DR3 archive adds what the local catalog lacks: Gaia's hints that the star itself is double
  (`non_single_star`, `ipd_frac_multi_peak` > 2 %, `duplicated_source`, `ruwe`) and neighbours it leaves out (fainter
  than its limit, or RUWE >= 1.4). Still open, in order of value:
  1. Known doubles: match the event stars with the occultation-discovered doubles of the PDS archive
     (`DoubleStars` table; 76 discoveries before 2020, 61 closer than 50 mas) and the Washington Double Star Catalog.
  2. Events on stars the local catalogs leave out: Gaia 2-parameter sources (position only, no parallax or proper
     motion) and poorly measured stars (RUWE >= 1.4, often unresolved doubles). OWC lists them. Seen in the OWC set of
     Oct 8-11 2026: 2 of 50 events, both on 2-parameter stars of G 11.6 and 12.0 (VERIFICATION.md, 1.5), and an
     observed event of (86288) 1999 UC45 on 2026-09-30 (target RUWE 1.65). **Addressed by the supplement (2.4,
     2026-10-10; since 1.3.0 part of the catalog), with proper motions from UCAC5/UCAC4 and the star's position
     error in the path uncertainty (`star_sigma_mas`)**.
  3. Step events: for a known pair, the two shadows (offset by separation x distance) and the drop of each step.

- **218001**: OWC lists a 1.56 mag drop and 0.51 s, PySyzygos 12.97 mag and 0.25 s. The duration difference is the
  diameter (OWC 3.56 km, PySyzygos 1.77 km from H). The drop is unexplained; hypothesis (unverified): the 5.6 mag star's
  angular diameter is comparable to the shadow, making the event partial. Idea: Gaia `radius_gspphot` and
  `distance_gspphot` (angle in mas ~ 9.305 R / d_pc), a partial-coverage drop, and a flag when the star is larger than
  about 30 % of the shadow.
- **Stellar parallax**: applied since 0.10.0 together with the light deflection (see below); an early, unused
  `geocentric_star_dir` in pysyzygos/search.py did the same (superseded by `pysyzygos.astrometry.parallax_dir`,
  removed in 1.3.3).
- **`star_test`'s `observable` text column**: `if not observable(...)` tests a tuple (always true), so the text never
  says "no". Harmless today, because `handle_star` rejects unobservable events with `observable(...)[0]`.
- **Path uncertainty (sigma)** (the ellipse is now logged and drawn, 0.14.x: `ellipses.py`, favorites panel; the error
  across the track is shown there, e.g. 52 km instead of the RSS-based 80 km for 369152, 0.9 instead of 2.7 km for
  101716; still to do: use it for the sigma lines and the chance): use the part of the Horizons error ellipse across the track (quantity 37: `SMAA_3sigma`,
  `SMIA_3sigma`, `Theta_3sigma`, projected onto the direction across the shadow's motion) instead of the RSS value, which
  overstates the path width whenever the long axis lies along the track. Also: Horizons gives these values to 0.01"
  only, which is coarse for well-known orbits (0.01" is ~10 km at 1.4 AU), and a value that rounds to 0.00 falls back to
  the 10 km default. Then compare with OWC event by event; the OWC orbit uncertainty comes from another source, so an
  exact match is not expected.
- **Verified 2026-10-03**: the Horizons column is `RSS_3sigma` (matched by `path_sigma3_km`), and the Earth-PCK body
  id 3000 gives the coverage message at start-up.
- **Report**: the map uses OpenStreetMap tiles, which need the page served by a web server (a `file://` page sends no
  Referer, so the tiles are refused); `--tile-url` selects another tile server.
- **Ideas**: `m_before` / `m_during` columns in the log; process-level parallelism by target in `pysyzygos/search.py`.

### Gravitational light deflection and stellar parallax (built in 0.10.0, 2026-10-04)

**What PySyzygos does now.** The asteroid comes from `spkpos(..., 'CN', '399')`: light-time corrected, astrometric,
with no stellar aberration and no gravitational light deflection. The star direction is the Gaia DR3 catalog
direction, propagated with its proper motion (for stars brighter than G 13 corrected for Gaia's bright-star frame
spin, Cantat-Gaudin & Brandt 2021, A&A 649, A124: up to 80 micro-arcsec/yr; `gaia_pm_bias`, since 2026-10-15) and,
for nearby fast stars, with Gaia DR3's radial velocity (perspective acceleration, up to 75 mas by 2026 for Barnard's
star; `starrv.py`, `star_rv`, since 2026-10-16; the propagation equals the Gaia archive's EPOCH_PROP_POS to
<= 0.002 mas without and <= 0.025 mas with radial velocity, VERIFICATION.md section 4);
Gaia directions are by definition free of light deflection (the
catalog removes it). Aberration is consistent: neither source gets it, and it would shift both the same way, so it
cancels. Light deflection does not cancel: the star's light and the asteroid's reflected light are bent by
different amounts, because the asteroid is much closer.

**Size.** For a source in direction u seen from an observer at distance E from the Sun (unit vector e from the Sun
to the observer), with q the unit vector from the Sun to the source (q = u for a star):

    deflection = (2GM/c^2) / E * |u x (e x q)| / (1 + q.e)          (2GM/c^2 = 2.95 km for the Sun)
               = (2GM/c^2) / E * |e (u.q) - q (u.e)| / (1 + q.e)

(Explanatory Supplement, 3rd ed.; IAU SOFA iauLd). For a star (q = u) the numerator is e - (u.e) u; for the asteroid
q and u differ (the directions from the Sun and from the Earth). Up to 2026-10-15 PySyzygos used the star form for
the asteroid as well, which put the asteroid's deflection too close to the star's away from elongation ~90 deg (main
belt at 150 deg: difference 0.05 instead of 0.43 mas; Phaethon 2019: 7.39 instead of 6.94 mas). Found with Occult's
deflection values in the comparison of VERIFICATION.md section 3; the table below is with the correct form.

For a star this is 4.07 mas x (1 + cos eps) / sin eps at elongation eps (1.75" at the solar limb). What moves the
shadow path is the difference between the star's and the asteroid's deflection, times the asteroid's distance.

Sun, typical main-belt asteroid (2.5 AU from the Sun), observer at 1 AU:

| Elongation | Star | Asteroid | Difference | Asteroid distance | Shift of the path on the ground |
|---|---|---|---|---|---|
| 60 deg (twilight) | 7.05 mas | 4.83 mas | 2.22 mas | 2.85 AU | 4.6 km |
| 90 deg | 4.07 mas | 2.67 mas | 1.41 mas | 2.29 AU | 2.3 km |
| 120 deg | 2.35 mas | 1.47 mas | 0.88 mas | 1.85 AU | 1.2 km |
| 150 deg | 1.09 mas | 0.66 mas | 0.43 mas | 1.58 AU | 0.5 km |
| 170 deg | 0.36 mas | 0.21 mas | 0.14 mas | 1.51 AU | 0.16 km |

Jupiter (2GM/c^2 = 2.8 m, 4.2 AU away), a star at angular distance chi from Jupiter's centre, asteroid at 1.5 AU
(much closer than Jupiter, so its light is not bent by Jupiter):

| chi | Star deflection | Shift of the path |
|---|---|---|
| 20" (Jupiter's limb) | 19.1 mas | 21 km |
| 30" | 12.7 mas | 14 km |
| 1' | 6.4 mas | 7 km |
| 5' | 1.3 mas | 1.4 km |
| 10' | 0.6 mas | 0.7 km |
| 1 deg | 0.1 mas | 0.1 km |

Saturn gives about a third of Jupiter's effect at the same angle; Earth and Moon only micro-arcseconds. For an
asteroid beyond the deflecting planet (for Jupiter: Trojans, outer objects) both lights are bent and the difference
shrinks.

**What this means.**
- The Sun term is not an extreme case: away from opposition (morning and evening sky, elongation below ~120 deg)
  the path shifts by 0.5 to 6 km, the size of a small asteroid's shadow and of the 1-sigma band of a well-known
  orbit. Near opposition, where most good events are, it is negligible.
- The planet term matters only within a few arc-minutes of Jupiter (or closer for Saturn). Such events are rare,
  and the planet's glare makes them hard to observe, but they are scientifically interesting (appulses, the
  deflection itself) and should then be predicted correctly.
- The OWC comparison (Part 5, VERIFICATION.md) compared times (agreement 1-5 s); a few km along the track is well under a second.
  The cross-track position of the path, where this shift shows, has not been compared. As far as known, Occult
  includes light deflection (to be confirmed); then OWC paths of events away from opposition would differ from ours
  by the amounts above.

**Real events.** For an OWC search at Test site 2 (50 events, Oct 4-7 2026, with twilight events) the expected
shift was computed for every event: 16556 at elongation 65 deg (morning twilight) 4.6 km, 22336 at 79 deg (evening
twilight) 3.1 km, four events at 87-92 deg about 2.3 km, and below 0.1 km from elongation 150 deg on. So it is not
only twilight: events around elongation 90 deg in the dark evening or morning sky shift by about 2 km. These are the
events for a cross-track comparison with OWC.

**Occult applies it (checked 2026-10-04 on 16556).** Occult's printed star position for 16556 (elongation 65 deg)
differed from PySyzygos's (then Gaia with proper motion only) by 4.5 mas, nearly away from the Sun, as expected if
Occult applies the light deflection and the stellar parallax; with both added (0.10.0) the difference fell to 0.9 mas,
within Occult's 1-sigma. Details and a control case near opposition: [VERIFICATION.md](VERIFICATION.md), section 2.

**Implemented in 0.10.0 (2026-10-04).** `pysyzygos/astrometry.py` corrects the star direction once per candidate in
`handle_star`, at the estimated event time (both corrections change by micro-arcseconds within the solver window):
stellar parallax (Gaia parallax > 0) and the light deflection by the Sun, Jupiter and Saturn (GM from DE440),
applied as star minus asteroid since the asteroid (SPICE 'CN') stays undeflected. Everything after it (time, offset,
map, preview) uses the corrected direction; `star_ra`/`star_dec` in the log are that direction, and the log columns
`corr_parallax_mas`, `corr_deflection_mas` give the size of each correction. Switches in pysyzygos_config.py:
`star_parallax`, `light_deflection` (both default on); the run summary records them and the report header shows them.
Not yet in the pick screen (its ~2 km screening accuracy hides them).

Checks: `tests/test_astrometry.py` (4.07 mas at elongation 90 deg, 1.75" at the solar limb, the differences star
minus asteroid of the table above, Jupiter 6.36 mas at 1', parallax size and direction, switches off = unchanged);
switches off reproduce the previous results exactly; with the corrections an OWC set of 50 events gained two matches
and every path moved by the predicted amount; Occult's star positions now agree within its 1-sigma. Numbers:
[VERIFICATION.md](VERIFICATION.md), sections 1.4 and 2.

---|---|---|
  | Gaia only | 4.52 | 0.09 |
  | Gaia + parallax | 5.60 | 0.87 |
  | Gaia + deflection | 1.91 | 0.66 |
  | Gaia + parallax + deflection (0.10.0) | 0.90 | 0.29 |

  Only parallax plus deflection fits both within sub-mas and within Occult's 1-sigma (0.9 and 4.0 mas). 30819 alone
  is a weak test: near opposition the parallax (towards the Sun) and the deflection (away from it) partly cancel.
  A sharper test would be a star with parallax > 3 mas at elongation ~90 deg.

---

## Part 7: Future plans

### Major solar-system bodies as targets (planets and moons built in 0.14.0; Earth's Moon open)

Can the Moon, the planets and the major moons be targets, as an option? Partly: the Moon is close to straightforward,
planets and their moons are doable but each needs a few real additions.

**What already fits.** The solver is the standard fundamental-plane method, which works for any occulting body: a star,
a body position from SPICE and a radius. The corridor scan, the local Gaia catalog, the visibility checks, metrics,
maps and the report do not care what the occulting body is.

| Body | Orbit data | Effort and caveats |
|---|---|---|
| **Moon** | already in `de440.bsp` | Small: SPICE knows "MOON", its radius is in the kernels. Lunar occultations are IOTA's most common events. Caveats: hundreds of events per month at G <= 10 (needs its own magnitude limit); grazes need the lunar limb profile, which we do not have; bright-limb and daylight events need filtering. |
| **Planets** (Mars to Neptune) and **Pluto** | `de440` has only the barycentres; planet centres come from NAIF's satellite kernels (mar097, jup365, sat441, ura111, nep097, plu058; tens of MB up to about 1 GB for Jupiter; sizes unverified) | Medium: download these kernels as an option in setup. The giant planets are flattened (Jupiter ~7 %), so the shadow edge should come from the real limb ellipse (SPICE `edlimb`), not a circle. Rings and atmospheres (gradual drops, central flashes) are not modelled. The planet's glare limits detection, so the drop and observability rules need care. |
| **Major moons** (Galilean moons, Titan, Triton, Charon, ...) | the same satellite kernels | Like asteroids once the kernels are there: nearly spherical, radii from the kernels. They need a brightness table (their H is not in SBDB) for the drop, and handling of the nearby planet's glare. |

**Target names.** Asteroids are plain numbers, and NAIF moon ids collide with them (Io is 501, so is asteroid (501)).
Major bodies would be given by name in `targets`, e.g. `["218001", "Moon", "Io", "Titan"]`; SPICE resolves the names.

**User side (plan of 2026-10-08).** A GUI tab **Planets & Moons** after Pick, choosing targets in groups (no pick
needed: only a few dozen bodies): Moon · Mars system · Jupiter system (planet + Galilean moons) · Saturn system
(planet + major moons) · Uranus · Neptune + Triton · Pluto + Charon. A group's satellite kernel is downloaded the
first time it is chosen. The targets go into the same list, with a readable type prefix that cannot collide with
asteroid numbers: `L:Moon`, `P:Jupiter`, `M:Io`, `M:Titan` (not a letter plus a NAIF number). They run as their
own search (own limits: bright stars, glare, long windows); only the target preparation differs (no Horizons SPK,
no SBDB size: radii from the kernels, brightness from a table). The hit log marks the target type, so the report
can show planet events with or apart from asteroid events. Order: Moon first, then the Jupiter system, then the
rest.

**Suggested order.**
1. The Moon as an optional target: about half a day; no new data; many events to cross-check against Occult.
2. Planets and major moons by name: optional kernel downloads in setup, ellipsoid limbs, a brightness table; a day or
   two, with clear caveats about rings, atmospheres and glare.

The pick tool would not need to change: there are only a handful of major bodies, so they would simply be listed as
targets.

**Status (0.14.0, 2026-10-08): planets and moons are built** (`pysyzygos/bodies.py`; usage in README, "Planets and
moons"; checks in VERIFICATION.md, section 4): Mars to Neptune, Pluto and 91 of their 458 known moons, a GUI tab
with groups per system, D/R contact times, a results list and report layout of their own, previews with the
system's disks. Of the items below, 1-5, 7 and 8 are done (the preview without phase and glare halo); open are 6
(the limb ellipse: the limb is a circle of the equatorial radius, so a graze near a pole of Jupiter or Saturn may be
a miss; rings not modelled) and the Moon (`L:Moon`: bright limb, daylight, its 30' disk). One change to the plan:
the positions come from JPL Horizons (the same ephemeris as NAIF's satellite kernels), written into a small type 13
kernel per search window (~1 m); NAIF's kernels are an optional download (`pysyzygos setup --planet-kernels`).

**Implementation notes (2026-10-08, from a review of the current search).** The search loop itself works unchanged
for major bodies: corridor scan, solver (`besselian_offsets`, `star_test`), local Gaia catalog, star corrections,
visibility (`observable`), Moon info, maps, globe and report only ask SPICE for the target's position (`spkpos` with
`IO`, `MOON`, `599`, ... once the kernel is loaded). What a "target kind" check (asteroid / planet / moon / Moon,
from the `L:`/`P:`/`M:` prefix) has to change, most important first:

1. **Brightness, drop, star limit.** `corridor.limiting_star_mag` caps the star magnitude from the asteroid's H and G
   and the minimum drop, and `event_metrics` computes the drop from star + target light. Against Jupiter (mag -2)
   or the Moon (-12) every drop is ~0, so these filters would reject every event. Planets and the Moon: no drop
   filter and no H/G cap, a plain star limit instead (later: glare, i.e. how bright the star must be at a given
   distance from the limb). Major moons: a brightness table (V or G at opposition, phase law) in place of SBDB H/G;
   the drop formula then works as for asteroids.
2. **Contact times.** We log the moment of closest approach, which is enough for asteroids (seconds). For the
   Moon and planets, disappearance (D) and reappearance (R) are minutes to an hour apart, and those are what
   observers need: solve |offset(t)| = radius on both sides of the closest approach (same distance function,
   e.g. `brentq` on [t_ca - T, t_ca] and [t_ca, t_ca + T]); log `d_utc`, `r_utc`, and show them in the report.
   Bright or dark limb at D and R (Moon: position angle vs the terminator) is a useful extra.
3. **Light deflection.** `astrometry.corrected_star_dir` deflects by the Sun, Jupiter and Saturn as star minus
   target (`deflect(..., unit(ast - body), ...)`). With the target in that body's own system (Jupiter itself or a
   Galilean moon) the target-minus-body vector is ~0 or tiny: skip the target's own planet for the planet itself,
   and check the formula's validity for its moons (close to the planet the deflection of the star is real, mas).
4. **Target preparation** (`fetch_target_orbit`, `get_asteroid_size`, `get_asteroid_name` in `search.py`): no
   Horizons SPK and no SBDB. Load the group's satellite kernel (downloaded the first time, like the Gaia catalog;
   names and sizes to verify at NAIF), radius from the PCK (`bodvrd RADII`: mean for a circle, or the ellipsoid),
   name from a table.
5. **Path uncertainty.** `paths.path_sigma3_km` asks Horizons for the small-body RSS uncertainty, default
   `default_sigma3_km` (10 km). Planets and major moons are known to well below a km (Moon: metres): use a
   per-kind value, else the sigma lines and the Chance column are wrong.
6. **Shape.** The shadow is a circle of one radius. Fine for the Moon and the major moons; Jupiter and Saturn are
   flattened (6-10 %): first version with the mean radius and a note, later the limb ellipse (SPICE `edlimb`)
   projected on the fundamental plane. Rings and atmospheres (gradual drops, central flashes) are not modelled.
7. **Report and lookups.** The asteroid cell links to JPL SBDB and adds "+moon", the earlier-occultations line, the
   close-star check and OWC, all keyed by asteroid number: skip them for major bodies (or link to a suitable page,
   e.g. NASA/JPL's body page), and show the kind (e.g. a "planet" / "moon" badge). `observable`'s Sun limit stays;
   the Moon also needs a daylight/bright-limb filter.
8. **Preview image** (`preview.render_svg` via `search.write_preview`): it draws the target as a point with its
   track. For planets and the Moon draw the disk at its angular size (radius / distance) with the phase (lit side
   from the Sun direction), the planet's major moons at their positions in the field (from the same kernel), and
   optionally a glare halo; for a moon target also its planet if it is in or near the field. The field size must
   grow with the disk (the Moon is 30').

Hit log: a `target_kind` column (asteroid, planet, moon, moon_earth) so the report can list planet events with or
apart from asteroid events. The OWC check, the pick tool and the saved picks stay asteroid-only.

---

## Supplemental: related tools (notes for later)

Pointed out by a tester (2026-10-11); kept here for later work. These are references to compare with and to learn
from, not code bases PySyzygos is built on. If one is ever used as a library, it is
credited in the README, the GUI's About box and CITATION.cff.

**SORA, Stellar Occultation Reduction and Analysis** (Gomes-Júnior, Morgado, Benedetti-Rossi, Boufleur, Rommel,
Banda-Huarca, Kilic, Braga-Ribas, Sicardy; MNRAS 2022, [arXiv:2201.01799](https://arxiv.org/abs/2201.01799); docs
https://sora.readthedocs.io/latest/modules.html). An open-source Python library on astropy from the Lucky Star team,
"from predicting such events up to the determination of Solar System bodies' sizes, shapes, and positions"; it can
also predict events for observers in space (e.g. JWST near the Sun-Earth L2 point). Widely used and actively
developed. Its focus complements PySyzygos's: SORA studies chosen objects in depth (prediction, light-curve fitting,
chords, limb and ellipse fits, astrometry), PySyzygos screens all asteroids for the events at an observer's site
(bulk pick, pre-screens, planning GUI). Possible uses:
1. **A third independent validation reference** (besides OWC and Occult): predict the same events with SORA (e.g.
   (86288) 1999 UC45 on 2026-09-30 and some OWC reference sets), compare time, centre line and path width, and add the
   results to VERIFICATION.md. SORA would run in a separate environment, so PySyzygos's dependencies stay as they are.
2. **Analysis after an event** (open item "observation data per favorite": result, D/R times, chords): export a
   favorite's prediction and the observers' timings in a form SORA reads, or use SORA optionally where it is
   installed, instead of writing chord and shape fitting from scratch. Check its license and API before that.

**Marc Buie's IDL library** (https://www2.boulder.swri.edu/~buie/idl/): an extensive, long-standing collection of
occultation and astrometry routines in IDL. IDL is commercial (licence on request from NV5 Geospatial Software,
https://www.nv5geospatialsoftware.com/Products/IDL), so PySyzygos cannot run or depend on it; a valuable read for
methods and edge cases.
