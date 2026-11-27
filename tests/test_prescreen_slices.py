"""prescreen_slices.py: split a whole-Earth pre-screen into G/H slices (disjoint, each sorted by time, day table,
block checksums, list), fetch only the slices and days a pick needs from a file:// mirror and merge them into one
local pre-screen equal to filtering the original; resume, a corrupt block refused, withdraw; the manager's plan
(split first, then the archive). No SPICE, no network."""
import _testtmp  # noqa: F401  (temporary files of this run in one folder, removed at exit)
import datetime as dt, json, os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
import numpy as np
from pysyzygos import prescreen as PS, prescreen_slices as SL, shadowtrack as ST, prescreen_manager as PM

os.chdir(tempfile.mkdtemp())
os.makedirs("prescreen")
share = os.path.abspath("share")
os.makedirs(share)
quiet = lambda *a: None
SL.CHUNK = 1500

# a 10-day whole-Earth pre-screen: 6000 events sorted by time, 300 asteroids with known H
rng = np.random.default_rng(1)
N, ET0, DAYS = 6000, 1_000_000.0, 10
ev = np.zeros(N, ST.DTYPE)
ev["et"] = np.sort(rng.uniform(ET0 - 43200, ET0 + DAYS * 86400 + 43200, N))
ev["number"] = rng.integers(1, 301, N)
ev["g"] = rng.uniform(8, 16, N).astype("f4")
ev["g"][:5] = [13.0, 14.0, 15.0, 16.0, 13.00005]      # exactly at the band edges: in the lower band
ev["half"] = rng.uniform(10, 20000, N).astype("f4")
ev["star"] = np.arange(N) + 1                        # unique: row identity
ev["x0"] = rng.normal(size=N)
ix = np.zeros(N, ST.IDX_DTYPE)
ix["lat_lo"] = rng.uniform(-80, 80, N)
ix["lon_w"] = np.arange(N)                             # = star - 1: rows stay paired
h_of = np.full(301, np.nan, np.float32)
h_of[1:] = rng.uniform(10, 21, 300)
h_of[7] = np.nan                                       # unknown H: the small-H slice
name = "global__2026-11-26_10d_G16"
p = f"prescreen/{name}.global.npy"
np.save(p, ev)
np.save(PS._idx_path(p), ix)
json.dump(dict(name="global", start="2026-11-26", days=float(DAYS), et0=ET0, et1=ET0 + DAYS * 86400, region=None,
               cam_limit=16.0, hmax=None, min_drop=0.1, reach_km=200.0, max_sun_alt=0.0, min_alt=0.0,
               supplement=True, n_events=N, n_asteroids=300, built="2026-11-27T00:00:00", catalog="cat",
               version="1.6.0", kind="global"), open(PS._meta_path(p), "w"))

# --- split: 8 disjoint slices that together are the original, each sorted, edges in the lower band
e = SL.split(p, share, h_of=h_of, synced=True, log=quiet, block_rows=700)
assert [s["key"] for s in e["slices"]] == ["G-13_H-17", "G-13_H17-", "G13-14_H-17", "G13-14_H17-", "G14-15_H-17",
                                           "G14-15_H17-", "G15-16_H-17", "G15-16_H17-"], [s["key"] for s in e["slices"]]
assert sum(s["rows"] for s in e["slices"]) == N
d = os.path.join(share, e["folder"])
allrows = []
for s in e["slices"]:
    a = np.load(os.path.join(d, s["file"]))
    x = np.load(os.path.join(d, s["idx_file"]))
    assert len(a) == len(x) == s["rows"] and np.all(np.diff(a["et"]) >= 0)
    assert np.array_equal(x["lon_w"], a["star"] - 1)                                   # rows stay paired
    h = np.where(np.isnan(h_of[a["number"]]), 0, h_of[a["number"]])
    assert np.all((h >= 17) == (s["h_lo"] == 17.0))
    assert s["g_lo"] is None or np.all(a["g"] > s["g_lo"] + SL.G_TOL)
    assert np.all(a["g"] <= s["g_hi"] + SL.G_TOL)
    assert s["offset"] + s["rows"] * 80 == os.path.getsize(os.path.join(d, s["file"]))
    assert len(s["blocks"]) == -(-s["rows"] // 700)
    allrows.append(a)
assert np.array_equal(np.sort(np.concatenate(allrows), order=["et", "star"]), np.sort(ev, order=["et", "star"]))
assert json.load(open(os.path.join(share, SL.MANIFEST)))["prescreens"][0]["name"] == name
assert SL.folder_state(share, e) == "ok"


def expected(start, days, gmax, hmax):
    w0 = ET0 + (dt.date.fromisoformat(start) - dt.date(2026, 11, 26)).days * 86400.0
    w1 = w0 + days * 86400.0
    h = np.where(np.isnan(h_of[ev["number"]]), 0, h_of[ev["number"]])
    m = (ev["et"] + ev["half"] >= w0) & (ev["et"] - ev["half"] <= w1) & (ev["g"] <= gmax + 1e-4)
    if hmax is not None:
        m &= h < 17                                   # whole slices: H < 17 for any hmax <= 17
    return ev[m], ix[m]


mirror = ["file://" + share + "/"]
for start, days, gmax, hmax in (("2026-11-26", 10, 16, None), ("2026-11-29", 3, 15, 17), ("2026-12-04", 2, 13.5, None),
                                ("2026-11-26", 1, 14, 17)):
    out = SL.fetch("latest", start, days, gmax, hmax, folder="dl", mirror_list=mirror, log=quiet)
    got, gx = np.load(out), np.load(PS._idx_path(out))
    want, wx = expected(start, days, gmax, hmax)
    assert len(got) == len(want) and np.all(np.diff(got["et"]) >= 0), (start, days, gmax, hmax, len(got), len(want))
    assert np.array_equal(np.sort(got, order=["et", "star"]), np.sort(want, order=["et", "star"]))
    assert np.array_equal(gx["lon_w"], got["star"] - 1)
    m = PS.read_meta(out)
    assert m["cam_limit"] == min(gmax, 16) and m["hmax"] == (17.0 if hmax else None) and m["start"] == start
    assert m["et1"] - m["et0"] == days * 86400 and m["n_events"] == len(want) and m["region"] is None
    # the pick's check accepts it inside its window and limits, refuses beyond them
    opt = dict(cam_limit=min(gmax, 16), reach_km=50.0, min_drop=0.1, max_sun_alt=0.0, min_alt=10.0, hmax=17.0)
    assert PS.check(m, m["et0"], m["et1"], 40.0, -73.0, opt) == []
    assert PS.check(m, m["et0"], m["et1"], 40.0, -73.0, dict(opt, cam_limit=gmax + 0.5))
    assert not os.path.exists(f"dl/.{os.path.basename(out)[:-len('.global.npy')]}.fetch")   # cache removed
    PS.remove(out)

# --- resume (blocks kept) and a corrupt block refused
base = SL.out_name(dt.date(2026, 11, 26), 10.0, 16.0, None)
cache = f"dl/.{base}.fetch"
os.makedirs(cache)
s0 = e["slices"][0]
open(os.path.join(cache, s0["file"] + ".0"), "wb").write(b"x" * (min(700, s0["rows"]) * 80))  # wrong: fetched again
out = SL.fetch("latest", None, None, None, None, folder="dl", mirror_list=mirror, log=quiet)
assert len(np.load(out)) == len(expected("2026-11-26", 10, 16, None)[0])
PS.remove(out)
# the same window and limits as the original, in the original's folder: kept, not overwritten
assert SL.fetch("latest", None, None, None, None, folder="prescreen", mirror_list=mirror, log=quiet) == p
assert len(np.load(p)) == N
bad = os.path.join(d, s0["file"])
b = bytearray(open(bad, "rb").read()); b[s0["offset"] + 5] ^= 0xFF; open(bad, "wb").write(bytes(b))
try:
    SL.fetch("latest", "2026-11-26", 1, 13, None, folder="dl", mirror_list=mirror, log=quiet)
    raise AssertionError("corrupt block accepted")
except SystemExit as x:
    assert "SHA-256" in str(x)
b[s0["offset"] + 5] ^= 0xFF; open(bad, "wb").write(bytes(b))

# --- a window outside the published one is refused
try:
    SL.fetch("latest", "2026-12-05", 3, 16, None, folder="dl", mirror_list=mirror, log=quiet)
    raise AssertionError("window beyond accepted")
except SystemExit as x:
    assert "not inside" in str(x)

# --- the manager: shows both forms, plans split first, then the archive; withdraw removes both
st = dict(settings=dict(PM.DEFAULTS, share_dir=share, publish_mode="both", auto_build=False), jobs=[])
PM.save_state(st)
TODAY = dt.date(2026, 11, 27)
i = PM.inventory(st, today=TODAY)
x = next(y for y in i["local"] if y["name"] == name)
assert x["on_slices"] and not x["on_archive"] and not x["published"]
acts = PM.plan(i, (True, ""))
assert ("publish", p) in [(a, t) for a, t, _ in acts], acts              # slices there: the archive next
PS.publish(p, share, log=quiet, remote=PS.synced_remote(share))
i = PM.inventory(st, today=TODAY)
x = next(y for y in i["local"] if y["name"] == name)
assert x["published"] and len(i["mirror"]) == 1 and i["mirror"][0]["sliced"] == "ok" and i["mirror"][0]["archive"]
assert not [a for a in PM.plan(i, (True, "")) if a[0] in ("split", "publish")]
st["settings"]["publish_mode"] = "slices"
SL.withdraw(name, share, log=quiet)
acts = PM.plan(PM.inventory(st, today=TODAY), (True, ""))
assert ("split", p) in [(a, t) for a, t, _ in acts], acts
PS.withdraw(name, share, log=quiet)                                        # both forms
assert not os.path.exists(os.path.join(share, name + ".tar.xz")) and not os.path.isdir(d)
assert PM.share_items(share)[0] == []
# sync conflict copy of the sliced list: merged, entries without their folder dropped
SL.split(p, share, h_of=h_of, synced=True, log=quiet, block_rows=700)
json.dump(dict(prescreens=[dict(e, name="gone", folder="gone.slices", published="2030-01-01")]),
          open(os.path.join(share, "prescreen_slices (conflicted copy 2026-11-27 1010).json"), "w"))
assert PM.share_items(share)[2]
PM.merge_share(share, log=quiet)
assert [z["name"] for z in json.load(open(os.path.join(share, SL.MANIFEST)))["prescreens"]] == [name]
assert not PM.share_items(share)[2]
print("test_prescreen_slices: ok")
