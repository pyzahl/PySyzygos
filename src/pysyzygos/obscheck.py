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
    p = np.asarray(spice.spkpos(target, et, "J2000", "CN", "399")[0])
    p1 = np.asarray(spice.spkpos(target, et + 1.0, "J2000", "CN", "399")[0])
    return dict(x=float(p @ x_ax), y=float(p @ y_ax), vx=float((p1 - p) @ x_ax), vy=float((p1 - p) @ y_ax),
                dist_km=float(np.linalg.norm(p)), star_corr=corr)


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
    done = load_results(res_path)
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
                            n_ok += 1
                        except Exception as ex:
                            x["chk_note"] = f"{type(ex).__name__}: {str(ex)[:100]}"
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
    yr = lambda r: int(str(r.get("best_utc", "0000"))[:4] or 0)
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
