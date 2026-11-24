"""horizon.py: OccultWatcher's [User Horizon] format (the example stations of its own help text), the horizon height
at an azimuth, behind / near a star, and the rules' errors. No SPICE, standard library only."""
import _testtmp  # noqa: F401  (temporary files of this run in one folder, removed at exit)
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
from pysyzygos import horizon as H

TEXT = """# comment lines and empty lines are ignored

Name = Marsfield
0, 0
270, 0
270, 10
280, 20
290, 10
290, 0
360, 0

Name = Wiruna
0, 20
10, 10
10, 0
350, 0
350, 10
360, 20
"""
st = H.parse(TEXT)
assert H.parse("\ufeff# saved by a Windows editor (byte-order mark)\n" + TEXT) == st
assert list(st) == ["Marsfield", "Wiruna"] and st["Marsfield"][3] == (280, 20)
m = st["Marsfield"]
assert H.altitude(m, 100) == 0 and H.altitude(m, 280) == 20 and H.altitude(m, 275) == 15
assert H.altitude(m, 270) == 10                                   # the vertical step: the higher side
assert H.altitude(st["Wiruna"], 5) == 15 and H.altitude(st["Wiruna"], 355) == 15 and H.altitude(st["Wiruna"], 365) == 15
# behind, near, clear (margin 15 deg, as OccultWatcher's default warning threshold)
assert H.assess(m, 10, 280)[0] == "behind" and H.assess(m, 30, 280)[0] == "near" and H.assess(m, 60, 100)[0] == ""
flag, h, sep = H.assess(m, 18, 292)                               # beside the obstacle: near in another direction
assert flag == "near" and h == 0 and 0 < sep < 15, (flag, h, sep)
assert H.assess([], 10, 280) == ("", None, None)
# the format's rules give errors with the line or station
for bad, why in (("Name = X\n0, 10\n180, 5\n", "360"), ("Name = X\n0, 0\n20, 5\n10, 5\n360, 0\n", "rise"),
                 ("Name = X\n0, 0\n90, 1\n90, 5\n90, 9\n360, 0\n", "more than two"), ("Name = X\n0, 0\n12.5, 4\n360, 0\n", "line 3"),
                 ("0, 0\n360, 0\n", "line 1"), ("# nothing\n", "no 'Name")):
    try:
        H.parse(bad)
        raise SystemExit(f"accepted: {bad!r}")
    except H.HorizonError as e:
        assert why in str(e), (why, str(e))
assert H.parse(H.to_text("Marsfield", m))["Marsfield"] == m       # written back in the same format
assert "<polygon" in H.svg(m, star=(280, 30))

# the pick screen's azimuth (screen.Site.azimuth, the search's az_deg formula); stand-in SPICE: ITRF = J2000
import math, types
import numpy as np
from pysyzygos import screen as SC
fake = types.SimpleNamespace(georec=lambda lon, lat, alt, a, f: [a + alt, 0.0, 0.0], pxform=lambda a, b, t: np.eye(3))
site = SC.Site(fake, 0.0, 0.0, 0.0)                               # at lat 0, lon 0: east = +y, north = +z
for v, az in (((0, 0, 1), 0.0), ((0, 1, 0), 90.0), ((0, 0, -1), 180.0), ((0, -1, 0), 270.0)):
    assert abs(site.azimuth(0.0, np.array(v, float)) - az) < 1e-9, (v, site.azimuth(0.0, np.array(v, float)))
# a negative margin: stars up to that far behind the line count (kept, marked 'behind'); positive: no allowance
assert H.allowance(15) == 0 and H.allowance(0) == 0 and H.allowance(-3) == 3 and H.allowance(None) == 0
assert H.limit(m, 280, 15) == 20 and H.limit(m, 280, -3) == 17 and H.limit(m, 0, -3) == -3
assert H.assess(m, 18, 280, -3)[0] == "behind" and H.assess(m, 30, 0, -3)[0] == ""      # no 'near' when <= 0
# a star at 10 deg: behind the obstacle at 280 deg (20 deg), above the flat part at 0 deg
assert 10 < H.altitude(m, 280) and 10 > H.altitude(m, 0)
print("HORIZON TESTS PASSED")
