"""The reach from the path's n-sigma limit (reach.py): n clamped to 0..3, for every target, the widening (capped),
the pick's angular allowance, the pre-screen's distance bound, the record fields; the report's badge. Numbers of
(612533) 2002 XV93 on 2026-11-11 (r 203 km, 1 sigma 3,038 km, site 2,061 km from the center line). No SPICE."""
import math, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
import numpy as np
from pysyzygos import reach, report

# n: 0..3, junk -> 0
assert [reach.n_sigma(v) for v in (None, "x", -1, 0, 1, "2", 2.6, 7)] == [0, 0, 0, 0, 1, 2, 3, 3]

# every target when n > 0 (small asteroids too: their 3 sigma is often > 50 km); the old size arguments are ignored
assert reach.applies(1) and reach.applies(3) and reach.applies(1, 2.0, 50.0) and not reach.applies(0)

# the widening: n x sigma, capped; unknown sigma -> nothing
assert reach.widening_km(1, 3038.0) == 3038.0 and reach.widening_km(3, 8000.0) == 3 * reach.CAP_KM
assert reach.widening_km(2, None) == 0.0 and reach.widening_km(2, float("nan")) == 0.0

# the pick: an angle at the asteroid's distance (37.1 AU), capped, 0 for n 0, arrays too
d = 37.14 * 1.495978707e8
w = reach.pick_widening_km(1, d)
assert abs(w - min(reach.PICK_SIGMA_MAS * math.pi / 648000000.0 * d, reach.CAP_KM)) < 1e-6 and w > 3038.0, w   # covers 2002 XV93
assert float(reach.pick_widening_km(0, d)) == 0.0
d2 = 2.0 * 1.495978707e8                                      # main belt: 200 mas at 2 AU = 290 km, below the cap
arr = reach.pick_widening_km(2, np.array([d2, 2 * d2]))
assert arr.shape == (2,) and abs(arr[1] - 2 * arr[0]) < 1e-6 and abs(arr[0] - 2 * 290.1) < 1.0, arr
# a pre-screen's events keep no distance: aphelion + 1 AU (Ceres a 2.77, e 0.08: 3.99 AU)
assert abs(reach.delta_max_km(2.77, 0.08) / 1.495978707e8 - 3.9916) < 1e-3

# the record fields: the 1-sigma limit at r + sigma, the site 1,181 km inside it; n 0 when the rule did not apply
f = reach.fields(1, 202.97, 3038.26, 2060.67, True)
assert f["reach_n"] == 1 and abs(f["reach_from_km"] - 3241.23) < 0.01 and abs(f["reach_dist_km"] + 1180.56) < 0.01, f
f0 = reach.fields(1, 202.97, 3038.26, 2060.67, False)
assert f0["reach_n"] == 0 and abs(f0["reach_from_km"] - 202.97) < 1e-9 and abs(f0["reach_dist_km"] - 1857.7) < 0.01

# the gate as the search applies it: kept with n = 1, not with n = 0 (reach 50 km)
r, s1, dist, rch = 202.97, 3038.26, 2060.67, 50.0
assert not dist < r + rch + reach.widening_km(0, s1)
assert dist < r + rch + reach.widening_km(1, s1)

# report: the badge on the distance cell (inside the n-sigma limit, beyond it, none inside the shadow)
e = dict(miss=2060.7, margin=1857.7, reach_n=1.0, reach_dist=-1180.6)
assert "in 1σ" in report.reach_badge(e) and "1181 km inside" in report.reach_badge(e)
assert "past 2σ" in report.reach_badge(dict(e, reach_n=2.0, reach_dist=30.0))
assert report.reach_badge(dict(e, margin=-5.0)) == "" and report.reach_badge(dict(e, reach_n=0.0)) == ""
assert report.reach_badge(dict(miss=10.0, margin=3.0)) == ""
# far asteroids (TNOs, Centaurs): rare and far, so never cut: no cap in the search, 150,000 km per sigma elsewhere
assert reach.is_far(a_au=43.0) and reach.is_far(group="tno") and reach.is_far(group="other")
assert reach.is_far(delta_km=37 * 1.495978707e8) and not reach.is_far(a_au=5.2, group="trojan")
assert not reach.is_far(a_au=2.7, group="main") and not reach.is_far() and not reach.is_far(group="")
assert reach.widening_km(1, 37500.0, reach.cap_for(True)) == 37500.0          # 90 % of TNOs: up to 37,500 km
assert reach.widening_km(1, 37500.0, reach.cap_for(False)) == reach.CAP_KM
assert float(reach.pick_widening_km(2, d, far=True)) == 2 * reach.FAR_SIGMA_KM
assert float(reach.pick_widening_km(0, d, far=True)) == 0.0
# the allowance per group: the main belt the angle (the compromise), the others their table sigma x 1.5, else the
# generous fallback; never capped outside the main belt
assert reach.cap_for(False, "main") == reach.CAP_KM and reach.cap_for(False, "neo") == float("inf")
assert reach.is_main("main") and not reach.is_main("neo") and reach.is_main(None, 2.7) and not reach.is_main(None, 1.2)
d2 = 2.0 * 1.495978707e8
assert abs(float(reach.allowance_km(1, d2, "main", 2.7)) - 290.1) < 1.0
assert float(reach.allowance_km(2, d2, "neo", 1.3)) == 2 * reach.NEAR_SIGMA_KM
assert float(reach.allowance_km(2, d2, "neo", 1.3, table_sigma1_km=120.0)) == 2 * 1.5 * 120.0
assert float(reach.allowance_km(1, d, "tno", 43.0)) == reach.FAR_SIGMA_KM
assert float(reach.allowance_km(1, d, "tno", 43.0, table_sigma1_km=float("nan"))) == reach.FAR_SIGMA_KM
assert float(reach.allowance_km(0, d, "tno", 43.0)) == 0.0

# the sigma table: built with a stand-in query (no Horizons), saved, reloaded; old entries asked again, fresh ones not
import json, tempfile
from pysyzygos import sigmatable as STB
tp = os.path.join(tempfile.mkdtemp(), STB.FILE)
asked = []
def q(n, utc):
    asked.append(n)
    return None if n == 3 else 10.0 * n
assert STB.build([1, 2, 3], tp, query=q, say=lambda *a: None) == (3, 2)
assert STB.load(tp) == {1: 10.0, 2: 20.0}
asked.clear()
assert STB.build([1, 2, 3], tp, query=q, say=lambda *a: None) == (1, 0) and asked == [3]   # only the missing one
data = json.load(open(tp))
data["entries"]["1"][1] = "2020-01-01"                                                  # an old entry: asked again
json.dump(data, open(tp, "w"))
asked.clear()
STB.build([1, 2], tp, query=q, say=lambda *a: None)
assert asked == [1]
assert STB.load(os.path.join(tempfile.mkdtemp(), "none.json")) == {}
# a proper-motion check that VizieR did not answer: 'pm ?' after the magnitude (report), noted in favorites and CSV
pm = dict(sflag="2p UCAC4", pm_check="not done (VizieR did not answer)", star_sigma=None, rad=5.0)
assert "pm ?" in report.star_mark(pm) and "VizieR did not answer" in report.star_mark(pm)
assert "pm ?" not in report.star_mark(dict(pm, pm_check=""))
from pysyzygos import favorites as _fav
assert "VizieR did not answer" in _fav.pm_text(dict(star_pm_source="UCAC4", star_pmra="1", star_pmdec="2",
                                                    star_pm_check="not done (VizieR did not answer)"))
print("REACH TESTS PASSED")
