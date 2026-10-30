"""prescreen.py - a pre-screened target list for the pick: every asteroid that has at least one possible occultation in a
region (or anywhere on the Earth) during a window, built once (e.g. per month) and used by any pick of a site in that
region: `pysyzygos pick --prescreen FILE` screens only those asteroids instead of all, otherwise unchanged.

    pysyzygos prescreen build --start 2026-11-01 --days 30 --region 35,60,-130,-60    # lat min,max, lon min,max (deg)
    pysyzygos prescreen build --start 2026-11-01 --days 30 --around-site 500          # a box 500 km around the site
    pysyzygos prescreen build --start 2026-11-01 --days 30 --around-sites 300         # one box around all your sites
    pysyzygos prescreen build --start 2026-11-01 --days 30 --global
    pysyzygos prescreen list                                                          # the built ones
    pysyzygos prescreen show prescreen/<name>.db
    pysyzygos prescreen extract prescreen/<global>.global.npy --region usa            # a region cut from a global one
    pysyzygos prescreen extract prescreen/<global>.global.npy --region 35,60,-10,30 --cam-limit 14
    pysyzygos prescreen query prescreen/<global>.global.npy                           # asteroids for the site
    pysyzygos prescreen remote                                                        # shared ones on the mirror
    pysyzygos prescreen fetch [name|latest]                                           # download one into prescreen/
    pysyzygos prescreen publish prescreen/<global>.global.npy   # maintainers: to release/world-prescreens/ (mirror)

Whole Earth (--global): instead of testing a region, the build stores per event the shadow's motion across the
fundamental plane (star direction, a quadratic in time, its misfit; ~80 bytes, see shadowtrack.py), sorted by time in
<name>.global.npy (+ .json). From it, any site is tested in seconds (pick --prescreen, auto included; query) and any
region cut out (extract: a small region file for picks there, or to share). The build costs about the same as a region
build (the region test was never the expensive part); size ~29 events per asteroid per 20 days at G 16 (~1 GB for
465k asteroids), ~1/13 of that at G 13.2.

Memory and progress: the asteroids go to the worker processes in chunks sized from the free memory (a chunk's numpy
arrays take ~12 x 3 x 8 bytes per asteroid and 10-min time step: 0.29 MB for 7 days, 1.2 MB for 30 days); --max-mem
GB or --mem-frac set the budget, --chunk a fixed size. Fewer workers are used if the budget is too small for them;
chunks shrink when the free memory runs low. After every chunk the events so far are saved in <output>.partial; after
a crash or Ctrl-C the same command resumes there (--fresh starts over).

How (the pick's own parts: SBDB elements, orbits integrated with the planets, the bright-star index, the candidate
scan), but for the whole Earth instead of one site:
  1. per asteroid, the stars (G <= cam_limit, and bright enough for a drop >= min_drop) within Earth radius + its
     radius + reach of its geocentric path: every star whose shadow can touch the Earth;
  2. per candidate, the ground track of the shadow axis (sampled, the Earth's rotation from SPICE every 10 min and
     the spin in between); kept if any sample lies in the region (+ shadow radius + reach) with the star above
     min_alt and the Sun below max_sun_alt there (a region build) - a global build keeps all candidates;
  3. stored in SQLite: the events (asteroid, star, time, geocentric miss, a ground point) and the build settings.
Region: a latitude/longitude box, not a circle. --around-site KM: +-KM/111.2 deg of latitude, +-KM/(111.2 cos(site
lat)) deg of longitude (exactly KM along the site's meridian and parallel; the poleward edge is a little narrower in km,
the equatorward edge wider). --around-sites KM: the box of all sites plus KM, longitude width taken at the poleward
edge (at least KM everywhere), the short way round across the date line. A candidate is kept if its ground track
touches the box widened by its radius + reach (per latitude), so the effective region is the box + 200 km or more.
All limits are loose on purpose (a superset): the pick then applies its exact site screen, so with a pre-screen built
with limits at least as loose as the pick's, it finds the same events, only faster. The orbits are those of the build
date: rebuild after a month or so (orbit updates of poorly known asteroids), as the search uses the current JPL
Horizons orbit for the final prediction anyway.
"""
from pysyzygos.version import __version__
import argparse, glob, json, math, os, sqlite3, sys, tempfile, time
import numpy as np
from pysyzygos import shadowtrack as ST

DIR = "prescreen"


def L_replace(src, dst):
    """Rename a finished file into place, retried on Windows' "file in use" (gaia_local.replace_file)."""
    from pysyzygos.gaia_local import replace_file
    replace_file(src, dst)
FORMAT = 3                                   # 3: padded grid, 161-sample tracks, plane reach -> ground (ground_reach)
HALF_MAX_S = 6 * 3600.0                      # an event's track: at most +-6 h around its Earth-centre time
PAD_S = 2 * HALF_MAX_S                       # the build's time grid reaches this far beyond the window


# ---------------------------------------------------------------- region
def region_box(lat_min, lat_max, lon_min, lon_max):
    if not (-90 <= lat_min < lat_max <= 90):
        raise ValueError("region: need lat_min < lat_max within -90..90")
    return dict(lat_min=float(lat_min), lat_max=float(lat_max), lon_min=float(lon_min), lon_max=float(lon_max))


# named regions (lat min, lat max, lon min, lon max; deg, lon east-positive): --region NAME
REGIONS = {
    "usa": (24.0, 50.0, -125.0, -66.0),                  # contiguous United States
    "north-america": (7.0, 72.0, -170.0, -50.0),
    "central-america": (7.0, 33.0, -118.0, -59.0),
    "south-america": (-56.0, 13.0, -82.0, -34.0),
    "europe": (34.0, 72.0, -25.0, 45.0),
    "africa": (-35.0, 38.0, -18.0, 52.0),
    "middle-east": (12.0, 42.0, 25.0, 63.0),
    "east-asia": (18.0, 54.0, 73.0, 146.0),
    "japan": (24.0, 46.0, 122.0, 146.0),
    "australia": (-44.0, -10.0, 112.0, 154.0),
    "new-zealand": (-48.0, -34.0, 166.0, 179.0),
}


def parse_region(text):
    """A region box from a name of REGIONS or 'lat_min,lat_max,lon_min,lon_max'."""
    key = str(text).strip().lower()
    if key in REGIONS:
        return region_box(*REGIONS[key])
    try:
        return region_box(*[float(x) for x in key.split(",")])
    except (TypeError, ValueError):
        raise ValueError(f"region {text!r}: a name ({', '.join(REGIONS)}) or lat_min,lat_max,lon_min,lon_max")


def box_around(lat, lon, km):
    """A lat/lon box reaching km from (lat, lon) in every direction."""
    dlat = km / 111.2
    dlon = min(km / (111.2 * max(math.cos(math.radians(lat)), 0.02)), 180.0)
    return region_box(max(lat - dlat, -90.0), min(lat + dlat, 90.0), lon - dlon, lon + dlon)


def box_around_all(points, km):
    """A lat/lon box reaching km from every (lat, lon) point (e.g. all sites of sites.py): one pre-screen for them all.
    Longitudes: the shortest arc holding all points (across the date line if that is shorter)."""
    pts = [(float(a), float(b)) for a, b in points]
    if not pts:
        raise ValueError("no points")
    lons = sorted(((b + 180.0) % 360.0) - 180.0 for _, b in pts)
    gaps = [(lons[(i + 1) % len(lons)] - lons[i]) % 360.0 or (360.0 if len(lons) == 1 else 0.0) for i in range(len(lons))]
    i = max(range(len(lons)), key=lambda k: gaps[k])                # the widest gap is outside the box
    west, east = lons[(i + 1) % len(lons)], lons[i]
    lat_lo, lat_hi = min(a for a, _ in pts), max(a for a, _ in pts)
    dlat = km / 111.2
    edge = min(max(abs(lat_lo - dlat), abs(lat_hi + dlat)), 89.9)    # the narrowest degree of longitude in the box
    cos_min = max(math.cos(math.radians(edge)), 0.02)
    dlon = km / (111.2 * cos_min)
    w, e = west - dlon, east + dlon
    if (e - w) % 360.0 >= 360.0 - 1e-9 or (east - west) % 360.0 + 2 * dlon >= 360.0:
        w, e = -180.0, 180.0
    else:
        w, e = ((w + 180.0) % 360.0) - 180.0, ((e + 180.0) % 360.0) - 180.0
    return region_box(max(lat_lo - dlat, -90.0), min(lat_hi + dlat, 90.0), w, e)


in_box = ST.in_box


def contains(meta, lat, lon):
    """Is the site inside the pre-screen's region (or is it global)?"""
    box = meta.get("region")
    if not box:
        return True
    return bool(in_box(np.array([lat]), np.array([lon]), box, 0.0)[0])


# ---------------------------------------------------------------- the build (worker processes, own SPICE each)
_W = {}


def _init(folder, catalog_dir, cam_limit):
    import spiceypy as spice
    from pysyzygos import screen as SC, gaia_local as L
    os.chdir(folder)
    SC.load_kernels(spice, folder)
    _W.update(spice=spice, index=L.open_index(catalog_dir, L.index_gmax(cam_limit)))


# Math: CO.1-CO.3, PS.1 (slides CO, PS): the world pre-screen, a corridor for the whole Earth and
# the shadow elements per event.
def build_chunk(spice, rows, et0, et1, index, opt, step_s=600.0, n_track=ST.N_TRACK):
    """The pre-screen events of these asteroids (pick.build_rows dicts). opt: cam_limit, min_drop, reach_km,
    max_sun_alt, min_alt, region (box dict, or None = global). A region build returns a list of event tuples (the
    events table), a global build a ST.DTYPE array (the shadow elements of every event that falls on the Earth in
    the dark with the star up somewhere)."""
    import pandas as pd
    from pysyzygos import orbits as O, screen as SC
    from pysyzygos.corridor import find_candidates, propagate_linear, pad_for_pm, _unit, EARTH_R_KM, GAIA_EPOCH_YEAR
    # the grid reaches PAD_S beyond the window: an event's track can start or end up to HALF_MAX_S from its
    # Earth-centre time, and the shadow elements need the orbit on both sides of it
    ets = np.arange(et0 - PAD_S, et1 + PAD_S + step_s, step_s)
    sun = np.asarray(spice.spkpos("SUN", ets, "J2000", "LT+S", "EARTH")[0])
    fr = dict(ets=ets, step=step_s, sun_u=sun / np.linalg.norm(sun, axis=1, keepdims=True),
              rot=np.array([spice.pxform("J2000", "ITRF93", float(t)) for t in ets]))      # (T,3,3)
    sun_bary = np.asarray(spice.spkpos("SUN", ets, "J2000", "NONE", "0")[0]) / O.AU_KM
    pad = pad_for_pm(1500.0, ets)
    years = 2000.0 + ets.mean() / (365.25 * 86400.0) - GAIA_EPOCH_YEAR
    dm_drop = SC.drop_cut(opt["min_drop"]) if opt["min_drop"] > 0 else 99.0
    box = opt.get("region")
    sin_alt, sin_sun = math.sin(math.radians(opt["min_alt"])), math.sin(math.radians(opt["max_sun_alt"]))
    el = {k: np.array([r[k] for r in rows], float) for k in ("a", "e", "i", "om", "w", "ma", "epoch")}
    r_b, v_b = O.propagate(spice, el, ets)
    g = O.astrometric(spice, r_b, v_b, ets)                                           # (n,T,3) km
    delta = np.linalg.norm(g, axis=2)
    U = g / delta[..., None]
    helio = r_b - sun_bary[None]
    rh = np.linalg.norm(helio, axis=2)
    cos_ph = np.sum(helio * g, 2) / (rh * delta)
    speed = np.zeros_like(delta)
    speed[:, 1:] = np.linalg.norm(np.diff(U, axis=1), axis=2) / step_s * delta[:, 1:]
    speed[:, 0] = speed[:, 1]
    out, elems = [], []
    for k, row in enumerate(rows):
        m_ast = SC.hg_mag(row["H"], row["G"], rh[k], delta[k] / O.AU_KM, cos_ph[k])
        cap = min(opt["cam_limit"], float(m_ast.max()) + dm_drop)
        r_max = row["D_max_km"] / 2
        margin = EARTH_R_KM + r_max + opt["reach_km"]
        w = np.degrees(margin / delta[k]) + pad / 3600.0
        stars = index.near_path(U[k], w, cap)
        if len(stars) == 0:
            continue
        sdf = pd.DataFrame({c: stars[c].astype(float) for c in ("ra", "dec", "pmra", "pmdec", "phot_g_mean_mag")})
        sdf["source_id"] = stars["source_id"]
        cands = find_candidates(sdf, dict(ets=ets, u=U[k], delta_km=delta[k], step_s=step_s), margin,
                                block_cells=SCAN_CELLS)
        if len(cands) == 0:
            continue
        tc = cands.et_guess.to_numpy()
        js = cands.j.to_numpy()
        half = np.minimum(1.3 * margin / np.maximum(speed[k][js], 0.3), HALF_MAX_S)
        inwin = (tc + half >= et0) & (tc - half <= et1)                             # the track touches the window
        if not inwin.any():
            continue
        cands, tc, js, half = cands[inwin], tc[inwin], js[inwin], half[inwin]
        ra, de = propagate_linear(sdf.iloc[cands.star.to_numpy()], years)
        sdir = _unit(ra, de)                                                         # (c,3)
        stars_i = cands.star.to_numpy()
        for b0 in range(0, len(tc), CAND_BLOCK):                                     # bounded memory per block
            sl = slice(b0, b0 + CAND_BLOCK)
            tau = ST.sample_times(tc[sl], half[sl], n_track)
            gs = ST.interp(g[k], ets, tau)                                           # (c,s,3)
            ex, ny = ST.plane(sdir[sl])
            px, py = np.einsum("csx,cx->cs", gs, ex), np.einsum("csx,cx->cs", gs, ny)
            keep, where = ST.ground_track(px, py, tau, sdir[sl], fr, r_max, box, opt["reach_km"], sin_alt, sin_sun)
            idx = np.where(keep)[0]
            if not len(idx):
                continue
            if box is not None:
                for q in idx:
                    i = b0 + q
                    out.append((int(row["number"]), int(sdf.source_id.iloc[stars_i[i]]), float(tc[i]),
                                float(sdf.phot_g_mean_mag.iloc[stars_i[i]]), float(m_ast[js[i]]),
                                float(cands.d_km.iloc[i]), *[None if not np.isfinite(x) else float(x) for x in where[q]]))
                continue
            step9 = (n_track - 1) // 8                                               # the 9 fit points among the samples
            f = ST.fit(px[idx][:, ::step9], py[idx][:, ::step9], half[sl][idx])
            e = np.zeros(len(idx), ST.DTYPE)
            i = b0 + idx
            e["number"] = int(row["number"])
            e["star"] = sdf.source_id.to_numpy()[stars_i[i]]
            e["et"], e["g"] = tc[i], sdf.phot_g_mean_mag.to_numpy()[stars_i[i]]
            e["m_ast"], e["geo_miss"] = m_ast[js[i]], cands.d_km.to_numpy()[i]
            e["sx"], e["sy"], e["sz"] = sdir[i, 0], sdir[i, 1], sdir[i, 2]
            for key in ("x0", "y0", "vx", "vy", "ax", "ay", "err"):
                e[key] = f[key]
            e["half"], e["r_km"] = half[i], r_max
            elems.append(e)
    if box is None:
        return np.concatenate(elems) if elems else np.zeros(0, ST.DTYPE)
    return out


SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS events (number INTEGER, star INTEGER, et REAL, g REAL, m_ast REAL, geo_miss_km REAL,
    lat REAL, lon REAL, sun_alt REAL, star_alt REAL);
CREATE INDEX IF NOT EXISTS events_number ON events (number);
CREATE INDEX IF NOT EXISTS events_et ON events (et);
"""


# ---------------------------------------------------------------- memory: the chunk plan
CAND_BLOCK = 1024                 # candidates per ground-track block (161 samples: ~60 MB transient)
SCAN_CELLS = 4e6                  # stars x time steps per candidate-scan block (~30 B each: ~120 MB; corridor's 2.5e7: 730 MB)
BYTES_PER_STEP = 12 * 3 * 8       # per asteroid and time step: the (n,T,3) float64 arrays of a chunk (measured ~10)
CHUNK_FIXED = 120e6               # per chunk on top: one scan block, star lists, one ground-track block (measured ~60 MB)
WORKER_BASE = 600e6               # a worker before its first chunk: Python, numpy/pandas, SPICE kernels, index offsets
MIN_CHUNK, MAX_CHUNK = 100, 2000  # MAX_CHUNK also sets how often progress is saved


def _meminfo():
    """{name: bytes} of /proc/meminfo (Linux), else {}."""
    try:
        with open("/proc/meminfo") as f:
            return {k: int(v.split()[0]) * 1024 for k, v in (ln.split(":", 1) for ln in f) if v.split()}
    except (OSError, ValueError):
        return {}


def mem_status():
    """(available, total, swap used) in bytes; None where the system does not tell (non-Linux: available = half of
    the physical memory)."""
    m = _meminfo()
    if m:
        return m.get("MemAvailable"), m.get("MemTotal"), m.get("SwapTotal", 0) - m.get("SwapFree", 0)
    total = None
    try:
        total = os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
    except (ValueError, OSError, AttributeError):
        pass
    if total is None and sys.platform == "win32":
        import ctypes

        class MS(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong)] + \
                       [(n, ctypes.c_ulonglong) for n in ("tot", "avail", "tpf", "apf", "tv", "av", "aev")]
        ms = MS()
        ms.dwLength = ctypes.sizeof(MS)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms)):
            return ms.avail, ms.tot, None
    return (total // 2 if total else None), total, None


def peak_rss():
    """Peak resident memory of this process (bytes), None if unknown."""
    try:
        import resource
        r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return r if sys.platform == "darwin" else r * 1024
    except (ImportError, OSError):
        return None


def rss_anon():
    """Resident memory of this process that is not file-backed (bytes; Linux), None if unknown: the worker's own
    arrays, without the pages of the memory-mapped star index (counted in peak_rss, but the system can drop them)."""
    try:
        with open("/proc/self/status") as f:
            for ln in f:
                if ln.startswith("RssAnon:"):
                    return int(ln.split()[1]) * 1024
    except (OSError, ValueError):
        pass
    return None


def chunk_bytes(n, steps):
    """Estimated peak of one chunk of n asteroids over this many time steps (numpy arrays of build_chunk)."""
    return n * steps * BYTES_PER_STEP + CHUNK_FIXED


def plan_chunks(n_rows, steps, workers, budget):
    """(workers, chunk): the largest chunk (<= MAX_CHUNK) that keeps workers x (base + chunk) within budget bytes;
    fewer workers if even MIN_CHUNK does not fit; at least ~4 chunks per worker for an even load."""
    per_ast = steps * BYTES_PER_STEP
    w = max(1, workers)
    while True:
        chunk = int((budget / w - WORKER_BASE - CHUNK_FIXED) // per_ast)
        if chunk >= MIN_CHUNK or w == 1:
            break
        w -= 1
    chunk = max(MIN_CHUNK, min(chunk, MAX_CHUNK, -(-n_rows // (4 * w)) if n_rows else MAX_CHUNK))
    return w, chunk


def _gb(x):
    return "?" if x is None else f"{x / 1e9:.1f} GB"


def _hms(s):
    s = int(max(s, 0))
    return f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}"


def _chunk_job(args):
    rows, et0, et1, opt = args
    t = time.time()
    ev = build_chunk(_W["spice"], rows, et0, et1, _W["index"], opt)
    return ev, [int(r["number"]) for r in rows], peak_rss(), rss_anon(), time.time() - t


# ---------------------------------------------------------------- the build driver (checkpointed)
def _settings(start, days, region, cam_limit, hmax, min_drop, reach_km, max_sun_alt, min_alt, catalog):
    return dict(start=start, days=days, region=region, cam_limit=cam_limit, hmax=hmax, min_drop=min_drop,
                reach_km=reach_km, max_sun_alt=max_sun_alt, min_alt=min_alt, catalog=os.path.basename(str(catalog)),
                format=FORMAT)


EDGE_KM = 200.0          # default build reach; for a whole-Earth pre-screen the margin beyond the Earth's edge (check)


def open_partial(path, settings, fresh=False):
    """The progress file of a build (SQLite: events so far, done asteroid numbers, the settings). An existing one
    with the same settings is resumed; with other settings it is refused unless fresh (then it starts over)."""
    if fresh and os.path.exists(path):
        os.remove(path)
    con = sqlite3.connect(path)
    con.executescript(SCHEMA + "CREATE TABLE IF NOT EXISTS done (number INTEGER PRIMARY KEY);"
                      "CREATE TABLE IF NOT EXISTS chunks (n INTEGER, data BLOB);")
    row = con.execute("SELECT value FROM meta WHERE key = 'settings'").fetchone()
    if row is None:
        con.execute("INSERT INTO meta VALUES ('settings', ?)", (json.dumps(settings),))
        con.commit()
    elif json.loads(row[0]) != json.loads(json.dumps(settings)):
        con.close()
        old = json.loads(row[0])
        if old.get("format") != settings.get("format"):
            raise RuntimeError(f"{path} is a partial build of an older format ({old.get('format')}; now "
                               f"{settings.get('format')}: improved selection), so it cannot be resumed: start over "
                               f"with --fresh (GUI: 'Start over')")
        raise RuntimeError(f"{path} is a partial build with other settings ({row[0]}); "
                           f"use --fresh to discard it (GUI: 'Start over'), or rerun with those settings to resume it")
    return con


def build(start, days, region, cam_limit=16.0, hmax=17.0, min_drop=0.1, reach_km=EDGE_KM, max_sun_alt=0.0,
          min_alt=0.0, workers=4, out=None, catalog=None, sbdb_cache=None, name=None, chunk=None, mp_start="spawn",
          max_mem=None, mem_frac=0.6, fresh=False, selection=None):
    """Build a pre-screen and write it to out (SQLite). selection (picks.selection: asteroid groups, a range, as the
    pick's) restricts it to those asteroids: a much smaller file, used only by picks inside that selection (check). Progress is saved after every chunk in out + '.partial'; a
    rerun with the same settings resumes there. Chunk size and workers follow the free memory (max_mem bytes or
    mem_frac of the available memory) unless chunk is given. Returns (path, n_events, n_asteroids)."""
    import gc, multiprocessing
    from concurrent.futures import ProcessPoolExecutor, FIRST_COMPLETED, wait
    import spiceypy as spice
    from pysyzygos.home import HOME
    from pysyzygos import pick as P, screen as SC, gaia_local as L
    say = lambda *a: print(*a, file=sys.stderr, flush=True)
    from pysyzygos.steps import Steps
    S, t_s = Steps("pre-screen build"), time.time()
    fields, data, fetched = P.fetch_sbdb(hmax, sbdb_cache or os.path.join(tempfile.gettempdir(), "PySyzygos_sbdb_cache.json"))
    rows = P.build_rows(fields, data, hmax)
    del fields, data
    gc.collect()
    from pysyzygos import picks as PK
    sel = PK.selection(**(selection or {}))
    if PK.restricted(sel):                                       # only these asteroids, as the pick's filter
        n_all = len(rows)
        rows = PK.select_rows(rows, sel)
        say(f"asteroid selection {PK.selection_text(sel)}: {len(rows)} of {n_all} asteroids")
    SC.load_kernels(spice, HOME)
    et0 = spice.str2et(f"{start}T00:00:00")
    et1 = et0 + days * 86400.0
    opt = dict(cam_limit=cam_limit, min_drop=min_drop, reach_km=reach_km, max_sun_alt=max_sun_alt, min_alt=min_alt,
               region=region)
    S.add("asteroid list (JPL SBDB), kernels", time.time() - t_s, len(rows), "asteroids")
    with S.step("star index (catalog)"):
        L.open_index(catalog, L.index_gmax(cam_limit))              # build missing indexes here, once
    supplement = bool(L.use_supplement() and L.has_supplement(catalog))
    name = name or ("global" if region is None else "region") + (f"-{PK.selection_tag(sel)}" if PK.restricted(sel) else "")
    out = out or os.path.join(DIR, f"{name}__{start}_{days:g}d_G{cam_limit:g}" + (".global.npy" if region is None
                                                                                  else ".db"))
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    partial = out + ".partial"
    settings = dict(_settings(start, days, region, cam_limit, hmax, min_drop, reach_km, max_sun_alt, min_alt, catalog),
                    supplement=supplement, **({"selection": sel} if PK.restricted(sel) else {}))
    con = open_partial(partial, settings, fresh)
    done_nums = {r[0] for r in con.execute("SELECT number FROM done")}
    n_events = con.execute("SELECT COUNT(*) FROM events").fetchone()[0] + \
        (con.execute("SELECT SUM(n) FROM chunks").fetchone()[0] or 0)
    todo = [r for r in rows if int(r["number"]) not in done_nums]
    say(f"pre-screen {name}: {len(rows)} asteroids, {start} + {days:g} d, G <= {cam_limit:g}, reach {reach_km:g} km, "
        f"region {region or 'whole Earth (shadow elements of every event, ' + str(ST.DTYPE.itemsize) + ' B each)'}")
    if done_nums:
        say(f"  resuming {partial}: {len(done_nums)} asteroids done, {n_events} events so far, {len(todo)} to go")

    # the chunk plan from the memory model and the free memory
    steps = int(round((et1 - et0 + 2 * PAD_S) / 600.0)) + 1
    avail, total, swap = mem_status()
    budget = max_mem if max_mem else (avail * mem_frac if avail else 4e9)
    if chunk:
        w = workers
    else:
        w, chunk = plan_chunks(len(todo), steps, workers, budget)
    say(f"  memory: available {_gb(avail)} of {_gb(total)}, swap used {_gb(swap)}, this process {_gb(peak_rss())}; "
        f"budget {_gb(budget)} ({'--max-mem' if max_mem else f'{mem_frac:.0%} of available'})")
    say(f"  numpy per asteroid: {steps} time steps x {BYTES_PER_STEP} B = {steps * BYTES_PER_STEP / 1e6:.2f} MB; "
        f"chunk {chunk} -> ~{_gb(chunk_bytes(chunk, steps))} + worker base ~{_gb(WORKER_BASE)}")
    say(f"  plan: {w} worker(s){f' (of {workers} asked, memory)' if w < workers else ''} x chunk {chunk} "
        f"= ~{_gb(w * (WORKER_BASE + chunk_bytes(chunk, steps)))} peak, "
        f"{-(-len(todo) // chunk) if todo else 0} chunks, progress saved after each")

    import signal

    def _term(*_):
        raise KeyboardInterrupt("terminated")
    try:
        signal.signal(signal.SIGTERM, _term)                     # GUI Stop: save and stop like Ctrl-C
    except ValueError:                                           # not the main thread
        pass
    t0, n_done = time.time(), 0
    pos, pending, wpeak, wbase = 0, {}, 0, 0
    P.single_thread_workers()
    ex = ProcessPoolExecutor(max_workers=w, mp_context=multiprocessing.get_context(mp_start),
                             initializer=_init, initargs=(HOME, catalog, cam_limit))
    try:
        while pos < len(todo) or pending:
            # keep w + 1 chunks in flight; smaller chunks, or a pause, when the free memory runs low
            while pos < len(todo) and len(pending) < w + 1:
                a_now = mem_status()[0]
                if a_now is not None and a_now < 2 * chunk_bytes(chunk, steps) and chunk > MIN_CHUNK:
                    chunk = max(MIN_CHUNK, chunk // 2)
                    say(f"  low memory ({_gb(a_now)} available): chunk now {chunk}")
                if a_now is not None and a_now < chunk_bytes(chunk, steps) and pending:
                    break                                                     # wait for a running chunk first
                job = todo[pos:pos + chunk]
                pending[ex.submit(_chunk_job, (job, et0, et1, opt))] = len(job)
                pos += len(job)
            fin, _ = wait(list(pending), return_when=FIRST_COMPLETED)
            for f in fin:
                pending.pop(f)
                ev, nums, wp, wa, dt = f.result()
                with con:
                    if region is None:
                        con.execute("INSERT INTO chunks VALUES (?, ?)", (len(ev), ev.tobytes()))
                    else:
                        con.executemany("INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?,?)", ev)
                    con.executemany("INSERT OR IGNORE INTO done VALUES (?)", [(x,) for x in nums])
                n_done += len(nums)
                n_events += len(ev)
                wpeak, wbase = max(wpeak, wp or 0), max(wbase, wa or 0)
                el = time.time() - t0
                rate = n_done / el
                a_now, _, sw = mem_status()
                say(f"  {len(done_nums) + n_done}/{len(rows)} asteroids ({(len(done_nums) + n_done) / len(rows):.1%}), "
                    f"{n_events} events | chunk {len(nums)} in {dt:.0f} s, {rate:.0f} ast/s, elapsed {_hms(el)}, "
                    f"ETA {_hms((len(todo) - n_done) / rate)} | mem available {_gb(a_now)}, swap used {_gb(sw)}, "
                    f"worker peak RSS {_gb(wpeak)} (incl. mapped index pages), own after chunk {_gb(wbase or None)}; "
                    f"est chunk ~{_gb(chunk_bytes(len(nums), steps))}")
    except BaseException as e:
        try:
            signal.signal(signal.SIGTERM, signal.SIG_IGN)          # a second Stop must not break the cleanup
        except ValueError:
            pass
        procs = list((getattr(ex, "_processes", None) or {}).values())
        ex.shutdown(wait=False, cancel_futures=True)
        for p in procs:                                            # running chunks are lost anyway: end them now,
            if p.is_alive():                                       # not after minutes (and never leave orphans that
                p.terminate()                                      # hold the GUI's output pipe open)
        for p in procs:
            p.join(5)
        con.close()
        say(f"pre-screen stopped ({type(e).__name__}: {e}); {len(done_nums) + n_done} of {len(rows)} asteroids saved in "
            f"{partial} - rerun the same command to resume")
        raise
    ex.shutdown()
    S.add("screen (workers)", time.time() - t0, n_done, "asteroids this run")
    t_w = time.time()
    meta = dict(name=name, start=start, days=days, et0=et0, et1=et1, region=region, cam_limit=cam_limit,
                hmax=hmax, min_drop=min_drop, reach_km=reach_km, max_sun_alt=max_sun_alt, min_alt=min_alt,
                asteroids_screened=len(rows), sbdb_fetched=fetched, built=time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
                build_s=round(time.time() - t0), catalog=os.path.basename(str(catalog)), version=__version__,
                resumed=bool(done_nums), supplement=supplement, workers=w, **sel)
    if region is None:
        n_ev, n_ast = _write_global(con, out, meta)
        con.close()
        os.remove(partial)
        S.add("write", time.time() - t_w, n_ev, "events")
        say(f"  indexing (a lat/lon box per track, for fast site and region queries) ...")
        with S.step("index (lat/lon box per track)", n_ev, "events"):
            index(out, w)
    else:
        with con:
            con.execute("DELETE FROM meta")
            con.executemany("INSERT INTO meta VALUES (?, ?)", [(k, json.dumps(v)) for k, v in meta.items()])
            con.execute("DROP TABLE done")
            con.execute("DROP TABLE chunks")
        con.execute("VACUUM")
        n_ev, n_ast = con.execute("SELECT COUNT(*), COUNT(DISTINCT number) FROM events").fetchone()
        con.close()
        L_replace(partial, out)
        S.add("write", time.time() - t_w, n_ev, "events")
    S.info.update(events=n_ev, asteroids=n_ast, resumed=bool(done_nums), output=os.path.basename(out))
    S.emit()
    say(f"pre-screen written: {out}: {n_ev} events of {n_ast} asteroids (of {len(rows)}), {_hms(time.time() - t0)}")
    return out, n_ev, n_ast


def _write_global(con, out, meta):
    """The chunks of a global build -> one ST.DTYPE array sorted by time (out, memory-mapped, so the parent never holds
    all events at once) + its meta (out without .npy + .json). Returns (events, asteroids)."""
    n = con.execute("SELECT COALESCE(SUM(n), 0) FROM chunks").fetchone()[0]
    folder = os.path.dirname(os.path.abspath(out))
    tmp_u = os.path.join(folder, f".unsorted_{os.getpid()}.npy")
    tmp_s = out + f".{os.getpid()}.tmp.npy"
    try:
        u = np.lib.format.open_memmap(tmp_u, mode="w+", dtype=ST.DTYPE, shape=(n,))
        i = 0
        for k, blob in con.execute("SELECT n, data FROM chunks"):
            u[i:i + k] = np.frombuffer(blob, ST.DTYPE)
            i += k
        order = np.argsort(u["et"], kind="stable")
        srt = np.lib.format.open_memmap(tmp_s, mode="w+", dtype=ST.DTYPE, shape=(n,))
        for b0 in range(0, n, 1_000_000):
            srt[b0:b0 + 1_000_000] = u[order[b0:b0 + 1_000_000]]
        n_ast = int(len(np.unique(srt["number"]))) if n else 0
        srt.flush()
        del srt, u, order                                    # unmapped before the rename (Windows needs it)
        meta = dict(meta, kind="global", n_events=int(n), n_asteroids=n_ast, dtype=str(ST.DTYPE.descr))
        mtmp = _meta_path(out) + ".tmp"
        with open(mtmp, "w") as f:
            json.dump(meta, f, indent=1)
        L_replace(tmp_s, out)
        L_replace(mtmp, _meta_path(out))
    finally:
        for p in (tmp_u, tmp_s):
            if os.path.exists(p):
                os.remove(p)
    return int(n), n_ast


# ---------------------------------------------------------------- use
def is_global(path):
    return str(path).endswith(".global.npy")


def _meta_path(path):
    return str(path)[:-len(".npy")] + ".json"


def read_meta(path):
    if is_global(path):
        with open(_meta_path(path)) as f:
            return json.load(f)
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return {k: json.loads(v) for k, v in con.execute("SELECT key, value FROM meta")}
    finally:
        con.close()


def numbers(path, et0, et1, gmax=None):
    """The asteroid numbers with events of a region pre-screen between et0 and et1 (+- HALF_MAX_S: the stored time
    is the Earth-centre one, the site's can be hours away for slow asteroids), with a star no fainter than gmax (the
    pick's star limit: the pick never uses fainter stars, screen.screen caps at cam_limit; same Gaia G). A pre-screen
    built to G 16 keeps ~1 in 6 asteroids, to G 13.2 only ~1 in 40."""
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    g = 99.0 if gmax is None else float(gmax) + 1e-4
    try:
        return {int(r[0]) for r in con.execute("SELECT DISTINCT number FROM events WHERE et BETWEEN ? AND ? AND g <= ?",
                                               (et0 - HALF_MAX_S, et1 + HALF_MAX_S, g))}
    finally:
        con.close()


# ---------------------------------------------------------------- global pre-screens: queries
def select(path, et0=None, et1=None, gmax=None, with_index=False):
    """Events of a global pre-screen whose track touches et0..et1 (default: all) with a star G <= gmax: a ST.DTYPE
    array in memory (the file is memory-mapped and sorted by time: a window reads only its part). with_index: also
    their index rows (ST.IDX_DTYPE, or None without an index file)."""
    a = np.load(path, mmap_mode="r")
    i0, i1 = 0, len(a)
    if et0 is not None:
        i0, i1 = (int(x) for x in np.searchsorted(a["et"], [et0 - HALF_MAX_S, et1 + HALF_MAX_S]))
    a = a[i0:i1]
    m = np.ones(len(a), bool)
    if et0 is not None:
        m &= (a["et"] + a["half"] >= et0) & (a["et"] - a["half"] <= et1)
    if gmax is not None:
        m &= a["g"] <= gmax + 1e-4
    ev = np.array(a[m])
    if not with_index:
        return ev
    ip = _idx_path(path)
    b = np.array(np.load(ip, mmap_mode="r")[i0:i1][m]) if os.path.exists(ip) else None
    return ev, b


def _idx_path(path):
    return str(path)[:-len(".npy")] + ".idx.npy"


def has_index(path):
    return os.path.exists(_idx_path(path))


def _index_job(args):
    path, i0, i1, reach_km, min_alt, max_sun_alt = args
    ev = np.array(np.load(path, mmap_mode="r")[i0:i1])
    return i0, ST.bounds(_W["spice"], ev, reach_km, min_alt, max_sun_alt)


def _init_spice(folder):
    import spiceypy as spice
    from pysyzygos import screen as SC
    os.chdir(folder)
    SC.load_kernels(spice, folder)
    _W.update(spice=spice)


def index(path, workers=4, block=100_000):
    """Write the index of a global pre-screen (<name>.global.idx.npy): per event the lat/lon box of its track's
    usable part (ST.bounds with the build's limits). Site and region queries then test only events whose box comes
    near (about 1 in 20 for a site). Worker processes; minutes for a month."""
    import multiprocessing
    from concurrent.futures import ProcessPoolExecutor
    from pysyzygos.home import HOME
    from pysyzygos import pick as P
    m = read_meta(path)
    n = len(np.load(path, mmap_mode="r"))
    out = _idx_path(path)
    tmp = out + f".{os.getpid()}.tmp.npy"
    idx = np.lib.format.open_memmap(tmp, mode="w+", dtype=ST.IDX_DTYPE, shape=(n,))
    jobs = [(path, i, min(n, i + block), m["reach_km"], m["min_alt"], m["max_sun_alt"]) for i in range(0, n, block)]
    t0, done = time.time(), 0
    P.single_thread_workers()
    try:
        with ProcessPoolExecutor(max_workers=max(1, workers), mp_context=multiprocessing.get_context("spawn"),
                                 initializer=_init_spice, initargs=(HOME,)) as ex:
            for i0, b in ex.map(_index_job, jobs):
                idx[i0:i0 + len(b)] = b
                done += len(b)
                el = time.time() - t0
                print(f"  index: {done}/{n} events, {_hms(el)}, ETA {_hms(el / done * (n - done))}", file=sys.stderr,
                      flush=True)
        idx.flush()
        del idx
        L_replace(tmp, out)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return out


def site_numbers(path, spice, et0, et1, lat, lon, ele_m, opt):
    """The asteroids of a global pre-screen with an event that can be seen from this site (ST.site_mask) in the
    window. opt: cam_limit, reach_km, min_alt, max_sun_alt (the pick's). With an index, only events whose track box
    comes within reach of the site are tested. Returns (numbers set, events in the window, events tested)."""
    ev, b = select(path, et0, et1, opt.get("cam_limit"), with_index=True)
    n_win = len(ev)
    if b is not None:
        ev = ev[ST.near_site(b, ev, lat, lon, opt["reach_km"], opt["min_alt"])]
    keep = ST.site_mask(spice, ev, lat, lon, ele_m, opt["reach_km"], opt["min_alt"], opt["max_sun_alt"])
    return {int(x) for x in ev["number"][keep]}, n_win, len(ev)


def extract(path, box, out=None, start=None, days=None, gmax=None, name=None):
    """A region pre-screen (SQLite, like a region build) cut from a global one: the events whose ground track
    touches the box (ST.region_mask with the global build's limits), optionally for a shorter window and a brighter
    star limit. Seconds instead of a build. Returns (out, events, asteroids)."""
    import spiceypy as spice
    from pysyzygos.home import HOME
    from pysyzygos import screen as SC
    SC.load_kernels(spice, HOME)
    m = read_meta(path)
    start, days = start or m["start"], float(days or m["days"])
    et0 = spice.str2et(f"{start}T00:00:00")
    et1 = et0 + days * 86400.0
    if et0 < m["et0"] - 1 or et1 > m["et1"] + 1:
        raise RuntimeError(f"window {start} + {days:g} d not in the global pre-screen ({m['start']} + {m['days']:g} d)")
    gmax = min(float(gmax), m["cam_limit"]) if gmax is not None else m["cam_limit"]
    ev, b = select(path, et0, et1, gmax, with_index=True)
    if b is not None:
        ev = ev[ST.hits_box(b, ev, box, m["reach_km"], m["min_alt"])]
    keep, where = ST.region_mask(spice, ev, box, m["reach_km"], m["min_alt"], m["max_sun_alt"])
    name = name or "region"
    out = out or os.path.join(os.path.dirname(path) or DIR, f"{name}__{start}_{days:g}d_G{gmax:g}.db")
    meta = dict(m, name=name, start=start, days=days, et0=et0, et1=et1, region=box, cam_limit=gmax,
                source=os.path.basename(path), extracted=time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()))
    for k in ("kind", "n_events", "n_asteroids", "dtype"):
        meta.pop(k, None)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(out)), suffix=".tmp")
    os.close(fd)
    con = sqlite3.connect(tmp)
    con.executescript(SCHEMA)
    e, w = ev[keep], where[keep]
    con.executemany("INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?,?)",
                    [(int(a["number"]), int(a["star"]), float(a["et"]), float(a["g"]), float(a["m_ast"]),
                      float(a["geo_miss"]), *[None if not np.isfinite(x) else float(x) for x in b]) for a, b in zip(e, w)])
    con.executemany("INSERT INTO meta VALUES (?, ?)", [(k, json.dumps(v)) for k, v in meta.items()])
    con.commit()
    con.close()
    L_replace(tmp, out)
    return out, int(keep.sum()), len(set(e["number"].tolist()))


def check(meta, et0, et1, lat, lon, opt):
    """Problems (list of str) using this pre-screen for a pick: window, region, and limits tighter than the pick's
    (then the pick could miss events the full screen finds). A whole-Earth pre-screen has no reach limit: inside the
    Earth's disk it holds every event at any reach; its reach_km is only the margin beyond the Earth's edge and the
    day/night line (EDGE_KM, plane km), which covers grazes and edge cases, so the pick's own reach is used."""
    out = []
    if et0 < meta["et0"] - 1 or et1 > meta["et1"] + 1:
        out.append(f"window not covered (pre-screen {meta['start']} + {meta['days']:g} d)")
    if not contains(meta, lat, lon):
        out.append("site outside the pre-screen's region")
    for k, label, worse in (("cam_limit", "star limit", lambda p, b: p > b + 1e-9),
                            ("reach_km", "reach", lambda p, b: p > b + 1e-9),
                            ("min_drop", "minimum drop", lambda p, b: p < b - 1e-9),
                            ("max_sun_alt", "Sun limit", lambda p, b: p > b + 1e-9),
                            ("min_alt", "minimum altitude", lambda p, b: p < b - 1e-9)):
        if k == "reach_km" and not meta.get("region"):        # whole Earth: no reach limit (see above)
            continue
        if k in opt and worse(opt[k], meta[k]):
            out.append(f"{label} {opt[k]:g} beyond the pre-screen's {meta[k]:g}")
    if opt.get("supplement") and not meta.get("supplement"):
        out.append("built without the high-RUWE supplement")
    if opt.get("hmax_all") or (meta.get("hmax") is not None and opt.get("hmax") is not None and opt["hmax"] > meta["hmax"]):
        out.append(f"H limit beyond the pre-screen's ({meta.get('hmax')})")
    from pysyzygos import picks as PK                         # a pre-screen of some asteroid groups / an a range only
    out += PK.selection_covers(meta_selection(meta), opt.get("selection"))
    return out


def meta_selection(meta):
    """The asteroid selection a pre-screen was built with (picks.selection; all asteroids for older builds)."""
    from pysyzygos import picks as PK
    return PK.selection(meta.get("groups"), meta.get("a_min"), meta.get("a_max"), meta.get("a_exclude", False))


def age_days(meta):
    """Days since the build (orbits of that day: rebuild after a few weeks)."""
    try:
        import calendar
        return (time.time() - calendar.timegm(time.strptime(meta["built"][:19], "%Y-%m-%dT%H:%M:%S"))) / 86400
    except (KeyError, ValueError, TypeError):
        return None


def counts(path):
    """(events, asteroids) of a pre-screen file."""
    if is_global(path):
        m = read_meta(path)
        return m.get("n_events"), m.get("n_asteroids")
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return con.execute("SELECT COUNT(*), COUNT(DISTINCT number) FROM events").fetchone()
    finally:
        con.close()


def best_fit(et0, et1, lat, lon, opt, folder=DIR):
    """The pre-screen to use for a pick: (path, meta) of the newest build that fits (check() empty), or (None, None);
    plus [(path, meta, problems)] of the others, for the message."""
    fits, other = [], []
    for p, m in list_files(folder):
        bad = check(m, et0, et1, lat, lon, opt)
        (other.append((p, m, bad)) if bad else fits.append((p, m)))
    if not fits:
        return None, None, other
    p, m = max(fits, key=lambda x: (x[1].get("built", ""), -x[1]["days"]))
    return p, m, other


def list_files(folder=DIR):
    """[(path, meta)] of the region (.db) and global (.global.npy + .json) pre-screens in folder."""
    out = []
    paths = glob.glob(os.path.join(folder, "*.db")) + \
        [p for p in glob.glob(os.path.join(folder, "*.global.npy")) if os.path.exists(_meta_path(p))]
    for p in sorted(paths):
        try:
            out.append((p, read_meta(p)))
        except (sqlite3.Error, OSError, ValueError):
            continue
    return out


def remove(path):
    """Delete a pre-screen (a global one with its meta file)."""
    for p in ([path, _meta_path(path), _idx_path(path)] if is_global(path) else [path]):
        if os.path.exists(p):
            os.remove(p)


# ------------------------------------------------------------------------- shared pre-screens (mirror)
MANIFEST = "prescreens.json"
SHARE_DIR = os.path.join("release", "world-prescreens")
SHARE_KEYS = ("start", "days", "et0", "et1", "region", "cam_limit", "hmax", "min_drop", "reach_km", "max_sun_alt",
              "min_alt", "supplement", "asteroids_screened", "n_events", "n_asteroids", "built", "build_s", "version",
              "groups", "a_min", "a_max", "a_exclude")


def _files(path):
    """The files of a global pre-screen to share: events, index, then the meta file (list_files sees a pre-screen
    only once its .json is there, so a fetch writes it last)."""
    return [p for p in (path, _idx_path(path)) if os.path.exists(p)] + [_meta_path(path)]


def _sha(path):
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for c in iter(lambda: f.read(1 << 22), b""):
            h.update(c)
    return h.hexdigest()


def _tar_xz(folder, names, dst):
    """Pack the files names (in folder, no directory part) into dst (.tar.xz): tar + the xz program on all cores if
    both are there, else Python's tarfile with lzma (same format)."""
    import shutil, subprocess, tarfile
    tmp = dst + ".part"
    if shutil.which("tar") and shutil.which("xz"):
        with open(tmp, "wb") as out:
            tar = subprocess.Popen(["tar", "-cf", "-", "-C", folder] + list(names), stdout=subprocess.PIPE)
            subprocess.run(["xz", "-T0", "-6", "-c"], stdin=tar.stdout, stdout=out, check=True)
            tar.stdout.close()
            if tar.wait() != 0:
                raise RuntimeError("tar failed")
    else:
        with tarfile.open(tmp, "w:xz", preset=6) as t:
            for n in names:
                t.add(os.path.join(folder, n), arcname=n)
    os.replace(tmp, dst)


def catalog_info(name):
    """What the pre-screen's catalog was: {'folder', 'format', 'build_id', 'gmax', 'pm_epoch'} from its catalog.json
    (the folder itself, or the same name without .new / .old after an upgrade swapped it in), else {'folder': name}."""
    out = {"folder": name}
    for d in (name, name.rsplit(".", 1)[0] if name.endswith((".new", ".old")) else None):
        p = os.path.join(d, "catalog.json") if d else None
        if p and os.path.isfile(p):
            with open(p) as f:
                c = json.load(f)
            out.update(format=c.get("format", 1), build_id=c.get("build_id"), gmax=c.get("gmax"),
                       pm_epoch=(c.get("pm_epoch") or {}).get("date"), data_version=c.get("data_version"))
            break
    return out


def publish(path, dest=SHARE_DIR, log=print, remote=None):
    """Pack a global pre-screen for the mirror: <name>.tar.xz (events, index, meta) + <name>.tar.xz.sha256 in the share
    folder, and its entry in the folder's prescreens.json (settings, catalog, the archive's and each file's size and
    SHA-256; replaces an entry of the same name). The list starts from the share folder's and the mirror's current
    one (remote: mirror folders, default mirrors(); [] for none), so a pre-screen built on another machine keeps its
    entry. Upload those to the mirror's pre-screen folder (world-prescreens/). Returns the entry."""
    if not is_global(path):
        sys.exit("only global (whole-Earth) pre-screens are shared: a region one is cut from them in seconds")
    m = read_meta(path)
    if not has_index(path):
        log("no index yet: building it first (pysyzygos prescreen index)")
        index(path)
    os.makedirs(dest, exist_ok=True)
    name = os.path.basename(path)[:-len(".global.npy")]
    files = [dict(name=os.path.basename(p), bytes=os.path.getsize(p), sha256=_sha(p)) for p in _files(path)]
    archive = name + ".tar.xz"
    out = os.path.join(dest, archive)
    t = time.time()
    log(f"{archive}: packing {', '.join(f['name'] for f in files)} ({sum(f['bytes'] for f in files) / 1e6:.0f} MB) ...")
    _tar_xz(os.path.dirname(os.path.abspath(path)), [f["name"] for f in files], out)
    sha = _sha(out)
    with open(out + ".sha256", "w") as f:
        f.write(f"{sha}  {archive}\n")
    log(f"   {os.path.getsize(out) / 1e6:.0f} MB in {_hms(time.time() - t)}, SHA-256 {sha}")
    entry = {k: m.get(k) for k in SHARE_KEYS}
    entry.update(name=name, kind="global", catalog=catalog_info(m.get("catalog", "")), archive=archive,
                 archive_bytes=os.path.getsize(out), archive_sha256=sha, files=files, published=time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()), published_with=__version__)
    mp = os.path.join(dest, MANIFEST)
    local = load_manifest(mp)
    m, there = remote_list(remote, log=lambda *a: None)
    if there is None:
        log(f"   no mirror answered: the list is this folder's only ({len((local or {}).get('prescreens', []))} "
            f"other pre-screen(s)); merge it with the mirror's later: pysyzygos prescreen merge")
    else:
        # the mirror's list is the truth: withdrawn ones (archive deleted there) leave it, and of this folder's list
        # only the pre-screens packed here and not uploaded yet (archive in this folder) are added
        there = on_mirror(there, m, log)
        local = dict(prescreens=[e for e in (local or {}).get("prescreens", [])
                                 if os.path.isfile(os.path.join(dest, e["archive"]))])
    man = merge_manifests([there, local, dict(prescreens=[entry])])
    write_manifest(man, mp)
    log(f"{mp}: {len(man['prescreens'])} pre-screen(s) ({', '.join(e['name'] for e in man['prescreens'])}). Upload "
        f"{archive}, {archive}.sha256 and {MANIFEST} to the mirror's pre-screen folder (urls.URL_PRESCREEN_MIRRORS)")
    return entry


def load_manifest(src):
    """A prescreens.json from a file or a URL (http(s):// or file://), or None if it cannot be read."""
    try:
        if "://" in src:
            return json.loads(_get(src))
        with open(src) as f:
            return json.load(f)
    except Exception:
        return None


def merge_manifests(mans):
    """One list of shared pre-screens from several (None ones skipped): each pre-screen once; listed more than once,
    the one published last wins (an equal time: the later list). Sorted by start, then name."""
    by = {}
    for man in mans:
        for e in (man or {}).get("prescreens", []):
            old = by.get(e.get("name"))
            if old is None or str(e.get("published") or "") >= str(old.get("published") or ""):
                by[e["name"]] = e
    items = sorted(by.values(), key=lambda e: (e.get("start") or "", e["name"]))
    return dict(format=1, about="PySyzygos shared pre-screens: pysyzygos prescreen remote / fetch",
                updated=max((str(e.get("published") or "") for e in items), default=""), prescreens=items)


def write_manifest(man, path):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path + ".tmp", "w") as f:
        json.dump(man, f, indent=1)
    os.replace(path + ".tmp", path)


def check_archives(man, mirror, log=print):
    """Names of the listed pre-screens whose archive is not on the mirror (a one-byte request each)."""
    missing = []
    for e in man.get("prescreens", []):
        url = mirror + e["archive"]
        try:
            if url.startswith("file://"):
                ok = os.path.isfile(url[len("file://"):])
            else:
                import requests
                r = requests.get(url, headers={"Range": "bytes=0-0"}, timeout=30, stream=True)
                ok = r.status_code in (200, 206)
                r.close()
        except Exception:
            ok = False
        log(f"   {e['archive']}: {'on the mirror' if ok else 'MISSING'}")
        if not ok:
            missing.append(e["name"])
    return missing


def on_mirror(man, mirror, log=print):
    """The mirror's list without the pre-screens whose archive is not on the mirror (deleted there)."""
    gone = set(check_archives(man, mirror, log=lambda *a: None))
    for name in sorted(gone):
        log(f"   {name}: listed on the mirror, archive not there: left out")
    return dict(man, prescreens=[e for e in man.get("prescreens", []) if e["name"] not in gone])


def mirrors():
    """Mirror folders of shared pre-screens: env PYSYZYGOS_PRESCREEN_MIRROR (comma-separated) first, then urls.py."""
    from pysyzygos import urls as U
    env = [m.strip() for m in os.environ.get("PYSYZYGOS_PRESCREEN_MIRROR", "").split(",") if m.strip()]
    return [m if m.endswith("/") else m + "/" for m in env + list(U.URL_PRESCREEN_MIRRORS)]


def _get(url, timeout=90):
    if url.startswith("file://"):
        with open(url[len("file://"):], "rb") as f:
            return f.read()
    import requests
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    return r.content


def remote_list(mirror_list=None, log=print):
    """(mirror, manifest) of the first mirror that answers, or (None, None)."""
    for m in (mirrors() if mirror_list is None else mirror_list):
        try:
            return m, json.loads(_get(m + MANIFEST))
        except Exception as e:                                     # unreachable, no manifest, not JSON
            log(f"   {m}: no list ({str(e)[:80]})")
    return None, None


def _choose(items, name):
    if name in (None, "", "latest"):
        return max(items, key=lambda e: (e.get("start") or "", e.get("built") or "")) if items else None
    return next((e for e in items if e["name"] == name or e["name"] + ".global.npy" == name), None)


def fetch(name="latest", folder=DIR, mirror_list=None, log=print):
    """Download a shared pre-screen into folder: its .tar.xz (resumable), SHA-256 checked, then only the listed files
    unpacked (by name; nothing else in the archive is written), each checked again, the meta file last. Nothing is
    downloaded when the files are already there and intact. Returns the .global.npy path."""
    import shutil, tarfile
    from pysyzygos import gaia_local as GL
    m, man = remote_list(mirror_list, log)
    if not man:
        sys.exit("no pre-screen mirror answered (offline?)")
    e = _choose(man.get("prescreens", []), name)
    if e is None:
        sys.exit(f"no shared pre-screen '{name}'; available: "
                 + ", ".join(x["name"] for x in man.get("prescreens", [])))
    os.makedirs(folder, exist_ok=True)
    need = sum(f["bytes"] for f in e["files"]) + e["archive_bytes"]
    if shutil.disk_usage(folder).free < need:
        sys.exit(f"not enough disk space in {folder}: {need / 1e9:.1f} GB needed")
    log(f"{e['name']}: {e['start']} + {e['days']:g} d, G <= {e['cam_limit']:g}, {e['n_events']} events of "
        f"{e['n_asteroids']} asteroids, built {str(e.get('built'))[:10]}, from {m}")
    if all(os.path.isfile(os.path.join(folder, f["name"])) and os.path.getsize(os.path.join(folder, f["name"]))
           == f["bytes"] and _sha(os.path.join(folder, f["name"])) == f["sha256"] for f in e["files"]):
        log("   already here and intact")
        return os.path.join(folder, e["name"] + ".global.npy")
    part = os.path.join(folder, e["archive"] + ".part")
    if not (os.path.isfile(part) and os.path.getsize(part) == e["archive_bytes"]):
        log(f"   {e['archive']}: {e['archive_bytes'] / 1e6:.0f} MB")
        if m.startswith("file://"):
            shutil.copyfile(m[len("file://"):] + e["archive"], part)
        else:
            GL._fetch_resume(m + e["archive"], e["archive_bytes"], part)
    log("   checking the SHA-256 ...")
    if _sha(part) != e["archive_sha256"]:
        os.remove(part)
        sys.exit(f"{e['archive']}: SHA-256 mismatch (corrupt download, deleted); run again")
    log(f"   unpacking {e['archive']} ...")
    want = {f["name"]: f for f in e["files"]}
    with tarfile.open(part, "r:xz") as t:
        members = {x.name: x for x in t.getmembers() if x.isfile()}
        missing = [n for n in want if n not in members]
        if missing:
            sys.exit(f"{e['archive']}: {', '.join(missing)} missing in the archive")
        for f in e["files"]:                                      # the list's order: the meta file last
            final = os.path.join(folder, f["name"])
            with t.extractfile(members[f["name"]]) as src, open(final + ".part", "wb") as dst:
                shutil.copyfileobj(src, dst, 1 << 22)
            if os.path.getsize(final + ".part") != f["bytes"] or _sha(final + ".part") != f["sha256"]:
                os.remove(final + ".part")
                sys.exit(f"{f['name']}: unpacked file does not match its SHA-256; run again")
            GL.replace_file(final + ".part", final)
    os.remove(part)
    path = os.path.join(folder, e["name"] + ".global.npy")
    log(f"{path}: ready (pick --prescreen auto uses it when it covers the window)")
    return path


def describe(path, meta=None):
    m = meta or read_meta(path)
    reg = m.get("region")
    where = "whole Earth" if not reg else (f"lat {reg['lat_min']:.1f}..{reg['lat_max']:.1f}, "
                                           f"lon {reg['lon_min']:.1f}..{reg['lon_max']:.1f}")
    from pysyzygos import picks as PK
    only = PK.selection_text(meta_selection(m))
    return (f"{m.get('name', '?')}: {m['start']} + {m['days']:g} d, {where}, for picks up to G {m['cam_limit']:g}, "
            + (f"reach {m['reach_km']:g} km, " if reg else "") + f"H {m.get('hmax')}" + (f", only {only}" if only else "")
            + f"; built {m.get('built', '?')[:16]}")


def main(argv=None):
    cfg = {}
    try:
        from pysyzygos import config as C
        g = lambda k, d: getattr(C, k, d)
        cfg = dict(sites=[(v["lat"], v["lon"]) for v in getattr(C, "sites", {}).values() if "lat" in v],
                   lat=C.LAT, lon=C.LON, ele=g("ELE", 0.0), reach=g("max_shadow_dist", 20.0), min_alt=g("MIN_STAR_ALT", 10.0),
                   max_sun_alt=g("MAX_SUN_ALT", 0.0), site=g("site_name", None), catalog=g("gaia_local_dir", "gaia_dr3_g16"),
                   cache=C.cache_path, hmax=g("pick_hmax", 17.0), cam_limit=g("pick_cam_limit", 16.0))
    except (ImportError, AttributeError):
        pass
    c = lambda k, d=None: cfg.get(k, d)
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=f"PySyzygos {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="build a pre-screen")
    b.add_argument("--start", required=True, help="UTC date YYYY-MM-DD")
    b.add_argument("--days", type=float, default=30.0)
    where = b.add_mutually_exclusive_group(required=True)
    where.add_argument("--region", help="a name (usa, europe, south-america, ...: see REGIONS) or "
                                        "lat_min,lat_max,lon_min,lon_max in degrees (lon east-positive)")
    where.add_argument("--around-site", type=float, metavar="KM", help="a box this far around the configured site")
    where.add_argument("--around-sites", type=float, metavar="KM",
                       help="one box this far around all sites of sites.py (one pre-screen for all of them)")
    where.add_argument("--global", dest="glob", action="store_true",
                       help="the whole Earth: stores the shadow elements of every event (~80 B each), so any site "
                            "(pick --prescreen) or region (prescreen extract) can be cut from it later")
    b.add_argument("--name", help="name of the pre-screen (default: region / site name / global)")
    b.add_argument("--cam-limit", type=float, default=max(float(c("cam_limit", 16.0)), 16.0), help="faintest star, G")
    b.add_argument("--hmax", type=float, default=c("hmax", 17.0))
    b.add_argument("--all", action="store_true", help="all numbered asteroids, any H")
    from pysyzygos.picks import GROUP_NAMES
    b.add_argument("--groups", default="all", help="only these asteroid groups (as pick --groups): "
                   + ", ".join(GROUP_NAMES) + "; default all. Picks of other groups do not use it")
    b.add_argument("--a-min", type=float, help="only asteroids with a semi-major axis of at least this, AU")
    b.add_argument("--a-max", type=float, help="only asteroids with a semi-major axis of at most this, AU")
    b.add_argument("--a-exclude", action="store_true", help="the asteroids OUTSIDE the --a-min/--a-max range")
    b.add_argument("--min-drop", type=float, default=0.1)
    b.add_argument("--reach", type=float, default=EDGE_KM,
                   help="regional: the largest reach (km) a pick will use; whole Earth (--global): the margin beyond "
                        "the Earth's edge and the day/night line, any pick reach then fits (default %(default)g)")
    b.add_argument("--max-sun-alt", type=float, default=0.0, help="loosest Sun limit a pick will use (deg)")
    b.add_argument("--min-alt", type=float, default=0.0, help="lowest star altitude a pick will use (deg)")
    b.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) // 2))
    b.add_argument("--catalog", default=c("catalog"))
    b.add_argument("--chunk", type=int, help="asteroids per chunk (default: from the free memory)")
    b.add_argument("--max-mem", type=float, metavar="GB", help="memory budget for all workers (default: --mem-frac of "
                   "the available memory)")
    b.add_argument("--mem-frac", type=float, default=0.6, help="share of the available memory to use (default 0.6)")
    b.add_argument("--fresh", action="store_true", help="discard a partial build of this name instead of resuming it")
    b.add_argument("-o", "--output")
    sub.add_parser("list", help="the pre-screens in prescreen/")
    s = sub.add_parser("show", help="settings and numbers of one pre-screen")
    s.add_argument("file")
    x = sub.add_parser("extract", help="cut a region pre-screen from a global one (seconds)")
    x.add_argument("file", help="a global pre-screen (.global.npy)")
    xw = x.add_mutually_exclusive_group(required=True)
    xw.add_argument("--region", help=f"a name ({', '.join(REGIONS)}) or lat_min,lat_max,lon_min,lon_max (deg)")
    xw.add_argument("--around-site", type=float, metavar="KM", help="a box this far around the configured site")
    xw.add_argument("--around-sites", type=float, metavar="KM", help="one box this far around all sites of sites.py")
    x.add_argument("--start", help="a later start (default: the global one's)")
    x.add_argument("--days", type=float, help="a shorter window (default: the global one's)")
    x.add_argument("--cam-limit", type=float, help="a brighter star limit (smaller file)")
    x.add_argument("--name")
    x.add_argument("-o", "--output")
    ix = sub.add_parser("index", help="(re)build the lat/lon index of a global pre-screen (done after every build)")
    ix.add_argument("file")
    ix.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) // 2))
    q = sub.add_parser("query", help="asteroids of a global pre-screen with events seen from the configured site")
    q.add_argument("file", help="a global pre-screen (.global.npy)")
    q.add_argument("--start", help="UTC date (default: the pre-screen's start)")
    q.add_argument("--days", type=float, help="default: the pre-screen's window")
    q.add_argument("--cam-limit", type=float, default=c("cam_limit", 16.0), help="faintest star, G")
    q.add_argument("--reach", type=float, default=c("reach", 20.0), help="km")
    q.add_argument("--min-alt", type=float, default=c("min_alt", 10.0))
    q.add_argument("--max-sun-alt", type=float, default=c("max_sun_alt", 0.0))
    q.add_argument("--numbers", action="store_true", help="print the asteroid numbers")
    pb = sub.add_parser("publish", help="pack a global pre-screen (.tar.xz + .sha256) into the share folder for the mirror")
    pb.add_argument("file", help="a global pre-screen (.global.npy)")
    pb.add_argument("--to", default=SHARE_DIR, help=f"share folder (default {SHARE_DIR})")
    pb.add_argument("--no-mirror", action="store_true", help="do not start the list from the mirror's current one")
    mg = sub.add_parser("merge", help="one prescreens.json from the mirror's and other lists (builds on several "
                                      "machines), without repacking")
    mg.add_argument("lists", nargs="*", help="more lists: files, URLs, or file names on the mirror (e.g. "
                                             "prescreens-new.json)")
    mg.add_argument("-o", "--output", default=os.path.join(SHARE_DIR, MANIFEST), help="the merged list (default "
                    "%(default)s): upload it to the mirror as " + MANIFEST)
    mg.add_argument("--no-mirror", action="store_true", help="leave the mirror's current list out")
    mg.add_argument("--check", action="store_true", help="check that every listed archive is on the mirror")
    mg.add_argument("--drop", action="append", default=[], metavar="NAME",
                    help="leave this pre-screen out (withdrawn; repeatable): every list is merged, so a deleted "
                         "archive's entry comes back from the mirror's list otherwise")
    sub.add_parser("remote", help="the shared pre-screens on the mirror")
    fe = sub.add_parser("fetch", help="download a shared pre-screen from the mirror into prescreen/")
    fe.add_argument("name", nargs="?", default="latest", help="its name (see remote), default: the latest")
    a = ap.parse_args(argv)
    if a.cmd == "publish":
        publish(a.file, a.to, remote=[] if a.no_mirror else None)
        return 0
    if a.cmd == "merge":
        mirror, there = (None, None) if a.no_mirror else remote_list()
        if there is not None:
            there = on_mirror(there, mirror)
        srcs =[("mirror " + MANIFEST, there)] if there is not None else []
        for x in a.lists:
            src = x if ("://" in x or os.path.exists(x) or not mirror) else mirror + x
            man = load_manifest(src)
            if man is None:
                sys.exit(f"cannot read the list {src}")
            srcs.append((src, man))
        if not srcs:
            sys.exit("nothing to merge (no mirror answered, no lists given)")
        merged = merge_manifests([m for _, m in srcs])
        drop = {d[:-len(".tar.xz")] if d.endswith(".tar.xz") else d for d in a.drop}
        unknown = drop - {e["name"] for e in merged["prescreens"]}
        if unknown:
            sys.exit(f"not in the lists: {', '.join(sorted(unknown))}")
        merged = merge_manifests([dict(prescreens=[e for e in merged["prescreens"] if e["name"] not in drop])])
        for src, m in srcs:
            print(f"{src}: {', '.join(e['name'] for e in m.get('prescreens', [])) or '(empty)'}")
        write_manifest(merged, a.output)
        print(f"{a.output}: {len(merged['prescreens'])} pre-screen(s): "
              f"{', '.join(e['name'] for e in merged['prescreens'])}. Upload it to the mirror as {MANIFEST}.")
        if a.check and mirror:
            missing = check_archives(merged, mirror)
            if missing:
                print(f"Not on the mirror yet: {', '.join(missing)} (upload their .tar.xz and .tar.xz.sha256)")
                return 1
        return 0
    if a.cmd == "remote":
        from pysyzygos import picks as PK
        m, man = remote_list()
        if not man:
            print("No pre-screen mirror answered (offline?).")
            return 1
        print(f"Shared pre-screens at {m} (updated {str(man.get('updated'))[:16]}):")
        here = {os.path.basename(p) for p, _ in list_files()}
        for e in man.get("prescreens", []):
            mb = e["archive_bytes"] / 1e6
            print(f"  {e['name']}{'  [installed]' if e['name'] + '.global.npy' in here else ''}\n"
                  f"    {e['start']} + {e['days']:g} d, whole Earth, for picks up to G {e['cam_limit']:g} (any reach"
                  + (f"; only {PK.selection_text(meta_selection(e))}" if PK.restricted(meta_selection(e)) else "") + "); "
                  f"{e['n_events']} events of {e['n_asteroids']} asteroids, built "
                  f"{str(e.get('built'))[:10]} ({e.get('version')}), download {mb:.0f} MB")
        return 0
    if a.cmd == "fetch":
        fetch(a.name)
        return 0
    if a.cmd == "list":
        for p, m in list_files():
            n_ev, n_ast = counts(p)
            age = age_days(m)
            print(f"{p}\n    {describe(p, m)}\n    {n_ast} asteroids, {n_ev} events"
                  + (f", {age:.0f} days old" if age is not None else "")
                  + ("" if not is_global(p) else ", indexed" if has_index(p) else ", no index"))
        return 0
    if a.cmd == "show":
        m = read_meta(a.file)
        n_ev, n_ast = counts(a.file)
        print(describe(a.file, m))
        print(f"{n_ev} events of {n_ast} asteroids (of {m.get('asteroids_screened')} screened), build {m.get('build_s')} s"
              + (f", {os.path.getsize(a.file) / 1e6:.0f} MB, " + ("indexed" if has_index(a.file) else "no index")
                 if is_global(a.file) else ""))
        return 0
    if a.cmd == "index":
        t = time.time()
        print(f"index written: {index(a.file, a.workers)} in {_hms(time.time() - t)}")
        return 0
    if a.cmd == "query":
        import spiceypy as spice
        from pysyzygos.home import HOME
        from pysyzygos import screen as SC
        if c("lat") is None:
            ap.error("query needs a configured site")
        SC.load_kernels(spice, HOME)
        m = read_meta(a.file)
        et0 = spice.str2et(f"{a.start or m['start']}T00:00:00")
        et1 = et0 + float(a.days or m["days"]) * 86400.0
        t = time.time()
        nums, n_win, n_ev = site_numbers(a.file, spice, et0, et1, c("lat"), c("lon"), c("ele", 0.0),
                                         dict(cam_limit=a.cam_limit, reach_km=a.reach, min_alt=a.min_alt,
                                              max_sun_alt=a.max_sun_alt))
        print(f"site {c('site')}: {len(nums)} asteroids ({n_ev} of {n_win} events tested"
              f"{', index' if has_index(a.file) else ', no index'}; G <= {a.cam_limit:g}, reach {a.reach:g} km, "
              f"star >= {a.min_alt:g}, Sun <= {a.max_sun_alt:g}) in {time.time() - t:.1f} s")
        if a.numbers:
            print(" ".join(str(x) for x in sorted(nums)))
        return 0
    if a.cmd == "extract":
        if a.region:
            box = parse_region(a.region)
            name = a.name or (a.region.lower() if a.region.lower() in REGIONS else "region")
        elif a.around_sites is not None:
            box, name = box_around_all(c("sites"), a.around_sites), a.name or f"sites_{a.around_sites:g}km"
        else:
            box, name = box_around(c("lat"), c("lon"), a.around_site), a.name or f"{c('site') or 'site'}_{a.around_site:g}km"
        t = time.time()
        try:
            out, n_ev, n_ast = extract(a.file, box, a.output, a.start, a.days, a.cam_limit, name)
        except RuntimeError as e:
            print(f"pre-screen: {e}", file=sys.stderr)
            return 2
        print(f"extracted {out}: {n_ev} events of {n_ast} asteroids in {time.time() - t:.1f} s")
        return 0
    if a.glob:
        region, name = None, a.name or "global"
    elif a.around_sites is not None:
        if not c("sites"):
            ap.error("--around-sites needs sites in sites.py")
        region, name = box_around_all(c("sites"), a.around_sites), a.name or f"sites_{a.around_sites:g}km"
    elif a.region:
        region = parse_region(a.region)
        name = a.name or (a.region.lower() if a.region.lower() in REGIONS else "region")
    else:
        if c("lat") is None:
            ap.error("--around-site needs a configured site")
        region, name = box_around(c("lat"), c("lon"), a.around_site), a.name or f"{c('site') or 'site'}_{a.around_site:g}km"
    try:
        _build_cli(a, c, region, name)
    except KeyboardInterrupt:
        return 130
    except RuntimeError as e:
        print(f"pre-screen: {e}", file=sys.stderr)
        return 2
    return 0


def _build_cli(a, c, region, name):
    from pysyzygos.picks import parse_groups
    build(a.start, a.days, region, a.cam_limit, None if a.all else a.hmax, a.min_drop, a.reach, a.max_sun_alt,
          a.min_alt, a.workers, a.output, a.catalog, os.path.join(c("cache") or tempfile.gettempdir(),
                                                                  "PySyzygos_sbdb_cache.json"), name,
          a.chunk, max_mem=a.max_mem * 1e9 if a.max_mem else None, mem_frac=a.mem_frac, fresh=a.fresh,
          selection=dict(groups=parse_groups(a.groups), a_min=a.a_min, a_max=a.a_max, a_exclude=a.a_exclude))


if __name__ == "__main__":
    sys.exit(main())
