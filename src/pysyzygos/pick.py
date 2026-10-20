"""pick.py - find the actual occultation events at your site for all asteroids, OWC-style, and choose the
`targets` list for search.py from the best of them.

Pipeline
  1. asteroids : JPL SBDB bulk query, full-precision elements (numbered, H < --hmax, or --all), cached as JSON
  2. paths     : every asteroid integrated with the planets over the window (orbits, ~0.01" vs Horizons)
  3. events    : actual Gaia stars (local catalog, bright-star index) along the path, solved for your site
                 (screen); only while the asteroid is up and the Sun is down
  4. detection : OWC's General Observability Criterion, StarMag < 5 log10(aperture_cm) + 2.5 log10(duration/frames)
                 + 8.5 + MagAdjust (optionally with atmospheric extinction), plus --min-dur and --min-drop.
                 Durations for this use the upper size bound, so H-only sizes are not dismissed too early.
  5. output    : pick_events.csv (all events), a ranked table, and targets.py with the asteroids of the best events.
                 Their size data goes to the shared size cache, so search.py needs no SBDB lookups for them.
                 search.py then computes the events exactly (Horizons SPK, exact solver, maps).

Defaults come from pysyzygos_config.py (site, window ct/days, reach, altitude limits, pick_* settings).
Needs the kernels and the local Gaia catalog with its bright-star index: pysyzygos setup
"""
from pysyzygos.version import __version__
from pysyzygos import net                      # https with certifi's certificate authorities
from pysyzygos import urls as U
import argparse, datetime as dt, json, math, os, sys, tempfile, time, urllib.parse, urllib.request
from concurrent.futures import ProcessPoolExecutor
import pandas as pd
from pysyzygos.home import HOME
from pysyzygos import sbdb                                     # shared per-asteroid size cache

SBDB_URL = U.URL_JPL_SBDB_QUERY_API
SBDB_FIELDS = ["spkid", "full_name", "H", "G", "diameter", "diameter_sigma", "extent", "albedo", "a", "e", "i", "om",
               "w", "ma", "epoch", "condition_code", "neo", "class"]


# ---------------------------------------------------------------- SBDB

def hms(seconds):
    """Seconds as H:MM:SS (progress lines)."""
    s = int(max(seconds, 0))
    return f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}"

def fetch_sbdb(hmax, cache, max_age_s=None):
    """Bulk SBDB download of numbered asteroids with H < hmax (hmax None: all), full-precision elements. Cached (atomic
    write); reused while it covers hmax, has all SBDB_FIELDS in full precision and is younger than max_age_s (config
    sbdb_max_age_days). Returns (fields, data, fetched)."""
    max_age_s = sbdb.max_age_s() if max_age_s is None else max_age_s
    want = math.inf if hmax is None else hmax
    stale = None                                                 # an expired cache: still usable without network
    if cache and os.path.exists(cache):
        with open(cache) as f:
            blob = json.load(f)
        fetched = blob.get("fetched") or os.path.getmtime(cache)
        usable = blob.get("hmax", 0) >= want and blob.get("full_prec") and set(SBDB_FIELDS) <= set(blob["fields"])
        if usable and time.time() - fetched < max_age_s:
            return blob["fields"], blob["data"], fetched
        stale = blob if usable else None
    from pysyzygos import offline
    copy = offline.sbdb_fallback(want)                           # the cache emptied (e.g. /dev/shm after a restart):
    if (copy and copy.get("full_prec") and set(SBDB_FIELDS) <= set(copy.get("fields", []))   # a fresh offline copy
            and time.time() - (copy.get("fetched") or 0) < max_age_s):                       # instead of 100 MB again
        print(f"asteroid list from the offline copy of {time.strftime('%Y-%m-%d', time.gmtime(copy['fetched']))} "
              f"(the cache had none, e.g. after a restart)", file=sys.stderr)
        _write_cache(cache, copy)
        return copy["fields"], copy["data"], copy["fetched"]
    q = dict(fields=",".join(SBDB_FIELDS), **{"sb-kind": "a", "sb-ns": "n", "full-prec": "true"})
    if hmax is not None:
        q["sb-cdata"] = json.dumps({"AND": [f"H|LT|{hmax}"]})
    print(f"Downloading SBDB ({'all numbered' if hmax is None else f'H < {hmax}'}, full precision) ...", file=sys.stderr)
    try:
        with net.urlopen(SBDB_URL + "?" + urllib.parse.urlencode(q), timeout=1200) as r:
            blob = json.load(r)
    except (OSError, ValueError) as e:                           # no network (or a broken answer): an older list
        old = offline.sbdb_fallback(want) or stale
        if old is None:
            raise
        age = (time.time() - (old.get("fetched") or 0)) / 86400.0
        print(f"WARNING: SBDB not reachable ({str(e)[:80]}): using the asteroid list from "
              f"{time.strftime('%Y-%m-%d', time.gmtime(old.get('fetched') or 0))} ({age:.0f} days old; orbits of that "
              f"date)", file=sys.stderr)
        return old["fields"], old["data"], old.get("fetched")
    blob["hmax"], blob["fetched"], blob["full_prec"] = want, time.time(), True
    offline.keep_sbdb(blob)                                      # a compressed copy for offline use, if switched on
    _write_cache(cache, blob)
    return blob["fields"], blob["data"], blob["fetched"]


def _write_cache(cache, blob):
    if not cache:
        return
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(cache)), suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(blob, f)
    os.replace(tmp, cache)


def to_float(x, default=float("nan")):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def build_rows(fields, data, hmax):
    """Asteroid dicts for the screen. Sizes follow pysyzygos.get_asteroid_size: measured diameter (upper bound +3 sigma,
    15 % if no sigma) or, from H, albedo 0.14 nominal and 0.05 upper bound."""
    rows = []
    for r in data:
        d = dict(zip(fields, r))
        H, a, e = to_float(d["H"]), to_float(d["a"]), to_float(d["e"])
        if math.isnan(H) or not (a > 0 and 0 <= e < 0.99) or math.isnan(to_float(d["epoch"])):
            continue                                                       # no bound orbit or missing elements
        if hmax is not None and H >= hmax:
            continue
        spk = int(d["spkid"])
        D = to_float(d["diameter"])
        if D > 0:
            Dmax, est = D + 3 * to_float(d["diameter_sigma"], 0.15 * D), False
        else:
            Dp = lambda p: 1329.0 / math.sqrt(p) * 10 ** (-H / 5)
            D, Dmax, est = Dp(0.14), Dp(0.05), True
        G = to_float(d["G"])
        rows.append(dict(number=spk - 20000000 if spk >= 20000000 else spk - 2000000, spkid=spk,
                         name=(d["full_name"] or "").strip(), H=H, G=0.15 if math.isnan(G) else G, D_km=D, D_max_km=Dmax,
                         D_est=est, cc=to_float(d["condition_code"], 9.0), neo=d.get("neo") == "Y",
                         **{k: to_float(d[k]) for k in ("a", "e", "i", "om", "w", "ma", "epoch")}))
    return rows


# ---------------------------------------------------------------- screening (worker processes, own SPICE each)
_W = {}


def _init(folder, catalog_dir, cam_limit, lat, lon, ele):
    import spiceypy as spice
    from pysyzygos import screen as SC, gaia_local as L
    os.chdir(folder)
    SC.load_kernels(spice, folder)
    _W.update(spice=spice, SC=SC, index=L.open_index(catalog_dir, L.index_gmax(cam_limit)),
              site=SC.Site(spice, lat, lon, ele))


def _screen_chunk(args):
    rows, et0, et1, opt = args
    return _W["SC"].screen(_W["spice"], rows, et0, et1, _W["site"], _W["index"], opt, chunk=max(len(rows), 1)), len(rows)


BLAS_VARS = ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS",
             "NUMEXPR_NUM_THREADS")


def single_thread_workers():
    """One BLAS thread per worker process: numpy's OpenBLAS otherwise starts one thread per CPU in every worker (4
    workers on 8 cores: 32 threads, each worker's own thread got ~40 % of a CPU). Set in the parent's environment
    before the pool starts, so the spawned workers read it when they import numpy; a value the user set is kept."""
    for k in BLAS_VARS:
        os.environ.setdefault(k, "1")


def run_screen(rows, et0, et1, opt, site_args, workers, chunk=2000, mp_start="spawn"):
    """Screen rows in worker processes. Workers are started with "spawn": each loads its own SPICE kernels with its
    own file handles. With "fork" (the Linux default before Python 3.14) they would inherit the parent's open kernel
    files and share their read position, so parallel reads of de440.bsp collide (SPICE(RECORDNOTFOUND),
    SPICE(INVALIDRADIUS), corrupted DAF), more often the more workers run."""
    import multiprocessing
    from pysyzygos import gaia_local as L
    folder = HOME                                          # kernels and catalogs (workers start there)
    # build a missing bright-star index here, once: workers only open it (before, each worker built it at the same
    # time, reading the whole catalog into memory: swap and a stalled system with a star limit above G 15)
    L.open_index(site_args[0], L.index_gmax(site_args[1]))
    jobs = [(rows[i:i + chunk], et0, et1, opt) for i in range(0, len(rows), chunk)]
    events, done, t0 = [], 0, time.time()
    single_thread_workers()
    with ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context(mp_start),
                             initializer=_init, initargs=(folder, *site_args)) as ex:
        for ev, n in ex.map(_screen_chunk, jobs):
            events += ev
            done += n
            el = time.time() - t0
            print(f"  {done}/{len(rows)} asteroids, {len(events)} events, {hms(el)}, "
                  f"ETA {hms(el / done * (len(rows) - done))}", file=sys.stderr, flush=True)
    return events


# ---------------------------------------------------------------- output
def write_targets(path, best, a):
    """Write an importable module:  from targets import targets, target_names  (and pick_meta: site, window, settings)"""
    now = dt.datetime.now(dt.timezone.utc)
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"# generated by pysyzygos pick on {now:%Y-%m-%d %H:%M} UTC\n")
        f.write(f"# events {a.start} + {a.days:g} d, site {a.site or a.lat}, reach {a.reach:g} km, G <= {a.cam_limit:g}, "
                f"{a.aperture:g} cm aperture, {a.frames} frames, MagAdjust {a.mag_adjust:+g}, extinction {a.extinction:g}, "
                f"min duration {a.min_dur:g} s, min drop {a.min_drop:g}\n")
        f.write(f"# asteroids screened: {getattr(a, 'screened', '') or 'all'}\n")
        f.write(f"# order: best event first (sorted by {a.sort}); comment = that event\n\n")
        f.write("targets = [\n")
        for e in best:
            f.write(f"    {str(e['number'])!r},   # {e['name'][:28]:<28} {e['utc'][:16]}  G {e['star_mag']:5.2f}  "
                    f"drop {e['drop']:5.2f}  dur {e['dur_s']:4.2f} s  miss {e['miss_km']:5.1f} km\n")
        f.write("]\n\ntarget_names = {\n")
        for e in best:
            f.write(f"    {str(e['number'])!r}: {e['name']!r},\n")
        f.write("}\n")
        meta = dict(site=a.site, start=a.start, days=a.days, picked=f"{now:%Y-%m-%dT%H:%M:%S}", version=__version__, lat=a.lat, lon=a.lon,
                    reach_km=a.reach, cam_limit=a.cam_limit, hmax=None if a.all else a.hmax, top=a.top, sort=a.sort)
        f.write(f"\npick_meta = {meta!r}\n")


SORT_KEYS = {"mag": ["star_mag", "et"], "date": ["et"], "margin": ["mag_margin"], "drop": ["drop"]}
SORT_ASC = {"mag": True, "date": True, "margin": False, "drop": False}


def main(argv=None):
    cfg = {}
    try:
        from pysyzygos import config as C
        g = lambda k, d: getattr(C, k, d)
        cfg = dict(site=g("site_name", None), picks_dir=g("picks_dir", "picks"), lat=C.LAT, lon=C.LON, ele=C.ELE, reach=C.max_shadow_dist, min_alt=C.MIN_STAR_ALT,
                   sun=C.MAX_SUN_ALT, cache=C.cache_path, start=str(C.ct)[:10], days=C.days,
                   catalog=g("gaia_local_dir", "gaia_dr3_g16"), min_drop=g("min_mag_drop", 0.1),
                   cam_limit=g("pick_cam_limit", 15.0), aperture=g("pick_aperture_cm", 25.0),
                   mag_adjust=g("pick_mag_adjust", 0.0), extinction=g("pick_extinction", 0.0),
                   frames=g("pick_frames", 4), min_dur=g("pick_min_dur_s", 0.4), hmax=g("pick_hmax", 17.0))
    except (ImportError, AttributeError) as ex:
        print(f"note: pysyzygos_config.py not usable ({ex}); give the site on the command line", file=sys.stderr)
    c = lambda k, d=None: cfg.get(k, d)
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=f"PySyzygos {__version__}")
    ap.add_argument("--start", default=c("start"), help="UTC date YYYY-MM-DD (default: config ct, else today)")
    ap.add_argument("--days", type=float, default=c("days", 30), help="window length (default: config days)")
    ap.add_argument("--hmax", type=float, default=c("hmax", 17.0), help="asteroids with H below this (default 17)")
    ap.add_argument("--all", action="store_true", help="exhaustive: all numbered asteroids, any H (~900k, slower)")
    ap.add_argument("--lat", type=float, default=c("lat"))
    ap.add_argument("--lon", type=float, default=c("lon"), help="east-positive degrees")
    ap.add_argument("--ele", type=float, default=c("ele", 0.0), help="site height, m")
    ap.add_argument("--reach", type=float, default=c("reach", 20.0), help="km you can travel from the site (max_shadow_dist)")
    ap.add_argument("--min-alt", type=float, default=c("min_alt", 10.0), help="minimum star altitude, deg")
    ap.add_argument("--max-sun-alt", type=float, default=c("sun", 0.0), help="Sun must be below this, deg")
    ap.add_argument("--min-drop", type=float, default=c("min_drop", 0.1), help="smallest useful magnitude drop")
    ap.add_argument("--cam-limit", type=float, default=c("cam_limit", 15.0), help="faintest star, G (bright-star index)")
    ap.add_argument("--aperture", type=float, default=c("aperture", 25.0), help="telescope aperture, cm")
    ap.add_argument("--mag-adjust", type=float, default=c("mag_adjust", 0.0),
                    help="OWC MagAdjust: + for better conditions (dark sky, sensitive camera), - for worse")
    ap.add_argument("--extinction", type=float, default=c("extinction", 0.0),
                    help="atmospheric extinction, mag per airmass (0 = off, ~0.2 typical)")
    ap.add_argument("--frames", type=int, default=c("frames", 4), help="exposures the event must last (detection frames)")
    ap.add_argument("--min-dur", type=float, default=c("min_dur", 0.4), help="shortest event, s")
    ap.add_argument("--sort", choices=sorted(SORT_KEYS), default="mag", help="ranking (default: brightest star first)")
    ap.add_argument("--top", type=int, default=40, help="asteroids written to targets.py (best events first)")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) // 2), help="parallel processes")
    ap.add_argument("--mp-start", choices=("spawn", "forkserver", "fork"), default="spawn",
                    help="how worker processes start (default spawn; fork shares the parent's open SPICE kernel files "
                         "and breaks parallel reads, for diagnosis only)")
    ap.add_argument("--catalog", default=c("catalog", "gaia_dr3_g16"), help="local Gaia catalog folder")
    ap.add_argument("--sbdb-cache", help="SBDB download cache (default: <config cache_path>/PySyzygos_sbdb_cache.json)")
    ap.add_argument("--prescreen", metavar="FILE|auto",
                    help="screen only the asteroids of this pre-screen (pysyzygos prescreen build): faster, the same "
                         "events if the pre-screen covers the window and the site and its limits are as loose; "
                         "'auto': the newest fitting one in prescreen/, else all asteroids")
    ap.add_argument("-o", "--output", default="pick_events.csv")
    ap.add_argument("--targets-file", default="targets.py", help="importable targets list ('' to skip)")
    ap.add_argument("--picks-dir", default=c("picks_dir", "picks"),
                    help="also save this pick per site and window here, for later searches ('' to skip)")
    a = ap.parse_args(argv)
    if a.lat is None or a.lon is None:
        ap.error("need --lat and --lon (no pysyzygos_config.py found)")
    a.start = a.start or dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    if a.sbdb_cache is None:
        a.sbdb_cache = os.path.join(c("cache") or tempfile.gettempdir(), "PySyzygos_sbdb_cache.json")

    hmax = None if a.all else a.hmax
    T = {"start": time.time()}                          # phase timings (printed at the end)
    fields, data, fetched = fetch_sbdb(hmax, a.sbdb_cache)
    rows = build_rows(fields, data, hmax)
    T["list"] = time.time()
    N = {"list": len(rows)}                             # counts for the step summary
    import spiceypy as spice
    from pysyzygos import screen as SC
    SC.load_kernels(spice, HOME)
    T["kernels"] = time.time()
    et0 = spice.str2et(a.start + "T00:00:00")
    et1 = et0 + a.days * 86400.0
    from pysyzygos import kernels as K
    if et0 < K.pck_span(spice, os.path.join(HOME, K.EARTH_PCK))[0] and not K.historic_earth_pck(HOME):
        print("window before 2000: getting the historic Earth orientation file", file=sys.stderr)
        if not K.download_historic_earth_pck(HOME):            # the workers load it (screen.load_kernels)
            sys.exit("no Earth orientation before 2000: pysyzygos setup --historic-earth (when online)")
        spice.kclear()
        SC.load_kernels(spice, HOME)                           # again, the historic file first
    opt = dict(reach_km=a.reach, min_alt=a.min_alt, max_sun_alt=a.max_sun_alt, min_drop=a.min_drop,
               min_dur=a.min_dur, cam_limit=a.cam_limit, aperture=a.aperture, frames=a.frames,
               mag_adjust=a.mag_adjust, extinction=a.extinction)
    from pysyzygos import gaia_local as L
    sup = bool(L.use_supplement() and L.has_supplement(a.catalog))   # high-RUWE stars too: the pre-screen must have them
    if a.prescreen == "auto":                           # the newest fitting pre-screen, else the full screen
        from pysyzygos import prescreen as PS
        path, _, other = PS.best_fit(et0, et1, a.lat, a.lon, dict(opt, hmax=hmax, hmax_all=a.all, supplement=sup))
        if path is None:
            print("pre-screen: none fits this pick" + "".join(f"\n  {os.path.basename(p)}: {'; '.join(bad)}"
                                                            for p, _, bad in other)
                  + "\n  -> screening all asteroids", file=sys.stderr)
        a.prescreen = path
    if a.prescreen:                                     # only the asteroids with events in the pre-screen
        from pysyzygos import prescreen as PS
        meta = PS.read_meta(a.prescreen)
        bad = PS.check(meta, et0, et1, a.lat, a.lon, dict(opt, hmax=hmax, hmax_all=a.all, supplement=sup))
        if bad:
            print(f"pre-screen {a.prescreen} does not fit this pick: " + "; ".join(bad) +
                  ". Build a fitting one (pysyzygos prescreen build) or pick without --prescreen.", file=sys.stderr)
            return 2
        if PS.is_global(a.prescreen):                   # whole Earth: the site test on the stored shadow elements
            t_q = time.time()
            keep, n_win, n_tested = PS.site_numbers(a.prescreen, spice, et0, et1, a.lat, a.lon, a.ele, opt)
            how = (f"site test of {n_tested} of {n_win} events (G <= {a.cam_limit:g}, reach {a.reach:g} km"
                   + (", index" if PS.has_index(a.prescreen) else "; no index: pysyzygos prescreen index FILE")
                   + f") in {time.time() - t_q:.1f} s")
        else:
            keep = PS.numbers(a.prescreen, et0, et1, a.cam_limit)
            how = f"events in the window with a star G <= {a.cam_limit:g}"
        n_all = len(rows)
        rows = [r for r in rows if int(r["number"]) in keep]
        print(f"pre-screen {PS.describe(a.prescreen, meta)}: {len(rows)} of {n_all} asteroids ({how})", file=sys.stderr)
        a.screened = f"{len(rows)} of {n_all} (pre-screen {os.path.basename(a.prescreen)})"
    T["select"] = time.time()
    N["screened"] = len(rows)
    a.site = c("site") if (a.lat, a.lon) == (c("lat"), c("lon")) else None
    print(f"{len(rows)} asteroids, {a.start} + {a.days:g} d, site {a.site or ''} {a.lat:.4f} {a.lon:.4f}, reach {a.reach:g} km, "
          f"G <= {a.cam_limit:g}, {a.workers} workers", file=sys.stderr)
    t0 = time.time()
    ev = run_screen(rows, et0, et1, opt, (a.catalog, a.cam_limit, a.lat, a.lon, a.ele), a.workers, mp_start=a.mp_start)
    print(f"screened in {time.time() - t0:.0f} s: {len(ev)} events", file=sys.stderr)
    T["screen"] = time.time()
    N["events"] = len(ev)

    E = pd.DataFrame(ev)
    if E.empty:
        print("no events found")
        print_timing(T, a.prescreen, N)
        return 0
    E["utc"] = [spice.et2utc(x, "ISOC", 0) for x in E.et]
    E = E.sort_values(SORT_KEYS[a.sort], ascending=SORT_ASC[a.sort]).reset_index(drop=True)
    cols = ["number", "name", "H", "utc", "star", "star_mag", "drop", "dur_s", "dur_max_s", "mag_margin",
            "miss_km", "inside", "star_alt", "sun_alt", "m_ast", "D_km", "D_est", "speed_kms", "cc", "star_ra",
            "star_dec", "et", "star_kind", "star_ruwe"]                # supplement star (gaia_local): at the end
    for col in ("star_kind", "star_ruwe"):
        if col not in E:
            E[col] = 0 if col == "star_kind" else float("nan")
    E[cols].to_csv(a.output, index=False, float_format="%.6g")
    print(f"{'#':>7} {'name':<26} {'UT':<19} {'G':>5} {'drop':>5} {'dur':>5}  {'marg':>5} {'miss':>6} {'alt':>4}")
    for e in E.head(max(a.top, 20)).itertuples():
        print(f"{e.number:>7} {e.name[:26]:<26} {e.utc[:19]:<19} {e.star_mag:5.2f} {e.drop:5.2f} "
              f"{e.dur_s:5.2f}{'~' if e.D_est else ' '}{e.mag_margin:6.2f} {e.miss_km:6.1f} {e.star_alt:4.0f}")
    best = E.drop_duplicates("number").head(a.top).to_dict("records")
    if a.targets_file:
        write_targets(a.targets_file, best, a)
    saved = None
    if a.picks_dir and a.site:                          # kept per site and window: search.py reuses it
        from pysyzygos import picks
        os.makedirs(a.picks_dir, exist_ok=True)
        saved, saved_csv = picks.paths(a.site, a.start, a.days, a.picks_dir)
        write_targets(saved, best, a)
        E[cols].to_csv(saved_csv, index=False, float_format="%.6g")
    raw = {int(r[fields.index("spkid")]): dict(zip(fields, r)) for r in data}
    n_put = sbdb.put({str(e["number"]): sbdb.entry_from_bulk(raw[int(e["spkid"])], fetched)
                               for e in best if int(e["spkid"]) in raw}, c("cache"))
    print(f"\nall events: {a.output}   (~ = diameter from H; dur is nominal, detection uses the upper size bound;\n"
          f"marg = magnitudes below the OWC observability limit)")
    if a.targets_file:
        print(f"targets of the best {len(best)} events: {a.targets_file}   ->   from targets import targets")
    if saved:
        print(f"saved for site {a.site}, {a.start} + {a.days:g} d: {saved} (+ .csv); searches of this site and window use it")
    print(f"size data of {n_put} targets -> {sbdb.cache_file(c('cache'))}", file=sys.stderr)
    N["targets"] = len(best)
    print_timing(T, a.prescreen, N)
    return 0


def print_timing(T, prescreen, N=None):
    """One line: where the pick's time went (start-up = Python and imports, from when the command started), and the
    step summary (steps.py: a table, and the line the GUI shows as the run summary). N: counts per step."""
    T["output"] = time.time()
    t0 = float(os.environ.get("PYSYZYGOS_T0") or T["start"])
    d = lambda a, b: T[b] - T[a]
    print(f"timing: total {T['output'] - t0:.1f} s = start-up {T['start'] - t0:.1f} + asteroid list "
          f"{d('start', 'list'):.1f} + kernels {d('list', 'kernels'):.1f} + "
          f"{'pre-screen' if prescreen else 'asteroid choice'} {d('kernels', 'select'):.1f} + screen (workers incl.) "
          f"{d('select', 'screen'):.1f} + output {d('screen', 'output'):.1f} s", file=sys.stderr)
    from pysyzygos.steps import Steps
    N, S = N or {}, Steps("pick")
    S.t0 = t0
    S.add("start-up (Python, modules)", T["start"] - t0)
    S.add("asteroid list (JPL SBDB)", d("start", "list"), N.get("list"), "asteroids")
    S.add("kernels (SPICE)", d("list", "kernels"))
    S.add("pre-screen site test" if prescreen else "asteroid choice", d("kernels", "select"), N.get("screened"),
          "asteroids kept")
    if "screen" in T:
        S.add("screen (workers)", d("select", "screen"), N.get("events"), "events")
        S.add("output (tables, targets)", d("screen", "output"), N.get("targets"), "targets")
    if prescreen:
        S.info["prescreen"] = os.path.basename(str(prescreen))
    S.emit()


if __name__ == "__main__":
    sys.exit(main())
