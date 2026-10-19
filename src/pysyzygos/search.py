from pysyzygos.version import __version__
from pysyzygos import urls as U
import sys, base64, functools, math, os, re, threading, time
T_START = time.time()                    # run statistics: start-up time is measured from here
from datetime import datetime
import numpy as np
import requests
import json
import subprocess
import pandas as pd
from pathlib import Path

from scipy.optimize import minimize_scalar
import spiceypy as spice
from astropy import units as u
from astropy.time import Time
from astropy.coordinates import EarthLocation
from astropy.coordinates import SkyCoord
import astropy.units as u

# to Silence Warnings:
import warnings, erfa
warnings.filterwarnings("ignore", category=erfa.ErfaWarning)

from pysyzygos import config
from pysyzygos.paths import shadow_path, path_sigma3_km, path_error, write_shadow_kml, site_probability
from pysyzygos import corridor
from pysyzygos import doubles          # close and double stars at an event
from pysyzygos import horizon          # the site's own horizon (OccultWatcher [User Horizon])
from pysyzygos import db               # results database
from pysyzygos import bodies           # planets and moons as targets (P:Jupiter, M:Io, ...)
from pysyzygos import binaries         # known asteroid satellites
from pysyzygos import astrometry
from pysyzygos import sbdb as sbdb_cache
from pysyzygos import screen          # OWC observability formula, extinction

########################## PROLOGUE KERNEL INIT SECTION


if config.force_cleanup:
    print ('Cleanup old files:')
    for filename in ["naif0012.tls", "de440.bsp", "pck00010.tpc", "earth_latest_high_prec.bpc"]:
        if os.path.exists(filename):
            print ('removing: ', filename)
            os.remove(filename)

# Wipe out old file/memory states completely
spice.clpool()



from pysyzygos.kernels import check_file_age, download_kernels, pck_comment_dates


# ==========================================
# KERNEL DOWNLOADING UTILITY
# ==========================================



EARTH_PCK = {}                                     # coverage of the Earth orientation file (run summary)
if download_kernels(config.earth_pck_max_age):
    try:
        print (f'* PySyzygos {__version__}: loading compute kernels *')
        # Load all required kernels
        from pysyzygos.kernels import lsk_file
        spice.furnsh(lsk_file("."))        # Leapseconds (the newest local naifNNNN.tls)
        spice.furnsh("pck00010.tpc")       # Planetary constants
        spice.furnsh("de440.bsp")          # Major planets base
        from pysyzygos import kernels as K
        _w0 = spice.str2et(str(config.ct))
        _w1 = _w0 + config.days * 86400.0
        _latest = K.pck_span(spice, K.EARTH_PCK)                    # 2000-01-01 .. ~3 months ahead
        _hist = K.historic_earth_pck(".")
        if _w0 < _latest[0] and not _hist:                          # a historic window: Earth orientation before 2000
            print(f"* Search window starts {spice.et2utc(_w0, 'ISOC', 0)[:10]}, before {K.EARTH_PCK} "
                  f"({spice.et2utc(_latest[0], 'ISOC', 0)[:10]}): getting the historic Earth orientation file")
            _hist = K.download_historic_earth_pck(".")
        _spans = []
        if _hist:                                                   # loaded first: EARTH_PCK wins where both cover
            spice.furnsh(_hist)
            _spans.append((os.path.basename(_hist), *K.pck_span(spice, _hist)))
        spice.furnsh(K.EARTH_PCK)
        _spans.append((K.EARTH_PCK, *_latest))
        EARTH_PCK = pck_comment_dates(K.EARTH_PCK)
        EARTH_PCK["stop"] = spice.et2utc(_latest[1], 'ISOC', 0)
        if _hist:
            EARTH_PCK["historic"] = dict(file=os.path.basename(_hist), start=spice.et2utc(_spans[0][1], 'ISOC', 0))
        _win_start, _win_end = spice.et2utc(_w0, 'ISOC', 0), spice.et2utc(_w1, 'ISOC', 0)
        print ('---------------------------------------------')
        print (f"* Earth PCK of {EARTH_PCK['created'] or '?'}: measured to {EARTH_PCK['last_datum'] or '?'}, "
               f"predicted to {EARTH_PCK['stop'][:10]}"
               + (f"; before {spice.et2utc(_latest[0], 'ISOC', 0)[:10]}: {os.path.basename(_hist)} (from "
                  f"{EARTH_PCK['historic']['start'][:10]})" if _hist else ""))
        _ok, _why = K.window_coverage(_spans, _w0, min(_w1, _latest[1]))
        if not _ok:                                                 # start (or a gap): no Earth orientation there
            sys.exit(f"Search window {_win_start[:10]} .. {_win_end[:10]}: no Earth orientation for all of it ({_why} "
                     f"the files: " + ", ".join(f"{n_} {spice.et2utc(a_, 'ISOC', 0)[:10]}..{spice.et2utc(b_, 'ISOC', 0)[:10]}"
                                                 for n_, a_, b_ in _spans)
                     + "). For dates before 2000: pysyzygos setup --historic-earth (downloads "
                       f"{K.EARTH_HISTORIC_GLOB}, ~31 MB)")
        if _win_end > EARTH_PCK["stop"]:                            # future: only the high-precision file's prediction
            sys.exit(f"Search window ends {_win_end[:10]}, after the Earth orientation file ({EARTH_PCK['stop'][:10]}): "
                     f"shorten the window (days) or refresh earth_latest_high_prec.bpc (delete it, rerun)")
        print ('---------------------------------------------')
    
        print ('* Testing Compute Kernels *')
        
        et = spice.str2et("2026-09-28 UTC")
        print(f"🚀 Success! CSPICE Active. Target ET: {et}")
        print ('---------------------------------------------')
        print ('---------- COMPUTE SYSTEM READY -------------')
        print ('---------------------------------------------')
            
    except Exception as e:
        print ('---------------------------------------------')
        print(f"CSPICE Error: {e}")
        print ('---------------------------------------------')
        sys.exit('Exiting as of error.')

########################## PROLOGUE KERNEL INIT SECTION END




### NOW OCCULT CALC AND STAR+ASTEROID EPH MANAGEMENT

PC_KM = 3.0856775814913673e13
def geocentric_star_dir(ra_deg, dec_deg, plx_mas, et):
    ra, dec = np.radians(ra_deg), np.radians(dec_deg)
    u_bary = np.array([np.cos(dec)*np.cos(ra), np.cos(dec)*np.sin(ra), np.sin(dec)])
    earth, _ = spice.spkpos('399', et, 'J2000', 'NONE', 'SSB')
    v = u_bary * (1000.0 / max(plx_mas, 0.01)) * PC_KM - earth
    return v / np.linalg.norm(v)


def observer_j2000(et, obs_geo):
    from pysyzygos import earth                           # WGS84 (GPS) geodetic coordinates
    itrf = spice.georec(obs_geo['lon'], obs_geo['lat'], obs_geo['alt'], earth.A_KM, earth.F)
    return spice.pxform('ITRF93', 'J2000', et) @ itrf

def moon_info(et, star_dir, obs_geo):
    moon_geo, _ = spice.spkpos('MOON', et, 'J2000', 'LT+S', '399')
    moon_topo = moon_geo - observer_j2000(et, obs_geo)
    sep = np.degrees(spice.vsep(moon_topo, star_dir))

    moon_from_sun, _ = spice.spkpos('MOON', et, 'J2000', 'LT+S', 'SUN')
    alpha = spice.vsep(moon_from_sun, moon_geo)              # phase angle at the Moon
    illum = 100.0 * (1 + np.cos(alpha)) / 2

    sun_geo, _ = spice.spkpos('SUN', et, 'J2000', 'LT+S', '399')
    R = spice.pxform('J2000', 'ECLIPJ2000', et)
    mv, sv = R @ moon_geo, R @ sun_geo
    age = np.degrees(np.arctan2(mv[1], mv[0]) - np.arctan2(sv[1], sv[0])) % 360.0

    return dict(moon_sep_deg=sep, moon_alt_deg=alt_deg(et, moon_topo, obs_geo),
                moon_illum_pct=illum, moon_age_deg=age)

def gaia_cone(ra_deg, dec_deg, radius_arcmin, mag_limit):
    """Archive cone query, used only by the old "windows" search mode (the corridor mode reads the local Gaia copy).
    Not cached. Async: the sync launch_job silently truncates at 2000 rows."""
    query = f"""
    SELECT 
        source_id, ra, dec, parallax, pmra, pmdec, phot_g_mean_mag, ruwe, radial_velocity
    FROM gaiadr3.gaia_source
    WHERE 1=CONTAINS(POINT('ICRS', ra, dec), CIRCLE('ICRS', {ra_deg}, {dec_deg}, {radius_arcmin / 60.0}))
    AND phot_g_mean_mag <= {mag_limit}
    AND pmra IS NOT NULL AND pmdec IS NOT NULL -- Required for propagation
    AND ruwe < 1.4
    """
    try:
        from astroquery.gaia import Gaia        # here only: importing it contacts the Gaia archive (7 s, 2026-10-16)
        return Gaia.launch_job_async(query).get_results().to_pandas()
    except Exception as e:
        print(f"An error occurred: {e}")
        return None

# fetch_and_propagate_stars(): df = gaia_cone(...).copy(); then your existing SkyCoord /
# apply_space_motion block, unchanged. Never cache that part.

def fetch_and_propagate_stars(
    ra_deg, dec_deg, event_time_str, radius_arcmin=10.0, mag_limit=16.0
):
    """Fetches Gaia DR3 stars and propagates their RA/Dec to a specific event time.

    Parameters:
    ra_deg (float): Center RA in decimal degrees (ICRS)
    dec_deg (float): Center Dec in decimal degrees (ICRS)
    event_time_str (str): Target date/time in ISO format (e.g., '2026-11-05
    12:00:00')
    radius_arcmin (float): Cone search radius in arcminutes
    mag_limit (float): Faintest G-band magnitude to include
    """
    # Parse target time and define reference epochs
    target_time = Time(event_time_str, scale="utc")
    gaia_epoch = Time("2016-01-01T12:00:00", scale="tcb")  # Gaia DR3 J2016.0 reference
    # gaia_cone(...)      -> raw Gaia table (epoch 2016.0)
    # propagate(df, time) -> adds ra_YYYYMMDD / dec_YYYYMMDD, never cached
    
    print(
        f"Querying Gaia DR3 & propagating positions to: {target_time.iso} UTC..."
    )

    df = gaia_cone(ra_deg, dec_deg, radius_arcmin, mag_limit)
    if df is None:
        return None
        
    # Handle missing or negative parallaxes safely by clipping them to 0 (very distant stars)
    #safe_parallax = np.where(
    #    df["parallax"].isna() | (df["parallax"] < 0), 0, df["parallax"]
    #)
    safe_parallax = np.clip(df["parallax"].fillna(0.0).to_numpy(), 0.01, None)   # mas, i.e. 100 kpc max
    
    # Initialize SkyCoord array at the native Gaia J2016.0 epoch
    stars_j2016 = SkyCoord(
        ra=df["ra"].values * u.deg,
        dec=df["dec"].values * u.deg,
        distance=CoordinateDistance(safe_parallax),
        pm_ra_cosdec=corridor.gaia_pm(df, getattr(config, "gaia_pm_bias", True))[0] * u.mas / u.yr,
        pm_dec=corridor.gaia_pm(df, getattr(config, "gaia_pm_bias", True))[1] * u.mas / u.yr,
        radial_velocity=(np.nan_to_num(df["radial_velocity"].to_numpy(float)) if getattr(config, "star_rv", True)
                         and "radial_velocity" in df else np.zeros(len(df))) * u.km / u.s,
        obstime=gaia_epoch,
        frame="icrs",
    )
    
    # Apply 3D space motion propagation to the target event epoch
    # This handles proper motion and positional changes accurately
    stars_target_epoch = stars_j2016.apply_space_motion(
        new_obstime=target_time
    )
    
    # Append the new highly precise computed coordinates back into the table
    df[f"ra_{target_time.datetime.strftime('%Y%m%d')}"] = (
        stars_target_epoch.ra.deg
    )
    df[f"dec_{target_time.datetime.strftime('%Y%m%d')}"] = (
        stars_target_epoch.dec.deg
    )

    print(f"Successfully processed {len(df)} stars.")
    return df



def CoordinateDistance(parallax_mas):
    """Helper to convert parallax safely to distance."""
    # Where parallax is 0, place the star effectively at infinity (100,000 parsecs)

    # Create a mask for where the parallax is safe
    condition = parallax_mas > 0

    # Compute safely: out fills the fallback value, where restricts execution
    distance_pc = np.divide(1000.0, parallax_mas, out=np.full_like(parallax_mas, 100000.0), where=condition)
    return distance_pc * u.pc


    
    


def list_spk_contents(kernel_path):
    # Find all unique object IDs tracked in the BSP file
    objects = spice.spkobj(kernel_path)
    
    print(f"Found {len(objects)} objects in {kernel_path}:\n")
    print(f"{'Object NAIF ID':<15} | {'Coverage Start (ET)':<20} | {'Coverage End (ET)':<20}")
    print("-" * 62)
    
    for obj_id in objects:
        # Retrieve the coverage windows for each object
        cover = spice.spkcov(kernel_path, obj_id)
        
        # Iterate over the distinct intervals within the window
        num_intervals = spice.wncard(cover)
        for i in range(num_intervals):
            # Extract start and end times in Ephemeris Time (seconds past J2000)
            start_et, end_et = spice.wnfetd(cover, i)
            
            # (Optional) Convert ET to a human-readable UTC string
            # Requires loading a leapseconds kernel (tls) if you want to use spice.et2utc
            
            print(f"{obj_id:<15} | {start_et:<20.3f} | {end_et:<20.3f}")



        
# 20028119, 28119 (1998 SX71),28119

#+20000000
def get_asteroid_name(spk_id):
    """Full name ("218001 (2001 XQ72)") from the SBDB size cache (fetched and cached if missing); the number if SBDB
    cannot be reached. Accepts the asteroid number or its SPK id (20000000 + number); a major body: its name."""
    if bodies.is_body(spk_id):
        return bodies.name(spk_id)
    n = int(spk_id)
    n = n - 20000000 if n >= 20000000 else n
    phys = sbdb_phys(n)
    return ((phys or {}).get("_fullname") or "").strip() or f"({n})"



_loaded = {}    # asteroid number -> NAIF id

def load_orbit(target_id, epochs):
    """fetch_target_orbit for the run loop: True when the orbit is loaded; False, with a one-line reason, when JPL
    Horizons has no such object (e.g. a mistyped number) or cannot be reached, so the run goes on with the others."""
    try:
        fetch_target_orbit(target_id, epochs)
        return True
    except (RuntimeError, requests.RequestException, ValueError) as ex:
        print(f"{target_id}: no orbit from JPL Horizons ({str(ex).strip()[:200]}), skipping")
        SKIPPED.append(str(target_id))
        return False


SKIPPED = []                                             # targets without an orbit (run summary)


def _spk_file(target_id, epochs, cache_dir=config.cache_path):
    return Path(cache_dir) / f"PySyzygos_asteroid_{target_id}_{epochs['start']}_{epochs['stop']}.bsp"


def _spk_stale(fn):
    """Missing, or older than orbit_max_age_days: to be downloaded."""
    max_age = float(getattr(config, "orbit_max_age_days", 1)) * 86400.0
    return not fn.is_file() or time.time() - fn.stat().st_mtime > max_age


def _horizons_spk(target_id, epochs, timeout=60):
    """The asteroid's SPK from JPL Horizons as bytes (network only, no SPICE: safe in threads). Raises
    requests.RequestException (network) or RuntimeError (no such object, no SPK)."""
    for k in range(3):                                        # Horizons answers 503 to too many requests at once
        resp = requests.get(U.URL_JPL_HORIZONS_API,
                            params={'format': 'json', 'COMMAND': str(target_id) + ';', 'EPHEM_TYPE': 'SPK',
                                    'MAKE_EPHEM': 'YES', 'START_TIME': epochs['start'], 'STOP_TIME': epochs['stop'],
                                    'OBJ_DATA': 'NO'}, timeout=timeout)
        if resp.status_code != 503 or k == 2:
            break
        time.sleep(1.0 + k)
    resp.raise_for_status()
    data = resp.json()
    if 'spk' not in data:
        text = " ".join(str(data.get('result', data)).split())
        if "out of bounds" in text or "No matches found" in text:
            raise RuntimeError(f"no such object in Horizons: {text[:160]}")
        raise RuntimeError(f"Horizons gave no SPK: {text[:200]}")
    return base64.b64decode(data['spk'])


def _save_spk(fn, blob):
    from pysyzygos import offline
    tmp = Path(str(fn) + f".{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_bytes(blob)
    os.replace(tmp, fn)                                        # atomic: never a half-written orbit file
    offline.keep_spk(fn)                                       # a copy for offline use, if switched on


def prefetch_orbits(targets, epochs, workers=2):
    """Download the missing or stale orbit files of these asteroids in parallel (network only, threads; SPICE loads
    them later in the main thread). Failures are left to fetch_target_orbit (fallbacks, messages). Returns the count."""
    from concurrent.futures import ThreadPoolExecutor
    todo = [str(t) for t in targets if not bodies.is_body(t) and _spk_stale(_spk_file(t, epochs))]
    if len(todo) < 2:
        return 0

    def one(t):
        try:
            _save_spk(_spk_file(t, epochs), _horizons_spk(t, epochs))
            return 1
        except Exception:
            return 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=min(workers, len(todo))) as ex:
        n = sum(ex.map(one, todo))
    print(f"orbits: {n} of {len(todo)} downloaded from JPL Horizons in {time.time() - t0:.1f} s ({workers} at a time)")
    return n


def fetch_target_orbit(target_id, epochs, cache_dir=config.cache_path):
    target_id = str(target_id)
    fn = _spk_file(target_id, epochs, cache_dir)
    from pysyzygos import offline
    blob = None
    if _spk_stale(fn):                                         # missing or older than orbit_max_age_days
        try:
            blob = _horizons_spk(target_id, epochs)
        except requests.RequestException as e:                    # no network: this file even if old, else a copy
            old = str(fn) if fn.is_file() else offline.spk_fallback(target_id, str(epochs['start'])[:10],
                                                                   str(epochs['stop'])[:10], (cache_dir,))
            if old is None:
                raise
            print(f"WARNING: JPL Horizons not reachable ({str(e)[:60]}): orbit of {target_id} from "
                  f"{os.path.basename(old)} (downloaded {time.strftime('%Y-%m-%d', time.gmtime(os.path.getmtime(old)))})")
            fn, blob = Path(old), None
    if blob is not None:                                       # downloaded now
        _save_spk(fn, blob)
    if target_id not in _loaded:
        spice.furnsh(str(fn))
        _loaded[target_id] = int(spice.spkobj(str(fn))[0])
        spice.boddef(target_id, _loaded[target_id])     # keep alias if callers still pass the number
    return _loaded[target_id]                           # NAIF id, safe to use directly in spkpos

SIZE_OVERRIDES = {}   # curate best values here: {"19": (r_km, r_sigma_km, "source note")}; they take priority

# Size bounds: r_km is the nominal radius; r_min_km / r_max_km are about +/-3 sigma, or the albedo range for H-only
# objects, widened by the tri-axial extent if given. They reflect size uncertainty only, not ephemeris uncertainty.

def sbdb_phys(target_id, timeout=30):
    """Raw SBDB physical parameters {name: {value, sigma, ref, ...}} plus '_fullname', from the shared cache
    (sbdb.py; also filled by pick.py) or the SBDB API. Returns None if SBDB cannot be reached and
    nothing is cached (failures are not cached)."""
    n = str(target_id).strip()
    hit, fresh = sbdb_cache.get(n, config.cache_path, getattr(config, "sbdb_max_age_days", 30))
    if fresh:
        return hit["phys"]
    try:
        resp = requests.get(U.URL_JPL_SBDB_API, params={"sstr": n, "phys-par": 1}, timeout=timeout)
        resp.raise_for_status()
        entry = sbdb_cache.entry_from_api(resp.json())
    except (requests.RequestException, ValueError) as e:
        print(f"SBDB lookup failed for {n}: {e}")
        if hit:
            return hit["phys"]                                    # stale data beats none
        from pysyzygos import offline                             # without network: the copies kept for offline use
        old = offline.phys_fallback(n)
        if old:
            print(f"  size data of {n} from the offline copy")
            return old["phys"]
        return None
    sbdb_cache.put({n: entry}, config.cache_path)
    return entry["phys"]


@functools.lru_cache(maxsize=None)
def get_asteroid_size(target_id, timeout=30):
    """Return dict(r_km, r_min_km, r_max_km, source, H, G), or None if nothing usable."""
    n = str(target_id).strip()
    pp = sbdb_phys(n, timeout)                 # also for overrides: H and G for the asteroid magnitude

    def num(name, key="value"):
        try:
            return float(pp[name][key])
        except (KeyError, TypeError, ValueError):
            return None

    H, G = (num("H"), num("G")) if pp else (None, None)
    if n in SIZE_OVERRIDES:
        r, sg, src = SIZE_OVERRIDES[n]
        return dict(r_km=r, r_min_km=max(r - 3*sg, 0.0), r_max_km=r + 3*sg, source=src, H=H, G=G)
    if pp is None:
        return None

    D = num("diameter")
    if D:
        sg = num("diameter", "sigma") or num("diameter_sigma") or 0.15 * D   # assume 15% if absent
        out = dict(r_km=D/2, r_min_km=max((D - 3*sg)/2, 0.0), r_max_km=(D + 3*sg)/2,
                   source=f"SBDB diameter (ref {pp['diameter'].get('ref', '?')})", H=H, G=G)
        ext = [float(x) for x in re.findall(r"[\d.]+", str(pp.get("extent", {}).get("value", "")))]
        if len(ext) >= 2:                      # tri-axial full dimensions -> semi-axes
            out["r_min_km"] = min(out["r_min_km"], min(ext)/2)
            out["r_max_km"] = max(out["r_max_km"], max(ext)/2)
        return out

    if H is None:
        return None                            # no diameter and no H: no size estimate possible

    Dp = lambda p: 1329.0 / np.sqrt(p) * 10**(-H/5)
    p = num("albedo")
    if p:
        return dict(r_km=Dp(p)/2, r_min_km=Dp(min(p*1.5, 1))/2, r_max_km=Dp(p/1.5)/2, source="H + SBDB albedo", H=H, G=G)
    return dict(r_km=Dp(0.14)/2, r_min_km=Dp(0.30)/2, r_max_km=Dp(0.05)/2, source="H only, albedo assumed", H=H, G=G)



def get_asteroid_ra_dec(target_id, utc_time, observer="EARTH", ref_frame="J2000", abcorr="LT+S"):
    """Calculates the high-precision RA and Dec of an asteroid using SPICE.

    Parameters:
    target_id (str): SPICE ID of the asteroid (e.g., '2000433' for Eros)
    utc_time (str): Target timestamp (e.g., '2026-11-05 04:15:30')
    observer (str): Observer location frame ('EARTH' or a topocentric ID)
    ref_frame (str): Inertial reference frame (typically 'J2000' or 'ICRF')
    abcorr (str): Aberration correction. Use 'LT+S' for occultations.
    """
    # 1. Load the essential SPICE kernels into the pool
    # Make sure these files are downloaded to your local working directory
    #try:
    #    spice.furnsh("naif0012.tls")  # Leapseconds kernel
    #    spice.furnsh("de440.bsp")  # Planetary ephemeris kernel
        # spice.furnsh("your_asteroid.bsp") # Uncomment and add your asteroid SPK here
    #except Exception as e:
    #    print(f"Kernel loading error: {e}")
    #    print(
    #        "Please ensure 'naif0012.tls' and 'de440.bsp' exist in this path."
    #    )
    #    return

    try:
        # 2. Convert human-readable UTC to Ephemeris Time (seconds past J2000)
        et = spice.str2et(utc_time)

        # 3. Compute the relative state vector (position and velocity)
        # Returns a 6-element list [x, y, z, vx, vy, vz] and light time
        state, lt = spice.spkezr(target_id, et, ref_frame, abcorr, observer)

        # Extract the rectangular position component vector [x, y, z]
        position = state[0:3]

        # 4. Convert rectangular coordinates to Spherical (Range, RA, Dec)
        # Output angles are explicitly returned in radians
        range_km, ra_rad, dec_rad = spice.recrad(position)

        # Convert the radian dimensions cleanly to degrees
        ra_deg = ra_rad * spice.dpr()
        dec_dec = dec_rad * spice.dpr()

        # Print clean results matrix
        print(f"Target SPICE ID   : {target_id}")
        print(f"Observation Time  : {utc_time} UTC")
        print(f"Ephemeris Time(ET): {et:.6f}")
        print("-" * 45)
        print(f"Right Ascension   : {ra_deg:12.6f}°")
        print(f"Declination       : {dec_dec:12.6f}°")
        print(f"Distance (Range)  : {range_km:12.3f} km")
        print(f"One-way Light Time: {lt:12.6f} seconds")

        return {"ra": ra_deg, "dec": dec_dec, "range": range_km, "et": et}

    except spice.utils.support_types.SpiceyError as e:
        print(f"\nSPICE Processing Error: {e}")
        print(
            f"Note: If it says target '{target_id}' was not found, you need to load"
        )
        print("the specific asteroid's .bsp kernel file via spice.furnsh().")
        sys.exit('Exiting as of error.')




AU_KM = 149597870.7

def apparent_mag_HG(et, target, H, G=0.15):
    ast_from_earth, _ = spice.spkpos(target, et, 'J2000', 'LT', '399')
    ast_from_sun, _   = spice.spkpos(target, et, 'J2000', 'LT', 'SUN')
    delta = np.linalg.norm(ast_from_earth) / AU_KM
    r     = np.linalg.norm(ast_from_sun) / AU_KM
    alpha = spice.vsep(ast_from_sun, ast_from_earth)      # phase angle at the asteroid, rad
    t = np.tan(alpha / 2)
    phi1, phi2 = np.exp(-3.33 * t**0.63), np.exp(-1.87 * t**1.22)
    return H + 5*np.log10(r * delta) - 2.5*np.log10((1 - G)*phi1 + G*phi2)


def besselian_offsets(et, star_vector, observer_geo, asteroid_target):
    """Offsets (km) of the shadow axis from the observer on the fundamental plane.
    x points east, y points celestial north; the value is asteroid axis minus observer."""
    # Plane basis: z toward the star, x east, y north
    z_axis = star_vector / np.linalg.norm(star_vector)
    x_axis = np.cross([0.0, 0.0, 1.0], z_axis)
    if np.linalg.norm(x_axis) < 1e-12:          # star at a celestial pole
        x_axis = np.array([1.0, 0.0, 0.0])
    x_axis /= np.linalg.norm(x_axis)
    y_axis = np.cross(z_axis, x_axis)
    M = np.vstack((x_axis, y_axis, z_axis))

    # Asteroid relative to the observer, with the light time from the observer (not from the Earth's centre: an
    # observer closer to the asteroid by z = R sin(star altitude) gets its light z/c sooner, up to 21 ms, while the
    # asteroid moves with its barycentric velocity; in the Earth's frame that is the aberration of the shadow's
    # direction, up to ~0.6 km at the surface; found against Occult, VERIFICATION.md section 3). 'CN', no stellar
    # aberration: aberration shifts the star and the asteroid alike. Observer fixed in ITRF93 (lon/lat in radians,
    # alt in km).
    from pysyzygos import earth                           # WGS84 (GPS) geodetic coordinates
    obs_itrf = spice.georec(observer_geo['lon'], observer_geo['lat'],
                            observer_geo['alt'], earth.A_KM, earth.F)
    state, _ = spice.spkcpo(str(asteroid_target), et, 'J2000', 'OBSERVER', 'CN', obs_itrf, '399', 'ITRF93')

    d = M @ np.asarray(state[:3])
    return d[0], d[1]


def get_besselian_miss_distance(*args):
    return np.hypot(*besselian_offsets(*args))

def event_context(et, star_dir, target, r_km, m_star, m_ast):
    """Event data as OWC's event page shows it (favorites panel): the target's distance (au) and its motion on the sky
    ("/h, RA x cos Dec and Dec, geocentric), the star's elongation from the Sun, the combined magnitude before the
    event, and the times the shadow is on the Earth (shadow_from_utc / shadow_to_utc: the shadow's centre within one
    Earth radius + the body's radius of the Earth's centre, i.e. any part of the shadow touching the Earth)."""
    from scipy.optimize import brentq
    def geo(t):
        return np.asarray(spice.spkpos(target, t, 'J2000', 'CN', '399')[0])
    a = geo(et)
    dist = float(np.linalg.norm(a))
    rd = [spice.recrad(geo(t))[1:] for t in (et - 60.0, et + 60.0)]
    dra = (rd[1][0] - rd[0][0] + math.pi) % (2 * math.pi) - math.pi
    dec = (rd[0][1] + rd[1][1]) / 2
    sun = np.asarray(spice.spkpos('SUN', et, 'J2000', 'LT+S', '399')[0])
    out = dict(dist_au=dist / AU_KM,
               motion_ra_ash=math.degrees(dra * math.cos(dec)) * 3600 * 30.0,      # per 120 s -> per hour
               motion_dec_ash=math.degrees(rd[1][1] - rd[0][1]) * 3600 * 30.0,
               sun_elong_deg=math.degrees(math.acos(float(np.clip(star_dir @ sun / np.linalg.norm(sun), -1, 1)))),
               m_combined=(-2.5 * math.log10(10 ** (-0.4 * m_star) + 10 ** (-0.4 * m_ast))
                           if m_ast is not None and np.isfinite(m_ast) else m_star),
               shadow_from_utc="", shadow_to_utc="")
    lim = corridor.EARTH_R_KM + r_km
    axis = lambda t: float(np.linalg.norm(np.cross(geo(t), star_dir)))   # shadow axis to the Earth's centre, km
    t0 = et + minimize_scalar(lambda dt: axis(et + dt), bounds=(-7200.0, 7200.0), method="bounded",
                              options={"xatol": 0.5}).x                    # offset from et: sub-second tolerance
    if axis(t0) < lim:
        times = []
        for sign in (-1, 1):
            step, far = 600.0, t0
            for _ in range(144):                                  # 10 min steps, up to a day each side
                far += sign * step
                if axis(far) > lim:
                    break
            else:
                break
            a_, b_ = (far, t0) if sign < 0 else (t0, far)
            times.append(brentq(lambda t: axis(t) - lim, a_, b_, xtol=0.1))
        if len(times) == 2:
            out.update(shadow_from_utc=spice.et2utc(times[0], "ISOC", 0), shadow_to_utc=spice.et2utc(times[1], "ISOC", 0))
    return out


def contact_times(et_ca, miss_km, r_km, speed_kms, star_dir, obs_geo, target):
    """(et_D, et_R): disappearance and reappearance at the site, where the distance from the shadow axis equals r_km,
    on both sides of the closest approach et_ca; None if the site is outside the shadow. For major bodies, whose
    events last minutes to hours (asteroids: the closest approach is enough)."""
    from scipy.optimize import brentq
    if not (miss_km < r_km) or not speed_kms or speed_kms <= 0:
        return None
    f = lambda et: get_besselian_miss_distance(et, star_dir, obs_geo, target) - r_km
    half = math.sqrt(r_km ** 2 - miss_km ** 2) / speed_kms
    out = []
    for sign in (-1, 1):
        step = max(2.0 * half, 60.0)
        far = et_ca + sign * step
        for _ in range(8):                                        # widen until outside the shadow
            if f(far) > 0:
                break
            far += sign * step
        else:
            return None
        a, b = (far, et_ca) if sign < 0 else (et_ca, far)
        out.append(brentq(f, a, b, xtol=1e-3))
    return tuple(out)


def event_metrics(et, star_dir, obs_geo, target, r_km, m_star, m_ast, dt=1.0):
    dx0, dy0 = besselian_offsets(et - dt, star_dir, obs_geo, target)
    dx1, dy1 = besselian_offsets(et + dt, star_dir, obs_geo, target)
    dx,  dy  = besselian_offsets(et,      star_dir, obs_geo, target)
    v     = np.hypot(dx1 - dx0, dy1 - dy0) / (2*dt)       # shadow speed vs observer, km/s
    b     = np.hypot(dx, dy)                               # impact parameter, km
    chord = 2*np.sqrt(max(r_km**2 - b**2, 0.0))
    drop  = 2.5*np.log10(1 + 10**(0.4*(m_ast - m_star)))
    return dict(speed_kms=v, chord_km=chord, duration_s=chord/v, mag_drop=drop)



def _up_j2000(et, obs_geo):
    lon, lat = obs_geo['lon'], obs_geo['lat']
    up_itrf = np.array([np.cos(lat)*np.cos(lon), np.cos(lat)*np.sin(lon), np.sin(lat)])
    return spice.pxform('ITRF93', 'J2000', et) @ up_itrf

def sun_alt_deg(et, obs_geo):
    sun, _ = spice.spkpos('SUN', et, 'J2000', 'LT+S', '399')
    return np.degrees(np.arcsin(_up_j2000(et, obs_geo) @ (sun / np.linalg.norm(sun))))

def alt_deg(et, direction, obs_geo):
    return np.degrees(np.arcsin(_up_j2000(et, obs_geo) @ (direction / np.linalg.norm(direction))))

def az_deg(et, direction, obs_geo):
    """Azimuth (deg, from north through east) of a J2000 direction at the site: the local east and north turned to
    J2000 with the Earth's real rotation (UT1, polar motion), as alt_deg."""
    lon, lat = obs_geo['lon'], obs_geo['lat']
    R = spice.pxform('ITRF93', 'J2000', et)
    east = R @ np.array([-np.sin(lon), np.cos(lon), 0.0])
    north = R @ np.array([-np.sin(lat)*np.cos(lon), -np.sin(lat)*np.sin(lon), np.cos(lat)])
    d = direction / np.linalg.norm(direction)
    return float(np.degrees(np.arctan2(d @ east, d @ north)) % 360.0)


def observable(et, star_dir, obs_geo, min_star_alt=config.MIN_STAR_ALT, max_sun_alt=config.MAX_SUN_ALT):
    star_alt = alt_deg(et, star_dir, obs_geo)
    sun_alt = sun_alt_deg(et, obs_geo)
    return bool(star_alt > min_star_alt and sun_alt < max_sun_alt), star_alt, sun_alt

def window_is_observable(et0, span, obs_geo, target_id, min_star_alt=config.MIN_STAR_ALT, max_sun_alt=config.MAX_SUN_ALT, alt_margin=config.ALT_MARGIN):
    for e in (et0 - span/2, et0, et0 + span/2):
        ast, _ = spice.spkpos(target_id, e, 'J2000', 'CN', '399')
        if (sun_alt_deg(e, obs_geo) < max_sun_alt and
                alt_deg(e, ast, obs_geo) > min_star_alt - alt_margin):
            return True
    return False




# ==========================================
# 3. EXECUTION AND TEST HARNESS
# ==========================================
def star_test (loc = EarthLocation(lat=40.7128*u.deg, lon=-74.0060*u.deg, height=10*u.m),
               center_time_utc = "2026-10-01T04:30:00", time_span = 24*3600,
               star_ra=np.radians(68.98), star_dec=np.radians(16.50),
               asteroid_id = "200019",
               r_asteroid_km = 50.0,
               r_search_km = 0.0):
    # Define Target Star Coordinates (ICRS / J2000)
    # Example: Aldebaran or target star of choice
    #star_ra = np.radians(68.98)   # RA in radians
    #star_dec = np.radians(16.50)  # Dec in radians
    
    # Unit vector pointing to the star
    star_direction = np.array([
        np.cos(star_dec) * np.cos(star_ra),
        np.cos(star_dec) * np.sin(star_ra),
        np.sin(star_dec)
    ])

    # Define Target Asteroid (SPICE ID or Name string if loaded in kernel)
    # For this demonstration template, we fall back to '301' (Moon) if specific asteroid .bsp isn't found
    #asteroid_id = "200019"  # Example SPICE ID for Asteroid 19 Fortuna

    # Define Observer Location via Astropy
    #loc = EarthLocation(lat=40.7128*u.deg, lon=-74.0060*u.deg, height=10*u.m)
    obs_geo = {
        'lon': loc.lon.to(u.rad).value,
        'lat': loc.lat.to(u.rad).value,
        'alt': loc.height.to(u.km).value
    }

    
    # Center-of-window Guess Time (UTC)
    # center_time_utc = "2026-10-01T04:30:00"

    #print (loc, obs_geo, center_time_utc)

    et_center = spice.str2et(center_time_utc)
    
    print(f"Targeting window around: {center_time_utc} UTC")
    print(f"Initial Ephemeris Time (ET): {et_center:.3f}\n")

    # Objective in seconds from et_center: the bounded solver's tolerance is sqrt(eps)*|x| + xatol/3, which for a raw
    # ET (~8.4e8 s) is ~12 s, i.e. tens of km of miss distance. With a small offset xatol really applies.
    def objective_func(dt):
        return get_besselian_miss_distance(et_center + dt, star_direction, obs_geo, asteroid_id)

    time_span2 = time_span/2
    print("Computing exact time of closest approach...")
    result = minimize_scalar(
        objective_func,
        bounds=(-time_span2, time_span2),
        method='bounded',
        options={'xatol': 1e-3, 'maxiter': 1000} # ~1 ms
    )

    if result.success:
        best_et = et_center + result.x
        min_distance = result.fun
        best_utc = spice.et2utc(best_et, "ISOC", 3)
        
        print("\n--- OCCULTATION SOLVER RESULTS ---")
        print(f"Time of Maximum Occultation: {best_utc} UTC")
        print(f"Minimum Shadow Axis Distance to Observer: {min_distance:.3f} km")
        
        # Real-world condition mapping:
        # Assuming an asteroid radius R_ast (e.g., 50 km)
        #r_asteroid_km = 50.0 
        if min_distance < r_asteroid_km:

            print(f"👉 SUCCESS: An occultation is PREDICTED at this site! Observer inside the shadow path.")
            print(f"*** Asterioid ", asteroid_id, " (", get_asteroid_name(asteroid_id), "), with star RA=",star_ra, " DE=", star_dec, " @ET=", best_et, ", UTC=", best_utc, " min dist=", min_distance, " km ", "***")
            if not observable(best_et, star_direction, obs_geo):
                print(f" ** BUT NOT OBSERVABLE, BELOW HORIZON OR LIMITS **")
                return { "best_utc": best_utc, "best_et": best_et, "min_distance": min_distance, "observable": "no" }
            return { "best_utc": best_utc, "best_et": best_et, "min_distance": min_distance,  "observable": "yes" }
            
        else:
            if min_distance < r_asteroid_km+r_search_km:
                if not observable(best_et, star_direction, obs_geo):
                    print(f" ** BUT NOT OBSERVABLE, BELOW HORIZON OR LIMITS **")
                    return { "best_utc": best_utc, "best_et": best_et, "min_distance": min_distance, "observable": "no, in search range" }
                return { "best_utc": best_utc, "best_et": best_et, "min_distance": min_distance,  "observable": "yes, in search range" }
            else:
                print(f"❌ MISS: Shadow path misses observer by {min_distance - r_asteroid_km:.3f} km.")
    else:
        print("Solver failed to converge on an event window.")

    return None



def screen_stars(ra_deg, dec_deg, target, et0, span, margin_km, step=60.0):
    ets = np.arange(et0 - span/2, et0 + span/2 + step, step)
    ast, _ = spice.spkpos(target, ets, 'J2000', 'CN', '399')      # astrometric, matches Gaia
    dist = np.linalg.norm(ast, axis=1)
    u_ast = ast / dist[:, None]
    ra, dec = np.radians(ra_deg), np.radians(dec_deg)
    s = np.column_stack((np.cos(dec)*np.cos(ra), np.cos(dec)*np.sin(ra), np.sin(dec)))
    chord = np.linalg.norm(s[:, None, :] - u_ast[None, :, :], axis=2)   # (stars, times)
    return np.where((chord * dist).min(axis=1) < margin_km)[0]          # ~plane distance, km




_seen = {}

def is_new_hit(target_id, star_id, et, tol=300.0):
    ets = _seen.setdefault((target_id, star_id), [])
    if any(abs(et - e) < tol for e in ets):
        return False
    ets.append(et)
    return True

def target_test(loc, event_time_utc, time_span, target_id, size, mag_lim=20.0, max_shadow_distance=0.0):
    obs_geo = {'lon': loc.lon.to(u.rad).value, 'lat': loc.lat.to(u.rad).value,
               'alt': loc.height.to(u.km).value}
    r_search = size['r_max_km']
    et0 = spice.str2et(event_time_utc)

    assert target_id in _loaded, f"fetch_target_orbit({target_id}) must run first"
    
    if not window_is_observable(et0, time_span, obs_geo, target_id):
        return          # skips Horizons position, Gaia query, screening, solver
    
    target = get_asteroid_ra_dec(target_id, utc_time=event_time_utc)     # cone centre only

    event_df = fetch_and_propagate_stars(target['ra'], target['dec'], event_time_utc, 10.0, mag_lim)
    if event_df is None or event_df.empty:
        return
    ra_col  = event_df.filter(regex=r'^ra_\d{8}$').columns[0]
    dec_col = event_df.filter(regex=r'^dec_\d{8}$').columns[0]

    idx = screen_stars(event_df[ra_col].to_numpy(), event_df[dec_col].to_numpy(),
                       target_id, et0, time_span, margin_km=6378 + r_search + config.max_shadow_dist) 
    print (f"Pre-Screening: {idx}")
    for row in event_df.iloc[idx].itertuples(index=False):
        handle_star(loc, obs_geo, target_id, size, row, ra_col, dec_col, et0, time_span, r_search, -np.inf, np.inf)


RUN = dict(candidates=0, gated=0, solves=0, hits=0, maps_s=0.0, calc_s=0.0)      # run statistics (see run_summary)
RUN_RECORDS = []         # this run's hits (for the online double-star check after the search)
DB, RUN_ID = None, None  # results database (db.py) and this run's id, set by the driver
LOCAL = None             # the local Gaia catalog (set by the driver), for the event previews


def write_preview(record, target_id, stem):
    """Event preview SVG (preview.py): stars of the local catalog around the target star at the event date,
    camera frame, asteroid track +/- 1 h; a planet or moon as a disk with its system's bodies, zoomed to them.
    Written to <map_dir>/<stem>.svg next to the KML."""
    from pysyzygos import preview
    fov = preview.camera_fov_arcmin(config.camera_focal_mm, config.camera_sensor_mm)
    field = max(config.preview_field_factor * max(fov), 10.0)
    et = record["best_et"]
    disks, sub, name, zoom = None, None, None, None
    if bodies.is_body(target_id):                        # the planet or moon as a disk, with its system's bodies
        b, disks, name = bodies.parse(target_id), [], bodies.name(target_id)
        for t in [t for t in bodies.GROUPS.get(b["group"], [target_id]) if t in bodies.LOADED]:
            try:                                         # bodies of this run (their kernels are loaded)
                v = np.asarray(spice.spkpos(bodies.parse(t)["alias"], et, 'J2000', 'CN', '399')[0])
                r_km = float(np.asarray(spice.bodvrd(str(bodies.parse(t)["naif"]), "RADII", 3)[1]).max())
            except Exception:
                continue
            _, a_, d_ = spice.recrad(v)
            disks.append(dict(ra=np.degrees(a_), dec=np.degrees(d_), r_arcsec=np.degrees(r_km / np.linalg.norm(v)) * 3600,
                              label=bodies.name(t), main=(bodies.parse(t)["naif"] == b["naif"]),
                              moon=bodies.parse(t)["kind"] == "moon"))
        # zoom: the system's bodies near the target (within 15'), at least 8 disk diameters, 2' minimum
        u0 = np.array([math.cos(math.radians(record["star_dec"])) * math.cos(math.radians(record["star_ra"])),
                       math.cos(math.radians(record["star_dec"])) * math.sin(math.radians(record["star_ra"])),
                       math.sin(math.radians(record["star_dec"]))])
        seps = []
        for dk in disks:
            u = np.array([math.cos(math.radians(dk["dec"])) * math.cos(math.radians(dk["ra"])),
                          math.cos(math.radians(dk["dec"])) * math.sin(math.radians(dk["ra"])), math.sin(math.radians(dk["dec"]))])
            sep = math.degrees(math.acos(float(np.clip(u @ u0, -1, 1)))) * 60 + dk["r_arcsec"] / 60
            if sep <= 15.0:
                seps.append(sep)
        main_r = max([dk["r_arcsec"] for dk in disks if dk["main"]] or [1.0]) / 60
        zoom = float(max(2.4 * max(seps or [0.0]), 16 * main_r, 2.0))
        field = zoom
        dur = record.get("duration_s") or 0.0
        sub = (f"Gaia DR3 {record['star']} \u00b7 G {record['mag']:.2f} \u00b7 "
               + (f"D {record['d_utc'][11:21]} \u00b7 R {record['r_utc'][11:21]} UT \u00b7 {dur / 60:.1f} min"
                  if record.get("d_utc") else f"passes {record['min_distance'] - record['r_km']:.0f} km outside the limb"))
    stars = LOCAL.cone(record["star_ra"], record["star_dec"], field / 60 * 0.75, config.preview_mag_limit)
    ra, de = corridor.propagate_linear(stars, 2000.0 + et / (365.25 * 86400) - corridor.GAIA_EPOCH_YEAR)
    def radec(t):
        _, a, d = spice.recrad(spice.spkpos(target_id, t, 'J2000', 'CN', '399')[0])
        return np.degrees(a), np.degrees(d)
    # track span: about a quarter of the field, between 30 min and 12 h each side
    (a0, d0), (a1, d1) = radec(et - 600.0), radec(et + 600.0)
    rate = np.hypot((a1 - a0) * np.cos(np.radians(d0)), d1 - d0) * 60 / 20.0            # arcmin per minute
    span = int(np.clip(field / 4 / max(rate, 1e-9), 30 if zoom is None else 2, 720))
    track = [(m, *radec(et + 60.0 * m)) for m in np.linspace(-span, span, 13)]
    # the searched strip (corridor.plan_corridor): Earth radius + body radius + reach, at the event distance
    corr_km = corridor.EARTH_R_KM + float(record.get("r_max_km") or record.get("r_km") or 0.0) + float(config.max_shadow_dist)
    delta = float(np.linalg.norm(spice.spkpos(target_id, et, 'J2000', 'CN', '399')[0]))
    svg = preview.render_svg(dict(ra=ra, dec=de, g=stars.phot_g_mean_mag.to_numpy()),
                             dict(ra=record["star_ra"], dec=record["star_dec"], g=record["mag"]), track, fov,
                             config.preview_field_factor,
                             title=f"{record['target_name']}  {record['best_utc'][:19].replace('T', ' ')} UT",
                             subtitle=sub or (f"Gaia DR3 {record['star']} \u00b7 G {record['mag']:.2f} \u00b7 drop "
                                      f"{record['mag_drop']:.2f} mag \u00b7 max {record['max_duration_s']:.2f} s \u00b7 "
                                      f"miss {record['min_distance']:.1f} km"), disks=disks, body_name=name,
                             field_arcmin=zoom, corridor_arcsec=np.degrees(corr_km / delta) * 3600, corridor_km=corr_km)
    os.makedirs(config.map_dir, exist_ok=True)
    with open(f"{config.map_dir}/{stem}.svg", "w", encoding="utf-8") as f:
        f.write(svg)


def write_globe(record, target_id, stem, star_dir, paths, sigma3, size, corr):
    """Whole-Earth view of the event (globe.py) as <map_dir>/<stem>_globe.svg."""
    from pysyzygos import globe
    stars = None
    if LOCAL is not None:
        cat = LOCAL.cone(record["star_ra"], record["star_dec"], 1.42, min(float(record["mag"]) + 1.5, 13.0))
        ra, de = corridor.propagate_linear(cat, 2000.0 + record["best_et"] / (365.25 * 86400) - corridor.GAIA_EPOCH_YEAR)
        stars = (ra, de, cat.phot_g_mean_mag.to_numpy())
    of_date = None
    try:
        from astropy.coordinates import TETE
        c = SkyCoord(ra=record["star_ra"] * u.deg, dec=record["star_dec"] * u.deg, frame="icrs").transform_to(
            TETE(obstime=Time(record["best_utc"], scale="utc")))
        of_date = (float(c.ra.deg), float(c.dec.deg))
    except Exception:
        pass
    d = globe.globe_data(spice, record, target_id, star_dir, paths, sigma3,
                         site=(config.LON, config.LAT, config.site.get("name", config.site_name)), stars=stars,
                         size=size, run_utc=datetime.fromtimestamp(T_START).strftime("%Y-%m-%dT%H:%M:%S"),
                         corrections=corr, of_date=of_date, style=getattr(config, "globe_style", "color"),
                         page=getattr(config, "globe_page", "A4"))
    with open(f"{config.map_dir}/{stem}_globe.svg", "w", encoding="utf-8") as f:
        f.write(globe.render_svg(d))


def save_path_debug(fname, paths, record, target_id, star_dir, sigma3):
    """Debug (config debug_save_paths): the event's geodetic shadow path as NumPy .npz, for later verification.
    Arrays: one per line of paths.shadow_path ('center', 'edge_plus', 'edge_minus', 'sigma1_plus', ...), each (n, 4)
    float64: ET (s, TDB), longitude (deg, east +), latitude (deg, geodetic on the WGS84 ellipsoid at height 0 m, as
    Occult's default output; Earth orientation ITRF93), centre-line duration (s,
    NaN where none); and the event: target_id, target_name, star (Gaia DR3 source_id), star_ra / star_dec (deg, the
    corrected direction the path uses), star_dir (J2000 unit vector), mag, best_utc, best_et, r_km, sigma3_km,
    min_distance_km, site (lon, lat, ele m), version. Read: d = np.load(fname); d['center'][:, 1:3]; str(d['best_utc'])."""
    plain = {k: v for k, v in paths.items() if k != "pm_alts"}
    plain.update({f"pm_{i}": pts for i, (_, pts) in enumerate(paths.get("pm_alts") or [], 1)})   # other proper motions
    lines = {name: np.array([(et, lon, lat, np.nan if dur is None else dur) for et, lon, lat, dur in pts], float)
             .reshape(-1, 4) for name, pts in plain.items()}
    np.savez(fname, **lines, line_names=np.array(list(plain)),
             pm_labels=np.array([lab for lab, _ in paths.get("pm_alts") or []] or [""]), columns=np.array(["et", "lon_deg", "lat_deg", "dur_s"]),
             target_id=np.array(str(target_id)), target_name=np.array(str(record.get("target_name", ""))),
             star=np.array(int(record["star"]), dtype=np.int64), star_ra=float(record["star_ra"]),
             star_dec=float(record["star_dec"]), star_dir=np.asarray(star_dir, float), mag=float(record["mag"]),
             best_utc=np.array(str(record["best_utc"])), best_et=float(record["best_et"]), r_km=float(record["r_km"]),
             sigma3_km=float(sigma3), min_distance_km=float(record["min_distance"]),
             site=np.array([config.LON, config.LAT, config.ELE], float), version=np.array(__version__),
             ellipsoid=np.array("WGS84 a=6378.137 km f=1/298.257223563"), height_m=0.0)


def owc_opt():
    """The chosen site's equipment for screen.owc_limit / extinction_loss (from pysyzygos_config, i.e. sites.py)."""
    return dict(aperture=config.pick_aperture_cm, frames=config.pick_frames, mag_adjust=config.pick_mag_adjust,
                extinction=config.pick_extinction)


def handle_star(loc, obs_geo, target_id, size, row, ra_col, dec_col, et_guess, bracket_s, r_search, win_lo, win_hi,
                t_start=None):
    """Refine one candidate star with the exact solver, log it (CSV, KML map) if it is a real, observable hit.
    The solver searches et_guess +/- bracket_s/2. win_lo / win_hi: ET limits of the run (an event outside them
    belongs to a neighbouring run). t_start: when work on this candidate began (for calc_s). Returns True if logged."""
    t_start = t_start or time.time()
    RUN["solves"] += 1
    ra, dec = np.radians(getattr(row, ra_col)), np.radians(getattr(row, dec_col))
    corr = {"parallax_mas": 0.0, "deflection_mas": 0.0}
    if getattr(config, "star_parallax", True) or getattr(config, "light_deflection", True):
        # corrected direction at the estimated event time: both change by micro-arcseconds within the solver window
        u0 = np.array([np.cos(dec)*np.cos(ra), np.cos(dec)*np.sin(ra), np.sin(dec)])
        u1, corr = astrometry.corrected_star_dir(spice, u0, float(getattr(row, "parallax", np.nan)), et_guess, target_id,
                                                 parallax=getattr(config, "star_parallax", True),
                                                 deflection=getattr(config, "light_deflection", True),
                                                 bodies=bodies.deflectors(target_id))
        ra, dec = np.arctan2(u1[1], u1[0]) % (2*np.pi), np.arcsin(np.clip(u1[2], -1.0, 1.0))
    res = star_test(loc, spice.et2utc(et_guess, "ISOC", 3), bracket_s, ra, dec, target_id, r_search, config.max_shadow_dist)
    if res is None:
        print (f" --- miss --- ")
        return False
    # minimum on the bracket edge is not a real minimum; a neighbouring window/candidate finds it
    if min(res['best_et'] - (et_guess - bracket_s/2), (et_guess + bracket_s/2) - res['best_et']) < 1.0:
        print (f" --- not real --- ")
        return False
    if not (win_lo <= res['best_et'] <= win_hi):
        print (f" --- outside run window --- ")
        return False
    if not is_new_hit(target_id, row.source_id, res['best_et']):
        print (f" --- not a hit --- ")
        return False
    star_dir = np.array([np.cos(dec)*np.cos(ra), np.cos(dec)*np.sin(ra), np.sin(dec)])
    ok, star_alt, sun_alt = observable(res['best_et'], star_dir, obs_geo)
    if not ok:
        print (f" --- not visible --- ")
        return False                                   # drop this line to log invisible events too
    m_ast = (apparent_mag_HG(res['best_et'], target_id, size['H'], size.get('G') or 0.15)
             if size.get('H') is not None else np.nan)
    met = event_metrics(res['best_et'], star_dir, obs_geo, target_id, size['r_km'], row.phot_g_mean_mag, m_ast)
    if np.isfinite(met['mag_drop']) and met['mag_drop'] < getattr(config, "min_mag_drop", 0.1):
        print (f" --- too low mag drop dM = {met['mag_drop']} --- ")
        return False
    moon = moon_info(res['best_et'], star_dir, obs_geo)

    record = dict(target_id=target_id, target_name=get_asteroid_name(target_id),
                  best_utc=res['best_utc'], best_et=res['best_et'],
                  min_distance=res['min_distance'], margin_km=res['min_distance'] - size['r_km'],
                  r_km=size['r_km'], r_min_km=size['r_min_km'], r_max_km=size['r_max_km'],
                  r_search_km=r_search, size_source=size['source'],
                  star=row.source_id, mag=row.phot_g_mean_mag,
                  star_ra=np.degrees(ra), star_dec=np.degrees(dec),
                  star_alt=star_alt, sun_alt=sun_alt, m_ast=m_ast, **met, **moon,
                  observable=res['observable'],
                  corr_parallax_mas=corr["parallax_mas"], corr_deflection_mas=corr["deflection_mas"])
    dx, dy = besselian_offsets(res['best_et'], star_dir, obs_geo, target_id)
    record.update(offset_east_km=dx, offset_north_km=dy,
                  max_duration_s=2*size['r_km']/met['speed_kms'])
    # OWC observability with atmospheric extinction at the star's altitude (upper size bound, as the pick tool)
    opt = owc_opt()
    ext = float(screen.extinction_loss(star_alt, opt))
    record.update(airmass=float(screen.airmass(star_alt)), extinction_mag=ext,
                  mag_margin=float(screen.owc_limit(2*size['r_max_km']/met['speed_kms'], opt)) - row.phot_g_mean_mag - ext,
                  calc_s=time.time() - t_start)
    # close and double stars (doubles.py): neighbours whose light stays in the camera image; online check after the run
    rad = float(getattr(config, "companion_radius_arcsec", 4.0))
    comps, flags, near = [], {}, None
    if LOCAL is not None:
        years = 2000.0 + res['best_et'] / (365.25 * 86400) - corridor.GAIA_EPOCH_YEAR
        near = LOCAL.cone(record["star_ra"], record["star_dec"], (rad + 3.0) / 3600.0)
        comps = doubles.companions(near, row.source_id, record["star_ra"], record["star_dec"], row.phot_g_mean_mag,
                                   years, rad)
        flags = doubles.star_flags(near, row.source_id, years)      # format-2 catalog with its quality part
    record.update(doubles.fields(comps, row.phot_g_mean_mag, m_ast, "local" if LOCAL is not None else "none", flags))
    # chance that the shadow covers the site, from the path uncertainty (Horizons 3-sigma RSS, else the default)
    if bodies.is_body(target_id):                        # planet or moon: no Horizons RSS; rough per-body value
        sigma3_h, src = bodies.sigma3_km(target_id), "ephemeris estimate"
    else:
        perr = path_error(target_id, res['best_utc'])
        sigma3_h, src = (perr or {}).get("sigma3_km"), "Horizons"
    sigma3 = sigma3_h or config.default_sigma3_km
    ast_sigma1 = sigma3 / 3.0
    # supplement star: its own position uncertainty at the event date (no or a poor proper motion) widens the path
    star_kind = int(getattr(row, "star_kind", 0) or 0)
    s_mas = gaia_local.star_sigma_mas(star_kind, getattr(row, "ruwe", None), getattr(row, "pos_err", None),
                                      getattr(row, "pm_err", None),
                                      2000.0 + res['best_et'] / (365.25 * 86400) - corridor.GAIA_EPOCH_YEAR)
    s_km, pm_alts = None, []
    if star_kind >= gaia_local.KIND_2P and getattr(config, "pm_alternatives", True):
        # 2-parameter star: the other proper-motion estimates (VizieR); their spread is the realistic uncertainty
        try:
            from pysyzygos import pmcheck
            yrs = 2000.0 + res['best_et'] / (365.25 * 86400) - corridor.GAIA_EPOCH_YEAR
            pe = getattr(row, "pos_err", None)
            pm_alts = pmcheck.estimates(float(row.ra), float(row.dec), float(row.phot_g_mean_mag),
                                        used=(float(row.pmra), float(row.pmdec)), years=yrs, ra_err=pe, dec_err=pe)
            spread = pmcheck.spread_mas(pm_alts)
            if spread and spread > (s_mas or 0.0):
                s_mas = spread
        except Exception as ex:                                       # offline: the quoted error only
            print(f" --- proper-motion estimates not checked: {ex}")
            pm_alts = []
    if s_mas:
        d_km = float(np.linalg.norm(spice.spkpos(str(target_id), res['best_et'], 'J2000', 'CN', '399')[0]))
        s_km = s_mas * d_km * np.pi / 648000000.0
        sigma3 = 3.0 * float(np.hypot(ast_sigma1, s_km))
        if not record.get("star_err_smaa_mas"):                # the star's error ellipse (circle) for the favorites
            record.update(star_err_smaa_mas=s_mas, star_err_smia_mas=s_mas, star_err_pa_deg=0.0)
    record.update(path_sigma1_km=sigma3 / 3.0, sigma_source=(src if sigma3_h else "default") + (" + star" if s_km else ""),
                  p_site=site_probability(res['min_distance'], size['r_km'], sigma3 / 3.0))
    contacts = []
    record["kind"] = bodies.kind(target_id)
    if bodies.is_body(target_id):                        # disappearance and reappearance at the site
        ct = contact_times(res['best_et'], res['min_distance'], size['r_km'], met['speed_kms'], star_dir, obs_geo,
                           target_id)
        record.update(d_utc=spice.et2utc(ct[0], "ISOC", 2) if ct else "", r_utc=spice.et2utc(ct[1], "ISOC", 2) if ct else "",
                      duration_s=(ct[1] - ct[0]) if ct else 0.0)
        if ct:
            contacts = [("D", record["d_utc"], ct[0], None), ("R", record["r_utc"], ct[1], None)]
    if not bodies.is_body(target_id) and perr and perr.get("smaa_mas") is not None:   # error ellipse (1 sigma)
        record.update(ast_err_smaa_mas=perr["smaa_mas"], ast_err_smia_mas=perr["smia_mas"], ast_err_pa_deg=perr["pa_deg"])
    try:                                                 # OWC-style event data (favorites panel); never fatal
        record.update(event_context(res['best_et'], star_dir, target_id, size['r_km'], row.phot_g_mean_mag, m_ast))
    except Exception as ex:
        print(f"(event data skipped: {ex})")
    RUN_RECORDS.append(record)
    # supplement stars (gaia_local: RUWE >= 1.4 or 2-parameter): flagged; new fields at the end of the record
    kind_, ruwe_ = int(getattr(row, "star_kind", 0) or 0), getattr(row, "ruwe", float("nan"))
    record.update(star_kind=kind_, star_ruwe=float(ruwe_) if ruwe_ is not None else float("nan"),
                  star_flag=gaia_local.star_flag(kind_, ruwe_), ast_sigma1_km=ast_sigma1,
                  star_sigma_mas=s_mas if s_mas else float("nan"), star_sigma_km=s_km if s_km else float("nan"))
    record.update(star_az=az_deg(res['best_et'], star_dir, obs_geo))     # the report's compass direction (exact UT1)
    pm_e = getattr(row, "pm_err", float("nan"))                         # the catalog's proper motion and its source
    record.update(star_pmra=float(getattr(row, "pmra", float("nan"))), star_pmdec=float(getattr(row, "pmdec", float("nan"))),
                  star_pm_err=float(pm_e) if pm_e is not None else float("nan"),
                  star_pm_source=gaia_local.pm_source(kind_))
    if pm_alts:                                                       # the other estimates (pmcheck)
        from pysyzygos import pmcheck
        sp = pmcheck.spread_mas(pm_alts)
        record.update(star_pm_spread_mas=round(sp, 1),
                      star_pm_spread_km=round(sp * s_km / s_mas, 1) if s_km and s_mas else float("nan"),
                      star_pm_alts=pmcheck.summary(pm_alts, gaia_local.pm_source(kind_)))
    names = dict(star_ucac4="", star_tyc="", star_hip="")             # the star's other names (catalog part xref)
    if near is not None and "ucac4" in near:
        me = near[near["source_id"].astype("int64") == int(row.source_id)]
        if len(me):
            names = dict(star_ucac4=me["ucac4"].iloc[0], star_tyc=me["tyc"].iloc[0], star_hip=me["hip"].iloc[0])
    record.update(names)
    # the site's own horizon (horizon.py, OccultWatcher's [User Horizon]): behind it / near it, as a warning
    site_ = getattr(config, "site", None) or {}
    hz_flag, hz_alt, hz_sep = horizon.assess(site_.get("horizon") or [], record.get("star_alt"), record.get("star_az"),
                                             float(site_.get("horizon_margin", 15.0)))
    record.update(horizon_flag=hz_flag, horizon_alt=float("nan") if hz_alt is None else round(hz_alt, 1),
                  horizon_sep_deg=float("nan") if hz_sep is None else round(hz_sep, 1))
    if hz_flag == "behind" and site_.get("horizon_filter"):
        print(f"  {record['target_name']} at {record['best_utc'][:19]} UT: star behind the site's horizon "
              f"({record['star_alt']:.0f} deg, horizon {hz_alt:.0f} deg there): left out (horizon_filter)")
        return False
    print(f"* hit: {record['target_name']} at {record['best_utc'][:19]} UT"
          + (f"  (star: {record['star_flag']}" + (f"; path +-{s_km:.0f} km 1-sigma from the star" if s_km else "")
             + ")" if record["star_flag"] else ""))
    db.add_event(DB, RUN_ID, record, kind=record["kind"], contacts=contacts)   # hits_log.csv: exported after the run
    RUN["hits"] += 1
    RUN["calc_s"] += record["calc_s"]

    t_map = time.time()
    from pysyzygos.report import file_id                  # P:Jupiter -> P-Jupiter (no ':' in file names)
    stem = f"{file_id(target_id)}_{res['best_utc'][:16].replace(':','').replace('-','')}"     # KML and preview
    if config.write_maps and res['min_distance'] < r_search + config.max_shadow_dist:   # shadow + reach, as logged
        os.makedirs(config.map_dir, exist_ok=True)
        paths = shadow_path(target_id, star_dir, res['best_et'], size['r_km'], sigma3,
                            sat_km=binaries.zone_km(target_id))    # known satellite: its zone on the map
        paths["pm_alts"] = []                                         # the centre line with each other proper motion
        for e in pm_alts:
            if abs(e["east"]) + abs(e["north"]) < 1.0:
                continue
            try:
                from pysyzygos import pmcheck
                alt = shadow_path(target_id, pmcheck.shifted_dir(star_dir, e["east"], e["north"]), res['best_et'],
                                  size['r_km'], sigma3)
                paths["pm_alts"].append((e["label"], alt["center"]))
            except Exception as ex:
                print(f" --- no path for proper motion {e['label']}: {ex}")
        write_shadow_kml(paths, f"{config.map_dir}/{stem}.kml",
                         f"{record['target_name']} / Gaia {row.source_id}", observer=(config.LON, config.LAT))
        if getattr(config, "debug_save_paths", False):               # debug: the geodetic path for later checks
            try:
                save_path_debug(f"{config.map_dir}/{stem}_path.npz", paths, record, target_id, star_dir, sigma3)
            except Exception as ex:                                   # never stops the search
                print(f" --- no path debug file: {ex}")
        if getattr(config, "write_globes", True):
            try:
                write_globe(record, target_id, stem, star_dir, paths, sigma3, size, corr)
            except Exception as ex:                                   # a plot must never stop the search
                print(f" --- no globe plot: {ex}")
    if getattr(config, "write_previews", False) and LOCAL is not None:
        try:
            write_preview(record, target_id, stem)
        except Exception as ex:                                       # a preview must never stop the search
            print(f" --- no preview: {ex}")
    RUN["maps_s"] += time.time() - t_map
    return True


def run_summary(mode, t_main, t_pass1, t_pass2, n_targets):
    """Print the run statistics and the site/limits, and append them as one JSON line to <hits log>.runs.jsonl
    (read by report.py for the page header)."""
    t_end = time.time()
    n_ok = max(n_targets, 1)
    s = dict(run_utc=datetime.fromtimestamp(T_START, tz=__import__("datetime").timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"), mode=mode,
             version=__version__,
             window_start=str(config.ct), window_days=config.days, targets=n_targets,
             candidates=RUN["candidates"], gated=RUN["gated"], solves=RUN["solves"], hits=RUN["hits"],
             total_s=t_end - T_START, startup_s=t_main - T_START, init_s=t_pass1, search_s=t_pass2,
             maps_s=RUN["maps_s"], per_asteroid_s=(t_pass1 + t_pass2) / n_ok, search_per_asteroid_s=t_pass2 / n_ok,
             per_solve_s=(t_pass2 - RUN["maps_s"]) / max(RUN["solves"], 1),
             calc_per_hit_s=RUN["calc_s"] / max(RUN["hits"], 1),
             site=dict(name=config.site_name, desc=config.site.get("name", ""), mpc_code=config.site.get("mpc_code"),
                       lat=config.LAT, lon=config.LON,
                       ele=getattr(config, "ELE_MSL", config.ELE), geoid_m=getattr(config, "GEOID_M", 0.0),
                       ele_wgs84=config.ELE, ele_ref=config.site.get("ele_ref", "msl"),
                       aperture_cm=config.pick_aperture_cm, frames=config.pick_frames,
                       mag_adjust=config.pick_mag_adjust, extinction=config.pick_extinction),
             limits=dict(mag_limit=config.MAG_MIN, min_star_alt=config.MIN_STAR_ALT, max_sun_alt=config.MAX_SUN_ALT,
                         reach_km=config.max_shadow_dist, min_mag_drop=getattr(config, "min_mag_drop", 0.1),
                         min_dur_s=config.pick_min_dur_s),
             earth_pck=EARTH_PCK, targets_from=globals().get("TARGETS_FROM", ""),
             corrections=dict(star_parallax=bool(getattr(config, "star_parallax", True)),
                              light_deflection=bool(getattr(config, "light_deflection", True)),
                              gaia_pm_bias=bool(getattr(config, "gaia_pm_bias", True)),
                              star_rv=bool(getattr(config, "star_rv", True))))
    print(f"\nRun summary ({mode}): {n_targets} asteroids, {s['candidates']} candidates, {s['solves']} exact solves, "
          f"{s['hits']} hits")
    print(f"  total {s['total_s']:.1f} s = start-up {s['startup_s']:.1f} s + asteroid data {t_pass1:.1f} s + search "
          f"{t_pass2:.1f} s (of it maps {s['maps_s']:.1f} s)")
    print(f"  per asteroid {s['per_asteroid_s']:.2f} s (search {s['search_per_asteroid_s']:.2f} s); search time per "
          f"exact solve {s['per_solve_s'] * 1000:.0f} ms (with star lookup and scan); calculation per hit "
          f"{s['calc_per_hit_s'] * 1000:.0f} ms")
    if SKIPPED:
        s["skipped_targets"] = list(SKIPPED)
        print(f"  skipped (no orbit from JPL Horizons, e.g. a mistyped number): {', '.join(SKIPPED)}")
    db.finish_run(DB, RUN_ID, s)                         # results database; then the exports of the current series
    n = db.export(DB, config.hits_output_cvs_file, lst=getattr(config, "results_list", "main"))
    print(f"  results: {getattr(config, 'results_db', db.DEFAULT)}, current series {n} event(s) -> "
          f"{config.hits_output_cvs_file}")
    return s


def online_double_check(records):
    """After the search: Gaia archive check of this run's event stars (doubles.py; config gaia_online_check), one
    query for all; updates their rows in the hit log. Skipped quietly when off, offline or slow."""
    if not records or not getattr(config, "gaia_online_check", True):
        return
    # a format-2 catalog with its quality part has the star's flags, and every neighbour that matters (up to DMAG
    # fainter) when it reaches that deep with all stars (supplement on): the archive adds nothing for such events
    local_all = (LOCAL is not None and getattr(LOCAL, "quality", None) is not None and getattr(LOCAL, "sup", False))
    if local_all:
        skip = [r for r in records if float(r["mag"]) + doubles.DMAG <= LOCAL.gmax]
        records = [r for r in records if float(r["mag"]) + doubles.DMAG > LOCAL.gmax]
        if skip:
            print(f"* Gaia online check: {len(skip)} event star(s) fully covered by the local catalog (G <= "
                  f"{LOCAL.gmax:g} with Gaia's flags), not asked")
        if not records:
            return
        why = (f"stars fainter than G {LOCAL.gmax - doubles.DMAG:g}: neighbours up to {doubles.DMAG:g} mag fainter go "
               f"beyond the catalog's G {LOCAL.gmax:g}; Gaia's flags of the stars are local already")
    elif LOCAL is not None and hasattr(LOCAL, "quality") and LOCAL.quality is None:
        why = "the catalog has no quality part: Gaia's flags and neighbours from the archive"
    elif LOCAL is not None and hasattr(LOCAL, "quality"):
        why = "the high-RUWE stars are switched off: neighbours among them from the archive"
    else:
        why = "an old-format catalog (no Gaia flags in it): flags and neighbours from the archive"
    rad = float(getattr(config, "companion_radius_arcsec", 4.0))
    print(f"* Gaia online check of {len(records)} event star(s) (close and double stars; {why}) ...")
    archive = doubles.fetch_online([(r["star_ra"], r["star_dec"]) for r in records], rad)
    if archive is None:
        return
    upd = doubles.online_fields(records, rad, archive)
    n = db.update_events(DB, records, upd, lst=getattr(config, "results_list", "main"))
    flagged = sum(1 for u in upd if u["double_hint"])
    print(f"* Gaia online check: {n} event(s) updated, {flagged} with a close or double star note")


def target_test_corridor(loc, plan, target_id, size, local=None, stars_cands=None):
    """Replacement for the per-window target_test(): one call per asteroid for the whole run.
    plan = corridor.plan_corridor(...) (needs SPICE, build serially). local = gaia_local.LocalGaia.
    stars_cands = (stars, candidates) if already computed. Returns the number of logged hits."""
    obs_geo = {'lon': loc.lon.to(u.rad).value, 'lat': loc.lat.to(u.rad).value, 'alt': loc.height.to(u.km).value}
    r_search = size['r_max_km']
    stars, cands = stars_cands or corridor.corridor_candidates(plan, local)
    if cands.empty:
        return 0
    ets = plan['path']['ets']
    win_lo, win_hi = float(ets[0]), float(ets[-1])
    n_log = 0
    RUN["candidates"] += len(cands)
    for cand in cands.sort_values('et_guess').itertuples(index=False):
        t_start = time.time()
        # the observer's closest approach can be up to margin/speed away from the Earth-centre estimate
        bracket = corridor.solver_bracket_s(plan, cand.j)
        # cheap early gate (Sun and asteroid altitude) before any solver work
        if not window_is_observable(cand.et_guess, bracket, obs_geo, target_id):
            RUN["gated"] += 1
            continue
        # only the candidates need exact space motion: propagate each to its own event time
        prop = corridor.propagate_exact(stars.iloc[[cand.star]], spice.et2utc(cand.et_guess, "ISOC", 0),
                                        pm_bias=getattr(config, "gaia_pm_bias", True),
                                        rv=getattr(config, "star_rv", True))
        ra_col = prop.filter(regex=r'^ra_\d{8}$').columns[0]
        dec_col = prop.filter(regex=r'^dec_\d{8}$').columns[0]
        row = next(prop.itertuples(index=False))
        n_log += handle_star(loc, obs_geo, target_id, size, row, ra_col, dec_col, cand.et_guess, bracket,
                             r_search, win_lo, win_hi, t_start)
    return n_log


def resolve_targets():
    """targets_source "auto": the saved pick of this site covering the search window (picks), else the
    config list (targets.py or the manual one). Sets config.targets; returns a description for the run summary."""
    if getattr(config, "targets_source", "auto") != "auto":
        return f"list ({len(config.targets)} targets)"
    from pysyzygos import picks
    p = picks.best_for(config.site_name, str(config.ct)[:10], config.days, getattr(config, "picks_dir", "picks"),
                                config.LAT, config.LON)
    if p is None:
        print(f"* No saved pick for site {config.site_name} covers {str(config.ct)[:10]} + {config.days:g} d: "
              f"using the config list / targets.py ({len(config.targets)} targets)")
        return f"targets.py / config list ({len(config.targets)} targets)"
    config.targets = p["targets"]
    config.target_names = p["names"]
    print(f"* Targets: {picks.describe(p)}")
    return picks.describe(p)


if __name__ == "__main__":
    t_main = time.time()
    DB = db.connect(getattr(config, "results_db", db.DEFAULT))       # results database (db.py)
    if db.import_log(DB, config.hits_output_cvs_file):               # an older hit log, once
        print(f"* imported {config.hits_output_cvs_file} into {getattr(config, 'results_db', db.DEFAULT)}")
    RUN_ID, _ = db.start_run(DB, getattr(config, "search_mode", "corridor"),
                             new_series=bool(getattr(config, "results_new_series", False)),
                             lst=getattr(config, "results_list", "main"))
    mag_min = config.MAG_MIN
    TARGETS_FROM = resolve_targets()
    obs_loc = EarthLocation(lat=config.LAT*u.deg, lon=config.LON*u.deg, height=config.ELE*u.m)


    t0 = pd.Timestamp(config.ct)
    epochs = {'start': (t0 - pd.Timedelta(days=1)).strftime('%Y-%m-%d'),
              'stop':  (t0 + pd.Timedelta(days=config.days + 1)).strftime('%Y-%m-%d')}
    periods = (pd.date_range(start=config.ct, periods=int(config.days*86400/config.spn), freq=f"{config.spn}s")
                 .strftime("%Y-%m-%d %H:%M:%S").tolist())

    if getattr(config, "search_mode", "corridor") == "windows":    # old path: ~200 Gaia cones per asteroid
        t_w = time.time()
        for t in config.targets:
            if bodies.is_body(t):
                print(f"{t}: planets and moons need the corridor search mode, skipping")
                continue
            if not load_orbit(t, epochs):                           # once per target; unknown numbers: skipped
                continue
            size = get_asteroid_size(t)
            if size is None:
                print(f"No size data for {t}, skipping")
                continue
            print(f"Estimated/known target {t} size: {size['r_max_km']:.1f} km (H={size.get('H')}, G={size.get('G')})")
            for ctp in periods:
                target_test(obs_loc, ctp, config.spn + 600, t, size, mag_min)   # +10 min so windows overlap
        run_summary("windows", t_main, 0.0, time.time() - t_w, len(config.targets))
        spice.kclear()
        sys.exit(0)

    # stars come from the local Gaia copy (python gaia_local.py build); checked first, before any SPK work
    if not getattr(config, "gaia_local_dir", None):
        sys.exit("corridor mode needs the local Gaia catalog: set gaia_local_dir and run  pysyzygos setup")
    from pysyzygos import gaia_local
    local = gaia_local.LocalGaia(config.gaia_local_dir)         # raises if the catalog is incomplete
    LOCAL = local
    print(f"Using local Gaia catalog {config.gaia_local_dir} (G <= {local.gmax})")
    if mag_min > local.gmax:                                      # (a GUI or config limit beyond the catalog)
        print(f"Star limit G {mag_min:g} is fainter than the catalog: using G {local.gmax:g}")
        mag_min = local.gmax
    if float(getattr(config, "gaia_local_gmax", local.gmax)) < local.gmax - 1e-9 and abs(mag_min - config.gaia_local_gmax) < 1e-9:
        print(f"Note: gaia_local_gmax = {config.gaia_local_gmax:g} in pysyzygos_config.py caps the star limit at "
              f"G {mag_min:g}, the catalog goes to G {local.gmax:g} (set gaia_local_gmax = {local.gmax:g} to use it)")

    et0 = spice.str2et(t0.strftime("%Y-%m-%dT%H:%M:%S"))
    et1 = et0 + config.days * 86400.0

    # pass 1 (serial, SPICE): sizes, SPKs and one corridor plan per target

    print(
        f"Pass 1 (serial, SPICE): sizes, SPKs and one corridor plan per target"
    )

    t_p1 = time.time()
    plans = {}
    prefetch_orbits(config.targets, epochs)                         # missing orbit files: several downloads at once
    for t in config.targets:
        mag_lim = mag_min
        if bodies.is_body(t):                                      # planet or moon: kernel from Horizons, radii
            try:
                bodies.ensure_kernel(spice, t, et0, et1, config.cache_path)
            except Exception as ex:
                print(f"{t}: no ephemeris ({str(ex)[:160]}), skipping")
                continue
            size = bodies.size(spice, t)
            print(f"Major body {t}: radius {size['r_km']:.0f} km, stars G <= {mag_lim:g}")
        else:
            if not load_orbit(t, epochs):                           # once per target; unknown numbers: skipped
                continue
            size = get_asteroid_size(t)
            if size is None:
                print(f"No size data for {t}, skipping")
                continue
            print(f"Estimated/known target {t} size: {size['r_max_km']:.1f} km (H={size.get('H')}, G={size.get('G')})")
        plans[t] = (size, corridor.plan_corridor(t, et0, et1, size, mag_lim, config.max_shadow_dist,
                                                 min_drop=getattr(config, "min_mag_drop", 0.1),
                                                 step_s=getattr(config, "corridor_step_s", 600.0)))

    t_p1 = time.time() - t_p1

    # pass 2 (serial, SPICE): stars from the local catalog, scan and solve
    t_p2 = time.time()
    print(
        f"Pass 2 (serial, SPICE): stars from the local catalog, scan and solve"
    )
    for t, (size, plan) in plans.items():
        n = target_test_corridor(obs_loc, plan, t, size, local=local)
        print(f"{t}: {n} hit(s) logged")
    t_p2 = time.time() - t_p2
    online_double_check(RUN_RECORDS)
    run_summary("corridor", t_main, t_p1, t_p2, len(plans))
    spice.kclear()
