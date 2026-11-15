"""sigmatable.py - each asteroid's path uncertainty outside the main belt, for the reach from the n-sigma limit.

The pick and the pre-screens have no orbit uncertainties. For the main belt (870,000 numbered asteroids) they allow
a fixed 200 mas (reach.PICK_SIGMA_MAS: the documented compromise, ABOUT 2.7.1). Outside it nothing may be cut:
NEOs, Mars-crossers, Trojans, Centaurs and TNOs (~26,000 numbered; JPL groups neo, marscross, trojan, tno, other)
get their own JPL Horizons 1 sigma (RSS / 3, km at the asteroid) from this table, queried once (2 at a time, ~2 h
for all; resumable) and refreshed when older than MAX_AGE_DAYS. Without an entry reach.py falls back to a generous
fixed allowance (NEAR_SIGMA_KM / FAR_SIGMA_KM).

    pysyzygos sigmas build [--groups neo,marscross,trojan,tno,other] [--workers 2] [--max-age 30]
    pysyzygos sigmas status

File: <data folder>/sigma_table.json {"entries": {number: [sigma1_km, "YYYY-MM-DD"]}, "updated": ...}, written
atomically every SAVE_EVERY answers (an interruption keeps what was asked). Derived data worth keeping: not in
cleanup's downloads.
"""
from pysyzygos.version import __version__
import argparse, json, os, sys, time

FILE = "sigma_table.json"
GROUPS = ("neo", "marscross", "trojan", "tno", "other")
MAX_AGE_DAYS = 30.0
SAVE_EVERY = 100


def path_of(folder=None):
    from pysyzygos.home import HOME
    return os.path.join(folder or HOME, FILE)


def load(path=None):
    """{number (int): sigma1_km} of the table ({} without one)."""
    try:
        with open(path or path_of(), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return {int(k): float(v[0]) for k, v in (data.get("entries") or {}).items() if v and v[0] is not None}


def _read(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return dict(entries={})


def _write(path, data):
    data["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
    data["version"] = __version__
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    os.replace(tmp, path)


def todo(numbers, data, today, max_age_days=MAX_AGE_DAYS):
    """The numbers without an entry, or with one older than max_age_days (dates 'YYYY-MM-DD')."""
    import datetime as dt
    t = dt.date.fromisoformat(today)
    out = []
    for n in numbers:
        e = (data.get("entries") or {}).get(str(n))
        if not e or (t - dt.date.fromisoformat(e[1])).days > max_age_days:
            out.append(n)
    return out


def build(numbers, path=None, workers=2, max_age_days=MAX_AGE_DAYS, query=None, say=print):
    """Ask Horizons (paths.path_error; query(number, utc) stands in for tests) for the numbers that need it; saves
    every SAVE_EVERY answers and at the end (also on Ctrl-C / SIGTERM). Returns (asked, answered)."""
    import datetime as dt, signal
    from concurrent.futures import ThreadPoolExecutor
    path = path or path_of()
    data = _read(path)
    data.setdefault("entries", {})
    today = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    utc = today + "T00:00:00"
    need = todo(numbers, data, today, max_age_days)
    if not need:
        say(f"sigma table: all {len(numbers)} entries younger than {max_age_days:g} days ({path})")
        return 0, 0
    if query is None:
        from pysyzygos import paths

        def query(n, t):
            pe = paths.path_error(str(n), t)
            return pe["sigma3_km"] / 3.0 if pe and pe.get("sigma3_km") else None
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))   # GUI Stop: save, end
    say(f"sigma table: asking JPL Horizons for {len(need)} asteroids, {workers} at a time ...")
    t0, got, done = time.time(), 0, 0
    try:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for n, s in zip(need, ex.map(lambda n: query(n, utc), need)):
                done += 1
                if s is not None:
                    data["entries"][str(n)] = [round(float(s), 3), today]
                    got += 1
                if done % SAVE_EVERY == 0:
                    _write(path, data)
                    eta = (time.time() - t0) / done * (len(need) - done)
                    say(f"  {done}/{len(need)}, {got} with a sigma, ETA {eta / 60:.0f} min")
    except KeyboardInterrupt:
        say("sigma table: interrupted, saving what was asked")
    finally:
        _write(path, data)
    say(f"sigma table: {got} of {done} answered in {time.time() - t0:.0f} s -> {path}")
    return done, got


def numbers_of(groups=GROUPS):
    """The numbered asteroids of these JPL groups (the pick's SBDB list, cached)."""
    import tempfile
    from pysyzygos import pick
    try:
        from pysyzygos import config as C
        cache = os.path.join(C.cache_path, "PySyzygos_sbdb_cache.json")
    except Exception:
        cache = os.path.join(tempfile.gettempdir(), "PySyzygos_sbdb_cache.json")
    fields, data, _ = pick.fetch_sbdb(None, cache)
    return [int(r["number"]) for r in pick.build_rows(fields, data, None) if r.get("group") in set(groups)]


def main(argv=None):
    from pysyzygos.__main__ import safe_console
    safe_console()
    ap = argparse.ArgumentParser(prog="pysyzygos sigmas", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=f"PySyzygos {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="query the missing and old entries")
    b.add_argument("--groups", default=",".join(GROUPS), help="JPL groups (default: all outside the main belt)")
    b.add_argument("--workers", type=int, default=2, help="Horizons queries at once (3 gave many HTTP 503)")
    b.add_argument("--max-age", type=float, default=MAX_AGE_DAYS, help="days before an entry is asked again")
    sub.add_parser("status", help="entries, age")
    a = ap.parse_args(argv)
    if a.cmd == "build":
        nums = numbers_of([g.strip() for g in a.groups.split(",") if g.strip()])
        build(nums, workers=a.workers, max_age_days=a.max_age)
        return 0
    data = _read(path_of())
    ent = data.get("entries") or {}
    dates = sorted(v[1] for v in ent.values())
    print(f"{path_of()}: {len(ent)} entries" + (f", {dates[0]} .. {dates[-1]}" if dates else "")
          + (f", updated {data.get('updated')}" if data.get("updated") else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
