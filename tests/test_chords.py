"""chords.py: the fit of an ellipse to chords in the fundamental plane and the profile plot (no SPICE, no network):
a synthetic event cut from a known ellipse is fitted back; circle, fixed size, misses as limits, excluded chords,
crossing times, the report times across midnight."""
import math, os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
import numpy as np
from pysyzygos import chords as C

TRUE = (14.0, 7.0, 51.8, 29.95, 40.6)                     # center x, y, semi-axes a, b, PA: Hertha 2008 (archive)
V = np.array([-4.9, 2.8])                                   # the stations' motion relative to the asteroid, km/s


def station(n, offset, result="positive", ell=TRUE, acc=0.05):
    """A station whose track passes `offset` km across the motion from the ellipse center; D and R where it cuts."""
    u = V / np.hypot(*V)
    nrm = np.array([-u[1], u[0]])
    p_ca = np.array(ell[:2]) + offset * nrm                 # closest approach to (x, y) at t_ca = 10 s
    s = dict(n=n, observer=f"Obs {n}", place="Somewhere", result=result, include=True, note="",
             p_ca=list(p_ca), w=list(V), t_ca=10.0)
    if result == "positive":
        tin, tout = C.crossing(s, ell)
        assert tin is not None, offset
        s.update(d_t=tin, r_t=tout, d_xy=list(p_ca + V * (tin - 10.0)), r_xy=list(p_ca + V * (tout - 10.0)),
                 d_acc=acc, r_acc=acc, d_utc="2008-12-11T07:44:30.00", r_utc="2008-12-11T07:44:40.00")
    return s


offs = [-30, -24, -15, -8, -2, 5, 11, 18, 25, 31]
data = dict(event=dict(source="occult archive", key="135|2008-12-11T07:45:46", target="135", name="135 Hertha",
                       utc="2008-12-11T07:45:46.516", star="85076262683056000", star_catalog="HIP 13021", r_km=37.65,
                       archive_fit=dict(major=103.6, minor=59.9, pa=40.6, x=14.0, y=7.0, quality="good")),
            stations=[station(i + 1, o) for i, o in enumerate(offs)] + [station(11, 60.0, "miss"),
                                                                        station(12, -70.0, "miss")])
f = C.fit(data)
assert f["mode"] == "ellipse" and f["n_chords"] == 10, f
assert abs(f["x"] - 14.0) < 0.01 and abs(f["y"] - 7.0) < 0.01, f
assert abs(f["major"] - 103.6) < 0.02 and abs(f["minor"] - 59.9) < 0.02 and abs(f["pa"] - 40.6) < 0.05, f
assert f["rms_km"] < 1e-3 and all(abs(r["d_s"]) < 1e-3 for k, r in f["stations"].items() if "d_s" in r), f
assert f["stations"]["11"] == dict(miss_inside=False)
# noisy end points: the size within its 1-sigma scale
rng = np.random.default_rng(1)
noisy = dict(data, stations=[dict(s, **({k: list(np.array(s[k]) + rng.normal(0, 1.0, 2)) for k in ("d_xy", "r_xy")}
                                        if s.get("d_xy") else {})) for s in data["stations"]])
g = C.fit(noisy)
assert abs(g["major"] - 103.6) < 4 * g["smajor"] + 1 and abs(g["pa"] - 40.6) < 4 * g["spa"] + 1, g
assert 0.3 < g["rms_km"] < 2.0 and g["smajor"] and g["sx"], g
# shapes: circle, fixed size, auto by the number of chords
c = C.fit(data, mode="circle")
assert c["mode"] == "circle" and c["major"] == c["minor"] and 59 < c["major"] < 104, c
k = C.fit(data, mode="fixed", diameter=80.0)
assert k["mode"] == "fixed" and k["major"] == 80.0 and k["smajor"] is None, k
two = dict(data, stations=data["stations"][3:5])
assert C.fit(two)["mode"] == "circle"
one = dict(data, stations=data["stations"][4:5])
o1 = C.fit(one)
assert o1["mode"] == "fixed" and o1["major"] == 75.3, o1                  # the predicted size (r_km 37.65)
assert C.fit(dict(data, stations=data["stations"][10:]))["mode"] == "none"
assert "3 chords" in C.fit(two, mode="ellipse")["why"]
# excluded chords leave the fit; a wrong chord excluded does not move it
bad = [dict(s) for s in data["stations"]]
bad[2] = dict(bad[2], d_xy=list(np.array(bad[2]["d_xy"]) + 12 * V / np.hypot(*V)))   # D 12 km late along the track
assert abs(C.fit(dict(data, stations=bad))["major"] - 103.6) > 0.5
e = C.fit(dict(data, stations=bad), exclude=[3])
assert abs(e["major"] - 103.6) < 0.02 and e["excluded"] == [3] and "3" not in e["stations"], e
bad[2]["include"] = False                                                # Occult's 'excluded' flag: the same
assert abs(C.fit(dict(data, stations=bad))["major"] - 103.6) < 0.02
# a miss through the true outline: inside; as a limit it pulls the fit off it
inside = dict(data, stations=data["stations"][:10] + [station(13, 20.0, "miss")])
m = C.fit(inside)
assert m["stations"]["13"]["miss_inside"] is True
m2 = C.fit(inside, misses=True)
assert m2["misses"] and m2["stations"]["13"]["miss_inside"] is False or m2["rms_km"] > 0.05, m2
# the text and the plot
t = C.fit_text(f)
assert t.startswith("103.6 ±") and "PA 40.6" in t and "10 chords" in t, t
assert C.fit_text(dict(mode="none", why="no chord to fit")) == "no fit: no chord to fit"
svg = C.svg(data, f)
assert svg.startswith("<svg") and svg.rstrip().endswith("</svg>")
assert "(135) Hertha 2008-12-11 07:45:46 UT" in svg and "Occult archive fit" in svg and "asteroid motion" in svg
assert svg.count('stroke-dasharray="7 5"') >= 3                          # 2 misses + the legend's sample
assert "Obs 10" in svg and "km</text>" in svg
d = tempfile.mkdtemp()
p = C.save(dict(data, fit_opts=dict(mode="circle")), d)
back = C.load(p)
assert back["fit"]["mode"] == "circle" and os.path.isfile(os.path.join(d, "profile.svg"))
# report times: across midnight from the reference
from datetime import datetime, timezone
ref = datetime(2026, 11, 2, 23, 59, 50, tzinfo=timezone.utc)
assert C._report_utc("2026-11-02", "00:00:05.25", ref) == "2026-11-03T00:00:05.250"
assert C._report_utc("2026-11-03", "23:59:58", datetime(2026, 11, 3, 0, 0, 5, tzinfo=timezone.utc)) == "2026-11-02T23:59:58.000"
assert C._report_utc("2026-11-02", "", ref) is None
assert C.report_time(dict(date="2026-11-02", predict_time="01:09:10")) == datetime(2026, 11, 2, 1, 9, 10, tzinfo=timezone.utc)
# a satellite's chords (Occult codes G/B): their own fit, the main body's fit unchanged; only satellite chords
SAT = (-300.0, 90.0, 58.0, 46.0, 95.0)
sats = [dict(station(20 + i, o, ell=SAT), body="satellite") for i, o in enumerate((-35, -20, -5, 10, 30))]
both = dict(data, event=dict(data["event"], sat=dict(name="(617) 1 = Menoetius", r_km=59.8)),
            stations=data["stations"] + sats)
d2 = tempfile.mkdtemp()
C.save(both, d2)
assert abs(both["fit"]["major"] - 103.6) < 0.02 and both["fit"]["n_chords"] == 10, both["fit"]
fs = both["fit_sat"]
assert fs["body"] == "satellite" and fs["n_chords"] == 5 and abs(fs["major"] - 116.0) < 0.05 and abs(fs["x"] + 300) < 0.05
lines = C.fit_lines(both)
assert lines[0].startswith("main body: 103.6") and lines[1].startswith("satellite (617) 1 = Menoetius: 116.0"), lines
only = dict(both, stations=data["stations"][10:] + sats)
C.save(only, d2)
assert C.fit_lines(only)[0].startswith("satellite") and len(C.fit_lines(only)) == 1
sv = C.svg(only)
assert "satellite chord (s)" in sv and "fit to the satellite" in sv and "chord D\u2013R" not in sv
# contacts paired per station: D with the next R; a lone D or R is a one-sided chord
P = C.pair_contacts([("01:00:01", "d1"), ("01:00:09", "d2")], [("01:00:05", "r1")])
assert P == [(("01:00:01", "d1"), ("01:00:05", "r1")), (("01:00:09", "d2"), (None, None))], P
assert C.pair_contacts([], [("01:00:05", "r1")]) == [((None, None), ("01:00:05", "r1"))]
# one-sided chords are points of the outline; planets and moons: their known size in 'auto'
one_side = [dict(x) for x in data["stations"][:10]]
for x in one_side[::3]:
    for k in ("r_xy", "r_t", "r_utc"):
        x.pop(k)
os_ = C.fit(dict(data, stations=one_side))
assert abs(os_["major"] - 103.6) < 0.05 and os_["stations"]["1"]["r_km"] is None and os_["stations"]["1"]["d_km"] is not None
assert "D 07:44:30.00 UT" in C.svg(dict(data, stations=one_side), os_)
moon = dict(data, event=dict(data["event"], body_kind="moon", r_km=50.0))
assert C.fit(moon)["mode"] == "fixed" and C.fit(moon)["major"] == 100.0
print("CHORDS TESTS PASSED")
