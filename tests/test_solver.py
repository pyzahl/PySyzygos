import _testtmp  # noqa: F401  (temporary files of this run in one folder, removed at exit)
import os, types, numpy as np
from scipy.optimize import minimize_scalar
# star_test from pysyzygos.py (not importable: kernel setup at import), run against a stand-in closest approach
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src', 'pysyzygos', 'search.py')).read()
func = src[src.index("def star_test ("):src.index("def screen_stars(")]

ET0 = 8.45e8                                   # real ephemeris times are ~8.4e8 s: the bounded solver's relative tolerance bites
T_TRUE, D_MIN, V = 2.3, 5.7, 12.0              # closest approach 2.3 s after the guess, 5.7 km miss, 12 km/s shadow speed
class Q:
    def __init__(s, v): s.value = v
    def __rmul__(s, v): return Q(v)
    def to(s, _): return s
units = types.SimpleNamespace(deg=Q(1), m=Q(1), rad=None, km=None)
ns = dict(np=np, minimize_scalar=minimize_scalar, u=units,
          EarthLocation=lambda lat, lon, height: types.SimpleNamespace(lat=lat, lon=lon, height=height),
          spice=types.SimpleNamespace(str2et=lambda s: ET0, et2utc=lambda et, f, p: "ET %.4f" % et),
          get_besselian_miss_distance=lambda et, sd, geo, t: float(np.hypot(D_MIN, V*(et - ET0 - T_TRUE))),
          observable=lambda et, sd, geo: (True, 40.0, -20.0), get_asteroid_name=lambda t: "Test")
exec(func, ns)
for span in (1200.0, 4200.0, 4*3600.0):
    res = ns['star_test'](center_time_utc="guess", time_span=span, asteroid_id="X", r_asteroid_km=10.0, r_search_km=200.0)
    dt = res['best_et'] - (ET0 + T_TRUE)
    print(f"span {span:7.0f} s: time error {dt*1e3:8.3f} ms, miss {res['min_distance']:.6f} km (true {D_MIN})")
    assert abs(dt) < 0.01 and abs(res['min_distance'] - D_MIN) < 1e-3, "solver did not converge to the closest approach"
print("SOLVER TEST PASSED")
