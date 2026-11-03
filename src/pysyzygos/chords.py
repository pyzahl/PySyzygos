"""chords.py - the chords of one occultation in the fundamental plane, an ellipse fitted to them, and the profile
plot (SVG), for the Observation Manager.

    pysyzygos chords archive "<target>|<YYYY-MM-DDTHH:MM:SS>"     an event of the Occult archive (observed.py)
    pysyzygos chords reports <report.json> [...]                  our saved reports of one event (all its stations)
    pysyzygos chords fit <chords.json> [--mode auto|ellipse|circle|fixed] [--misses] [--exclude 3,5] [--svg out]

Each station's D and R become points in the fundamental plane: the station's position relative to the asteroid's
predicted center at that time (the asteroid from JPL Horizons as the station sees it, light time from the station;
the star as the search takes it), on axes of date (y toward the true pole of date, x east; as Occult's archive and
plots). A positive station draws a chord from D to R along its track; a miss draws its whole track. With the
predicted asteroid at the origin, the fitted ellipse's center is the observed minus predicted position.

`build` (SPICE, JPL Horizons: a process of its own, as the GUI runs it) writes observations/chords/<event>/chords.json;
`fit` and `svg` need neither (numpy, scipy): the GUI refits and redraws at once when chords are switched off or the
fit's shape is changed. The archive's own fit (Occult) is drawn for comparison.
"""
import argparse, glob, json, math, os, re, sys, tempfile
from datetime import datetime, timedelta, timezone

import numpy as np

from pysyzygos.version import __version__

DIR = os.path.join("observations", "chords")      # in the data folder: <event slug>/chords.json, profile.svg
FORMAT = 2                                        # chords.json layout; older files are computed again (2: chords
                                                  # of satellites and 2nd stars, 'body')
GROUP_TOL_S = 600.0                               # reports of one event: same asteroid, times within 10 min
RESULTS = {"POSITIVE": "positive", "NEGATIVE": "miss", "CLOUDED OUT": "clouded"}
DATUM_WGS84 = ("_", "", "*", "WGS84", "unspecified")   # heights + EGM96 geoid (alt_m above sea level)
MODES = ("auto", "ellipse", "circle", "fixed")
# Occult's event codes (D / R): the main body on the main star, a satellite on the main star, the main body on the
# 2nd star of a double, a satellite on the 2nd star; each pair is a chord of its own
BODIES = (("D", "R", "main"), ("G", "B", "satellite"), ("d", "r", "2nd star"), ("g", "b", "satellite, 2nd star"))


def slug(text):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", str(text)).strip("._") or "event"


# ------------------------------------------------------------------------------------------- the stations
def stations_archive(key):
    """(event, stations) of an Occult archive event ('target|YYYY-MM-DDTHH:MM:SS'): per observer site in the archive's
    order one entry per chord (BODIES: main body, satellite, 2nd star; a site can have several), with D and R,
    accuracies, personal equations and Occult's 'excluded' flag; misses and clouded sites without times."""
    from pysyzygos import observed
    rec, cts = observed.find(key)
    if rec is None:
        raise SystemExit(f"{key}: not in the observations database (Occult data add-on)")
    same = lambda a, b: a is not None and b is not None and abs(float(a) - float(b)) < 1e-6
    st = []
    for s in rec.get("obs_sites") or []:
        if s.get("lat") is None or s.get("lon") is None:
            continue
        base = dict(observer=s.get("observer", ""), place=s.get("place", ""), lat=s["lat"], lon=s["lon"],
                    alt_m=s.get("alt_m") or 0.0, datum=s.get("datum", "_"), method=s.get("method", ""),
                    result=s.get("result", ""), include=True, note="", body="main")
        mine = [(lab, u, d) for lab, u, d in cts if d.get("observer") == base["observer"]
                and same(d.get("lat"), base["lat"]) and same(d.get("lon"), base["lon"])]
        pairs = []
        for cd, cr, body in BODIES:                    # several of one kind at a site: paired in time order
            ds = sorted(((u, d) for lab, u, d in mine if lab == cd), key=lambda q: q[0])
            rs = sorted(((u, d) for lab, u, d in mine if lab == cr), key=lambda q: q[0])
            pairs += [(body, ud, dd, ur, dr) for (ud, dd), (ur, dr) in zip(ds, rs)]
        if not pairs:
            x = dict(base, n=len(st) + 1)
            if x["result"] == "positive":
                x["result"] = "positive (no times)"
            elif x["result"] not in ("miss", "clouded"):
                x.update(result="other", note=f"Occult code {x['result']}: not a chord")
            st.append(x)
            continue
        for body, ud, dd, ur, dr in sorted(pairs, key=lambda q: q[1]):
            x = dict(base, n=len(st) + 1, body=body, result="positive", d_utc=ud, r_utc=ur, d_acc=dd.get("acc_s"),
                     r_acc=dr.get("acc_s"), d_pe=dd.get("pe_s") or 0.0, r_pe=dr.get("pe_s") or 0.0)
            if "x" in ((dd.get("include") or "_"), (dr.get("include") or "_")):
                x.update(include=False, note="excluded in Occult's fit")
            if body != "main":
                x["note"] = "; ".join(v for v in (x["note"], f"{body} chord") if v)
            st.append(x)
    star_ok = rec.get("star_gaia_version") in (3, "3")
    ev = dict(source="occult archive", key=key, target=str(rec["target_id"]), name=rec.get("target_name") or "",
              utc=rec["best_utc"][:23], star=str(rec.get("star") or ""), star_catalog=rec.get("star_catalog") or "",
              star_gaia=star_ok, star_ra=rec.get("star_ra"), star_dec=rec.get("star_dec"), r_km=rec.get("r_km"),
              mag=rec.get("mag"))
    if rec.get("n_sat"):
        ev["sat"] = dict(name=rec.get("sat_name") or "", r_km=(rec.get("sat_dia_km") or 0) / 2 or None,
                         sep_mas=rec.get("sat_sep_mas"), pa_deg=rec.get("sat_pa_deg"), fit=rec.get("sat_fit") or "")
    if rec.get("fit_major_km") and rec.get("fit_minor_km"):
        ev["archive_fit"] = dict(major=rec["fit_major_km"], minor=rec["fit_minor_km"], pa=rec.get("fit_pa_deg") or 0.0,
                                 utc=rec["best_utc"][:23],
                                 geo_x=rec.get("geo_x_km"), geo_y=rec.get("geo_y_km"),
                                 quality=rec.get("fit_quality_text") or "", assumed=bool(rec.get("fit_assumed_size")))
    return ev, st


def _report_utc(date, hms, ref=None):
    """'YYYY-MM-DDTHH:MM:SS.sss' of a report's time of day; across midnight from the reference time (datetime)."""
    from pysyzygos.obsreport import seconds_of_day
    s = seconds_of_day(hms)
    if s is None or not date:
        return None
    t = datetime.strptime(str(date)[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc) + timedelta(seconds=s)
    if ref is not None:
        if (t - ref).total_seconds() > 43200:
            t -= timedelta(days=1)
        elif (ref - t).total_seconds() > 43200:
            t += timedelta(days=1)
    return t.strftime("%Y-%m-%dT%H:%M:%S.%f")[:23]


def report_time(f):
    """A report's event time (datetime UTC): the predicted time, else D, else the date's noon; None without a date."""
    for k in ("predict_time", "d_time", "r_time"):
        u = _report_utc(f.get("date"), f.get(k))
        if u:
            return datetime.fromisoformat(u).replace(tzinfo=timezone.utc)
    return None


def report_group(path, folder=None):
    """The saved reports of the same event as `path` (all stations): same asteroid, times within GROUP_TOL_S."""
    from pysyzygos import obsreport
    me = obsreport.load(path)["fields"]
    t0, who = report_time(me), (str(me.get("asteroid_number") or ""), str(me.get("asteroid_name") or ""))
    out = []
    for r in obsreport.saved(folder or obsreport.DIR):
        f = obsreport.load(r["path"]).get("fields") or {}
        if (str(f.get("asteroid_number") or ""), str(f.get("asteroid_name") or "")) != who:
            continue
        t = report_time(f)
        if t0 is None or t is None or abs((t - t0).total_seconds()) <= GROUP_TOL_S:
            out.append(os.path.abspath(r["path"]))
    return sorted(set(out) | {os.path.abspath(path)})


def stations_reports(paths, entries=None):
    """(event, stations) from our saved reports of one event (obsreport.save; one per station). The star direction
    and the predicted size come from the event's favorite (the search's corrected star direction): `entries` (the
    favorites and saved lists; default: all of them)."""
    from pysyzygos import obsreport
    reps = [obsreport.load(p) for p in paths]
    fs = [r.get("fields") or {} for r in reps]
    if not fs:
        raise SystemExit("no reports")
    f0 = fs[0]
    ref = report_time(f0)
    if entries is None:
        entries = _all_entries()
    fav = next(iter(obsreport.matching(f0, entries)), None)
    rec = (fav or {}).get("record") or {}
    st = []
    for p, f in zip(paths, fs):
        try:
            lat, lon = float(f.get("lat")), float(f.get("lon"))
        except (TypeError, ValueError):
            continue
        res = RESULTS.get(str(f.get("outcome") or "").upper(), str(f.get("outcome") or "").lower() or "?")
        pe = _f(f.get("pe_s")) or 0.0
        x = dict(n=0, observer=", ".join(v for v in (f.get("observer1"), f.get("observer2")) if v),
                 place=f.get("station") or f.get("nearest_city") or "", lat=lat, lon=lon, alt_m=_f(f.get("alt_m")) or 0.0,
                 datum=f.get("datum") or "", method=f.get("method") or "", result=res, include=True, note="",
                 report=os.path.basename(os.path.dirname(p)) + "/" + os.path.basename(p))
        if res == "positive":
            d, r = _report_utc(f.get("date"), f.get("d_time"), ref), _report_utc(f.get("date"), f.get("r_time"), ref)
            if d and r:
                x.update(d_utc=d, r_utc=r, d_acc=_f(f.get("d_acc")), r_acc=_f(f.get("r_acc")), d_pe=pe, r_pe=pe)
            else:
                x["result"] = "positive (no times)"
        st.append(x)
    tid = str(f0.get("asteroid_number") or rec.get("target_id") or "").strip()
    ev = dict(source="reports", key=obsreport.event_key(f0), target=tid,
              name=f0.get("asteroid_name") or rec.get("target_name") or "",
              utc=(ref or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:23],
              star=str(f0.get("gaia_id") or rec.get("star") or ""), star_catalog=f0.get("star") or "",
              star_dir=[_f(rec.get("star_ra")), _f(rec.get("star_dec"))] if rec else None,
              r_km=_f(rec.get("r_km")) or ((_f(f0.get("asteroid_diam_km")) or 0) / 2 or None),
              mag=_f(rec.get("mag")), favorite=(fav or {}).get("key", ""), reports=list(paths))
    return ev, st


def archive_star(target, utc):
    """The star of the Occult archive's event of this asteroid within GROUP_TOL_S of utc (reports without a favorite,
    e.g. a past event entered by hand): dict(star, star_ra, star_dec, star_gaia, key), or None."""
    try:
        from pysyzygos import db, observed
        dbp = observed.paths()[1]
        if not os.path.isfile(dbp):
            return None
        t0 = datetime.fromisoformat(utc[:19])
        con = db.connect(dbp)
        try:
            rows = con.execute("SELECT best_utc, record FROM events WHERE target_id = ? AND best_utc LIKE ?",
                               (str(target), utc[:10] + "%")).fetchall()
        finally:
            con.close()
        for u, r in rows:
            if abs((datetime.fromisoformat(u[:19]) - t0).total_seconds()) <= GROUP_TOL_S:
                rec = json.loads(r)
                return dict(star=str(rec.get("star") or ""), star_ra=rec.get("star_ra"), star_dec=rec.get("star_dec"),
                            star_gaia=rec.get("star_gaia_version") in (3, "3"), key=f"{target}|{u[:19]}")
    except Exception:
        return None
    return None


def _all_entries():
    from pysyzygos import favorites
    out = list(favorites.load())
    for m in favorites.lists():
        try:
            with open(os.path.join(favorites.DIR, favorites.LISTS, m["slug"], "list.json"), encoding="utf-8") as fh:
                out += json.load(fh).get("entries", [])
        except (OSError, ValueError):
            pass
    return out


def _f(x):
    try:
        v = float(str(x).strip())
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------------------------------------- SPICE: the plane
# Math: OB.1, LT.1, FP.1, FP.2 (slides OB, LT, FP): the station relative to the asteroid in the fundamental plane.
def _plane_fn(spice, target, lon, lat, h_m, x_ax, y_ax):
    """q(et): the station minus the asteroid's predicted center in the fundamental plane (km, x east, y north; axes
    of date), the asteroid as the station sees it (light time from the station)."""
    from pysyzygos import earth
    site = spice.georec(math.radians(lon), math.radians(lat), h_m / 1000.0, earth.A_KM, earth.F)
    def q(et):
        v = np.asarray(spice.spkcpo(target, et, "J2000", "OBSERVER", "CN", site, "EARTH", "ITRF93")[0][:3])
        return -np.array([v @ x_ax, v @ y_ax])
    return q


def place_stations(spice, target, z, axes, stations, et_ref):
    """Adds to each station: t_ca (s from et_ref: its closest approach to the predicted center), p_ca (km), w (km/s,
    its motion relative to the asteroid), dist_km; with times also d_xy, r_xy, d_t, r_t (s from et_ref, personal
    equations removed)."""
    from scipy.optimize import minimize_scalar
    from pysyzygos import geoid
    x_ax, y_ax = axes
    for s in stations:
        try:
            h = float(s.get("alt_m") or 0.0) + (geoid.height(s["lat"], s["lon"]) if (s.get("datum") or "") in DATUM_WGS84
                                                 else 0.0)
            q = _plane_fn(spice, target, s["lon"], s["lat"], h, x_ax, y_ax)
            guess, span = 0.0, 1200.0
            if s.get("d_utc") and s.get("r_utc"):
                td = spice.str2et(s["d_utc"]) - (s.get("d_pe") or 0.0) - et_ref
                tr = spice.str2et(s["r_utc"]) - (s.get("r_pe") or 0.0) - et_ref
                s.update(d_t=round(td, 4), r_t=round(tr, 4), d_xy=[float(v) for v in q(et_ref + td)],
                         r_xy=[float(v) for v in q(et_ref + tr)])
                guess, span = (td + tr) / 2.0, 600.0
            r = minimize_scalar(lambda dt: float(np.hypot(*q(et_ref + guess + dt))), bounds=(-span, span),
                                method="bounded", options={"xatol": 1e-4, "maxiter": 500})
            t = guess + float(r.x)
            w = (q(et_ref + t + 0.5) - q(et_ref + t - 0.5))
            s.update(t_ca=round(t, 4), p_ca=[float(v) for v in q(et_ref + t)], w=[float(v) for v in w],
                     dist_km=round(float(r.fun), 3), h_ellipsoid_m=round(h, 1))
        except Exception as ex:
            s["note"] = (s.get("note", "") + f"; not placed: {type(ex).__name__}").strip("; ")
    return stations


def build(kind, what, log=print, folder=None):
    """The chords of one event: kind 'archive' (what = the archive key) or 'reports' (what = report paths). Fetches
    the orbit (JPL Horizons), places the stations, fits, writes <folder>/<event>/chords.json and profile.svg.
    Returns the chords.json path."""
    import spiceypy as spice
    from pysyzygos import astrometry, kernels, screen, obscheck
    from pysyzygos.home import HOME
    ev, st = stations_archive(what) if kind == "archive" else stations_reports(list(what))
    if not ev["target"]:
        raise SystemExit("no asteroid number or designation in the reports")
    screen.load_kernels(spice)
    et_ref = spice.str2et(ev["utc"])
    day = datetime.fromisoformat(ev["utc"][:19])
    a, b = (day - timedelta(days=1)).strftime("%Y-%m-%d"), (day + timedelta(days=1)).strftime("%Y-%m-%d")
    log(f"chords: {ev['name'] or ev['target']} {ev['utc'][:19]} UT, {len(st)} station(s); orbit from JPL Horizons")
    blob = obscheck.horizons_spk(ev["target"], a, b)
    tmp = tempfile.mkdtemp(prefix="chords_")
    fn = os.path.join(tmp, "orbit.bsp")
    with open(fn, "wb") as fh:
        fh.write(blob)
    try:
        spice.furnsh(fn)
        name = "CHORDS_TARGET"
        kernels.body_alias(spice, name, int(spice.spkobj(fn)[0]))
        z, star_note, pred = None, "", None
        fav_dir = ev.get("star_dir") if kind == "reports" and None not in (ev.get("star_dir") or [None]) else None
        arc = (dict(star=ev["star"], star_ra=ev["star_ra"], star_dec=ev["star_dec"], star_gaia=ev["star_gaia"])
               if kind == "archive" else archive_star(ev["target"], ev["utc"]))
        if arc and kind == "reports":                               # the event is in the archive (a past event)
            aev, _ = stations_archive(arc["key"])
            ev["archive_key"] = arc["key"]
            if aev.get("archive_fit"):
                ev["archive_fit"] = aev["archive_fit"]
            ev["r_km"] = ev.get("r_km") or aev.get("r_km")
            if fav_dir:
                arc = None                                         # the favorite's star: as the search took it
            else:
                ev["star_from"] = f"Occult archive event {arc['key']}"
                ev["star"] = ev.get("star") or arc["star"]
        if arc and arc.get("star_gaia"):                           # the star as the search takes it
            try:
                from pysyzygos import config, gaia_local
                row = obscheck.find_star(gaia_local.LocalGaia(config.gaia_local_dir),
                                         dict(star=arc["star"], star_gaia_version=3, star_ra=arc["star_ra"],
                                              star_dec=arc["star_dec"]), {})
                if row is not None:
                    pred = obscheck.predict(spice, name, row, et_ref)
                    z, star_note = pred["z"], "Gaia DR3 (local catalog) with all corrections, as the search"
            except Exception as ex:
                log(f"chords: star from the local catalog not usable ({type(ex).__name__}: {ex}); the archive's position")
        if z is None:
            ra, dec = (arc["star_ra"], arc["star_dec"]) if arc else (fav_dir or [None, None])
            if ra is None or dec is None:
                raise SystemExit("no star position: neither the event's favorite nor an archive event was found")
            u = np.array([math.cos(math.radians(dec)) * math.cos(math.radians(ra)),
                          math.cos(math.radians(dec)) * math.sin(math.radians(ra)), math.sin(math.radians(dec))])
            z = u if fav_dir else astrometry.corrected_star_dir(spice, u, 0.0, et_ref, name)[0]
            star_note = ("the search's corrected direction (favorite)" if fav_dir else
                         "the archive's position (+ light deflection)")
        axes = obscheck.date_axes(et_ref, np.asarray(z))
        place_stations(spice, name, np.asarray(z), axes, st, et_ref)
        if ev.get("archive_fit") and ev["archive_fit"].get("geo_x") is not None:   # Occult's center vs predicted
            t_af = spice.str2et(ev["archive_fit"].get("utc") or ev["utc"])        # at the archive's reference time
            p = np.asarray(spice.spkpos(name, t_af, "J2000", "CN", "EARTH")[0])
            af = ev["archive_fit"]
            af.update(x=round(af["geo_x"] - float(p @ axes[0]), 3), y=round(af["geo_y"] - float(p @ axes[1]), 3))
    finally:
        spice.unload(fn)
        os.remove(fn)
        os.rmdir(tmp)
    if kind == "reports":                                           # numbered across the track, north side first
        placed = [s for s in st if s.get("w")]
        if placed:
            w = np.mean([s["w"] for s in placed], axis=0)
            n = np.array([-w[1], w[0]]) / (np.hypot(*w) or 1.0)
            st.sort(key=lambda s: -float(np.dot(s.get("p_ca") or [0, 0], n)))
        for i, s in enumerate(st, 1):
            s["n"] = i
    data = dict(format=FORMAT, version=__version__, made=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"), event=ev,
                stations=st, star_used=star_note, frame="fundamental plane, axes of date (x east, y north), km; "
                "origin: the predicted asteroid (JPL Horizons orbit as of 'made')", fit_opts=dict(mode="auto",
                                                                                                  misses=False))
    out = os.path.join(folder or os.path.join(HOME, DIR), slug(ev["key"]))
    os.makedirs(out, exist_ok=True)
    try:                                                          # computed again: keep the choices made
        old = load(os.path.join(out, "chords.json"))
        data["fit_opts"] = old.get("fit_opts") or data["fit_opts"]
        was = {(s.get("observer"), round(s["lat"], 5), round(s["lon"], 5)): s.get("include", True)
               for s in old.get("stations", [])}
        for s in st:
            s["include"] = was.get((s.get("observer"), round(s["lat"], 5), round(s["lon"], 5)), s["include"])
    except (OSError, ValueError, KeyError):
        pass
    p = save(data, out)
    log(f"chords: {sum(1 for s in st if s.get('d_xy'))} chord(s), {sum(1 for s in st if s['result'] == 'miss')} "
        f"miss(es) -> {p}")
    return p


def save(data, out):
    """chords.json (atomic) and profile.svg with the fit of data['fit_opts']."""
    opts = data.get("fit_opts", {})
    fit_ = fit(data, **opts)
    data["fit"] = fit_
    if any((x.get("body") or "main") == "satellite" and x.get("d_xy") for x in data["stations"]):
        data["fit_sat"] = fit(data, mode="auto", exclude=opts.get("exclude", ()), body="satellite")
    else:
        data.pop("fit_sat", None)
    p = os.path.join(out, "chords.json")
    fd, tmp = tempfile.mkstemp(dir=out, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1)
    os.replace(tmp, p)
    with open(os.path.join(out, "profile.svg"), "w", encoding="utf-8") as fh:
        fh.write(svg(data, fit_))
    return p


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


# ------------------------------------------------------------------------------------------- the fit (pure)
def _radius(phi, a, b):
    """The ellipse's radius in the direction phi (from its major axis)."""
    return 1.0 / np.sqrt((np.cos(phi) / a) ** 2 + (np.sin(phi) / b) ** 2)


def _axes(pa_deg):
    """Unit vectors (x east, y north) of the major and minor axis for a position angle (north through east)."""
    t = math.radians(pa_deg)
    return np.array([math.sin(t), math.cos(t)]), np.array([math.cos(t), -math.sin(t)])


def used(data, exclude=(), body="main"):
    """The chords that enter the fit of a body ('main', 'satellite'): D and R placed, included, not in exclude
    (numbers)."""
    ex = {int(n) for n in exclude}
    return [s for s in data["stations"] if s.get("d_xy") and s.get("r_xy") and s.get("include", True)
            and s["n"] not in ex and (s.get("body") or "main") == body]


def fit(data, mode="auto", misses=False, exclude=(), diameter=None, body="main"):
    """The ellipse (or circle) fitted to the chords' end points: least squares of the radial distances of D and R
    from the outline (km), each miss inside the outline adding its depth when misses=True. mode 'auto': ellipse with
    3 or more chords, circle with 2, the predicted (or given) diameter with 1. Returns dict(mode, x, y (center:
    observed minus predicted, km), major, minor, pa (deg, major axis from north through east), their 1-sigma, rms_km,
    n_chords, per-station residuals (D and R: km radial, s along the track)) or dict(mode='none', why=...). body:
    the main body's chords, or a satellite's (its own outline; misses and its fixed size: the archive's diameter)."""
    from scipy.optimize import least_squares
    ch = used(data, exclude, body)
    n = len(ch)
    if mode == "auto":
        mode = "ellipse" if n >= 3 else "circle" if n == 2 else "fixed"
    sat = body != "main"
    misses = misses and not sat
    r_fix = (diameter or 0) / 2.0 or ((data["event"].get("sat") or {}).get("r_km") if sat else data["event"].get("r_km"))
    if n == 0 or (mode == "fixed" and not r_fix):
        return dict(mode="none", why="no chord to fit" if n == 0 else "no diameter for a fixed-size fit")
    pts = np.array([s[k] for s in ch for k in ("d_xy", "r_xy")])
    mlines = [(np.array(s["p_ca"]), np.array(s["w"])) for s in data["stations"]
              if misses and s["result"] == "miss" and s.get("p_ca") and s.get("w") and s.get("include", True)
              and s["n"] not in {int(k) for k in exclude}]
    c0 = pts.mean(axis=0)
    r0 = max(float(np.max(np.hypot(*(pts - c0).T))), 0.5)

    def unpack(p):
        if mode == "ellipse":
            return p[0], p[1], abs(p[2]), abs(p[3]), math.degrees(p[4])
        if mode == "circle":
            return p[0], p[1], abs(p[2]), abs(p[2]), 0.0
        return p[0], p[1], r_fix, r_fix, 0.0

    def resid(p):
        x, y, a, b, pa = unpack(p)
        e1, e2 = _axes(pa)
        v = pts - [x, y]
        phi = np.arctan2(v @ e2, v @ e1)
        out = list(np.hypot(*v.T) - _radius(phi, max(a, 1e-3), max(b, 1e-3)))
        for p0, w in mlines:                        # a miss whose track passes inside the outline: how deep
            u = w / (np.hypot(*w) or 1.0)
            q = p0 - [x, y]
            qq = np.array([(q @ e1) / a, (q @ e2) / b])          # in the outline's unit circle
            uu = np.array([(u @ e1) / a, (u @ e2) / b])
            t = -(qq @ uu) / (uu @ uu)
            d = float(np.hypot(*(qq + t * uu)))
            out.append(max(0.0, 1.0 - d) * (a + b) / 2.0)
        return np.array(out)

    starts = {"ellipse": [[c0[0], c0[1], r0 * 1.1, r0 * 0.9, math.radians(t)] for t in (0, 45, 90, 135)],
              "circle": [[c0[0], c0[1], r0]],
              "fixed": [[c0[0], c0[1]], [0.0, 0.0]]}[mode]
    if mode == "ellipse" and len(pts) + len(mlines) < 6:
        return dict(mode="none", why="an ellipse needs 3 chords: choose circle or fixed")
    best = None
    for x0 in starts:
        try:
            r = least_squares(resid, np.array(x0, float), method="lm" if len(pts) + len(mlines) >= len(x0) else "trf")
        except ValueError:
            r = least_squares(resid, np.array(x0, float), method="trf")
        if best is None or r.cost < best.cost:
            best = r
    x, y, a, b, pa = unpack(best.x)
    res = resid(best.x)
    k = len(best.x)
    dof = len(res) - k
    sig = [None] * 5
    if dof > 0:
        try:
            cov = np.linalg.inv(best.jac.T @ best.jac) * float(res @ res) / dof
            sd = np.sqrt(np.clip(np.diag(cov), 0, None))
            sig = ([sd[0], sd[1], sd[2], sd[3], math.degrees(sd[4])] if mode == "ellipse" else
                   [sd[0], sd[1], sd[2], sd[2], None] if mode == "circle" else [sd[0], sd[1], None, None, None])
        except np.linalg.LinAlgError:
            pass
    if b > a:                                      # the major axis first
        a, b, pa = b, a, pa + 90.0
        if sig[2] is not None:
            sig[2], sig[3] = sig[3], sig[2]
    pa %= 180.0
    rms = float(np.sqrt(np.mean(res[:len(pts)] ** 2)))
    per = {}
    for i, s in enumerate(ch):
        di, ri = res[2 * i], res[2 * i + 1]
        entry, leave = crossing(s, (x, y, a, b, pa))
        per[str(s["n"])] = dict(d_km=round(float(di), 3), r_km=round(float(ri), 3),
                                d_s=None if entry is None else round(s["d_t"] - entry, 3),
                                r_s=None if leave is None else round(s["r_t"] - leave, 3))
    for s in data["stations"] if not sat else ():  # misses: inside the fitted outline?
        if s["result"] == "miss" and s.get("p_ca"):
            e, _ = crossing(s, (x, y, a, b, pa))
            per[str(s["n"])] = dict(miss_inside=e is not None)
    r1 = lambda v, nd=2: None if v is None else round(float(v), nd)
    return dict(mode=mode, x=r1(x, 3), y=r1(y, 3), major=r1(2 * a), minor=r1(2 * b), pa=r1(pa, 1),
                sx=r1(sig[0]), sy=r1(sig[1]), smajor=r1(None if sig[2] is None else 2 * sig[2]),
                sminor=r1(None if sig[3] is None else 2 * sig[3]), spa=r1(sig[4], 1), rms_km=round(rms, 3),
                n_chords=n, misses=bool(mlines), excluded=sorted(int(k) for k in exclude), stations=per, body=body)


def crossing(s, ell):
    """(entry, exit) times (s from the reference, as d_t / r_t) of a station's track through the ellipse
    (x, y, a, b, pa), or (None, None); the track straight with its motion at closest approach."""
    x, y, a, b, pa = ell
    e1, e2 = _axes(pa)
    p0, w = np.array(s["p_ca"]) - [x, y], np.array(s["w"])
    u1, u2, w1, w2 = p0 @ e1, p0 @ e2, w @ e1, w @ e2
    A = w1 * w1 / (a * a) + w2 * w2 / (b * b)
    B = 2.0 * (u1 * w1 / (a * a) + u2 * w2 / (b * b))
    C = u1 * u1 / (a * a) + u2 * u2 / (b * b) - 1.0
    disc = B * B - 4.0 * A * C
    if A <= 0 or disc <= 0:
        return None, None
    r = math.sqrt(disc)
    return s["t_ca"] + (-B - r) / (2 * A), s["t_ca"] + (-B + r) / (2 * A)


def fit_text(f):
    """'103.6 ± 2.1 × 59.9 ± 1.8 km, PA 40.6 ± 1.2°, RMS 1.8 km (12 chords)' or why there is none."""
    if not f or f.get("mode") == "none":
        return "no fit" + (f": {f['why']}" if f and f.get("why") else "")
    pm = lambda v, s, nd=1: f"{v:.{nd}f}" + (f" ± {s:.{nd}f}" if s is not None else "")
    if f["mode"] == "ellipse":
        size = f"{pm(f['major'], f['smajor'])} × {pm(f['minor'], f['sminor'])} km, PA {pm(f['pa'], f['spa'])}°"
    elif f["mode"] == "circle":
        size = f"circle {pm(f['major'], f['smajor'])} km"
    else:
        size = f"fixed diameter {f['major']:.1f} km"
    return (f"{size}, center {f['x']:+.1f}, {f['y']:+.1f} km from the prediction, RMS {f['rms_km']:.2f} km "
            f"({f['n_chords']} chord{'s' if f['n_chords'] != 1 else ''}" + (", misses as limits" if f.get("misses") else "")
            + ")")


# ------------------------------------------------------------------------------------------- the plot (pure)
W, H, PLOT = 1000, 720, 640                        # page, plot square (left); the station list on the right
COL = dict(pos="#1d4ed8", track="#cbd5e1", miss="#dc2626", off="#9ca3af", fit="#059669", occ="#9333ea",
           pred="#64748b", ink="#0f172a", muted="#64748b", err="#f59e0b", sat="#ea580c", sfit="#c2410c")
BODY_COL = {"main": "#1d4ed8", "satellite": "#ea580c", "2nd star": "#0d9488", "satellite, 2nd star": "#b45309"}
BODY_TAG = {"main": "+", "satellite": "s", "2nd star": "2", "satellite, 2nd star": "s2"}


def fit_lines(data, f=None):
    """The fit(s) as text lines: the main body's, and a satellite's when it has chords."""
    f = f if f is not None else data.get("fit")
    fs = data.get("fit_sat")
    if not fs:
        return [fit_text(f)]
    name = ((data["event"].get("sat") or {}).get("name") or "").strip()
    out = [] if (f or {}).get("why") == "no chord to fit" else ["main body: " + fit_text(f)]
    return out + [f"satellite{' ' + name if name else ''}: " + fit_text(fs)]


def _nice(v):
    """A round scale-bar length near v (1, 2, 5 x 10^n)."""
    e = 10 ** math.floor(math.log10(max(v, 1e-6)))
    return next(m * e for m in (1, 2, 5, 10) if m * e >= v)


def _esc(t):
    return (str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))


def label(ev):
    """'(135) Hertha' (the archive's names carry the number: '135 Hertha'), or the designation."""
    t = str(ev.get("target") or "")
    if t.isdigit():
        bare = re.sub(rf"^\(?{re.escape(t)}\)?\s+", "", str(ev.get("name") or ""))
        return f"({t}) {bare}".strip()
    return str(ev.get("name") or t)


def _ellipse_pts(x, y, a, b, pa, n=180):
    e1, e2 = _axes(pa)
    t = np.linspace(0, 2 * math.pi, n + 1)
    return [(x + a * math.cos(s) * e1[0] + b * math.sin(s) * e2[0],
             y + a * math.cos(s) * e1[1] + b * math.sin(s) * e2[1]) for s in t]


def svg(data, f=None):
    """The profile plot as Occult draws it: sky view (north up, east left), each station's track across the plot,
    the chord from D to R (with its timing accuracy), misses dashed, the fitted outline, the predicted size at the
    predicted center, the archive's (Occult's) fit for comparison, and the numbered station list."""
    ev, st = data["event"], data["stations"]
    f = f if f is not None else data.get("fit")
    ok = f and f.get("mode") not in (None, "none")
    fs = data.get("fit_sat")
    ok_s = fs and fs.get("mode") not in (None, "none")
    lines = fit_lines(data, f)
    top = 70 + 16 * (len(lines) - 1)               # the plot's top edge: below the title and the fit lines
    HH = H + top - 70
    pts = [p for s in st for p in (s.get("d_xy"), s.get("r_xy")) if p]
    shapes = []
    if ok:
        shapes += _ellipse_pts(f["x"], f["y"], f["major"] / 2, f["minor"] / 2, f["pa"], 36)
    if ok_s:
        shapes += _ellipse_pts(fs["x"], fs["y"], fs["major"] / 2, fs["minor"] / 2, fs["pa"], 36)
    af = ev.get("archive_fit")
    if af and af.get("x") is not None:
        shapes += _ellipse_pts(af["x"], af["y"], af["major"] / 2, af["minor"] / 2, af["pa"], 36)
    if ev.get("r_km"):
        shapes += _ellipse_pts(0.0, 0.0, ev["r_km"], ev["r_km"], 0.0, 36)
    allp = np.array(pts + shapes) if pts + shapes else np.array([[0.0, 0.0]])
    if not pts and not shapes:                     # misses only: around their closest approaches
        mp = [s["p_ca"] for s in st if s.get("p_ca")]
        allp = np.array(mp or [[0.0, 0.0]])
    lo, hi = allp.min(axis=0), allp.max(axis=0)
    cx, cy = (lo + hi) / 2.0
    half = max(float(max(hi - lo)) / 2.0 * 1.18, 5.0)
    k = (PLOT - 40) / (2 * half)                   # px per km
    ox, oy = 20 + PLOT / 2, top + PLOT / 2
    X = lambda x: ox - (x - cx) * k                # east to the left (sky view)
    Y = lambda y: oy - (y - cy) * k
    P = lambda p: f"{X(p[0]):.1f},{Y(p[1]):.1f}"
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {HH}" width="{W}" height="{HH}" '
         f'font-family="system-ui,sans-serif" font-size="12">',
         f'<rect width="{W}" height="{HH}" fill="#ffffff"/>',
         f'<defs><clipPath id="plotclip"><rect x="20" y="{top}" width="{PLOT}" height="{PLOT}"/></clipPath></defs>']
    name = label(ev)
    o.append(f'<text x="20" y="26" font-size="18" font-weight="600" fill="{COL["ink"]}">{_esc(name)} '
             f'{_esc(ev["utc"][:19].replace("T", " "))} UT</text>')
    for i, t in enumerate(lines):
        o.append(f'<text x="20" y="{46 + 16 * i}" fill="{COL["sfit"] if t.startswith("satellite") else COL["ink"]}">'
                 f'{_esc(t)}</text>')
    sub = (f"star {ev.get('star_catalog') or ''}" + (f" (Gaia DR3 {ev['star']})" if ev.get("star") else "")
           + f" · {'Occult archive' if ev['source'] == 'occult archive' else 'our reports'} · "
           f"PySyzygos {data.get('version', __version__)}, orbit JPL Horizons")
    o.append(f'<text x="20" y="{top - 8}" font-size="11" fill="{COL["muted"]}">{_esc(sub)}</text>')
    o.append(f'<rect x="20" y="{top}" width="{PLOT}" height="{PLOT}" fill="#f8fafc" stroke="#e2e8f0"/>')
    o.append('<g clip-path="url(#plotclip)">')
    excl = set(f.get("excluded") or []) if f else set()
    per = dict((f or {}).get("stations") or {}, **((fs or {}).get("stations") or {}))
    for s in st:                                   # tracks, then chords on top
        if not s.get("p_ca") or not s.get("w") or s["result"] in ("clouded", "other"):
            continue
        w = np.array(s["w"])
        sp = np.hypot(*w) or 1.0
        tc = float(np.dot(np.array([cx, cy]) - s["p_ca"], w) / sp ** 2)          # nearest to the view center
        L = 3 * half / sp
        a_, b_ = np.array(s["p_ca"]) + w * (tc - L), np.array(s["p_ca"]) + w * (tc + L)
        off = not s.get("include", True) or s["n"] in excl
        if s["result"] == "miss":
            col, dash = (COL["off"] if off else COL["miss"]), ' stroke-dasharray="7 5"'
            o.append(f'<line x1="{X(a_[0]):.1f}" y1="{Y(a_[1]):.1f}" x2="{X(b_[0]):.1f}" y2="{Y(b_[1]):.1f}" '
                     f'stroke="{col}" stroke-width="1.3"{dash}><title>{s["n"]} {_esc(s["observer"])}, '
                     f'{_esc(s["place"])}: miss</title></line>')
        else:
            o.append(f'<line x1="{X(a_[0]):.1f}" y1="{Y(a_[1]):.1f}" x2="{X(b_[0]):.1f}" y2="{Y(b_[1]):.1f}" '
                     f'stroke="{COL["track"]}" stroke-width="1"/>')
    if ev.get("r_km"):                             # the predicted size at the predicted center
        r = ev["r_km"] * k
        o.append(f'<circle cx="{X(0):.1f}" cy="{Y(0):.1f}" r="{r:.1f}" fill="none" stroke="{COL["pred"]}" '
                 f'stroke-width="1" stroke-dasharray="3 4"><title>predicted: {2 * ev["r_km"]:.1f} km at the predicted '
                 f'center</title></circle>')
        o.append(f'<path d="M{X(0) - 6:.1f},{Y(0):.1f}h12M{X(0):.1f},{Y(0) - 6:.1f}v12" stroke="{COL["pred"]}"/>')
    if af and af.get("x") is not None:
        o.append(f'<polyline points="{" ".join(P(p) for p in _ellipse_pts(af["x"], af["y"], af["major"] / 2, af["minor"] / 2, af["pa"]))}" '
                 f'fill="none" stroke="{COL["occ"]}" stroke-width="1.4" stroke-dasharray="2 3"><title>Occult archive '
                 f'fit: {af["major"]:.1f} x {af["minor"]:.1f} km, PA {af["pa"]:.1f}° {_esc(af.get("quality", ""))}'
                 f'</title></polyline>')
    for g, c, t in ((f, COL["fit"], lines[0]), (fs, COL["sfit"], lines[-1])):
        if not g or g.get("mode") in (None, "none"):
            continue
        o.append(f'<polyline points="{" ".join(P(p) for p in _ellipse_pts(g["x"], g["y"], g["major"] / 2, g["minor"] / 2, g["pa"]))}" '
                 f'fill="{c}" fill-opacity="0.07" stroke="{c}" stroke-width="2"><title>{_esc(t)}</title></polyline>')
        o.append(f'<path d="M{X(g["x"]) - 5:.1f},{Y(g["y"]) - 5:.1f}l10,10M{X(g["x"]) - 5:.1f},{Y(g["y"]) + 5:.1f}'
                 f'l10,-10" stroke="{c}" stroke-width="1.5"/>')
    for s in st:                                   # the chords: D to R, accuracy bars, D square, R circle
        if not s.get("d_xy") or not s.get("r_xy"):
            continue
        off = not s.get("include", True) or s["n"] in excl
        col = COL["off"] if off else BODY_COL.get(s.get("body") or "main", COL["pos"])
        d, r = np.array(s["d_xy"]), np.array(s["r_xy"])
        w = np.array(s.get("w") or (r - d))
        u = w / (np.hypot(*w) or 1.0)
        sp = float(np.hypot(*w))
        tip = (f'{s["n"]} {s["observer"]}, {s["place"]}' + (f' ({s["body"]})' if (s.get("body") or "main") != "main" else "")
               + f': D {s.get("d_utc", "")[11:]} R {s.get("r_utc", "")[11:]} UT, '
               f'{(s["r_t"] - s["d_t"]):.2f} s, {np.hypot(*(r - d)):.1f} km' + (f' ({s["note"]})' if s.get("note") else ""))
        res = per.get(str(s["n"])) or {}
        if res.get("d_s") is not None:
            tip += f'; O−C D {res["d_s"]:+.2f} s, R {res["r_s"]:+.2f} s'
        o.append(f'<g><title>{_esc(tip)}</title><line x1="{X(d[0]):.1f}" y1="{Y(d[1]):.1f}" x2="{X(r[0]):.1f}" '
                 f'y2="{Y(r[1]):.1f}" stroke="{col}" stroke-width="{2.6 if not off else 1.6}"'
                 + (' stroke-dasharray="5 3"' if off else "") + '/>')
        for p_, acc, mark in ((d, s.get("d_acc"), "sq"), (r, s.get("r_acc"), "ci")):
            if acc:
                e = u * acc * sp
                o.append(f'<line x1="{X(p_[0] - e[0]):.1f}" y1="{Y(p_[1] - e[1]):.1f}" x2="{X(p_[0] + e[0]):.1f}" '
                         f'y2="{Y(p_[1] + e[1]):.1f}" stroke="{COL["err"]}" stroke-width="5" stroke-opacity="0.55"/>')
            o.append(f'<rect x="{X(p_[0]) - 3:.1f}" y="{Y(p_[1]) - 3:.1f}" width="6" height="6" fill="#fff" stroke="{col}" '
                     f'stroke-width="1.4"/>' if mark == "sq" else
                     f'<circle cx="{X(p_[0]):.1f}" cy="{Y(p_[1]):.1f}" r="3.3" fill="#fff" stroke="{col}" stroke-width="1.4"/>')
        o.append("</g>")
    o.append("</g>")
    for s in st:                                   # numbers where the track enters the plot
        if not s.get("p_ca") or not s.get("w") or s["result"] in ("clouded", "other"):
            continue
        pos = _entry(s, X, Y, half, top)
        if pos:
            col = COL["miss"] if s["result"] == "miss" else BODY_COL.get(s.get("body") or "main") if s.get("d_xy") \
                else COL["muted"]
            o.append(f'<text x="{pos[0]:.1f}" y="{pos[1]:.1f}" fill="{col}" font-size="11" text-anchor="middle" '
                     f'dominant-baseline="middle" paint-order="stroke" stroke="#f8fafc" stroke-width="3">{s["n"]}</text>')
    # compass, motion, scale
    o.append(f'<g fill="{COL["ink"]}" stroke="{COL["ink"]}" font-size="12" transform="translate(0,{top - 70})">'
             f'<path d="M60,130v-38m0,0l-4,8m4,-8l4,8'
             f'M60,130h-34m0,0l8,-4m-8,4l8,4" fill="none" stroke-width="1.3"/><text x="60" y="86" stroke="none" '
             f'text-anchor="middle">N</text><text x="20" y="134" stroke="none" text-anchor="start" dx="-2">E</text></g>')
    ws = [np.array(s["w"]) for s in st if s.get("w")]
    if ws:
        w = -np.mean(ws, axis=0)                   # the asteroid (its shadow) relative to the stations
        u = w / (np.hypot(*w) or 1.0)
        bx, by = 20 + PLOT - 70, top + 40
        ex, ey = -u[0], -u[1]                      # screen direction (east left, y down)
        hx, hy = bx + 26 * ex, by + 26 * ey
        o.append(f'<g stroke="{COL["muted"]}" fill="{COL["muted"]}"><line x1="{bx - 26 * ex:.1f}" y1="{by - 26 * ey:.1f}" '
                 f'x2="{hx:.1f}" y2="{hy:.1f}" stroke-width="1.5"/><path d="M{hx:.1f},{hy:.1f}'
                 f'L{hx - 9 * ex + 4 * ey:.1f},{hy - 9 * ey - 4 * ex:.1f}L{hx - 9 * ex - 4 * ey:.1f},{hy - 9 * ey + 4 * ex:.1f}Z"/>'
                 f'<text x="{bx}" y="{by + 44}" stroke="none" text-anchor="middle" font-size="11">asteroid motion, '
                 f'{np.hypot(*w):.2f} km/s</text></g>')
    bar = _nice(half / 3)
    bx, by = 20 + PLOT - 20 - bar * k, top + PLOT - 22
    o.append(f'<g stroke="{COL["ink"]}"><path d="M{bx:.1f},{by - 4}v4h{bar * k:.1f}v-4" fill="none" stroke-width="1.4"/>'
             f'<text x="{bx + bar * k / 2:.1f}" y="{by + 15}" stroke="none" fill="{COL["ink"]}" '
             f'text-anchor="middle">{bar:g} km</text></g>')
    # legend of the lines
    lx = 20 + PLOT + 22                            # under the station list
    main = any((x.get("body") or "main") == "main" and x.get("d_xy") for x in st) or not pts
    items = ([(COL["pos"], "", 2.6, "chord D–R (□ D, ○ R; amber: timing accuracy)")] if main else []) + \
        [(COL["miss"], "7 5", 1.3, "miss")] + ([(COL["fit"], "", 2, "fit to the chords")] if ok or main else [])
    if any((x.get("body") or "main") == "satellite" and x.get("d_xy") for x in st):
        items[1:1] = [(COL["sat"], "", 2.6, "satellite chord (s)")]
        if ok_s:
            items.append((COL["sfit"], "", 2, "fit to the satellite's chords"))
    if any((x.get("body") or "main") in ("2nd star", "satellite, 2nd star") and x.get("d_xy") for x in st):
        items[1:1] = [(BODY_COL["2nd star"], "", 2.6, "chord on the 2nd star (2)")]
    if af and af.get("x") is not None:
        items.append((COL["occ"], "2 3", 1.4, "Occult archive fit"))
    if ev.get("r_km"):
        items.append((COL["pred"], "3 4", 1, f"predicted {2 * ev['r_km']:.0f} km at the predicted center (+)"))
    ly = HH - 14 - 15 * len(items)
    for i, (c, dash, sw, t) in enumerate(items):
        y = ly + 15 * i
        o.append(f'<line x1="{lx}" y1="{y}" x2="{lx + 26}" y2="{y}" stroke="{c}" stroke-width="{sw}"'
                 + (f' stroke-dasharray="{dash}"' if dash else "") + f'/><text x="{lx + 34}" y="{y + 4}" '
                 f'font-size="11" fill="{COL["ink"]}">{_esc(t)}</text>')
    # the station list
    tx, ty = 20 + PLOT + 22, top + 14
    o.append(f'<text x="{tx}" y="{ty}" font-weight="600" fill="{COL["ink"]}">Stations</text>'
             f'<text x="{W - 12}" y="{ty}" font-size="10" text-anchor="end" fill="{COL["muted"]}">O−C D / R (s)</text>')
    rows = [s for s in st]
    lh = min(17.0, (HH - ty - 40 - 15 * len(items)) / max(len(rows), 1))
    fs = 11 if lh >= 14 else 9
    for i, s in enumerate(rows):
        y = ty + 18 + i * lh
        off = not s.get("include", True) or s["n"] in excl
        res = s["result"]
        col = (COL["off"] if off else BODY_COL.get(s.get("body") or "main", COL["pos"]) if res == "positive" else
               COL["miss"] if res == "miss" else COL["muted"])
        tag = (BODY_TAG.get(s.get("body") or "main", "+") if res == "positive" else
               {"miss": "–", "clouded": "c"}.get(res, "?"))
        r = per.get(str(s["n"])) or {}
        oc = (f"{r['d_s']:+.2f} / {r['r_s']:+.2f}" if r.get("d_s") is not None and r.get("r_s") is not None else
              "inside!" if r.get("miss_inside") else "")
        who = f"{s['observer']}, {s['place']}".strip(", ")
        who = who if len(who) <= 30 else who[:29] + "…"
        o.append(f'<text x="{tx}" y="{y:.1f}" font-size="{fs}" fill="{col}"><tspan font-weight="600">{s["n"]:>2}</tspan>'
                 f'<tspan x="{tx + 22}">{tag}</tspan><tspan x="{tx + 34}"'
                 + (' text-decoration="line-through"' if off else "") + f'>{_esc(who)}</tspan>'
                 f'<title>{_esc(res + ("; " + s["note"] if s.get("note") else "") + ("; not in the fit" if off else ""))}'
                 f'</title></text><text x="{W - 12}" y="{y:.1f}" font-size="{fs}" text-anchor="end" fill="'
                 + (COL["miss"] if oc == "inside!" else COL["muted"]) + f'">{oc}</text>')
    o.append("</svg>")
    return "\n".join(o)


def _entry(s, X, Y, half, top=70):
    """Where the station's track enters the plot square (svg coordinates, a little inside), or None."""
    p0, w = np.array(s["p_ca"]), np.array(s["w"])
    best = None
    for t in np.linspace(-3 * half, 3 * half, 1201) / (np.hypot(*w) or 1.0):
        p = p0 + w * t
        x, y = X(p[0]), Y(p[1])
        if 20 + 12 <= x <= 20 + PLOT - 12 and top + 12 <= y <= top + PLOT - 12:
            best = (x, y) if best is None else best
            break
    return best


# ------------------------------------------------------------------------------------------- CLI
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=f"PySyzygos {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a1 = sub.add_parser("archive", help="an event of the Occult archive")
    a1.add_argument("key", help="'<target>|<YYYY-MM-DDTHH:MM:SS>' (the archive's reference time)")
    a2 = sub.add_parser("reports", help="our saved reports of one event (one per station)")
    a2.add_argument("paths", nargs="+", help="report .json files; one is enough: the others of its event are added")
    a3 = sub.add_parser("fit", help="fit and draw again (no SPICE)")
    a3.add_argument("json", help="chords.json")
    a3.add_argument("--mode", choices=MODES, default=None)
    a3.add_argument("--misses", action="store_true", help="misses as limits of the outline")
    a3.add_argument("--exclude", default="", help="station numbers left out of the fit, e.g. 3,5")
    a3.add_argument("--diameter", type=float, help="diameter for --mode fixed (default: the predicted one)")
    for p in (a1, a2):
        p.add_argument("--out", help="folder (default: observations/chords in the data folder)")
    a = ap.parse_args(argv)
    if a.cmd == "archive":
        print(build("archive", a.key, folder=a.out))
    elif a.cmd == "reports":
        paths = sorted({q for p in a.paths for q in report_group(os.path.abspath(p))})
        print(build("reports", paths, folder=a.out))
    else:
        d = load(a.json)
        opts = dict(d.get("fit_opts") or {})
        if a.mode:
            opts["mode"] = a.mode
        if a.misses:
            opts["misses"] = True
        if a.exclude:
            opts["exclude"] = [int(x) for x in a.exclude.split(",") if x.strip()]
        if a.diameter:
            opts["diameter"] = a.diameter
        d["fit_opts"] = opts
        save(d, os.path.dirname(os.path.abspath(a.json)))
        print("\n".join(fit_lines(d)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
