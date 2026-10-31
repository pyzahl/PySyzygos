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
  v1.5.0 was never tagged: v1.5.1 (2026-10-30) is the release after v1.4.0 and carries 1.5.0 (CHANGELOG
  [1.5.0] links the compare v1.4.0...v1.5.1).
  Each 1.x.0 GitHub release also carries docs/math/pysyzygos_math.pdf as an asset (`make` in docs/math: formula
  check + build; the PDF is not in git, decided 2026-10-20: a committed PDF goes stale).
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
- `pysyzygos/paths.py`: shadow ground track (centre, limits, 3-sigma) as KML. Lines at height 0 on WGS84 (Occult's);
  `height_km=` adds 'center_height' (surfpt on a+h, c+h: the height-h surface to < 1 cm up to 5 km; search passes ELE,
  KML "Center line at site height (N m)", report LINE_STYLES first match wins); `height_shift_km` = h/tan(alt)
  towards the star's azimuth, across the ground track (direction from the axis's ground points at et -+ 30 s) ->
  record `height_shift_km` (end; + = A side), report `height_text` (shadow cell title), favorites "Site height
  shift". Checked 2026-10-22: 0.533 vs 0.535 km measured between the lines (2000 m, alt 75 deg).
  Limit lines (2026-10-27, PD.3): offset across the motion RELATIVE TO THE GROUND POINT (v - v_G), not the geocentric
  n (sites on the old lines passed closer: Phaethon -306 m at 500 km); started from the previous sample's direction
  (`last_n`), refined to 1 cm (LIMIT_PASSES max 5); ~+0.13 s per path. Consistency check part 1b tests the lines'
  closest approach. `ground_point` (PL.2/PL.3, shared with earth_point, height_shift_km), `bary_velocity`.
  Ground distance (FP.3): `paths.ground_scale(v_rel, star, up)` = 1/sqrt(1-(n.u)^2); `search.ground_distance` takes
  it halfway to the center line (7 m at 100 km) -> record ground_scale, ground_dist_km, ground_margin_km (end, in
  finish); report `DISTANCE` ("ground" default | "plane"; --distance; DIST_NOTE/DIST_HEAD; e miss/margin = shown,
  miss_p/margin_p = plane for chance, sigma_text, chord; `dist_text` hover); GUI System `pg.sys_dist` ->
  `pg.set_distance` (gui_state shadow_distance, report.DISTANCE in-process, rebuild both pages), `gui_common.dist_args`
  for report runs; db.HITS ground_dist. Reach stays a plane distance.
- `pysyzygos/report.py`: `hits_log.csv` (+ last run of `hits_log.runs.jsonl` for the header) to HTML/Markdown with an embedded Leaflet map. Standard library only.
- `pysyzygos/pick.py`: event finder over all asteroids (OWC-style) for a window; writes `pick_events.csv` and
  `targets.py`, and saves both per site + window in `picks/` (`pysyzygos/picks.py`; pysyzygos/search.py with
  `targets_source = "auto"` uses the newest saved pick of its site covering the search window; an explicit
  `targets` override sets `"list"`). Engine `pysyzygos/screen.py` (site solve, OWC observability formula; no min duration since 1.5.1, user: keep any short dip; `--prescreen all|none` = full screen), orbits `pysyzygos/orbits.py` (SBDB full-precision
  elements + planets, RK4, ~0.01" vs Horizons; 1.5.1: `step_for` halves the 0.5 d step down to 0.5 x (q/1 AU)^1.5
  and the Sun's 1PN term (`_accel(..., v)`): Phaethon q 0.14 was 9,200 km off after its 2026-09 perihelion, the
  pick and all pre-screens missed its events; pre-screens built before miss such events), stars `BrightIndex` (G <= index_gmax(cam_limit) = max(15, ceil(limit)), cells sorted by G; a missing one is
  built by `run_screen` in the parent before the workers start, low-memory via a memmap). Worker processes; chunk
  size and workers from the free memory (`prescreen.plan_chunks`, MEM_FRAC 0.6; 2026-10-27: a fixed 2000 took ~8 GB
  per worker for 100 days and the OOM killer broke the pool).
- Asteroid groups (2026-10-25, user + a colleague's request for high-value targets): `picks.GROUPS` / GROUP_NAMES
  (main MBA/IMB/OMB, trojan TJN, marscross MCA, neo APO/AMO/ATE/IEO, tno TNO, other = any other class), `group_of`,
  `parse_groups` (in the light picks.py: describe() names them; pick.py imports them). SBDB_FIELDS + pha, sats
  (the cache refetches when fields are missing). build_rows rows: cls, group, pha, sats; pick `--groups` filters
  after the pre-screen; pick CSV columns class, pha, sats (end); targets.py header "# asteroid groups:", pick_meta
  groups. Pre-screens (2026-10-26): `picks.selection` (groups or None = all, a_min/a_max/a_exclude), `restricted`,
  `select_rows`, `selection_text`/`_tag`, `selection_covers(built, want)` (groups subset, a range inside; else
  problems) -> prescreen build(selection=) filters rows, meta keys groups/a_*, settings 'selection' only when
  restricted (old partials resume), default name global-<tag>; check() adds selection_covers(meta_selection(meta),
  opt['selection'] (missing = all)); pick passes it; SHARE_KEYS; GUI: no new controls, `pg.selection_args` (pick and
  pre-screen build), `pg.selection_now` (fit check; groups_changed refreshes it). Orbit class in results (2026-10-26): sbdb entry phys '_class' (value code, title
  name, neo, pha; always set by entry_from_api, by entry_from_bulk when the row has 'class'); search sbdb_phys /
  `_phys_fresh` treat entries without '_class' as stale (one refetch); `asteroid_class` -> record ast_class,
  ast_class_name (end, in finish); `picks.CLASS_NAMES`; report `class_text` in the asteroid hover (tip_ast);
  db.HITS column class. GUI Pick checkboxes `pg.p_groups` (gui_state pick_groups); a range `--a-min/--a-max` (`pg.p_amin/p_amax`, gui_state
  pick_a_min/max/exclude, `--a-exclude`; CSV a_au; header/meta/describe); bands table (rowClick -> range); live
  count `picks.count_index(cache json)` (numpy H/a/group of the cached SBDB list, once per file mtime, ~2 s) +
  `picks.count(...)` -> `pg.p_count` (count_update on every filter change). Counts (numbered): main 870,924, trojan 10,633,
  marscross 9,196, neo 3,874, tno 1,049, other 234; unnumbered non-main ~74,000 (not in the pick yet: its bulk list is numbered only; the search takes them, below). Plan for later phases: memory file pick-groups-plan. tests/test_pick_groups.py.
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
  Whole-Earth pre-screens have no reach limit (2026-10-21, user's decision): `check` skips reach_km when the meta has
  no region (inside the disk every event is kept at any reach; reach_km = `EDGE_KM` 200 = the margin beyond the
  Earth's edge and the day/night line only); the site test uses the pick's reach; describe/GUI show no reach for them.
  Shared (1.3.3): `publish` (release/world-prescreens/: <name>.tar.xz via tar + xz -T0 or tarfile, .sha256,
  prescreens.json with SHARE_KEYS settings, catalog_info (catalog.json of the folder or its .new/.old twin), archive,
  archive_bytes/_sha256, files [name, bytes, sha256], meta file last), `remote_list` / `fetch` (URL_PRESCREEN_MIRRORS
  = BNL box world-prescreens/ + env PYSYZYGOS_PRESCREEN_MIRROR, file:// for tests; GL._fetch_resume, only the
  listed members extracted and checked, nothing downloaded if intact). GUI Pick
  "Download shared" (`prescreen_shared`). tests/test_prescreen_share.py. Verified 2026-10-19: global__2026-10-01_40d_G16
  (1.57 GB tar.xz) from the BNL mirror on Linux (identical files) and macOS (interrupted download resumed; pick
  "auto" used it at a newly added site, then search).
  Several build machines (2026-10-22): `publish(..., remote=None)` merges the mirror's current prescreens.json
  (`remote_list`) + the share folder's + the new entry (`merge_manifests`: each name once, the later `published`
  wins; `--no-mirror`). Withdrawing (2026-10-30): the mirror's list is the truth: `on_mirror` drops its entries
  whose archive is not on the mirror (publish and merge), and publish keeps of the share folder's list only entries
  whose archive is in that folder (packed, not uploaded yet); CLI `prescreen merge [lists] [-o] [--check] [--drop
  NAME]` (lists: files, URLs, or names on the mirror; --drop leaves a name out by hand;
  `check_archives` = one-byte GET per archive). The mirror's folder cannot be listed anonymously (Nextcloud
  WebDAV needs login), single files can be read. First use: the 40 d (2026-10-01) + 70 d (2026-10-21) lists merged.
  Tests: publish(remote=[]) (no network), two-machine case via file:// in test_prescreen_share.py.
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
  (JSON config overrides per run). Split by tab (2026-10-21, no behaviour change; checked: the served page is
  identical to the old one's): `gui.py` = main() (start-up, backfills, API routes), quit/restart, index() (header,
  About/quit dialogs, tab bar, log card, header wiring, page-wide catalog_ok/download_csv/results_db); one module per
  tab, `gui_site`, `gui_pick`, `gui_bodies`, `gui_search`, `gui_results`, `gui_favorites` (incl. path verification),
  `gui_system`, each with `panel(pg)` (controls), `handlers(pg)` (functions and state) and, where needed,
  `connect(pg)` (wiring and first fill); `gui_common` = what they share (Job, run_process/stop_process, run logs,
  gui_state, mag_limit/fov, catalog_options, resizable_box, PRE_FIXED, KSTARS_OPT, today_utc, ...). `pg` (a
  SimpleNamespace made per page load) holds every element and function used by more than one part: a tab's
  function is `pg.<name> = <name>` after its def and is called as `pg.<name>()` anywhere, so the names in these
  notes (show_site, prescreen_options, ...) are attributes of pg. index() calls all panels, then all handlers, then
  the connects in the old order (site, header, search, pick, system, favorites): elements are created in the same
  order as before. A new element or function used by another tab: assign it to pg. `pysyzygos/geo.py`: IP/place/elevation lookups (setup + GUI). `pysyzygos/preview.py`:
  event preview SVG per hit (`maps/<target>_<stamp>.svg`), shown by the report's Preview button. Magnifier
  (2026-10-23, `zoom=` -> `_zoom_svg`, ZOOM_PX 184 top right): `zoom_field_arcsec` (3 x nearest neighbour, 10-50,
  30 default; config preview_zoom/_arcsec/preview_seeing_arcsec), stars = LOCAL.cone 40" without a mag cap, core +
  seeing halo (radialGradient), labels dG/sep (<= ZOOM_DMAG 6), tooltip PA, passing time along/rate, shadow offset
  across x delta_km; track from the SITE (spkcpo; geocentric is off by the parallax, arcsec) in whole-second ticks.
  Planets/moons: none. tests/test_preview.py.
- `pysyzygos/bodies.py` (2026-10-08): planets/moons as targets, prefix + name (`P:Jupiter`, `M:Io`; `L:Moon` later),
  REGISTRY (NAIF id, centre = system barycentre, kind, V(1,0), phase coeff, rough sigma3), GROUPS ("jupiter").
  `ensure_kernel`: Horizons VECTORS (CENTER 500@<bary>, 20 min, ICRF) -> SPK type 13 via `spkw13` in cache_path
  (~1 m vs Horizons; Horizons = jup365 ephemeris, so no 1 GB NAIF download), furnsh + `kernels.body_alias(alias)` so all SPICE
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
  View `hits` (2026-10-22, `create_hits_view` in every connect, from `db.HITS` = (column, record field(s) a|b first
  non-empty, kind num/pct/text, unit, meaning): typed columns, numeric text of old CSV imports converted, ''/nan ->
  NULL, chance = p_site x 100; "drop" is an SQL keyword: column mag_drop). `where_keys(path, where, lst)`: current
  series, read-only connection (mode=ro + query_only), no ';', bad SQL -> ValueError; WHERE_MAX_S 10 s via
  set_progress_handler ("took too long"); the condition sits in parentheses after "series = ? AND" (an OR cannot
  leave the list); load_extension "not authorized"; checked: UNION/comment tricks, DROP, ';', endless recursive CTE. report `--where/--db/--list`
  (+ page note .sqlnote); GUI Results "SQL filter (advanced)" (gui_results: sql_in, word suggestions sql_sugg,
  Fields table rowClick inserts, examples, saved conditions gui_state sql_queries, active sql_where used by every
  build_report; gui_results.connect). Report filter bar (all layouts): rows carry data-f* (`report.filter_attrs`:
  mag dur drop alt sun ruwe chance% flags sup/unc/dbl/twi/hz/est/moon; data-ftime = Unix s UTC for the time window
  from/to (datetime-local inputs data-t, read as UTC; 'to' includes its minute; SQL utc >= 'from' / <= 'to:59.999')), `filter_bar`/FILTER_JS: instant filter,
  "showing n of m", named sets via GUI `/api/filters|save|delete` (gui_state filters; file:// -> localStorage),
  the page's last filter in localStorage pyo_filter:<path>; favorites select-all and mass actions only on shown
  rows (event 'pyofilter'). GUI start rewrites favorites.html (new page code). CSV = what is shown: rows carry
  data-ev = `report.event_key(target, utc)` ('target|YYYY-MM-DDTHH:MM:SS'); GUI `pg.shown_keys(frame)` reads the
  visible rows' keys from the iframe (ui.run_javascript, getHtmlElement(id).contentDocument; None if unreadable ->
  all rows) -> `exports.only_shown(pairs, keys)` keeps and orders them (hits_csv, fav_csv, bodies_csv; toast says
  how many). Results tab loads the existing hits_report.html at start (gui_results.connect). create_hits_view replaces the view only when its SQL
  differs (BEGIN IMMEDIATE, a concurrent creation tolerated): dropping it on every connect made the GUI start fail
  ("view hits already exists": backfill thread + write_page connecting at once).
  Horizon applied afterwards (2026-10-22): view column `site` (runs.summary site.name via LEFT JOIN), SQL functions
  `horizon_alt(az)` (list's site = last run of the series) / `horizon_alt(az, site)` registered in where_keys
  (`_horizon_functions`: horizon.altitude on sites.py points, `db._horizons()`; NULL without a horizon),
  db.FUNCTIONS for the GUI help (SQL_NAMES in gui_results); bar field `hzc` "clear of horizon >=" (rows data-faz,
  favorites data-fsite; page `report.horizon_js` = window.PYO_HZ of its sites; JS hzAlt = horizon.altitude; no
  horizon -> pass); SQL template "(horizon_alt(star_az, site) IS NULL OR star_alt - horizon_alt(...) >= v)".
  Checked: favorites page vs Python horizon.altitude, same 9 of 20 hidden at 5 deg. `db.filter_to_sql(spec)`
  (FILTER_SQL / FILTER_HIDE_SQL; often-unknown fields as "x IS NULL OR ...", unc = star_sigma <= 0.5 radius, only
  +moon -> /* comment */, no column): the SQL box is filled from the frame's bar when opened empty
  (`sql_from_bar`, also a button); checked equal to the bar's selection on real data for 14 specs. Verified in headless
  Chrome: G <= 12.5 + sort by Max dur -> CSV of the 15 shown rows, longest first. Verified in headless Chrome
  (G <= 12.5: 15 of 29; shared set offered in Favorites; SQL apply/clear). tests/test_db.py, test_report_filter.py.
- `pysyzygos/doubles.py`: close/double stars per event. Local: `companions()` from `LOCAL.cone` (radius
  `companion_radius_arcsec`, <= 5 mag fainter, proper motion to the event date), `blended_drop`, `fields()` (blend_*,
  mag_drop_blended, double_hint only if the drop changes >= 0.1 mag or Gaia flags). Online (`gaia_online_check`):
  `search.online_double_check` after pass 2: one async ADQL job (OR of circles, daemon thread, 120 s timeout) ->
  `online_fields` -> `db.update_events` (this run's events in the results database).
  New record fields go at the END of the hit record (the log is appended; mixed headers otherwise).
- `pysyzygos/owc.py` (on by default since 1.3.3, user's decision 2026-10-20: low request volume; config `owc_feeds`
  (template True), GUI button "Check OWC Feeds" in Results and Favorites; the old key `owc_lookup` is ignored, since
  every config copy carried `owc_lookup = False`; still say little about it in public docs until IOTA/OWC agree): OccultWatcher Cloud lookup through the public
  event pages' interface `URL_OWC_API` (`events/?astNo=&dt=&bf=` then `event/<id>`; no login; `my-events` needs
  login: not used). Match by Gaia id (`gaia.id`) else time (10 min); 1 s pause, User-Agent PySyzygos; on click only
  (GUI "Check OWC Feeds" in Results/Favorites, `run.io_bound`); cache `<data folder>/owc_cache.json`; report `owc_line()`
  under the asteroid (tags, station count, hover: observer, signed distance km, commitment).
- `pysyzygos/weather.py` (2026-10-29, user's wish: "will it be clear?"): Open-Meteo forecast (URL_OPEN_METEO, no key,
  hourly cloud_cover + low/mid/high, precipitation_probability, visibility; 16 days, model best_match) per site
  (`site_key` = lat/lon to 0.01 deg) -> <data folder>/weather_cache.json (gitignored, cleanup DOWNLOADS); `check(favs)`
  only for events from PAST_H 6 h ago to 16 d ahead, one request per site, on click (GUI Favorites "Cloud forecast",
  `pg.fav_weather`, errors to fav_log); `info(lat, lon, utc, cache)` linear between hours + strip +-STRIP_H 3 h;
  `symbol` (🌙 <= 20, ⛅ <= 50, 🌥 <= 80, ☁), `level`, `short`, `text`, `strip_html`. report `weather_line(e)` under
  the time in favorites rows (span.wx wx-clear/part/cloudy); panel `pg.f_wx`. tests/test_weather.py.
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
  search's), asteroid geo/bary(t - lt)/lt/own deflection + geometric barycentric states at t (asteroid, Earth, difference; S.
  Preston's request 2026-10-20), Besselian elements (ICRF axes and of date via erfa.pnm06a/gst06a,
  d, mu) at touch-down/centre/leaving (bisection on the centre line, minimize for the centre), geodetic points ->
  steps_<stamp>.md/.json. `run` deletes the target's cached SPKs first (search reuses covering cache files up to orbit_max_age_days)
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
  Sky detection (2026-10-22) for photos without a transparent sky: `sky_mask(rgb)` (blue: b > r+8, b >= g-5, v > 70;
  or bright grey v > 200, sat < 0.18 (haze, glare); opening; only regions touching the top rows (blue roofs/water
  below do not count); closing; top 3 deg = sky; fill holes (clouds); padded with wrap-around first, else the
  smoothing ate the left/right edges); `ground(im)` -> (mask, 'transparent sky' | 'sky detection') or (None, '')
  under 2 % sky; `profile` uses it; meta `profile_from`; GUI notify says which. Checked on the stored London (Royal
  Observatory, cloudy) and home photos: lines on tree crowns/roof; home vs its 11 OW points: 19-44 vs 23-45 deg where
  low, trees 65-85 vs 80. test_panorama: synthetic sky/cloud/skyline/lake case.
  Aligning by the Sun (2026-10-22): `sun_altaz(lat, lon, utc)` (NOAA solar formulas + refraction; vs astropy <=
  0.01 deg, test uses Greenwich references), `sun_in_photo(jpg)` (largest saturated white blob above -10 deg ->
  (deg from left edge, alt)), svg(sun=) yellow ring + "Sun az", azimuth ticks every 5/10 deg with numbers. GUI Site
  tab: "Sun at (site's local time)" (filled from the photo's EXIF: `photo_time` at upload, before the thumbnail
  drops it: GPS time > DateTimeOriginal+OffsetTimeOriginal > DateTimeOriginal as local; meta 'taken';
  `photo_location` -> meta 'where' -> `photo_where` dialog offers it for the site (> 100 m off; GoPro exports have
  an empty GPS fix, GPSAltitudeRef is a byte); upload with
  the Sun in the photo aligns at once; show_site refills it) (hz_sun: geo.timezone of the form's position, cached pg.HZ_TZ; 16:45:04,
  4:45:04 pm or 2026-10-22 16:45) + "Align by the Sun" (hz_sun_align: hz_az = sun az - disk position). First use:
  Camp photo, Sun at 4:45:04 pm EDT 242.8 deg -> left edge 183.0 deg, disk 1 deg low. A GoPro file name's 13-digit
  number is the file's save time, not the capture time.
- Site tab safety (2026-10-24, after a real mix-up: Add site copied a site's photo/description, a save put another
  place's position into a site): `switch_site` (header selector -> dialog Save <old> / Discard / Cancel when
  saved_site != effective(collect)); `show_unsaved` (label + save_btn amber "Save changes"); `pg.SITE_GEN` counter
  (+1 in show_site) and `site_stale(gen, what)` guard every await that writes the form (elevation, places, IP,
  photo save, timezone, Sun, horizon file); `new_site_from_form` (Add site: HZ_KEYS, description, MPC code only if
  changed); panorama.save names files <site>_<YYYYmmdd-HHMMSS>.jpg (never overwrites a saved site's photo).
  Verified in headless Chrome on a throwaway data folder (edit -> amber; switch -> dialog; cancel/discard/save).
- GUI job slots (2026-10-19): `Job.proc` = the main job (search, pick, pre-screen, setup, report, catalog: one at a
  time, blocking each other), `Job.fav` = the Favorites tab's path-verification tasks (run, export, compare, steps,
  keep), independent of the main job; `run_process(..., slot="fav")`, `stop_process(log, slot)`. The Favorites tab
  has its own log card (`fav_log`, Clear/Stop) and hides the main log card (tabs.on_value_change). Safe in
  parallel: own processes/SPICE, path-check output in favorites/<key>/pathcheck/run with its own db; it deletes only
  that asteroid's cached SPKs (picks/pre-screens do not use them; a main search of the same asteroid at that moment
  would download it again). `_stop_job` (quit/restart) stops both.
- Server mode (2026-10-28, `pysyzygos/server_mode.py`, deploy/; one name everywhere: server mode, --server,
  MODE["server"], server_auth.json; only systemd's own "service" stays): the GUI on a home server for the observatory computer
  or a phone, one user. `gui --host 0.0.0.0` (non-loopback) or `--server` -> server_mode.MODE["server"]; login
  `gui --set-password` -> HOME/server_auth.json (PBKDF2-SHA256, mode 600, cookie secret; gitignored, cleanup
  SETTINGS); `server_mode.Guard` pure-ASGI middleware (app.add_middleware in gui.main, covers the mounted
  /_nicegui_ws socket): HTTP Basic once -> signed cookie pysyzygos_session (30 d, SameSite=Strict, HttpOnly,
  Secure over https / X-Forwarded-Proto), WebSocket by cookie; `--no-auth` only behind a login proxy. Cross-site
  guard in BOTH modes (`cross_site_refused`: /api and WebSocket same-origin only; other paths allow only
  navigation; Origin vs Host without Sec-Fetch): before, any page could GET /api/favorites/remove on 127.0.0.1.
  Off in server mode: KStars/Stellarium (/api/*/status ok False, show refuses; report .stbtn now asks
  /api/stellarium/status), the Results location checkbox, Quit (restart_app passes --host/--server/--no-auth),
  the browser. User docs: `SERVER_MODE.md` (all of it: setup, systemd, HTTPS, Tailscale for phones outside, never
  an open port; the API and its fields; security notes; keep in step), README only links it; deploy/ = the unit
  file and Caddyfile (+ a short README listing them). Checked 2026-10-28 with curl on the LAN address: 401/200 + cookie, socket.io
  polling and WebSocket 101 with cookie, 403 without/foreign origin. Not yet: several users, phone layout.
  Favorites API for programs (2026-10-28, user's PyStarLight camera app pointing a telescope): `pysyzygos/pointing.py`
  (`event(entry)` JSON: target, utc, shadow window, star name/ids, ra/dec_icrs = record star_ra/dec, ra/dec_app =
  erfa atci13 - eo (= astropy TETE to 0.000"), alt/az, site, /fav files; `select` from/to/status/site/limit),
  routes GET /api/v1/, /api/v1/favorites, /favorites/next, /favorites/{key} (gui.main, Query alias 'from'). Tokens:
  `gui --new-token NAME|--revoke-token|--list-tokens` (auth file 'tokens', SHA-256, kept by --set-password),
  Bearer, GET/HEAD on TOKEN_PATHS /api/v1/, /fav/ only, no cookie; Guard re-reads the file on (inode, mtime_ns)
  change. Keep the v1 field names stable (an outside program reads them). tests/test_server_mode.py.
- GUI header power button: `quit_dialog` -> `restart_app` (os.execv `python -m pysyzygos gui --port P --no-browser`,
  GUI_ARGS) / `quit_app` (app.shutdown); `_stop_job` first. Report: `alt_cell` + AZ_SWITCH/AZ_JS (checkbox in the
  Altitude header, its clicks do not sort; localStorage az_deg); `sigma_text`, chance column "33 % · 0.6σ", `chance_bar_svg` (favorites panel f_bar).
  Sort memory (2026-10-22): report JS stores the last sorted column (heading text) + direction per page
  (localStorage `pyo_sort:<pathname>`: results, favorites, bodies separately) and re-applies it on load (checked in
  headless Chrome: a rebuilt/reloaded page keeps "Max dur" descending).
- `pysyzygos/pmcheck.py` (2026-10-19): per event on a 2-parameter star (kind >= 2, config pm_alternatives): VizieR
  ASU UCAC5 (I/340/ucac5: RAgaia/DEgaia within 1", G 0.5) + UCAC4 (I/322A/out: J2000 + own pm to 2016 within 1",
  mag 1.5; EpRA/EpDE, e_RAJ2000/e_DEJ2000 = position errors at the central epoch) -> `estimates` (UCAC5, UCAC4,
  epoch via starcat.epoch_pm on a built UCAC4_REC, J2000->Gaia "as Occult"; east/north mas offsets at the event vs
  the pm used), `spread_mas` (RMS) -> s_mas = max(quoted, spread) in search; `shifted_dir` -> extra shadow_path per
  alternative, paths["pm_alts"] [(label, centre pts)] -> KML "Proper motion <label>" (report LINE_STYLES pink),
  save_path_debug pm_1.. + pm_labels; record star_pm_alts (summary), star_pm_spread_mas/_km (end). Report amber tier
  `star_noted` (0.5 r < s <= r, span.swarn2), tooltip lists estimates; favorites `alts_text`. Galbraith: "as Occult"
  line on Occult's centre to 0.19 km. tests/test_pmcheck.py (stand-in TSV of Galbraith's rows).
- Run warnings (2026-10-26, user's rule: every automatic fallback or critical skip is recorded permanently, not only
  in the log): search.py `WARNINGS` (key -> text), `OLD_ORBITS`, `SKIPPED`, `NOTED` via `run_note(kind, target)`
  (NOTE_TEXT kinds), pmcheck.FAILED -> `run_warnings()` -> run summary "warnings" -> report `warnings_info` row
  "Warnings" (`info_html` class warn, orange). Pick: pick.WARNINGS (older SBDB list) -> pick_meta warnings + header
  "# WARNINGS:" -> picks `warnings_text` (GUI Pick `pg.pick_warn`, Search tab targets line orange) and the search's
  WARNINGS["pick"]. A new fallback anywhere: add it there. tests: test_orbit_cache (run warnings), test_offline.
- Search hit flow (1.3.3): `handle_star` solves and checks, then for asteroids appends (target, best_utc, finish) to
  `PENDING`; `finish(perr)` (inner function: sigma, chance, star fields, db.add_event, maps) runs in `finish_pending()`
  after pass 2 (corridor and windows mode): `path_error` for all hits PATH_ERROR_WORKERS (2) at a time in threads
  (network only; 3 at once gave ~40 % HTTP 503), None ones once more alone, then each finish in the main thread
  (SPICE). Planets/moons finish at once. DEFER_HITS = False restores the old one-by-one flow. `paths.path_error`
  retries a 503 up to 3 times. `prefetch_sizes` (SBDB, 4 threads, one retry, cache written once in the caller) runs in
  a thread beside `prefetch_orbits`. Verified 2026-10-19: 8 targets with maps and 200 targets: identical records
  (and KML) to the old flow; uncertainties 48 s vs 103 s for 201 hits. tests/test_patch.py calls finish_pending.
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
- `pysyzygos/selfupdate.py` (2026-10-23, `pysyzygos update [--check]`, System tab top line): `repo_dir()` = the
  checkout the code runs from (.git); `status()` = git fetch, rev-list ahead/behind vs @{u}, dirty tracked files
  (porcelain, untracked ignored), commits, remote version.py and `changelog_head` (entries above this version) via
  git show; + GitHub latest release (URL_GITHUB_LATEST_RELEASE) for ZIP installs; `update()` = pull --ff-only only
  when behind, clean and not ahead; deps (`uv sync` with uv + .venv + uv.lock, else pip install -e) when
  pyproject.toml/uv.lock changed. GUI: checked once when the System tab is first opened (no other notices, user's
  wish), Update -> run_process + restart dialog (pg.restart_app). tests/test_selfupdate.py (temp bare remote).
- `pysyzygos/observed.py` (2026-10-23, `pysyzygos observed build|status|show`): Occult's Asteroid~Observations.xml
  (occultdata "observations"; `_finish` builds it after download) -> occult_data/observations.db (db.py tables,
  results list "observed", one run with summary kind "observed"; built as .new then os.replace; db.add_event
  commit=False bulk) + observations_log.csv export. `record(ev)`: our field names (target_id, target_name, best_utc
  = ReferenceTime, star = Gaia id, star_ra/dec J2000 deg (RA hours x 15), mag = Mg, r_km = nominal dia/2,
  max_duration_s = longest main-star D..R, star_ruwe/star_flag) + archive fields: fit_* (EllipticFit; quality
  FIT_QUALITY), geo_x_km/geo_y_km (MainBody: observed centre in the geocentric plane, AXES OF DATE), n_chords,
  fit_code, conj_x/y_km + conj_utc (MainAtConjunction = geocentric closest approach, confirmed), sat_* (Satellite
  14 fields, last = CBET; sat_cbet), star_double, n_observers (distinct; an observer appears once per chord),
  n_positive/n_miss/n_cloud, obs_sites (list: observer, place, lon, lat, alt_m, result), prediction; contacts = each
  observer's D/R (codes D/R/G/B/d/r). Format doc: occult_data/FileFormat AsteroidObservations.htm. 17,218 events in
  5 s. Rebuild re-applies obs_check results. db._cell writes lists/dicts as JSON. db.HITS columns chords,
  observers, fit_quality, cbet, dx_across, dt_along, scope. Report: layout "observed" (`html_row_observed`,
  `obscheck.check_event(key)` (CLI `obs-check event`, dialog button): per observer site (details rows, positive/
  miss/clouded) a search subprocess (overrides LAT/LON/ELE(+geoid)/ELE_MSL/GEOID_M, site_name/site = 'Place
  (Observer)', no limits, maps/preview/globe into HOME/obs_checks/<key>/NN, removed after), the hit on the event's
  star -> favorites.add(record as CSV strings via db._cell, key_suffix '_<observer>', status observed/clouded, note);
  favorites.add got key_suffix/status/note (files looked up by the base key).
  `sites_text`; rows class obsrow + OBS_JS: click -> parent.emitEvent('obs_select', data-ev) -> gui_results
  `show_observed` dialog from observed.find(key) + `details(rec, contacts)` (sections + one row per observer/site with
  our chk_chords; CLI `show <n> --date`)), header_info kind observed; archive rows skip dedupe (O(n^2), and it merged 10 real events), KML
  lookups and alt_az (17k rows: 2 min -> 1.7 s); exports.results_rows likewise. tests/test_observed.py.
- `pysyzygos/obscheck.py` (2026-10-23, `pysyzygos obs-check run|report`, System tab "Check our predictions" /
  "Summary"): per observed event with MainBody on a Gaia DR3 star of the local catalog: Horizons SPK per asteroid
  (span of its events +-2 d; `workers` download threads -> queue -> main thread SPICE; file deleted after use),
  star by source_id from LOCAL.cone(30"), `predict` = propagate_exact + corrected_star_dir, asteroid 'CN' geocentric
  at the reference time, plane axes of date (`date_axes`: erfa.pnm06a true pole; precession turns north by ~20"/yr x
  sin RA / cos Dec), `compare` -> chk_across_km (+ left of motion), chk_along_km/_s, chk_mas. Results
  occult_data/obs_check.jsonl (resumed by key target|utc|star; SIGTERM = Ctrl-C), `apply_to_db`, `summarize` ->
  obs_check.md (by fit quality, year, chords, star; largest outliers). Pilot 48 events: medians ~0 (axes right).
  Per-site check (the main one, user's wish: measured data, not Occult's fit): `load_chords` (contacts D/R of the
  main star paired per observer+site; misses from obs_sites), `site_solve` (spkcpo from the site, minimize |xy|;
  returns t_ca, d, v, p0, w), `chord_checks`: dt_mid_s = (D+R)/2 (minus personal equations) - t_ca; dur_pred_s
  (archive nominal circle) and, with `best_size` (fitted ellipse if axes fitted and quality 2/3/4/6, else shape
  dia), `ellipse_chord` -> dur_pred_best_s, dt_mid_best_s; misses dist/outside_km/inside_best. Record chk_v 2,
  chk_chords, chk_misses, chk_site_dt_s (median, all chords incl. Occult-excluded), chk_size_best. Contacts data
  carry datum ('_' WGS84, N NAD27, ...; '*' taken as WGS84), method ('f' visual), pe_s, include ('x' excluded),
  time_adj_s (Occult's, not applied). Height: alt + EGM96 geoid (assumed MSL). occultdata.remove keeps
  obs_check.* (results were lost once when the dataset was re-ticked). Phaethon video chords: mid-times within ~0.01-0.04 s.
- Search anywhere on Earth (2026-10-23): config `search_scope = "earth"` (GUI Search toggle "Anywhere on Earth":
  targets from the list, results_list "earth", hits earth_log.csv, max_shadow_dist 0). search.py `EARTH`,
  `earth_point` (geocentric closest approach over the bracket, ground point via paths.ground_point = each point's own light time, as all path lines (2026-10-26, user: all paths the exact same corrections; pin to center line 0.2-1.4 m, was up to 0.38 km); shadow touches the WGS84 outline: ellipse A x
  sqrt(A^2 sin^2 d + C^2 cos^2 d) + r; ground point on the axis at that time, or just inside the outline), then
  star_test at that ground point; no window_is_observable gate, observable() not rejecting, p_site NaN, no
  horizon; record scope, ground_lat/lon, geo_utc, geo_miss_km, geo_x/y_km (J2000 axes), central; `site_lle(record)`
  replaces config LON/LAT/ELE for KML pin, preview, globe, height line. run summary scope; report header_info scope
  earth. Checked: 15 random observed 2024-26 events all found on the observed star, geo_utc = archive conj_utc to
  ~1-3 s. GUI Results `SOURCES` (site / earth / observed; `source_files`, `where_key` per source in gui_state
  sql_where[_src], results_source), routes /out/earth_report.html, /out/observed_report.html.
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
  Star mark (2026-10-22): buttons send `data-names` (report.`sky_names`: "HIP n|Gaia DR3 id") -> `kstars.mark`:
  getObjectDataXML (unknown: '<xml></xml>') then addLabel, the previous label removed (`LABEL`). KStars 3.6.2 finds
  stars by proper/Bayer name only ("alp Ori"), not HIP/HD/SAO/TYC/Gaia numbers: most occultation stars stay unlabelled
  (message says so). No D-Bus call selects by position (checked the whole interface). The user's solution: a custom
  FOV symbol (Settings > FOV Symbols: "PySyzygos Pointer", 0.5'x0.5', Crosshairs) marks the map center, where the
  star always is (README "Marking the star in KStars"; the no-name message points to it). popupMessage is not in
  exportImage (unverified on screen).
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
  Star mark (2026-10-22): `stellarium.mark(names)` = main/focus target=<name> mode=mark (answers "true"/"false"; the
  selection marker, view unchanged), first known name wins; none: main/focus without parameters clears the selection.
  Verified live: "HIP 24973" and "Gaia DR3 3383655504436521856" (G 9.8) found, TYC names not. show() clears the
  selection before main/view (a selected, tracked star pulls the view back: "several clicks to get there"); mark()
  asks again for up to 2 s (deeper catalogs load only for the region in view once drawn). View/fov are reported at
  the target at once and stay there through a location change (checked). Stellarium applies a new time/location at
  its next DRAWN frame; idle it drew 0.02-1 frames/s here (screenshots via scripts/direct core.screenshot, saved to
  ~/Pictures/Stellarium), so a view set before that frame could land elsewhere (user: first click at the Pleiades,
  second right; not reproduced on demand): mark() re-sets the view before each retry (up to 3.5 s) and show() sets
  it once more 0.5 s after marking. The user found the trigger: a time-zone change (another site's zone). show() now
  sets StelCore.currentTimeZone only when it differs (`current_time_zone`, GET stelproperty/list) and then sends the
  event time again after 1 s (tests/test_stellarium.py covers both).
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
  `owc_refs/occult_paths/consistency/check.py` (2026-10-22): path points (all lines, Phaethon 2019) as sites in
  search.besselian_offsets -> d = line offset within 1 cm (3.1 mm now); `--old REV`, `--occult`. Run it after
  changes to paths.py or the solver.
  `owc_refs/event_checks/<asteroid>_<date>_<star>/` (2026-10-19): single published events compared in detail
  (compare.md + OWC event JSON with Besselian elements + our search output); OWC's x/y/dX/dY are in axes of date.
- `docs/verification/` (2026-10-30, tracked): scripts behind VERIFICATION.md numbers that need no private data
  (`gr_effect.py`: 1PN term per orbit class in orbits.propagate; `horizons_check.py`: orbits.propagate vs Horizons vectors, same solution, 300 d; slide "Sources for the asteroid path" = screen own orbits vs search Horizons SPK). Open from it: Pluto (134340) in the screen feels
  barycenter 9 (its own system, ~2,000 km away): leave out the target's own system barycenter in orbits.py.
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
- `docs/math/` (2026-10-20, tracked): the math slides on their own (beamer): `pysyzygos_math.tex` (main),
  `math_slides.tex` (the slides, single source: workflow, need for speed SP (funnel), search corridor CO
  (corridor.py), pre-screens and picks PS (shadowtrack.py), conventions, who computes what, notation, astrometry ST1 ST2
  AS, solver IN OB LT, Besselian figure, FG FP CA OV, shadow path on the map PG (geocentric-plane figure + inputs)
  PT PL PD (paths.shadow_path, height_shift_km; added 2026-10-26); "variables and outputs" slides (no ID) after the
  astrometry, solver and PG slides: inputs, intermediate symbols, outputs with record field names (keep in step)), `preamble.tex` (theme, colours, \vv \uv \slideid \eqtag \grp,
  library tags; shared), `figures/` (Besselian elements, CC BY-SA 3.0, credit on its slide), `Makefile`
  (check_xref then latexmk), `check_xref.py` -> `xref_table.tex` (generated appendix "Code references"). The
  private talk (slides/, gitignored) \input's preamble and math_slides from here; personal slides and the Galbraith
  globe (names the site) stay private. Convention: math slides carry \slideid{ID}; key formulas are numbered
  ID.n (\tag in displays, \eqtag in text lines); the function implementing one gets a comment block right above
  its def: `# Math: FP.1, FP.2 (slide FP): ...` (ranges ST2.1-ST2.3, "slide X" refs). After changing a formula or
  its code, run `python3 docs/math/check_xref.py` (tests/test_math_xref.py fails on references that do not exist).
- `CONTRIBUTING.md`: fork/branch workflow, setup, tests, working with Claude Code, private files, pull requests,
  GPL-3.0-or-later for contributions. `LICENSE` (GPL-3.0 text), `CITATION.cff` (validated with cffconvert).
- `tests/`: stand-in based tests, run each with `python tests/<name>.py` (no SPICE, astropy or network needed).

## Conventions that matter
- Asteroid position: `spkpos(id, et, 'J2000', 'CN', 'EARTH')` (399, not 3 = the Earth-Moon barycentre; by name, see below). `CN` is astrometric (matches Gaia).
  For a site (solver, `besselian_offsets`) the asteroid is taken with the light time FROM THE SITE:
  `spkcpo(id, et, 'J2000', 'OBSERVER', 'CN', site_itrf, 'EARTH', 'ITRF93')`; path lines move the axis per ground point by
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
- Never name a real body by a numeric string in SPICE calls ("EARTH", "SUN", "JUPITER BARYCENTER", "SATURN
  BARYCENTER", "MOON"; astrometry.DEFLECTORS; radii with bodvcd(code)): body_alias makes asteroid numbers names, so
  "5", "6", "10", "399" meant asteroids 5, 6, 10, 399 once they were targets (fixed 2026-10-23, found by obs-check).
- Unnumbered targets (2026-10-30, first: TNO 2026 ED138): the provisional designation is the target id ('2026 ED138',
  with the space). `sbdb.is_designation`, `sbdb.split_targets` (GUI Search list, comma separated, user's wish: commas are hard
  boundaries, spaces trimmed; within an item a year + designation token is one target, '2026 218001' stays two;
  '2026_ED138'/'2026ED138' -> '2026 ED138'); search `horizons_command` -> "'DES=2026 ED138;'"
  (quoted, else Horizons: 'missing COMMAND content'), SPK object = JPL's SPK id (54667839); get_asteroid_name,
  sbdb.get_full and favorites.backfill_phys accept designations; owc.lookup skips them (number only); file names
  keep the space (report URLs are quoted). Not in the pick/pre-screens (SBDB bulk list: numbered). tests/test_designations.py.
- Target ids are strings of the asteroid number ('218001'); `fetch_target_orbit` makes it a SPICE name of the SPK's
  object with `kernels.body_alias` (kernel pool NAIF_BODY_NAME/CODE). Never `spice.boddef` for names: CSPICE N0067
  holds 853 name/code pairs, ~692 built in, so boddef fails after ~161 (SPICE(TOOMANYPAIRS); a 400-target search on
  2026-10-19). The pool takes thousands (tests/test_body_alias.py); kclear() empties it, body_alias restores all.
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
  `PySyzygos_sbdb_phys.json`; both SBDB caches refetched after `sbdb_max_age_days`; Horizons orbit SPKs after `orbit_max_age_days`, default 7 (2026-10-21; was 1): search `_fresh_spk` also reuses a file of another window that covers this one; `horizons_up()` probes Horizons once per run (10 s connect; False after a failed connection or a server-fault answer, `HORIZONS_FAULTS` e.g. 'wldini(): missing required file', raised as ConnectionError): when down, no requests, cached covering files of any age with a WARNING line, default path uncertainties (an outage cost ~1 min per target before); tests/test_orbit_cache.py) goes to `config.cache_path`
  (`/dev/shm` if present, else the system temp folder); never hard-code a path. Gaia is not cached: corridor mode
  reads the local catalog, the old windows mode queries the archive uncached.
- Historic Earth orientation (2026-10-12): `kernels.historic_earth_pck` (newest `earth_1962_*_combined.bpc`, NAIF
  pck/ listing, `download_historic_earth_pck`, URL_NAIF_PCK_DIR), loaded BEFORE earth_latest_high_prec.bpc
  (`earth_kernels`, screen.load_kernels; SPICE: last loaded wins, so the latest rules from 2000 on: identical, checked).
  search.py start-up: window start before the latest's start -> fetch it; `window_coverage(spans, et0, et1)` checks
  the whole window (start, gaps). End (2026-10-27, user's decision): past the latest's prediction (~3 months)
  `kernels.long_term_check` allows the combined file's long-term prediction up to LONG_TERM_MAX_DAYS 365 after its last
  measured value (UT1 ~0.01 s at 6 months: ~4 m), fetched when missing, with a run Warning (search EARTH_PCK
  'long_term' -> run_warnings; pick WARNINGS); beyond: exit. Forced refresh: `kernels.refresh_earth_pck`, setup
  `--refresh-earth`, System tab button (`pg.sys_earth`).
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
- Maps on demand (user, 2026-10-20): a 400-asteroid search (430 hits) spent 32.7 of 70.6 s on maps (KML, preview,
  globe SVG; ~0.08 s per hit). A switch for big searches to skip them (config write_maps/write_globes exist, but no
  GUI choice), and make them only for favorites (when a hit is starred: KML + preview + globe from the record and the
  saved path, as the favorites copy them now) or on click in the report. Next after that: the VizieR proper-motion
  check (~1.4 s per 2-parameter star) and the online double check (~9 s per run).
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

