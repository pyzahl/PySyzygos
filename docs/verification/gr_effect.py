"""The Sun's relativistic term (1PN, slide AS.3) in the pick's own orbits: position difference with / without it, per
orbit class. VERIFICATION.md section 4, "Orbits of the pick". Run from the data folder (de440.bsp, a leap-second
kernel, offline/sbdb_list.json.gz or the SBDB cache), e.g.  python docs/verification/gr_effect.py [start] [days]"""
import collections, gzip, json, os, sys
import numpy as np
import spiceypy as spice
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))
from pysyzygos import orbits as O, pick as P, kernels as K

N_PER_CLASS = 300
ORDER = ["q<0.3", "IEO", "ATE", "APO", "AMO", "MCA", "IMB", "MBA", "OMB", "TJN", "CEN", "TNO", "AST"]


def sbdb_rows():
    for path in ("offline/sbdb_list.json.gz", "sbdb_cache.json"):
        if os.path.isfile(path):
            blob = json.load(gzip.open(path) if path.endswith(".gz") else open(path))
            return P.build_rows(blob["fields"], blob["data"], None)
    sys.exit("no SBDB list here (offline/sbdb_list.json.gz): run a pick first")


def positions(sel, et, gr):
    """Geocentric astrometric positions (km) from orbits.propagate, with or without the 1PN term."""
    el = {k: np.array([r[k] for r in sel]) for k in ("a", "e", "i", "om", "w", "ma", "epoch")}
    accel = O._accel
    if not gr:
        O._accel = lambda r, bp, gm, v=None: accel(r, bp, gm)
    try:
        R, V = O.propagate(spice, el, et)
    finally:
        O._accel = accel
    return O.astrometric(spice, R, V, et)


def main():
    start = sys.argv[1] if len(sys.argv) > 1 else "2026-10-30"
    days = float(sys.argv[2]) if len(sys.argv) > 2 else 120.0
    spice.furnsh(K.lsk_file("."))
    spice.furnsh("de440.bsp")
    et = spice.str2et(start + "T00:00:00") + np.arange(0, days + 1, 2.0) * 86400
    by = collections.defaultdict(list)
    for r in sbdb_rows():
        by[r["cls"]].append(r)
        if r["a"] * (1 - r["e"]) < 0.3:
            by["q<0.3"].append(r)                             # the extreme ones, whatever their class
    rng = np.random.default_rng(1)
    print(f"{start} + {days:g} d: largest |with - without 1PN| over the window, km (geocentric)")
    print(f"{'class':6} {'n':>5} {'median':>8} {'90%':>8} {'max':>8}   worst (q AU)")
    for cls in ORDER + sorted(set(by) - set(ORDER)):
        lst = by.get(cls, [])
        sel = [lst[i] for i in rng.choice(len(lst), min(len(lst), N_PER_CLASS), replace=False)] if lst else []
        sel = [r for r in sel if O.jd_to_et(r["epoch"]) < et[0]]     # propagate needs the epoch before the window
        if not sel:
            continue
        d = np.linalg.norm(positions(sel, et, True) - positions(sel, et, False), axis=-1).max(1)
        w = int(np.argmax(d))
        print(f"{cls:6} {len(sel):5d} {np.median(d):8.2f} {np.percentile(d, 90):8.2f} {d.max():8.1f}   "
              f"{sel[w]['name'][:28]} (q {sel[w]['a'] * (1 - sel[w]['e']):.2f})")


if __name__ == "__main__":
    main()
