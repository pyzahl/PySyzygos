"""pysyzygos_kstars: command building and safe failure, with a stand-in for subprocess (no KStars, no D-Bus needed)."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
from pysyzygos import kstars as K

calls = []


class R:                                                        # subprocess.CompletedProcess stand-in
    def __init__(self, out):
        self.returncode, self.stdout, self.stderr = 0, out, ""


def fake_run(cmd, **kw):
    calls.append(cmd)
    if cmd[-1].endswith(".location") or "org.kde.kstars.location" in cmd:
        return R('(\'{"latitude":47.0,"longitude":9.6,"tz":2,"tz0":1}\',)')
    return R("()")


K.sys.platform = "linux"
K.shutil.which = lambda n: "/usr/bin/gdbus" if n == "gdbus" else None
K.subprocess.run = fake_run
ok, msg = K.show(100.0, -20.5, "2026-10-19T00:27:34.761Z", 1.5, lat=47.0, lon=-9.6, ele=900)
assert ok, msg
by = {c[c.index("--method") + 1].rsplit(".", 1)[1]: c for c in calls}
for m in ("setGPSLocation", "setLocalTime", "setRaDecJ2000", "setTracking", "setApproxFOV"):
    assert m in by, m
args = lambda m: by[m][by[m].index("--") + 1:]                  # "--" so negative numbers are not read as options
assert args("setGPSLocation")[:2] == ["-9.6", "47.0"], args("setGPSLocation")
assert args("setRaDecJ2000") == [repr(100.0 / 15.0), "-20.5"], "RA in hours, Dec in degrees"
assert args("setLocalTime") == ["2026", "10", "19", "2", "27", "34"], "UT + KStars' tz (2 h)"
assert args("setTracking") == ["true"] and args("setApproxFOV") == ["1.5"]

# dbus-send: typed arguments
calls.clear()
K.shutil.which = lambda n: "/usr/bin/dbus-send" if n == "dbus-send" else None
assert K.show(10.0, 5.0, "2026-10-19T00:00:00")[0]
ra = next(c for c in calls if c[5].endswith("setRaDecJ2000"))
assert ra[6:] == [f"double:{10.0 / 15.0}", "double:5.0"], ra

# location option: KStars is at Testtown (fake_loc, made up); the site is a test site ~6400 km away, or next door
K.shutil.which = lambda n: "/usr/bin/gdbus" if n == "gdbus" else None
fake_loc = '(\'{"name":"Testtown","latitude":40.0,"longitude":-74.0,"tz":-4,"tz0":-5}\',)'
def run_loc(cmd, **kw):
    calls.append(cmd)
    return R(fake_loc if "org.kde.kstars.location" in cmd else "()")
K.subprocess.run = run_loc
methods = lambda: [c[c.index("--method") + 1].rsplit(".", 1)[1] for c in calls]
calls.clear()
ok, msg = K.show(80.0, 31.0, "2026-10-19T00:27:34", 2.0, lat=48.0, lon=11.0, ele=500)
assert ok and "setGPSLocation" in methods() and "changed from Testtown" in msg, msg
calls.clear()
ok, msg = K.show(80.0, 31.0, "2026-10-19T00:27:34", 2.0, lat=48.0, lon=11.0, ele=500, set_location=False)
assert ok and "setGPSLocation" not in methods() and "km from the site" in msg, msg
calls.clear()
ok, msg = K.show(80.0, 31.0, "2026-10-19T00:27:34", 2.0, lat=40.001, lon=-74.0, ele=30)   # already there
assert ok and "setGPSLocation" not in methods() and "; " not in msg, msg

# labelling the star: only names KStars knows (proper / Bayer names; here 'alp Ori'); the last label is removed
def run_names(cmd, **kw):
    calls.append(cmd)
    if "org.kde.kstars.location" in cmd:
        return R(fake_loc)
    if "org.kde.kstars.getObjectDataXML" in cmd:
        known = cmd[-1] == "alp Ori"
        return R("('<?xml version=\"1.0\"?><object><Name>Betelgeuse</Name></object>',)" if known else "('<xml></xml>',)")
    return R("()")
K.subprocess.run = run_names
K.LABEL.clear()
calls.clear()
ok, msg = K.show(88.8, 7.4, "2026-10-19T00:27:34", 1.0, names=["HIP 27989", "alp Ori"])
by = {c[c.index("--method") + 1].rsplit(".", 1)[1]: c for c in calls}
assert ok and "alp Ori labelled" in msg and args("addLabel") == ["alp Ori"], msg
calls.clear()
ok, msg = K.show(88.8, 7.4, "2026-10-19T00:27:34", 1.0, names=["Gaia DR3 1"])
by = {c[c.index("--method") + 1].rsplit(".", 1)[1]: c for c in calls}
assert ok and "no name KStars knows" in msg and args("removeLabel") == ["alp Ori"] and "addLabel" not in by, msg
assert K.LABEL == {}

# never raises: other systems, no tool, bad data
K.sys.platform = "darwin"
assert K.show(1, 2, "2026-10-19T00:00:00") == (False, "KStars control works on Linux only")
K.sys.platform = "linux"
K.shutil.which = lambda n: None
assert K.show(1, 2, "2026-10-19T00:00:00")[0] is False
K.shutil.which = lambda n: "/usr/bin/gdbus" if n == "gdbus" else None
assert K.show("x", 2, "nonsense")[0] is False
print("KSTARS TESTS PASSED")
