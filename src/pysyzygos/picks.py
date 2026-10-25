"""picks.py - saved pick results per site and window, so a search can reuse them instead of picking again.

pick.py saves every run for a named site as a pair in picks/ (config picks_dir):
    picks/<site>__<start>_<days>d.py     importable target list (targets, target_names, pick_meta)
    picks/<site>__<start>_<days>d.csv    all events of that pick (as pick_events.csv)
A new pick of the same site and window replaces the pair. search.py (targets_source = "auto") uses the newest saved
pick of its site whose window covers the search window; without one it falls back to targets.py / the config list.

    pysyzygos picks list [site]       # saved picks
    pysyzygos picks import            # save the current targets.py + pick_events.csv under their site/window

Standard library only.
"""
from pysyzygos.version import __version__
import argparse, os, re, runpy, shutil, sys
from datetime import date, timedelta

DIR = "picks"
HEADER = re.compile(r"^# events (\d{4}-\d\d-\d\d) \+ ([\d.]+) d, site ([^,]+),", re.M)


def _safe(site):
    return re.sub(r"[^\w.-]+", "_", str(site)).strip("_") or "site"


def paths(site, start, days, folder=DIR):
    """(targets .py, events .csv) of the saved pick for this site and window."""
    stem = os.path.join(folder, f"{_safe(site)}__{str(start)[:10]}_{float(days):g}d")
    return stem + ".py", stem + ".csv"


# asteroid groups (pick --groups, the Pick tab's checkboxes) by JPL's orbit class; 'other' = every class not listed
# (Centaurs CEN, AST, ...). Numbered asteroids, 2026-10-25: main 870,924; trojan 10,633; marscross 9,196; neo 3,874;
# tno 1,049; other 234
GROUPS = {"main": ("MBA", "IMB", "OMB"), "trojan": ("TJN",), "marscross": ("MCA",), "neo": ("APO", "AMO", "ATE", "IEO"),
          "tno": ("TNO",)}
GROUP_NAMES = {"main": "Main belt", "trojan": "Jupiter Trojans", "marscross": "Mars-crossers", "neo": "NEO",
               "tno": "TNO", "other": "Everything else"}


def group_of(cls):
    """The group key of an SBDB orbit class ('other' for any class not in GROUPS)."""
    c = str(cls or "").strip().upper()
    return next((k for k, v in GROUPS.items() if c in v), "other")


def parse_groups(text):
    """Group keys from 'all' or 'main,neo,...' (also the GROUP_NAMES); ValueError for an unknown one."""
    t = str(text or "all").strip().lower()
    if t in ("", "all"):
        return set(GROUP_NAMES)
    out = set()
    for w in t.replace(" ", "").split(","):
        k = w if w in GROUP_NAMES else next((k for k, n in GROUP_NAMES.items() if n.lower().replace(" ", "") == w), None)
        if k is None:
            raise ValueError(f"unknown asteroid group {w!r}: {', '.join(GROUP_NAMES)}")
        out.add(k)
    return out


# ---------------------------------------------------------------- how many asteroids the pick settings screen
_COUNT = {}


def count_index(cache_file):
    """H, a and group code (index in GROUP_NAMES) of every asteroid in the pick's cached SBDB list (the JSON written
    by pick.fetch_sbdb), as numpy arrays, plus the list's H limit ('hmax', None if all) and its date; the same rows
    pick.build_rows keeps (H known, a > 0, e < 0.99). Read once per file version (~2 s for ~100 MB). None if missing."""
    import json
    import numpy as np
    try:
        st = os.stat(cache_file)
    except OSError:
        return None
    key = (cache_file, st.st_mtime)
    if key not in _COUNT:
        with open(cache_file) as f:
            blob = json.load(f)
        fi = {n: i for i, n in enumerate(blob["fields"])}
        num = lambda v: float(v) if v not in (None, "") else float("nan")
        H = np.array([num(r[fi["H"]]) for r in blob["data"]])
        a = np.array([num(r[fi["a"]]) for r in blob["data"]])
        e = np.array([num(r[fi["e"]]) for r in blob["data"]])
        keys = list(GROUP_NAMES)
        g = np.array([keys.index(group_of(r[fi["class"]])) if "class" in fi else keys.index("other")
                      for r in blob["data"]], np.int8)
        ok = np.isfinite(H) & (a > 0) & (e >= 0) & (e < 0.99)
        hmax = blob.get("hmax")
        _COUNT.clear()
        _COUNT[key] = dict(H=H[ok], a=a[ok], g=g[ok], hmax=None if not hmax or hmax >= 90 else float(hmax),
                           fetched=blob.get("fetched") or st.st_mtime)
    return _COUNT[key]


def count(idx, hmax=None, groups=None, a_min=None, a_max=None, a_exclude=False):
    """(n, n_h): asteroids the pick screens with these settings (before a pre-screen and the site/star test), and
    how many there are with the H limit alone. hmax None = all numbered (the list must hold them)."""
    import numpy as np
    m = np.ones(len(idx["H"]), bool) if hmax is None else idx["H"] < float(hmax)
    n_h = int(m.sum())
    if groups is not None and set(groups) != set(GROUP_NAMES):
        codes = [i for i, k in enumerate(GROUP_NAMES) if k in set(groups)]
        m &= np.isin(idx["g"], codes)
    if a_min is not None or a_max is not None:
        lo = float(a_min) if a_min is not None else 0.0
        hi = float(a_max) if a_max is not None else float("inf")
        inside = (idx["a"] >= lo) & (idx["a"] <= hi)
        m &= ~inside if a_exclude else inside
    return int(m.sum()), n_h


def _read(py):
    """dict(site, start, days, picked, targets, names, py, csv) of one saved pick, or None if unreadable."""
    try:
        mod = runpy.run_path(py)
    except Exception:
        return None
    meta = mod.get("pick_meta") or {}
    if not meta:                                          # targets.py style: window and site from the header line
        with open(py, encoding="utf-8") as f:
            head = f.read(4000)
        m, g = HEADER.search(head), re.search(r"^# generated by .* on (\d{4}-\d\d-\d\d \d\d:\d\d) UTC", head, re.M)
        if not m:
            return None
        meta = dict(start=m[1], days=float(m[2]), site=m[3].strip(), picked=g[1].replace(" ", "T") if g else "")
    return dict(site=str(meta["site"]), start=str(meta["start"])[:10], days=float(meta["days"]),
                picked=meta.get("picked") or "", lat=meta.get("lat"), lon=meta.get("lon"), targets=[str(t) for t in mod.get("targets", [])],
                names=mod.get("target_names", {}), py=py, csv=os.path.splitext(py)[0] + ".csv",
                groups=meta.get("groups"), a_min=meta.get("a_min"), a_max=meta.get("a_max"),
                a_exclude=bool(meta.get("a_exclude")))


def list_for(site=None, folder=DIR):
    """Saved picks (of one site, or all), newest window first."""
    if not os.path.isdir(folder):
        return []
    out = []
    for f in sorted(os.listdir(folder)):
        if f.endswith(".py") and "__" in f and (site is None or f.startswith(_safe(site) + "__")):
            p = _read(os.path.join(folder, f))
            if p and (site is None or p["site"] == str(site)):
                out.append(p)
    return sorted(out, key=lambda p: (p["start"], p["picked"]), reverse=True)


def end_of(p):
    return (date.fromisoformat(p["start"]) + timedelta(days=p["days"])).isoformat()


def moved(p, lat, lon, tol_deg=0.01):
    """True if the pick was made for another position of the site (by more than ~1 km)."""
    return (None not in (lat, lon, p.get("lat"), p.get("lon"))
            and max(abs(p["lat"] - lat), abs((p["lon"] - lon + 180) % 360 - 180)) > tol_deg)


def best_for(site, start, days, folder=DIR, lat=None, lon=None):
    """The saved pick of this site whose window covers start .. start+days (newest pick first), or None. With lat/lon,
    picks made before the site was moved are skipped."""
    s0 = str(start)[:10]
    s1 = (date.fromisoformat(s0) + timedelta(days=float(days))).isoformat()
    cover = [p for p in list_for(site, folder) if p["start"] <= s0 and end_of(p) >= s1 and not moved(p, lat, lon)]
    return max(cover, key=lambda p: (p["picked"], p["start"])) if cover else None


def describe(p):
    g = p.get("groups")
    only = (f", groups {', '.join(GROUP_NAMES.get(k, k) for k in GROUP_NAMES if k in g)}"
            if g and set(g) != set(GROUP_NAMES) else "")
    return (f"saved pick {p['site']} {p['start']} + {p['days']:g} d"
            + (f" (picked {p['picked'][:16].replace('T', ' ')} UTC)" if p["picked"] else "") + f", {len(p['targets'])} targets"
            + only + (f", {'not ' if p.get('a_exclude') else ''}a {p.get('a_min') if p.get('a_min') is not None else ''}-"
                      f"{p.get('a_max') if p.get('a_max') is not None else ''} AU"
                      if p.get("a_min") is not None or p.get("a_max") is not None else ""))


def import_current(targets_py="targets.py", events_csv="pick_events.csv", folder=DIR):
    """Save an existing targets.py (+ pick_events.csv) under the site and window named in its header."""
    p = _read(targets_py)
    if p is None:
        sys.exit(f"{targets_py}: no readable header line '# events <start> + <days> d, site <name>, ...'")
    os.makedirs(folder, exist_ok=True)
    py, csv = paths(p["site"], p["start"], p["days"], folder)
    shutil.copyfile(targets_py, py)
    if os.path.isfile(events_csv):
        shutil.copyfile(events_csv, csv)
    print(f"saved {py}" + (f" and {csv}" if os.path.isfile(events_csv) else ""))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=f"PySyzygos {__version__}")
    ap.add_argument("cmd", choices=["list", "import"])
    ap.add_argument("site", nargs="?")
    a = ap.parse_args()
    from pysyzygos.home import HOME
    os.chdir(HOME)
    if a.cmd == "import":
        import_current()
    else:
        for p in list_for(a.site):
            print(f"{p['site']:20s} {p['start']} + {p['days']:g} d  picked {p['picked'][:16] or '?':16s}  "
                  f"{len(p['targets']):3d} targets  {p['py']}")


if __name__ == "__main__":
    sys.exit(main())
