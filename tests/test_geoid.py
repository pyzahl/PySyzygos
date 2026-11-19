"""geoid.py and sitesfile.py: EGM96 values, the elevation reference, sites.py round trip, and the config loader adding
the geoid height (also for an older user config that sets ELE itself), in a temporary data folder."""
import _testtmp  # noqa: F401  (temporary files of this run in one folder, removed at exit)
import os, subprocess, sys, tempfile
SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src')
sys.path.insert(0, SRC)
from pysyzygos import geoid, sitesfile

# EGM96 reference values (NGA): +13.61 m at the North Pole, -29.53 m at the South Pole; the extremes near
# 4.7 N 78.8 E (about -107 m) and 8.3 S 147.3 E (about +85 m; the 0.5 deg grid smooths the peaks a little)
assert abs(geoid.height(90, 0) - 13.61) < 0.05 and abs(geoid.height(-90, 123) - (-29.53)) < 0.05
assert -108 < geoid.height(4.75, 78.75) < -105 and 82 < geoid.height(-8.25, 147.25) < 86
assert abs(geoid.height(10.0, 359.9) - geoid.height(10.0, -0.1)) < 1e-9          # longitude wraps
assert abs(geoid.height(-30.0, 180.0) - geoid.height(-30.0, -180.0)) < 1e-9
assert abs(geoid.height(40.7128, -74.006) - (-32.8)) < 0.5                         # New York City Hall (example site)

s = geoid.fill(dict(lat=40.7128, lon=-74.006, ele=10))
assert s["geoid_m"] == round(geoid.height(40.7128, -74.006), 1)
assert geoid.fill(dict(lat=40.7128, lon=-74.006, ele=10, ele_ref="ellipsoid"))["geoid_m"] == 0.0

tmp = tempfile.mkdtemp()
path = os.path.join(tmp, "sites.py")
sitesfile.save_sites({"a": dict(lat=48.0, lon=11.0, ele=500.0), "b": dict(lat=-33.0, lon=151.0, ele=10.0,
                                                                          ele_ref="ellipsoid")}, "a", by="test", path=path)
sites, default = sitesfile.load_sites(path)
assert default == "a" and sites["a"]["geoid_m"] == round(geoid.height(48.0, 11.0), 1) and sites["b"]["geoid_m"] == 0.0

# the config loader: ELE = ele + geoid_m, also when the user's (older) config sets ELE = site["ele"] itself
home = tempfile.mkdtemp()
sitesfile.save_sites({"t": dict(lat=48.0, lon=11.0, ele=500.0)}, "t", by="test", path=os.path.join(home, "sites.py"))
template = open(os.path.join(SRC, "pysyzygos", "templates", "pysyzygos_config.py"), encoding="utf-8").read()
old = template.replace('ELE_MSL = site["ele"]', 'ELE = site["ele"]  #').replace("GEOID_M = ", "_unused = ") \
              .replace("ELE = ELE_MSL + GEOID_M", "pass")
open(os.path.join(home, "pysyzygos_config.py"), "w", encoding="utf-8").write(old)
env = dict(os.environ, PYSYZYGOS_HOME=home, PYTHONPATH=SRC)
env.pop("PYSYZYGOS_SITE", None)
out = subprocess.run([sys.executable, "-c", "from pysyzygos import config as C; print(C.ELE_MSL, C.GEOID_M, C.ELE)"],
                     env=env, capture_output=True, text=True, cwd=home)
assert out.returncode == 0, out.stderr
msl, n, ele = map(float, out.stdout.split())
assert msl == 500.0 and n == round(geoid.height(48.0, 11.0), 1) and abs(ele - (500.0 + n)) < 1e-9, out.stdout
print(f"config (older user file): ELE_MSL {msl:g} + GEOID_M {n:+.1f} = ELE {ele:.1f}")
print("GEOID TESTS PASSED")
