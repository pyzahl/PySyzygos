# Changelog

All notable changes to PySyzygos. Newest first. Format: [Keep a Changelog](https://keepachangelog.com), versions:
[semantic versioning](https://semver.org) (MAJOR.MINOR.PATCH). The version and its code name live in
`src/pysyzygos/version.py`; the code name changes at major milestones. Details of the computations: `ABOUT.md`.

## [1.3.3] "Beyond Horizons" - 2026-10-19

### Added
- **Occult data, an optional add-on** (`occultdata.py`, `pysyzygos occult-data`, GUI System tab "Occult data"):
  asteroid data that D. Herald maintains for Occult, downloaded from IOTA's server per dataset (or copied from an
  Occult installation): infrared diameters (weighted mean and per survey, with albedos), H and G in two colours for
  ~122,000 asteroids, asteroid satellites with orbits, the occultation results archive and Gaia DR3 non-single stars.
  The favorites panel shows what they know about the asteroid and the star; with the archive installed, "earlier
  occultations" come from it (updated continuously) instead of the yearly NASA PDS extract. "Check for updates"
  compares the installed files with the server. Reference data only: the predictions do not use them yet.
  `pysyzygos info` and the System tab's "Data in use" list them; `pysyzygos cleanup` removes them.
- **Run summary and run logs**: pick, search and pre-screen build end with a table of their steps (time, share,
  count; `steps.py`), e.g. for a search: start-up, setup, orbits, sizes, corridor plans, star scan, early gate, star
  motion, corrections, exact solves, and per hit the path uncertainty (JPL Horizons), event data and maps, then the
  online double check and the results. The GUI shows it as a table under the log, and saves every run's output to
  `logs/<date>-<time>_<command>.log` (30 days; `cleanup` removes the folder).
- **Catalog data version 2.1 on Zenodo** (doi:10.5281/zenodo.23428079): the G <= 16 catalog with the epoch proper
  motions (core, quality, extras, star names), checked against the SHA-256 sums built into PySyzygos; the old-format
  archives stay in it for versions before 1.3.0. Setup and catalog updates now find it on Zenodo as well as on the
  mirror.
- **Shared world pre-screens** (`pysyzygos prescreen remote | fetch [name|latest] | publish`, Pick tab
  "Pre-screens -> Download shared"): whole-Earth pre-screens on the mirror (`URL_PRESCREEN_MIRRORS`, folder
  `world-prescreens/` with `prescreens.json`), downloaded instead of built (hours): one `<name>.tar.xz` +
  `.sha256`, resumable, SHA-256 checked, only the listed files unpacked and checked again, the meta file last. The first: 2026-10-01 + 40 days, G <= 16.

### Changed
- **Faster searches, same results**: the path uncertainties from JPL Horizons (one query per hit, the largest part of a
  search) now run 2 at a time after the exact solves (the hits are completed afterwards, in order); the asteroid sizes
  from SBDB are fetched 4 at a time while the orbits download. A 200-asteroid search: path uncertainties 48 s instead
  of 103 s; all 201 events identical field by field. A busy Horizons (HTTP 503) is asked again after a pause instead
  of falling back to the default uncertainty.

### Fixed
- **Searches of more than about 160 asteroids** stopped with SPICE(TOOMANYPAIRS) ("no room available for adding ...
  to the list of name/code pairs"): each asteroid number was registered as a SPICE body name with `boddef`, and this
  SPICE version keeps only 853 names, about 692 of them built in. The names now go into SPICE's kernel pool
  (`kernels.body_alias`, as a text kernel would define them), which takes thousands; planets and moons and the path
  check use it too.
- **Start-up time of runs started from the GUI**: the run summary (and the pick's timing line) counted from when
  the GUI was started, e.g. "start-up 186129 s" after two days; each run now gets its own start time.


## [1.3.2] "Beyond Horizons" - 2026-10-19

1.3.1 (version number set on 2026-10-17) was never released; its changes are part of this release.

### Added
- **Favorites tasks run beside a search, pick or pre-screen**: the path verification (compute our path, compare,
  step by step, export, keep) has its own job slot and its own log on the Favorites tab, which shows only those
  tasks; searches, picks, pre-screens and setup still run one at a time.
- **Proper-motion estimates for 2-parameter stars, per event** (`pmcheck.py`, config `pm_alternatives`): the search
  asks VizieR for the star's UCAC5 and UCAC4 rows and computes all four estimates (UCAC5, UCAC4, UCAC4 epoch to Gaia,
  UCAC4 J2000 to Gaia as Occult uses). Their spread becomes the star's uncertainty when larger than the quoted error
  (path sigma lines, chance), the map draws the centre line for each, the badge's hover lists them, the favorites
  panel shows "Other estimates". New amber badge "star ±X km" when the star's uncertainty is over half the asteroid's
  radius (red over the radius, as before). (4089) Galbraith: ±46 km instead of ±27; the line "as Occult" lies on
  Occult's centre line to 0.2 km.
- **Catalog data versions and updates**: each catalog shows its data version (System tab, header list, `setup
  --status`): v2.1 (epoch proper motions, 1.3.2), v2.0 (as published with 1.3.0), old format. A v2.0 catalog can
  be updated in place: System tab **Update to 2.1** or `pysyzygos setup --update-catalog` downloads only the changed
  parts (core, quality, xref), copies extras, and swaps (`starcat.data_version`, `update_available`, `update`).
- **Which proper motion a star has**: new record fields `star_pmra`, `star_pmdec`, `star_pm_err`, `star_pm_source`
  (Gaia DR3, UCAC5, UCAC4, UCAC4 epoch to Gaia, none); the favorites panel shows a "Proper motion" row, the ⚑ flag's
  hover text and the path verification's step-by-step name the source.
- **The ☆ in the results toggles**: a filled ★ removes the event from the favorites again (it asks first only when
  you gave the favorite a note or a status other than "planned"); the Favorites tab follows at once.
- **Your site's 360° photo** (Site tab, Horizon): an equirectangular photo (2:1, a 360° camera or a phone's photo
  sphere) shows the horizon line and the margin over the real view, and the favorites panel shows the star at the
  event time on it. The azimuth reference is set by hand or fitted to the horizon points; with the sky made
  transparent (PNG), the horizon line is read from the photo (`panorama.py`) and can be downloaded as
  `UserHorizon.txt` for OccultWatcher. Kept as a small copy in `horizons/` (private). New dependency: Pillow.
- **Path comparison input** (`pathcheck.parse_listing`): any path table works, not only Occult's exact layout:
  only the centre's longitude, latitude and UT are needed, other columns are ignored. Tables with a header row are
  read by column names (CSV, tab, semicolon, spaces; decimal or d m s, ° ′ ″, N/S/E/W, decimal commas; hh:mm:ss, ISO
  date-times, decimal hours); Occult's layouts also without the limit or altitude columns. A missing star altitude
  is computed, times near midnight go to the event's day. Occult's own listings read exactly as before.
- **UserHorizon.txt**: the horizon now belongs to the site in the form (the "Station in the file" select is gone; a
  file with several stations: the one named like the site); files saved with a byte-order mark (Windows editors,
  OccultWatcher's own) load, which failed before.
- **Better proper motions for 2-parameter stars** (`pysyzygos catalog pm-epoch`, and in the same pass as the `xref`
  part): a third estimate, from UCAC4's measured position (its central epoch, ~1998, with its error) to Gaia's 2016.0
  one; each star keeps the one with the smallest error among UCAC5, UCAC4 and this (new kind 5, "2-param, pm UCAC4
  epoch to Gaia"). UCAC4's own motions are often worse than they claim (test zone: 23 % beyond 3 sigma), so most of
  them are replaced. Found with (4089) Galbraith: Occult's path, 69 km from ours, uses a motion from UCAC4's J2000
  position, which carries UCAC4's own motion's error.
- **Double-star check (VizieR)**, a button in the favorites panel: the Washington Double Star Catalog's pairs at the
  star (discoverer, separation, position angle, magnitudes, first/last observed, notes; "O" = orbit in ORB6) and
  Gaia DR3's signs of a companion the local catalog does not keep (elongated image `ipd_gof_harmonic_amplitude`,
  position wobble `astrometric_excess_noise` and its significance, colour-window excess, plus RUWE, multi-peak,
  duplicated, NSS), with short readings; kept with the favorite. (4089) Galbraith's star: WDS AG 112 AB, 2.8",
  9.83 / 9.88 mag, observed since 1902; Gaia: two peaks in 41 % of scans, elongated, 19.8 mas excess noise.
- **Restart / Quit** (power button in the GUI header): for a GUI started from a launcher, no process to hunt for.
  Restart starts the same program again (with an installed update) and the page reconnects; Quit ends it. A
  running job is stopped first.
- **Azimuth in degrees**: a checkbox "az°" in the Altitude column's header shows the star's azimuth ("55° az 117°")
  instead of the compass direction ("55° SE"), in the results and favorites tables; remembered in the browser.
- **Your own horizon** (Site tab, "Horizon (optional)"): load OccultWatcher's `UserHorizon.txt` (`horizon.py`: its
  format and rules, several stations per file); a profile shows it; events whose star is behind it are marked ⛰
  yellow, those closer to it than the margin (default 15°, OccultWatcher's threshold) red, in the results, favorites
  and CSV; optionally events behind it are left out. Record fields `horizon_flag`, `horizon_alt`, `horizon_sep_deg`.
- **Chance with sigma**: the Chance column adds the site's distance from the centre line in units of the path's 1σ
  ("33 % · 0.6σ"); the favorites panel shows a bar across the path at the site (green the shadow, orange 1σ beyond
  its edges, black ticks at 3σ, a blue mark for the site with km, σ and chance).
- **Star names: catalog part `xref`** (`pysyzygos catalog xref`, or tick it in the System tab): each star's UCAC4,
  Tycho-2 and Hipparcos numbers. UCAC4 from its 900 zone files (CDS, streamed, none kept): our stars moved back to
  J2000 with Gaia's proper motions, the nearest UCAC4 star within 1" and 1.5 mag, one Gaia star per UCAC4 star (so
  a double like (4089) Galbraith's gets 573-029535 and 573-029536 right); TYC and HIP from Gaia DR3's
  best-neighbour tables. The search stores them with each event (`star_ucac4`, `star_tyc`, `star_hip`, end of the
  record); results, favorites, the Globe page and the CSV name the star "UCAC4 573-029535" instead of the long Gaia
  number, with Gaia DR3, TYC and HIP in the hover text and the event summary. Older favorites are filled in at GUI
  start.
- **System tab, catalog parts**: unticking a part asks first: **switch off, keep the files** (renamed
  `<part>.npy.off`, back at once when ticked again, no download) or **delete** (frees the space; the dialog says
  whether it can come back by download or only by a new build). Command line: `pysyzygos catalog off|on <part>`.
  (Before, unticking deleted the part at once.)
- **System tab, planets and moons offline**: a checkbox per planet system for its NAIF kernel (Jupiter, Saturn,
  Neptune, Pluto, Mars, with file and size): tick downloads it, untick deletes it after asking (positions then from
  JPL Horizons). Command line: `pysyzygos planets [status] | add [system ...] | remove system ...`.
- **Whole-Earth view on an A4 page** (`globe_page = "A4"`, default; `"square"` keeps the view alone): two panels
  below the view, from the event's own values: the geometry at true scale (Earth, target, Sun, Jupiter, Saturn, AU)
  and the light paths (AU along the star's direction, sideways offsets in mas): the star's bent ray, the target on
  it, where it would stand without deflection, and the shift that moves the shadow (e.g. Phaethon 2019-07-29: 6.94
  mas = 4.8 km); the Sun, and Jupiter or Saturn where they deflect the light, marked with their true distance.
  Plain SVG, 210 x 297 mm.

- **Catalog upgrade in the System tab**: for a catalog of the old format, "Upgrade the catalog" with the parts to
  install and "delete the old catalog when the new one is in place" (on by default); a dialog first says what it
  will do (G 16: download; other limits: a 2-hour build from ESA's files; a finished `<folder>.new` is only swapped
  in), the free disk space and the old catalog's size. Setup: `--delete-old` (with `--upgrade-catalog`) deletes the
  old catalog only after the new one is complete and swapped in; parts not chosen are removed from a `.new` built
  with all of them. The header's catalog list updates afterwards.

### Changed
- Results and favorites: an estimated size (from H and an assumed albedo) is marked by a box "size est." instead of
  a small "*"; the asteroid's hover shows its full name and size with a short source ("SBDB diameter (NEOWISE)")
  instead of the star's name and SBDB's raw reference.
- **After a restart the pick does not download the asteroid list again** when offline copies are on (System tab):
  an empty cache (Linux keeps it in memory, `/dev/shm`) is filled from the offline copy if that is younger than
  `sbdb_max_age_days`; the size data likewise.
- **Search start-up 7 s faster**: `import astroquery.gaia` contacted the Gaia archive at every start (status
  messages, 7.2 s; offline: until a timeout); it is now imported only where the old "windows" mode queries the
  archive. Missing orbit files are downloaded two at a time before pass 1 (JPL Horizons answers 503 to more; such
  answers are retried). A 19-target, 20-day search: 8.8 -> 2.6 s with the orbits cached, 23 -> 10 s without.
- Catalog download: each step is reported (asking Zenodo / each mirror with the answer time, speed measurement,
  download with resume, SHA-256 check, unpacking, part done), progress every 10 s in the GUI log (was 30 s); a slow
  mirror gets 90 s to answer (was 30 s: a busy Nextcloud took 23 s and would have been skipped).
- The online Gaia check says in the log why it still runs (stars fainter than the catalog limit - 5 mag: their
  neighbours go beyond the catalog; an old-format catalog; no quality part; high-RUWE stars switched off).

### Fixed
- **Catalog upgrade could drop finished parts**: swapping in an already finished new catalog removed every part not
  ticked in the upgrade choice (default "core + quality"), so a locally built xref or extras part was lost. A
  finished one now keeps all its parts; the choice offers "core + quality + star names" (default) and says what
  "all parts" includes.
- **UCAC4 zone downloads could hang for hours** (xref build): a server sending a few bytes now and then never
  tripped the read timeout; each zone file now has a limit for the whole download (10 min), then it is retried.
- **Stellarium showed the computer's time zone** after moving to the site (a site set by coordinates has no time
  zone in Stellarium): the link now also sets Stellarium's clock to the site's zone (`StelCore.currentTimeZone`, e.g.
  Europe/Zurich with summer time; from the favorites, else looked up once). The instant was right before too.
- **Favorites / results table wider than the window**: the site time's zone, the star warnings and the az° switch
  wrap onto a second line, so all columns fit again.
- Runs started by the GUI hung when setup asked a question: they inherited the terminal the GUI was started from,
  and the question (no line end) never reached the GUI log (seen with "Install the new catalog": it waited after
  "... then swapped in" until Enter was pressed in that terminal). GUI runs now get an empty input, so setup takes
  its defaults.

## [1.3.0] "Beyond Horizons" - 2026-10-16

### Added
- **New star catalog** (`pysyzygos/starcat.py`, `pysyzygos catalog build|fetch|add|remove|status|xmatch|pack`): all
  Gaia DR3 stars to the limit in one catalog, the high-RUWE and 2-parameter stars included (flagged; no separate
  supplement), sorted by 0.25 deg sky cell and G, so searches, picks, pre-screens and previews read one sort order
  and the pick needs no separate star index (1.3-2.8 GB less). Positions stored to 0.0002 mas in 8 bytes. In parts:
  **core** (2.4 GB for G <= 16, needed), **quality** (1.6 GB: RUWE, Gaia's errors, correlations and double-star flags)
  and **extras** (0.8 GB: BP/RP, radial velocity, Teff). G <= 16: 78.0 M stars, built from ESA's files in 1 h 49 min,
  465,590 of the 573,735 2-parameter stars with a UCAC5/UCAC4 proper motion. Checked against the earlier catalogs: the
  same stars, positions within 0.0001 mas, the same events for a 20-day search and a 4-day pick (times within 1 ms);
  search strips 2-7x faster.
- **Catalog mirrors** (`URL_CATALOG_MIRRORS`, env `PYSYZYGOS_CATALOG_MIRROR`, `catalog fetch --mirror`): the archives
  come from the fastest of Zenodo and the mirrors (a speed probe of each), an interrupted download continues from
  another source, and every file is checked against the SHA-256 stored in PySyzygos (`starcat.ARCHIVE_SHA256`).
  First mirror: a temporary folder on BNL's data box; tested end to end (core + quality, 3.2 GB, in 2.8 min).
- **The star's Gaia flags and error ellipse offline**: with the quality part they come from the local catalog for
  every event; the online Gaia check now only asks about stars whose neighbours the catalog may miss (the star less
  than 5 mag brighter than the catalog limit), so for bright stars the run does not wait for the archive.
- **Setup**: new installs get the new catalog (G <= 16 from Zenodo, other limits built from ESA's files),
  `--groups` for the parts, `--upgrade-catalog` for a catalog of the old format (installed next to it as
  `<folder>.new`, swapped in, the old one moved to `<folder>.old` and deleted on request).
- **System tab**: section "Star catalog" with a checkbox per optional part (download / remove), "Install the new
  catalog" for an old one and "Delete" for a leftover `.old` folder; "Data in use" shows the parts, and a new group
  **Planets and moons** (the moons' list, NAIF kernels with their range, Horizons files in the cache).

### Changed
- Zenodo carries the ready-made catalog for G <= 16 only (new archives `gaia_dr3_g16_v2_<part>.tar.xz`); deeper
  catalogs (G 17, 18, ...) are built locally from ESA's files. Catalogs of the old format keep working (marked "old
  format" in the GUI); `--supplement` and `pysyzygos gaia` remain for them.

## [1.2.0] "Beyond Horizons" - 2026-10-16

Released as tag `v1.2.01`: the tag `v1.2.0` was set one commit too early (still version 1.1.1, without the globe fix).

### Added
- **Offline use** (GUI tab **System**, `pysyzygos offline on|off|copy|status|remove`): copies of the pick's asteroid
  list (compressed, 103 MB -> 34 MB for H < 17), of the searches' orbit files and of the size cache in the data
  folder's `offline/`, kept with every download when switched on (the caches in `/dev/shm` are lost at a restart).
  Without network the pick uses the copied (or a stale cached) list, the search a copied orbit file covering its
  window and the copied size data, each with a warning saying how old it is. Tested with the network blocked: the
  Phaethon search gives the same event as online. The System tab also shows the data folder, runs
  `setup --status` and lists the **data in use** (`pysyzygos info`): leap seconds, Earth orientation (measured /
  predicted / valid range), DE440, the catalogs (in use marked), supplement, star indexes, the asteroid data in the
  cache and the copies, picks, pre-screens, results.

### Changed
- **GUI star limit (Pick, Search, Planets & Moons):** a note next to "Star G limit" says where the value comes from
  (the site's aperture, frames, exposure, MagAdjust, or its mag_limit; capped at the catalog's limit) and, in Pick,
  when the first pick would build a deeper star index (minutes, GBs on disk). A value you type is now kept until you
  reset it (↺), also across GUI restarts (gui_state `mag_override`); before, any edit in the Site tab reset it.
  Prompted by a site with 107 cm typed for 10.7 cm, which sent a pick to G 18 and a 10 GB index.
- Pick and pre-screen index progress: elapsed time and ETA as H:MM:SS (were seconds).
- **Orbit files expire:** a search downloads an asteroid's orbit (Horizons SPK) again when the cached file is older
  than `orbit_max_age_days` (new config key, default 1); before, a cached file was reused regardless of age. Without
  network the old file is used, with a warning giving its date. `pysyzygos info` (System tab) shows the oldest
  cached orbit. Why a day: JPL's solutions for main-belt asteroids are months old (median 133 days for H < 17, last
  observation median 306 days, 2026-10-16), but near-Earth asteroids often get a new one daily (11 % within a day),
  and a download costs only seconds. Manually: System tab **Download orbits again** (deletes the cached orbit files)
  and **Empty cache** (also the asteroid list and size data; offline copies kept), `pysyzygos cleanup --orbits` /
  `--cache`.

### Fixed
- Whole-Earth view (globe) missing after short searches (a window of an hour or two): its star-field inset asks for
  the asteroid's position a day before and after the event, past the end of the orbit file downloaded for such a
  window, and the search printed "no globe plot". Now a shorter step is taken there and drawn to a full day.
- `path-check steps`: the star's source_id was read from a mixed table row, i.e. through a float, and printed rounded
  (2637445446884721408 as ...721664); the radial-velocity lookup there used the rounded id too. Now taken from the
  int64 column. The star itself and the search were not affected. The proper-motion row names the proper motion and
  the years; the shift column says "mas, not mas/yr".

### Added
- **Path verification, step by step** (`pysyzygos path-check steps`, GUI: *Step by step* in the Favorites' path
  verification): the event from our side, stage by stage, for comparing with another program's own steps (asked for
  by Steve Preston): the star from the catalog through every correction with its amount, the asteroid (geocentric,
  barycentric, light time, its own deflection), the resulting vectors, the Besselian elements (ICRF axes and axes of
  date; d, mu, UT1 - UTC) at the shadow's touch-down, centre and leaving, and the geodetic points. *Compute our
  path* now removes the target's cached orbit files first, so it really uses today's orbit (the search reuses a
  cached orbit file of the same name however old it is).
- **Leap seconds:** the newest local leap-second kernel (naifNNNN.tls) is used, and NAIF's leap-second directory is
  checked with the weekly Earth orientation refresh: should a last leap second come before leap seconds end
  (2027-05-20), its new file is fetched by itself (`kernels.lsk_file`, `refresh_lsk`; `.lsk_checked`; offline:
  nothing happens).
- **The star's azimuth in the event record** (`star_az`, at the end): computed by the search with SPICE and the
  measured UT1 (equal to astropy/IERS to 0.0001 deg); the report's compass direction uses it. Its own `alt_az`
  (UT1 taken as UTC, no nutation; 0.003 deg off for Phaethon 2019) remains only for older records.
- **Radial velocities of fast nearby stars** in their propagation (perspective acceleration). The local catalog has
  no radial velocities; for nearby fast stars the missing term grows to tens of mas by 2026 (Barnard's star 75 mas,
  others 1-64 mas), tens of km on the ground at typical asteroid distances. `data/gaia_dr3_rv_fast.npy` holds Gaia
  DR3's radial velocity for every star where it moves the position by more than 0.01 mas within 20 years
  (164,602 stars; `starrv.py`, built from a Gaia archive query), used by `corridor.propagate_exact` (config
  `star_rv`, default on; shown in the report header). Checked against the Gaia archive's own propagation
  (EPOCH_PROP_POS): equal to <= 0.002 mas without and <= 0.025 mas with radial velocity (without the table the
  fastest stars were up to 74.8 mas off). Prompted by Paolo Tanga's suggestion
  to compare with the archive.

### Documentation
- ABOUT.md 2.2, "Time scales": how UTC, TDB and UT1 are handled, and why the end of leap seconds (CGPM 2026: UTC
  continuous from 2027-05-20) needs no change.

### Added
- **Path verification against Occult** (`pysyzygos path-check`, GUI Favorites with the "Path verification"
  checkbox): for a favorite, compute our geodetic path fresh (the search for that event only, today's orbit; path and
  orbit files kept with the favorite), export it in Occult's listing layout, and compare it with Occult's listing
  (pasted or loaded, optionally with its plot header): a Markdown report in a popup and a CSV, by the method of
  VERIFICATION.md section 3 (it reproduces the Phaethon numbers there); optionally kept in `owc_refs/occult_paths/`
  with an index line. `pathcheck.py`, `tests/test_pathcheck.py`.
- **Site heights above sea level corrected to the WGS84 ellipsoid.** Elevations from maps, Open-Meteo and most GPS
  displays are above mean sea level (the geoid), but the geometry needs the height above the ellipsoid; they differ by
  -107 to +85 m (the test sites: -32 to +48 m), which moved the path relative to a site by that over tan(star
  altitude) (about 85 m at 20 deg). Each site's geoid height (EGM96, NGA, public domain; `geoid.py` with a 0.5 deg grid
  in `data/egm96_30min.npy`, 0.12 m rms against the 15-minute grid) is looked up once when the site is saved and kept
  in sites.py as `geoid_m`; the config adds it (`ELE = ele + geoid_m`, also with older user config files). GUI Site
  tab: "Elevation is above sea level / above WGS84 ellipsoid" (MPC observatory codes set the latter: `ele_ref`);
  `pysyzygos setup --geoid` fills in all sites; `setup --status` and the report header show the heights. Existing
  sites keep their old behaviour until saved once (the GUI saves an edited or older site before a run). Prompted by
  Occult's author (site elevations are given above mean sea level). Shared sites.py reading and writing:
  `sitesfile.py`.

### Fixed
- `gaia supplement-pm` (and `setup --supplement`) rerun: its record in the supplement's catalog.json counted only that
  run's new matches, so a rerun on a finished supplement reported "0 from UCAC5, 0 from UCAC4" and `setup --status`
  "2-param stars with pm: 0 of 108169", although the proper motions were in the star files. The record now counts
  all stars in the files (465,566 of 573,735 for G <= 16). Data were never affected.

## [1.1.1] "Beyond Horizons" - 2026-10-16

The shadow at each observer is now computed with the asteroid as that observer sees it: the light time from the
observer, not from the Earth's centre. This removed the last systematic difference to Occult's path of (3200)
Phaethon: across the track the two now agree within the listing's rounding (+-30 m), along it within 11 ms
(VERIFICATION.md sections 3 and 5). The OWC regression checks are unchanged (15 of 16, 45 of 50).

### Fixed
- **The asteroid as each observer sees it: light time from the observer, not from the Earth's centre.** An observer
  closer to the asteroid by z = R sin(star altitude) receives its light z/c sooner (up to 21 ms), and in that time the
  asteroid moves with its barycentric velocity; equivalently, in the Earth's frame the shadow runs along the star's
  aberrated direction. PySyzygos used the geocentric light time for every site, which put the shadow up to
  (v/c) R sin(alt), about 0.4-0.9 km for typical velocities, off at the surface: zero at the limb, largest with the
  star high. Site solver (`search.besselian_offsets`: SPICE `spkcpo` with the site fixed in ITRF93, 'CN') and path
  lines (`paths.shadow_path`: per ground point, the axis moved by the asteroid's barycentric velocity x the point's
  light-time difference). Found in the comparison with Occult's Phaethon path: across the track the two paths now
  agree within +-30 m (before +0.17 to +0.47 km), what is left is a constant 11 ms along the track
  (VERIFICATION.md section 3). Checked against a hand-iterated light time with real SPICE (0.0000 m).

## [1.1.0] "Beyond Horizons" - 2026-10-15

More accurate paths, found in a whole-path comparison with Occult ((3200) Phaethon 2019-07-29, VERIFICATION.md
section 3): the light deflection of the asteroid is now computed with the formula for a source at a finite distance
(it was off by up to ~1 km across the track, most near opposition), and Gaia's proper motions of bright stars are
corrected for their known bias. Also: paths that were cut off at one end are complete, and twilight events of bright
stars are kept and marked (default Sun limit 0 deg).
New code name "Beyond Horizons" (before: "New Horizons"): the orbits still come from JPL Horizons, and the
astrometry is now checked beyond them, whole paths across the globe against an independent program.
Zenodo: doi:10.5281/zenodo.23407110 (this release; all versions: 10.5281/zenodo.23149371).

### Added
- **Twilight mark**: events with the Sun above -12 deg at the site get "☼ −8°" next to the star magnitude (Results
  and Planets & Moons pages, Markdown, favorites, CSV exports with a new `sun_alt` value, the GUI Pick table; hover:
  civil or nautical twilight). Only bright stars are seen in twilight (`report.twilight_text`, `TWILIGHT_SUN_ALT`).

- **Gaia proper-motion bias of bright stars**: proper motions of stars brighter than G 13 are corrected for the
  frame spin of Gaia DR3's bright stars (Cantat-Gaudin & Brandt 2021, A&A 649, A124; up to 80 micro-arcsec/yr, up to
  ~0.8 mas in 2026), as Occult does (`astrometry.gaia_pm_bias`, identical to the paper's function; config
  `gaia_pm_bias`, default on; shown in the report header). Not for the UCAC proper motions of 2-parameter stars.

### Changed
- **Default Sun limit 0 deg** (was -6) for sites without their own `max_sun_alt` (config template, GUI Site tab,
  pick, pre-screens): twilight events of bright stars are kept and marked instead of dropped. Prompted by
  (3200) Phaethon on 2019-07-29 (G 7.3 star, Sun at -8 to -13 deg where it was observed), which a -12 deg limit hid.
  Sites that set `max_sun_alt` keep their value.

### Fixed
- **Light deflection of the asteroid** (since 0.10.0): the deflection formula's star form, numerator e - (p.e) p, was
  used for the asteroid too; for a source at a finite distance it is e (p.q) - q (p.e) (Explanatory Supplement;
  IAU SOFA iauLd). The asteroid's deflection was too close to the star's away from elongation ~90 deg, so paths were
  off across the track by up to ~1 km for main-belt asteroids (largest near opposition: 0.43 instead of 0.05 mas at
  150 deg) and 0.3 km for Phaethon 2019. Found with Occult's deflection values (VERIFICATION.md section 3); tested
  against a transcription of iauLd. Results change accordingly.
- **Shadow paths (KML, path files, whole-Earth view) cut off at one end** when the event's time at the observer's
  site lies near one end of the track: the path's time span was centred on that time and covered 1.3 Earth radii of
  motion either side, so the other end could be missing (Phaethon 2019-07-29: the path started 3 minutes late, found
  in the comparison with Occult, VERIFICATION.md section 3). The span is now centred on the shadow axis's closest
  approach to the Earth's centre (`paths.shadow_path`; an explicit `half_span` stays centred on the given time).

## [1.0.0] "New Horizons" - 2026-10-14

PyOccult is now **PySyzygos**. *Syzygos* is Greek for "yoked together", the root of *syzygy*: three celestial bodies
in a straight line, as the observer, the asteroid and the star are during an occultation. The predictions are
unchanged; names, the command and the package are new. Old installations keep working: the old names are still read
for a transition period. The GitHub repository moved to https://github.com/pyzahl/PySyzygos (the old address forwards).
Zenodo: doi:10.5281/zenodo.23381498 (this release; all versions: 10.5281/zenodo.23149371, unchanged).

### Changed
- **Name**: command `pysyzygos` (was `pyoccult`), Python package `pysyzygos` (`src/pysyzygos/`), settings file
  `pysyzygos_config.py`, results database `pysyzygos.db`, environment variables `PYSYZYGOS_HOME`, `PYSYZYGOS_SITE`,
  `PYSYZYGOS_CATALOG`, `PYSYZYGOS_SUPPLEMENT`, data-folder setting in `~/.config/pysyzygos/home` (macOS
  `~/Library/Application Support/PySyzygos/home`, Windows `%APPDATA%\PySyzygos\home`), default data folder
  `~/PySyzygos`, cache files `PySyzygos_*`, logo `pysyzygos_logo.svg/.png` (same design).
- Documentation, GUI About box and CITATION.cff: the name and its origin.
- A source checkout needs a fresh install after updating: `pip install -e .` in the project folder (or
  `linux_install.sh`, or `uv run pysyzygos`, which does it by itself), because the installed package name changed.

### Transition (names before 1.0.0, still read)
- `PYOCCULT_*` environment variables count as `PYSYZYGOS_*` where those are not set.
- The data-folder setting of PyOccult (`~/.config/pyoccult/home` etc.) is copied to the new place once; an existing
  `~/PyOccult` stays the default data folder of an installed copy.
- In the data folder, `pyoccult_config.py` becomes `pysyzygos_config.py` on the first start, with the old names in it
  replaced (the original kept as `pyoccult_config.py.pre-1.0`), and `pyoccult.db` becomes `pysyzygos.db`. A message
  says so.
- `pysyzygos cleanup` also finds the old file and cache names.

## [0.18.0] "New Horizons" - 2026-10-12

More honest predictions for less well-measured stars, and older events. Gaia gives no proper motion for its
"2-parameter" stars; PySyzygos now takes it from UCAC5 or UCAC4 (as OWC does) and puts every supplement star's position
uncertainty into the path, with a red warning where it decides whether the shadow reaches the site (a false "hit" of
(4089) Galbraith, OWC 100+ km away, prompted it). Shadow paths are exactly on the WGS84 ellipsoid at height 0 (as
Occult's default output), events before 2000 work with NAIF's historic Earth orientation, and four near-Earth asteroid
events of 2019-2021 (Phaethon, Apophis) check out. Also: Windows fixes for the first installs, always a decimal point
in the GUI, pick timings, and a debug file of each event's geodetic path.

### Added
- **Historic events before 2000**: the Earth orientation file `earth_latest_high_prec.bpc` starts 2000-01-01; for
  earlier windows PySyzygos loads NAIF's historic `earth_1962_*_combined.bpc` (measured from 1962; ~31 MB; the newest
  by name) before it, so the high-precision file still rules from 2000 on (checked: identical there). A search or pick
  before 2000 downloads it when missing (`pysyzygos setup --historic-earth` beforehand); every search now checks that
  the whole window has Earth orientation (before: only its end) and stops with a clear message otherwise (e.g.
  before 1962). `setup --status`, `cleanup` and the run summary know the file.
- **Proper motions for the supplement's 2-parameter stars** (Gaia DR3 has none for them): `pysyzygos gaia
  supplement-pm` (run automatically by `setup --supplement` and `gaia supplement`) cross-matches them with UCAC5
  (Gaia DR1 2015.0 positions within 0.2", G within 0.5 mag), then UCAC4, through CDS XMatch, as OWC/Occult take them
  from other catalogs. Of 573,735 stars (G <= 16): 294,328 from UCAC5, 171,238 from UCAC4, 108,169 still without
  (2 min). Flags: "2-param, pm UCAC5" / "pm UCAC4" / "NO proper motion".
- **The star's position uncertainty in the path**: for supplement stars the 1-sigma position at the event date
  (2-parameter: position error + proper-motion error, or 10 mas/yr per axis when none is known, times the years
  since 2016; high RUWE: Gaia's errors scaled by RUWE) is converted to km and combined with the orbit's sigma: wider
  1- and 3-sigma lines, an honest "chance at site", a star error ellipse. Record fields `star_sigma_mas`,
  `star_sigma_km`, `ast_sigma1_km`. When it exceeds the asteroid's radius the report shows a red "⚠ star ±157 km"
  (Pick table: "⚠ 2-param, NO proper motion").
- Debug option `debug_save_paths` (config, default off): each event's geodetic shadow path (WGS84, height 0 m) (centre, edges, 1- and
  3-sigma limits, satellite zone; ET, longitude, latitude, duration) together with the event (target, Gaia star, time,
  size, sigma, site, version) as `<map_dir>/<event>_path.npz`, for later verification.
- The pick prints where its time went: `timing: total … = start-up + asteroid list + kernels + pre-screen (or
  asteroid choice) + screen (workers incl.) + output` (start-up measured from the start of the `pysyzygos` command).

### Changed
- Geodetic coordinates use the WGS84 ellipsoid exactly (`pysyzygos/earth.py`): shadow paths are points at height 0 m
  on WGS84 (as Occult's default output, for exact comparisons), and sites, the observer and the globe plot convert
  with it too. Before, the SPICE kernel's Earth radii (pck00010, ~0.4 m off WGS84) were used: paths move by 0.3 m
  (median), up to ~3.6 m near the limb.
- Documentation: VERIFICATION.md section 4 (then 3) with four near-Earth asteroid events (Phaethon 2019 and 2021,
  Apophis 2021 x2): found by the regular search on the right Gaia stars within 1-3 m of the computed centre
  lines; one given time (Phaethon 2021-10-03 "17:30 UT") does not fit any star. README: installing and
  updating the supplement's proper motions; all setup options in one table.

### Fixed
- GUI number fields always use the decimal point (45.12345): Firefox formatted them by the browser's language
  (German: 45,12345), unlike the values, logs and reports. The page now declares English (`lang`) and every number
  field carries `lang="en"`; a pasted number with a decimal comma (45,12345) is converted.
- (4089) Galbraith on 2026-10-13: a predicted "hit" 1.6 km from a site was on a G 9.8 2-parameter Gaia star (a
  resolved double, no proper motion) whose 2016 position was used unchanged; OWC put the path over 100 km away. With
  UCAC5's proper motion the path lies 206 km away (±27 km); without a proper motion the event is now shown with its
  real uncertainty (±157 km, chance 1 %).
- Windows: building the bright-star index failed at the end with `PermissionError: [WinError 32] … being used by
  another process` (in setup and before the first pick), so picks could not run. The index file was still
  memory-mapped (a NumPy view kept the mapping open) when it was renamed into place, which Windows refuses (Linux and
  macOS allow it). The sort now works on copies and releases the mapping first; all finished files (catalog, index,
  pre-screens) are renamed through `gaia_local.replace_file`, which retries for ~10 s on "file in use" (e.g. a virus
  scanner holding a new file). Setup no longer blames the network for such errors. Tests check that no file is
  mapped at its rename.
- Windows: a console with a legacy code page (cp1252) crashed on PySyzygos's symbols (e.g. "✅ All kernels verified" during
  setup: `UnicodeEncodeError`). Console output now replaces characters it cannot show with "?" (every command), and runs
  started by the GUI use Python's UTF-8 mode, so the log shows them all. README: do not install from an administrator
  prompt (it starts in `C:\Windows\System32`).

## [0.17.0] "New Horizons" - 2026-10-11

Events on the stars Gaia measured less well are now predicted, flagged: a high-RUWE supplement of the local catalog
(8.0 M stars with RUWE >= 1.4 or without proper motions, 0.35 GB, ready-made on Zenodo) is merged into picks, searches
and pre-screens, so an event like (86288) 1999 UC45 on 2026-09-30, observed from three sites and missed before, is
found (1.17 s predicted, 1.17 s observed). Also: `pysyzygos cleanup` to start over, coordinates pasted in any usual
format in the Site tab, named regions in the GUI, and clearer documentation.

### Added
- `pysyzygos cleanup`: remove what PySyzygos downloaded and generated (kernels, its cache files, bright-star indexes,
  the supplement, run outputs), keeping the large Gaia catalogs, `owc_refs/`, `private-docs/`, `release/` and `.venv`;
  a dry run with sizes unless `--yes`; `--keep-results`, `--all` (also settings and favorites). For testing a fresh
  install.
- **High-RUWE supplement** of the local catalog (`pysyzygos gaia supplement --dir <catalog> --gmax 16`, into
  `<catalog>/supplement/`): the stars the main catalog leaves out, Gaia RUWE >= 1.4 (often unresolved doubles) and
  2-parameter sources (no parallax or proper motion), about 8 M stars / 0.3 GB to G 16. Picks, searches and
  pre-screens use it when present (GUI header "+ high-RUWE stars", config `gaia_supplement`, env
  `PYSYZYGOS_SUPPLEMENT`); events on such stars are flagged ⚑ ("RUWE 1.65", "2-param") in the results, report,
  favorites, Pick table and CSV (`star_kind`, `star_ruwe`, `star_flag` at the end of the record). Pre-screens record
  whether they were built with it. `pysyzygos setup --supplement` (`--supplement-gmax`) installs it, a first-time
  setup offers it, `setup --status` shows it: ready-made from Zenodo (catalog record version 2,
  doi:10.5281/zenodo.23298192, 0.35 GB, SHA-256 checked) or built from ESA's files (`--source esa`, ~2 h). Motivation: (86288) 1999 UC45 on 2026-09-30, observed by three stations, was not
  predictable (its G 11.7 target has RUWE 1.65); OWC lists such events.
- GUI Site tab: coordinates pasted as text into Latitude, Longitude or Elevation are parsed (`geo.parse_coords`):
  labels in any order (lat/latitude, lon/lng/long/longitude, alt/elevation/height, also German), degrees-minutes-
  seconds, decimal minutes or decimal degrees, N/S/E/W or signs, heights in m/ft/km; without labels latitude first
  (as Google Maps copies them). All three fields are filled, the map marker moves, a missing elevation is looked up.
- GUI Pick tab, Pre-screens panel: the named regions (USA, North/Central/South America, Europe, Africa, Middle East,
  East Asia, Japan, Australia, New Zealand) in the Region selector, with their lat/lon boxes.

### Changed
- Documentation: README sections "If something goes wrong: start over" and
  "Files, copying and sharing" (pre-screens); ABOUT.md 3.8, where a prediction's time goes and what a live search
  engine would keep ready.

## [0.16.0] "New Horizons" - 2026-10-10

Picks in seconds instead of minutes: a pre-screen does the site-independent part of a pick (which asteroids can put
a star's shadow on the Earth at all) once for a window and stores it, for a region or for the whole Earth. A
whole-Earth pre-screen stores each event's shadow path (Besselian-element style), so any site, or any region cut from
it, is tested in seconds; for a 4-day window the pick with it gave exactly the full pick's events in 14 s instead of
210 s. In the GUI, "Asteroids: auto" uses a fitting pre-screen by itself, and a Pre-screens panel builds and lists
them. Picks and builds also run up to 2.4x faster with one math thread per worker.

### Added
- **Pre-screens** (`pysyzygos/prescreen.py`, `pysyzygos prescreen build|list|show|query|extract|index`): the asteroids
  with possible occultations in a window, using the pick's own parts (SBDB elements, orbits, bright-star index,
  candidate scan) for the whole Earth plus each candidate's ground track (161 samples, the Earth's rotation from SPICE).
  Regions: a box around the site (`--around-site KM`), one box around all sites of sites.py (`--around-sites KM`,
  the short way round across the date line), named regions (`--region usa|europe|south-america|...`) or a lat/lon
  box. A strict superset of what any fitting pick finds: every test is widened by what can change between samples,
  and the reach, a distance in the fundamental plane, is turned into the exact largest ground distance of an
  observer (`shadowtrack.ground_reach`: up to 1/sin(star altitude) longer); the orbit grid reaches 12 h beyond the
  window, so events whose track touches it are found. Checked against dense sampling and the exact site test at many
  sites (VERIFICATION.md).
- **Whole-Earth pre-screens** (`prescreen build --global`, new `pysyzygos/shadowtrack.py`): per event the shadow's
  motion across the fundamental plane (star direction, quadratic in time, misfit; 80 bytes) in a time-sorted
  `.global.npy` + `.json`, at about the cost of a region build (~1 GB per month at G 16 for 465k asteroids). An
  **index** (`.idx.npy`, written after the build; `prescreen index` for older files) holds each track's lat/lon box
  and star altitude range, so a site or region query tests only the events that can reach it (14-26 %).
  `prescreen query` (asteroids for the site), `prescreen extract` (a region file, optionally shorter window and
  brighter star limit, e.g. a continent to share).
- **Picks with pre-screens**: `pick --prescreen FILE|auto`; auto takes the newest pre-screen that fits the site,
  window and limits, else screens all asteroids and says why none fits. Only the pre-screen's asteroids with an event
  in the window and a star within the pick's star limit are screened (a whole-Earth file: those passing the site
  test). `targets.py` notes which asteroids were screened. Same events as the full pick (checked).
- **Pre-screen builds fit the free memory and resume**: chunk size and workers from the available memory and a
  measured model of the NumPy arrays; chunks shrink when memory runs low; every chunk is committed to `<name>.partial`
  and the same command resumes after a crash, Ctrl-C or the GUI's Stop (`--fresh` starts over; a build of an older
  format is refused with a clear message). Verbose progress: the plan, then per chunk rate, ETA, free memory, swap
  and worker memory. Stop ends the workers at once. The candidate scan and ground tracks run in bounded blocks.
- GUI Pick tab: "Asteroids" = auto (default) / all (any place and time) / a fitting pre-screen, with a line saying
  what the pick will screen; a "Pre-screens" panel to build one (start, days, region: this site, all my sites, whole
  Earth; box km; Start over) with its progress in the log, and a table of the built ones (window, region, sites
  inside, limits, asteroids/events, age, fits this pick or why not) with delete.

### Fixed
- Pick workers use one NumPy (OpenBLAS) thread each: before, every worker started one thread per CPU (4 workers on
  8 cores: 32 busy threads, each worker at ~40 % of a CPU); a pre-screen build ran 2.4x faster with the fix.

## [0.15.0] "New Horizons" - 2026-10-10

The favorites panel now summarises each event like OccultWatcher Cloud's event page (prediction, event, star,
object; checked against OWC), with the sky-plane uncertainty ellipses of the target, the star and both combined in one
diagram. All verification is in the new VERIFICATION.md, with the full lists of two 50-event OWC comparisons. Also:
the GUI remembers its site and catalog, a target unknown to JPL Horizons no longer stops a search, and maps no
longer show a false second path for tracks across the date line.

### Added
- GUI: the site and catalog chosen at the top right are remembered across restarts (`gui_state.json` in the
  data folder, private); a site or catalog that no longer exists falls back to the default.
- **VERIFICATION.md**: all checks in one place (OWC search results, Occult's star positions, internal and geometric
  checks, what the differences mean), moved out of ABOUT.md Part 5 (now a summary with a link), with a new OWC set
  (Oct 8-11 2026, 50 events: 44 match; two events on Gaia 2-parameter stars the local catalog leaves out, one small
  asteroid's orbit, three drops by the asteroid's brightness) and the full lists of both 50-event sets (matches,
  misses, extras, time differences over 1.5 s marked). ABOUT.md has a table of contents.
- Favorites panel: an **event summary laid out like OccultWatcher Cloud's event page** (Prediction, Event, Target
  star, Object): orbit solution (JPL# and date, from SBDB), path error in path widths and in time, the times the
  shadow is on the Earth (From/To), combined magnitude, solar and Moon elongation, Moon phase, constellation, the
  star's ICRS and apparent (true equator and equinox of date) position, the target's angular diameter, distance and
  motion. Checked on 369152 (Oct 12 2026) against OWC: From/To within 1 s, distance, elongations, star positions
  (apparent within 6 mas) and magnitude as OWC. The search logs the new values with each event (`dist_au`,
  `motion_ra_ash`, `motion_dec_ash`, `sun_elong_deg`, `m_combined`, `shadow_from_utc`, `shadow_to_utc`); older
  favorites get them once from JPL Horizons at GUI start (From/To then from the map's minute marks, marked ≈).
  Not available locally, so not shown: the star's V/R/B magnitudes, its diameter and RUWE (the local catalog keeps
  RUWE < 1.4), and the error ellipse (Horizons gives its RSS size).
- Favorites panel layout: title "<asteroid> occults <Gaia DR3 star> around <time> UT at <site> (lat, lon, height)"; the four
  groups (Prediction, Event, Star, Object) in a larger font, the Object group with H, albedo, shape and rotation and
  the known satellites, the Star group with RUWE and the close/double-star check; the uncertainty-ellipse diagram at the
  bottom left next to status and note. The separate lines for site, size, shape, double star and satellites are
  gone (now in the groups). When Gaia's errors for the star are not at hand (archive not reached, 2-parameter
  source), the diagram uses a typical Gaia DR3 star of that G (Lindegren et al. 2021), marked "!".
- Favorites panel: the **sky-plane 1-sigma uncertainty ellipses** of the event in one diagram, titled "Uncertainty
  ellipses (sky plane, 1σ)", at one scale (as OWC's
  "Error Ellipses", but overlaid): the target's (JPL Horizons SMAA/SMIA/Theta), the star's (Gaia DR3 position and
  proper-motion errors with their correlations, carried to the event date; at true scale usually a dot) and the
  combined one, with the target's motion and the **error across the track** in mas and km (only that part shifts
  the path). Checked on 369152 against OWC: target 28.00 x 22.33 mas @ 94, star 0.28 x 0.26 mas @ 90, combined
  28.00 x 22.33 mas @ 94 (OWC 22.30); with Gaia's correlations, which OWC seems to leave out (without them
  ours equals OWC's), the star's ellipse is 0.30 x 0.22 mas @ 126 (1 % of the target's). The search logs the target's ellipse (`ast_err_*`), the Gaia online check
  the star's (`star_err_*`); older favorites get them once at GUI start (Horizons, one Gaia job, in the
  background). New module `pysyzygos/ellipses.py`.
  The diagram also shows the target's disk at its angular size and the star where it stands as seen from the site
  at closest approach (its ellipse again, dashed, with its track relative to the target): from the logged offsets
  of the shadow axis, so its distance from the centre is the site's distance from the centre line (in mas and km,
  "inside" or "outside" the shadow). A star more than 2 shadow widths outside is not drawn (the diagram does not
  zoom out for it); the legend gives its distance.
- `pysyzygos owc-check --markdown FILE`: the full comparison as a Markdown table, by star magnitude (every OWC event
  and PySyzygos's extra events, marked); `--hits FILE` compares a saved hit list (with `--compare-only`).

### Fixed
- Maps (report, favorites): a shadow path across the date line showed a false second path, a straight band
  along one latitude across the whole map (the step from -179.8 to +178.8 deg drawn the long way round). Longitudes
  are now continuous along each line, placed next to the observer. The KML files themselves were right.
- Gaia online check (close and double stars, now also the star's errors): synchronous queries in chunks instead of
  one asynchronous job, whose status polling hung for minutes (October 2026) while the synchronous query answered
  in seconds.
- Search: a target JPL Horizons does not know (e.g. a mistyped asteroid number) stopped the whole run with a
  traceback. It is now skipped with a one-line reason, the others are searched, and the run summary lists it
  (`skipped_targets`).
- `owc-check`: OWC tag words in capitals (e.g. "IBEROC") are no longer taken as part of the asteroid's name.

## [0.14.0] "New Horizons" - 2026-10-08

**Planets and moons** join the asteroids as occulting bodies: Mars to Neptune, Pluto and 91 of their moons, in
their own GUI tab with disappearance and reappearance times. All results now live in one **results database**
(`pysyzygos.db`). Also new: Stellarium pointing, a column file for the CSV downloads, the star limit per run in the
Search tab, and the search corridor in the previews. Nothing to do after updating: an existing `hits_log.csv` and
`favorites/favorites.json` are imported into the database once.

### Added
- **Planets and moons as targets** (`pysyzygos/bodies.py`): `P:Mars`, `P:Jupiter`, ... `P:Neptune`, `P:Pluto` and
  moons such as `M:Io`, `M:Titan`, `M:Himalia`, `M:Triton`, `M:Charon` in the target list (the prefix keeps them
  apart from asteroid numbers; `python -m pysyzygos.bodies` lists them). Positions from JPL Horizons as a small SPICE
  kernel per search window (cached; the same ephemeris as NAIF's satellite kernels, reproduced to ~1 m), radii from
  the planet constants. Events get **disappearance and reappearance times** at the site (`d_utc`, `r_utc`, also as
  contacts in the database); verified: D and R put the star exactly one Jupiter radius from its centre in
  independent geometry. A star covered by a planet disappears, so planets have no drop limit; moons and Pluto
  follow the asteroid rules (drop limit). The light deflection leaves out the target's own planet.
- Satellite table `src/pysyzygos/data/satellites.json`: all 458 moons of Mars to Pluto known to JPL Horizons, with
  radius and brightness (H with the phase removed, H-G law with G 0.5; within ~0.2 mag of published values for the
  major moons, Phobos ~1 mag). 91 can be searched; a missing size or brightness is estimated as for asteroids
  (marked \*); the rest (mostly tiny, recently found moons of magnitude 22-25) have neither. Rebuilt with
  `python -m pysyzygos.bodies build`. Rough 3-sigma path uncertainty by size (15-200 km) for the sigma lines and
  the chance.
- GUI tab **Planets & Moons** (after Pick): per system the planet and its larger moons (radius 150 km or more) to
  tick, one box for its smaller moons; window, star G limit, the moons' minimum drop, Run. Results right in the
  tab as their own list (`bodies_log.csv`, list "bodies" in the database, apart from the asteroid search) with a
  report layout for major bodies: D, closest approach and R at the site, duration, star, sky, shadow distance,
  chance, tools. Previews show the planet and its moons as disks at their size, zoomed to the system, each moon
  marked with a small cyan **+** whatever its size. File and favorite names use `P-Jupiter` (no ':' for Windows).
- Optional offline ephemeris: `pysyzygos setup --planet-kernels` (also asked on a first-time setup) downloads NAIF's
  satellite kernels (Jupiter `jup365.bsp` 1.1 GB, Saturn `sat441.bsp`, Neptune `nep097.bsp`, Pluto `plu060.bsp`,
  Mars `mar099.bsp`), used instead of Horizons when they cover the search window.
- **Stellarium** button next to KStars in the Results and Favorites tables (`pysyzygos/stellarium.py`, any
  system): through Stellarium's Remote Control plugin (port 8090) it sets the event time with the clock stopped,
  the view on the star and the field, and with "KStars/Stellarium: set its location to the event site" the site.
  Shown whenever the GUI serves the report; a click tries and reports. Also `pysyzygos stellarium`.
- **CSV columns file** `csv_exports.py` in the data folder (`pysyzygos/exports.py`, template
  `templates/csv_exports.py`, created at the first download): which columns the CSV buttons of the Pick, Results,
  Planets & Moons and Favorites tabs export, in which order and with which headings. Default: exactly the table's
  columns and values as shown; any raw field of the event record (`"raw:star"`, ...), all of them (`"*"`) or a
  function can be added. UTF-8 with byte order mark for spreadsheets.
- GUI Search and Planets & Moons tabs: **Star G limit** for one run (as in the Pick tab; default from the site's
  telescope, capped at the selected catalog's limit). A search notes when `gaia_local_gmax` in your
  `pysyzygos_config.py` caps the limit below the catalog's (older configs have 13).
- Event preview: the **search corridor** (the strip searched for stars: Earth radius + body radius + reach, at the
  event distance) as dotted lines on both sides of the track, with its half-width in the legend.

### Changed
- **Results database** (`pysyzygos/db.py`): searches and favorites are stored in `pysyzygos.db` in the data folder
  (SQLite, part of Python): every run with its summary, every event, and the favorites. "Start a fresh hits_log.csv"
  became **Start a fresh results list**: a new list (series) begins, the older ones stay in the database instead of
  being deleted. `hits_log.csv` / `bodies_log.csv` and their `.runs.jsonl` are still written after each search, as
  plain-text copies of the current list with consistent columns (the reports and other tools read them). An
  existing `hits_log.csv` and `favorites/favorites.json` are imported once (the latter kept as
  `favorites.json.migrated`).
- The CSV buttons export the table as shown (see the columns file above) instead of the raw log with all columns;
  Results, Planets & Moons and Favorites are exported from the database. The full files stay: `hits_log.csv`,
  `bodies_log.csv`, `favorites/favorites.csv`.
- The KStars location checkbox of the Results tab is now "KStars/Stellarium: set its location to the event site".

### Fixed
- A minimum drop of 0 stopped the search with "math domain error" (now: no drop limit).
- A star limit set for a planet run was capped by `MAG_MIN` (G 13 with older configs), so faint stars were never
  searched; the separate planet star limit is gone, the run's Star G limit applies.
- The asteroid size lookup (SBDB) is no longer tried for planet and moon targets.

## [0.13.0] "New Horizons" - 2026-10-07

A standard Python package now (`pyproject.toml`, code in `src/pysyzygos/`, one `pysyzygos` command; install with
`pip install -e .` or run with `uv run pysyzygos`): **after updating, run `pip install -e .` once** in your virtual
environment, or use uv. New reference information with each event: close and double stars, known asteroid
satellites, earlier occultations; plus the camera list, the data folder setting and several fixes.

### Changed
- Default Gaia catalog G <= 16 (`gaia_dr3_g16`, 2.1 GB download, ~3 GB on disk; enough for most amateur
  telescopes): template `gaia_local_dir`/`gaia_local_gmax`, setup's limit question (Enter = 16) and the pick's
  default catalog. Before, the template capped the star limit at G 13 (`gaia_local_gmax = 13.0`). G 18 stays
  available (`pysyzygos setup --gmax 18`). Your own `pysyzygos_config.py` keeps its values.
- **Standard Python package** (PEP 517/518/621, src layout as PyMovie and PyOTE use): `pyproject.toml` replaces
  `requirements.txt`; the code moved from the project root into `src/pysyzygos/` with short module names
  (`pysyzygos_pick.py` -> `pysyzygos/pick.py`, `pysyzygos.py` -> `pysyzygos/search.py`, ...); imports are
  `from pysyzygos import ...`. One command, `pysyzygos`, starts everything: `pysyzygos` (web interface),
  `pysyzygos setup`, `pysyzygos pick ...`, `pysyzygos search`, `pysyzygos report hits_log.csv`, `pysyzygos owc-check`,
  `pysyzygos gaia ...`, `pysyzygos picks ...` (`pysyzygos --help`; options unchanged); also `python -m pysyzygos`.
  Your data stays where it is: the project folder is the data folder (`PYSYZYGOS_HOME` chooses another one).
  `pysyzygos_config.py` is now your own file there (not in git): it is created from
  `src/pysyzygos/templates/pysyzygos_config.py` when missing, and settings it lacks keep the template's default.
  `sites_example.py`, the logo and the globe's map data moved into the package. Checked: tests on Python 3.10 and
  3.14, a clean install with uv (Python 3.10), and pick (spawn workers), search, report, setup and the GUI run
  through the new command from another folder.
  **Upgrading an existing install:** `git pull`, then once `pip install -e .` in your virtual environment (or
  `.venv/bin/python -m pip install -e .`); start the GUI with `pysyzygos` (`.venv/bin/pysyzygos`) instead of
  `python pysyzygos_gui.py`. If you changed `pysyzygos_config.py`, keep a copy before pulling (git removes the tracked
  file; PySyzygos then recreates it from the template, so copy your changes back in).
- All download and web addresses moved into one file, `pysyzygos/urls.py`, each with its own name (`URL_NAIF_DE440`,
  `URL_JPL_HORIZONS_API`, `URL_MPC_OBSCODES`, ...), so they are maintained in one place. A separate file rather than
  `pysyzygos_config.py`, which reads `sites.py` when imported: setup and the report need addresses without it.
- GUI Site tab: the site list is now the Minor Planet Center's list of observatory codes (ObsCodes.html, ~2700
  observatories, downloaded once into `data/`, not in git; `pysyzygos.geo.mpc_observatories`), searchable by code or
  name. It replaces Occult's site list of 0.12.0, which turned out to hold mainly reference cities. Positions and
  heights come from the MPC parallax constants (WGS84); for old entries with fewer than 5 decimals the height is
  looked up instead.

- Documentation: README table of contents, how to type the commands (uv, pip, alias), where data and settings
  live (data folder, setting, cache, per system); ABOUT.md 3.5 memory and CPU use of the pick (per worker ~0.5 GB +
  ~55 MB per day of window; NumPy threads per worker), 4.1 what Horizons/SBDB hold vs the occultation archive,
  4.2 asteroid satellites; open items for close and double stars (Part 6).

### Added
- Experimental, off by default: **Check OWC** buttons in the GUI's Results and Favorites tabs (`owc_lookup = True` in
  `pysyzygos_config.py`; no GUI switch). They look the events up in OccultWatcher Cloud through the interface of its
  public event pages (`pysyzygos/owc.py`; one request per second, PySyzygos named as the client, only on click) and
  show the prediction feeds and signed-up stations under the asteroid, e.g. "OWC IBEROC · 2 stations", linked
  to the OWC event page (stations with distance and commitment on hover). Matched by the star's Gaia DR3 id, else
  by time; results cached in `owc_cache.json` in the data folder.
- Results and Favorites tables: a **Chance** column, the probability that the shadow covers your site, from the
  offset, the shadow radius and the 1-sigma path uncertainty (JPL Horizons' 3-sigma position uncertainty / 3, else
  `default_sigma3_km`), like Occult's "Rank" but for your site; sortable, details on hover. New hit-log columns
  `path_sigma1_km`, `sigma_source`, `p_site` (events logged before show "—").
- **Asteroid satellites** (`pysyzygos/binaries.py`, `data/binaries.json`: 325 systems from W. R. Johnston's Binary
  Minor Planets Compilation V3.0, NASA PDS 2019, doi:10.26033/bb68-pw96, plus satellites seen in occultations):
  "+moon" / "+2 moons" ("+moon?": only reported in an occultation) after the asteroid in the Results and Favorites
  tables with sizes, distances and periods on hover, a "Satellites" line in the favorites panel, and a dotted
  **satellite zone** on the event maps (KML, report map, globe plot): the primary's shadow plus the largest known
  moon distance and radius, where a moon's shadow can pass (its position is not predicted). ABOUT.md 4.2.
- Favorites: the close/double-star check also for favorites added before it (filled in once at GUI start from the
  local catalog), shown in the favorites table (⚠ after the drop) and as a "close or double star" line in the
  detail panel.
- **Close and double stars** (`pysyzygos/doubles.py`): each event checks the local catalog for neighbours within
  4" (`companion_radius_arcsec`) whose light stays in the camera image, and recomputes the drop with it
  (`mag_drop_blended`; the report shows e.g. "3.61 ⚠ 3.31" with details on hover when the drop is 0.1 mag or
  more smaller). Optional online check after a search (`gaia_online_check`, default on, GUI Search tab): one query to
  the Gaia DR3 archive for all events adds Gaia's double-star hints for the event star (`non_single_star`,
  `ipd_frac_multi_peak`, `duplicated_source`, `ruwe`) and neighbours the local catalog leaves out; skipped when
  offline. New hit-log columns at the end (`blend_*`, `mag_drop_blended`, `double_hint`, `double_check`, `gaia_*`).
  Still open (ABOUT.md Part 6): known-double catalogs, events on stars the catalog drops (RUWE >= 1.4), step events.
- **Earlier occultations** of an asteroid in the favorites panel, e.g. "Occultations (NASA PDS archive, to 2023-12):
  8 events 1991-2021 (1 reliable size, ...); shape-model diameter 107.8 +- 5.6 km (6 events); best profile
  2008-06-06: 119.1 x 101.7 km". From NASA PDS Small Bodies Node "Small Bodies Occultations" V4.0 (Herald, Dunham et
  al., doi:10.26033/ehqs-jp27): a compact extract ships with PySyzygos (`pysyzygos/occultations.py`,
  `data/occultations_pds.json`, 2903 asteroids, 387 kB). Reference only; the prediction's size source is unchanged.
  ABOUT.md 4.1 explains what Horizons/SBDB holds (no chords) and what the archive adds.
- GUI Site tab: **Sensor (cameras)** list next to the MPC observatory list: 21 sensors common in occultation work, one
  entry each as "Sony IMX174: 11.34 x 7.13 mm, 1936 x 1216 px of 5.86 um (ZWO ASI174MM / MC, QHY174M-GPS, ...,
  DVTI+CAM 174)", with the ZWO, QHY, ASTRID, DVTI+CAM, Seestar and Unistellar cameras built with them, plus analog
  video formats. Searchable by sensor or camera name (e.g. "174", "QHY600", "ASTRID"); picking one fills sensor width
  and height (computed from pixels x pixel size; `pysyzygos/cameras.py`). The Site
  form now has MagAdjust next to the focal length, and sensor width, height and detection frames in one row.
- **uv support** (as PyMovie and PyOTE): `uv run pysyzygos` in the PySyzygos folder installs Python 3.12
  (`.python-version`) and the exact package versions of `uv.lock` (Linux, macOS, Windows) into `.venv` by itself;
  then `uv run pysyzygos setup` and `uv run pysyzygos`. README: install steps for uv on each system (also from the
  GitHub ZIP, without git). The pip way still works.
- README: **Windows, step by step (with uv)**: installing uv, the ZIP (or git), a folder outside OneDrive, setup,
  start, an optional `PySyzygos.bat` start icon, updating and removing. Not yet tested on Windows.
- **Data folder setting** for installed copies (pip/uv without a clone): the first `pysyzygos setup` asks where to keep
  the data (Enter = `~/PySyzygos`) and saves the choice in the system's settings folder (Linux
  `~/.config/pysyzygos/home`, macOS `~/Library/Application Support/PySyzygos/home`, Windows `%APPDATA%\PySyzygos\home`);
  `pysyzygos setup --home <folder>` changes it (for a clone too; files are not moved, setup says if the old folder
  holds your data). A clone keeps using its own folder; `PYSYZYGOS_HOME` still sets it for one run. The folder in use
  and why: `pysyzygos setup --status`, the GUI's About box and start-up line.
- Pick: the asteroid's H in `pick_events.csv`, the saved picks and the Pick tab table (the "H below" limit is the
  most common reason an asteroid is missing from a pick).
- GUI Pick and Results tabs: a **CSV** button downloads the selected saved pick's events, or the search results
  (`hits_log.csv`, downloaded as `hits_<site>__<start>_<days>d.csv` from the last run, like the saved picks).
- GUI Pick tab: **Star G limit** (left of "H below"), the pick's star limit, computed from the site's telescope (as "Stars searched
  to G" in the Site tab) and capped at the selected catalog; it can be changed for one run (`--cam-limit`). Before,
  the GUI pick used the config's `MAG_MIN`, which `gaia_local_gmax` can cap lower than the site allows.
- GUI Site tab: **Add as new site** next to the MPC list: adds what the map and form show as a new site to the site
  selector and saves it at once (it is then selected for all runs).
- GUI Site tab: **Remove site** deletes the site selected at the top right from `sites.py` (asks first, saves at
  once; the last site cannot be removed; if it was the default for command-line runs, another site becomes it).
- Results, Favorites and Pick tables: an **\*** after the asteroid name marks a size estimated from H with an
  assumed albedo (no measured diameter; uncertain by a factor of about 1.7); hover text and a note below the table.
- Favorites detail panel: a **shape and rotation** line (axes from SBDB `extent`, rotation period, pole, taxonomic
  type) where SBDB has them. Favorites get SBDB's full per-object record once (`pysyzygos.sbdb.get_full`; the pick
  tool's bulk rows hold only size fields); older favorites when the GUI starts.
- Site key `mpc_code` (the official MPC observatory code), a **MPC code** field in the GUI Site tab (filled in when
  an MPC observatory is picked), shown in the report header and kept in the run summary.

### Fixed
- A minimum drop of 0 (no drop limit) stopped the search with a math error in the star limit; it now means "no cap".
- Web lookups with Python's standard library (OWC check, place/elevation/IP lookups and the MPC list, the full SBDB
  record for favorites, the pick's SBDB download) failed on Python installations without certificate authorities
  (often macOS: "CERTIFICATE_VERIFY_FAILED: unable to get local issuer certificate"), while the browser worked. They
  now use certifi's list (installed with requests) via `pysyzygos/net.py`. OWC check failures name the request and
  the error in the GUI log.
- Results and Favorites tables were wider than the page (the right side looked cut off; its scroll bar was only at
  the table's end): tool buttons and column headings may wrap, the asteroid name and offset too, tighter cell
  padding, the calculation-time column dropped (it stays in `hits_log.csv`), and on windows narrower than about
  1180 px the favorites' Note and Added columns are hidden (both are in the detail panel). Both tables fit a
  1280 px window.
- GUI: the Favorites table's height (drag the corner) was sometimes restored as a sliver after a restart: it was saved
  on every size change, including the box's minimum height while the tab was laid out. Now it is saved only after
  you drag, as a share of the window height, and restored only between 25 and 92 % of the window (else the
  default, 60 %). The Results report (default 75 %) and the Pick table (55 %; all rows in one scrollable box instead
  of pages of 15) got the same resizable box, each remembered separately in the browser.
- Favorites tab: the check boxes' mass actions (**Remove**, **Set status**, the "selected" count) did nothing since
  0.12.0: the times selector's script variable `sel` replaced the selection helper `sel()` of the same script
  (seen as "cannot remove a favorite"). Renamed; the favorites test now guards against it.
- README: the logo at the top pointed to its old place in the project root (moved into `src/pysyzygos/`).
- GUI Favorites tab: the **CSV** download was saved as "true.csv" (the link's `download` attribute); it is now a
  button like in the Pick and Results tabs and saves `favorites_<date>.csv`.
- Pick tool with a star limit above G 15 (now easy to reach with the GUI's **Star G limit** field): the deeper
  bright-star index it needs (`bright_G16.0.v2.npy`, ...) was built by every worker at once, each reading the whole
  catalog into memory, so the system ran into swap and the browser stalled. The pick now builds a missing index once,
  before starting workers, and the build is low-memory (three passes through a memory-mapped file; peak about one
  catalog file or block instead of the whole index). Same index as before (checked on G <= 15: identical).
- GUI: when the browser page was lost during a run (stalled, closed, reloaded), the GUI stopped reading the run's
  output, so the process blocked and every later run was refused as "already in progress". Output is now read to the
  end without the page (results still go to their files, e.g. `picks/`); the page reconnect timeout is 60 s.
- Setup with an unreachable or blocked address (offline, server down, proxy or firewall): instead of a traceback it
  stops with a message (the address, the proxy setting `https_proxy`, rerun to resume, the other catalog source,
  copying files from another computer). Kernel downloads use `curl -f` into a `.part` file (before, a proxy's error
  page or a broken download was saved as the kernel); a failed refresh of the Earth orientation file keeps the older
  copy. The ESA build detects a proxy page instead of the file listing, skips a file that fails after its retries
  (the rerun fetches it) and stops early when the first files all fail.
- Pick tool: events near sunrise or sunset (or near the altitude limit) could be lost. A candidate was kept only if
  the asteroid was visible at the sample of its Earth-centre time estimate, but the event at the site can be 10-40 min
  from it (e.g. 539175 on 2026-10-09: estimate 06:00 UT with the Sun at +4 deg at Test site 3, real event 05:26 UT with
  the Sun at -1.6 deg). A candidate is now kept if the asteroid is visible anywhere in its solver window, as in the
  search; the exact star and Sun altitude at the solved time are checked as before.
- GUI Site tab: after picking a second MPC observatory, the proposed site name kept the first one, so **Add site**
  stored e.g. Trieste's position under "000 Greenwich"; the name now follows each pick (a name you typed is kept).
  Adding a site no longer overwrote its description with the site name.
- `linux_install.sh`: ran `.venv/bin/activate` as a command (no effect), so `pip install` went to the system Python
  (refused as "externally-managed-environment" on Debian/Ubuntu) and setup and GUI ran without their packages. It now
  calls `.venv/bin/python` directly, finds `python3`, stops at the first error, hints at `python3-venv`, and can be
  rerun.

## [0.12.0] "New Horizons" - 2026-10-05

### Fixed
- Pick tool with several workers on Linux with Python 3.13 or older: workers were started with "fork" and inherited
  the parent's open SPICE kernel files, so parallel reads of `de440.bsp` collided (SPICE(RECORDNOTFOUND) "corrupted
  DAF", SPICE(INVALIDRADIUS)); seen with 14 workers on a 28-thread server. Workers now always start with "spawn" and
  open their own kernels (Python 3.14 and macOS were not affected). Reproduced with `--mp-start fork` and 12 workers,
  fixed with the default spawn. `--mp-start` (spawn, forkserver, fork) is kept for diagnosis.
- Results and Favorites tables: sorting by Asteroid is numeric by its number (20 before 100), not alphabetic.

### Added
- GUI Site tab: **Occult/OWC site list**, a searchable list of Occult's ~800 reference places and observatories
  (InstallSites.zip from occultations.org, downloaded once into `data/`, not in git; `pysyzygos_geo.occult_sites`).
  Picking one sets position, elevation and description and proposes it as a new site name (**Add site**).
- Favorites table: a **times** selector shows the event times in UT (default), in this computer's time zone
  (Local) or in each event site's time zone (Site, e.g. "2026-Oct-12 00:47:46 GMT+2 (Zurich)"), with daylight saving
  time; remembered in the browser, sorting unchanged. Site time zones are looked up once per site (Open-Meteo,
  `pysyzygos_geo.timezone`) when a favorite is added, and for older favorites when the GUI starts.

### Changed
- GUI: the start date of the Pick and Search windows defaults to today (UTC) instead of `ct` from
  `pysyzygos_config.py` (which stays the default for command-line runs).

## [0.11.1] "New Horizons" - 2026-10-05

First GitHub release with a Zenodo DOI: 10.5281/zenodo.23149372 (this release; all versions:
10.5281/zenodo.23149371). Tags `V0.11.1-NewHorizons` and `V0.1.11-NewHorizons` (same commit).

### Fixed
- Globe plot, color style: land masses mostly on the far side of the Earth could flood the visible disk with land
  colour (e.g. Africa/Eurasia when the view is centred on the Americas or the Pacific). Land is now drawn with an
  extended orthographic projection (the far side continues beyond the disk edge) clipped to the disk; a land mass
  containing the far-side point is detected by its orientation and filled as the outside of its outline. Checked on
  nine views around the globe and on the reported event (84851, 2026-10-18).

## [0.11.0] "New Horizons" - 2026-10-04

The code name: PySyzygos's orbits come from JPL Horizons, and the New Horizons mission measured its flyby target
Arrokoth beforehand with stellar occultations observed around the globe.

### Added
- Globe plot (`pysyzygos_globe.py`): an Occult-style event plot per event, `maps/<event>_globe.svg`. The whole Earth
  as seen from the star at the event time with the shadow path (centre line, shadow limits, 1- and 3-sigma limits,
  minute marks), the shadow axis off the Earth, the site, and a header with Occult's parameter set (star position as
  used and of date, durations, time per km and per mas, drop, Sun and Moon, 1-sigma error, asteroid size, parallax,
  hourly motion) plus a 2 deg star chart. Style `"color"` (sea, land, night side, like OWC's globe) or `"lines"`
  (black on white, like Occult). Config `write_globes`, `globe_style`. Checked against Occult's plot of 30819.
- `data/ne_110m_earth.json`: coastlines, borders and land from Natural Earth 1:110m (public domain).
- **Globe** button in the Results and Favorites tables, a Globe link in the favorites detail panel; favorites keep
  their own copy (and pick it up from `maps/` for older favorites).
- Links in the tables: the asteroid name to the JPL Small-Body Database, the star magnitude to its Gaia DR3 record
  in VizieR.
- GUI **About** box (header): logo, version and code name, author, purpose, credits, licence, GitHub link. Project
  facts (`__codename__`, `__author__`, `__copyright__`, `__license__`, `__url__`) in `pysyzygos_version.py`.
- `CHANGELOG.md` (this file).

### Changed
- Report and favorites keep the preview (`<event>.svg`) and the globe plot (`<event>_globe.svg`) strictly apart.

## [0.10.0] - 2026-10-04

### Added
- Astrometric corrections of the star direction (`pysyzygos_astrometry.py`), applied once per candidate in the
  search: stellar parallax (Gaia parallax) and the gravitational light deflection by the Sun, Jupiter and Saturn
  (as star minus asteroid). Switches `star_parallax`, `light_deflection` (config and GUI Search tab, both on by
  default; off reproduces the 0.9.0 results exactly). Log columns `corr_parallax_mas`, `corr_deflection_mas`; the
  report header shows which corrections were on. Against Occult's printed star positions the difference dropped
  from 4.52 to 0.90 mas (16556) and is 0.29 mas near opposition (30819). Paths move by up to ~10 km.
- `pysyzygos_owc_check.py --sea-level`: our side at elevation 0, as OWC online computes (it ignores the site
  height; up to ~0.9 km across the track at a 1000 m site).

### Fixed
- `pysyzygos_owc_check.py` silently skipped OWC events marked with the Sun's altitude (twilight events,
  "sun symbol -5 deg"); it now reads them and sets the Sun limit to match.

## [0.9.0] - 2026-10-04

First numbered version (`pysyzygos_version.py`; GUI header, run summary, report, picks, favorites and `--version`
show it). It collects the work since the first commit:

- 2026-09-28: the search script (`pysyzygos.py`): SPICE-based exact closest-approach solver in the fundamental
  plane, Gaia stars, hit log, asteroid name lookups.
- 2026-09-30: configuration file and observing window, Moon information, automatic refresh of the Earth orientation
  kernel, KML shadow paths, the HTML/Markdown report with an embedded map, the all-asteroid pick tool.
- 2026-10-01: the local Gaia DR3 catalog and the corridor search (fast, offline), observing sites in `sites.py`.
- 2026-10-02: run statistics, extinction, automatic site setup, `--gmax`, the NiceGUI web interface, the logo.
- 2026-10-03: the ready-made catalogs on Zenodo (doi:10.5281/zenodo.23113337) with setup asking for the limit and
  the source, saved picks per site and window, KStars pointing (Linux), the favorites list (status, notes, CSV,
  mass actions, map and preview copies), 1-sigma path lines, star-field previews with density dimming, Earth
  orientation coverage in the report header, progress output for long downloads, OWC reference comparisons.
- 2026-10-04: GPL-3.0-or-later licence, `CITATION.cff`, `CONTRIBUTING.md`, references and acknowledgements.

[1.3.2]: https://github.com/pyzahl/PySyzygos/compare/v1.3.0...main
[1.3.0]: https://github.com/pyzahl/PySyzygos/releases/tag/v1.3.0
[1.2.0]: https://github.com/pyzahl/PySyzygos/releases/tag/v1.2.01
[1.1.1]: https://github.com/pyzahl/PySyzygos/releases/tag/v1.1.1
[1.1.0]: https://github.com/pyzahl/PySyzygos/releases/tag/v1.1.0
[1.0.0]: https://github.com/pyzahl/PySyzygos/releases/tag/v1.0.0
[0.15.0]: https://github.com/pyzahl/PySyzygos/commits/main
[0.14.0]: https://github.com/pyzahl/PySyzygos/commits/main
[0.13.0]: https://github.com/pyzahl/PySyzygos/commits/main
[0.12.0]: https://github.com/pyzahl/PySyzygos/commits/main
[0.11.1]: https://github.com/pyzahl/PySyzygos/releases/tag/V0.11.1-NewHorizons
[0.11.0]: https://github.com/pyzahl/PySyzygos/commit/5abc5f6
[0.10.0]: https://github.com/pyzahl/PySyzygos/commit/0047057
[0.9.0]: https://github.com/pyzahl/PySyzygos/commit/a2d5c21
