"""Shadow elements (pysyzygos.shadowtrack) and global pre-screen files (pysyzygos.prescreen): the quadratic fit, the
ground track on a synthetic geometry (star along +x, no Earth rotation), the superset margins (a track crossing a
small box between two samples), and the sorted global file with its window and star-limit selection. No SPICE."""
import _testtmp  # noqa: F401  (temporary files of this run in one folder, removed at exit)
import sys, os, json, sqlite3, tempfile
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
from pysyzygos import shadowtrack as ST, prescreen as PS

# the fit: an exact quadratic is recovered, with no misfit
half = np.array([600.0, 3600.0])
dt = half[:, None] * np.linspace(-1, 1, 9)[None, :]
px = 100.0 + 8.0 * dt + 1e-4 * dt * dt
py = -50.0 - 3.0 * dt
f = ST.fit(px, py, half)
assert np.allclose(f["x0"], 100.0) and np.allclose(f["vx"], 8.0) and np.allclose(f["ax"], 1e-4)
assert np.allclose(f["vy"], -3.0) and np.allclose(f["ay"], 0.0, atol=1e-12) and f["err"].max() < 1e-6
ev = np.zeros(2, ST.DTYPE)
ev["et"] = 1000.0
for k in ("x0", "y0", "vx", "vy", "ax", "ay"):
    ev[k] = f[k]
qx, qy = ST.positions(ev, 1000.0 + dt)
assert np.allclose(qx, px, rtol=1e-5, atol=1e-2) and np.allclose(qy, py, atol=1e-2), "positions() follows the fit"

# ground track, synthetic: star along +x, ITRF = J2000 (identity), samples at grid times (no spin)
sdir = np.array([[1.0, 0.0, 0.0]])
ets = np.arange(-6000.0, 6001.0, 600.0)
fr = dict(ets=ets, step=600.0, rot=np.repeat(np.eye(3)[None], len(ets), 0), sun_u=np.repeat([[-1.0, 0, 0]], len(ets), 0))
tau = np.array([[-600.0, 0.0, 600.0]])
# the plane basis for a star along +x: x east = (0,0,1) x (1,0,0) = (0,1,0), y north = (0,0,1)
ex, ny = ST.plane(sdir)
assert np.allclose(ex, [[0, 1, 0]]) and np.allclose(ny, [[0, 0, 1]])
on_axis = (np.zeros((1, 3)), np.zeros((1, 3)))                       # the shadow axis through the sub-star point
near = PS.box_around(0.0, 0.0, 100)
far = PS.region_box(40, 50, 0, 10)
k, w = ST.ground_track(*on_axis, tau, sdir, fr, 1.0, near, 20.0, 0.0, 0.0)
assert k[0] and abs(w[0, 0]) < 1e-6 and abs(w[0, 1]) < 1e-6 and w[0, 3] > 89.9, w
assert not ST.ground_track(*on_axis, tau, sdir, fr, 1.0, far, 20.0, 0.0, 0.0)[0][0], "box far away"
day = dict(fr, sun_u=np.repeat([[1.0, 0, 0]], len(ets), 0))
assert not ST.ground_track(*on_axis, tau, sdir, day, 1.0, near, 20.0, 0.0, 0.0)[0][0], "Sun up at the sub-star point"
assert ST.ground_track(*on_axis, tau, sdir, fr, 1.0, None, 20.0, 0.0, 0.0)[0][0], "global: no box test"
off = (np.full((1, 3), 9000.0), np.zeros((1, 3)))                    # passes 9000 km from the Earth's centre
assert not ST.ground_track(*off, tau, sdir, fr, 1.0, None, 200.0, 0.0, 0.0)[0][0], "misses the Earth"

# a track moving east along the equator, samples 1000 km apart: the box (50 km) lies between two samples
px = np.array([[-1500.0, -500.0, 500.0, 1500.0]])
py = np.zeros((1, 4))
t4 = np.array([[-600.0, -600.0, -600.0, -600.0]])                  # same grid time: no spin
box = PS.box_around(0.0, 0.0, 50)
k, _ = ST.ground_track(px, py, t4, sdir, fr, 1.0, box, 5.0, 0.0, 0.0)
assert k[0], "a track crossing the box between two samples is kept (half-step margin)"
assert ST._half_steps(np.stack([px, py], 2)).tolist() == [[500.0, 500.0, 500.0, 500.0]]

# the global file: chunks (as a build saves them) -> one array sorted by time; select by window and star limit
d = tempfile.mkdtemp()
con = sqlite3.connect(os.path.join(d, "p.partial"))
con.executescript(PS.SCHEMA + "CREATE TABLE chunks (n INTEGER, data BLOB);")
rng = np.random.default_rng(1)
for c in range(3):
    e = np.zeros(50, ST.DTYPE)
    e["number"] = rng.integers(1, 40, 50)
    e["et"] = rng.uniform(0, 10 * 86400, 50)
    e["g"] = rng.uniform(8, 16, 50)
    e["half"] = 1800.0
    con.execute("INSERT INTO chunks VALUES (?, ?)", (len(e), e.tobytes()))
con.commit()
out = os.path.join(d, "t.global.npy")
from pysyzygos import gaia_local as GL                        # Windows: nothing may be mapped when renamed (WinError 32)
real_replace, mapped = GL.replace_file, []
def checked_replace(src, dst, *a, **k):
    if os.path.exists("/proc/self/maps") and os.path.abspath(src) in open("/proc/self/maps").read():
        mapped.append(src)
    return real_replace(src, dst, *a, **k)
GL.replace_file = checked_replace
n_ev, n_ast = PS._write_global(con, out, dict(name="t", start="2026-10-01", days=10, et0=0.0, et1=10 * 86400.0,
                                                region=None, cam_limit=16.0, reach_km=200.0, min_drop=0.1,
                                                max_sun_alt=0.0, min_alt=0.0, hmax=17.0, built="2026-10-01T00:00:00"))
con.close()
GL.replace_file = real_replace
assert not mapped, f"still memory-mapped while renamed: {mapped}"
a = np.load(out)
assert n_ev == 150 and len(a) == 150 and np.all(np.diff(a["et"]) >= 0), "sorted by time"
assert n_ast == len(set(a["number"].tolist()))
m = PS.read_meta(out)
assert m["kind"] == "global" and PS.counts(out) == (150, n_ast) and PS.is_global(out)
assert [p for p, _ in PS.list_files(d)] == [out]
sel = PS.select(out, 86400.0, 2 * 86400.0, 12.0)
ref = a[(a["et"] + a["half"] >= 86400.0) & (a["et"] - a["half"] <= 2 * 86400.0) & (a["g"] <= 12.0 + 1e-4)]
assert len(sel) == len(ref) and np.array_equal(sel["et"], ref["et"])
assert PS.check(m, 86400.0, 2 * 86400.0, -33.9, 151.2, dict(cam_limit=13.0)) == [], "a global one fits any site"
PS.remove(out)
assert not os.path.exists(out) and not os.path.exists(out[:-4] + ".json")
print("SHADOWTRACK TESTS PASSED")
