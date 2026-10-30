"""prescreen.py shared pre-screens: publish (one .tar.xz + .sha256 + prescreens.json), remote list and fetch from a
file:// mirror (identical files, only the listed members written, intact files kept, a corrupt download refused,
'latest'), and the catalog info of an upgrade's .new folder. No network, no SPICE."""
import json, os, shutil, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
import numpy as np
from pysyzygos import prescreen as PS

os.chdir(tempfile.mkdtemp())
os.makedirs("prescreen")
os.makedirs("gaia_dr3_g16.new")
json.dump(dict(format=2, build_id="abc123", gmax=16.0, pm_epoch=dict(date="2026-10-17")),
          open("gaia_dr3_g16.new/catalog.json", "w"))


def make(name, start, built):
    p = f"prescreen/{name}.global.npy"
    rng = np.random.default_rng(len(name))
    np.save(p, rng.normal(size=(5000, 4)))                          # stands in for the event records
    np.save(PS._idx_path(p), rng.normal(size=(5000, 2)))
    json.dump(dict(name="global", start=start, days=40.0, et0=1.0, et1=2.0, region=None, cam_limit=16.0, hmax=17.0,
                   min_drop=0.1, reach_km=200.0, max_sun_alt=0.0, min_alt=0.0, supplement=True, n_events=5000,
                   n_asteroids=900, built=built, catalog="gaia_dr3_g16.new", version="1.3.1", kind="global"),
              open(PS._meta_path(p), "w"))
    return p


a = make("global__2026-10-01_40d_G16", "2026-10-01", "2026-10-19T22:25:43")
b = make("global__2026-11-01_40d_G16", "2026-11-01", "2026-11-01T10:00:00")
share = os.path.abspath("share")
quiet = lambda *x: None
e = PS.publish(a, share, log=quiet, remote=[])
assert [f["name"] for f in e["files"]] == [os.path.basename(a), os.path.basename(PS._idx_path(a)),
                                           os.path.basename(PS._meta_path(a))]               # meta last
assert e["catalog"] == dict(folder="gaia_dr3_g16.new", format=2, build_id="abc123", gmax=16.0, pm_epoch="2026-10-17",
                            data_version=None)
arch = os.path.join(share, e["archive"])
assert e["archive"] == "global__2026-10-01_40d_G16.tar.xz" and os.path.getsize(arch) == e["archive_bytes"]
assert open(arch + ".sha256").read() == f"{e['archive_sha256']}  {e['archive']}\n"
import tarfile
assert sorted(tarfile.open(arch).getnames()) == sorted(f["name"] for f in e["files"])          # no folder part
PS.publish(b, share, log=quiet, remote=[])
PS.publish(a, share, log=quiet, remote=[])                         # again: replaces its entry, no duplicate
man = json.load(open(os.path.join(share, PS.MANIFEST)))
assert [x["name"] for x in man["prescreens"]] == ["global__2026-10-01_40d_G16", "global__2026-11-01_40d_G16"]

# fetch into another data folder from the file:// mirror
mirror = ["file://" + share + "/"]
m, man2 = PS.remote_list(mirror, log=quiet)
assert m == mirror[0] and man2 == man
assert PS.remote_list(["file:///nonexistent/"], log=quiet) == (None, None)
dest = tempfile.mkdtemp()
got = PS.fetch("latest", dest, mirror, log=quiet)
assert os.path.basename(got) == os.path.basename(b)                # latest = the newest start
for src in PS._files(b):
    assert open(src, "rb").read() == open(os.path.join(dest, os.path.basename(src)), "rb").read()
assert not [f for f in os.listdir(dest) if f.endswith(".part")]
assert [os.path.basename(p) for p, _ in PS.list_files(dest)] == [os.path.basename(b)]
lines = []
PS.fetch("global__2026-11-01_40d_G16", dest, mirror, log=lines.append)                  # intact: kept
assert any("already here" in x for x in lines) and not any("MB" in x and "tar.xz" in x for x in lines)

# a corrupt file on the mirror is refused and nothing half-written stays
x = os.path.join(share, "global__2026-10-01_40d_G16.tar.xz")
blob = bytearray(open(x, "rb").read())
blob[100] ^= 0xFF
open(x, "wb").write(bytes(blob))
dest2 = tempfile.mkdtemp()
try:
    PS.fetch("global__2026-10-01_40d_G16", dest2, mirror, log=quiet)
    raise AssertionError("corrupt download accepted")
except SystemExit as ex:
    assert "SHA-256 mismatch" in str(ex)
assert PS.list_files(dest2) == [] and not [f for f in os.listdir(dest2) if f.endswith(".part")]
# an extra member (e.g. '../evil') in an archive is never written: only the listed files are unpacked
PS.publish(a, share, log=quiet, remote=[])                         # a good archive again
with tarfile.open(x, "r:xz") as t0:
    members = [(m_, t0.extractfile(m_).read()) for m_ in t0.getmembers()]
import io
with tarfile.open(x, "w:xz") as t1:
    for m_, data in members:
        t1.addfile(m_, io.BytesIO(data))
    ev = tarfile.TarInfo("../evil.txt")
    ev.size = 1
    t1.addfile(ev, io.BytesIO(b"x"))
man = json.load(open(os.path.join(share, PS.MANIFEST)))
for e_ in man["prescreens"]:
    if e_["archive"] == os.path.basename(x):
        e_["archive_bytes"], e_["archive_sha256"] = os.path.getsize(x), PS._sha(x)
json.dump(man, open(os.path.join(share, PS.MANIFEST), "w"))
dest3 = os.path.join(tempfile.mkdtemp(), "inner")
PS.fetch("global__2026-10-01_40d_G16", dest3, mirror, log=quiet)
assert not os.path.exists(os.path.join(os.path.dirname(dest3), "evil.txt")) and len(os.listdir(dest3)) == 3
try:
    PS.fetch("nonexistent", dest2, mirror, log=quiet)
    raise AssertionError("unknown name accepted")
except SystemExit as ex:
    assert "global__2026-10-01_40d_G16" in str(ex)
try:
    PS.publish("prescreen/region.db", share, log=quiet, remote=[])
    raise AssertionError("region pre-screen published")
except SystemExit:
    pass
# builds on two machines: machine B's publish starts from the mirror's list, so A's entry stays listed
mirror_a = tempfile.mkdtemp()
PS.publish(a, mirror_a, log=quiet, remote=[])                        # machine A: the 40-day one, on the mirror
share_b = tempfile.mkdtemp()
PS.publish(b, share_b, log=quiet, remote=["file://" + mirror_a + "/"])   # machine B: the 70-day one
names = [x["name"] for x in json.load(open(os.path.join(share_b, PS.MANIFEST)))["prescreens"]]
assert names == ["global__2026-10-01_40d_G16", "global__2026-11-01_40d_G16"], names
assert PS.check_archives(json.load(open(os.path.join(mirror_a, PS.MANIFEST))), "file://" + mirror_a + "/", log=quiet) == []
# withdrawn: A's archive deleted on the mirror (its list still names it): the next publish on B leaves it out, also
# from B's own older list (its archive is not in B's folder); B's archive is in B's folder: kept until uploaded
os.remove(os.path.join(mirror_a, "global__2026-10-01_40d_G16.tar.xz"))
PS.publish(b, share_b, log=quiet, remote=["file://" + mirror_a + "/"])
names = [x["name"] for x in json.load(open(os.path.join(share_b, PS.MANIFEST)))["prescreens"]]
assert names == ["global__2026-11-01_40d_G16"], names
gone = PS.on_mirror(json.load(open(os.path.join(mirror_a, PS.MANIFEST))), "file://" + mirror_a + "/", log=quiet)
assert gone["prescreens"] == [], gone
# merge without repacking: two separate lists into one; a name listed twice: the later publication wins
only_b = dict(prescreens=[dict(name="x", start="2026-11-01", published="2026-10-22T10:00:00", archive="x.tar.xz"),
                          dict(name="y", start="2026-10-01", published="2026-10-20T10:00:00", archive="y.tar.xz")])
only_a = dict(prescreens=[dict(name="y", start="2026-10-01", published="2026-10-21T10:00:00", archive="y.tar.xz")])
m = PS.merge_manifests([only_b, None, only_a])
assert [x["name"] for x in m["prescreens"]] == ["y", "x"] and m["prescreens"][0]["published"].startswith("2026-10-21")
assert m["updated"] == "2026-10-22T10:00:00"
PS.write_manifest(m, os.path.join(share_b, "merged.json"))
assert PS.load_manifest(os.path.join(share_b, "merged.json")) == m and PS.load_manifest("/nonexistent.json") is None
assert PS.check_archives(m, "file://" + mirror_a + "/", log=quiet) == ["y", "x"]              # neither archive there
print("PRESCREEN SHARE TESTS PASSED")
