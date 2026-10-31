"""orbits.propagate (the pick's and pre-screens' own orbits) against JPL Horizons' barycentric vectors of the same orbit
solution, from the element epoch on. VERIFICATION.md section 4, "Against Horizons over 300 days". Run from the data
folder (de440.bsp, a leap-second kernel; network), e.g.  python docs/verification/horizons_check.py 3200 [days ...]"""
import json, os, re, sys, urllib.parse
import numpy as np
import spiceypy as spice
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))
from pysyzygos import orbits as O, kernels as K, net, urls as U

target = sys.argv[1] if len(sys.argv) > 1 else "3200"
spice.furnsh(K.lsk_file(".")); spice.furnsh("de440.bsp")

js = json.load(net.urlopen(U.URL_JPL_SBDB_API + "?" + urllib.parse.urlencode({"sstr": target, "full-prec": "true"}), timeout=60))
orb = js["orbit"]; el0 = {e["name"]: float(e["value"]) for e in orb["elements"]}
epoch = float(orb["epoch"])
el = {k: np.array([el0[s]]) for k, s in (("a", "a"), ("e", "e"), ("i", "i"), ("om", "om"), ("w", "w"), ("ma", "ma"))}
el["epoch"] = np.array([epoch])
print(f"{js['object']['fullname']}: SBDB orbit JPL#{orb['orbit_id']} ({orb['soln_date']}), epoch JD {epoch} TDB, "
      f"q {el0['q']:.4f} AU, perihelion JD {el0['tp']:.3f}")

days = [float(x) for x in sys.argv[2:]] or [0, 30, 60, 90, 100, 120, 145, 150, 200, 250, 300]
jd = [epoch + d for d in days]
q = {"format": "json", "COMMAND": f"'{target};'" if target.isdigit() else f"'DES={target};'", "OBJ_DATA": "NO",
     "MAKE_EPHEM": "YES", "EPHEM_TYPE": "VECTORS", "CENTER": "'500@0'", "REF_PLANE": "FRAME", "REF_SYSTEM": "ICRF",
     "VEC_TABLE": "2", "VEC_CORR": "NONE", "OUT_UNITS": "AU-D", "TIME_TYPE": "TDB", "CSV_FORMAT": "YES",
     "TLIST": " ".join(f"'{x}'" for x in jd)}
res = json.load(net.urlopen(U.URL_JPL_HORIZONS_API + "?" + urllib.parse.urlencode(q), timeout=120))["result"]
sol = re.search(r"JPL#\s*\d+|soln ref\.?=\s*\S+", res)
print("Horizons:", sol.group(0) if sol else "?", "|", (re.search(r"Integrator.*|EPHEMERIS.*", res) or [""])[0].strip())
rows = res.split("$$SOE")[1].split("$$EOE")[0].strip().splitlines()
hz = np.array([[float(v) for v in r.split(",")[2:8]] for r in rows])      # X Y Z VX VY VZ (AU, AU/d)
hr, hv = hz[:, :3], hz[:, 3:]

et = O.jd_to_et(np.array(jd))
earth = np.array(spice.spkpos("EARTH", et, "J2000", "NONE", "0")[0]) / O.AU_KM
los = hr - earth; dist = np.linalg.norm(los, axis=1); los /= dist[:, None]

def run(**kw):
    acc = O._accel
    if kw.pop("nogr", False):
        O._accel = lambda r, bp, gm, v=None: acc(r, bp, gm)
    st = kw.pop("step", None)
    sf = O.step_for
    if st:
        O.step_for = lambda a, e, s=0.5: np.full(len(np.atleast_1d(a)), st)
    try:
        r, v = O.propagate(spice, el, et)
    finally:
        O._accel, O.step_for = acc, sf
    return r[0]

h0 = O.step_for(el["a"], el["e"])[0]
cases = [("as used (step %.4g d, 1PN)" % h0, {}), ("step 0.005 d, 1PN", {"step": 0.005}),
         ("as used, no 1PN", {"nogr": True}), ("step 0.5 d, no 1PN (before 1.5.1)", {"step": 0.5, "nogr": True})]
print(f"\nours - Horizons (barycentric, geometric), km; 'across' = perpendicular to the Earth->asteroid line "
      f"(what moves the shadow); mas = across / distance")
for name, kw in cases:
    d = (run(**kw) - hr) * O.AU_KM
    across = d - np.sum(d * los, 1)[:, None] * los
    print(f"\n{name}")
    print(f"{'days':>5} {'date (TDB)':>11} {'|d| km':>10} {'across km':>10} {'mas':>8}  {'Earth dist AU':>13}")
    for k, dd in enumerate(days):
        a = np.linalg.norm(across[k])
        print(f"{dd:5.0f} {spice.et2utc(et[k], 'ISOC', 0)[:10]:>11} {np.linalg.norm(d[k]):10.2f} {a:10.2f} "
              f"{a / (dist[k] * O.AU_KM) * 206264806:8.2f}  {dist[k]:13.3f}")
