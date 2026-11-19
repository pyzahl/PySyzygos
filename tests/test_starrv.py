"""starrv.py: the radial-velocity table (build, lookup, unknown stars 0) and the size of the perspective acceleration
(Barnard's star: the Gaia archive's EPOCH_PROP_POS gave 74.8 mas between 2016.0 and 2026.79 with and without its
radial velocity)."""
import _testtmp  # noqa: F401  (temporary files of this run in one folder, removed at exit)
import os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
import numpy as np
from pysyzygos import starrv as S

tmp = tempfile.mkdtemp()
csv = os.path.join(tmp, "rv.csv")
with open(csv, "w") as f:
    f.write("source_id,radial_velocity,radial_velocity_error,phot_g_mean_mag,pm,parallax\n"
            "4472832130942575872,-110.47,0.12,8.19,10393,547.45\n"
            "100,25.0,1.0,12.0,300,50\n"
            "50,-7.5,0.5,10.0,500,80\n"
            "100,25.0,1.0,12.0,300,50\n")                                      # a duplicate row
out = os.path.join(tmp, "rv.npy")
assert S.build(csv, out) == 3
t = np.load(out)
assert list(t["source_id"]) == [50, 100, 4472832130942575872] and t.dtype == S.DTYPE   # sorted, no duplicates
S._table = t                                                                   # use this table
v = S.rv_for([100, 7, 4472832130942575872, 50, 10 ** 18])
assert np.allclose(v, [25.0, 0.0, -110.47, -7.5, 0.0], atol=1e-4), v
assert len(S.rv_for([])) == 0
S._table = np.zeros(0, S.DTYPE)                                                # no table: all zero, as before
assert np.all(S.rv_for([100, 50]) == 0)

# size of the effect: Barnard's star over 10.79 years
m = S.perspective_mas(10393.0, -110.47, 547.45, 2026.789 - 2016.0)
assert abs(m - 74.8) < 1.0, m
assert S.perspective_mas(20.0, 30.0, 2.0, 20.0) < 1e-3                         # an ordinary star: negligible
# the threshold: 0.01 mas within 20 years
assert abs(S.perspective_mas(S.THRESHOLD, 1.0, 1.0, 20.0) - 0.01) < 1e-4
S._table = None
print("STARRV TESTS PASSED")
