"""pathcheck.py - a favorite's geodetic shadow path, fresh, and its comparison with Occult's path listing.

    pysyzygos path-check run <key>                    # our path now: the search for this event only (today's orbit,
                                                      # this code), its path file and orbit files into the favorite
    pysyzygos path-check export <key> [--step 1.45]   # our path as a text table in Occult's layout
    pysyzygos path-check compare <key> <listing.txt>  # compare with Occult's listing: Markdown + CSV
    pysyzygos path-check keep <key>                   # also into owc_refs/occult_paths/ (private), with an index line

Files go to favorites/<key>/pathcheck/: path.npz (debug_save_paths of the search), the asteroid's SPK files (so a later
comparison uses the same orbit), meta.json (version, orbit solution, run time), our listing, Occult's listing as
given, compare_<stamp>.md / .csv. The method is that of VERIFICATION.md section 3: our path at exactly Occult's times
(paths.shadow_path, with each ground point's own light time), across / along the track, and in the fundamental plane
against the shadow axis as each point sees it (SPICE spkcpo), with a least-squares fit (constant offset; constant +
Earth rotation as a check). Both should be computed on the same day: the orbit changes.
"""
from pysyzygos.version import __version__
import argparse, calendar, glob, json, math, os, re, shutil, subprocess, sys, time
import numpy as np

DIRNAME = "pathcheck"
C_KMS = 299792.458
OMEGA_EARTH = 7.2921150e-5                                  # rad/s
SAMPLE_FRACTIONS = np.linspace(0.0, 1.0, 11)                # the rows shown in the report: start to end
ROUNDING_M = 31.0                                           # Occult's listing: whole arcseconds, ~31 m in latitude


# ----------------------------------------------------------------------------------------------- Occult's listing
def dms(tok):
    """['-15', '40', '42'] or ['-0', '59', '6'] -> degrees (the sign on the first token, also for -0)."""
    neg = tok[0].startswith("-")
    v = abs(float(tok[0])) + float(tok[1]) / 60.0 + float(tok[2]) / 3600.0
    return -v if neg else v


def _occult_row(line):
    """One row of Occult's own layouts, or None: centre longitude, latitude (d m s each) and UT (h m s) are required;
    star altitude/azimuth and Sun altitude, then the limits (8 longitude/latitude pairs by time, or 4 latitudes by
    longitude) are taken when present and plausible. Signs may stand apart ("- 9 57 38"); extra columns are ignored."""
    t = line.split()
    merged, i = [], 0
    while i < len(t):
        if t[i] in ("-", "+") and i + 1 < len(t):
            merged.append(t[i].replace("+", "") + t[i + 1]); i += 2
        else:
            merged.append(t[i]); i += 1
    num = [x for x in merged if re.fullmatch(r"[-+]?\d+(\.\d+)?", x)]
    lead = 0
    while lead < len(merged) and re.fullmatch(r"[-+]?\d+(\.\d+)?", merged[lead]):
        lead += 1
    if lead < 9:
        return None
    v = merged[:lead]
    try:
        f = [float(x) for x in v]
    except ValueError:
        return None
    if not (abs(f[0]) <= 360 and 0 <= f[1] < 60 and 0 <= f[2] < 60 and abs(f[3]) <= 90 and 0 <= f[4] < 60
            and 0 <= f[5] < 60 and 0 <= f[6] < 48 and 0 <= f[7] < 60 and 0 <= f[8] < 61):
        return None
    row = dict(lon=dms(v[0:3]), lat=dms(v[3:6]), sec=f[6] * 3600 + f[7] * 60 + f[8], star_alt=None, star_az=None,
               sun_alt=None, l1=None, l2=None, e1=None, e2=None)
    rest = v[9:]
    if len(rest) >= 3 and -90 <= float(rest[0]) <= 90 and 0 <= float(rest[1]) <= 360 and -90 <= float(rest[2]) <= 90 \
            and all(re.fullmatch(r"[-+]?\d+", x) for x in rest[:3]):
        row.update(star_alt=float(rest[0]), star_az=float(rest[1]), sun_alt=float(rest[2]))
        rest = rest[3:]
    try:
        if len(rest) >= 24:                                  # by time: each limit as a (longitude, latitude) pair
            lim = [dms(rest[3 * k: 3 * k + 3]) for k in range(8)]
            row.update(l1=(lim[0], lim[1]), l2=(lim[2], lim[3]), e1=(lim[4], lim[5]), e2=(lim[6], lim[7]))
        elif len(rest) >= 6:                                 # by longitude: the limits as latitudes at this longitude
            lim = [dms(rest[3 * k: 3 * k + 3]) for k in range(len(rest) // 3)][:4]
            pairs = [(row["lon"], la) for la in lim]
            row.update(l1=pairs[0], l2=pairs[1], e1=pairs[2] if len(pairs) > 2 else None,
                       e2=pairs[3] if len(pairs) > 3 else None)
    except (ValueError, IndexError):
        pass
    return row


def angle(text):
    """Degrees from one field: '-15.6783', '15 40 42', '-15:40:42.5', '15°40'42"W', 'W 15 40 42', '15d40m42s', a
    Unicode minus; S and W (letters) negative. ValueError if it is not an angle."""
    t = str(text).strip().replace("−", "-")
    if not t:
        raise ValueError("empty")
    letters = re.findall(r"[A-Za-z]", re.sub(r"(?<=\d)[dms](?=\d|\s|$)", " ", t))
    if len(letters) > 1 or (letters and letters[0].upper() not in "NSEW"):
        raise ValueError(t)
    neg = bool(re.match(r"^\s*[A-Za-z]?\s*-", t)) or (letters and letters[0].upper() in "SW")
    nums = re.findall(r"\d+(?:[.,]\d+)?", t)
    if not 1 <= len(nums) <= 3:
        raise ValueError(t)
    v = sum(float(n.replace(",", ".")) / 60.0 ** k for k, n in enumerate(nums))
    return -v if neg else v


def ut_time(text):
    """(seconds of the day, 'YYYY-MM-DD' or None) from one field: '11:03:39.82', '11 3 39.82', '11h03m39.8s',
    '2019-07-29T11:03:39.82Z', '2019 Jul 29 11:03:39', or decimal hours ('11.0611'). ValueError otherwise."""
    t = str(text).strip()
    date = None
    m = re.search(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", t)
    if m:
        date = f"{int(m[1]):04d}-{int(m[2]):02d}-{int(m[3]):02d}"
        t = t[m.end():]
    else:
        m = re.search(r"(\d{4})\s+([A-Za-z]{3})[a-z]*\s+(\d{1,2})", t)
        if m and m[2].title() in calendar.month_abbr:
            date = f"{int(m[1]):04d}-{list(calendar.month_abbr).index(m[2].title()):02d}-{int(m[3]):02d}"
            t = t[m.end():]
    nums = re.findall(r"\d+(?:[.,]\d+)?", t)
    f = [float(n.replace(",", ".")) for n in nums]
    if len(f) >= 3 and f[0] < 48 and f[1] < 60 and f[2] < 61:
        return f[0] * 3600 + f[1] * 60 + f[2], date
    if len(f) == 2 and f[0] < 48 and f[1] < 60:
        return f[0] * 3600 + f[1] * 60, date
    if len(f) == 1 and re.search(r"[.,]", nums[0]) and f[0] < 48:
        return f[0] * 3600.0, date                           # decimal hours
    raise ValueError(text)


_COL = dict(lon=r"lon|λ|lambda", lat=r"lat|φ|phi", time=r"^\W*(u\.?\s?t\.?c?|time|zeit|epoch|date.?time)\b",
            alt=r"alt|elev|höhe")


def _find_cols(fields):
    """Column indices of longitude, latitude, time and the star's altitude from a header row (names), preferring a
    centre/centre-line column where there are several; None where not found."""
    low = [f.strip().lower() for f in fields]
    def pick(key, avoid=r"limit|edge|error|sigma|sun|moon"):
        cand = [i for i, f in enumerate(low) if re.search(_COL[key], f) and not re.search(avoid, f)]
        cent = [i for i in cand if re.search(r"cent|center|centre|mitte", low[i])]
        return (cent or cand or [None])[0]
    cols = dict(lon=pick("lon"), lat=pick("lat"), time=pick("time", r"limit|edge|error|sigma|dur|length"),
                alt=pick("alt", r"limit|edge|error|sigma|sun|moon|crn|elevation.?model|height|ellip"))
    return cols if None not in (cols["lon"], cols["lat"], cols["time"]) else None


def _table_rows(text):
    """Rows of a table with a header row naming longitude, latitude and time (CSV, tab, semicolon or spaces; any extra
    columns); None when no such header is found."""
    lines = text.splitlines()
    for k, line in enumerate(lines):
        delim = next((d for d in ("\t", ";", ",") if line.count(d) >= 2), None)
        fields = line.split(delim) if delim else line.split()
        cols = _find_cols(fields)
        if not cols:
            continue
        rows = []
        for data in lines[k + 1:]:
            if not data.strip():
                continue
            f = [x.strip().strip('"') for x in (data.split(delim) if delim else data.split())]
            if not delim and len(f) != len(fields):
                continue                                     # spaces: only rows with one token per column
            try:
                lon, lat = angle(f[cols["lon"]]), angle(f[cols["lat"]])
                sec, date = ut_time(f[cols["time"]])
            except (ValueError, IndexError):
                continue
            if not (-360 <= lon <= 360 and -90 <= lat <= 90):
                continue
            alt = None
            if cols["alt"] is not None:
                try:
                    alt = float(f[cols["alt"]].replace(",", "."))
                except (ValueError, IndexError):
                    alt = None
            rows.append(dict(lon=lon, lat=lat, sec=sec, date=date, star_alt=alt, star_az=None, sun_alt=None,
                             l1=None, l2=None, e1=None, e2=None))
        if rows:
            return rows
    return None


def parse_listing(text):
    """Rows of a path listing: list of dicts lon, lat (deg), sec (UT seconds of the day; 'date' when the listing
    gives one), star_alt (None if not given), star_az, sun_alt, l1, l2, e1, e2 ((lon, lat) of the path and error
    limits, None if not given). Only the centre line's longitude, latitude and time are needed; everything else is
    optional and extra columns are ignored. Read as (1) a table whose header row names longitude, latitude and time
    (CSV, tab, semicolon or spaces; decimal or d m s values, N/S/E/W, ISO times), else (2) Occult's own layouts: by
    time (limits as longitude/latitude pairs) or by longitude (limits as latitudes), signs standing apart for short
    degrees ("- 9 57 38"). Also returns the title line ("Occultation of ...")."""
    title = next((ln.strip() for ln in text.splitlines() if ln.strip().lower().startswith("occultation of")), "")
    rows = _table_rows(text)
    if rows is None:
        rows = [r for r in (_occult_row(ln) for ln in text.splitlines()) if r]
    return rows, title


def parse_header(text):
    """Optional facts from Occult's plot header pasted with the listing: orbit ("JPL#1016"), the star's astrometric
    RA/Dec ("RA = 5 20 54.7283", "Dec = 40 53 5.373"), the asteroid's diameter ("Dia = 5.0"). Missing ones are None."""
    out = dict(jpl=None, star_ra=None, star_dec=None, dia_km=None)
    if m := re.search(r"JPL#\s*(\d+)", text):
        out["jpl"] = m[1]
    if m := re.search(r"\bRA\s*=?\s*(\d+)\s+(\d+)\s+([\d.]+)", text):
        out["star_ra"] = 15.0 * (int(m[1]) + int(m[2]) / 60.0 + float(m[3]) / 3600.0)
    if m := re.search(r"\bDec\s*=?\s*([+-]?)\s*(\d+)\s+(\d+)\s+([\d.]+)", text):
        v = int(m[2]) + int(m[3]) / 60.0 + float(m[4]) / 3600.0
        out["star_dec"] = -v if m[1] == "-" else v
    if m := re.search(r"Dia\s*=\s*([\d.]+)\s*(?:\+-|±)?", text):
        out["dia_km"] = float(m[1])
    return out


def fmt_dms(v, width=3):
    """Degrees -> Occult's '- 15 40 42' (sign apart, degrees right-aligned, whole seconds)."""
    sign = "-" if v < 0 else " "
    a = round(abs(v) * 3600.0)
    d, rest = divmod(a, 3600)
    m, s = divmod(rest, 60)
    return f"{sign}{d:{width}d} {m:2d} {s:2d}"


def fmt_ut(sec):
    h, rest = divmod(sec, 3600.0)
    m, s = divmod(rest, 60.0)
    return f"{int(h):2d} {int(m):2d} {s:5.2f}"


# ----------------------------------------------------------------------------------------------- the comparison math
def fit_plane(px, py, dvx, dvy, drx, dry):
    """Least squares of the plane offsets (km, per point) for (a) a constant offset and (b) a constant offset plus an
    Earth-rotation angle (partials drx, dry per radian). Returns {"const": (cx, cy, rms_km, max_km),
    "rot": (cx, cy, angle_rad, rms_km, max_km, s_cx, s_cy, s_angle)}; dvx/dvy (the shadow's motion) are kept for the
    direction of the offset."""
    n = len(px)
    y = np.column_stack([px, py]).reshape(-1)
    ex, ey = np.tile([1.0, 0.0], n), np.tile([0.0, 1.0], n)
    out = {}
    A = np.column_stack([ex, ey])
    sol, *_ = np.linalg.lstsq(A, y, rcond=None)
    res = y - A @ sol
    out["const"] = (sol[0], sol[1], float(np.sqrt(np.mean(res ** 2))), float(np.abs(res).max()))
    A = np.column_stack([ex, ey, np.column_stack([drx, dry]).reshape(-1)])
    sol, *_ = np.linalg.lstsq(A, y, rcond=None)
    res = y - A @ sol
    rms = float(np.sqrt(np.mean(res ** 2)))
    sig = np.sqrt(rms ** 2 * np.diag(np.linalg.inv(A.T @ A)))
    out["rot"] = (sol[0], sol[1], sol[2], rms, float(np.abs(res).max()), sig[0], sig[1], sig[2])
    return out


def sample_rows(rows):
    """Indices of the rows shown in the report: SAMPLE_FRACTIONS of the way through the listing."""
    n = len(rows)
    return sorted({int(round(f * (n - 1))) for f in SAMPLE_FRACTIONS}) if n else []


ARCSEC_M = 30.87          # 1" of latitude on the ground, m (the listing's coordinates are whole arcseconds)
R_EARTH_KM, C_KM_S = 6378.137, 299792.458


def summary(points):
    """Statistics of the compared points (dicts with across, along, dt, star_alt): all and star above 20 deg."""
    out = {}
    for label, sel in (("all", [p for p in points]), ("alt20", [p for p in points if p["star_alt"] >= 20])):
        if not sel:
            continue
        a = np.array([[p["across"], p["along"], p["dt"], p["dist"]] for p in sel])
        k = math.sqrt(len(sel))
        out[label] = dict(n=len(sel), across_min=a[:, 0].min(), across_max=a[:, 0].max(), across_mean=a[:, 0].mean(),
                          along_mean=a[:, 1].mean(), dt_min=a[:, 2].min(), dt_max=a[:, 2].max(),
                          dt_mean=a[:, 2].mean(), dist_max=a[:, 3].max(), across_rms=a[:, 0].std(),
                          across_sem=a[:, 0].std() / k, dt_rms=a[:, 2].std(), dt_sem=a[:, 2].std() / k)
    return out


def verdict(stats, fit, mas_per_km, speed_kms):
    """One line: across within the listing's rounding or not, the time difference, the plane offset."""
    s = stats.get("alt20") or stats["all"]
    acr = max(abs(s["across_min"]), abs(s["across_max"])) * 1000.0
    cx, cy, rms, _ = fit["const"]
    off = math.hypot(cx, cy)
    across = (f"across the track within the listing's rounding (largest {acr:.0f} m, rounding ~{ROUNDING_M:.0f} m)"
              if acr <= 1.5 * ROUNDING_M else f"across the track up to {acr:.0f} m (rounding ~{ROUNDING_M:.0f} m)")
    return (f"{across}; along the track Occult {'later' if s['dt_mean'] < 0 else 'earlier'} by "
            f"{abs(s['dt_mean']) * 1000:.0f} ms (mean); offset in the fundamental plane {off * 1000:.0f} m "
            f"({off * mas_per_km:.2f} mas), {rms * 1000:.0f} m rms around it")


def markdown(meta, title, header, points, stats, fit, mas_per_km, speed_kms, our_dia_km):
    """The report (Markdown), laid out like VERIFICATION.md section 3."""
    hms = lambda s: f"{int(s // 3600):02d}:{int(s % 3600 // 60):02d}:{s % 60:05.2f}"
    L = [f"# Path check: {meta['target_name']} on {meta['best_utc'][:10]}", "",
         f"Occult: *{title or 'listing without a title line'}*. PySyzygos {meta['version']}, run "
         f"{meta['run_utc']} UTC, orbit {meta.get('orbit') or 'unknown'}. {len(points)} points compared.", "",
         "| | Occult | PySyzygos |", "|---|---|---|",
         f"| Orbit | {('JPL#' + header['jpl']) if header.get('jpl') else '(not given)'} | {meta.get('orbit') or '?'} |",
         f"| Star | {('RA %.6f, Dec %.6f (printed astrometric)' % (header['star_ra'], header['star_dec'])) if header.get('star_ra') is not None else '(not given)'} "
         f"| Gaia DR3 {meta['star']}, RA {meta['star_ra']:.6f}, Dec {meta['star_dec']:.6f} (with parallax, deflection) |",
         f"| Diameter | {('%.2f km' % header['dia_km']) if header.get('dia_km') else '(not given)'} | {our_dia_km:.2f} km |",
         ""]
    ours_id = re.search(r"\d+", str(meta.get("orbit") or ""))
    if header.get("jpl") and ours_id and header["jpl"] != ours_id[0]:
        L += [f"**Different orbit solutions** (Occult JPL#{header['jpl']}, PySyzygos {meta['orbit']}): differences "
              f"below then include the orbit.", ""]
    L += ["Occult minus PySyzygos at Occult's times; across: positive to the left of the shadow's motion; plane: the "
          "point minus the shadow axis as that point sees it (x east, y north).", "",
          "| UT | Star alt | Across (km) | Along (km) | Along (s) | Path width Occult / ours (km) | Plane x, y (km) | (mas) |",
          "|---|---|---|---|---|---|---|---|"]
    for i in sample_rows(points):
        p = points[i]
        L.append(f"| {hms(p['utc'])} | {p['star_alt']:.0f} | {p['across']:+.3f} | {p['along']:+.3f} | {p['dt']:+.3f} | "
                 f"{p['w_occ']:.2f} / {p['w_our']:.2f} | {p['px']:+.3f}, {p['py']:+.3f} | "
                 f"{p['px'] * mas_per_km:+.2f}, {p['py'] * mas_per_km:+.2f} |")
    L.append("")
    for key, label in (("all", "All points"), ("alt20", "Star above 20 deg")):
        if key in stats:
            s = stats[key]
            L.append(f"- **{label}** ({s['n']}): across {s['across_min']:+.3f} to {s['across_max']:+.3f} km "
                     f"(mean {s['across_mean']:+.3f}); along {s['dt_min']:+.3f} to {s['dt_max']:+.3f} s "
                     f"(mean {s['dt_mean']:+.3f} s); largest distance {s['dist_max']:.3f} km.")
    lats = [abs(p["lat"]) for p in points if p.get("lat") is not None]
    if lats and "all" in stats:
        s, m_lat = stats["all"], ARCSEC_M
        m_lon = ARCSEC_M * math.cos(math.radians(float(np.median(lats))))
        L += ["", f"**What the listing can resolve.** Occult's positions are whole arcseconds: 1\" = {m_lat:.0f} m in "
              f"latitude, {m_lon:.0f} m in longitude here, so each point carries up to ±{m_lat / 2:.0f} m of rounding "
              f"({m_lat / math.sqrt(12):.0f} m rms); times are to 0.01 s ({10 / math.sqrt(12):.1f} ms rms). A "
              f"difference below about {m_lat:.0f} m at a single point says nothing. Scatter about the mean here: "
              f"{s['across_rms'] * 1000:.0f} m across, {s['dt_rms'] * 1000:.1f} ms along. The means over all "
              f"{s['n']} points are measured well: across {s['across_mean'] * 1000:+.1f} ± "
              f"{s['across_sem'] * 1000:.1f} m, along {s['dt_mean'] * 1000:+.1f} ± {s['dt_sem'] * 1000:.1f} ms."]
    alts = np.array([p["star_alt"] for p in points], float)
    if len(alts) > 10 and np.ptp(alts) > 10:                       # the time difference against the site's height
        dts = np.array([p["dt"] for p in points], float) * 1000.0  # above the fundamental plane (R sin alt)
        A_ = np.vstack([np.ones_like(alts), np.sin(np.radians(alts))]).T
        (c0, c1), *_ = np.linalg.lstsq(A_, dts, rcond=None)
        L += ["", f"**Time against the star's altitude.** Along (s) fitted as a + b x sin(star altitude): a = "
              f"{c0:+.1f} ms, b = {c1:+.1f} ms (R⊕/c = {R_EARTH_KM / C_KM_S * 1000:.1f} ms: the light time between the "
              f"fundamental plane through the geocentre and a site with the star at the zenith); rms {dts.std():.1f} "
              f"ms before, {np.std(dts - A_ @ np.array([c0, c1])):.1f} ms after. A b near ±R⊕/c means the two "
              f"programs relate the time in the fundamental plane to the time at the site differently."]
    cx, cy, rms, mx = fit["const"]
    rx, ry, ang, rrms, rmx, scx, scy, sang = fit["rot"]
    L += ["", "| Fit in the fundamental plane | Result | rms (max) |", "|---|---|---|",
          f"| constant offset | x {cx:+.3f} km ({cx * mas_per_km:+.2f} mas), y {cy:+.3f} km ({cy * mas_per_km:+.2f} mas) "
          f"| {rms * 1000:.0f} m ({mx * 1000:.0f} m) |",
          f"| + Earth rotation (check) | x {rx:+.3f}, y {ry:+.3f} km, rotation = UT1 {ang / OMEGA_EARTH * 1000:+.0f} "
          f"+- {sang / OMEGA_EARTH * 1000:.0f} ms | {rrms * 1000:.0f} m ({rmx * 1000:.0f} m) |", "",
          f"Shadow speed in the plane {speed_kms:.2f} km/s; 1 km = {mas_per_km:.3f} mas at the target.", "",
          f"**Result:** {verdict(stats, fit, mas_per_km, speed_kms)}.", ""]
    return "\n".join(L)


# ----------------------------------------------------------------------------------------------- files
def fav_dir(key, folder=None):
    from pysyzygos import favorites
    return os.path.join(folder or favorites.DIR, key, DIRNAME)


def entry_of(key, folder=None):
    from pysyzygos import favorites
    for e in favorites.load(folder or favorites.DIR):
        if e["key"] == key:
            return e
    raise SystemExit(f"no favorite {key!r} (pysyzygos favorites lists them)")


def _orbit_id(target):
    """JPL's current orbit solution for an asteroid ("JPL#1016, 2026-10-14"), or None (bodies, offline)."""
    if ":" in str(target):
        return None
    try:
        from pysyzygos import geo, urls as U
        o = geo.get_json(f"{U.URL_JPL_SBDB_API}?sstr={target}", timeout=20).get("orbit", {})
        return f"JPL#{o.get('orbit_id')}, {str(o.get('soln_date', ''))[:10]}"
    except Exception:
        return None


# ----------------------------------------------------------------------------------------------- run
def run(key, folder=None):
    """Our path now: the search for this event only (target, star, site and time of the favorite; +-1 h; relaxed
    limits; debug_save_paths), as a separate process (search.py sets up SPICE at import). Writes path.npz, the SPK files
    used and meta.json into the favorite's pathcheck folder; returns that folder."""
    from pysyzygos import config, geoid, home
    e = entry_of(key, folder)
    r, site = e["record"], e.get("site") or {}
    out = os.path.abspath(fav_dir(key, folder))
    work = os.path.join(out, "run")
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    t = time.strptime(r["best_utc"][:19], "%Y-%m-%dT%H:%M:%S")
    t0 = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(calendar.timegm(t) - 3600))
    lat, lon = float(site.get("lat", config.LAT)), float(site.get("lon", config.LON))
    ele = float(site.get("ele", 0.0))
    if site.get("ele_ref") != "ellipsoid":
        ele += float(site.get("geoid_m") if site.get("geoid_m") is not None else geoid.height(lat, lon))
    mag = float(r.get("mag") or 15.0)
    ov = dict(ct=t0, days=2.0 / 24.0, targets=[str(r["target_id"])], targets_source="list", LAT=lat, LON=lon, ELE=ele,
              MIN_STAR_ALT=-90.0, MAX_SUN_ALT=90.0, max_shadow_dist=1e5, MAG_MIN=mag + 0.5, min_mag_drop=0.0,
              pick_min_dur_s=0.0, debug_save_paths=True, write_maps=True, write_globes=False, map_dir=work,
              results_db=os.path.join(work, "check.db"), hits_output_cvs_file=os.path.join(work, "hits.csv"),
              results_new_series=True, gaia_online_check=False)
    env = dict(os.environ, PYSYZYGOS_HOME=home.HOME)
    # a fresh orbit: the search reuses a cached orbit file of the same name up to orbit_max_age_days old, so remove
    # this asteroid's cached files first (the search then downloads today's from JPL Horizons) and keep only the new one
    tid = str(r["target_id"])
    from pysyzygos.report import file_id
    pats = [f"PySyzygos_asteroid_{tid}_*.bsp", f"PySyzygos_body_{file_id(tid)}*.bsp"]
    for p in pats:
        for f in glob.glob(os.path.join(config.cache_path, p)):
            os.remove(f)
    t_start = time.time()
    print(f"path-check: search for {r.get('target_name', r['target_id'])} around {r['best_utc']} (fresh orbit)", flush=True)
    rc = subprocess.run([sys.executable, "-u", "-m", "pysyzygos", "run", "search", json.dumps(ov)], env=env).returncode
    if rc != 0:
        raise SystemExit(f"the search ended with code {rc}")
    found = []
    for f in glob.glob(os.path.join(work, "*_path.npz")):
        z = np.load(f, allow_pickle=False)
        if str(z["star"]) == str(r.get("star")):
            found.append((abs(_et_of(z) - _utc_sec(r["best_utc"])), f))
    if not found:
        raise SystemExit("the search did not find this event again (other star or time): see its output above")
    best = min(found)[1]
    shutil.copyfile(best, os.path.join(out, "path.npz"))
    for old in glob.glob(os.path.join(out, "*.bsp")):
        os.remove(old)
    for p in pats:
        for f in glob.glob(os.path.join(config.cache_path, p)):
            if os.path.getmtime(f) >= t_start - 1:               # downloaded by this run only
                shutil.copyfile(f, os.path.join(out, os.path.basename(f)))
    if not glob.glob(os.path.join(out, "*.bsp")):
        raise SystemExit("no orbit file was downloaded by this run (see its output above)")
    z = np.load(os.path.join(out, "path.npz"), allow_pickle=False)
    meta = dict(key=key, target_id=tid, target_name=str(z["target_name"]), star=str(z["star"]),
                best_utc=str(z["best_utc"]), version=str(z["version"]), run_utc=time.strftime("%Y-%m-%d %H:%M", time.gmtime()),
                orbit=_orbit_id(tid))
    with open(os.path.join(out, "meta.json"), "w") as f:
        json.dump(meta, f, indent=1)
    shutil.rmtree(work, ignore_errors=True)
    print(f"path-check: our path saved in {out} (PySyzygos {meta['version']}, orbit {meta['orbit']})")
    return out


def _utc_sec(utc):
    return calendar.timegm(time.strptime(utc[:19], "%Y-%m-%dT%H:%M:%S")) + (float("0" + utc[19:]) if utc[19:20] == "." else 0.0)


def _et_of(z):
    return _utc_sec(str(z["best_utc"]))


# ----------------------------------------------------------------------------------------------- SPICE side
def _load(out):
    """Kernels, the saved SPK files and the path file of a pathcheck folder: (spice, z, tid)."""
    import spiceypy as spice
    from pysyzygos import screen
    p = os.path.join(out, "path.npz")
    if not os.path.isfile(p):
        raise SystemExit(f"no path in {out}: run `pysyzygos path-check run <key>` first")
    screen.load_kernels(spice)
    spks = sorted(glob.glob(os.path.join(out, "*.bsp")))
    if not spks:
        raise SystemExit(f"no orbit file in {out}: run `pysyzygos path-check run <key>` again")
    for f in spks:
        spice.furnsh(f)
    z = np.load(p, allow_pickle=False)
    tid = str(z["target_id"])
    if ":" in tid:
        raise SystemExit("planets and moons are not supported by path-check yet")
    spice.boddef(tid, int(spice.spkobj(spks[-1])[0]))
    return spice, z, tid


def _ecef(lon, lat, h_km=0.0):
    from pysyzygos import earth
    lo, la = math.radians(lon), math.radians(lat)
    e2 = earth.F * (2 - earth.F)
    n = earth.A_KM / math.sqrt(1 - e2 * math.sin(la) ** 2)
    return np.array([(n + h_km) * math.cos(la) * math.cos(lo), (n + h_km) * math.cos(la) * math.sin(lo),
                     (n * (1 - e2) + h_km) * math.sin(la)])


def compare(out, listing_text, header_text=""):
    """Our path (pathcheck folder `out`) at Occult's times against its listing. Returns (markdown, points, stats, fit)."""
    from pysyzygos import paths
    rows, title = parse_listing(listing_text)
    if not rows:
        raise SystemExit("no path rows recognised: Occult's path listing, or a table whose header row names longitude, "
                         "latitude and time (UT) is expected")
    header = parse_header(header_text + "\n" + listing_text)
    spice, z, tid = _load(out)
    meta = json.load(open(os.path.join(out, "meta.json")))
    meta.update(star_ra=float(z["star_ra"]), star_dec=float(z["star_dec"]))
    star_dir, r_km, s3 = z["star_dir"], float(z["r_km"]), float(z["sigma3_km"])
    x_ax, y_ax, z_ax = paths.plane_basis(star_dir)
    et0 = spice.str2et(str(z["best_utc"])[:10] + " 00:00:00 UTC")

    def ours(et):
        p = paths.shadow_path(tid, star_dir, et, r_km, s3, half_span=0.0, step=1.0)
        g = lambda k: (p[k][0][1], p[k][0][2]) if p[k] else None
        return g("center"), g("edge_plus"), g("edge_minus")

    try:
        best_et = spice.str2et(str(z["best_utc"]).replace("T", " ").rstrip("Z") + " UTC")
    except Exception:
        best_et = et0 + 43200.0
    points = []
    for r in rows:
        et = (spice.str2et(r["date"] + " 00:00:00 UTC") if r.get("date") else et0) + r["sec"]
        if not r.get("date"):                                # times only: the day nearest our event (midnight)
            et += 86400.0 * round((best_et - et) / 86400.0)
        c0, ep, em = ours(et)
        c1, _, _ = ours(et + 0.5)
        if c0 is None or c1 is None:
            continue
        P, P1, Q = _ecef(*c0), _ecef(*c1), _ecef(r["lon"], r["lat"])
        v = (P1 - P) / 0.5
        speed = float(np.linalg.norm(v))
        u = v / speed
        n = np.cross(P / np.linalg.norm(P), u)
        d = Q - P
        w_occ = float(np.linalg.norm(_ecef(*r["l1"]) - _ecef(*r["l2"]))) if r.get("l1") and r.get("l2") else float("nan")
        star_alt = r.get("star_alt")
        if star_alt is None:                                 # not in the listing: the star's altitude at the point
            lo_, la_ = math.radians(r["lon"]), math.radians(r["lat"])
            up = np.array([math.cos(la_) * math.cos(lo_), math.cos(la_) * math.sin(lo_), math.sin(la_)])
            s_itrf = spice.pxform("J2000", "ITRF93", et) @ np.asarray(star_dir, float)
            star_alt = math.degrees(math.asin(max(-1.0, min(1.0, float(up @ s_itrf) / np.linalg.norm(s_itrf)))))
        w_our = float(np.linalg.norm(_ecef(*ep) - _ecef(*em))) if ep and em else float("nan")
        # the fundamental plane: Occult's point minus the shadow axis as that point sees it (light time from the point)
        rel = np.asarray(spice.spkcpo(tid, et, "J2000", "OBSERVER", "CN", Q, "399", "ITRF93")[0][:3])
        a0 = np.asarray(spice.spkpos(tid, et - 0.5, "J2000", "CN", "399")[0])
        a1 = np.asarray(spice.spkpos(tid, et + 0.5, "J2000", "CN", "399")[0])
        rot = spice.pxform("ITRF93", "J2000", et) @ np.cross([0.0, 0.0, 1.0], Q)
        points.append(dict(utc=(et - et0) % 86400.0, lat=float(r["lat"]), star_alt=star_alt, across=float(d @ n), along=float(d @ u),
                           dt=float(d @ u) / speed, dist=float(np.linalg.norm(d)), w_occ=w_occ, w_our=w_our,
                           px=float(-(rel @ x_ax)), py=float(-(rel @ y_ax)),
                           dvx=float(-((a1 - a0) @ x_ax)), dvy=float(-((a1 - a0) @ y_ax)),
                           drx=float(rot @ x_ax), dry=float(rot @ y_ax), dist_target=float(np.linalg.norm(rel))))
    if len(points) < 3:
        raise SystemExit("fewer than 3 of Occult's points lie on our path's time span (other event or date?)")
    A = lambda k: np.array([p[k] for p in points])
    fit = fit_plane(A("px"), A("py"), A("dvx"), A("dvy"), A("drx"), A("dry"))
    stats = summary(points)
    mas_per_km = 206264806.247 / float(np.mean(A("dist_target")))
    speed = float(np.hypot(A("dvx").mean(), A("dvy").mean()))
    md = markdown(meta, title, header, points, stats, fit, mas_per_km, speed, 2 * r_km)
    return md, points, stats, fit


def export(out, step=1.45):
    """Our path (pathcheck folder `out`) as a text table in Occult's layout: centre, UT, star alt/az, Sun alt, the
    shadow limits and the 1-sigma limits, every `step` seconds while the centre is on the Earth."""
    from pysyzygos import paths
    spice, z, tid = _load(out)
    star_dir, r_km, s3 = z["star_dir"], float(z["r_km"]), float(z["sigma3_km"])
    p = paths.shadow_path(tid, star_dir, float(z["best_et"]), r_km, s3, step=step)
    by = {k: {round(e, 3): (lo, la) for e, lo, la, _ in v} for k, v in p.items()}
    meta = json.load(open(os.path.join(out, "meta.json")))
    L = [f"Occultation of Gaia DR3 {z['star']} by {z['target_name']} on {str(z['best_utc'])[:10]}, WGS84 height 0 "
         f"(PySyzygos {z['version']}, orbit {meta.get('orbit')}, run {meta.get('run_utc')} UTC)", "",
         "                   Centre                Star  Star  Sun|      Path Limit 1   |      Path Limit 2   |"
         "     Error Limit 1   |     Error Limit 2   |",
         "  E. Longitude    Latitude      U.T.      Alt   Az   Alt| Longitude   Latitude| Longitude   Latitude|"
         " Longitude   Latitude| Longitude   Latitude|",
         "      o  '  \"     o  '  \"    h  m  s       o     o     o|   o  '  \"    o  '  \"|   o  '  \"    o  '  \"|"
         "   o  '  \"    o  '  \"|   o  '  \"    o  '  \"|", ""]
    day0 = spice.str2et(str(z["best_utc"])[:10] + " 00:00:00 UTC")
    for et, lon, lat, _ in p["center"]:
        k = round(et, 3)
        R = spice.pxform("J2000", "ITRF93", et)
        Pg = _ecef(lon, lat)
        up = Pg / np.linalg.norm(Pg)
        east = np.cross([0.0, 0.0, 1.0], up); east /= np.linalg.norm(east)
        north = np.cross(up, east)
        s = R @ star_dir
        sun = R @ np.asarray(spice.spkpos("SUN", et, "J2000", "LT+S", "399")[0])
        sun = sun / np.linalg.norm(sun)
        alt = math.degrees(math.asin(float(s @ up)))
        az = math.degrees(math.atan2(float(s @ east), float(s @ north))) % 360.0
        sun_alt = math.degrees(math.asin(float(sun @ up)))
        part = lambda name: (" " + fmt_dms(by[name][k][0]) + " " + fmt_dms(by[name][k][1], 2)) if k in by[name] else \
            "        ....          ...."
        L.append(f"  {fmt_dms(lon)} {fmt_dms(lat, 2)}   {fmt_ut(et - day0)}   {alt:3.0f}   {az:3.0f}   {sun_alt:3.0f}"
                 + part("edge_plus") + part("edge_minus") + part("sigma1_plus") + part("sigma1_minus"))
    return "\n".join(L) + "\n"


# ----------------------------------------------------------------------------------------------- step by step
EARTH_A = 6378.137                                           # km, WGS84 equatorial radius (Besselian x, y unit)


def _radec(v):
    v = np.asarray(v, float)
    r = np.linalg.norm(v)
    return math.degrees(math.atan2(v[1], v[0])) % 360.0, math.degrees(math.asin(v[2] / r))


def _hms(ra_deg, nd=5):
    h = ra_deg / 15.0
    a, b = divmod(h * 3600.0, 3600.0)
    m, s_ = divmod(b, 60.0)
    return f"{int(a):02d}h{int(m):02d}m{s_:0{3 + nd}.{nd}f}s"


def _dms_s(dec_deg, nd=4):
    sg = "-" if dec_deg < 0 else "+"
    a = abs(dec_deg) * 3600.0
    d, r = divmod(a, 3600.0)
    m, s_ = divmod(r, 60.0)
    return f"{sg}{int(d):02d}°{int(m):02d}'{s_:0{3 + nd}.{nd}f}\""


def _shift_mas(a, b):
    """b - a as (RA x cos Dec, Dec) in mas, for two unit vectors."""
    ra1, de1 = _radec(a)
    ra2, de2 = _radec(b)
    dra = ((ra2 - ra1 + 180.0) % 360.0 - 180.0) * math.cos(math.radians(de1))
    return dra * 3.6e6, (de2 - de1) * 3.6e6


def steps(out, folder_key=None):
    """The event step by step (pathcheck folder `out`): the star from the catalog through every correction (amounts),
    the asteroid (geocentric, barycentric, its own deflection), the resulting vectors and the Besselian elements (ICRF
    axes and axes of date, d, mu) at the shadow axis's touch-down on the Earth, its closest approach to the Earth's
    centre and its leaving, and the geodetic centre-line points then. Returns (markdown, data dict)."""
    import erfa
    from scipy.optimize import brentq, minimize_scalar
    from pysyzygos import astrometry as A, config, corridor, gaia_local, paths, starrv
    spice, z, tid = _load(out)
    meta = json.load(open(os.path.join(out, "meta.json")))
    star_used = np.asarray(z["star_dir"], float)
    r_km, s3 = float(z["r_km"]), float(z["sigma3_km"])
    x_ax, y_ax, z_ax = paths.plane_basis(star_used)

    def axis_xy(et):
        a = np.asarray(spice.spkpos(tid, et, "J2000", "CN", "399")[0])
        return np.array([a @ x_ax, a @ y_ax])

    # the three instants: closest approach to the Earth's centre, touch-down and leaving of the centre line
    et_best = float(z["best_et"])
    res = minimize_scalar(lambda d: float(np.linalg.norm(axis_xy(et_best + d))), bounds=(-7200.0, 7200.0),
                          method="bounded", options=dict(xatol=1e-3))
    et_c = et_best + float(res.x)

    def on_earth(et):
        return bool(paths.shadow_path(tid, star_used, et, r_km, s3, half_span=0.0, step=1.0)["center"])

    def edge(direction):
        lo, step = et_c, 30.0
        hi = lo + direction * step
        while on_earth(hi) and abs(hi - et_c) < 4 * 3600:
            lo, hi = hi, hi + direction * step
        for _ in range(40):                                      # bisection to ~0.01 s
            mid = 0.5 * (lo + hi)
            lo, hi = (mid, hi) if on_earth(mid) else (lo, mid)
            if abs(hi - lo) < 0.005:
                break
        return lo

    instants = [("touch-down", edge(-1.0)), ("centre (closest to the Earth's centre)", et_c), ("leaving", edge(+1.0))]
    utc = lambda et: spice.et2utc(et, "ISOC", 3)
    tdb = lambda et: spice.timout(et, "YYYY-MM-DD HR:MN:SC.### ::TDB")

    # ---- the star, at the centre instant: catalog, then each correction
    from pysyzygos import starcat
    gl = gaia_local.LocalGaia(config.gaia_local_dir)
    ra0, de0 = float(z["star_ra"]), float(z["star_dec"])
    cone = gl.cone(ra0, de0, 30.0 / 3600.0)
    row = cone[cone.source_id.astype(str) == str(z["star"])]
    if row.empty:
        raise SystemExit(f"star {z['star']} not found in the local catalog {config.gaia_local_dir}")
    row = row.iloc[[0]]
    r0 = row.iloc[0]                       # a mixed row: numbers become float64, so never read the id from it
    sid = int(row["source_id"].to_numpy(np.int64)[0])        # the exact 19-digit id from the int64 column
    ruwe = getattr(r0, "ruwe", None)
    ruwe_text = (f"RUWE {float(ruwe):.3f}" if ruwe is not None and ruwe == ruwe else
                 "RUWE < 1.4 (the value is not stored in this catalog: an old-format catalog, or one without its "
                 "quality part)" if int(getattr(r0, "star_kind", 0) or 0) == 0 else "RUWE not stored in this catalog")
    cat = A.unit([math.cos(math.radians(r0.dec)) * math.cos(math.radians(r0.ra)),
                  math.cos(math.radians(r0.dec)) * math.sin(math.radians(r0.ra)), math.sin(math.radians(r0.dec))])
    t_c = utc(et_c)
    vec = lambda df, col: A.unit([math.cos(math.radians(df[f"dec_{col}"].iloc[0])) * math.cos(math.radians(df[f"ra_{col}"].iloc[0])),
                                  math.cos(math.radians(df[f"dec_{col}"].iloc[0])) * math.sin(math.radians(df[f"ra_{col}"].iloc[0])),
                                  math.sin(math.radians(df[f"dec_{col}"].iloc[0]))])
    tag = t_c[:10].replace("-", "")
    p1 = vec(corridor.propagate_exact(row, t_c, pm_bias=False, rv=False), tag)
    p2 = vec(corridor.propagate_exact(row, t_c, pm_bias=True, rv=False), tag)
    p3 = vec(corridor.propagate_exact(row, t_c, pm_bias=True, rv=True), tag)
    earth_ssb = np.asarray(spice.spkpos("399", et_c, "J2000", "NONE", "0")[0])
    plx = float(r0.parallax) if r0.parallax == r0.parallax else 0.0
    p4 = A.parallax_dir(p3, plx, earth_ssb) if plx > 0 else p3
    ast_c = np.asarray(spice.spkpos(tid, et_c, "J2000", "CN", "399")[0])
    defl_star, defl_ast = {}, {}
    for b in ("10", "5", "6"):
        body = np.asarray(spice.spkpos(b, et_c, "J2000", "CN", "399")[0])
        defl_star[A.BODY_NAMES[b]] = A.deflect(p4, -body, p4, A.GM[b])
        defl_ast[A.BODY_NAMES[b]] = A.deflect(p4, -body, A.unit(ast_c - body), A.GM[b])
    p5 = A.unit(p4 + sum(defl_star.values()))
    p6 = A.unit(p4 + sum(defl_star.values()) - sum(defl_ast.values()))
    rv = float(starrv.rv_for([sid])[0])
    # of date (true equator and equinox): precession-nutation (IAU 2006/2000A, ERFA) and the Earth's rotation (UT1)
    from astropy.time import Time
    from astropy.utils import iers
    iers.conf.auto_download = False

    def of_date(et):
        t = Time(utc(et), scale="utc")
        rpn = erfa.pnm06a(t.tt.jd1, t.tt.jd2)
        try:
            ut1 = t.ut1
            dut1 = float((ut1.jd1 - t.utc.jd1 + ut1.jd2 - t.utc.jd2) * 86400.0)
        except Exception:                                        # no IERS data at hand: UT1 = UTC (stated)
            ut1, dut1 = t.utc, float("nan")
        gast = math.degrees(erfa.gst06a(ut1.jd1, ut1.jd2, t.tt.jd1, t.tt.jd2))
        return rpn, gast, dut1

    rpn_c, _, _ = of_date(et_c)
    ap = None
    try:                                                         # astropy's apparent place of date (with aberration)
        from astropy.coordinates import SkyCoord, TETE, Distance
        import astropy.units as u
        sc = SkyCoord(ra=r0.ra * u.deg, dec=r0.dec * u.deg, distance=Distance(parallax=max(plx, 0.01) * u.mas),
                      pm_ra_cosdec=float(r0.pmra) * u.mas / u.yr, pm_dec=float(r0.pmdec) * u.mas / u.yr,
                      radial_velocity=rv * u.km / u.s, obstime=Time("2016-01-01T12:00:00", scale="tcb"), frame="icrs")
        tt = sc.apply_space_motion(new_obstime=Time(t_c, scale="utc")).transform_to(TETE(obstime=Time(t_c, scale="utc")))
        ap = (tt.ra.deg, tt.dec.deg)
    except Exception:
        pass

    # ---- markdown
    L = [f"# Step by step: {meta['target_name']} occults Gaia DR3 {z['star']}", "",
         f"PySyzygos {__version__}; our path run {meta.get('run_utc')} UTC (PySyzygos {meta.get('version')}), orbit "
         f"{meta.get('orbit') or '?'}; orbit files: {', '.join(os.path.basename(f) for f in sorted(glob.glob(os.path.join(out, '*.bsp'))))}. "
         f"Frames: ICRF (SPICE 'J2000'); times UTC and TDB; Earth orientation ITRF93 (NAIF, IERS EOP); WGS84.", "",
         "## 1. Instants", "", "| Instant | UTC | TDB | ET (s past J2000 TDB) |", "|---|---|---|---|"]
    for name, et in instants:
        L.append(f"| {name} | {utc(et)} | {tdb(et)} | {et:.3f} |")
    L += ["", "Touch-down and leaving: the centre line (shadow axis) meets / leaves the WGS84 surface (height 0), with "
          "each point's own light time (bisection to 0.01 s). Centre: the axis's closest approach to the Earth's centre.",
          "", "## 2. The star (at the centre instant)", "",
          "| Gaia DR3 catalog (epoch 2016.0 TCB) | |", "|---|---|",
          f"| local catalog | {os.path.basename(os.path.normpath(config.gaia_local_dir))} "
          f"({'format 2, parts: ' + ', '.join(starcat.groups_present(config.gaia_local_dir)) if starcat.is_format2(config.gaia_local_dir) else 'old format'}) |",
          f"| source_id | {sid} |", f"| G | {float(r0.phot_g_mean_mag):.3f} |",
          f"| RA, Dec | {float(r0.ra):.9f}°, {float(r0.dec):.9f}° ({_hms(float(r0.ra))} {_dms_s(float(r0.dec))}) |",
          f"| parallax | {plx:.4f} mas |", f"| pmRA·cosDec, pmDec | {float(r0.pmra):.4f}, {float(r0.pmdec):.4f} mas/yr |",
          f"| radial velocity | {rv:.3f} km/s" + (" (from data/gaia_dr3_rv_fast.npy)" if rv else " (not used: below the threshold or none)") + " |",
          f"| kind, RUWE | {int(getattr(r0, 'star_kind', 0) or 0)} (0 = 5/6-parameter astrometry, RUWE < 1.4), "
          f"{ruwe_text} |", "",
          "| Step | RA | Dec | Shift of the position by this step (RA·cosDec, Dec; mas, not mas/yr) |", "|---|---|---|---|"]
    prev = cat
    years = (et_c - spice.str2et("2016-01-01 12:00:00 TDB")) / (365.25 * 86400.0)
    pm_label = (f"+ proper motion to the event: {float(r0.pmra):.3f}, {float(r0.pmdec):.3f} mas/yr x {years:.3f} yr "
                f"(barycentric, ICRF)")
    for label, v in (("catalog position (2016.0)", cat), (pm_label, p1),
                     ("+ Gaia bright-star proper-motion bias", p2), ("+ radial velocity (perspective acceleration)", p3),
                     ("+ stellar parallax (geocentric)", p4), ("+ the star's own light deflection (Sun, Jupiter, Saturn)", p5)):
        ra_, de_ = _radec(v)
        sx, sy = _shift_mas(prev, v)
        L.append(f"| {label} | {ra_:.9f}° ({_hms(ra_)}) | {de_:.9f}° ({_dms_s(de_)}) | {sx:+.3f}, {sy:+.3f} |")
        prev = v
    L += ["", "The last line is **the star's direction**: GCRS astrometric (geocentric, with parallax) plus the deflection "
              "of the star's own light. The asteroid's light is deflected too (by the same bodies, less, as it is "
              "nearer): that deflection belongs to the asteroid's position (section 3).", "",
          "| Light deflection at the centre instant (mas, RA·cosDec, Dec) | Star | Asteroid (its own light) | Star minus asteroid |",
          "|---|---|---|---|"]
    for k in defl_star:
        a_ = _shift_mas(p4, A.unit(p4 + defl_star[k]))
        b_ = _shift_mas(p4, A.unit(p4 + defl_ast[k]))
        L.append(f"| {k} | {a_[0]:+.3f}, {a_[1]:+.3f} | {b_[0]:+.3f}, {b_[1]:+.3f} | {a_[0] - b_[0]:+.3f}, {a_[1] - b_[1]:+.3f} |")
    chk = A.angle_mas(p6, star_used)
    # the same geometry two ways at the centre instant: the asteroid's deflection on the asteroid (the definition), or
    # as the equivalent change of the star direction (how the search applies it: once per event, not per position)
    ast_c_def = np.linalg.norm(ast_c) * A.unit(A.unit(ast_c) + sum(defl_ast.values()))
    def _axis(z, ast):
        xa = np.cross([0.0, 0.0, 1.0], z)
        xa /= np.linalg.norm(xa)
        return np.array([ast @ xa, ast @ np.cross(z, xa)])
    equiv_cm = float(np.linalg.norm(_axis(p5, ast_c_def) - _axis(p6, ast_c))) * 1e5
    sx, sy = _shift_mas(p5, p6)
    L += ["", f"**How the search applies it.** Instead of moving every asteroid position by the asteroid's own "
              f"deflection, the search subtracts that deflection from the star direction once per event (the "
              f"relative direction asteroid-star, which makes the shadow, is the same): its working direction is "
              f"{sx:+.3f}, {sy:+.3f} mas from the star's (RA·cosDec, Dec). Both give the same shadow axis at the centre "
              f"instant to {equiv_cm:.1f} cm (a second-order difference: deflection x the axis's distance from the "
              f"geocentre). The search's working direction differs from the one computed here by {chk:.4f} mas "
              f"(it is computed once per candidate, at its first time estimate). Unit vector (ICRF): "
              f"({star_used[0]:.12f}, {star_used[1]:.12f}, {star_used[2]:.12f}).", ""]
    rd = _radec(rpn_c @ p5)
    L.append(f"Of date (true equator and equinox; IAU 2006/2000A precession-nutation of the geocentric direction with "
             f"deflection, no aberration): RA {_hms(rd[0])}, Dec {_dms_s(rd[1])}." +
             (f" Astropy's apparent place of date (TETE, with annual aberration): RA {_hms(ap[0])}, Dec {_dms_s(ap[1])}."
              if ap else ""))
    L += ["", "## 3. The asteroid", "",
          "| Instant | Geocentric astrometric RA, Dec (ICRF, light time 'CN') | Distance (AU) | Light time (s) | "
          "Barycentric position at t - lt (km) | Check: bary(t - lt) - Earth(t) minus geocentric (m) | Its own deflection by the Sun (mas) |",
          "|---|---|---|---|---|---|---|"]
    rows = []
    for name, et in instants:
        a, lt = spice.spkpos(tid, et, "J2000", "CN", "399")
        a = np.asarray(a)
        bary = np.asarray(spice.spkpos(tid, et - lt, "J2000", "NONE", "0")[0])
        e_ = np.asarray(spice.spkpos("399", et, "J2000", "NONE", "0")[0])
        sun = np.asarray(spice.spkpos("10", et, "J2000", "CN", "399")[0])
        dsun = _shift_mas(A.unit(a), A.unit(A.unit(a) + A.deflect(A.unit(a), -sun, A.unit(a - sun), A.GM["10"])))
        ra_, de_ = _radec(a)
        L.append(f"| {name} | {_hms(ra_)} {_dms_s(de_)} | {np.linalg.norm(a) / 1.495978707e8:.9f} | {lt:.6f} | "
                 f"({bary[0]:.3f}, {bary[1]:.3f}, {bary[2]:.3f}) | {np.linalg.norm(bary - e_ - a) * 1000:.3f} | "
                 f"{dsun[0]:+.3f}, {dsun[1]:+.3f} |")
        rows.append((name, et, a))
    L += ["", "At a point on the Earth the light time is that point's own (shorter by up to 21 ms), with the asteroid "
              "moving at its barycentric velocity in between (SPICE spkcpo per site and per path point).", "",
          "## 4. Fundamental plane (Besselian elements)", "",
          "The fundamental plane's axes by definition (Besselian elements): z parallel to the shadow axis, i.e. the "
          "direction from the asteroid along the star's light (for a star this far: the star's direction), x along "
          "the true equator of date (east), y north. PySyzygos computes in ICRF-oriented axes (x = (0,0,1) × z, "
          "y = z × x): the same plane, rotated about z, so x, y differ from the elements of date by that rotation "
          "while every distance in the plane, and so the path, is the same; both sets are given. "
          "ICRF axes: z = the search's working direction, x = (0,0,1) × z (east), y = z × x (north). Of date: the same plane, "
          "with x east and y north of the true pole of date; d = the star's declination of date, mu = its Greenwich "
          "hour angle (GAST - RA of date, UT1 from IERS). x, y in km and in Earth radii (6378.137 km); rates per second "
          "and per hour.", "",
          "| Instant | x, y (km) ICRF axes | x, y (Earth radii) | dx/dt, dy/dt (km/s) | x, y of date (Earth radii) | d (deg) | mu (deg) | UT1-UTC (s) |",
          "|---|---|---|---|---|---|---|---|"]
    bess = []
    for name, et, a in rows:
        xy = np.array([a @ x_ax, a @ y_ax])
        v = (axis_xy(et + 0.5) - axis_xy(et - 0.5))
        rpn, gast, dut1 = of_date(et)
        pole = rpn.T @ np.array([0.0, 0.0, 1.0])
        xd = A.unit(np.cross(pole, z_ax)); yd = np.cross(z_ax, xd)
        sd = rpn @ z_ax
        dd = math.degrees(math.asin(sd[2]))
        mu = (gast - math.degrees(math.atan2(sd[1], sd[0]))) % 360.0
        xyd = np.array([a @ xd, a @ yd]) / EARTH_A
        L.append(f"| {name} | {xy[0]:+.3f}, {xy[1]:+.3f} | {xy[0] / EARTH_A:+.7f}, {xy[1] / EARTH_A:+.7f} | "
                 f"{v[0]:+.5f}, {v[1]:+.5f} | {xyd[0]:+.7f}, {xyd[1]:+.7f} | {dd:.7f} | {mu:.7f} | {dut1:+.4f} |")
        bess.append(dict(instant=name, et=et, utc=utc(et), x_km=xy[0], y_km=xy[1], dxdt=v[0], dydt=v[1],
                         x_date=xyd[0], y_date=xyd[1], d_deg=dd, mu_deg=mu, ut1_utc=dut1))
    L += ["", "## 5. Geodetic (WGS84, height 0)", "",
          "| Instant | Centre line lon, lat (deg) | Shadow limits lon, lat (deg) |", "|---|---|---|"]
    for name, et in instants:
        p_ = paths.shadow_path(tid, star_used, et, r_km, s3, half_span=0.0, step=1.0)
        g = lambda k: f"{p_[k][0][1]:+.6f}, {p_[k][0][2]:+.6f}" if p_[k] else "off the Earth"
        L.append(f"| {name} | {g('center')} | {g('edge_plus')} / {g('edge_minus')} |")
    L += ["", f"Shadow radius {r_km:.3f} km (diameter {2 * r_km:.2f} km); 3-sigma {s3:.3f} km.", ""]
    data = dict(meta=meta, star=dict(source_id=sid, steps={k: _radec(v) for k, v in
                (("catalog", cat), ("pm", p1), ("pm_bias", p2), ("rv", p3), ("parallax", p4), ("deflection", p5),
                 ("used", p6))}), besselian=bess)
    return "\n".join(L), data


# ----------------------------------------------------------------------------------------------- command
def main(argv=None):
    ap = argparse.ArgumentParser(prog="pysyzygos path-check", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=f"PySyzygos {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run").add_argument("key")
    q = sub.add_parser("export"); q.add_argument("key"); q.add_argument("--step", type=float, default=1.45)
    q = sub.add_parser("compare"); q.add_argument("key"); q.add_argument("listing")
    q.add_argument("--header", help="a text file with Occult's plot header (orbit, star RA/Dec, diameter)")
    sub.add_parser("keep").add_argument("key")
    sub.add_parser("steps").add_argument("key")
    a = ap.parse_args(argv)
    out = fav_dir(a.key)
    stamp = time.strftime("%Y%m%dT%H%M", time.gmtime())
    if a.cmd == "run":
        run(a.key)
    elif a.cmd == "export":
        text = export(out, a.step)
        path = os.path.join(out, f"pysyzygos_path_{stamp}.txt")
        open(path, "w", encoding="utf-8").write(text)
        print(f"wrote {path}")
    elif a.cmd == "compare":
        listing = open(a.listing, encoding="utf-8", errors="replace").read()
        header = open(a.header, encoding="utf-8", errors="replace").read() if a.header else ""
        md, points, stats, fit = compare(out, listing, header)
        shutil.copyfile(a.listing, os.path.join(out, f"occult_{stamp}.txt")) if os.path.abspath(a.listing) != \
            os.path.abspath(os.path.join(out, f"occult_{stamp}.txt")) else None
        mdp = os.path.join(out, f"compare_{stamp}.md")
        open(mdp, "w", encoding="utf-8").write(md)
        import csv
        with open(os.path.join(out, f"compare_{stamp}.csv"), "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(points[0])); w.writeheader(); w.writerows(points)
        print(md)
        print(f"wrote {mdp}")
    elif a.cmd == "steps":
        md, data = steps(out)
        path = os.path.join(out, f"steps_{stamp}.md")
        open(path, "w", encoding="utf-8").write(md)
        with open(os.path.join(out, f"steps_{stamp}.json"), "w") as f:
            json.dump(data, f, indent=1, default=float)
        print(md)
        print(f"wrote {path}")
    elif a.cmd == "keep":
        dest = os.path.join("owc_refs", "occult_paths")
        os.makedirs(dest, exist_ok=True)
        files = sorted(glob.glob(os.path.join(out, "compare_*.md")))
        if not files:
            raise SystemExit("no comparison yet: pysyzygos path-check compare <key> <listing>")
        md = files[-1]
        st = os.path.basename(md)[len("compare_"):-len(".md")]
        for f in (md, md[:-3] + ".csv", os.path.join(out, f"occult_{st}.txt")):
            if os.path.isfile(f):
                shutil.copyfile(f, os.path.join(dest, f"{a.key}_{os.path.basename(f)}"))
        line = next((l for l in open(md, encoding="utf-8") if l.startswith("**Result:**")), "").strip()
        with open(os.path.join(dest, "index.md"), "a", encoding="utf-8") as f:
            f.write(f"- {a.key} ({st}): {line[len('**Result:** '):]}\n")
        print(f"kept in {dest} (index.md)")


if __name__ == "__main__":
    main()
