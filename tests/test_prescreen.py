"""Pre-screens (pysyzygos.prescreen): region boxes (also across the date line), the box around a site, the fit check
before a pick uses one, and the asteroid list of a window from the SQLite file."""
import sys, os, json, sqlite3, tempfile, time
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
from pysyzygos import prescreen as PS

box = PS.region_box(35, 60, -130, -60)
lat, lon = np.array([40.0, 40.0, 40.0, 30.0, 34.8]), np.array([-72.9, -50.0, -59.5, -100.0, -100.0])
assert PS.in_box(lat, lon, box, 0).tolist() == [True, False, False, False, False]
assert PS.in_box(lat, lon, box, 100).tolist() == [True, False, True, False, True], "the margin widens the box"
wrap = PS.region_box(-50, -30, 170, -170)                      # across the date line (New Zealand east)
assert PS.in_box(np.array([-40.0, -40.0, -40.0]), np.array([175.0, -175.0, 160.0]), wrap, 0).tolist() == [True, True, False]
b = PS.box_around(40.87, -72.86, 500)
assert abs((b["lat_max"] - b["lat_min"]) - 2 * 500 / 111.2) < 1e-6 and b["lon_min"] < -72.86 - 5.9 and b["lon_max"] > -72.86 + 5.9
try:
    PS.region_box(60, 35, 0, 10)
    raise AssertionError("lat_min > lat_max must be refused")
except ValueError:
    pass

# the fit check: window, region, limits at least as loose as the pick's
meta = dict(et0=0.0, et1=7 * 86400.0, start="2026-10-12", days=7, region=b, cam_limit=16.0, reach_km=200.0, min_drop=0.1,
            max_sun_alt=0.0, min_alt=0.0, hmax=17.0)
pick = dict(cam_limit=15.0, reach_km=100.0, min_drop=0.1, max_sun_alt=-6.0, min_alt=5.0, hmax=17.0)
assert PS.check(meta, 0.0, 3 * 86400.0, 40.87, -72.86, pick) == []
bad = PS.check(meta, 0.0, 9 * 86400.0, 52.0, 9.0, dict(pick, cam_limit=17.0, reach_km=250.0, min_drop=0.05, hmax=18.0))
assert len(bad) == 6 and any("window" in x for x in bad) and any("outside" in x for x in bad), bad
assert PS.contains(dict(region=None), -80.0, 10.0), "a global pre-screen contains every site"
glob_meta = dict(meta, region=None)                            # whole Earth: no reach limit, any pick reach fits
assert PS.check(glob_meta, 0.0, 3 * 86400.0, -80.0, 10.0, dict(pick, reach_km=300.0)) == []
assert PS.check(glob_meta, 0.0, 3 * 86400.0, -80.0, 10.0, dict(pick, reach_km=5000.0, cam_limit=17.0)) == \
    ["star limit 17 beyond the pre-screen's 16"]                # the other limits still count
assert "reach" not in PS.describe("x", dict(glob_meta, name="g", built="2026-10-21")) and \
    "reach 200 km" in PS.describe("x", dict(meta, name="r", built="2026-10-21"))

# the file: asteroids with events in the window
p = os.path.join(tempfile.mkdtemp(), "t.db")
con = sqlite3.connect(p)
con.executescript(PS.SCHEMA)
con.executemany("INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?,?)",
                [(30819, 1, 1000.0, 9.7, 17.0, 10.0, 40.0, -72.0, -20.0, 40.0),
                 (101716, 2, 5 * 86400.0, 11.5, 17.4, 50.0, 40.0, -72.0, -20.0, 40.0)])
con.executemany("INSERT INTO meta VALUES (?, ?)", [(k, json.dumps(v)) for k, v in meta.items()] + [("name", '"t"')])
con.commit(); con.close()
assert PS.numbers(p, 0.0, 86400.0) == {30819} and PS.numbers(p, 0.0, 7 * 86400.0) == {30819, 101716}
assert PS.numbers(p, 0.0, 7 * 86400.0, 11.0) == {30819}, "the pick's star limit drops asteroids with fainter stars only"
assert PS.numbers(p, 0.0, 7 * 86400.0, 11.5) == {30819, 101716}, "a star exactly at the limit is kept"
assert PS.read_meta(p)["reach_km"] == 200.0 and "lat 36.4" in PS.describe(p)
assert PS.counts(p) == (2, 2)

# one box around several sites: every site inside with its margin; across the date line the short way round
two = PS.box_around_all([(40.9, -72.9), (46.8, 9.6)], 300)
assert all(PS.in_box(np.array([la]), np.array([lo]), two, 299)[0] for la, lo in ((40.9, -72.9), (46.8, 9.6)))
assert two["lon_min"] < -72.9 and two["lon_max"] > 9.6 and two["lon_max"] < 20
pac = PS.box_around_all([(-41.3, 174.8), (21.3, -157.8)], 300)                 # Wellington, Honolulu
assert pac["lon_min"] > 170 and pac["lon_max"] < -150, pac
assert PS.in_box(np.array([0.0]), np.array([180.0]), pac, 0)[0] and not PS.in_box(np.array([0.0]), np.array([0.0]), pac, 0)[0]
ring = PS.box_around_all([(0, 0), (0, 120), (0, -120)], 300)                     # spread around the globe
assert all(PS.in_box(np.array([0.0]), np.array([x]), ring, 0)[0] for x in (0.0, 120.0, -120.0))

# auto choice for a pick: the newest fitting pre-screen; the others with their reasons
d = tempfile.mkdtemp()
def mk(name, built, **kw):
    q = os.path.join(d, name + ".db")
    con = sqlite3.connect(q)
    con.executescript(PS.SCHEMA)
    con.executemany("INSERT INTO meta VALUES (?, ?)", [(k, json.dumps(v)) for k, v in dict(meta, name=name, built=built, **kw).items()])
    con.commit(); con.close()
    return q
old_ = mk("old", "2026-09-01T00:00:00")
new_ = mk("new", "2026-10-01T00:00:00")
far = mk("far", "2026-10-05T00:00:00", region=PS.box_around(-33.9, 151.2, 300))
path, m, other = PS.best_fit(0.0, 86400.0, 40.87, -72.86, pick, d)
assert path == new_ and m["name"] == "new" and [os.path.basename(x[0]) for x in other] == ["far.db"], (path, other)
assert PS.best_fit(0.0, 30 * 86400.0, 40.87, -72.86, pick, d)[0] is None, "window not covered: no pre-screen"
assert abs(PS.age_days(dict(built=time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() - 3 * 86400)))) - 3) < 0.01
assert PS.parse_region("Europe") == PS.region_box(*PS.REGIONS["europe"])
assert PS.parse_region("35,60,-130,-60") == box
try:
    PS.parse_region("atlantis")
    raise AssertionError("unknown region name must be refused")
except ValueError:
    pass
print("PRESCREEN TESTS PASSED")
