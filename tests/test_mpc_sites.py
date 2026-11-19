"""pysyzygos_geo.mpc_observatories / mpc_geodetic: MPC ObsCodes.html parsing and parallax constants -> geodetic."""
import _testtmp  # noqa: F401  (temporary files of this run in one folder, removed at exit)
import os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
from pysyzygos import geo as G

# parallax constants -> geodetic: a point on the WGS84 ellipsoid at lat 45, height 1000 m round-trips
import math
a, f = 6378.137, 1 / 298.257223563
e2 = f * (2 - f)
lat0, h0 = math.radians(45.0), 1.0
n = a / math.sqrt(1 - e2 * math.sin(lat0) ** 2)
rc, rs = (n + h0) * math.cos(lat0) / a, (n * (1 - e2) + h0) * math.sin(lat0) / a
lat, lon, ele = G.mpc_geodetic(350.0, rc, rs)
assert abs(lat - 45.0) < 1e-7 and abs(lon + 10.0) < 1e-9 and abs(ele - 1000.0) < 1e-3, (lat, lon, ele)

folder = tempfile.mkdtemp()
open(os.path.join(folder, "ObsCodes.html"), "w").write(
    "<pre>\nCode  Long.   cos      sin    Name\n"
    "000   0.0000 0.62411 +0.77873 Greenwich\n"
    "002   0.62   0.622   +0.781   Rayleigh\n"
    "247                           Roving Observer\n"
    "309 289.595690.909943-0.414336Cerro Paranal\n"
    "500   0.000000.000000+0.000000Geocentric\n"
    "695 248.405330.849504+0.526425Kitt Peak\n"
    "</pre>\n")
G._MPC = None
s = G.mpc_observatories(folder, url="http://invalid.invalid/none.html")       # local file: no download
assert [o["code"] for o in s] == ["000", "002", "309", "695"], [o["code"] for o in s]   # roving, geocentric skipped
gw, ray, par, kp = s
assert abs(gw["lat"] - 51.477) < 0.002 and gw["lon"] == 0.0 and 0 < gw["ele"] < 150 and gw["ele_ok"]
assert not ray["ele_ok"], "3-decimal constants: height not trusted"
assert abs(par["lat"] + 24.627) < 0.002 and abs(par["lon"] + 70.404) < 0.002 and abs(par["ele"] - 2635) < 60
assert abs(kp["lat"] - 31.958) < 0.002 and abs(kp["lon"] + 111.595) < 0.002 and kp["name"] == "Kitt Peak"
G._MPC = None
assert G.mpc_observatories(tempfile.mkdtemp(), url="http://invalid.invalid/none.html") == [], "offline, no file: empty"
print("MPC SITES TESTS PASSED")
