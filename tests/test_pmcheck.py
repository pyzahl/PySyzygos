"""pmcheck.py without network: VizieR stand-ins with the UCAC5 / UCAC4 rows of (4089) Galbraith's star (Gaia DR3
3383655504436521856 = UCAC4 573-029535, a 2-parameter star in a 2.8" double) and its companion: the four proper-motion
estimates, their offsets at the event, the spread, the shifted star direction and the summary."""
import math, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
import numpy as np
from pysyzygos import pmcheck as P

RA, DEC, G = 96.87470281886635, 24.532824010646436, 9.82                    # Gaia DR3 2016.0
U5 = ("RAgaia\tDEgaia\tpmRA\te_pmRA\tpmDE\te_pmDE\tGmag\ndeg\tdeg\tmas/yr\tmas/yr\tmas/yr\tmas/yr\tmag\n"
      "-\t-\t-\t-\t-\t-\t-\n 96.8747044\t 24.5328269\t  -4.0\t 1.7\t -13.0\t 1.7\t 9.760\n")
U4 = ("UCAC4\tRAJ2000\tDEJ2000\te_RAJ2000\te_DEJ2000\tEpRA\tEpDE\tpmRA\te_pmRA\tpmDE\te_pmDE\tf.mag\ta.mag\n"
      + "\t".join("-" * 13) + "\n" + "\t".join("-" * 13) + "\n"
      "573-029535\t096.8747159\t+24.5328645\t 21\t 47\t1995.47\t1995.73\t -5.6\t 2.9\t -15.8\t 6.2\t 9.613\t 9.197\n"
      "573-029536\t096.8751415\t+24.5335753\t 17\t 33\t1990.42\t1991.05\t  4.6\t 0.9\t   3.9\t 1.7\t 9.785\t 9.202\n")
calls = []
def fetch(url):
    calls.append(url)
    return U5 if "ucac5" in url else U4

ests = P.estimates(RA, DEC, G, used=(-4.0, -13.0), years=10.78, ra_err=2.2, dec_err=1.93, fetch=fetch)
by = {e["label"]: e for e in ests}
assert list(by) == ["UCAC5", "UCAC4", "UCAC4 epoch to Gaia", P.LABEL_J2000], list(by)
assert len(calls) == 2 and "-c.rs=3" in calls[0]
assert by["UCAC5"]["east"] == 0 and by["UCAC5"]["north"] == 0 and by["UCAC5"]["err"] == 1.7
assert by["UCAC4"]["pmdec"] == -15.8 and by["UCAC4"]["err"] == 6.2             # the companion (573-029536) not taken
ep = by["UCAC4 epoch to Gaia"]                                                  # from the 1995.5 measurement, not J2000
assert abs(ep["pmra"] + 3.31) < 0.02 and abs(ep["pmdec"] + 10.51) < 0.02 and abs(ep["err"] - 2.32) < 0.02, ep
oc = by[P.LABEL_J2000]                                                          # Occult's star: 44 mas from ours,
assert abs(oc["pmra"] + 2.68) < 0.02 and abs(oc["pmdec"] + 9.11) < 0.02      # as the path comparison measured
assert abs(oc["east"] - 14.3) < 0.3 and abs(oc["north"] - 41.9) < 0.3, oc
sp = P.spread_mas(ests)
assert 30 < sp < 33, sp
assert P.spread_mas([]) is None
s = P.summary(ests, "UCAC5")
assert s.startswith("UCAC5 -4.0, -13.0 ±1.7 (used); UCAC4 -5.6") and "(44 mas)" in s, s

# the shifted star direction: east / north by the given mas
ra, dec = math.radians(RA), math.radians(DEC)
s0 = np.array([math.cos(dec) * math.cos(ra), math.cos(dec) * math.sin(ra), math.sin(dec)])
s1 = P.shifted_dir(s0, 14.3, 41.9)
ra1, dec1 = math.degrees(math.atan2(s1[1], s1[0])), math.degrees(math.asin(s1[2]))
assert abs((ra1 - RA) * math.cos(dec) * 3.6e6 - 14.3) < 0.01 and abs((dec1 - DEC) * 3.6e6 - 41.9) < 0.01

# nothing matching (too far, other magnitude), and no answer: no estimates, no error
assert P.estimates(RA + 0.01, DEC, G, fetch=fetch) == []
assert P.estimates(RA, DEC, 14.0, fetch=fetch) == []
def down(url):
    raise OSError("offline")
assert P.estimates(RA, DEC, G, fetch=down) == []
print("PMCHECK TESTS PASSED")
