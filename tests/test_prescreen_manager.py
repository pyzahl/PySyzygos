"""prescreen_manager.py: inventory of local / partial / shared pre-screens, expired and superseded, the maintenance
plan (publish, delete, withdraw, merge of sync conflict copies, build / resume / wait for memory), withdraw, the
build and resume command lines, job output names and log progress. No SPICE, no network, no curses."""
import _testtmp  # noqa: F401  (temporary files of this run in one folder, removed at exit)
import datetime as dt, json, os, sqlite3, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
import numpy as np
from pysyzygos import prescreen as PS, prescreen_manager as PM

os.chdir(tempfile.mkdtemp())
os.makedirs("prescreen")
share = os.path.abspath("share")
os.makedirs(share)
quiet = lambda *a: None
TODAY = dt.date(2026, 11, 26)


def make(start, days, built, cam=16.0):
    name = f"global__{start}_{days:g}d_G{cam:g}"
    p = f"prescreen/{name}.global.npy"
    np.save(p, np.zeros((100, 4)))
    np.save(PS._idx_path(p), np.zeros((100, 2)))
    json.dump(dict(name="global", start=start, days=float(days), et0=1.0, et1=2.0, region=None, cam_limit=cam,
                   hmax=17.0, min_drop=0.1, reach_km=200.0, max_sun_alt=0.0, min_alt=0.0, supplement=False,
                   n_events=100, n_asteroids=50, built=built, catalog="cat", version="1.6.0", kind="global"),
              open(PS._meta_path(p), "w"))
    return p


old = make("2026-10-01", 40, "2026-10-01T00:00:00")          # over
mid = make("2026-11-02", 40, "2026-11-02T00:00:00")          # current, ends 2026-12-12
st = dict(settings=dict(PM.DEFAULTS, share_dir=share, keep_min=1, publish_mode="archive"), jobs=[])   # slices: test_prescreen_slices
PM.save_state(st)


def inv():
    return PM.inventory(st, today=TODAY)


# --- expired / superseded, protection
i = inv()
by = {x["name"]: x for x in i["local"]}
assert by["global__2026-10-01_40d_G16"]["expired"] and not by["global__2026-11-02_40d_G16"]["expired"]
assert PM.protected(i["local"], 1) == {"global__2026-11-02_40d_G16"}
acts = PM.plan(i, (True, ""))
kinds = [(a, os.path.basename(str(t))) for a, t, _ in acts]
assert ("publish", os.path.basename(mid)) in kinds, kinds          # current, not on the mirror: published
assert ("publish", os.path.basename(old)) not in kinds              # an expired one is not
assert ("delete", os.path.basename(old)) in kinds
assert acts[-1][0] == "build" and acts[-1][1] == "2026-11-26", acts  # 16 days ahead < 21
assert PM.plan(i, (False, "swap 95% full"))[-1][0] == "wait"        # memory short: no build
st["settings"]["lead_days"] = 10.0
assert PM.plan(inv(), (True, ""))[-1] [0] == "wait"                 # 16 days ahead >= 10
st["settings"]["lead_days"] = 21.0

# --- publish into the synced share folder (its own list = the mirror's), then the plan sees it there
PS.publish(mid, share, log=quiet, remote=PS.synced_remote(share))
i = inv()
assert {x["name"]: x for x in i["local"]}["global__2026-11-02_40d_G16"]["published"]
assert [e["state"] for e in i["mirror"]] == ["ok"]
assert not any(a == "publish" for a, _, _ in PM.plan(i, (True, "")))

# --- a newer, longer build supersedes the 40-day one (local and on the mirror) once it is published
new = make("2026-11-26", 70, "2026-11-26T12:00:00")
i = inv()
assert {x["name"]: x for x in i["local"]}["global__2026-11-02_40d_G16"]["superseded"]
acts = PM.plan(i, (True, ""))
kinds = [(a, os.path.basename(str(t))) for a, t, _ in acts]
assert ("publish", os.path.basename(new)) in kinds and ("delete", os.path.basename(mid)) in kinds, kinds
assert acts[-1][0] == "wait" and "covered" in acts[-1][2]           # 2027-02-04: 70 days ahead
PS.publish(new, share, log=quiet, remote=PS.synced_remote(share))
acts = PM.plan(inv(), (True, ""))
assert ("withdraw", "global__2026-11-02_40d_G16", "a newer build covers its window") in acts, acts
assert ("withdraw", "global__2026-11-26_70d_G16") not in [(a, t) for a, t, _ in acts]   # the newest: kept

# --- execute: delete local, withdraw on the mirror
for a in acts:
    if a[0] in ("delete", "withdraw"):
        PM.execute(st, a, log=quiet)
assert not os.path.exists(old) and not os.path.exists(mid) and not os.path.exists(PS._meta_path(mid))
assert not os.path.exists(os.path.join(share, "global__2026-11-02_40d_G16.tar.xz"))
man = json.load(open(os.path.join(share, PS.MANIFEST)))
assert [e["name"] for e in man["prescreens"]] == ["global__2026-11-26_70d_G16"]
assert PM.plan(inv(), (True, ""))[-1][0] == "wait" and len(PM.plan(inv(), (True, ""))) == 1

# --- a sync conflict copy (another machine's list) is merged, entries without an archive left out
other = dict(man, prescreens=man["prescreens"] + [dict(man["prescreens"][0], name="gone", archive="gone.tar.xz",
                                                       published="2030-01-01T00:00:00")])
json.dump(other, open(os.path.join(share, "prescreens (conflicted copy 2026-11-26 101010).json"), "w"))
i = inv()
assert i["conflicts"] and PM.plan(i, (True, ""))[0][0] == "merge"
PM.merge_share(share, log=quiet)
assert not PM.share_items(share)[2]                                   # conflict copy gone
assert [e["name"] for e in json.load(open(os.path.join(share, PS.MANIFEST)))["prescreens"]] == \
    ["global__2026-11-26_70d_G16"]

# --- orphans and a missing archive
open(os.path.join(share, "stray.tar.xz"), "w").write("x")
assert PM.share_items(share)[1] == ["stray.tar.xz"]
os.rename(os.path.join(share, "global__2026-11-26_70d_G16.tar.xz"), os.path.join(share, "moved"))
assert PM.share_items(share)[0][0]["state"] == "missing"
os.rename(os.path.join(share, "moved"), os.path.join(share, "global__2026-11-26_70d_G16.tar.xz"))
assert PS.withdraw("stray", share, log=quiet) and not os.path.exists(os.path.join(share, "stray.tar.xz"))

# --- a stopped build is resumed instead of a new one; its command keeps the stored settings
PS.remove(new)
part = "prescreen/global__2026-11-20_70d_G16.global.npy.partial"
settings = dict(PS._settings("2026-11-20", 70.0, None, 16.0, 17.0, 0.1, 200.0, 0.0, 0.0, "cat"), supplement=False)
con = PS.open_partial(part, settings)
con.executemany("INSERT INTO done VALUES (?)", [(n,) for n in range(1, 1001)])
con.commit()
con.close()
st["settings"]["share_dir"] = None
i = inv()
assert i["partials"][0]["done"] == 1000 and i["partials"][0]["end"] == dt.date(2027, 1, 29)
a = PM.plan(i, (True, ""))[-1]
assert a[0] == "resume" and a[1] == part, a
args, out = PM.resume_args(st["settings"], i["partials"][0])
assert out == part[:-len(".partial")] and "--global" in args and args[args.index("--start") + 1] == "2026-11-20"
assert float(args[args.index("--hmax") + 1]) == 17.0 and args[args.index("--name") + 1] == "global"
reg = dict(lat_min=44.29238827338129, lat_max=49.6880717266187, lon_min=5.682683991561715, lon_max=13.592816008438286)
ra, _ = PM.resume_args(st["settings"], dict(path="prescreen/Seewis_300km__x.db.partial",
                                             settings=dict(settings, region=reg, reach_sigma=3)))
r = next(x for x in ra if x.startswith("--region="))
assert PS.parse_region(r[len("--region="):]) == reg                  # exact round trip: the partial resumes
assert ra[ra.index("--name") + 1] == "Seewis_300km" and "--reach-sigma" in ra
assert PM.resume_args(st["settings"], dict(path=part, settings=dict(settings, selection={"groups": ["tno"]})))[0] is None
b, bout = PM.build_args(dict(st["settings"], hmax=None, catalog="gaia_dr3_g16_v2"), "2026-12-01")
assert "--all" in b and bout == "prescreen/global__2026-12-01_70d_G16.global.npy" and "--catalog" in b

# --- command lines of running jobs, log progress, exit code
argv = ["/x/python", "-u", "-m", "pysyzygos", "prescreen", "build", "--start", "2026-11-26", "--days", "70",
        "--global", "--cam-limit", "16"]
assert PM.out_of(argv) == "prescreen/global__2026-11-26_70d_G16.global.npy"
assert PM.out_of(["pysyzygos", "prescreen", "publish", "prescreen/a.global.npy", "--to", "s"]) == "prescreen/a.global.npy"
line = ("  89631/464740 asteroids (19.3%), 1717755 events | chunk 207 in 91 s, 14 ast/s, elapsed 1:45:13, ETA 7:20:22 "
        "| mem available 7.3 GB, swap used 17.2 GB, worker peak RSS 5.7 GB")
assert PM.progress_text(["x", line]) == "19.3 % (89631/464740), ETA 7:20:22, mem 7.3 GB, swap 17.2 GB"
assert PM.exit_code(["a", "--- exit code 0"]) == 0 and PM.exit_code(["a"]) is None
assert PM.window_of("global__2026-11-26_70d_G16") == (dt.date(2026, 11, 26), dt.date(2027, 2, 4))

# --- a launched job: detached, logged with its exit code, seen as finished
j = PM.launch(st, "index", ["--version"], "prescreen/x")
for _ in range(100):
    if not PM.alive(j["pid"]):
        break
    import time; time.sleep(0.1)
PM.reap()
js = PM.jobs(st)
assert js[-1]["pid"] == j["pid"] and not js[-1]["alive"] and js[-1]["exit"] == 0, js[-1]
assert "PySyzygos" in open(j["log"]).read()
print("test_prescreen_manager: ok")
