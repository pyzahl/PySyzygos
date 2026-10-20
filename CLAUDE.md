# PySyzygos: project notes for Claude Code

Portable occultation predictor in Python. Finds asteroid occultations of Gaia stars for one observer site. Called
PyOccult up to 0.18.0; renamed PySyzygos in 1.0.0 (2026-10-14; Greek sýzygos "yoked together", root of syzygy: observer,
asteroid and star in one line; explained in README top, ABOUT.md intro, GUI About box, CITATION.cff). Never describe it
as a replacement, successor, port or derivative of Occult or OWC; they are only references for comparing results
(VERIFICATION.md, literature). GitHub: github.com/pyzahl/PySyzygos (old PyOccult address forwards). Not "PySyzygy":
rodluger/pysyzygy (transit code) owns that PyPI/import name. Read `ABOUT.md` for the computations and sources,
`README.md` for usage.
- Old names (transition, 1.0.0): `home.legacy_env` (PYOCCULT_* -> PYSYZYGOS_* via setdefault), `home.legacy_pointer`
  (old settings file copied once), `home.LEGACY_DEFAULT` (~/PyOccult kept if it exists), `home.legacy_files(HOME)`
  called by config.py (pyoccult_config.py -> pysyzygos_config.py with names replaced, original as .pre-1.0;
  pyoccult.db(+wal/shm) -> pysyzygos.db), cleanup lists the old names. tests/test_home.py. Remove after a while.

## Files
- Layout (since 2026-10-06): PEP 621 package, src layout like PyMovie/PyOTE. `pyproject.toml` (setuptools, version
  from `pysyzygos.version`, dependencies, entry point `pysyzygos = pysyzygos.__main__:main`); code in `src/pysyzygos/`
  (paths below are relative to `src/`); install `pip install -e .` (later: uv). Imports are `from pysyzygos import x`,
  never file paths. `pysyzygos/home.py`: `HOME` = data folder, first match: env `PYSYZYGOS_HOME`; the saved setting
  `home.POINTER` (Linux `~/.config/pysyzygos/home`, macOS `~/Library/Application Support/PySyzygos/home`, Windows
  `%APPDATA%\PySyzygos\home`; written by `pysyzygos setup --home <dir>` or setup's first-run question); the checkout
  root (pyproject.toml); else `~/PySyzygos` (`home.SOURCE` says which; stdlib only, no platformdirs). The dispatcher
  creates HOME except for `setup`, which chooses it first (`choose_home`, module level, before config). `PKG` (package dir: logo, `data/ne_110m_earth.json`, `templates/`). Every command
  chdirs to HOME, so data paths in the config stay relative (kernels, catalogs, sites.py, maps/, picks/, ...).
  `pysyzygos/__main__.py`: dispatcher `pysyzygos [command] ...` (no command = GUI; `COMMANDS` maps names to modules).
  It imports the module and calls `main()`, so functions sent to spawn workers (pick, gaia build) pickle as
  `pysyzygos.<module>.<fn>`; never run those modules via runpy as `__main__`. Exception: `search` (not import-safe)
  runs via `runpy.run_module(..., run_name="__main__")`. The GUI starts runs as `[sys.executable, "-u", "-m",
  "pysyzygos", <command>, ...]` with `PYSYZYGOS_HOME` and `PYTHONPATH` set. Tests put `src/` on sys.path.
- uv (2026-10-06): `uv run pysyzygos` in a clone (or unpacked ZIP) creates `.venv` with `.python-version` (3.12) and the
  pinned set of `uv.lock` (universal: Linux/macOS/Windows; 94 packages). After any change to `dependencies` run
  `uv lock` and commit `uv.lock`; `uv run --locked ...` fails if the lock is stale. Tested on Linux only so far.
- `pysyzygos/config.py`: loader. Runs `templates/pysyzygos_config.py` (defaults), then the user's `HOME/pysyzygos_config.py`
  (gitignored; copied from the template if missing) into this module's globals, so older user files get new keys.
  Puts HOME on sys.path (sites.py, targets.py) and templates/ (sites_example for old config copies).
- `pysyzygos/version.py`: the one place for `__version__` and `__codename__` ("Beyond Horizons" since 1.1.0, before "New Horizons"; changes at major
  milestones), `__author__`, `__copyright__`, `__license__`, `__url__` (GUI About box). Releases: GitHub tag `vX.Y.Z` (matching
  `__version__`) -> Zenodo DOI automatically; concept DOI 10.5281/zenodo.23149371 (README badge, CITATION.cff `doi`);
  v1.0.0 (first as PySyzygos) = 10.5281/zenodo.23381498; Zenodo followed the GitHub rename by itself.
  v1.1.0 = 10.5281/zenodo.23407110 (2026-10-16; the webhook timed out while Zenodo was down, archived later).
  v1.2.0 was released as tag `v1.2.01` (2026-10-16; tag v1.2.0 points one commit too early, at 1.1.1 code).
  GitHub releases (tag -> Zenodo DOI) only for 1.x.0 (user's rule, 2026-10-19: not too often); patch versions
  (1.3.2, ...) are only committed, users get them with git pull / the update. Every version increase gets a
  `CHANGELOG.md` entry (Keep a Changelog style, newest first) (semver; keep CITATION.cff `version` and the README line in step);
  every module imports it, tools have `--version`, GUI header, run summary/report, picks and favorites record it.
- `pysyzygos/search.py`: main search script. Kernel setup runs at import time (not import-safe). Driver is the `__main__` block.
- `sites.py` (private, not in git, in HOME; layout `pysyzygos/templates/sites_example.py`): named observing sites with view (min_alt, max_sun_alt,
  reach_km) and equipment (aperture_cm, frames, mag_adjust, extinction, ...); `pysyzygos_config.py` derives `LAT`, `LON`,
  `ELE`, `MIN_STAR_ALT`, `MAX_SUN_ALT`, `MAG_MIN`, `pick_*` from `default_site` or env `PYSYZYGOS_SITE`. Never put real coordinates in tracked files.
  Env `PYSYZYGOS_CATALOG=<folder>` overrides `gaia_local_dir` for one run (GUI header selector sets it).
- `pysyzygos_config.py` (user file in HOME, not in git; template `pysyzygos/templates/pysyzygos_config.py`): run config (targets, window, site, thresholds). Optional: `map_dir`, `min_mag_drop`, `search_mode` (`corridor`/`windows`), `corridor_step_s`,
  `gaia_local_dir` (required by corridor mode), `gaia_local_gmax`.
- `pysyzygos/paths.py`: shadow ground track (centre, limits, 3-sigma) as KML.
- `pysyzygos/report.py`: `hits_log.csv` (+ last run of `hits_log.runs.jsonl` for the header) to HTML/Markdown with an embedded Leaflet map. Standard library only.
- `pysyzygos/pick.py`: event finder over all asteroids (OWC-style) for a window; writes `pick_events.csv` and
  `targets.py`, and saves both per site + window in `picks/` (`pysyzygos/picks.py`; pysyzygos/search.py with
  `targets_source = "auto"` uses the newest saved pick of its site covering the search window; an explicit
  `targets` override sets `"list"`). Engine `pysyzygos/screen.py` (site solve, OWC observability formula), orbits `pysyzygos/orbits.py` (SBDB full-precision
  elements + planets, RK4, ~0.01" vs Horizons), stars `BrightIndex` (G <= index_gmax(cam_limit) = max(15, ceil(limit)), cells sorted by G; a missing one is
  built by `run_screen` in the parent before the workers start, low-memory via a memmap). Worker processes.
- `pysyzygos/prescreen.py` (0.16.0; FORMAT 3 since 2026-10-10: time grid +-PAD_S 12 h, candidates kept if
  tc +- half touches the window, `numbers` +- HALF_MAX_S; region test via shadowtrack.ground_track; FORMAT 1 builds
  missed ~21 % of a 500 km region's asteroids through 41-sample gaps and axis-only sky tests): pre-screens = per region/window the asteroids with possible events (build:
  pick.fetch_sbdb/build_rows, orbits.propagate, BrightIndex.near_path with Earth radius + r_max + reach, corridor
  find_candidates, then a vectorized ground track per candidate: shadow axis in the fundamental plane -> surface
  point (sphere), J2000->ITRF from pxform on the 10-min grid + spin OMEGA*dt, region box (+ r_max + reach margin,
  lon wrap), Sun and star altitude there). SQLite `prescreen/<name>.db`: events + meta (build limits). pick
  `--prescreen`: PS.check (window, region, limits as loose) else exit 2; rows filtered by PS.numbers(et0, et1).
  GUI Pick "Asteroids" select (prescreen_options: files covering window and site). A superset by design: same
  events as the full pick when it fits. Build memory (2026-10-10): `plan_chunks` from `mem_status()` (/proc/meminfo MemAvailable; else
  half of physical) x mem_frac or --max-mem, model `chunk_bytes` = n x steps x BYTES_PER_STEP (12x3x8, measured ~10)
  + CHUNK_FIXED; workers reduced if MIN_CHUNK does not fit; w+1 chunks in flight, halved when free < 2 chunks.
  find_candidates gets block_cells=SCAN_CELLS (4e6; the corridor default 2.5e7 made a ~730 MB transient for 30-day
  paths), ground tracks in CAND_BLOCK blocks (`_ground_track`; identical events). Checkpoint `<out>.partial` (events
  + `done` numbers + meta 'settings'; resumed only with equal settings, `--fresh` discards), finished -> meta,
  DROP done, VACUUM, os.replace. Worker RSS peak includes the memory-mapped bright index pages (reclaimable); the
  progress line also shows RssAnon after the chunk. SIGTERM (GUI Stop) is handled like Ctrl-C. Use: pick `--prescreen auto`
  -> PS.numbers(et0, et1, gmax=cam_limit) (pick never uses stars fainter than cam_limit: G 13.2 -> ~1/40 of the
  asteroids vs ~1/6 at G 16) -> `best_fit` (newest by meta 'built' among check()==[]; else full screen + reasons); `box_around_all` (CLI
  `--around-sites`, all sites.py sites, widest longitude gap outside; lon width at the poleward edge, so >= km
  everywhere; `box_around` (single site) uses cos(site lat): ~7 % narrower at the north edge for 500 km at 41 N,
  documented, change only between builds: resume compares the stored region); targets.py line "# asteroids screened:".
  GUI Pick tab: p_pre "auto"/"all"/path (PRE_FIXED), `pre_info` line, expansion "Pre-screens" (ps_start, ps_days,
  ps_where site/sites/global, ps_km, `run_prescreen`, ps_table with fit reasons, `delete_prescreens`);
  prescreen_options() mirrors PS.check without SPICE (`_day_et`: both windows start 00:00 UTC).
- `pysyzygos/shadowtrack.py` (2026-10-10): shadow elements per event (DTYPE 80 B: number, star, et=tc, g, m_ast,
  geo_miss, star dir sx/sy/sz f4, x0/y0/vx/vy/ax/ay f4 quadratic in dt=t-tc over +-half, half, r_km, err = misfit at 9
  points; measured <= 0.3 km), `fit`, `positions`, `ground_track` (shared by build and region test: N_TRACK 161
  samples, all tests widened by `_half_steps` and the sky by (r + reach)/R: strict superset vs 1281 samples),
  `region_mask`, `site_mask` (Site.at on a 1-min grid, segment distances between N_SAMPLES 81 samples, TOL_KM 10,
  TOL_DEG 1), `frames`, `in_box`. Global files: prescreen `<name>.global.npy` sorted by et + `.global.json` meta
  (kind global, n_events, n_asteroids); `PS.select` (searchsorted window +- half, g), `site_numbers`, `extract` ->
  region .db, `remove`, `is_global`; pick uses `site_numbers` for a global file; CLI `query`, `extract`, `index`.
  Reach is a PLANE distance: `ground_reach(sin_h, rho, sin_min)` = exact largest ground distance of an observer
  within rho (plane) of the axis point (|proj| = R cos h; chord^2 = rho^2 + R^2 dsin^2): 210 km -> 280 km at 50 deg,
  730 at 20, 1640 at 0; used for in_box margins and the sky tolerance in `_track` (FORMAT 3). Index
  `<name>.global.idx.npy` (IDX_DTYPE: lat_lo/hi, lon_w, lon_width, sin_lo/hi; `track_bounds` pads only gs + r;
  `near_site`/`hits_box` add `_reach_pad` = max ground_reach over the track's altitude range (not monotonic in h:
  33 points + 3 %) for the query's reach/min_alt, TOL margins; validated 2026-10-10: 0 dropped at all tested
  sites/limits, passes 14-26 % of events). Named regions `REGIONS` / `parse_region`.
  Shared (1.3.3): `publish` (release/world-prescreens/: <name>.tar.xz via tar + xz -T0 or tarfile, .sha256,
  prescreens.json with SHARE_KEYS settings, catalog_info (catalog.json of the folder or its .new/.old twin), archive,
  archive_bytes/_sha256, files [name, bytes, sha256], meta file last), `remote_list` / `fetch` (URL_PRESCREEN_MIRRORS
  = BNL box world-prescreens/ + env PYSYZYGOS_PRESCREEN_MIRROR, file:// for tests; GL._fetch_resume, only the
  listed members extracted and checked, nothing downloaded if intact). GUI Pick
  "Download shared" (`prescreen_shared`). tests/test_prescreen_share.py. Verified 2026-10-19: global__2026-10-01_40d_G16
  (1.57 GB tar.xz) from the BNL mirror on Linux (identical files) and macOS (interrupted download resumed; pick
  "auto" used it at a newly added site, then search).
- `pysyzygos/corridor.py`: per-asteroid path, magnitude cap and vectorized candidate scan; `corridor_candidates(plan, local)`
  takes the stars from `LocalGaia`. No archive access (removed 2026-10-01: archive too slow).
- `linux_install.sh` (user's quick install, Linux/macOS): creates `.venv` with python3, installs the project via
  `.venv/bin/python -m pip install -e .` (never `activate`: sh runs it in a subshell; system pip is refused by PEP 668),
  runs `.venv/bin/pysyzygos setup` then `exec`s `.venv/bin/pysyzygos`; `set -e`, rerunnable. Keep it in step with setup/GUI changes.
- `pysyzygos/setup.py`: one-time bootstrap (kernels via `pysyzygos/kernels.py`, local Gaia catalog, bright-star index);
  rerunnable, resumes. `pysyzygos/kernels.py`: the kernel download, also called by pysyzygos/search.py at start-up.
- `pysyzygos/starcat.py` (2026-10-16, catalog format 2, `pysyzygos catalog build|fetch|add|remove|status|xmatch|pack`):
  one catalog of ALL Gaia stars to G (supplement stars included, kind in `flags` bits 0-2, FLAG_DUP, FLAG_NSS), rows
  sorted by 0.25 deg cell (cell_of: dec band * 1440 + ra band) then G (u2 mmag), positions as u4 offsets in the cell
  (SCALE = 0.25/2^32 deg, 0.0002 mas; `encode`/`decode`). Files: catalog.json (format 2, build_id, groups; written
  last), offsets.npy, core.npy (CORE 31 B), hpm.npy (rows), optional quality.npy (QUALITY 20 B: ruwe, errors f2, corr
  i1 x127, nss, multi_peak) and extras.npy (EXTRAS 10 B: bp/rp mmag, rv, rv_error, teff), each with <group>.json
  (build_id, n_stars; `group_ok`). Part `xref` (2026-10-17, XREF 12 B: ucac4 = zone*1e6+number, tyc = (t1*20000+t2)*4+t3,
  hip; `ucac4_name`, `tyc_name`): `build_xref` = `match_ucac4` (+ `records=` -> `choose_pm`: epoch pm, see below; zone files via `_download`: a
  timer closes the connection after ZONE_DEADLINE_S 600 s, as a trickling CDS server once held a zone 20 h) (zones z001..z900 from URL_UCAC4_ZONES, UCAC4_REC 78 B
  little-endian, J2000 vs ours moved back 16 yr with Gaia pm, cKDTree, <= 1" and 1.5 mag, one Gaia star per UCAC4
  star) + `tyc_hip` (gaiadr3.tycho2tdsc_merge_best_neighbour / hipparcos2_best_neighbour by source_id range, async,
  split at the 50k cap; DR3/DR2 have no UCAC4 table, only gaiadr1). Epoch pm (1.3.2): UCAC4_REC full layout
  (sigra/sigdc mas +128, cepra/cepdc 0.01 yr - 1900, pm 0.1 mas/yr); `epoch_pm` = UCAC4 J2000 taken back to its central
  epoch with UCAC4's pm, then to Gaia 2016 (errors hypot(sig, Gaia pos err)/interval, >= EPOCH_MIN_YEARS);
  `choose_pm` replaces where max-axis error < stored (quality pmra/pmdec_error; kind 2 = inf) -> KIND_2P_EPOCH 5
  (KINDS_2P_PM, gaia_local PM_SOURCE); changes the CORE (repack). Record fields star_pmra/star_pmdec/star_pm_err/star_pm_source (end;
  `gaia_local.pm_source(kind)`), favorites `pm_text` row "Proper motion", report `star_flag_tip` names the source. CLI `catalog pm-epoch [--dry-run]` (xref numbers),
  `xref --no-pm-epoch`; catalog.json pm_epoch. Galbraith keeps UCAC5 (1.70 vs 2.32). merge skips groups whose fields are not in PART.
  add_group("xref") builds locally when no archive. `StarCatalog.names`, frame columns ucac4/tyc/hip; search record
  star_ucac4/star_tyc/star_hip (end); `report.star_label(r)` -> (name, other names) for report tips, favorites,
  globe, exports star_name; GUI `local_star_names` -> `favorites.backfill_names`. Build: ESA files -> parts/<stem>.npy (PART, resumable, build.json) -> `merge`
  (memmaps, low memory) -> `xmatch` (UCAC5/4 pm for kind 2, in place). `StarCatalog`: LocalGaia + BrightIndex methods
  (cone with quality/extras columns under Gaia's names, corridor_stars, near_path -> ROWS, high_pm, frame); supplement
  switch filters kind 0. gaia_local hands format-2 folders over (`LocalGaia.__new__`, `open_index`, `status`,
  `has_supplement`); old-format folders keep the old code. `doubles.star_flags` (shared with the online check) gives
  Gaia's flags + error ellipse locally when the cone has the columns. Zenodo: G 16 only (`ZENODO_STEM`,
  `<stem>_<group>.tar.xz`), other limits are local ESA builds. Upgrade: `staging_dir` (<d>.new) + `swap_in` (old ->
  <d>.old; cleanup lists it). Data versions (2026-10-19): `data_version(d)` (catalog.json data_version, else 2.1 if
  pm_epoch, else 2.0; old format "1"), DATA_LATEST {16: "2.1"}, DATA_TEXT, `update_available`, `update(d)` (fetch
  core + changed parts + xref into .new, copy UNCHANGED parts (extras: same build id), swap_in); setup
  `--update-catalog` (asked in a tty), GUI System tab `cat_update` button, header labels "(G <= 16, v2.1)". setup `catalog_step` (--groups, --upgrade-catalog), GUI System tab "Star catalog"
  (`cat_refresh`, `cat_part`, `cat_upgrade_ask` dialog -> `cat_upgrade` = setup --upgrade-catalog --groups P [--delete-old], then `catalog_options()` refreshes the header select; `cat_delete_old`; parts: untick -> dialog: `disable_group` (rename to `<part>.npy.off`, OFF) / `remove_group`; `enable_group`, `disabled_groups`, CLI `catalog off|on`). Planets offline: `bodies.kernels_status`, `remove_naif`, CLI `pysyzygos planets add|remove|status` (bodies.main), GUI `planets_refresh` / `planet_kernel`. tests/test_starcat.py.
- `pysyzygos/gaia_local.py`: (old format, before 1.3.0) builds/reads a local G-limited Gaia DR3 copy from ESA's CDN bulk files (`build`, `status`);
  one `.npy` per source file plus `.cells.npy` (1x1 deg cell index) and `.hpm.npy` (pm > 1500 mas/yr). No healpy.
  Ready-made copies (G <= 16, 18; no bright index) on Zenodo, concept DOI 10.5281/zenodo.23113337 (first version
  ...338, packed by `release/pack.sh`, untracked): `fetch_zenodo` (resumable, SHA-256, unpacks into any folder name);
  setup `--source auto|zenodo|esa` (auto: ask, Enter = zenodo; resumes a partial ESA build; esa for other limits).
- Supplement (2026-10-10): `gaia_local` `build(..., supplement=True)` / `pysyzygos gaia supplement --dir D --gmax 16`
  -> `D/supplement/` (catalog.json kind "supplement"; SUPP_DTYPE = DTYPE + ruwe, ra_error, dec_error, kind 1 RUWE /
  2 two-parameter, missing pm/parallax stored 0). `LocalGaia(dir, supplement=None)` merges it (columns star_kind, ruwe
  always present), `open_index` -> `MergedIndex` (COMMON_DTYPE) for pick/prescreen workers; `use_supplement()`: env
  PYSYZYGOS_SUPPLEMENT (GUI header checkbox, every run via run_process) else config gaia_supplement. Records/pick events:
  star_kind, star_ruwe, star_flag (end of record); report `star_mark` (⚑, keep exports.event_shown/pick_shown in step);
  prescreen meta/settings `supplement`, check() refuses a pre-screen without it when the pick uses it. Exec-excerpt
  tests need `gaia_local` in their ns (test_patch). Built 2026-10-10: 8.0 M stars G <= 16, 0.42 GB, 106 min.
  setup.py `supplement_step` (step 3b): `--supplement` builds/resumes, asked on a first-time setup (tty), status line.
  2-parameter pm (2026-10-12): `supplement_pm` (CDS XMatch, URL_CDS_XMATCH): UCAC5 (RAgaia/DEgaia 2015 within
  0.2", |Gmag-g| <= 0.5) then UCAC4 (J2000 + pm to 2016 within 0.5"); kinds 3/4 (PM_SOURCE), SUPP_DTYPE + pm_error,
  .hpm.npy rewritten too (`_as_dtype`; lookups join parts in one layout); catalog.json `pm_xmatch`; setup
  `supplement_pm_step` (3c). `star_sigma_mas` -> search: star_sigma_km combined into path sigma (lines, p_site,
  star_err_* ellipse); report `star_uncertain` red badge when > r_km. Pre-screens built before this used pm 0 for
  2-parameter stars: rebuild. The Zenodo supplement (version 2) has no pm yet: setup adds it locally.
  Catalog record version 2.1 (published 2026-10-19, doi 10.5281/zenodo.23428079, 14 files: the four
  gaia_dr3_g16_v2_* parts of data version 2.1, checked against ARCHIVE_SHA256, + the version-2 old-format archives
  for PySyzygos < 1.3.0, which reads the newest version). Before:
  On Zenodo since 2026-10-11 (catalog record version 2, doi 10.5281/zenodo.23298192; concept DOI unchanged):
  `gaia_dr3_g18_supplement_g16.tar.xz` (+ .sha256), `ZENODO_SUPPLEMENT`, `fetch_zenodo(dir, 16, supplement=True)`
  unpacks into dir/supplement (works for any catalog folder); setup/`gaia supplement` default to Zenodo, `--source esa`
  builds. Download verified identical to the local build. release/pack.sh packs it separately (`pack.sh supplement`)
  and excludes <catalog>/supplement from the catalog archives.
- `pysyzygos/sbdb.py`: shared per-asteroid SBDB cache (raw diameter/extent/H/G/albedo/name, not derived sizes). Filled by
  `pysyzygos.search.sbdb_phys()` (per-object API) and by `pysyzygos/pick.py` for its top targets (bulk rows: size fields only); `get_full()` fetches the per-object
  record (rotation, pole, extent, type) for favorites; standard library only.
- `pysyzygos/gui.py`: NiceGUI web interface (127.0.0.1 only); runs scripts as subprocesses via `pysyzygos/runner.py`
  (JSON config overrides per run). `pysyzygos/geo.py`: IP/place/elevation lookups (setup + GUI). `pysyzygos/preview.py`:
  event preview SVG per hit (`maps/<target>_<stamp>.svg`), shown by the report's Preview button.
- `pysyzygos/bodies.py` (2026-10-08): planets/moons as targets, prefix + name (`P:Jupiter`, `M:Io`; `L:Moon` later),
  REGISTRY (NAIF id, centre = system barycentre, kind, V(1,0), phase coeff, rough sigma3), GROUPS ("jupiter").
  `ensure_kernel`: Horizons VECTORS (CENTER 500@<bary>, 20 min, ICRF) -> SPK type 13 via `spkw13` in cache_path
  (~1 m vs Horizons; Horizons = jup365 ephemeris, so no 1 GB NAIF download), furnsh + `boddef(alias)` so all SPICE
  calls take "M:IO". search.py: corridor loop branch (no SBDB/Horizons SPK; size from PCK radii; planets H=None ->
  no drop cap, star limit = MAG_MIN like asteroids (GUI "Star G limit" override; no separate planet limit); moons H from satellites.json, G=MOON_G), deflection without own system
  (`bodies.deflectors`), sigma from REGISTRY, `contact_times` D/R (brentq on |offset|=r; logged d_utc/r_utc,
  duration_s; db contacts), record `kind`. Windows mode skips bodies. Verified 2026-10-08: Jupiter events, D/R at
  exactly the radius by independent topocentric geometry (0.1 km). Report: name + kind badge (no SBDB link).
  Stage 3: results lists in db (`results_list` "main"/"bodies", series per list via meta 'series:<list>', numbers
  unique); GUI tab "Planets & Moons" runs search with results_list=bodies, hits_output_cvs_file=bodies_log.csv,
  report `--layout bodies` (`html_row_body`: D/closest/R); favorites ★ finds events in the db (any list,
  `db.find_event_run`). File/folder names: `report.file_id` (P:Jupiter -> P-Jupiter). Preview: `disks=` (system
  bodies at angular size) and `field_arcmin` zoom. Optional NAIF kernel (`NAIF_KERNELS`, `naif_kernel`,
  `download_naif`; setup `--planet-kernels`): used if it covers the window (spkcov), else Horizons.
  All systems (2026-10-08): REGISTRY = PLANETS (Mars..Neptune kind planet, Pluto kind dwarf = H rule) + moons from
  `data/satellites.json` (`python -m pysyzygos.bodies build`: Horizons 'MB' list + one OBSERVER query per moon,
  APmag/Ang-diam/r/delta; `phase_correct` with H-G G=MOON_G=0.5 via SPICE phase angle; `fill_estimates`
  radius<->H with albedo, flagged -> D_est/'*'). 458 moons, 91 usable. GROUPS per system (planet + usable moons by
  size), `featured()` = planet + radius >= 150 km vs smaller. `LOADED` = targets with kernels (previews).
  Brightness vs literature: ~0.2 mag (Phobos ~1 mag). Saturn rings not modelled.
- `pysyzygos/db.py` (2026-10-08): results database `<data folder>/pysyzygos.db` (config `results_db`; sqlite3, WAL,
  30 s busy timeout: GUI and run processes share it). Tables runs (summary JSON), events (kind, target, best_utc,
  record JSON; `series`), contacts (D/R, C1-C4 later), favorites (entry JSON), meta (schema, current series). A
  series = what hits_log.csv was: GUI "Start a fresh results list" / config `results_new_series` starts a new one.
  search.py: `db.start_run` at start (after a one-time `import_log` of an old hits_log.csv + runs.jsonl),
  `db.add_event` per hit, `db.finish_run` + `db.export` in run_summary: hits_log.csv and hits_log.runs.jsonl are
  EXPORTS of the current series (report, CSV button, OWC check and favorites read them). favorites.py load/_save use
  the db next to the favorites folder (favorites.json imported once -> .migrated). owc_check uses owc_check.db.
- `pysyzygos/doubles.py`: close/double stars per event. Local: `companions()` from `LOCAL.cone` (radius
  `companion_radius_arcsec`, <= 5 mag fainter, proper motion to the event date), `blended_drop`, `fields()` (blend_*,
  mag_drop_blended, double_hint only if the drop changes >= 0.1 mag or Gaia flags). Online (`gaia_online_check`):
  `search.online_double_check` after pass 2: one async ADQL job (OR of circles, daemon thread, 120 s timeout) ->
  `online_fields` -> `db.update_events` (this run's events in the results database).
  New record fields go at the END of the hit record (the log is appended; mixed headers otherwise).
- `pysyzygos/owc.py` (experimental, hidden: config `owc_lookup = False`, only by editing the config; the user is
  introducing it to IOTA people step by step, so keep it low-key): OccultWatcher Cloud lookup through the public
  event pages' interface `URL_OWC_API` (`events/?astNo=&dt=&bf=` then `event/<id>`; no login; `my-events` needs
  login: not used). Match by Gaia id (`gaia.id`) else time (10 min); 1 s pause, User-Agent PySyzygos; on click only
  (GUI "Check OWC" in Results/Favorites, `run.io_bound`); cache `<data folder>/owc_cache.json`; report `owc_line()`
  under the asteroid (tags, station count, hover: observer, signed distance km, commitment).
- `pysyzygos/binaries.py`: known asteroid satellites, `data/binaries.json` from Johnston's PDS compilation V3.0
  (fixed-width `binarytable.tab`, layout read from its PDS4 label) + SAT_* columns of the occultations archive's
  `Asteroid_*.psv` (separation in mas). `short()` "+moon"/"+moon?" (report label, Markdown), `text()` (favorites
  panel, hover), `zone_km()` = max(a + d2/2) -> `shadow_path(sat_km=)` adds 'satellite_plus/minus' -> KML
  "Satellite zone A/B", report LINE_STYLES, globe LINES. Reference only; moon positions not predicted.
- `geo.parse_coords(text, field)` (2026-10-10): pasted site coordinates (labels incl. German, DMS / decimal minutes /
  decimal, N/S/E/W, m/ft/km; unlabeled: hemisphere letters, else lat, lon, ele; lat > 90 with lon <= 90 swapped;
  lon > 180 -> -360). GUI Site tab: number fields drop text, so a `paste` js_handler (PASTE_JS) emits non-numeric
  clipboard text to `on_paste` (fills lat/lon/ele, moves marker, looks up elevation). Verified in headless Chrome
  over CDP (scratch script; no Playwright installed). `tests/test_geo_parse.py`.
- `pysyzygos/geoid.py` (2026-10-16): EGM96 geoid height N (data/egm96_30min.npy, 0.5 deg, int16 cm, bilinear; build
  from GeographicLib's egm96-15.pgm, URL_EGM96_GEOID). sites.py `ele` is above MSL; `geoid_m` (filled by `fill` when
  saved: GUI via `sitesfile.save_sites`, `setup --geoid`, new sites in setup) is added by config.py AFTER both config
  files (ELE = ele + geoid_m, also when the user file sets ELE = site["ele"]); `ele_ref: "ellipsoid"` (MPC codes,
  GUI select) -> geoid_m 0. Run summary site: ele (MSL, for KStars/Stellarium), geoid_m, ele_wgs84, ele_ref.
  `pysyzygos/sitesfile.py`: load_sites/save_sites (moved from gui.py). tests/test_geoid.py.
- `pysyzygos/pathcheck.py` (2026-10-16, `pysyzygos path-check run|export|compare|keep <fav key>`): favorites/<key>/
  pathcheck/: `run` = search subprocess for that event only (ct = event - 1 h, 2 h, relaxed limits, debug_save_paths,
  map_dir/results_db/hits in pathcheck/run), path.npz of the favorite's star, the target's SPK files copied (a later
  compare uses the same orbit), meta.json (version, SBDB orbit id, run_utc). `compare`: parse_listing (Occult layout,
  sign apart), parse_header (JPL#, RA/Dec, Dia), shadow_path at Occult's times, plane offsets via spkcpo per point,
  fit_plane (const; + rotation), markdown -> compare_<UTC stamp>.md/.csv. Input tolerant (2026-10-17): `_table_rows` (header names: `_find_cols` lon/lat/time/
  alt, centre preferred, limits/sun avoided; `angle`, `ut_time` per field) else `_occult_row` (9 numbers required:
  lon/lat d m s + UT; alt/az/sun and limits optional); compare computes a missing star_alt (SPICE), date or nearest
  day to best_utc, w_occ NaN without limits. Old and new parser identical on the Phaethon/Galbraith listings. `export`: shadow_path at 1.45 s in Occult's
  layout (fmt_dms/fmt_ut). `steps`: star catalog -> each correction (amounts) -> direction used (checked against the
  search's), asteroid geo/bary/lt/own deflection, Besselian elements (ICRF axes and of date via erfa.pnm06a/gst06a,
  d, mu) at touch-down/centre/leaving (bisection on the centre line, minimize for the centre), geodetic points ->
  steps_<stamp>.md/.json. `run` deletes the target's cached SPKs first (search reuses same-name cache files up to orbit_max_age_days)
  and keeps only the newly downloaded. GUI: Favorites checkbox `pc_chk` (gui_state path_check), block `f_pc`, dialog,
  expansion `f_pc_steps`. Bodies: not yet.
- `pysyzygos/starrv.py` (2026-10-16): Gaia DR3 radial velocities of fast nearby stars (data/gaia_dr3_rv_fast.npy,
  164,602 stars with pm x |rv| x parallax > 24445: > 0.01 mas within 20 yr), `rv_for(ids)` (0 if unknown) ->
  `corridor.propagate_exact(df, utc, pm_bias, rv)` SkyCoord radial_velocity (perspective acceleration; Barnard 75 mas
  by 2026); config `star_rv`; windows mode takes the archive's radial_velocity. Archive anonymous async jobs cap at
  50000 rows (Gaia.ROW_LIMIT does not lift it): split queries by source_id ranges. Checked: equal to the archive's
  EPOCH_PROP_POS to <= 0.002 mas without, <= 0.025 mas with radial velocity.
- `pysyzygos/offline.py` (2026-10-16, `pysyzygos offline`, GUI tab System): copies in HOME/offline/ when the marker
  offline/enabled exists: sbdb_list.json.gz (pick.fetch_sbdb keep_sbdb after download; on OSError -> sbdb_fallback
  or the stale cache, warning), orbits/*.bsp (search.fetch_target_orbit keep_spk; on RequestException ->
  spk_fallback covering the window), sbdb_phys.json (sbdb.put copies it; search.sbdb_phys -> phys_fallback: copy,
  else the list's row via entry_from_bulk). cleanup removes offline/ only with --all. tests/test_offline.py. Tests that
  download (test_pick, test_sizecache) call `offline.use_dir(tmp)`: the copies are relative to the working folder
  and tests run in the data folder. `pysyzygos/sysinfo.py`: `pysyzygos info [--json]`, the System tab's "Data in use"
  (run as a process: SPICE for the kernels' coverage).
- `pysyzygos/horizon.py` (2026-10-17): OccultWatcher's [User Horizon] format (`parse` -> {station: [(az, alt)]},
  `check` rules, `altitude` (linear, vertical steps: higher side), `assess` -> behind / near (margin, any direction,
  line sampled every 0.5 deg), `svg`, `to_text`). sites.py keys horizon, horizon_name, horizon_margin (15),
  horizon_filter (False). search.handle_star after star_az: record horizon_flag/_alt/_sep_deg (end); filter returns
  False. report `horizon_text`/`horizon_mark` (⛰ yellow behind, red near) in `alt_cell`; exports altitude text.
  GUI Site tab expansion (hz_upload: for the form's site, station named like it else the first; hz_set marks
  unsaved; collect/show_site). parse strips a byte-order mark (OW/Windows files have one). tests/test_horizon.py uses OW's own
  example stations (never the user's real file: it names the site).
- `pysyzygos/panorama.py` (2026-10-17): the site's 360-degree photo (equirectangular 2:1; col = az_left + 360 x/W,
  row = 90 - 180 y/H). `profile` (alpha >= OPAQUE = ground; first row with ~0.3 deg ground below: wires ignored; max
  per STEP_DEG 0.25 bin), `points` (whole degrees, ceil of the per-degree max, Douglas-Peucker 1 deg), `fit_az_left`
  (min scatter of differences around their median: constant offsets do not shift it; ~1 deg with whole-degree
  points), `save` -> horizons/<slug>.jpg (1440x720, sky SKY_FILL) + .json (profile, source), `svg` (north left, two
  image copies for the wrap, grid, horizon + dashed margin, star ring). sites.py keys horizon_image (relative),
  horizon_image_az. GUI: Site tab (pano_upload fits az if points exist, hz_az, hz_fit, hz_from, hz_dl, hz_draw),
  favorites `fav_pano` (site by lat/lon in sites.py; star_alt/star_az, else report.alt_az) -> f_pano. Dependency
  Pillow (uv.lock). horizons/ gitignored, in cleanup SETTINGS. tests/test_panorama.py (synthetic photo). First use:
  Seewis observatory (GoPro MAX, transparent-sky PNG): left edge 195.8 deg, 1.2 deg median vs its UserHorizon.
- GUI job slots (2026-10-19): `Job.proc` = the main job (search, pick, pre-screen, setup, report, catalog: one at a
  time, blocking each other), `Job.fav` = the Favorites tab's path-verification tasks (run, export, compare, steps,
  keep), independent of the main job; `run_process(..., slot="fav")`, `stop_process(log, slot)`. The Favorites tab
  has its own log card (`fav_log`, Clear/Stop) and hides the main log card (tabs.on_value_change). Safe in
  parallel: own processes/SPICE, path-check output in favorites/<key>/pathcheck/run with its own db; it deletes only
  that asteroid's cached SPKs (picks/pre-screens do not use them; a main search of the same asteroid at that moment
  would download it again). `_stop_job` (quit/restart) stops both.
- GUI header power button: `quit_dialog` -> `restart_app` (os.execv `python -m pysyzygos gui --port P --no-browser`,
  GUI_ARGS) / `quit_app` (app.shutdown); `_stop_job` first. Report: `alt_cell` + AZ_SWITCH/AZ_JS (checkbox in the
  Altitude header, its clicks do not sort; localStorage az_deg); `sigma_text`, chance column "33 % · 0.6σ", `chance_bar_svg` (favorites panel f_bar).
- `pysyzygos/pmcheck.py` (2026-10-19): per event on a 2-parameter star (kind >= 2, config pm_alternatives): VizieR
  ASU UCAC5 (I/340/ucac5: RAgaia/DEgaia within 1", G 0.5) + UCAC4 (I/322A/out: J2000 + own pm to 2016 within 1",
  mag 1.5; EpRA/EpDE, e_RAJ2000/e_DEJ2000 = position errors at the central epoch) -> `estimates` (UCAC5, UCAC4,
  epoch via starcat.epoch_pm on a built UCAC4_REC, J2000->Gaia "as Occult"; east/north mas offsets at the event vs
  the pm used), `spread_mas` (RMS) -> s_mas = max(quoted, spread) in search; `shifted_dir` -> extra shadow_path per
  alternative, paths["pm_alts"] [(label, centre pts)] -> KML "Proper motion <label>" (report LINE_STYLES pink),
  save_path_debug pm_1.. + pm_labels; record star_pm_alts (summary), star_pm_spread_mas/_km (end). Report amber tier
  `star_noted` (0.5 r < s <= r, span.swarn2), tooltip lists estimates; favorites `alts_text`. Galbraith: "as Occult"
  line on Occult's centre to 0.19 km. tests/test_pmcheck.py (stand-in TSV of Galbraith's rows).
- `pysyzygos/steps.py` (1.3.3): `Steps(tool)`: add / step (context) / wrap (timed function: time and calls add up),
  group = parent step (listed under it), placeholders fix the order, "other" = total since PYSYZYGOS_T0 minus the
  top-level steps; `emit` prints a table and the line `PYSYZYGOS-STEPS {json}` (`parse`). Used by pick
  (`print_timing` from T + counts N), search (`STEPS`, `wrap_steps()` in the corridor driver replaces the step
  functions by timed versions: P1/P2 parts, 'hit:' per-hit work; `run_summary` adds passes, maps, results, emits),
  prescreen build. GUI `run_process`: `open_run_log` -> logs/<stamp>_<cmd>.log (LOG_KEEP_DAYS 30; cleanup OUTPUTS,
  .gitignore), the summary line goes to HOOKS["steps"] = `show_steps` (table under the log, not the raw JSON).
  tests/test_steps.py. First numbers (2026-10-19, 8 targets x 10 d): path uncertainty from Horizons 0.5 s per hit
  uncached, maps 0.3 s per hit, exact solve ~5 ms.
- `pysyzygos/cameras.py`: `SENSORS` (sensor, px w, px h, pixel um, camera names) for the Site tab's "Sensor (cameras)"
  list; sizes = pixels x pixel size (`sensor_mm`); one entry per sensor, cameras searchable in the label.
- `pysyzygos/occultations.py`: earlier occultations from NASA PDS "Small Bodies Occultations" V4.0 (doi
  10.26033/ehqs-jp27): compact extract `data/occultations_pds.json` (per numbered asteroid: events, years, quality
  counts, best profile of codes >= 2 with measured size, shape-model diameter; no chords/observers), rebuilt with
  `python -m pysyzygos.occultations build <zip>`. Reference line in the favorites panel only; not a size source yet.
- `pysyzygos/occultdata.py` (1.3.3, optional add-on, `pysyzygos occult-data status|add|remove|update|import|show`, GUI
  System tab "Occult data"): D. Herald's Occult data from IOTA, URL_OCCULT_DATA + <File>.zip (case-sensitive; HEAD
  Last-Modified = server date in occult_data/datasets.json; only the expected member names are extracted). DATASETS:
  diameters (AsteroidDiameters.bin: int16 dia x10 for 1..n, n = size/3, then u1 unc x5 at byte 2n; negative = from
  H; the help page's offsets are the old layout), diameters_all (9-byte records num i4, dia i2, unc u1 x2.5, source,
  albedo x500; the Indiv file swaps the last two), magnitudes (HGsHG1G2_Magnitudes.csv by column position, HV =
  Hg - 0.03 - 0.42 (Hg - Hr)), binaries (CSV with orbits), observations (Asteroid~Observations.xml -> observations.json
  in occultations.py's schema; occultations.load prefers it over the PDS extract), gaia_doubles (Gaia_Doubles.csv +
  gaia_doubles.idx.npy by RA, `gaia_doubles_near`, `star_text` 3"). `import_folder` copies from an Occult "Resource
  Files" folder (server date unknown -> listed by check_updates). Favorites panel `f_ocd` (summary + star_text),
  sysinfo `occult_data`, cleanup DOWNLOADS. Reference only; not used by the predictions yet. Redistribution not
  agreed: never ship these files in data/. tests/test_occultdata.py.
- `pysyzygos/globe.py` (0.11.0): whole-Earth view (globe) `maps/<stem>_globe.svg` (written by
  `pysyzygos.write_globe` after the KML; `write_globes`, `globe_style` "color"/"lines"); `globe_data(spice, ...)` +
  pure `render_svg(d)`. Data `data/ne_110m_earth.json` (Natural Earth 110m coast/borders/land, public domain).
  A4 page (1.3.2, `globe_page` "A4" | "square"; PAGES, W x 1448, width/height in mm): `system_data(spice, et, target,
  star_dir)` (bodies in the star-Sun plane, deflection curve y(x) = x (d_star - d(x)) via astrometry.deflect) ->
  `_panel_true_scale` (AU, equal scale), `_panel_light` (x AU, y mas at the target's distance; Sun and, from
  DEFL_SHOWN_MAS, Jupiter/Saturn as edge markers with a broken distance line) (pure; `_Box`, `_frame` axes,
  `_ticks` 1/2/2.5/5 x 10^n, FS/LW sizes, `_Labels` placer with padding and leader lines, `_corner_note`). Report "Globe" button (prevbtn with data-wide); favorites copy it as files["globe"] (+ `backfill_globes` from maps/
  at GUI start). Preview lookups exclude `*_globe.svg`.
- Debug `debug_save_paths` (2026-10-11, default False): search.py `save_path_debug` after `shadow_path` writes
  `<map_dir>/<stem>_path.npz` (np.savez, no pickle): one (n,4) array per path line [et, lon, lat, dur(NaN)], `line_names`,
  `columns`, and the event (target_id/name, star, star_ra/dec/dir, mag, best_utc/et, r_km, sigma3_km,
  min_distance_km, site, version, ellipsoid "WGS84 …", height_m 0). Not in globe.py (its `_land_path` draws coastlines, not the shadow path).
- MPC observatories: `pysyzygos.geo.mpc_observatories()` downloads https://minorplanetcenter.net/iau/lists/ObsCodes.html
  once to `data/ObsCodes.html` (gitignored) and parses the fixed columns (code [0:3], east lon [4:13], rho cos phi'
  [13:21], rho sin phi' [21:30], name [30:]); `mpc_geodetic` turns the parallax constants into WGS84 lat/lon/height
  (ele_ok False below 5 decimals: look the height up). GUI Site tab select (code + name only, so a code search does
  not match coordinates) and the `mpc_code` site key (report header, run summary). Replaced Occult's InstallSites.zip
  (0.12.0: mainly cities) and astropy's EarthLocation registry (no MPC codes).
- `pysyzygos/kstars.py`: KStars D-Bus control (Linux only, `gdbus` with `--` before args, else `dbus-send`; never raises).
  setGPSLocation(site) -> setLocalTime (KStars local time: re-read `tz` from location(), it follows DST of the shown
  date) -> setRaDecJ2000 (RA in hours) -> setTracking -> setApproxFOV. `set_location` (GUI Results checkbox,
  `KSTARS_OPT`): move KStars to the site (message names the old place) or keep it (warn if > 50 km). KStars ignores
  the tz passed to setGPSLocation and picks its own (a US Eastern-time site got -6): label only, UT is right. GUI routes `/api/kstars/status|show`; the report's
  hidden `.ksbtn` buttons appear only if the status call succeeds (not from file://). Verified with KStars 3.6.2.
- `pysyzygos/exports.py` (2026-10-08): GUI CSV downloads. Columns from `csv_exports.py` in HOME (template
  `templates/csv_exports.py`, copied at first use; user EXPORTS dict per table over the template's): lists of
  (heading, source), source = shown name | "raw:<field>" | "*" | f(shown, raw). Shown values = the tables' text
  (`event_shown` from report.build_event + report fmt helpers; `pick_shown` is also what the GUI Pick table uses,
  so they cannot drift). results_rows reads db.events(lst) of the current series (raw values via db._cell, as the
  CSV export) with report dedupe + mag sort; favorite_rows from favorites.load(). Written to
  cache_path/pysyzygos_exports, utf-8-sig. Keep event_shown in step with report.html_row / html_row_body.
- `pysyzygos/stellarium.py` (2026-10-08): Stellarium Remote Control plugin (`URL_STELLARIUM_API`, port 8090, HTTP POST
  form fields via `net.urlopen`): location/setlocationfields (if KSTARS_OPT set_location) + stelproperty/set StelCore.currentTimeZone = the
  site's IANA zone (GUI `site_timezone`: favorites' site tz, else geo.timezone, cached; verified live) -> main/time (time = JD
  UT, timerate=0) -> main/view (j2000=[x,y,z]) -> main/fov. Never raises. GUI route `/api/stellarium/show`; report
  `.stbtn` shown whenever served over http (no status check: blind try, toast). Verified with a running Stellarium.
- `pysyzygos/favorites.py`: favorites in `favorites/` (private, gitignored): `favorites.json` (entry = hits_log record,
  site and run context from the run summary, status, note) and `favorites/<target>_<YYYYMMDDTHHMM>/` with copies of
  KML and preview SVG. Report: hidden `.favbtn` stars, shown only via the GUI (`/api/favorites/keys|add`; add looks
  the event up in hits_log.csv by target + minute, site from the last run summary). GUI tab Favorites: iframe of
  `favorites/favorites.html` (`write_page`: report `to_html` with `meta["favorites"]`, rows get `e["fav"]`/`e["site"]`;
  select boxes, Site/Status/Note/Added, per-row KStars site) rebuilt after every change; mass actions call
  `/api/favorites/update|remove|cleanup`; row click -> `parent.emitEvent('fav_select', key)` -> detail panel (preview,
  map from the KML copy, size line, status, note). Entry key `phys`: the pysyzygos.sbdb cache data (H, G, diameter,
  diameter_sigma, extent, albedo as (value, ref)) copied at add time (/dev/shm cache is volatile); GUI start
  backfills it for older entries. `favorites.csv` is rewritten by every `_save` (flat: key/status/note/added/site,
  all record columns, sbdb_*, file paths).
  Event summary (0.14.x): `favorites.event_info(entry)` -> [(group, [(label, value)])] like OWC's event page
  (Prediction/Event/Star/Object; astropy TETE for the apparent place, get_constellation), shown as a 4-column
  grid in the GUI panel. Record fields from `search.event_context` (end of the record); `backfill_event` (GUI start)
  fills older favorites from one Horizons OBSERVER query (quantities 3,20,23) + KML minute marks ("~" = approximate).
  sbdb `entry_from_api` keeps the orbit solution as phys "orbit" (PHYS_KEYS); get_full refetches entries without it.
  Error ellipses: `pysyzygos/ellipses.py` (x east, y north, mas; PA north->east; cov/ellipse/add/star_ellipse/
  across_track/svg). Target: `paths.path_error` (Horizons q37: PA = 90 - Theta, verified = OWC) -> record ast_err_*;
  star: Gaia online check (doubles ERROR_COLS) -> star_err_*; favorites `backfill_errors` (GUI start, daemon
  thread: Gaia may hang; `err_checked` once both answered), `error_svg` -> data URI img in the panel.
- OWC twilight events carry the Sun altitude after the time ("☼ -5°"); `read_owc` parses it (`sun_alt_deg`) and then
  sets MAX_SUN_ALT to the brightest + 1 (fixed 2026-10-04: before, such lines were silently skipped).
- OWC online computes at sea level (ignores the site elevation); `pysyzygos/owc_check.py --sea-level` sets ELE = 0 for
  a like-for-like check. Effect up to h x cos(star alt) across the track (958 m: up to 0.9 km).
- `pysyzygos/owc_check.py` + `owc_reference.txt` (private, not in git: names the site): an OWC search result pasted as
  text; the script parses events and filter settings, reruns pysyzygos/search.py at the sites.py site and compares.
- `owc_refs/` (private, not in git): stored OWC search results (`<site>_<date>_<filter>.txt`, `--ref` for
  pysyzygos/owc_check.py) with the matching pick runs (`.pick.csv/.log`) and a README of settings and findings. Keep
  adding sets there; never delete them.
  `owc_refs/event_checks/<asteroid>_<date>_<star>/` (2026-10-19): single published events compared in detail
  (compare.md + OWC event JSON with Besselian elements + our search output); OWC's x/y/dX/dY are in axes of date.
- `VERIFICATION.md` (2026-10-08): all validation (OWC sets, Occult star positions, internal/geometric checks, what the
  differences mean); ABOUT Part 5 is a summary with a link. New OWC reference sets: add the numbers there (sites
  unnamed: "Test site 1", "Test site 2", "Test site 3", ...; the key to the real sites only in owc_refs/README.md)
  and the details to `owc_refs/README.md` Full lists:
  `pysyzygos owc-check --markdown <set>.list.md` (`--compare-only --hits <saved csv>` for a stored run); markers ✅ 🟠
  (|dt| > WARN_T 1.5 s) 🔴 🔵.
- `pysyzygos/cleanup.py` (`pysyzygos cleanup`, 2026-10-11): deletes downloads, PySyzygos's own cache files
  (CACHE_PATTERNS in cache_path only), catalog extras (bright_*, supplement/, tmp) and run outputs (OUTPUTS), with
  --all also SETTINGS + home.POINTER; NEVER: owc_refs/, owc_reference.*, private-docs/, release/, run.sh, .venv, git,
  catalog star files. Dry run unless --yes; `--orbits` / `--cache` (`empty_cache`, ORBIT_PATTERNS; System tab buttons) delete at once. Reads cache_path from the config only if pysyzygos_config.py exists (loading
  it would create one). Keep its lists in step when new downloads/outputs are added. `tests/test_cleanup.py`.
- `GETTING_STARTED.md` (2026-10-17): beginners' walk-through (install, site, pick, search, results, favorites; why the
  first runs are slow, caches); linked at the top of README's Quick start. Keep it in step with GUI labels.
- `CONTRIBUTING.md`: fork/branch workflow, setup, tests, working with Claude Code, private files, pull requests,
  GPL-3.0-or-later for contributions. `LICENSE` (GPL-3.0 text), `CITATION.cff` (validated with cffconvert).
- `tests/`: stand-in based tests, run each with `python tests/<name>.py` (no SPICE, astropy or network needed).

## Conventions that matter
- Asteroid position: `spkpos(id, et, 'J2000', 'CN', '399')`. Earth centre is 399, not 3. `CN` is astrometric (matches Gaia).
  For a site (solver, `besselian_offsets`) the asteroid is taken with the light time FROM THE SITE:
  `spkcpo(id, et, 'J2000', 'OBSERVER', 'CN', site_itrf, '399', 'ITRF93')`; path lines move the axis per ground point by
  the asteroid's barycentric velocity x (|A| - |A - P|)/c (2026-10-16; geocentric light time for all sites was up to
  ~0.6 km off at the surface, found against Occult). Scans (corridor, pick, pre-screens) stay geocentric (km margins).
- Star direction (0.10.0): `pysyzygos.astrometry.corrected_star_dir` in `handle_star`, once per candidate at et_guess:
  Gaia (propagated) + stellar parallax + light deflection by Sun/Jupiter/Saturn as star MINUS asteroid (asteroid stays
  SPICE 'CN'). Switches `star_parallax`, `light_deflection` (off = old results exactly). Log `star_ra/star_dec` are the
  corrected direction; `corr_parallax_mas`, `corr_deflection_mas`. Not in the pick screen yet.
  `astrometry.deflect` uses the finite-source numerator e (p.q) - q (p.e) (SOFA iauLd; fixed 2026-10-15, before: the
  star form e - (p.e) p for the asteroid too, up to ~1 km wrong near opposition). Gaia proper motions G < 13 corrected
  for the frame spin (`astrometry.gaia_pm_bias` = Cantat-Gaudin & Brandt 2021 edr3ToICRF; `corridor.gaia_pm` skips
  UCAC kinds 3/4; config `gaia_pm_bias`, run summary `corrections`), in `corridor.propagate_exact` and windows mode.
- Fundamental plane: z toward the star, x east = (0,0,1) x z, y north. Miss distance = hypot(dx, dy) in km.
- Observer longitude is east-positive, geodetic, radians inside the solver.
- Geodetic <-> ITRF conversions use WGS84 from `pysyzygos/earth.py` (A_KM, F, C_KM), never `bodvrd('EARTH','RADII')`
  (pck00010 is ~0.4 m off): paths.shadow_path (surfpt/recgeo: height 0 on WGS84, Occult's default), screen.Site,
  search.observer_j2000 / plane offsets, globe. Changed 2026-10-11: paths moved 0.3 m median, <= 3.6 m.
- Target ids are strings of the asteroid number ('218001'); the SPK is aliased with `boddef` in `fetch_target_orbit`.
- Sun limit default 0 deg (2026-10-15; was -6); events with the Sun above `report.TWILIGHT_SUN_ALT` (-12) are marked
  "☼ −8°" after the star magnitude (`twilight_text`/`twilight_mark`; report rows, Markdown, exports.event_shown and
  pick_shown: keep them in step).
- `observable()` returns a tuple `(ok, star_alt, sun_alt)`; always index it. `if not observable(...)` is always False.
- `mag_drop` is the change in combined brightness (`m_ast - m_before`), never smaller than `m_ast - m_star`.
- Drop of at least `d` needs the star no fainter than `m_ast + 2.5*log10(1/(10^(0.4 d) - 1))` (2.54 mag for 0.1).
- SPICE is not thread-safe: use processes, load kernels per process, never call spice from threads. Start worker
  processes with `spawn` (`mp_context=multiprocessing.get_context("spawn")`), never `fork`: forked workers inherit the
  parent's open kernel files and share their read position, so parallel reads of de440.bsp collide
  (SPICE(RECORDNOTFOUND) "corrupted DAF", SPICE(INVALIDRADIUS)). Linux defaulted to fork up to Python 3.13 (3.14:
  forkserver), macOS uses spawn; found on a 14-worker server with Python 3.13 (2026-10-05). Network-only code
  (Gaia/Horizons fetches) may use a few threads.
- Gaia bulk files: `https://cdn.gea.esac.esa.int/Gaia/gdr3/gaia_source/` (note `esac`); the listing is an S3 bucket at
  `https://gaia.eu-1.cdn77-storage.com/?prefix=Gaia/gdr3/gaia_source/&delimiter=/`. Files are `csv.gz` with `#` comment
  lines and `null` for missing values.
- Gaia archive: synchronous `Gaia.launch_job` silently truncates at 2000 rows (`Gaia.ROW_LIMIT = -1` does not lift
  it). Windows mode (cone searches): `launch_job_async`. Online double check and star errors (doubles.py): synchronous
  in chunks (50 events / 1000 source_ids, far below the cap; a chunk reaching 2000 rows is reported), because the
  async job's status polling hung for minutes in 2026-10 while sync answered in ~5 s.
- GUI numbers always with the decimal point: Firefox localises `type=number` inputs by the element's/page's `lang`
  (no lang: the browser locale, German -> "45,12345"). gui.main: head script `document.documentElement.lang='en'`,
  `ui.number.default_props("lang=en")`, `ui.run(language="en-US")`; paste: a single "45,12345" -> "45.12345".
  Verified 2026-10-12 (Firefox lang=de shows a comma, lang=en a point; CDP: all number inputs lang=en).
- Console output must never crash on a character: `__main__.safe_console()` sets stdout/stderr `errors="replace"`
  (Windows cp1252 consoles crashed on "✅", 2026-10-11); GUI runs get PYTHONUTF8=1 / PYTHONIOENCODING=utf-8 (the log
  decodes UTF-8). Code started outside `pysyzygos.__main__.main` must call `safe_console()` itself.
- Standard-library web requests go through `pysyzygos.net.urlopen` (SSL context with certifi's CA list): some Pythons
  (macOS) have no CAs for urllib -> CERTIFICATE_VERIFY_FAILED, while requests (own certifi) works. Never call
  `urllib.request.urlopen` directly; test stand-ins must accept `context=`.
- Every download/web address lives in `pysyzygos/urls.py` (`URL_*` names; no side effects, so setup/geo/kernels/report
  can import it before a sites.py exists). Never hard-code an http(s) address elsewhere; exceptions: XML namespaces
  (SVG, KML) and `pysyzygos.version.__url__`. Tests that exec code excerpts must put `U` (pysyzygos.urls) in their ns.
- Windows: a file must not be memory-mapped (or open) when renamed (WinError 32). Copy blocks out of memmaps
  (`np.array(mm[i:j])`, never `np.asarray`, which is a view keeping the map alive), drop all references before the
  rename, and rename finished files with `gaia_local.replace_file` (retries ~10 s: virus scanners). Tests check
  /proc/self/maps at the rename (test_gaia_local, test_shadowtrack). Found 2026-10-12 in the first Windows install.
- Write cache files atomically (temp file + `os.replace`). Every cache (asteroid SPKs, SBDB bulk list, per-asteroid SBDB size data
  `PySyzygos_sbdb_phys.json`; both SBDB caches refetched after `sbdb_max_age_days`; Horizons orbit SPKs after `orbit_max_age_days`, default 1, stale file used offline) goes to `config.cache_path`
  (`/dev/shm` if present, else the system temp folder); never hard-code a path. Gaia is not cached: corridor mode
  reads the local catalog, the old windows mode queries the archive uncached.
- Historic Earth orientation (2026-10-12): `kernels.historic_earth_pck` (newest `earth_1962_*_combined.bpc`, NAIF
  pck/ listing, `download_historic_earth_pck`, URL_NAIF_PCK_DIR), loaded BEFORE earth_latest_high_prec.bpc
  (`earth_kernels`, screen.load_kernels; SPICE: last loaded wins, so the latest rules from 2000 on: identical, checked).
  search.py start-up: window start before the latest's start -> fetch it; `window_coverage(spans, et0, et1)` checks
  the whole window (start, gaps); the end check stays on the latest file only (no silent century predictions).
  pick: same fetch. setup `--historic-earth`, status line, cleanup pattern. tests/test_kernels_coverage.py.
- Leap seconds (2026-10-16): `kernels.lsk_file(folder)` = newest local naifNNNN.tls (use it, never the literal
  name); `refresh_lsk` checks URL_NAIF_LSK_DIR at most every earth_pck_max_age days (marker .lsk_checked, gitignored),
  called at the end of download_kernels; never raises. Record `star_az` (search.az_deg, SPICE/UT1) feeds the report's
  compass; report.alt_az (UT1 = UTC) only for older records.
- Earth PCK coverage: `pck_comment_dates` reads "Creation date" and "UTC Epoch of last datum" (end of measured EOP)
  from the file's comment block; `pckcov` gives the end of the prediction. Run summary key `earth_pck`; a search window
  past the end exits at start-up.
- Never import `astroquery.gaia` at module level: its import contacts the Gaia archive (status messages, 7 s;
  found 2026-10-16 in every search start). Import it inside the function that queries (search.gaia_cone,
  doubles). search.prefetch_orbits downloads missing SPKs 2 at a time (Horizons answers 503 to more; retried).
- Worker pools call `pick.single_thread_workers()` before starting (OPENBLAS/OMP/MKL_NUM_THREADS=1 via setdefault,
  inherited by spawn): OpenBLAS otherwise starts a thread per CPU in every worker (4 workers on 8 cores: load 24,
  each worker ~40 % CPU; found 2026-10-10 in a pre-screen build).
- SpiceyPy `surfpt` returns only the point and raises `NotFoundError` on a miss.
- Tests use stand-ins for spiceypy/astropy/astroquery that follow the real call contracts; keep them honest when changing
  signatures.

## Status
- Validated 2026-10-02 (`pysyzygos owc-check`, 16 OWC events at the user's site, Oct 2-9): all 16 found, same
  stars (our G equals OWC's "V" column to 0.01, so OWC shows Gaia G), times within 5.4 s (13 within 3 s). Drops match within
  0.25 mag below 5 mag. Durations match within 10 % wherever both use the same diameter; 4 events differ only by
  diameter (H+albedo estimates, or OWC using another source than NEOWISE). Open: 218001 (OWC drop 1.56 mag, ours 12.97;
  OWC diameter 3.56 km, ours 1.77 km from H). Hypothesis, unverified: the 5.6 mag star's angular diameter makes it
  partial; not modelled yet (idea: Gaia `radius_gspphot`, `distance_gspphot`).
- Corridor search is merged into `pysyzygos/search.py` (`handle_star` shared by both modes, `target_test_corridor`, 2-pass driver;
  `search_mode = "windows"` keeps the old path). The Gaia archive was far too slow for strip queries (2026-10-01), so the
  corridor reads only the local catalog `gaia_dr3_g18` (built 2026-10-01: 280.3 M stars of 1811.7 M, 11.2 GB, 101 min).
  Whole run for 23 asteroids x 20 days: 75 s.
- Verified 2026-10-01 against the old path (23 targets, 2026-10-01 + 20 days, reach 200 km): all 40 old hits with
  G <= 18 found, within 1.4 ms and 0.8 m; 10 extra real hits; the other 28 old hits are G > 18 (beyond the catalog).
- Solver bug fixed 2026-10-01: `star_test` minimised over raw ET, where `minimize_scalar(bounded)` has a ~12 s
  tolerance (sqrt(eps)*|x|); it now solves for the offset from the window centre (`tests/test_solver.py`). Results
  logged before (old `hits_log.csv`, maps) are off by up to ~9 s and ~90 km (median 6 km). The OWC check above uses
  the fixed solver.
- Corridor solver bracket: the scan estimates the Earth-centre closest approach; the observer's can be margin/speed
  (10-20 min) away, so the bracket is `corridor.solver_bracket_s` (+/- 1.3 margin/speed, >= 1 step, <= 4 h).
- Not run against live services: Horizons RSS 3-sigma column names in `pysyzygos/paths.py`.
- Pick tool validated 2026-10-01: blind screen of all 465k asteroids (H < 17), Oct 1 + 8 d, 20 km reach, min alt 5:
  39 events incl. all 13 OWC reference events with H < 17 (same stars, times within 5 s, drops/durations as
  pysyzygos/search.py); 819762 (H 18.45) needs `--all`. 875 s in one process, 318 s with 4 workers, same events.
  SBDB bulk elements MUST be full precision (`full-prec=true`): rounded ones give ~40" errors.
- Report map: OpenStreetMap tiles only (`--tile-url`), so it works through a web server (OSM needs a Referer), not
  from `file://`. Map dialog reopen bug fixed 2026-10-02 (the box was cleared on every open, removing Leaflet's panes).

## Ideas not built yet
- Double / companion stars from more sources (planned 2026-10-17, then put on the list): Gaia resolves pairs from
  ~0.4-0.7"; closer ones only show as RUWE, ipd_frac_multi_peak, duplicated_source, NSS (all in the quality part)
  and three indicators we do not keep yet: ipd_gof_harmonic_amplitude (elongated image), astrometric_excess_noise
  (+ _sig), phot_bp_rp_excess_factor (blend in the 3.5" colour window). Plan: 1) WDS (+ ORB6 orbits) as a small
  local data file like data/binaries.json (VizieR B/wds/wds answers: WDS, Disc, Comp, Obs1/2, Nobs, pa1/2, sep1/2,
  mag1/2, SpType, pm, Notes, RAJ2000/DEJ2000; ~150k pairs; ORB6 table name still to find), matched by position per
  event (offline, < 1 ms); 2) the three Gaia indicators added to the online check's ARCHIVE_COLS now (same single
  query), into the quality part at the DR4 rebuild; 3) Gaia NSS orbit parameters (nss_two_body_orbit) on demand in
  the favorites panel; BUILT 2026-10-17 on demand: `doubles.vizier_check` (VizieR ASU B/wds/wds cone 30" +
  I/355/gaiadr3 by Source: RUWE, IPDfmp, IPDgofha, epsi, sepsi, E(BP/RP), Dup, NSS; hints), `vizier_text`, GUI
  favorites button -> entry "vizier" (`favorites.set_field`); ORB6 has no VizieR table under the tried names (WDS
  Notes 'O' tells an orbit exists); 4) per companion: PA, dG, and where its own shadow falls (separation x distance) relative to
  the site; 5) later perhaps IOTA / D. Herald's catalogue of doubles discovered by occultations.
- Catalog additions for the next rebuild (ideally with Gaia DR4, 2026-12-02): compared with Occult's G16 subset (D.
  Herald, 2026-10-16: 77,951,442 stars, 58 B/star, 4.52 GB, zip 2.64 GB; ours 77,952,398): 1) star diameter from
  Gaia FLAME (`radius_flame`, astrophysical_parameters files on ESA's CDN, join by source_id; + a flag "other
  estimates exist") into extras, for the star-size model (218001); 2) Hip/Tyc2 ids from Gaia's best_neighbour tables;
  3) stars too bright for Gaia from Hipparcos 2 (own kind). A core flag bit "entries in other Gaia files" (2 free).
- Catalog mirrors: BUILT in 1.3.0 (starcat `mirrors`, `sources`: Zenodo + `URL_CATALOG_MIRRORS` + env
  PYSYZYGOS_CATALOG_MIRROR, speed probe, resume across sources, `ARCHIVE_SHA256` stored). First mirror: a temporary
  BNL box share (Nextcloud: direct files at public.php/dav/files/<token>/catalog_v2.1/<name>, Range works; one folder per
  set of checksums: rev2 removed 2026-10-19; catalog_v2.1 = 1.3.2 epoch-pm core/quality + xref; never replace files in place, a release
  checks the SHA-256s built into it). Still to add:
  GitHub Releases or another permanent host; replace the BNL one when it goes.
- Live search engine (ABOUT.md 3.8, timings of 2026-10-10): resident process with kernels, catalog, global
  pre-screen + index, SBDB list and orbits in memory; site test + exact solves in ~1-2 s; maps on demand; rolling
  nightly pre-screen builds. Locally: one combined pick + search run (saves a ~5 s start-up), SBDB rows only for
  the pre-screen's asteroids, per-segment index boxes.
- Star angular-diameter model for the drop and duration.
- Astrometric corrections in the pick screen (built for the search in 0.10.0; pick screen still without).
- Process-level parallelism by target (`ProcessPoolExecutor`; parent does kernel checks, Horizons SPKs and opens the local Gaia catalog;
  workers return records, parent writes the CSV).
- `m_before` / `m_during` columns in the log.
- Favorites, next steps (simple version built 2026-10-04, see Files): re-predict one favorite with the latest orbit
  (single-target search; keep old map/preview versions next to new ones), export (CSV, KML bundle, report page),
  share/pull with Occult Watcher Cloud (campaign events, multi-site chords; how TBD, no known public OWC interface;
  findings 2026-10-06: OWC Cloud is a JS app over a private REST API `https://www.occultwatcher.net/api2/v1/...`
  (login), its profile can issue a per-user API key / OAuth client (undocumented), deep link
  `api2/ext/locate?ast=&tag=&date=` (or `&occelmntId=`: Occult element id); no public export/iCal. Plan: ask H. Pavlov
  for API docs and permission, never scrape with the user's login. Without it: prediction feeds (IBEROC etc., Occult
  elements read by OW desktop) may be public files to mark campaign events; the user plans this with the community),
  observation data per favorite (result, D/R times, chord, link to the SODIS report from DVTI+CAM / ASTRID).

