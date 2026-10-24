"""obscheck.py - our predictions against every observed occultation of the IOTA / Occult archive.

    pysyzygos obs-check run [--since YEAR] [--asteroids N,N,...] [--limit N] [--workers 2] [--fresh]
    pysyzygos obs-check report

For each observed event with an astrometric solution (observed.py: geo_x_km / geo_y_km, the observed centre of the
asteroid in the fundamental plane through the geocentre, axes of date, at the archive's reference time) on a Gaia
DR3 star of the local catalog: the asteroid's position as PySyzygos predicts it at that time (today's JPL Horizons
orbit, asteroid 'CN' from the geocentre; the star as the search takes it: Gaia DR3 with proper motion, the bright-
star frame-spin bias, radial velocity, stellar parallax and light deflection), in the same plane, turned from J2000
axes to axes of date (IAU 2006/2000A precession-nutation, erfa.pnm06a). Observed minus predicted: across the track
(km; + to the left of the motion) and along it (km and s). Written per event to <occult_data>/obs_check.jsonl
(resumed: done asteroids are skipped), into the observations database (chk_* fields: Results tab, 'Observed events'
column "Obs - pred", SQL dx_across / dt_along) and summarised in obs_check.md.

Orbits: one JPL Horizons SPK per asteroid spanning all its events, downloaded `workers` at a time (threads, network
only; SPICE in the main thread), deleted after use. ~7,000 asteroids: a few hours; Stop and run again to resume.
Note: JPL's orbit solutions include occultation astrometry for some asteroids, so the recent events partly test
consistency rather than prediction.
"""
import argparse, base64, json, math, os, queue, sys, tempfile, threading, time
from datetime import datetime, timezone

import numpy as np

from pysyzygos.version import __version__
from pysyzygos import urls as U
from pysyzygos import db, observed, occultdata

RESULTS = "obs_check.jsonl"
SUMMARY = "obs_check.md"
PAD_DAYS = 2


def files(base=None):
    d = occultdata.folder(base)
    return os.path.join(d, RESULTS), os.path.join(d, SUMMARY)


def ev_key(r):
    return f"{r['target_id']}|{str(r['best_utc'])[:19]}|{r.get('star', '')}"


def load_results(path):
    out = {}
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    x = json.loads(line)
                    out[x["key"]] = x
                except (ValueError, KeyError):
                    continue
    return out


# ----------------------------------------------------------------------------------------------- orbits
def horizons_spk(number, start, stop, timeout=120):
    """The asteroid's SPK (bytes) from JPL Horizons for [start, stop] (YYYY-MM-DD). Network only (threads)."""
    import requests
    for k in range(4):
        r = requests.get(U.URL_JPL_HORIZONS_API, params={
            "format": "json", "COMMAND": f"{number};", "EPHEM_TYPE": "SPK", "MAKE_EPHEM": "YES",
            "START_TIME": start, "STOP_TIME": stop, "OBJ_DATA": "NO"}, timeout=(15, timeout))
        if r.status_code != 503 or k == 3:
            break
        time.sleep(2.0 * (k + 1))
    r.raise_for_status()
    data = r.json()
    if "spk" not in data:
        raise RuntimeError(" ".join(str(data.get("result", data)).split())[:200])
    return base64.b64decode(data["spk"])


def _span(events):
    d = [datetime.fromisoformat(e["best_utc"][:19]) for e in events]
    a = datetime.fromtimestamp(min(x.timestamp() for x in d) - PAD_DAYS * 86400, timezone.utc)
    b = datetime.fromtimestamp(max(x.timestamp() for x in d) + PAD_DAYS * 86400, timezone.utc)
    return a.strftime("%Y-%m-%d"), b.strftime("%Y-%m-%d")


# ----------------------------------------------------------------------------------------------- one event
def date_axes(et, z):
    """(x, y) unit vectors of the fundamental plane in axes of date: y toward the true pole of date (IAU 2006/2000A,
    erfa.pnm06a: GCRS -> true equator and equinox of date), x = y x z (east), for the star direction z (GCRS)."""
    import erfa
    jd = 2451545.0 + et / 86400.0                                          # TDB ~ TT for this purpose
    npb = erfa.pnm06a(2451545.0, jd - 2451545.0)
    pole = np.asarray(npb)[2]                                               # true pole of date in GCRS
    x = np.cross(pole, z)
    x /= np.linalg.norm(x)
    return x, np.cross(z, x)


# Math: FP.1, FP.2 (slide FP): the asteroid's offsets in the plane through the geocentre, axes of date.
def predict(spice, target, star_row, et, use_parallax=True, use_deflection=True):
    """dict(x, y (km, axes of date), vx, vy (km/s), dist_km, star_corr) of the asteroid at et, or raises."""
    from pysyzygos import astrometry, corridor
    utc = spice.et2utc(et, "ISOC", 3)
    prop = corridor.propagate_exact(star_row, utc, pm_bias=True, rv=True)
    ra = float(prop.filter(regex=r"^ra_\d{8}$").iloc[0, 0])
    dec = float(prop.filter(regex=r"^dec_\d{8}$").iloc[0, 0])
    u0 = np.array([math.cos(math.radians(dec)) * math.cos(math.radians(ra)),
                   math.cos(math.radians(dec)) * math.sin(math.radians(ra)), math.sin(math.radians(dec))])
    z, corr = astrometry.corrected_star_dir(spice, u0, float(star_row["parallax"].iloc[0] or 0.0), et, target,
                                            parallax=use_parallax, deflection=use_deflection)
    x_ax, y_ax = date_axes(et, z)
    p = np.asarray(spice.spkpos(target, et, "J2000", "CN", "EARTH")[0])
    p1 = np.asarray(spice.spkpos(target, et + 1.0, "J2000", "CN", "EARTH")[0])
    return dict(x=float(p @ x_ax), y=float(p @ y_ax), vx=float((p1 - p) @ x_ax), vy=float((p1 - p) @ y_ax),
                dist_km=float(np.linalg.norm(p)), star_corr=corr, z=z)


# ----------------------------------------------------------------------------------------------- at the sites
DATUM_WGS84 = ("_", "", "*")                     # WGS84, or unspecified (taken as WGS84; '*' noted)
VISUAL = "f"                                     # observing method 'visual' (personal equation, reaction times)


def load_chords(dbp):
    """{event key: ([positive chords], [misses])} from the observations database: a chord = one observer's main-star
    D and R at one site (contacts, codes D/R), with the site (lon, lat, alt_m, datum), method, accuracies, personal
    equations, Occult's include flags and time adjustment; misses from the record's obs_sites."""
    con = db.connect(dbp)
    ev = {r["id"]: json.loads(r["record"]) for r in con.execute("SELECT id, record FROM events")}
    out = {}
    for i, rec in ev.items():
        out[ev_key(rec)] = ([], [s for s in (rec.get("obs_sites") or []) if s.get("result") == "miss"
                                 and s.get("lat") is not None and s.get("lon") is not None])
    pairs = {}
    for r in con.execute("SELECT event_id, label, utc, data FROM contacts WHERE label IN ('D', 'R')"):
        d = json.loads(r["data"])
        k = (r["event_id"], d.get("observer"), d.get("lon"), d.get("lat"))
        pairs.setdefault(k, {})[r["label"]] = (r["utc"], d)
    con.close()
    for (i, who, lon, lat), p in pairs.items():
        if "D" in p and "R" in p and lon is not None and lat is not None and i in ev:
            (ud, dd), (ur, dr) = p["D"], p["R"]
            out[ev_key(ev[i])][0].append(dict(observer=who, place=dd.get("place", ""), lon=lon, lat=lat,
                                              alt_m=dd.get("alt_m") or 0.0, datum=dd.get("datum", "_"),
                                              method=dd.get("method", ""), d_utc=ud, r_utc=ur,
                                              d_acc=dd.get("acc_s"), r_acc=dr.get("acc_s"), d_pe=dd.get("pe_s") or 0.0,
                                              r_pe=dr.get("pe_s") or 0.0, include=dd.get("include", "_") + dr.get("include", "_"),
                                              time_adj_s=dd.get("time_adj_s")))
    return out


# Math: OB.1, OB.2, LT.1, FP.1, FP.2 (slides OB, LT, FP): the shadow axis seen from the site (spkcpo 'CN').
def site_solve(spice, target, z, lon, lat, alt_m, t_guess, span_s):
    """(t_ca, d_km, v_kms, p0, w): the closest approach of the shadow axis to the site (geodetic WGS84 lon/lat deg,
    alt_m above the ellipsoid) within t_guess +- span_s, the distance there (fundamental plane), the shadow's speed
    relative to the site, and the axis minus the site at t_ca (p0, km, x east / y north) and its rate (w, km/s); the
    asteroid as the site sees it (light time from the site), as the search's solver."""
    from scipy.optimize import minimize_scalar
    from pysyzygos import earth
    from pysyzygos.paths import plane_basis
    x_ax, y_ax, _ = plane_basis(z)
    site = spice.georec(math.radians(lon), math.radians(lat), alt_m / 1000.0, earth.A_KM, earth.F)
    def xy(t):
        v = np.asarray(spice.spkcpo(target, t, "J2000", "OBSERVER", "CN", site, "EARTH", "ITRF93")[0][:3])
        return np.array([v @ x_ax, v @ y_ax])
    r = minimize_scalar(lambda dt: float(np.hypot(*xy(t_guess + dt))), bounds=(-span_s, span_s), method="bounded",
                        options={"xatol": 1e-4, "maxiter": 500})
    t = t_guess + float(r.x)
    w = xy(t + 0.5) - xy(t - 0.5)
    return t, float(r.fun), float(np.hypot(*w)), xy(t), w


def best_size(rec):
    """(a, b, pa_deg, text): the best size of the asteroid known for this event: the ellipse fitted to the chords
    (when its axes were fitted, not assumed, and the fit gives a size), else the good shape-model fits' diameter,
    else None."""
    q = rec.get("fit_quality")
    if rec.get("fit_major_km") and rec.get("fit_minor_km") and not rec.get("fit_assumed_size") and q in (2, 3, 4, 6):
        a, b = rec["fit_major_km"] / 2.0, rec["fit_minor_km"] / 2.0
        return a, b, float(rec.get("fit_pa_deg") or 0.0), f"fitted ellipse {2 * a:.1f} x {2 * b:.1f} km"
    if rec.get("shape_dia_km"):
        r = rec["shape_dia_km"] / 2.0
        return r, r, 0.0, f"shape models {2 * r:.1f} km"
    return None


# The chord of the site's line through the ellipse (axes a, b, major axis at PA from north through east).
def ellipse_chord(p0, w, a, b, pa_deg):
    """(duration_s, mid_s): the site's track relative to the asteroid, s(t) = -(p0 + w t), through the ellipse
    centred on the predicted shadow axis: how long it is inside and the middle of that time relative to t_ca."""
    pa = math.radians(pa_deg)
    e1, e2 = np.array([math.sin(pa), math.cos(pa)]), np.array([math.cos(pa), -math.sin(pa)])
    u1, u2, w1, w2 = p0 @ e1, p0 @ e2, w @ e1, w @ e2
    A = w1 * w1 / (a * a) + w2 * w2 / (b * b)
    B = 2.0 * (u1 * w1 / (a * a) + u2 * w2 / (b * b))
    C = u1 * u1 / (a * a) + u2 * u2 / (b * b) - 1.0
    disc = B * B - 4.0 * A * C
    return (math.sqrt(disc) / A if disc > 0 else 0.0), -B / (2.0 * A)


def chord_checks(spice, target, z, chords, misses, r_km, t_ref, rec=None):
    """Per chord: observed mid-time (D and R less the personal equations) minus the predicted closest approach at
    that site (s); the predicted distance from the centre line (km) and chord duration for the archive's diameter;
    per miss: the predicted distance (km). Returns (chord results, miss results)."""
    from pysyzygos import geoid
    out, out_m = [], []
    best = best_size(rec or {})
    for c in chords:
        try:
            td = spice.str2et(c["d_utc"]) - c["d_pe"]
            tr = spice.str2et(c["r_utc"]) - c["r_pe"]
            if not 0.0 < tr - td < 3600.0:
                continue
            h = c["alt_m"] + (geoid.height(c["lat"], c["lon"]) if c["datum"] in DATUM_WGS84 else 0.0)
            t, d, v, p0, w = site_solve(spice, target, z, c["lon"], c["lat"], h, (td + tr) / 2.0, 300.0)
            dur_pred = 2.0 * math.sqrt(r_km * r_km - d * d) / v if r_km and d < r_km else 0.0
            x = dict(observer=c["observer"], place=c["place"], lat=round(c["lat"], 5), lon=round(c["lon"], 5),
                     datum=c["datum"], method=c["method"], include=c["include"],
                     dt_mid_s=round((td + tr) / 2.0 - t, 4), dist_km=round(d, 3),
                     dur_obs_s=round(tr - td, 3), dur_pred_s=round(dur_pred, 3),
                     acc_s=max(c["d_acc"] or 0.0, c["r_acc"] or 0.0), time_adj_s=c["time_adj_s"])
            if best:                                              # the best size: the fitted ellipse on our center
                dur_b, mid_b = ellipse_chord(p0, w, *best[:3])
                x.update(dur_pred_best_s=round(dur_b, 3), dt_mid_best_s=round((td + tr) / 2.0 - (t + mid_b), 4))
            out.append(x)
        except Exception as ex:
            out.append(dict(observer=c["observer"], note=f"{type(ex).__name__}"))
    for m in misses:
        try:
            h = (m.get("alt_m") or 0.0) + (geoid.height(m["lat"], m["lon"]) if (m.get("datum") or "_") in DATUM_WGS84 else 0.0)
            t, d, v, p0, w = site_solve(spice, target, z, m["lon"], m["lat"], h, t_ref, 1200.0)
            y = dict(observer=m.get("observer", ""), dist_km=round(d, 3), outside_km=round(d - (r_km or 0.0), 3))
            if best:                                              # a miss inside the best-size ellipse: a conflict
                y["inside_best"] = bool(ellipse_chord(p0, w, *best[:3])[0] > 0.0)
            out_m.append(y)
        except Exception:
            continue
    return out, out_m


def compare(rec, pr):
    """Observed minus predicted (km, s) in the track's frame."""
    dx, dy = rec["geo_x_km"] - pr["x"], rec["geo_y_km"] - pr["y"]
    v = math.hypot(pr["vx"], pr["vy"])
    ux, uy = pr["vx"] / v, pr["vy"] / v
    along, across = dx * ux + dy * uy, -dx * uy + dy * ux
    mas = math.degrees(math.hypot(dx, dy) / pr["dist_km"]) * 3.6e6
    return dict(chk_dx_km=round(dx, 3), chk_dy_km=round(dy, 3), chk_across_km=round(across, 3),
                chk_along_km=round(along, 3), chk_along_s=round(along / v, 4), chk_mas=round(mas, 3),
                chk_speed_kms=round(v, 4))


def find_star(local, rec, cache):
    """The Gaia DR3 row (DataFrame of one row) of the event's star from the local catalog, or None."""
    sid = str(rec.get("star") or "")
    if not sid or rec.get("star_gaia_version") not in (3, "3"):
        return None
    if sid in cache:
        return cache[sid]
    row = None
    try:
        near = local.cone(float(rec["star_ra"]), float(rec["star_dec"]), 30.0 / 3600.0)
        if near is not None and len(near):
            m = near[near["source_id"].astype("int64") == int(sid)]
            row = m.iloc[[0]].reset_index(drop=True) if len(m) else None
    except Exception:
        row = None
    cache[sid] = row
    return row


# ----------------------------------------------------------------------------------------------- the run
def run(since=None, asteroids=None, limit=None, workers=2, fresh=False, log=print):
    import spiceypy as spice
    from pysyzygos import config, gaia_local, kernels, screen
    _, dbp, csvp = observed.paths()
    if not os.path.isfile(dbp):
        raise SystemExit("no observed events: download the 'observations' dataset (System tab, Occult data)")
    res_path, md_path = files()
    if fresh and os.path.isfile(res_path):
        os.remove(res_path)
    done = {k: x for k, x in load_results(res_path).items()      # failures (orbit, SPICE) are tried again, and
            if not (x.get("chk_note") or "").startswith(("Spice", "no orbit"))   # results before the site check
            and (x.get("chk_v") == 2 or x.get("chk_across_km") is None)}
    con = db.connect(dbp)
    recs = db.events(con, lst=observed.LIST)
    con.close()
    todo = {}
    for r in recs:
        if r.get("geo_x_km") is None or r.get("geo_y_km") is None or not str(r.get("target_id", "")).isdigit():
            continue
        if since and r["best_utc"][:4] < str(since):
            continue
        if asteroids and r["target_id"] not in asteroids:
            continue
        if ev_key(r) in done:
            continue
        todo.setdefault(r["target_id"], []).append(r)
    order = sorted(todo, key=lambda t: max(e["best_utc"] for e in todo[t]), reverse=True)   # newest events first
    if limit:
        order = order[:int(limit)]
    n_ev = sum(len(todo[t]) for t in order)
    log(f"obs-check: {n_ev} events of {len(order)} asteroids to check ({len(done)} done before); "
        f"orbits from JPL Horizons, {workers} at a time")
    if not order:
        return summarize(log=log)
    screen.load_kernels(spice)
    chords = load_chords(dbp)                                            # the observers' sites and times
    local = gaia_local.LocalGaia(config.gaia_local_dir)
    log(f"obs-check: stars from {config.gaia_local_dir} (G <= {local.gmax})")
    import signal

    def _stop(*_):                                                      # GUI Stop (SIGTERM): as Ctrl-C
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, _stop)
    q, stop = queue.Queue(maxsize=6), threading.Event()

    def fetch(ts):
        for t in ts:
            if stop.is_set():
                return
            a, b = _span(todo[t])
            try:
                q.put((t, horizons_spk(t, a, b), None))
            except Exception as ex:
                q.put((t, None, f"{type(ex).__name__}: {str(ex)[:120]}"))
    chunks = [order[i::workers] for i in range(workers)]
    threads = [threading.Thread(target=fetch, args=(c,), daemon=True) for c in chunks]
    for th in threads:
        th.start()
    tmpdir = tempfile.mkdtemp(prefix="obscheck_")
    stars, n_done, n_ok, t0 = {}, 0, 0, time.time()
    try:
        with open(res_path, "a", encoding="utf-8") as out:
            for i in range(len(order)):
                t, blob, err = q.get()
                evs = todo[t]
                if blob is None:
                    for r in evs:
                        out.write(json.dumps(dict(key=ev_key(r), target_id=t, best_utc=r["best_utc"],
                                                  chk_note=f"no orbit: {err}")) + "\n")
                    n_done += len(evs)
                    continue
                fn = os.path.join(tmpdir, f"{t}.bsp")
                with open(fn, "wb") as f:
                    f.write(blob)
                spice.furnsh(fn)
                kernels.body_alias(spice, t, int(spice.spkobj(fn)[0]))
                for r in evs:
                    x = dict(key=ev_key(r), target_id=t, best_utc=r["best_utc"])
                    row = find_star(local, r, stars)
                    if row is None:
                        x["chk_note"] = ("star not in the local catalog" if r.get("star_gaia_version") in (3, "3")
                                         else "not a Gaia DR3 star")
                    else:
                        try:
                            et = spice.str2et(r["best_utc"])
                            pr = predict(spice, t, row, et)
                            x.update(compare(r, pr), chk_note="", chk_star_g=float(row["phot_g_mean_mag"].iloc[0]))
                            pos, mis = chord_checks(spice, t, pr["z"], *chords.get(ev_key(r), ([], [])),
                                                    r.get("r_km"), et, r)
                            good = [c["dt_mid_s"] for c in pos if "dt_mid_s" in c]   # all chords (Occult's flags not used)
                            bs = best_size(r)
                            x.update(chk_v=2, chk_size_best=bs[3] if bs else "", chk_chords=pos, chk_misses=mis,
                                     chk_chord_n=len(good),
                                     chk_site_dt_s=round(float(np.median(good)), 4) if good else None)
                            n_ok += 1
                        except Exception as ex:
                            msg = " ".join(str(ex).split())
                            x["chk_note"] = f"{type(ex).__name__}: {msg[msg.find('--') + 3:][:400] if '--' in msg else msg[:400]}"
                    out.write(json.dumps(x) + "\n")
                out.flush()
                spice.unload(fn)
                os.remove(fn)
                n_done += len(evs)
                if (i + 1) % 25 == 0 or i + 1 == len(order):
                    el = time.time() - t0
                    log(f"obs-check: {i + 1}/{len(order)} asteroids, {n_done}/{n_ev} events ({n_ok} compared), "
                        f"{el / 60:.1f} min, about {el / (i + 1) * (len(order) - i - 1) / 60:.0f} min to go", flush=True)
    except KeyboardInterrupt:
        log("obs-check: stopped; run again to continue")
    finally:
        stop.set()
        for f in os.listdir(tmpdir):
            os.remove(os.path.join(tmpdir, f))
        os.rmdir(tmpdir)
    return summarize(log=log)


def apply_to_db(results, log=print):
    """Write the chk_* fields into the observations database (and its CSV export); returns the count."""
    _, dbp, csvp = observed.paths()
    con = db.connect(dbp)
    n = 0
    for row in con.execute("SELECT id, record FROM events").fetchall():
        rec = json.loads(row["record"])
        x = results.get(ev_key(rec))
        if not x:
            continue
        rec.update({k: v for k, v in x.items() if k.startswith("chk_")})
        con.execute("UPDATE events SET record=? WHERE id=?", (db._json(rec), row["id"]))
        n += 1
    run_ = con.execute("SELECT id, summary FROM runs ORDER BY id DESC LIMIT 1").fetchone()
    if run_ and run_["summary"]:
        s = json.loads(run_["summary"])
        s.update(checked=time.strftime("%Y-%m-%d", time.gmtime()),
                 checked_n=sum(1 for x in results.values() if x.get("chk_across_km") is not None))
        con.execute("UPDATE runs SET summary=? WHERE id=?", (db._json(s), run_["id"]))
    con.commit()
    db.export(con, csvp, lst=observed.LIST)
    con.close()
    log(f"obs-check: {n} observed events updated in {dbp}")
    return n


def _stats(v):
    v = np.asarray([x for x in v if x is not None and math.isfinite(x)], float)
    if not len(v):
        return None
    return dict(n=len(v), median=float(np.median(v)), mad=float(1.4826 * np.median(np.abs(v - np.median(v)))),
                p68=float(np.percentile(np.abs(v), 68.27)), p95=float(np.percentile(np.abs(v), 95)))


def summarize(log=print):
    """obs_check.md from obs_check.jsonl (+ the observations database for the events' details); applies the results
    to the database. Returns the summary dict."""
    res_path, md_path = files()
    results = load_results(res_path)
    if not results:
        log("obs-check: no results yet")
        return {}
    apply_to_db(results, log)
    _, dbp, _ = observed.paths()
    con = db.connect(dbp)
    recs = {ev_key(r): r for r in db.events(con, lst=observed.LIST)}
    con.close()
    rows = [(recs.get(k, {}), x) for k, x in results.items() if x.get("chk_across_km") is not None]
    notes = {}
    for x in results.values():
        if x.get("chk_across_km") is None:
            n = (x.get("chk_note") or "?").split(":")[0]
            notes[n] = notes.get(n, 0) + 1
    L = ["# Observed occultations against PySyzygos predictions", "",
         f"PySyzygos {__version__}, {time.strftime('%Y-%m-%d %H:%M', time.gmtime())} UTC. Observed: the IOTA / Occult "
         f"archive (D. Herald), the centre of the asteroid fitted to the chords, in the fundamental plane through "
         f"the geocentre at the archive's reference time. Predicted: today's JPL Horizons orbit, Gaia DR3 star with the "
         f"search's corrections. Observed minus predicted, across the track (km) and along it (s).", "",
         f"**{len(rows)} events compared** of {len(results)} checked" + (
             "; not compared: " + ", ".join(f"{v} {k}" for k, v in sorted(notes.items(), key=lambda kv: -kv[1]))
             if notes else "") + ".", ""]

    def table(title, groups):
        out = [f"## {title}", "", "| Group | Events | Across: median, scatter (km) | |across| 68 % / 95 % (km) | "
               "Along: median, scatter (s) | |along| 68 % / 95 % (s) | |offset| 68 % (mas) |",
               "|---|---|---|---|---|---|---|"]
        for name, sel in groups:
            a, t, m = (_stats([x["chk_across_km"] for _, x in sel]), _stats([x["chk_along_s"] for _, x in sel]),
                       _stats([x["chk_mas"] for _, x in sel]))
            if not a:
                continue
            out.append(f"| {name} | {a['n']} | {a['median']:+.2f}, {a['mad']:.2f} | {a['p68']:.2f} / {a['p95']:.2f} | "
                       f"{t['median']:+.3f}, {t['mad']:.3f} | {t['p68']:.3f} / {t['p95']:.3f} | {m['p68']:.1f} |")
        return out + [""]
    # 1) the measured data: every positive chord at its site (observer's times and coordinates, nothing else)
    ch = [(r, x, c) for r, x in rows for c in (x.get("chk_chords") or []) if "dt_mid_s" in c]
    if ch:
        def ctable(title, groups):
            out = [f"## {title}", "", "| Group | Chords | Mid-time obs - pred: median, scatter (s) | |dt| 68 % / 95 % "
                   "(s) | Duration obs / pred, catalog size | Duration obs / pred, best size (chords) | Mid-time with "
                   "best size: 68 % (s) |", "|---|---|---|---|---|---|---|"]
            for name, sel in groups:
                a = _stats([c["dt_mid_s"] for _, _, c in sel])
                if not a:
                    continue
                q = [c["dur_obs_s"] / c["dur_pred_s"] for _, _, c in sel if c.get("dur_pred_s")]
                qb = [c["dur_obs_s"] / c["dur_pred_best_s"] for _, _, c in sel if c.get("dur_pred_best_s")]
                mb = _stats([c["dt_mid_best_s"] for _, _, c in sel if "dt_mid_best_s" in c])
                out.append(f"| {name} | {a['n']} | {a['median']:+.3f}, {a['mad']:.3f} | {a['p68']:.3f} / {a['p95']:.3f} | "
                           + (f"{float(np.median(q)):.2f} ({len(q)})" if q else "") + " | "
                           + (f"{float(np.median(qb)):.2f}, scatter {1.4826 * float(np.median(np.abs(np.array(qb) - np.median(qb)))):.2f} ({len(qb)})" if qb else "")
                           + " | " + (f"{mb['p68']:.3f}" if mb else "") + " |")
            return out + [""]
        L += ["## At the observers' sites (the measured data)", "",
              "Each positive chord: the observer's measured disappearance and reappearance (less a visual observer's "
              "reported personal equation) at the observer's coordinates (WGS84; height above sea level + EGM96 "
              "geoid) against PySyzygos's closest approach of the shadow axis at that site (asteroid seen from the "
              "site, as the search). Mid-time = (D + R) / 2, independent of the asteroid's size. Nothing of Occult's "
              "solution is used; chords Occult excluded from its fit are included.", ""]
        cy = lambda r: int(str(r.get("best_utc", "0000"))[:4] or 0)
        L += ctable("Chord mid-times: all, and by method and timing", [
            ("all chords", ch),
            ("video, camera, photometer, drift scan (not visual)", [p for p in ch if p[2].get("method") != VISUAL]),
            ("visual", [p for p in ch if p[2].get("method") == VISUAL]),
            ("stated accuracy <= 0.05 s", [p for p in ch if (p[2].get("acc_s") or 9) <= 0.05]),
            ("excluded by Occult from its fit", [p for p in ch if "x" in (p[2].get("include") or "")]),
            ("datum not WGS84 / unspecified", [p for p in ch if p[2].get("datum") not in ("_", "")]),
            ("star with a double-star solution (Gaia: the pair's light centre)", [p for p in ch if p[0].get("star_double")]),
            ("video, star single (no double solution, RUWE < 1.4)", [p for p in ch if p[2].get("method") != VISUAL
                                                                     and not p[0].get("star_double")
                                                                     and not p[0].get("star_flag")])])
        L += ctable("Chord mid-times by year (not visual)", [
            (f"{y}-{y + 4}" if y < 2020 else str(y), [p for p in ch if p[2].get("method") != VISUAL and
                                                       (y <= cy(p[0]) <= y + 4 if y < 2020 else cy(p[0]) == y)])
            for y in (1975, 1980, 1985, 1990, 1995, 2000, 2005, 2010, 2015) + tuple(range(2020, 2027))])
        mis = [m for _, x in rows for m in (x.get("chk_misses") or [])]
        if mis:
            inside = sum(1 for m in mis if m["outside_km"] < 0)
            mb = [m for m in mis if "inside_best" in m]
            L += [f"Misses: {len(mis)} reported; PySyzygos predicts {len(mis) - inside} of them outside the shadow "
                  f"(archive diameter), {inside} inside (median {float(np.median([m['outside_km'] for m in mis])):+.1f} km "
                  f"from the edge)" + (f"; with the best size {sum(1 for m in mb if m['inside_best'])} of {len(mb)} "
                                      f"inside" if mb else "") + ".", "",
                  "Catalog size: the archive's nominal diameter (infrared surveys, as SBDB), a circle: the durations "
                  "test the size. Best size: the ellipse fitted to the event's chords (axes fitted, not assumed), else "
                  "the shape models: centred on PySyzygos's predicted shadow axis, so the durations test our position "
                  "across the track at each site (a few km off shows as too short / too long chords on the two sides).",
                  ""]
    yr = lambda r: int(str(r.get("best_utc", "0000"))[:4] or 0)
    L += ["## Against the archive's fitted centre (secondary)", "",
          "Occult's fit of the asteroid's centre to all chords of an event, in the fundamental plane through the "
          "geocentre: depends on its fit and assumed size.", ""]
    L += table("All events and by quality of the fit", [("all", rows)] + [
        (observed.FIT_QUALITY.get(q, str(q)), [p for p in rows if p[0].get("fit_quality") == q]) for q in range(7)])
    L += table("By year", [(f"{y}-{y + 4}" if y < 2020 else str(y),
                            [p for p in rows if (y <= yr(p[0]) <= y + 4 if y < 2020 else yr(p[0]) == y)])
                           for y in (1975, 1980, 1985, 1990, 1995, 2000, 2005, 2010, 2015) + tuple(range(2020, 2027))])
    L += table("By number of positive chords", [
        ("1", [p for p in rows if (p[0].get("n_positive") or 0) == 1]),
        ("2-3", [p for p in rows if 2 <= (p[0].get("n_positive") or 0) <= 3]),
        ("4-9", [p for p in rows if 4 <= (p[0].get("n_positive") or 0) <= 9]),
        ("10+", [p for p in rows if (p[0].get("n_positive") or 0) >= 10])])
    L += table("By the star", [
        ("RUWE < 1.4, no flags", [p for p in rows if not p[0].get("star_flag")]),
        ("flagged (RUWE, duplicated, no pm)", [p for p in rows if p[0].get("star_flag")]),
        ("G < 10", [p for p in rows if (p[1].get("chk_star_g") or 99) < 10]),
        ("G 10-13", [p for p in rows if 10 <= (p[1].get("chk_star_g") or 99) < 13]),
        ("G >= 13", [p for p in rows if (p[1].get("chk_star_g") or 0) >= 13])])
    big = sorted(rows, key=lambda p: -abs(p[1]["chk_across_km"]) / max(p[0].get("r_km") or 1.0, 0.5))[:30]
    L += ["## Largest across-track differences (in asteroid radii)", "",
          "| Event (UT) | Asteroid | Star G | Fit | Chords | Across (km) | Along (s) | Radius (km) | Star |",
          "|---|---|---|---|---|---|---|---|---|"]
    for r, x in big:
        L.append(f"| {str(r.get('best_utc', ''))[:19]} | {r.get('target_name', x['target_id'])} | "
                 f"{x.get('chk_star_g', 0):.2f} | {r.get('fit_quality_text', '')} | {r.get('n_positive', '')} | "
                 f"{x['chk_across_km']:+.1f} | {x['chk_along_s']:+.2f} | {r.get('r_km') or 0:.1f} | "
                 f"{r.get('star_flag') or ''} |")
    L += ["", "Scatter: 1.4826 x the median absolute deviation (a robust standard deviation). Along-track times "
          "also hold the asteroid's own orbit error along its motion; across-track the star's position error "
          "counts in full.", ""]
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    a = _stats([x["chk_across_km"] for _, x in rows])
    t = _stats([x["chk_along_s"] for _, x in rows])
    s = _stats([c["dt_mid_s"] for _, x in rows for c in (x.get("chk_chords") or []) if "dt_mid_s" in c])
    if s:
        log(f"obs-check: {s['n']} chords at their sites: mid-time obs - pred median {s['median']:+.3f} s, 68 % within "
            f"{s['p68']:.3f} s")
    log(f"obs-check: {len(rows)} events compared; across median {a['median']:+.2f} km, 68 % within {a['p68']:.2f} km; "
        f"along median {t['median']:+.3f} s, 68 % within {t['p68']:.3f} s -> {md_path}")
    return dict(n=len(rows), across=a, along=t)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="pysyzygos obs-check", description=__doc__.splitlines()[0])
    ap.add_argument("--version", action="version", version=f"PySyzygos {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="compare (resumes; newest events first)")
    r.add_argument("--since", type=int, help="only events from this year on")
    r.add_argument("--asteroids", help="only these asteroid numbers (comma separated)")
    r.add_argument("--limit", type=int, help="at most this many asteroids in this run")
    r.add_argument("--workers", type=int, default=2, help="Horizons downloads at a time (default 2; Horizons answers "
                                                            "503 to more)")
    r.add_argument("--fresh", action="store_true", help="discard earlier results")
    sub.add_parser("report", help="the summary (obs_check.md) from the results so far")
    a = ap.parse_args(argv)
    if a.cmd == "run":
        run(a.since, set(a.asteroids.split(",")) if a.asteroids else None, a.limit, max(1, a.workers), a.fresh,
            log=lambda *x, **k: print(*x, flush=True))
    else:
        summarize()
    return 0


if __name__ == "__main__":
    sys.exit(main())
