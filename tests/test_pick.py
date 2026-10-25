import os, sys, json, math, time, types, tempfile, numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
from pysyzygos import pick as P, screen as SC
from pysyzygos import offline as _offline
_offline.use_dir(tempfile.mkdtemp())          # never the data folder's real offline copies

# ---------- 1. OWC General Observability Criterion: StarMag < 5 log10(ap_cm) + 2.5 log10(dur/frames) + 8.5 + adj
opt = dict(aperture=25.0, frames=4, mag_adjust=0.0)
assert abs(SC.owc_limit(4.0, opt) - (5 * math.log10(25) + 8.5)) < 1e-12              # dur/frames = 1 s
assert abs(SC.owc_limit(1.0, dict(opt, aperture=50.0)) - SC.owc_limit(1.0, opt) - 5 * math.log10(2)) < 1e-12
assert abs(SC.owc_limit(1.0, dict(opt, mag_adjust=0.7)) - SC.owc_limit(1.0, opt) - 0.7) < 1e-12
assert abs(SC.owc_limit(2.0, opt) - SC.owc_limit(1.0, opt) - 2.5 * math.log10(2)) < 1e-12
# every OWC reference event (G, max duration) passes at 25 cm / 4 frames; with the aperture in inches several would not
ref = [(5.61, 0.51), (8.10, 0.95), (10.42, 0.86), (12.08, 1.10), (12.11, 0.54), (12.28, 0.48), (12.78, 0.51),
       (12.90, 0.84), (12.97, 0.74), (13.13, 1.83), (13.37, 2.07), (14.06, 4.33), (14.09, 1.55), (14.20, 2.34)]
assert all(g < SC.owc_limit(d, opt) for g, d in ref)
assert sum(g < SC.owc_limit(d, dict(opt, aperture=25 / 2.54)) for g, d in ref) < len(ref)
# extinction: none when off, none at the zenith, ~k at 30 deg (airmass ~2), grows towards the horizon
assert SC.extinction_loss(20.0, opt) == 0.0
k = dict(opt, extinction=0.2)
assert abs(SC.extinction_loss(90.0, k)) < 1e-3 and abs(SC.extinction_loss(30.0, k) - 0.2) < 0.01
assert SC.extinction_loss(10.0, k) > SC.extinction_loss(30.0, k) > SC.extinction_loss(60.0, k)
print("OWC limit 25 cm, 4 frames: 0.5 s event ->", round(float(SC.owc_limit(0.5, opt)), 2), " 2 s ->",
      round(float(SC.owc_limit(2.0, opt)), 2), "; extinction 0.2 at 15 deg:", round(float(SC.extinction_loss(15.0, k)), 2))

# ---------- 2. asteroid table: sizes like pysyzygos.get_asteroid_size, bad orbits skipped, H limit
F = P.SBDB_FIELDS
def row(**kw):
    d = dict(spkid=20000001, full_name=" 1 Test", H="10", G=None, diameter=None, diameter_sigma=None, extent=None,
             albedo=None, a="2.5", e="0.1", i="5", om="10", w="20", ma="30", epoch="2461200.5", condition_code="0",
             neo="N", pha="N", sats=0, **{"class": "MBA"}); d.update(kw); return [d[f] for f in F]
data = [row(), row(spkid=20000002, diameter="100", diameter_sigma="2"), row(spkid=20000003, diameter="50"),
        row(spkid=20000004, e="1.2"), row(spkid=20000005, H=None), row(spkid=20000006, H="18.0")]
rows = P.build_rows(F, data, 17.0)
assert [r["number"] for r in rows] == [1, 2, 3], [r["number"] for r in rows]
r1, r2, r3 = rows
Dp = lambda p, H: 1329.0 / math.sqrt(p) * 10 ** (-H / 5)
assert r1["D_est"] and abs(r1["D_km"] - Dp(0.14, 10)) < 1e-9 and abs(r1["D_max_km"] - Dp(0.05, 10)) < 1e-9 and r1["G"] == 0.15
assert not r2["D_est"] and r2["D_km"] == 100 and r2["D_max_km"] == 106 and abs(r3["D_max_km"] - 50 * 1.45) < 1e-9
assert len(P.build_rows(F, data, None)) == 4                       # --all keeps H 18, still skips the bad ones

# ---------- 3. SBDB bulk cache: reused only if full precision, all fields, covering hmax and fresh
calls = []
class R:
    def __init__(s, b): s.b = b
    def __enter__(s): return s
    def __exit__(s, *a): pass
    def read(s): return json.dumps(s.b).encode()
def urlopen(url, timeout, context=None):                   # as urllib.request.urlopen (net.py passes context)
    calls.append(url); return R(dict(fields=F, data=data))
_j = json
P.urllib.request.urlopen = urlopen
cache = os.path.join(tempfile.mkdtemp(), "bulk.json")
P.fetch_sbdb(17.0, cache, 1e9); assert len(calls) == 1 and "full-prec=true" in calls[0] and "H%7CLT%7C17" in calls[0]
P.fetch_sbdb(17.0, cache, 1e9); assert len(calls) == 1, "cache not reused"
P.fetch_sbdb(16.0, cache, 1e9); assert len(calls) == 1, "a cache for H < 17 covers H < 16"
P.fetch_sbdb(None, cache, 1e9); assert len(calls) == 2 and "sb-cdata" not in calls[1], "--all needs a new download"
P.fetch_sbdb(17.0, cache, 1e9); assert len(calls) == 2, "the --all cache covers H < 17"
P.fetch_sbdb(17.0, cache, 0.0); assert len(calls) == 3, "expired cache not refreshed"
b = _j.load(open(cache)); b["full_prec"] = False; _j.dump(b, open(cache, "w"))
P.fetch_sbdb(17.0, cache, 1e9); assert len(calls) == 4, "an old rounded-elements cache must be replaced"
assert not [f for f in os.listdir(os.path.dirname(cache)) if f.endswith(".tmp")]

# ---------- 4. screen helpers: cubic interpolation and the site solver on a straight shadow track
ets = np.arange(0.0, 6000.0, 600.0)
g = np.stack([ets * 7.0 - 20000.0, 3.0e8 + 0 * ets, 50.0 + ets * 0.002], 1)        # linear motion: exact for cubics
tq = np.array([601.0, 2999.5, 4200.0]); gi = SC._interp(g, ets, tq)
assert np.allclose(gi, np.stack([tq * 7.0 - 20000.0, 3.0e8 + 0 * tq, 50.0 + tq * 0.002], 1))
class FakeSite:                                                                         # observer fixed at the origin
    def at(self, et):
        et = np.atleast_1d(et); return np.zeros((len(et), 3)), np.tile([0.0, 0.0, 1.0], (len(et), 1))
sdir = np.array([[0.0, 1.0, 0.0]])                                                       # star along +y: plane is x, z
T_TRUE, B = 2000.0, 37.0                                                                 # closest approach time, miss km
track = lambda t: np.stack([7.0 * (np.atleast_1d(t) - T_TRUE), 3.0e8 + 0 * np.atleast_1d(t), B + 0 * np.atleast_1d(t)], 1)
t, miss, off, v = SC.solve_site(None, FakeSite(), track, sdir, np.array([2300.0]), np.array([900.0]))
print("site solver: t", round(float(t[0]), 4), "miss", round(float(miss[0]), 4), "speed", round(float(v[0]), 4))
assert abs(t[0] - T_TRUE) < 1e-3 and abs(miss[0] - B) < 1e-6 and abs(v[0] - 7.0) < 1e-9
t, miss, _, _ = SC.solve_site(None, FakeSite(), track, sdir, np.array([2300.0]), np.array([100.0]))
assert abs(t[0] - 2200.0) < 1e-9, "the solution must stay inside the bracket"
# worker processes must start with "spawn": with "fork" (Linux default before Python 3.14) they share the parent's open
# SPICE kernel files and their read position, and parallel reads of de440.bsp collide (regression 2026-10-05)
import inspect
from pysyzygos import pick as _pk
assert inspect.signature(_pk.run_screen).parameters["mp_start"].default == "spawn"
assert 'mp_context=multiprocessing.get_context(mp_start)' in inspect.getsource(_pk.run_screen)
print("PICK TESTS PASSED")
