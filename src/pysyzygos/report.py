"""report.py - turn PySyzygos's hits_log.csv into a readable event list (HTML or Markdown).

Columns follow the Occult Watcher (OWC) list - asteroid, event time (UT), star magnitude, magnitude
drop, maximum duration, star altitude with compass direction, Moon distance with phase icon - plus the
observer's shadow distance (from the shadow centre line) and a link to the KML ground-track file.

Standard library only. Usage:

    pysyzygos report hits_log.csv                       # -> hits_report.html next to the CSV
    pysyzygos report hits_log.csv -o events.html --kml-dir maps --max-miss 50 --min-drop 0.5
    pysyzygos report hits_log.csv --format md           # Markdown table instead
    pysyzygos report hits_log.csv --sort date           # by event time (default: by star magnitude)

The observer position (needed only for the compass direction) comes from pysyzygos_config.py (LAT, LON)
if that file is importable, or from --lat / --lon (east-positive degrees).

KML files are looked up as  <kml-dir>/<target_id>_<YYYYMMDD>T<HHMM>*.kml , i.e. the name that
paths.write_shadow_kml() is given in the pipeline hook (best_utc truncated to the minute).

For every event with a KML file the HTML page gets a "Map" button: an interactive map (Leaflet + OpenStreetMap
tiles, loaded from the internet when the button is first used) showing the shadow centre line, the shadow
limits, the 3-sigma limits and the observer. The path data is embedded in the page, so it works when the file
is opened straight from disk. A link opens the closest centre-line point in Google Maps. --no-embed turns it off.
"""
from pysyzygos.version import __version__
from pysyzygos import urls as U
import argparse
import csv
import glob
import html
import json
import math
import os
import re
import sys
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
COMPASS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
MOON_ICONS = "🌑🌒🌓🌔🌕🌖🌗🌘"          # moon_age_deg: 0 new, 90 first quarter, 180 full, 270 last quarter
NEAR_KM = 10.0                            # misses closer than this to the shadow edge get the amber tag


# ---------------------------------------------------------------- reading the log

def num(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def read_log(path):
    """Rows as dicts. Tolerates repeated header lines (columns get added over time) and short/long rows."""
    rows, header, skipped = [], None, 0
    with open(path, newline="", encoding="utf-8-sig") as f:
        for raw in csv.reader(f):
            if not raw or not any(c.strip() for c in raw):
                continue
            if raw[0].strip() == "target_id":
                header = [c.strip() for c in raw]
                continue
            if header is None or len(raw) != len(header):
                skipped += 1
                continue
            rows.append(dict(zip(header, raw)))
    return rows, skipped


def read_last_run(csv_path):
    """The last run summary search.py appended to <hits log>.runs.jsonl, or None."""
    path = os.path.splitext(csv_path)[0] + ".runs.jsonl"
    try:
        with open(path) as f:
            lines = [ln for ln in f if ln.strip()]
        return json.loads(lines[-1]) if lines else None
    except (OSError, ValueError):
        return None


def header_info(run, lat, lon):
    """(label, text) lines for the page header: site, equipment, limits, run statistics."""
    if not run:
        if lat is None or lon is None:
            return []
        return [("Site", f"{abs(lat):.4f}°{'N' if lat >= 0 else 'S'} {abs(lon):.4f}°{'E' if lon >= 0 else 'W'}"
                         " (no run summary found)")]
    s, L = run["site"], run["limits"]
    ns, ew = ("N" if s["lat"] >= 0 else "S"), ("E" if s["lon"] >= 0 else "W")
    out = [("Site", f"{s['name']}" + (f" ({s['desc']})" if s.get("desc") else "") +
            f": {abs(s['lat']):.4f}°{ns} {abs(s['lon']):.4f}°{ew}, {s['ele']:g} m"
            + (" (WGS84)" if s.get("ele_ref") == "ellipsoid" else
               f" above sea level, {s['ele_wgs84']:.0f} m above WGS84 (geoid {s['geoid_m']:+.1f} m)" if s.get("geoid_m")
               else "")
            + (f", MPC code {s['mpc_code']}" if s.get("mpc_code") else "")),
           ("Equipment", f"{s['aperture_cm']:g} cm aperture, {s['frames']} detection frames, MagAdjust "
                         f"{s['mag_adjust']:+g}, extinction " +
                         (f"{s['extinction']:g} mag/airmass" if s["extinction"] else "off")),
           ("Limits", f"stars G ≤ {L['mag_limit']:g}, star altitude ≥ {L['min_star_alt']:g}°, Sun ≤ "
                      f"{L['max_sun_alt']:g}°, reach {L['reach_km']:g} km, drop ≥ {L['min_mag_drop']:g} mag, "
                      f"duration ≥ {L['min_dur_s']:g} s"),
           ("Run", (f"PySyzygos {run['version']}, " if run.get("version") else "") + f"{run['run_utc']} UT, {run['window_start'][:10]} + {run['window_days']:g} d, {run['targets']} asteroids, "
                   f"{run['candidates']} candidates, {run['solves']} exact solves, {run['hits']} hits"
                   + (f"; targets: {run['targets_from']}" if run.get("targets_from") else "")),
           ("Timing", f"total {run['total_s']:.1f} s: start-up {run['startup_s']:.1f} s, asteroid data "
                      f"{run['init_s']:.1f} s, search {run['search_s']:.1f} s (maps {run['maps_s']:.1f} s); "
                      f"{run['per_asteroid_s']:.2f} s per asteroid, {run['per_solve_s'] * 1000:.0f} ms search time per "
                      f"exact solve" + (f", {run['calc_per_hit_s'] * 1000:.0f} ms calculation per hit"
                                        if "calc_per_hit_s" in run else ""))]
    if run.get("corrections"):
        c = run["corrections"]
        out.append(("Astrometry", f"stellar parallax {'on' if c.get('star_parallax') else 'off'}, light deflection by "
                                  f"Sun, Jupiter, Saturn {'on' if c.get('light_deflection') else 'off'}"
                                  + (f", Gaia bright-star proper-motion bias {'on' if c['gaia_pm_bias'] else 'off'}"
                                     if "gaia_pm_bias" in c else "")
                                  + (f", radial velocity of fast stars {'on' if c['star_rv'] else 'off'}"
                                     if "star_rv" in c else "")))
    if run.get("earth_pck"):
        out.append(("Earth orientation", earth_pck_text(run["earth_pck"], run)))
    return out


def earth_pck_text(e, run):
    """Coverage of the Earth orientation file the run used, and which part of it the search window falls in."""
    from datetime import date, timedelta
    last, stop = e.get("last_datum"), (e.get("stop") or "")[:10]
    txt = (f"earth_latest_high_prec.bpc of {(e.get('created') or '?')[:10]}: measured to {last or '?'}, "
           f"predicted to {stop or '?'}")
    try:
        w0 = date.fromisoformat(run["window_start"][:10])
        w1 = (w0 + timedelta(days=float(run["window_days"]))).isoformat()
    except (KeyError, ValueError):
        return txt
    if last and w1 <= last:
        part = "measured values"
    elif last and w0.isoformat() >= last:
        part = "predicted values"
    else:
        part = f"measured values up to {last}, predicted after" if last else "?"
    return txt + f"; this window ({w0.isoformat()} to {w1}) uses {part}"


def parse_utc(text):
    """'2026-10-08T22:10:05.939' (any number of decimals, optional Z) -> aware UTC datetime. Python before 3.11
    only reads 3 or 6 decimals with datetime.fromisoformat."""
    base, _, frac = str(text).strip().rstrip("Z").partition(".")
    t = datetime.fromisoformat(base).replace(tzinfo=timezone.utc)
    return t + timedelta(seconds=float("0." + frac)) if frac else t


def size_estimated(e):
    """True if the event's asteroid size comes from H with an assumed albedo (no measured diameter)."""
    return str(e.get("size_src") or "").lower().startswith("h only")


def asteroid_label(target_id, name):
    """'218001 (2001 XQ72)' -> '(218001) 2001 XQ72';  '4272 Entsuji (1977 EG5)' -> '(4272) Entsuji'."""
    name = (name or "").strip()
    if name.startswith(("Numbered Asteroid", "Unnumbered")):
        name = ""
    m = re.match(r"^\(?\d+\)?\s*(.*)$", name)
    rest = m.group(1).strip() if m else name
    if rest.startswith("(") and rest.endswith(")") and rest.count("(") == 1:
        rest = rest[1:-1]                                        # only a provisional designation
    else:
        rest = re.sub(r"\s*\([^()]*\)\s*$", "", rest)            # a name is known: drop the designation
    return f"({target_id}) {rest}".strip()


# ---------------------------------------------------------------- azimuth (stdlib spherical astronomy)

def julian_date(dt):
    return 2440587.5 + (dt - datetime(1970, 1, 1, tzinfo=timezone.utc)).total_seconds() / 86400.0


def precess_j2000(ra, dec, jd):
    """J2000 -> mean equator/equinox of date (IAU 1976, Meeus ch. 21); radians."""
    T = (jd - 2451545.0) / 36525.0
    s = lambda arcsec: math.radians(arcsec / 3600.0)
    zeta = s(2306.2181 * T + 0.30188 * T**2 + 0.017998 * T**3)
    z = s(2306.2181 * T + 1.09468 * T**2 + 0.018203 * T**3)
    theta = s(2004.3109 * T - 0.42665 * T**2 - 0.041833 * T**3)
    A = math.cos(dec) * math.sin(ra + zeta)
    B = math.cos(theta) * math.cos(dec) * math.cos(ra + zeta) - math.sin(theta) * math.sin(dec)
    C = math.sin(theta) * math.cos(dec) * math.cos(ra + zeta) + math.cos(theta) * math.sin(dec)
    return math.atan2(A, B) + z, math.asin(max(-1.0, min(1.0, C)))


def alt_az(ra_deg, dec_deg, when, lat_deg, lon_deg):
    """Altitude and azimuth (deg, from north through east) of a J2000 position. Only for records without the search's
    star_az (before 2026-10-16; the search computes it with SPICE and the measured UT1). Here UT1 is taken as UTC (under
    0.01 deg today; with leap seconds ending in 2027 UT1 - UTC grows, ~0.25 deg after a century) and nutation and
    aberration are left out (well under 0.1 deg): fine for a compass direction."""
    jd = julian_date(when)
    ra, dec = precess_j2000(math.radians(ra_deg), math.radians(dec_deg), jd)
    T = (jd - 2451545.0) / 36525.0
    gmst = (280.46061837 + 360.98564736629 * (jd - 2451545.0) + 0.000387933 * T * T - T**3 / 38710000.0) % 360.0
    H = math.radians(gmst + lon_deg) - ra
    phi = math.radians(lat_deg)
    sin_alt = math.sin(dec) * math.sin(phi) + math.cos(dec) * math.cos(phi) * math.cos(H)
    alt = math.degrees(math.asin(max(-1.0, min(1.0, sin_alt))))
    az = math.degrees(math.atan2(-math.cos(dec) * math.sin(H),
                                 math.sin(dec) * math.cos(phi) - math.cos(dec) * math.sin(phi) * math.cos(H))) % 360.0
    return alt, az


def compass(az):
    return COMPASS[int((az + 22.5) // 45) % 8]


# ---------------------------------------------------------------- building events

def file_id(target_id):
    """The target as part of a file or folder name: 'P:Jupiter' -> 'P-Jupiter' (':' is not allowed on Windows);
    asteroid numbers unchanged."""
    return str(target_id).strip().replace(":", "-")


def find_kml(kml_dir, target_id, when, ext="kml"):
    """<kml_dir>/<target>_<YYYYMMDDTHHMM>*.<ext>: the KML ground track, or with ext="svg" the event preview."""
    if not kml_dir or not os.path.isdir(kml_dir):
        return None
    stamp, target_id = when.strftime("%Y%m%dT%H%M"), file_id(target_id)
    found = sorted(glob.glob(os.path.join(glob.escape(kml_dir), f"{glob.escape(str(target_id))}_{stamp}*.{ext}")))
    if ext == "globe":                                           # the whole-Earth view <stem>_globe.svg
        found = sorted(glob.glob(os.path.join(glob.escape(kml_dir), f"{glob.escape(str(target_id))}_{stamp}*_globe.svg")))
    elif ext == "svg":                                           # the preview, not the globe plot
        found = [f for f in found if not f.endswith("_globe.svg")]
    return found[0] if found else None


JPL_SBDB = U.URL_JPL_SBDB_PAGE                                       # asteroid page, + number
VIZIER_GAIA = U.URL_VIZIER_GAIA_DR3                                   # star, + Gaia DR3 id
KML_NS = "{http://www.opengis.net/kml/2.2}"
LINE_STYLES = (("Center line at site height", "#65a30d", 2, "10 4"), ("Centre", "#15803d", 3, None), ("Shadow limit", "#dc2626", 2, None), ("1-sigma", "#7c3aed", 1.5, "2 4"),
               ("3-sigma", "#d97706", 2, "6 6"), ("Satellite zone", "#0891b2", 1.5, "1 5"),
               ("Proper motion", "#db2777", 1.5, "8 3 2 3"))       # the centre with another proper motion (pmcheck)


def kml_to_data(path):
    """Lines and pins of a paths KML as a compact dict ([lat, lon] order, ~1 m precision).
    Line colours are re-mapped to map-friendly ones (the KML uses neon colours meant for Google Earth).
    Longitudes along a line are made continuous across the date line (178.8 after -179.8 becomes -181.2), else a
    web map draws that step the long way round, as a straight line across the whole map; each line is then
    shifted by 360 deg so that its part nearest the observer pin lies next to it."""
    root = ET.parse(path).getroot()
    lines, pins = [], []
    for pm in root.iter(KML_NS + "Placemark"):
        name = (pm.findtext(KML_NS + "name") or "").strip()
        ls = pm.find(f".//{KML_NS}LineString/{KML_NS}coordinates")
        pt = pm.find(f".//{KML_NS}Point/{KML_NS}coordinates")
        if ls is not None and ls.text:
            pts = []
            for tok in ls.text.split():
                c = tok.split(",")
                if len(c) >= 2:
                    pts.append([round(float(c[1]), 5), round(float(c[0]), 5)])
            color, width, dash = "#2563eb", 2, None
            for prefix, col, w, d in LINE_STYLES:
                if name.startswith(prefix):
                    color, width, dash = col, w, d
                    break
            lines.append(dict(name=name, color=color, width=width, dash=dash, pts=pts))
        elif pt is not None and pt.text:
            c = pt.text.strip().split(",")
            pins.append(dict(name=name, desc=(pm.findtext(KML_NS + "description") or "").strip(),
                             lat=round(float(c[1]), 5), lon=round(float(c[0]), 5)))
    ref = next((p["lon"] for p in pins if p["name"] == "Observer"), 0.0)
    for ln in lines:
        pts = ln["pts"]
        for i in range(1, len(pts)):                              # continuous across the date line
            while pts[i][1] - pts[i - 1][1] > 180:
                pts[i][1] -= 360
            while pts[i][1] - pts[i - 1][1] < -180:
                pts[i][1] += 360
        if pts:
            k = min((-2, -1, 0, 1, 2), key=lambda k: min(abs(p[1] + 360 * k - ref) for p in pts))
            for p in pts:
                p[1] = round(p[1] + 360 * k, 5)
    centre = next((ln["pts"] for ln in lines if ln["name"].startswith("Centre")), [])
    for p in pins:                                                # minute marks: on their (shifted) line
        if p["name"] != "Observer" and centre:
            k = min((-2, -1, 0, 1, 2), key=lambda k: min(abs(q[1] - p["lon"] - 360 * k) + abs(q[0] - p["lat"])
                                                         for q in centre))
            p["lon"] = round(p["lon"] + 360 * k, 5)
    return dict(lines=lines, pins=pins)


def size_source_text(src):
    """A size source for a hover text: 'SBDB diameter (NEOWISE)' instead of SBDB's reference with its URN and web
    address; other texts unchanged."""
    src = (src or "").strip()
    if "(ref" not in src:
        return src
    base, ref = src.split("(ref", 1)
    low = ref.lower()
    name = next((n for k, n in (("neowise", "NEOWISE"), ("akari", "AKARI"), ("iras", "IRAS"), ("msx", "MSX"),
                                ("occult", "occultations"), ("radar", "radar")) if k in low), None)
    if not name:
        m = re.search(r"abs/(\d{4}[A-Za-z&.]+[\d.]+[A-Z])", ref)          # an ADS bibcode
        name = m[1] if m else ref.strip(" ()")[:40]
    return f"{base.strip()} ({name})"


def star_label(r):
    """(name, other names) of an event's star: 'UCAC4 573-029535' when the record has a UCAC4 number (catalog part
    xref), else 'Gaia DR3 <id>'; the other names (Gaia DR3, TYC, HIP) for a hover text."""
    gaia = f"Gaia DR3 {str(r.get('star') or '').strip()}" if str(r.get("star") or "").strip() else ""
    u, t, h = (str(r.get(k) or "").strip() for k in ("star_ucac4", "star_tyc", "star_hip"))
    if h.endswith(".0"):
        h = h[:-2]
    others = [x for x in (gaia if u else "", f"TYC {t}" if t else "", f"HIP {h}" if h else "") if x]
    return (f"UCAC4 {u}" if u else gaia), " · ".join(others)


def sky_names(r):
    """The star's names a planetarium may know, best first, joined by '|' for the KStars/Stellarium buttons: 'HIP n'
    (catalog part xref), then 'Gaia DR3 <id>' (Stellarium finds both when its star catalogs reach the star; it does
    not know TYC names). '' without any."""
    h = str(r.get("star_hip") or "").strip()
    h = h[:-2] if h.endswith(".0") else h
    g = str(r.get("star") or "").strip().split(".")[0]
    return "|".join(x for x in (f"HIP {h}" if h else "", f"Gaia DR3 {g}" if g.isdigit() else "") if x)


def build_event(r, lat, lon, kml_dir, out_dir):
    when = parse_utc(r["best_utc"])
    tid = r["target_id"].strip()
    mag, drop = num(r.get("mag")), num(r.get("mag_drop"))
    speed, rad = num(r.get("speed_kms")), num(r.get("r_km"))
    dur = num(r.get("max_duration_s"))
    if dur is None and speed and rad is not None:
        dur = 2 * rad / speed
    alt, az = num(r.get("star_alt")), num(r.get("star_az"))
    ra, dec = num(r.get("star_ra")), num(r.get("star_dec"))
    if az is None and None not in (ra, dec, lat, lon):
        calc_alt, az = alt_az(ra, dec, when, lat, lon)
        alt = calc_alt if alt is None else alt
    moon = None
    if (num(r.get("moon_alt_deg")) or -1) > 0 and num(r.get("moon_sep_deg")) is not None:
        age = num(r.get("moon_age_deg"))
        icon = MOON_ICONS[int(round(age / 45.0)) % 8] if age is not None else "🌙"
        illum = num(r.get("moon_illum_pct"))
        moon = dict(icon=icon, sep=num(r["moon_sep_deg"]), alt=num(r["moon_alt_deg"]), illum=illum)
    kml_abs = find_kml(kml_dir, tid, when)
    prev_abs = find_kml(kml_dir, tid, when, "svg")
    fov = 2.0                                                    # deg; the preview's field when there is one
    if prev_abs:
        try:
            with open(prev_abs, encoding="utf-8") as f:
                m = re.search(r"field (\d+(?:\.\d+)?)\u2032", f.read())
            fov = float(m[1]) / 60.0 if m else fov
        except OSError:
            pass
    preview = urllib.parse.quote(os.path.relpath(prev_abs, out_dir).replace(os.sep, "/")) if prev_abs else None
    globe_abs = find_kml(kml_dir, tid, when, "globe")
    globe = urllib.parse.quote(os.path.relpath(globe_abs, out_dir).replace(os.sep, "/")) if globe_abs else None
    kml = urllib.parse.quote(os.path.relpath(kml_abs, out_dir).replace(os.sep, "/")) if kml_abs else None
    miss, margin = num(r.get("min_distance")), num(r.get("margin_km"))
    if margin is None and miss is not None and rad is not None:
        margin = miss - rad
    body = ":" in tid                                            # a planet or moon (bodies.py: P:Jupiter, M:Io)
    label = (r.get("target_name") or tid.split(":", 1)[1]).strip() if body else asteroid_label(tid, r.get("target_name"))
    return dict(when=when, label=label, full=(r.get("target_name") or "").strip(), tid=tid, body=body, kind=(r.get("kind") or ("asteroid" if not body else "")).strip(),
                d_utc=(r.get("d_utc") or "").strip(), r_utc=(r.get("r_utc") or "").strip(),
                contact_dur=num(r.get("duration_s")) if (r.get("d_utc") or "").strip() else None,
                star=r.get("star", "").strip(), star_name=star_label(r)[0], star_tip=star_label(r)[1], sky_names=sky_names(r),
                hz=(str(r.get("horizon_flag") or "").strip(), num(r.get("horizon_alt")), num(r.get("horizon_sep_deg"))),
                mag=mag, drop=drop, dur=dur, alt=alt,
                compass=compass(az) if az is not None else "", az=az, moon=moon,
                miss=miss, margin=margin, rad=rad, hshift=num(r.get("height_shift_km")), kml=kml, kml_abs=kml_abs, preview=preview,
                m_ast=num(r.get("m_ast")), m_before=num(r.get("m_before")), calc=num(r.get("calc_s")),
                sun=num(r.get("sun_alt")),
                margin_mag=num(r.get("mag_margin")), airmass=num(r.get("airmass")), ext=num(r.get("extinction_mag")),
                size_src=(r.get("size_source") or "").strip(), utc=r["best_utc"].strip(),
                drop_blend=num(r.get("mag_drop_blended")), dhint=(r.get("double_hint") or "").strip(),
                sflag=(r.get("star_flag") or "").strip(), star_sigma=num(r.get("star_sigma_km")),
                pm_alts=(r.get("star_pm_alts") or "").strip(),
                p_site=num(r.get("p_site")), sigma1=num(r.get("path_sigma1_km")),
                ruwe=num(r.get("star_ruwe")) if num(r.get("star_ruwe")) is not None else num(r.get("gaia_ruwe")),
                sigma_src=(r.get("sigma_source") or "").strip(), ra=ra, dec=dec, fov=fov,
                globe=globe)


def dedupe(events, tol=300.0):
    """Reruns append the same event again; the later log line replaces the earlier one."""
    kept = []
    for ev in events:
        for i, k in enumerate(kept):
            if k["tid"] == ev["tid"] and k["star"] == ev["star"] and abs((k["when"] - ev["when"]).total_seconds()) < tol:
                kept[i] = ev
                break
        else:
            kept.append(ev)
    return kept


def fmt_time(when):
    t = when + timedelta(seconds=0.5)
    return f"{t.year}-{MONTHS[t.month - 1]}-{t.day:02d} {t:%H:%M:%S}"


def fmt(v, nd=2, unit=""):
    return "—" if v is None else f"{v:.{nd}f}{unit}"


def alt_text(e):
    return "—" if e["alt"] is None else f"{e['alt']:.0f}° {e['compass']}".rstrip()


def horizon_text(e):
    """'' or the site horizon's warning: 'behind horizon (28°)' / 'near horizon (6° from it)'."""
    flag, h, sep = e.get("hz") or ("", None, None)
    if flag == "behind":
        return f"behind horizon ({h:.0f}° there)" if h is not None else "behind horizon"
    if flag == "near":
        return f"near horizon ({sep:.0f}° from it)" if sep is not None else "near horizon"
    return ""


def horizon_mark(e):
    """A mountain mark after the altitude for the site's own horizon (horizon.py): yellow behind it, red near it
    (OccultWatcher's colours); '' without a warning."""
    t = horizon_text(e)
    if not t:
        return ""
    col = "#b45309" if t.startswith("behind") else "#dc2626"
    return f' <span class="hzmark" style="color:{col}" title="{esc(t)}">\u26f0</span>'


def alt_cell(e, tip):
    """The altitude cell: '45° SE'; with the page's 'azimuth in degrees' switch '45° az 132°' (data-az, AZ_JS); the
    site horizon's mark after it."""
    az = f' data-az="{e["az"]:.0f}"' if e.get("az") is not None and e["alt"] is not None else ""
    sort = "" if e["alt"] is None else f"{e['alt']:.1f}"
    hz = horizon_text(e)
    tip = tip + (esc(" · " + hz) if hz else "")
    return (f'<td data-s="{sort}" title="{tip}"><span class="altcell"{az}>{esc(alt_text(e))}</span>'
            f'{horizon_mark(e)}</td>')


AZ_SWITCH = ('<span class="azsw" title="Tick: the star\'s azimuth in degrees (north 0, east 90) instead of the '
             'compass direction (remembered)"><input type="checkbox" id="azdeg">az°</span>')   # in the Altitude header
AZ_JS = """<script>
(function(){var b=document.getElementById('azdeg');if(!b)return;
var w=b.parentNode;w.addEventListener('click',function(ev){ev.stopPropagation();if(ev.target!==b){b.checked=!b.checked;
 b.dispatchEvent(new Event('change'));}});                    // in the header: no sorting by this click
var cs=[].slice.call(document.querySelectorAll('.altcell[data-az]'));cs.forEach(function(c){c.dataset.cmp=c.textContent;});
function show(on){cs.forEach(function(c){c.textContent=on?c.dataset.cmp.split(' ')[0]+' az '+c.dataset.az+'\u00b0':c.dataset.cmp;});
 try{localStorage.setItem('az_deg',on?'1':'0');}catch(e){}}
try{b.checked=localStorage.getItem('az_deg')==='1';}catch(e){}
b.addEventListener('change',function(){show(b.checked);});if(b.checked)show(true);})();
</script>"""


def moon_text(e):
    return "" if not e["moon"] else f"{e['moon']['icon']} {e['moon']['sep']:.0f}°"


# ---------------------------------------------------------------- HTML

CSS = """
.azsw{display:block;font-size:.75rem;font-weight:normal;text-transform:none;color:var(--muted);white-space:nowrap;
 cursor:pointer;margin-top:2px}
td.mag{white-space:normal;min-width:4.2em} td.evtime .tz{font-size:.8rem;color:var(--muted)}
.azsw input{vertical-align:middle;margin:0 2px 0 0;cursor:pointer}.favbar{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin:0 0 10px}
:root{--bg:#f6f7f9;--card:#fff;--ink:#16202b;--muted:#5d6b7a;--line:#e1e5ea;--head:#eef1f5;--accent:#1f6feb;
--in-bg:#dff5e6;--in-ink:#14653a;--near-bg:#fdf0d2;--near-ink:#7a5200}
@media (prefers-color-scheme:dark){:root{--bg:#10151b;--card:#171e26;--ink:#e6ebf1;--muted:#93a1b1;--line:#2a3441;
--head:#1e2732;--accent:#6aa6ff;--in-bg:#17402a;--in-ink:#8be0ae;--near-bg:#4a3a12;--near-ink:#f3cf7a}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:1440px;margin:0 auto;padding:24px 16px 40px}
h1{font-size:1.35rem;margin:0 0 4px}
.sub{color:var(--muted);margin:0 0 16px}
.info{display:grid;grid-template-columns:max-content 1fr;gap:2px 14px;font-size:.88rem;margin:0 0 16px}
.info dt{color:var(--muted)}.info dd{margin:0}
.wrap{overflow-x:auto;background:var(--card);border:1px solid var(--line);border-radius:10px}
table{border-collapse:collapse;width:100%;min-width:760px}
th,td{padding:8px 7px;text-align:left;white-space:nowrap;border-bottom:1px solid var(--line)}
th{white-space:normal;vertical-align:bottom}
td.tools{white-space:normal;min-width:9.5em} td.ast{white-space:normal;min-width:9em}
td .sub{white-space:normal} .badge{white-space:nowrap}
@media (max-width:1180px){.c-narrow{display:none}}   /* favorites on narrow windows: note and date are in the panel */ td.tools .mapbtn{margin:2px 0}
th{background:var(--head);font-size:.8rem;text-transform:uppercase;letter-spacing:.03em;color:var(--muted);
cursor:pointer;user-select:none;position:sticky;top:0}
th.sorted-asc::after{content:" ▲"}th.sorted-desc::after{content:" ▼"}
tbody tr:last-child td{border-bottom:0}
tbody tr:hover{background:var(--head)}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
.sub{display:block;color:var(--muted);font-size:.78rem;line-height:1.5}
.badge{display:inline-block;padding:0 8px;border-radius:99px;font-size:.78rem}
.in{background:var(--in-bg);color:var(--in-ink)}.near{background:var(--near-bg);color:var(--near-ink)}
a{color:var(--accent)}
a.owc{display:inline-block;margin-top:2px;padding:0 6px;border-radius:6px;font-size:.78rem;text-decoration:none;
 background:color-mix(in srgb,#2563eb 14%,transparent);color:var(--accent)}
.badge.kind{background:color-mix(in srgb,#7c3aed 14%,transparent);color:#6d28d9;font-size:.72rem}
sup.bin{color:#0891b2;font-weight:600;margin-left:3px;cursor:help;white-space:nowrap}
span.dbl{color:#b26a00;font-weight:600;cursor:help;white-space:nowrap}
span.sflag{color:#b26a00;font-size:85%;cursor:help;white-space:nowrap}
span.twi{color:#8a6d00;font-size:85%;cursor:help;white-space:nowrap}
span.swarn2{color:#92400e;background:#fde68a;font-weight:600;font-size:85%;padding:0 4px;border-radius:3px;cursor:help;white-space:nowrap}
span.swarn{color:#fff;background:#c62828;font-weight:700;font-size:85%;padding:0 4px;border-radius:3px;cursor:help;white-space:nowrap}
span.sizeest{color:#3730a3;background:#e0e7ff;font-weight:600;font-size:75%;padding:0 4px;border-radius:3px;
 cursor:help;white-space:nowrap;vertical-align:middle}
.notes{color:var(--muted);font-size:.85rem;margin-top:16px}
.notes li{margin:3px 0}
.empty{padding:28px;text-align:center;color:var(--muted)}
"""

JS = """
// sortable columns; the last sort of each page (results, favorites, planets and moons) is kept in the browser and
// applied again when the page loads (a rebuilt report keeps its order)
var SORTKEY='pyo_sort:'+location.pathname;
function thKey(th){return th.textContent.replace(/\\s+/g,' ').trim();}
document.querySelectorAll('th[data-k]').forEach(function(th){
  th.addEventListener('click',function(){
    var tb=th.closest('table').tBodies[0],i=th.cellIndex,rows=Array.from(tb.rows),
        dir=th.classList.contains('sorted-asc')?-1:1;
    try{localStorage.setItem(SORTKEY,JSON.stringify({k:thKey(th),d:dir}));}catch(e){}
    th.closest('tr').querySelectorAll('th').forEach(function(h){h.classList.remove('sorted-asc','sorted-desc')});
    th.classList.add(dir===1?'sorted-asc':'sorted-desc');
    rows.sort(function(a,b){
      var x=a.cells[i].dataset.s||'',y=b.cells[i].dataset.s||'',num=/^\\s*-?\\d+(\\.\\d+)?([eE][-+]?\\d+)?\\s*$/;
      var c=(num.test(x)&&num.test(y))?parseFloat(x)-parseFloat(y):x.localeCompare(y);return c*dir;});
    rows.forEach(function(r){tb.appendChild(r)});
  });
});
(function(){try{var s=JSON.parse(localStorage.getItem(SORTKEY)||'null');if(!s)return;
 var th=Array.from(document.querySelectorAll('th[data-k]')).find(function(h){return thKey(h)===s.k;});if(!th)return;
 th.classList.remove('sorted-asc','sorted-desc');th.click();if(s.d===-1)th.click();}catch(e){}})();
"""


MAP_CSS = """
.mapbtn,.tb{font:inherit;font-size:.85rem;padding:2px 10px;border:1px solid var(--line);border-radius:6px;background:var(--head);color:var(--ink);cursor:pointer}
.mapbtn:hover,.tb:hover{border-color:var(--accent);color:var(--accent)}
dialog{width:min(980px,96vw);height:min(720px,90vh);padding:0;border:1px solid var(--line);border-radius:12px;background:var(--card);color:var(--ink);overflow:hidden}
dialog[open]{display:flex;flex-direction:column}
dialog::backdrop{background:rgba(0,0,0,.55)}
.dh{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:10px 14px;border-bottom:1px solid var(--line)}
.dh h2{font-size:1rem;margin:0}
.dh button{font:inherit;font-size:1.1rem;border:0;background:none;color:var(--muted);cursor:pointer}
#map{flex:1;min-height:200px;background:#cfd8e3;color:#16202b;padding:0}
.df{display:flex;flex-wrap:wrap;gap:8px 14px;align-items:center;padding:10px 14px;border-top:1px solid var(--line);font-size:.85rem}
.legend{margin-left:auto;color:var(--muted)}
.legend i{display:inline-block;width:18px;height:3px;margin:0 5px 2px 12px;vertical-align:middle}
.legend i.dash{background:repeating-linear-gradient(90deg,#d97706 0 6px,transparent 6px 10px)}
.legend i.dot{background:repeating-linear-gradient(90deg,#7c3aed 0 2px,transparent 2px 5px)}
"""

LEAFLET_TAGS = (f'<link rel="stylesheet" href="{U.URL_LEAFLET_CSS}">'
                f'<script defer src="{U.URL_LEAFLET_JS}"></script>')

TOAST_JS = """<script>
function pyoToast(msg,stay){var t=document.getElementById('pyotoast');if(!t){t=document.createElement('div');t.id='pyotoast';
 t.setAttribute('role','status');t.style.cssText='position:fixed;left:50%;bottom:20px;transform:translateX(-50%);'+
 'max-width:min(720px,92vw);padding:10px 14px;border-radius:8px;background:#1e293b;color:#f8fafc;font-size:.9rem;'+
 'box-shadow:0 4px 16px rgba(0,0,0,.3);z-index:1000';document.body.appendChild(t);}
 t.textContent=msg;t.hidden=false;clearTimeout(t._h);t._h=setTimeout(function(){t.hidden=true;},stay?9000:4000);}
</script>"""

FAV_JS = """<script>
(function(){var bs=document.querySelectorAll('.favbtn');if(!bs.length||location.protocol==='file:')return;
var ON='In the favorites: click to remove it again',OFF='Add to the favorites (with its map and preview)';
function tell(){try{if(parent&&parent!==window&&parent.emitEvent)parent.emitEvent('fav_changed','');}catch(e){}}
function mark(b,on){b.textContent=on?'★':'☆';b.title=on?ON:OFF;}
fetch('/api/favorites/keys').then(function(r){return r.json();}).then(function(j){
 var have=new Set(j.keys||[]),edited=new Set(j.edited||[]);        // edited: a note or a status set
 bs.forEach(function(b){b.hidden=false;mark(b,have.has(b.dataset.key));
  b.addEventListener('click',function(){
   if(b.textContent==='★'){                    // a favorite: remove it again (asked first only if you edited it)
    if(edited.has(b.dataset.key)&&!confirm('Remove this event from the favorites?\\nIts status and note are '+
      'deleted with it.'))return;
    fetch('/api/favorites/remove?'+new URLSearchParams({keys:b.dataset.key})).then(function(r){return r.json();})
     .then(function(j){if(j.ok){mark(b,false);tell();}pyoToast(j.msg,!j.ok);})
     .catch(function(){pyoToast('Favorites: no answer from the GUI',true);});return;}
   var q=new URLSearchParams({tid:b.dataset.tid,utc:b.dataset.utc});
   fetch('/api/favorites/add?'+q).then(function(r){return r.json();}).then(function(j){
    if(j.ok){mark(b,true);tell();}pyoToast(j.msg,!j.ok);})
   .catch(function(){pyoToast('Favorites: no answer from the GUI',true);});});});}).catch(function(){});})();
</script>"""

FAVPAGE_JS = """<style>
.favbar{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin:0 0 10px;font-size:.9rem}
.favbar select{font:inherit;padding:2px 4px}
th,td{padding:8px 6px} tr.favrow{cursor:pointer} tr.favrow.cur td{background:color-mix(in srgb,var(--accent) 12%,transparent)}
td.note{max-width:12em;overflow:hidden;text-overflow:ellipsis}
tr.favrow td:last-child{white-space:normal;min-width:9.5em}
</style><script>
(function(){
var boxes=[].slice.call(document.querySelectorAll('.favsel')),all=document.getElementById('favall'),
    cnt=document.getElementById('favcount');
function shown(b){var r=b.closest('tr');return !r||r.style.display!=='none';}   // rows the filter hides: never acted on
function sel(){return boxes.filter(function(b){return b.checked&&shown(b);}).map(function(b){return b.value;});}
function upd(){var v=boxes.filter(shown);cnt.textContent=sel().length+' selected';
 if(all)all.checked=v.length>0&&sel().length===v.length;}
document.addEventListener('pyofilter',upd);
boxes.forEach(function(b){b.addEventListener('change',upd);});
if(all)all.addEventListener('change',function(){boxes.forEach(function(b){if(shown(b)||!all.checked)b.checked=all.checked;});upd();});
function tell(n,a){try{if(parent&&parent!==window&&parent.emitEvent)parent.emitEvent(n,a);}catch(e){}}
function call(url,done){fetch(url).then(function(r){return r.json();}).then(function(j){pyoToast(j.msg,!j.ok);
  tell('fav_changed','');if(j.ok)setTimeout(function(){location.reload();},700);})
 .catch(function(){pyoToast('Favorites: no answer from the GUI (open this page from the GUI)',true);});}
function need(){var k=sel();if(!k.length){pyoToast('Select events first (check boxes on the left)');return null;}return k;}
document.getElementById('favsetst').addEventListener('click',function(){var k=need();if(!k)return;
 call('/api/favorites/update?'+new URLSearchParams({keys:k.join(','),status:document.getElementById('favstatus').value}));});
document.getElementById('favdel').addEventListener('click',function(){var k=need();if(!k)return;
 if(confirm('Remove '+k.length+' favorite(s) with their copied maps and previews?'))
  call('/api/favorites/remove?'+new URLSearchParams({keys:k.join(',')}));});
document.getElementById('favpast').addEventListener('click',function(){
 if(confirm('Remove every favorite whose event is before today (UTC)?'))call('/api/favorites/cleanup');});
document.querySelectorAll('tr.favrow').forEach(function(tr){tr.addEventListener('click',function(ev){
 if(ev.target.closest('input,button,a'))return;
 document.querySelectorAll('tr.favrow.cur').forEach(function(x){x.classList.remove('cur');});
 tr.classList.add('cur');tell('fav_select',tr.dataset.key);});});
upd();
// event times: UT (default), this computer's time zone, or each site's time zone; remembered in this browser.
// (tsel, not sel: sel() above is the selection helper, a var of the same name in this function would replace it)
var cells=[].slice.call(document.querySelectorAll('td.evtime')),tsel=document.getElementById('favtime'),
    head=document.getElementById('evtimehead'),M=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
cells.forEach(function(c){c.dataset.ut=c.textContent;});
function zoned(c,tz){var o={year:'numeric',month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit',
  second:'2-digit',hour12:false,timeZoneName:'short'};if(tz)o.timeZone=tz;var p={};
  try{new Intl.DateTimeFormat('en-US',o).formatToParts(new Date(c.dataset.utc)).forEach(function(x){p[x.type]=x.value;});}
  catch(e){return [c.dataset.ut,''];}
  return [p.year+'-'+M[+p.month-1]+'-'+('0'+p.day).slice(-2)+' '+(p.hour==='24'?'00':p.hour)+':'+p.minute+':'+p.second,
    p.timeZoneName||''];}
function put(c,v){c.textContent=v[0];if(v[1]){c.appendChild(document.createElement('br'));   // the zone below: narrower
  var z=document.createElement('span');z.className='tz';z.textContent=v[1];c.appendChild(z);}}
function show(mode){cells.forEach(function(c){put(c,mode==='local'?zoned(c,null):
  mode==='site'?(c.dataset.tz?(function(v){return [v[0],v[1]+' ('+c.dataset.tz.split('/').pop().replace(/_/g,' ')+')'];})(
  zoned(c,c.dataset.tz)):[c.dataset.ut,'UT (site zone unknown)']):[c.dataset.ut,'']);});
  if(head)head.firstChild.textContent={ut:'Event time (UT)',local:'Event time (local)',site:'Event time (site)'}[mode];
  try{localStorage.setItem('fav_time',mode);}catch(e){}}
if(tsel){try{var m=localStorage.getItem('fav_time');if(m)tsel.value=m;}catch(e){}
  tsel.addEventListener('change',function(){show(tsel.value);});if(tsel.value!=='ut')show(tsel.value);}
})();
</script>"""

KSTARS_JS = """<script>
(function(){var site=__SITE__,bs=document.querySelectorAll('.ksbtn');if(!bs.length||location.protocol==='file:')return;
fetch('/api/kstars/status').then(function(r){return r.json();}).then(function(j){if(!j.ok)return;
 bs.forEach(function(b){b.hidden=false;b.addEventListener('click',function(){
  var q=new URLSearchParams({ra:b.dataset.ra,dec:b.dataset.dec,utc:b.dataset.utc,fov:b.dataset.fov});
  if(b.dataset.names)q.set('names',b.dataset.names);
  var st=b.dataset.lat?{lat:b.dataset.lat,lon:b.dataset.lon,ele:b.dataset.ele}:site;
  if(st){q.set('lat',st.lat);q.set('lon',st.lon);q.set('ele',st.ele||0);}
  b.textContent='KStars …';
  fetch('/api/kstars/show?'+q).then(function(r){return r.json();}).then(function(j){
   b.textContent=j.ok?'KStars ✓':'KStars ✗';b.title=j.msg;pyoToast(j.msg,!j.ok||j.msg.indexOf('; ')>0);
   setTimeout(function(){b.textContent='KStars';},4000);})
  .catch(function(){b.textContent='KStars ✗';pyoToast('KStars: no answer from the GUI',true);});});});}).catch(function(){});})();
(function(){var site=__SITE__,bs=document.querySelectorAll('.stbtn');if(!bs.length||location.protocol==='file:')return;
 bs.forEach(function(b){b.hidden=false;b.addEventListener('click',function(){
  var q=new URLSearchParams({ra:b.dataset.ra,dec:b.dataset.dec,utc:b.dataset.utc,fov:b.dataset.fov});
  if(b.dataset.names)q.set('names',b.dataset.names);
  var st=b.dataset.lat?{lat:b.dataset.lat,lon:b.dataset.lon,ele:b.dataset.ele}:site;
  if(st){q.set('lat',st.lat);q.set('lon',st.lon);q.set('ele',st.ele||0);}
  b.textContent='Stellarium …';
  fetch('/api/stellarium/show?'+q).then(function(r){return r.json();}).then(function(j){
   b.textContent=j.ok?'Stellarium ✓':'Stellarium ✗';b.title=j.msg;pyoToast(j.msg,!j.ok);
   setTimeout(function(){b.textContent='Stellarium';},4000);})
  .catch(function(){b.textContent='Stellarium ✗';pyoToast('Stellarium: no answer from the GUI',true);});});});})();
</script>"""

PREVIEW_DIALOG = """<dialog id="prevdlg" aria-label="Event preview" style="width:auto;height:auto;max-width:96vw;max-height:96vh">
<div class="dh"><h2>Preview</h2><button id="prevclose" type="button" aria-label="Close preview">✕</button></div>
<img id="previmg" alt="Event preview" style="display:block;max-width:min(560px,94vw);max-height:84vh;margin:0 auto">
</dialog>
<script>
(function(){var d=document.getElementById('prevdlg'),img=document.getElementById('previmg');
document.querySelectorAll('.prevbtn').forEach(function(b){b.addEventListener('click',function(){
  d.querySelector('h2').textContent=b.dataset.t;img.src=b.dataset.src;
  img.style.maxWidth=b.dataset.wide?'min(1024px,94vw)':'min(560px,94vw)';if(!d.open)d.showModal();});});
document.getElementById('prevclose').addEventListener('click',function(){d.close();});
d.addEventListener('click',function(ev){if(ev.target===d)d.close();});})();
</script>"""

DIALOG = """<dialog id="mapdlg" aria-label="Shadow path map">
<div class="dh"><h2>Map</h2><button id="mapclose" type="button" aria-label="Close map">✕</button></div>
<div id="map"></div>
<div class="df"><button class="tb" id="mapobs" type="button">Zoom to observer</button>
<button class="tb" id="mapall" type="button">Whole path</button>
<a id="mapgm" target="_blank" rel="noopener" hidden>Closest centre-line point in Google Maps</a>
<span class="legend"><i style="background:#15803d"></i>centre line<i style="background:#dc2626"></i>shadow limits<i class="dot"></i>1σ limits<i class="dash"></i>3σ limits</span></div>
</dialog>"""

MAP_JS = """
(function(){
var DATA=JSON.parse(document.getElementById('pathdata').textContent),TILES=__TILES__,OBS0=__OBS__,
    dlg=document.getElementById('mapdlg'),box=document.getElementById('map'),gm=document.getElementById('mapgm'),
    map=null,layer=null,obs=null,near=null;
function nearest(line,o){            /* closest point of a polyline to o; equirectangular is fine at this scale */
  var k=Math.cos(o[0]*Math.PI/180),best=null;
  for(var i=0;i<line.length-1;i++){
    var ax=(line[i][1]-o[1])*k,ay=line[i][0]-o[0],bx=(line[i+1][1]-o[1])*k,by=line[i+1][0]-o[0],
        dx=bx-ax,dy=by-ay,L2=dx*dx+dy*dy,t=L2?Math.max(0,Math.min(1,-(ax*dx+ay*dy)/L2)):0,
        px=ax+t*dx,py=ay+t*dy,d=px*px+py*py;
    if(!best||d<best.d)best={d:d,lat:o[0]+py,lon:o[1]+px/k};
  }
  return best;
}
function zoomAll(){if(map&&layer)map.fitBounds(layer.getBounds(),{padding:[20,20]});}
function zoomObs(){
  if(!map)return;
  if(obs&&near)map.fitBounds([[obs[0],obs[1]],[near.lat,near.lon]],{padding:[70,70],maxZoom:11});
  else if(obs)map.setView(obs,7);
  else zoomAll();
}
function show(key,title){
  var d=DATA[key];if(!d)return;
  dlg.querySelector('h2').textContent=title;
  if(!dlg.open)dlg.showModal();
  if(!window.L){box.innerHTML='<p style="margin:14px">The map library could not be loaded (offline?). Use the KML link instead.</p>';return;}
  if(!map){box.textContent='';                 /* only before the first map: later it would remove Leaflet's panes */
    map=L.map(box,{worldCopyJump:true});
    L.tileLayer(TILES,{maxZoom:18,attribution:'&copy; OpenStreetMap contributors'}).addTo(map);}
  if(layer)layer.remove();
  layer=L.featureGroup().addTo(map);
  var centre=null;obs=OBS0;
  d.lines.forEach(function(l){
    L.polyline(l.pts,{color:l.color,weight:l.width,dashArray:l.dash||null}).bindTooltip(l.name,{sticky:true}).addTo(layer);
    if(!centre&&l.name.indexOf('Centre')===0)centre=l.pts;
  });
  d.pins.forEach(function(p){
    if(p.name==='Observer'){obs=[p.lat,p.lon];
      L.circleMarker(obs,{radius:7,color:'#fff',weight:2,fillColor:'#e11d48',fillOpacity:1}).bindTooltip('Observer',{permanent:true,direction:'right'}).addTo(layer);}
    else L.circleMarker([p.lat,p.lon],{radius:3,color:'#15803d',weight:1,fillOpacity:1}).bindTooltip(p.name+(p.desc?' · '+p.desc:'')).addTo(layer);
  });
  near=(obs&&centre&&centre.length>1)?nearest(centre,obs):null;
  if(near){gm.href='__GMAPS__'+near.lat.toFixed(5)+','+near.lon.toFixed(5);gm.hidden=false;}
  else gm.hidden=true;
  setTimeout(function(){map.invalidateSize();zoomObs();},0);
}
document.querySelectorAll('.mapbtn').forEach(function(b){b.addEventListener('click',function(){show(b.dataset.k,b.dataset.t);});});
document.getElementById('mapobs').addEventListener('click',zoomObs);
document.getElementById('mapall').addEventListener('click',zoomAll);
document.getElementById('mapclose').addEventListener('click',function(){dlg.close();});
dlg.addEventListener('click',function(ev){if(ev.target===dlg)dlg.close();});
})();
"""


def map_script(paths, meta):
    data = json.dumps(paths, separators=(",", ":")).replace("</", "<\\/")
    js = (MAP_JS.replace("__TILES__", json.dumps(meta["tiles"])).replace("__OBS__", json.dumps(meta["obs"]))
          .replace("__GMAPS__", U.URL_GOOGLE_MAPS_SEARCH))
    return f'<script id="pathdata" type="application/json">{data}</script><script>{js}</script>'


def esc(s):
    return html.escape(str(s), quote=True)


def shadow_cell(e):
    if e["miss"] is None:
        return '<td class="num" data-s="">—</td>'
    m = e["margin"]
    if m is None:
        sub = ""
    elif m <= 0:
        sub = '<span class="sub"><span class="badge in" title="inside the shadow path">inside</span></span>'
    elif m <= NEAR_KM:
        sub = (f'<span class="sub"><span class="badge near" title="{m:.1f} km outside the shadow path">'
               f'{m:.1f} km out</span></span>')
    else:
        sub = f'<span class="sub" title="{m:.1f} km outside the shadow path">{m:.1f} km out</span>'
    tip = height_text(e.get("hshift"))
    tip = f' title="{esc(tip)}"' if tip else ""
    return f'<td class="num" data-s="{e["miss"]:.3f}" style="min-width:5.5em"{tip}>{e["miss"]:.1f} km{sub}</td>'


def height_text(km):
    """The site-height shift of the center line (record height_shift_km) as a sentence; '' if not known."""
    if km is None:
        return ""
    side = "A" if km >= 0 else "B"
    return (f"Your site's height moves the center line you see {abs(km):.2f} km across the track (towards limit {side}) "
            f"from the one at height 0 (the map shows both); the distance shown already includes it")



def map_cell(e):
    fav = ("" if e.get("fav") else
           f'<button class="mapbtn favbtn" type="button" hidden data-tid="{esc(e["tid"])}" data-utc="{esc(e["utc"])}" '
           f'data-key="{esc(file_id(e["tid"]))}_{e["when"]:%Y%m%dT%H%M}" aria-label="Favorite">☆</button> ')
    site = e.get("site") or {}                                   # favorites: each row has its own site
    ks_site = (f'data-lat="{site["lat"]}" data-lon="{site["lon"]}" data-ele="{site.get("ele") or 0}" '
               if site.get("lat") is not None and site.get("lon") is not None else "")
    names = f'data-names="{esc(e.get("sky_names") or "")}" ' if e.get("sky_names") else ""
    ks = fav + (f'<button class="mapbtn ksbtn" type="button" hidden data-ra="{e["ra"]:.7f}" data-dec="{e["dec"]:.7f}" '
          f'data-utc="{esc(e["utc"])}" data-fov="{e["fov"]:.3f}" {ks_site}{names}title="Point KStars at the star at the event '
          f'time, seen from the site (Linux, KStars running, report opened from the GUI)">KStars</button> '
          if e.get("ra") is not None and e.get("dec") is not None else "")
    if e.get("ra") is not None and e.get("dec") is not None:     # shown whenever the GUI serves the page (blind try)
        ks += (f'<button class="mapbtn stbtn" type="button" hidden data-ra="{e["ra"]:.7f}" data-dec="{e["dec"]:.7f}" '
               f'data-utc="{esc(e["utc"])}" data-fov="{e["fov"]:.3f}" {ks_site}{names}title="Point Stellarium at the star at '
               f'the event time (Stellarium running with its Remote Control plugin on port 8090; report opened from '
               f'the GUI)">Stellarium</button> ')
    if not e["kml"] and not e.get("preview") and not e.get("globe"):
        return f'<td class="tools">{ks}—</td>' if ks else '<td class="tools">—</td>'
    title = f'{e["label"]} · {fmt_time(e["when"])} UT'
    out = ks
    if e.get("pkey"):
        out += f'<button class="mapbtn" type="button" data-k="{esc(e["pkey"])}" data-t="{esc(title)}">Map</button> '
    if e.get("preview"):
        out += (f'<button class="mapbtn prevbtn" type="button" data-src="{e["preview"]}" data-t="{esc(title)}" '
                f'title="Star field at the event: camera frame, target star, asteroid track">Preview</button> ')
    if e.get("globe"):
        out += (f'<button class="mapbtn prevbtn" type="button" data-src="{e["globe"]}" data-t="{esc(title)}" '
                f'data-wide="1" title="Whole-Earth view: the Earth seen from the star with the shadow path, '
                f'minute marks and the event parameters">Globe</button> ')
    if e["kml"]:
        out += f'<a href="{e["kml"]}" download title="KML for Google Earth or My Maps">KML</a>'
    return f'<td class="tools">{out}</td>'


_OWC = {}


def owc_line(e):
    """'<span class=sub><a class=owc ...>OWC IBEROC · 2 stations</a></span>' under the asteroid when the event was
    looked up in OccultWatcher Cloud (owc.py; cache owc_cache.json in the data folder = the working folder); hover
    lists the stations, the link opens the OWC event page. Empty otherwise."""
    from pysyzygos import owc
    try:
        m = os.path.getmtime(owc.CACHE)
    except OSError:
        return ""
    if _OWC.get("m") != m:
        _OWC.update(m=m, data=owc.load("."))
    hit = owc.info(e["tid"], e["utc"], _OWC["data"])
    if not hit:
        return ""
    label, tip, url = hit
    return (f'<span class="sub"><a class="owc" href="{esc(url)}" target="_blank" rel="noopener" '
            f'title="{esc(tip)}">{esc(label)}</a></span>')


def binary_mark(tid):
    """'<sup class=bin>+moon</sup>' after the asteroid when it has known satellites (binaries.py), with details on
    hover; empty otherwise."""
    from pysyzygos import binaries
    tag = binaries.short(tid)
    return f'<sup class="bin" title="{esc(binaries.text(tid))}">{esc(tag)}</sup>' if tag else ""


def double_mark(e):
    """' <span class=dbl>⚠ 0.82</span>' after the drop when a close or double star is known (doubles.py): the drop
    with the neighbours' light, details on hover; empty otherwise."""
    if not e.get("dhint"):
        return ""
    val = f" {e['drop_blend']:.2f}" if e.get("drop_blend") is not None else ""
    return f' <span class="dbl" title="{esc(e["dhint"])}">\u26a0{val}</span>'


def star_flag_tip(flag):
    """Hover text of a supplement star's flag (gaia_local supplement: RUWE >= 1.4 or a 2-parameter source)."""
    if flag.startswith("RUWE"):
        return (f"Gaia {flag} (>= 1.4): the star's astrometry fits a single star poorly, often an unresolved double; its "
                f"position, and so the shadow path, is less certain than usual. From the high-RUWE supplement of the "
                f"local catalog.")
    if "pm " in flag:                                            # a proper motion from another catalog
        src = flag.split("pm ", 1)[1]
        how = ("from UCAC4's measured position (around 1998) to Gaia's (2016)" if "epoch" in src else f"from {src}")
        return (f"Gaia 2-parameter source: Gaia measured its position only, no parallax or proper motion. Its proper "
                f"motion here is {how}, less precise than Gaia's (sources and the choice: ABOUT.md 2.4.1), so the "
                f"shadow path is less certain than usual.")
    return ("Gaia 2-parameter source: position only, no parallax or proper motion, and none found in UCAC5 or UCAC4; "
            "its position at the event date is off by its unknown motion since 2016 (typically 0.05-0.2\"), so the "
            "shadow path is less certain.")


def star_noted(e):
    """The star's own uncertainty (km, 1 sigma) when it is more than half the asteroid's radius but not more than the
    radius (the amber tier below star_uncertain's red); else None."""
    s, r = e.get("star_sigma"), e.get("rad")
    return s if s is not None and r and 0.5 * r < s <= max(r, 1.0) else None


def star_uncertain(e):
    """The star's own position uncertainty (km, 1 sigma, across the path) when it matters: larger than the asteroid's
    radius (then it decides whether the shadow reaches the site at all); else None."""
    s, r = e.get("star_sigma"), e.get("rad")
    return s if s is not None and s > max(r or 0.0, 1.0) else None


TWILIGHT_SUN_ALT = -12.0          # Sun above this at the site (nautical/civil twilight): marked next to the star


def twilight_text(sun_alt):
    """'☼ -8°' when the Sun is above TWILIGHT_SUN_ALT at the event (twilight; the star must be bright enough to
    see), else ''. sun_alt: degrees or None."""
    if sun_alt is None or sun_alt <= TWILIGHT_SUN_ALT:
        return ""
    return f"\u263c {sun_alt:.0f}\u00b0".replace("-", "\u2212")


def twilight_mark(e):
    """twilight_text as a small HTML mark after the star magnitude, with a hover text."""
    t = twilight_text(e.get("sun"))
    if not t:
        return ""
    kind = "civil twilight" if e["sun"] > -6 else "nautical twilight"
    tip = (f"Twilight: the Sun is {e['sun']:.1f} deg high at the site at the event ({kind}). Only bright enough stars "
           f"can be seen against the sky; check your camera's limit in twilight.")
    return f' <span class="twi" title="{esc(tip)}">{t}</span>'


def star_mark(e):
    """After the star magnitude: a red '⚠ star ±150 km' when the star's position is too uncertain for this path
    (2-parameter star without a proper motion, ...), else the small '⚑ RUWE 1.65' for a supplement star; empty for a
    main-catalog star."""
    f = e.get("sflag") or ""
    if not f:
        return ""
    s = star_uncertain(e)
    alts = (e.get("pm_alts") or "").strip()
    more = (f" Proper-motion estimates (VizieR; their spread sets this uncertainty): {alts}." if alts else "")
    tip = star_flag_tip(f) + (f" The star's position at the event date is uncertain by about {s:.0f} km (1 sigma) "
                              f"across the path, more than the asteroid's radius: this event may well not be "
                              f"observable here; check other predictions (OWC) before observing." if s else "") + more
    if s:
        return f' <span class="swarn" title="{esc(tip)}">\u26a0 star \u00b1{s:.0f} km</span>'
    h = star_noted(e)                                             # half the radius .. the radius: worth a look
    if h:
        tip += (f" The star's position is uncertain by about {h:.0f} km (1 sigma), more than half the asteroid's "
                f"radius: the path may lie noticeably off.")
        return f' <span class="swarn2" title="{esc(tip)}">star \u00b1{h:.0f} km</span>'
    return f' <span class="sflag" title="{esc(tip)}">\u2691 {esc(f)}</span>'


def contact_text(utc):
    """'2026-10-11T02:19:37.48' -> '02:19:37.5'; '' -> '—'."""
    if not utc:
        return "\u2014"
    t = parse_utc(utc)
    return f"{t:%H:%M:}{t.second + t.microsecond / 1e6:04.1f}"


def html_row_body(e):
    """A row of the planets & moons layout: D, closest approach and R at the site, duration, star, sky, chance."""
    s = lambda v, nd=3: "" if v is None else f"{v:.{nd}f}"
    moon = e["moon"]
    moon_tip = esc(f"Moon {moon['alt']:.0f}\u00b0 above horizon, {moon['illum']:.0f}% lit") if moon and moon["illum"] is not None else ""
    alt_tip = esc(f"azimuth {e['az']:.0f}\u00b0" if e["az"] is not None else "")
    dur = e.get("contact_dur")
    dur_txt = "\u2014" if not dur else (f"{dur / 60:.1f} min" if dur >= 120 else f"{dur:.1f} s")
    tip = esc(f"{e.get('full') or e['label']} \u00b7 radius {e['rad']:.0f} km, {size_source_text(e['size_src'])}"
              if e["rad"] else (e.get("full") or ""))
    d_ts = parse_utc(e["d_utc"]).timestamp() if e.get("d_utc") else ""
    return (
        f'<tr{filter_attrs(e)}><td class="ast" data-s="{esc(e["tid"])}" title="{tip}">{esc(e["label"])} '
        f'<span class="badge kind">{esc(e["kind"] or "body")}</span></td>'
        f'<td data-s="{d_ts}" title="{esc(e.get("d_utc") or "outside the shadow: no contact")} UTC">'
        f'{esc(e["when"].strftime("%Y-%b-%d"))} {contact_text(e.get("d_utc"))}</td>'
        f'<td data-s="{e["when"].timestamp():.3f}" title="{esc(e["utc"])} UTC (closest approach to the observer)">'
        f'{esc(contact_text(e["utc"]))}</td>'
        f'<td title="{esc(e.get("r_utc") or "")} UTC">{contact_text(e.get("r_utc"))}</td>'
        f'<td class="num" data-s="{s(dur)}">{dur_txt}</td>'
        f'<td class="num mag" data-s="{s(e["mag"])}">{fmt(e["mag"])}{star_mark(e)}{twilight_mark(e)}</td>'
        f'{alt_cell(e, alt_tip)}'
        f'<td data-s="{s(moon["sep"], 1) if moon else ""}" title="{moon_tip}">{esc(moon_text(e))}</td>'
        f"{shadow_cell(e)}" + chance_cell(e) + f"{map_cell(e)}</tr>")


def html_row(e):
    size = f"D≈{2 * e['rad']:.1f} km" if e["rad"] is not None else ""
    tip_ast = esc(f"{e.get('full') or e['label']}" + (f" · {size}" + (f", {size_source_text(e['size_src'])}" if e['size_src'] else "") if size else ""))
    drop_tip = ""
    if e["m_ast"] is not None:
        before = f"{e['m_before']:.2f} → " if e["m_before"] is not None else ""
        drop_tip = esc(f"{before}{e['m_ast']:.2f} mag during the event (asteroid alone)")
    alt_tip = f"azimuth {e['az']:.0f}°" if e["az"] is not None else ""
    if e["airmass"] is not None:
        alt_tip += f" · airmass {e['airmass']:.2f}" + (f", extinction {e['ext']:.2f} mag" if e["ext"] else "")
    alt_tip = esc(alt_tip)
    mag_tip = esc(f"{e['margin_mag']:+.2f} mag below the observability limit" if e["margin_mag"] is not None
                  and e["margin_mag"] >= 0 else f"{-e['margin_mag']:.2f} mag fainter than the observability limit"
                  if e["margin_mag"] is not None else "")
    moon = e["moon"]
    moon_tip = esc(f"Moon {moon['alt']:.0f}° above horizon, {moon['illum']:.0f}% lit") if moon and moon["illum"] is not None else ""
    s = lambda v, nd=3: "" if v is None else f"{v:.{nd}f}"
    f = e.get("fav")
    if f:                                                        # favorites page: select box, site; no calc time
        site = (e.get("site") or {}).get("name", "?")
        lead = (f'<tr class="favrow" data-key="{esc(f["key"])}"{filter_attrs(e)}><td><input type="checkbox" class="favsel" '
                f'value="{esc(f["key"])}" aria-label="Select {esc(e["label"])}"></td>')
        mid = f'<td data-s="{esc(site)}">{esc(site)}</td>'
        calc = ""
        tail = (f'<td data-s="{esc(f["status"])}">{esc(f["status"])}</td>'
                f'<td data-s="{esc(f["note"])}" class="note c-narrow" title="{esc(f["note"])}">{esc(f["note"][:40])}'
                f'{"…" if len(f["note"]) > 40 else ""}</td>'
                f'<td class="c-narrow" data-s="{esc(f["added"])}" title="{esc(f["added"])} UTC">{esc(f["added"][5:16].replace("T", " "))}</td>')
    else:
        lead, mid, tail = f"<tr{filter_attrs(e)}>", "", ""
        calc = ""                                                # calculation time: in hits_log.csv only
    return (
        lead +
        f'<td class="ast" data-s="{esc(e["tid"])}" title="{tip_ast}">' + (
            f'{esc(e["label"])} <span class="badge kind">{esc(e["kind"] or "body")}</span>' if e.get("body") else
            f'<a href="{JPL_SBDB}{urllib.parse.quote(str(e["tid"]))}" target="_blank" rel="noopener">{esc(e["label"])}</a>')
        + binary_mark(e["tid"])
        + (f' <span class="sizeest" title="Size estimated from H with an assumed albedo: diameter, duration and shadow '
           f'width are uncertain by a factor of about 1.7 (no measured diameter in SBDB)">size est.</span>'
           if size_estimated(e) else '')
        + owc_line(e)
        + '</td>' + mid +
        f'<td data-s="{e["when"].timestamp():.3f}" title="{esc(e["utc"])} UTC (closest approach to the observer)"'
        + (f' class="evtime" data-utc="{(e["when"] + timedelta(milliseconds=500)).strftime("%Y-%m-%dT%H:%M:%SZ")}" '
           f'data-tz="{esc((e.get("site") or {}).get("tz") or "")}"' if f else "")
        + f'>{esc(fmt_time(e["when"]))}</td>'
        f'<td class="num mag" data-s="{s(e["mag"])}" title="{mag_tip}">'
        + (f'<a href="{esc(VIZIER_GAIA)}{urllib.parse.quote(str(e["star"]))}" target="_blank" rel="noopener" '
           f'title="{esc(e.get("star_name") or "Gaia DR3 " + str(e["star"]))}'
           f'{esc(" (" + e["star_tip"] + ")") if e.get("star_tip") else ""}: Gaia DR3 in VizieR. {mag_tip}">'
           f'{fmt(e["mag"])}</a>' if e.get("star") else fmt(e["mag"]))
        + star_mark(e) + twilight_mark(e) + '</td>'
        f'<td class="num" data-s="{s(e["drop"])}" title="{drop_tip}">{fmt(e["drop"])}{double_mark(e)}</td>'
        f'<td class="num" data-s="{s(e["dur"])}">{fmt(e["dur"])}</td>'
        f'{alt_cell(e, alt_tip)}'
        f'<td data-s="{s(moon["sep"], 1) if moon else ""}" title="{moon_tip}">{esc(moon_text(e))}</td>'
        f"{shadow_cell(e)}" + chance_cell(e) + calc + tail +
        f"{map_cell(e)}"
        "</tr>"
    )


def chance_text(e):
    """'62 %' (chance that the shadow covers the site), '<1 %', or '—' for events logged before it existed."""
    p = e.get("p_site")
    if p is None:
        return "\u2014"
    return "<1 %" if 0 < p < 0.005 else f"{100 * p:.0f} %"


def sigma_text(e):
    """The site's distance from the centre line in units of the path's 1-sigma, e.g. '0.4σ'; '' if not known."""
    if e.get("miss") is None or not e.get("sigma1"):
        return ""
    return f"{e['miss'] / e['sigma1']:.1f}\u03c3"


def chance_cell(e):
    tip = ""
    if e.get("p_site") is not None and e.get("sigma1") is not None:
        tip = (f"shadow distance {e['miss']:.1f} km, shadow radius {e['rad']:.1f} km, path uncertainty 1 sigma "
               f"{e['sigma1']:.1f} km ({e['sigma_src'] or '?'}): the site lies {sigma_text(e)} from the centre "
               f"line") if e.get("miss") is not None and e.get("rad") else ""
    p = e.get("p_site")
    txt = chance_text(e) + (f" \u00b7 {sigma_text(e)}" if sigma_text(e) and p is not None else "")
    return f'<td class="num" data-s="{"" if p is None else f"{p:.4f}"}" title="{esc(tip)}">{esc(txt)}</td>'


def chance_bar_svg(miss_km, rad_km, sigma1_km, p_site=None, width=520, height=64):
    """A bar across the path at the site: green the shadow (+- radius around the centre line), orange out to 1 sigma
    beyond its edges, black ticks at 3 sigma, and a marker where the site is (its distance in km and sigma). None
    when the values are missing. Standard SVG, for the favorites panel."""
    if miss_km is None or not rad_km or not sigma1_km:
        return None
    half = max(rad_km + 3.4 * sigma1_km, abs(miss_km) + rad_km) * 1.08
    x = lambda km: width / 2 + km / half * (width / 2 - 10)
    y0, h = 20, 18
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
         f'font-family="sans-serif" font-size="11">',
         f'<rect x="{x(-half):.1f}" y="{y0}" width="{x(half) - x(-half):.1f}" height="{h}" fill="#e5e7eb"/>',
         f'<rect x="{x(-rad_km - sigma1_km):.1f}" y="{y0}" width="{x(rad_km + sigma1_km) - x(-rad_km - sigma1_km):.1f}" '
         f'height="{h}" fill="#f59e0b"/>',
         f'<rect x="{x(-rad_km):.1f}" y="{y0}" width="{x(rad_km) - x(-rad_km):.1f}" height="{h}" fill="#16a34a"/>']
    for k in (-1, 1):
        xs = x(k * (rad_km + 3 * sigma1_km))
        o.append(f'<line x1="{xs:.1f}" y1="{y0 - 4}" x2="{xs:.1f}" y2="{y0 + h + 4}" stroke="#111" stroke-width="2.5"/>')
        o.append(f'<text x="{xs + 4:.1f}" y="{y0 - 6}" text-anchor="start" fill="#111">3\u03c3</text>' if k < 0 else
                 f'<text x="{xs - 4:.1f}" y="{y0 - 6}" text-anchor="end" fill="#111">3\u03c3</text>')
    o.append(f'<line x1="{x(0):.1f}" y1="{y0}" x2="{x(0):.1f}" y2="{y0 + h}" stroke="#14532d" stroke-width="1"/>')
    xm = x(abs(miss_km))
    sig = abs(miss_km) / sigma1_km
    o.append(f'<polygon points="{xm:.1f},{y0 - 1} {xm - 6:.1f},{y0 - 11} {xm + 6:.1f},{y0 - 11}" fill="#1d4ed8"/>')
    o.append(f'<line x1="{xm:.1f}" y1="{y0}" x2="{xm:.1f}" y2="{y0 + h}" stroke="#1d4ed8" stroke-width="2.5"/>')
    lab = f"site: {abs(miss_km):.1f} km = {sig:.1f}\u03c3" + (f", {100 * p_site:.0f} %" if p_site is not None else "")
    anchor = "end" if xm > width * 0.6 else "start"
    o.append(f'<text x="{xm + (-8 if anchor == "end" else 8):.1f}" y="{y0 - 4}" text-anchor="{anchor}" fill="#1d4ed8">'
             f'{esc(lab)}</text>')
    o.append(f'<text x="{x(0):.1f}" y="{y0 + h + 15}" text-anchor="middle" fill="#14532d">shadow '
             f'{2 * rad_km:.1f} km</text>')
    o.append(f'<text x="{x(-half):.1f}" y="{y0 + h + 15}" text-anchor="start" fill="#b45309">'
             f'1\u03c3 = {sigma1_km:.1f} km</text>')
    o.append("</svg>")
    return "".join(o)


def info_html(info):
    if not info:
        return ""
    return '<dl class="info">' + "".join(f"<dt>{esc(k)}</dt><dd>{esc(v)}</dd>" for k, v in info) + "</dl>"


# ------------------------------------------------------------------------------------------- the filter bar
# Every row carries its values as data-f* attributes (filter_attrs); the bar hides the rows that do not pass and
# counts the rest. Named filter sets are shared by all report pages (Results, Favorites, Planets & Moons): kept by the
# GUI (/api/filters, gui_state.json) when it serves the page, else in the browser (localStorage). The current filter
# of each page is remembered in the browser and applied again when the page loads.
FILTER_FLAGS = (("sup", "⚑ supplement star"), ("unc", "uncertain star"), ("dbl", "⚠ close/double star"),
                ("twi", "☼ twilight"), ("hz", "⛰ horizon"), ("est", "size est."))


def event_key(target_id, utc):
    """An event's key in the pages and exports: 'target|YYYY-MM-DDTHH:MM:SS' (the CSV downloads keep the rows the
    page shows, exports.only_shown)."""
    return f"{str(target_id).strip()}|{str(utc).strip()[:19]}"


def filter_attrs(e):
    """The row's filter values: event time (Unix s, UTC), star mag, duration (s), drop, star and Sun altitude, RUWE,
    chance (%), flags."""
    from pysyzygos import binaries
    flags = [k for k, ok in (
        ("sup", bool(e.get("sflag"))), ("unc", bool(star_uncertain(e) or star_noted(e))), ("dbl", bool(e.get("dhint"))),
        ("twi", bool(twilight_text(e.get("sun")))), ("hz", (e.get("hz") or ("",))[0] in ("behind", "near")),
        ("est", not e.get("body") and size_estimated(e)),
        ("moon", not e.get("body") and bool(binaries.short(e["tid"])))) if ok]
    v = lambda x, nd=3: "" if x is None else f"{x:.{nd}f}"
    dur = e.get("contact_dur") if e.get("body") and e.get("contact_dur") else e.get("dur")
    chance = None if e.get("p_site") is None else 100.0 * e["p_site"]
    t = e["when"].timestamp() if e.get("when") is not None else None
    return (f' data-ev="{esc(event_key(e["tid"], e["utc"]))}" data-ftime="{v(t, 0)}"'
            f' data-fmag="{v(e.get("mag"))}" data-fdur="{v(dur)}" data-fdrop="{v(e.get("drop"))}"'
            f' data-falt="{v(e.get("alt"), 1)}" data-fsun="{v(e.get("sun"), 1)}" data-fruwe="{v(e.get("ruwe"), 2)}"'
            f' data-fchance="{v(chance, 2)}" data-fflags="{" ".join(flags)}" data-faz="{v(e.get("az"), 1)}"'
            + (f' data-fsite="{esc((e.get("site") or {}).get("name") or "")}"' if e.get("site") else ""))


def horizon_js(events, meta):
    """The horizons of the page's sites (the run's site; on the favorites page each row's) for the filter's
    'clear of horizon': window.PYO_HZ = {site: [[az, alt], ...]}, window.PYO_HZSITE = the page's site."""
    names = {meta.get("site_name") or ""} | {(e.get("site") or {}).get("name") or "" for e in events}
    try:
        from pysyzygos import db
        hz = {n: p for n, p in db._horizons().items() if n in names}
    except Exception:
        hz = {}
    data = json.dumps(hz).replace("</", "<\\/")
    return (f"<script>window.PYO_HZ={data};window.PYO_HZSITE={json.dumps(meta.get('site_name') or '')};</script>")


def filter_bar():
    num = lambda key, label, unit, step, tip: (
        f'<label title="{esc(tip)}">{label} <input type="number" step="{step}" data-f="{key}">{unit}</label>')
    hide = "".join(f'<label><input type="checkbox" data-h="{k}">{esc(t)}</label>' for k, t in FILTER_FLAGS)
    when = lambda key, label, tip: (f'<label title="{esc(tip)}">{label} <input type="datetime-local" data-t="{key}">'
                                    f'</label>')
    return ('<details class="fbar" id="fbar"><summary>Filter <span id="fcount"></span></summary><div class="frow">'
            + when("from", "from (UTC)", "first event time, UTC (the table's times)")
            + when("to", "to", "last event time, UTC (this minute included)")
            + '</div><div class="frow">'
            + num("mag", "G ≤", "", "0.1", "faintest star (Gaia G)")
            + num("dur", "duration ≥", " s", "0.1", "shortest event")
            + num("drop", "drop ≥", " mag", "0.05", "smallest magnitude drop")
            + num("alt", "star alt ≥", "°", "1", "lowest star altitude")
            + num("sun", "Sun ≤", "°", "1", "highest Sun altitude (e.g. -12: no twilight)")
            + num("ruwe", "RUWE ≤", "", "0.1", "Gaia RUWE (stars without a value pass)")
            + num("chance", "chance ≥", " %", "1", "chance that the shadow covers the site")
            + num("hzc", "clear of horizon ≥", "°", "1", "star at least this high above your site's horizon "
                  "(sites.py horizon); sites without a horizon pass")
            + '</div><div class="frow"><span class="flab">hide:</span>' + hide
            + '<span class="flab">only:</span><label><input type="checkbox" data-o="moon">+moon</label></div>'
            '<div class="frow"><select id="fset" aria-label="Saved filter sets"></select>'
            '<button class="mapbtn" id="fsave" type="button">Save as…</button>'
            '<button class="mapbtn" id="fdel" type="button">Delete</button>'
            '<button class="mapbtn" id="fclear" type="button">Clear</button>'
            '<span class="fnote">empty fields and unknown values pass; saved sets are shared by Results and '
            'Favorites</span></div></details>')


FILTER_CSS = """
.sqlnote{margin:0 0 8px;padding:4px 10px;border-left:3px solid var(--accent);background:var(--card);font-size:.9rem}
.fbar{margin:0 0 10px;border:1px solid var(--line);border-radius:8px;padding:6px 10px;background:var(--card)}
.fbar summary{cursor:pointer;font-weight:600}.fbar.factive summary{color:var(--accent)}
.frow{display:flex;flex-wrap:wrap;gap:6px 14px;align-items:center;margin:6px 0}
.frow label{white-space:nowrap;font-size:.9rem}.frow input[type=number]{width:5.2em;margin-left:4px}
.frow input[type=datetime-local]{margin-left:4px;font:inherit;font-size:.85rem}
.flab{color:var(--muted);font-size:.85rem}.fnote{color:var(--muted);font-size:.8rem}#fcount{font-weight:normal}
.fbar button{font:inherit;font-size:.85rem;padding:2px 10px;border:1px solid var(--line);border-radius:6px;
 background:var(--head);color:var(--ink);cursor:pointer}.fbar button:hover{border-color:var(--accent);color:var(--accent)}
.fbar select{font:inherit;font-size:.85rem}
"""

FILTER_JS = """<script>
(function(){var bar=document.getElementById('fbar');if(!bar)return;
var rows=[].slice.call(document.querySelectorAll('table tbody tr')),sel=document.getElementById('fset');
var PK='pyo_filter:'+location.pathname,SK='pyo_filter_sets',served=location.protocol!=='file:',sets={};
var LIM={mag:-1,dur:1,drop:1,alt:1,sun:-1,ruwe:-1,chance:1};
function tsec(v,end){var t=Date.parse(v+'Z');return isNaN(t)?NaN:t/1000+(end?59.999:0);}
function spec(){var s={},h=[],o=[];
 bar.querySelectorAll('input[data-t]').forEach(function(i){if(i.value&&!isNaN(tsec(i.value)))s[i.dataset.t]=i.value;});
 bar.querySelectorAll('input[data-f]').forEach(function(i){if(i.value!==''&&!isNaN(parseFloat(i.value)))s[i.dataset.f]=parseFloat(i.value);});
 bar.querySelectorAll('input[data-h]').forEach(function(i){if(i.checked)h.push(i.dataset.h);});
 bar.querySelectorAll('input[data-o]').forEach(function(i){if(i.checked)o.push(i.dataset.o);});
 if(h.length)s.hide=h;if(o.length)s.only=o;return s;}
function setForm(s){s=s||{};
 bar.querySelectorAll('input[data-t]').forEach(function(i){i.value=s[i.dataset.t]||'';});
 bar.querySelectorAll('input[data-f]').forEach(function(i){i.value=(s[i.dataset.f]!==undefined)?s[i.dataset.f]:'';});
 bar.querySelectorAll('input[data-h]').forEach(function(i){i.checked=(s.hide||[]).indexOf(i.dataset.h)>=0;});
 bar.querySelectorAll('input[data-o]').forEach(function(i){i.checked=(s.only||[]).indexOf(i.dataset.o)>=0;});}
var HZ=window.PYO_HZ||{},HZ0=window.PYO_HZSITE||'';
function hzAlt(site,az){var p=HZ[site];if(!p||!p.length)return null;az=((az%360)+360)%360;var b=null;   // horizon.altitude
 for(var i=0;i+1<p.length;i++){var a0=p[i][0],h0=p[i][1],a1=p[i+1][0],h1=p[i+1][1];
  if(a0<=az&&az<=a1){var h=(a1===a0)?Math.max(h0,h1):h0+(h1-h0)*(az-a0)/(a1-a0);b=(b===null)?h:Math.max(b,h);}}
 return b===null?0:b;}
function pass(r,s){var tm=parseFloat(r.dataset.ftime);
 if(s.hzc!==undefined){var az=parseFloat(r.dataset.faz),al=parseFloat(r.dataset.falt),h=hzAlt(r.dataset.fsite||HZ0,az);
  if(h!==null&&!isNaN(az)&&!isNaN(al)&&al-h<s.hzc)return false;}
 if(!isNaN(tm)){if(s.from&&tm<tsec(s.from))return false;if(s.to&&tm>tsec(s.to,true))return false;}
 for(var k in LIM){if(s[k]===undefined)continue;var v=r.dataset['f'+k];if(v===undefined||v==='')continue;
  v=parseFloat(v);if(LIM[k]<0?v>s[k]:v<s[k])return false;}
 var fl=(r.dataset.fflags||'').split(' ');
 for(var i=0;i<(s.hide||[]).length;i++)if(fl.indexOf(s.hide[i])>=0)return false;
 for(var j=0;j<(s.only||[]).length;j++)if(fl.indexOf(s.only[j])<0)return false;return true;}
function apply(){var s=spec(),n=0,act=Object.keys(s).length>0;
 rows.forEach(function(r){var ok=pass(r,s);r.style.display=ok?'':'none';if(ok)n++;});
 document.getElementById('fcount').textContent=act?('\\u00b7 showing '+n+' of '+rows.length):'';
 bar.classList.toggle('factive',act);
 try{localStorage.setItem(PK,JSON.stringify({spec:s,name:sel.value}));}catch(e){}
 document.dispatchEvent(new Event('pyofilter'));}
function fill(cur){while(sel.firstChild)sel.removeChild(sel.firstChild);
 var o=document.createElement('option');o.value='';o.textContent='\\u2014 saved filters \\u2014';sel.appendChild(o);
 Object.keys(sets).sort().forEach(function(n){var p=document.createElement('option');p.value=n;p.textContent=n;sel.appendChild(p);});
 sel.value=(cur&&sets[cur])?cur:'';}
function local(){try{sets=JSON.parse(localStorage.getItem(SK)||'{}')||{};}catch(e){sets={};}}
function keepLocal(){try{localStorage.setItem(SK,JSON.stringify(sets));}catch(e){}}
function load(done){if(!served){local();done();return;}
 fetch('/api/filters').then(function(r){return r.json();}).then(function(j){sets=j.sets||{};done();})
 .catch(function(){local();done();});}
function store(url){if(!served){keepLocal();return;}
 fetch(url).then(function(r){return r.json();}).then(function(j){if(!j.ok)pyoToast(j.msg,true);})
 .catch(function(){keepLocal();});}
bar.querySelectorAll('input').forEach(function(i){i.addEventListener('input',function(){sel.value='';apply();});
 i.addEventListener('change',function(){sel.value='';apply();});});
sel.addEventListener('change',function(){if(sel.value&&sets[sel.value])setForm(sets[sel.value]);apply();});
document.getElementById('fclear').addEventListener('click',function(){setForm({});sel.value='';apply();});
document.getElementById('fsave').addEventListener('click',function(){var s=spec();
 if(!Object.keys(s).length){pyoToast('Set a filter first');return;}
 var n=(prompt('Name of this filter set (shared by Results and Favorites):',sel.value||'')||'').trim();if(!n)return;
 sets[n]=s;fill(n);store('/api/filters/save?'+new URLSearchParams({name:n,spec:JSON.stringify(s)}));apply();
 pyoToast('Filter set \\u201c'+n+'\\u201d saved');});
document.getElementById('fdel').addEventListener('click',function(){var n=sel.value;
 if(!n){pyoToast('Choose a saved filter set first');return;}if(!confirm('Delete the filter set \\u201c'+n+'\\u201d?'))return;
 delete sets[n];fill('');store('/api/filters/delete?'+new URLSearchParams({name:n}));apply();});
var last={};try{last=JSON.parse(localStorage.getItem(PK)||'{}')||{};}catch(e){}
setForm(last.spec);apply();if(last.spec&&Object.keys(last.spec).length)bar.open=true;
load(function(){fill(last.name);});})();
</script>"""


def to_html(events, meta):
    on = lambda key: ' sorted-asc' if meta.get("sort", "date") == key else ""
    fav = meta.get("favorites")
    head = (('<th><input type="checkbox" id="favall" aria-label="Select all"></th><th data-k>Asteroid</th>'
             '<th data-k title="Site the event was predicted for">Site</th>') if fav else '<th data-k>Asteroid</th>') + (
            f'<th class="{on("date").strip()}" data-k id="evtimehead">Event time (UT)</th>'
            f'<th class="num{on("mag")}" data-k title="Gaia G magnitude of the star">Star mag</th>'
            '<th class="num" data-k title="Magnitude drop with the star fully covered">Mag drop</th>'
            '<th class="num" data-k title="Maximum duration (centre line), seconds">Max dur (s)</th>'
            '<th data-k title="Star altitude and compass direction at closest approach">Altitude' + AZ_SWITCH + '</th>'
            '<th data-k title="Moon distance from the star; shown while the Moon is up">Moon dist</th>'
            '<th class="num" data-k title="Distance of the observer from the shadow centre line">Shadow dist</th>'
            '<th class="num" data-k title="Chance that the shadow covers your site, from the shadow distance, the shadow '
            'radius and the 1-sigma path uncertainty">Chance</th>'
            + ('<th data-k>Status</th><th data-k class="c-narrow">Note</th><th data-k class="c-narrow">Added (UT)</th>'
               if fav else "")
            + '<th title="☆ favorites and KStars (when opened from the GUI), Map: shadow path, Preview: star field, '
            'KML: ground track for Google Earth">Tools</th>')
    if meta.get("layout") == "bodies":                           # planets & moons: contact times
        head = ('<th data-k>Body</th>'
                f'<th class="{on("date").strip()}" data-k title="Date and disappearance (D) at the site, UT">D (UT)</th>'
                '<th data-k title="Closest approach of the star to the centre, UT">Closest (UT)</th>'
                '<th data-k title="Reappearance (R) at the site, UT">R (UT)</th>'
                '<th class="num" data-k title="From D to R at the site">Duration</th>'
                f'<th class="num{on("mag")}" data-k title="Gaia G magnitude of the star">Star mag</th>'
                '<th data-k title="Star altitude and compass direction at closest approach">Altitude' + AZ_SWITCH + '</th>'
                '<th data-k title="Moon distance from the star; shown while the Moon is up">Moon dist</th>'
                '<th class="num" data-k title="Distance of the observer from the shadow centre line">Shadow dist</th>'
                '<th class="num" data-k title="Chance that the shadow covers your site">Chance</th>'
                '<th>Tools</th>')
        body = "".join(html_row_body(e) for e in events)
    else:
        body = "".join(html_row(e) for e in events)
    table = (filter_bar() + f'<div class="wrap"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'
             if events else '<div class="wrap"><div class="empty">No events match.</div></div>')
    if fav:
        opts = "".join(f"<option>{esc(x)}</option>" for x in meta.get("statuses", ()))
        table = (f'<div class="favbar"><span id="favcount">0 selected</span>'
                 f'<label>status <select id="favstatus">{opts}</select></label>'
                 f'<button class="mapbtn" id="favsetst" type="button">Set status</button>'
                 f'<button class="mapbtn" id="favdel" type="button">Remove selected</button>'
                 f'<button class="mapbtn" id="favpast" type="button" title="Remove every favorite whose event is '
                 f'before today (UTC)">Remove past events</button>'
                 f'<label title="Event times in UT, in this computer\'s time zone (Local), or in the time zone of each '
                 f'event\'s site (Site; looked up once per site), with daylight saving time">times '
                 f'<select id="favtime"><option value="ut">UT</option><option value="local">Local</option>'
                 f'<option value="site">Site</option></select></label>' +
                 f'</div>' + table)
    n_kml = sum(1 for e in events if e["kml"])
    n_prev = sum(1 for e in events if e.get("preview"))
    paths = meta.get("paths") or {}
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(meta['title'])}</title><style>{CSS}{FILTER_CSS}{MAP_CSS if paths or n_prev else ''}</style>{LEAFLET_TAGS if paths else ''}</head>
<body><main>
<h1>{esc(meta['title'])}</h1>
<p class="sub">{len(events)} events{esc(meta['span'])} · {esc(meta['observer'])} · times in UT · generated {esc(meta['generated'])} · {n_kml} map file{'s' if n_kml != 1 else ''}</p>
{info_html(meta.get("info"))}{f'<p class="sqlnote">{esc(meta["sql"])}</p>' if meta.get("sql") else ''}
{table}
<ul class="notes">
<li>Star magnitude is Gaia G. The drop assumes the star is fully covered and ignores the star's angular size and diffraction, so bright stars and very small bodies can show a smaller real drop.</li>
<li><b>+moon</b> after an asteroid: it has known satellites (W. R. Johnston's compilation, NASA PDS 2019; "+moon?": only reported in an occultation, not confirmed); hover for their sizes and distances. A satellite casts its own shadow, somewhere within the dotted "satellite zone" lines on the map (its distance from the asteroid plus its radius): observers outside the main path may see a short extra event. Newer discoveries: Johnston's Archive (johnstonsarchive.net).</li>
<li><b>\u26a0</b> after a drop: a close or double star. The number is the drop with the light of neighbours within a few arcseconds, which stays in the camera image when the star is covered; hover for details (neighbours from the local catalog; with the online check also Gaia's double-star hints and neighbours the catalog leaves out).</li>
<li><span class="sizeest">size est.</span> after an asteroid: no measured diameter; its size is estimated from H with an assumed albedo, so diameter, duration and shadow width are uncertain by a factor of about 1.7 (typical for small asteroids, H above ~15).</li>
<li>Chance: the probability that the shadow covers your site, from the shadow distance, the shadow radius and the path uncertainty (1 sigma: JPL Horizons' 3-sigma position uncertainty / 3, else the default). It assumes the size is right; an uncertain size ("size est." after the asteroid) or a far-future event (large uncertainty) makes it a rough guide. Check again as the date approaches: the orbit, and with it the chance, improves.</li>
<li>Shadow dist is the observer's distance from the shadow centre line in the fundamental plane. "Inside" means within the shadow radius; otherwise it is the gap to the shadow edge. Radius comes from the size lookup (hover the asteroid name).</li>
<li>Altitude is the star's altitude at closest approach. The Moon is shown only while above the horizon. Click a column heading to sort.</li>
<li>Map shows the path on an interactive map (needs internet for the map tiles) and links the closest centre-line point in Google Maps. Google Maps itself cannot load a local KML file: use the KML link with Google Earth, or import it in My Maps (Create a new map, then Import).</li>
</ul>
</main>{DIALOG if paths else ''}<script>{JS}</script>{map_script(paths, meta) if paths else ''}{PREVIEW_DIALOG if n_prev else ''}{TOAST_JS}{horizon_js(events, meta)}{FILTER_JS}{AZ_JS}{FAVPAGE_JS if fav else FAV_JS}{KSTARS_JS.replace("__SITE__", json.dumps(meta.get("site")))}</body></html>
"""


# ---------------------------------------------------------------- Markdown

def to_markdown(events, meta):
    out = [f"# {meta['title']}", "",
           f"{len(events)} events{meta['span']} · {meta['observer']} · times in UT · generated {meta['generated']}", ""]
    out += [f"- **{k}:** {v}" for k, v in (meta.get("info") or [])] + ([""] if meta.get("info") else [])
    out += ["| Asteroid | Event time (UT) | Star mag (G) | Mag drop | Max dur (s) | Altitude | Moon dist | Shadow dist | Chance | Calc (s) | Files |",
            "|---|---|---:|---:|---:|---|---|---:|---:|---:|---|"]
    for e in events:
        if e["miss"] is None:
            off = "—"
        elif e["margin"] is not None and e["margin"] <= 0:
            off = f"inside ({e['miss']:.1f} km)"
        else:
            off = f"{e['miss']:.1f} km" + (f" ({e['margin']:.1f} outside)" if e["margin"] is not None else "")
        kml = " ".join(x for x in (f"[KML]({e['kml']})" if e["kml"] else "", f"[Preview]({e['preview']})"
                                   if e.get("preview") else "") if x) or "—"
        from pysyzygos import binaries
        star = " \\*" if size_estimated(e) else ""                      # size from H only (footnote)
        star += f" {binaries.short(e['tid'])}" if binaries.short(e["tid"]) else ""   # known satellites
        dbl = (" \u26a0" + (f" {e['drop_blend']:.2f}" if e.get("drop_blend") is not None else "")) if e.get("dhint") else ""
        sf = (f" \u26a0 star \u00b1{star_uncertain(e):.0f} km ({e['sflag']})" if star_uncertain(e)
              else f" \u2691 {e['sflag']}" if e.get("sflag") else "")
        sf += f" {twilight_text(e.get('sun'))}" if twilight_text(e.get("sun")) else ""
        out.append(f"| {e['label']}{star} | {fmt_time(e['when'])} | {fmt(e['mag'])}{sf} | {fmt(e['drop'])}{dbl} | {fmt(e['dur'])} "
                   f"| {alt_text(e)} | {moon_text(e)} | {off} | {chance_text(e)} | {fmt(e['calc'])} | {kml} |")
    if any(size_estimated(e) for e in events):
        out.append("\n\\* size estimated from H with an assumed albedo (no measured diameter): diameter, duration and "
                   "shadow width uncertain by a factor of about 1.7.")
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- main

def load_config_observer(csv_path):
    try:
        from pysyzygos import config as cfg
        return getattr(cfg, "LAT", None), getattr(cfg, "LON", None), getattr(cfg, "map_dir", None)
    except (ImportError, SystemExit, OSError):           # no usable configuration: no observer position
        return None, None, None


def main(argv=None):
    ap = argparse.ArgumentParser(description="Turn PySyzygos hits_log.csv into an HTML or Markdown event list.")
    ap.add_argument("--version", action="version", version=f"PySyzygos {__version__}")
    ap.add_argument("csv", help="hits_log.csv written by PySyzygos")
    ap.add_argument("-o", "--output", help="output file (default: hits_report.html / .md next to the CSV)")
    ap.add_argument("--format", choices=("html", "md"), help="default: from the output extension, else html")
    ap.add_argument("--kml-dir", help="folder with the KML files (default: map_dir from pysyzygos_config, else ./maps)")
    ap.add_argument("--lat", type=float, help="observer latitude, deg north (for the compass direction)")
    ap.add_argument("--lon", type=float, help="observer longitude, deg east (negative = west)")
    ap.add_argument("--max-miss", type=float, help="only events whose centre-line distance is below this (km)")
    ap.add_argument("--min-drop", type=float, help="only events with at least this magnitude drop")
    ap.add_argument("--sort", choices=("mag", "date"), default="mag",
                    help="row order: mag = brightest star first (default), date = by event time")
    ap.add_argument("--title", help="page title (default: by layout)")
    ap.add_argument("--layout", choices=["auto", "asteroids", "bodies"], default="auto",
                    help="table layout: asteroids, or planets & moons with contact times (auto: bodies if all are)")
    ap.add_argument("--no-embed", action="store_true", help="do not embed the KML paths and map viewer in the HTML page")
    ap.add_argument("--where", help="only events matching this SQL condition on the results database's view hits, e.g. "
                                    "\"mag < 11 AND chance > 30\" (columns: pysyzygos.db HITS; GUI Results: SQL filter)")
    ap.add_argument("--db", help="results database for --where (default: config results_db next to the CSV)")
    ap.add_argument("--list", default="main", help="results list for --where: main (default) or bodies")
    ap.add_argument("--tile-url", default=U.URL_OSM_TILES,
                    help="tile URL template for the embedded map (default: OpenStreetMap, fine for light personal use)")
    a = ap.parse_args(argv)

    cfg_lat, cfg_lon, cfg_maps = load_config_observer(a.csv)
    lat = a.lat if a.lat is not None else cfg_lat
    lon = a.lon if a.lon is not None else cfg_lon
    fmt_name = a.format or ("md" if (a.output or "").lower().endswith(".md") else "html")
    out = a.output or os.path.join(os.path.dirname(os.path.abspath(a.csv)), "hits_report." + fmt_name)
    out_dir = os.path.dirname(os.path.abspath(out))
    kml_dir = a.kml_dir or cfg_maps or "maps"
    if lat is None or lon is None:
        print("note: no observer position (pysyzygos_config.py or --lat/--lon): compass directions omitted", file=sys.stderr)

    if os.path.isfile(a.csv):
        rows, skipped = read_log(a.csv)
    elif os.path.isfile(os.path.splitext(a.csv)[0] + ".runs.jsonl"):
        rows, skipped = [], 0                     # the last run found no events: report it (header with the run's site)
        print(f"note: {a.csv} does not exist: the last run logged no events", file=sys.stderr)
    else:
        sys.exit(f"{a.csv} not found")
    events, bad = [], 0
    for r in rows:
        try:
            events.append(build_event(r, lat, lon, kml_dir, out_dir))
        except (KeyError, ValueError) as ex:
            bad += 1
            print(f"skipping unreadable row ({ex!r}): {r.get('target_id', '?')} {r.get('best_utc', '?')}", file=sys.stderr)
    events = dedupe(events)
    n_all, sql_note = len(events), ""
    if a.where:                                          # only the events the condition selects (read-only query)
        from pysyzygos import db
        path = a.db
        if not path:
            try:
                from pysyzygos import config as cfg
                path = getattr(cfg, "results_db", db.DEFAULT)
            except Exception:
                path = db.DEFAULT
            path = path if os.path.isabs(path) else os.path.join(os.path.dirname(os.path.abspath(a.csv)), path)
        try:
            keys = {(t.strip(), u[:19]) for t, u in db.where_keys(path, a.where, a.list)}
        except ValueError as ex:
            sys.exit(f"SQL filter not usable: {ex}")
        events = [e for e in events if (e["tid"], e["utc"][:19]) in keys]
        sql_note = f"SQL filter: {a.where} ({len(events)} of {n_all} events)"
        print(sql_note)
    if a.max_miss is not None:
        events = [e for e in events if e["miss"] is not None and e["miss"] <= a.max_miss]
    if a.min_drop is not None:
        events = [e for e in events if e["drop"] is not None and e["drop"] >= a.min_drop]
    if a.sort == "mag":                                  # brightest first, unknown magnitudes last, ties by time
        events.sort(key=lambda e: (e["mag"] is None, e["mag"] if e["mag"] is not None else 0.0, e["when"]))
    else:
        events.sort(key=lambda e: e["when"])

    paths = {}
    if fmt_name == "html" and not a.no_embed:
        for e in events:
            if e["kml_abs"]:
                key = os.path.splitext(os.path.basename(e["kml_abs"]))[0]
                try:
                    paths[key] = kml_to_data(e["kml_abs"])
                    e["pkey"] = key
                except (ET.ParseError, ValueError, OSError) as ex:
                    print(f"could not read {e['kml_abs']} for the map ({ex}); the KML link is kept", file=sys.stderr)

    span = ""
    if events:
        span = f" from {min(e['when'] for e in events):%Y-%m-%d} to {max(e['when'] for e in events):%Y-%m-%d}"
    observer = f"observer {abs(lat):.4f}°{'N' if lat >= 0 else 'S'} {abs(lon):.4f}°{'E' if lon >= 0 else 'W'}" \
        if lat is not None and lon is not None else "observer position not set"
    run = read_last_run(a.csv)
    if run and run.get("site"):                                  # the run's site wins over the current config
        lat, lon = run["site"]["lat"], run["site"]["lon"]
        observer = f"site {run['site']['name']}"
    layout = a.layout if a.layout != "auto" else ("bodies" if events and all(e.get("body") for e in events)
                                                     else "asteroids")
    a.title = a.title or ("PySyzygos planet and moon occultations" if layout == "bodies"
                          else "PySyzygos asteroid occultation events")
    meta = dict(title=a.title, layout=layout, span=span, sort=a.sort, sql=sql_note, info=header_info(run, lat, lon), observer=observer, generated=datetime.now().strftime("%Y-%m-%d %H:%M"),
                paths=paths, tiles=a.tile_url, obs=[lat, lon] if lat is not None and lon is not None else None,
                site_name=((run or {}).get("site") or {}).get("name", ""),
                site=dict(lat=lat, lon=lon, ele=(run or {}).get("site", {}).get("ele", 0.0))
                if lat is not None and lon is not None else None)
    text = to_markdown(events, meta) if fmt_name == "md" else to_html(events, meta)
    with open(out, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"{len(events)} events -> {out}" + (f"  ({skipped + bad} unreadable rows skipped)" if skipped + bad else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
