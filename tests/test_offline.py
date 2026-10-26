"""offline.py: switching on/off, the compressed asteroid list and its H coverage, orbit files and their time spans,
size data from the copied cache or from the list, status and removal (in a temporary data folder, no network)."""
import json, os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
from pysyzygos import offline as O

os.chdir(tempfile.mkdtemp())                               # every command runs in the data folder
assert not O.enabled()
blob = dict(fields=["spkid", "full_name", "H", "G", "diameter", "diameter_sigma", "extent", "albedo"],
            data=[["2003200", "  3200 Phaethon (1983 TB)", "14.38", "", "", "", "", "0.12"],
                  ["2000433", "   433 Eros (A898 PA)", "10.4", "0.46", "16.84", "0.06", "", "0.25"]],
            hmax=17.0, fetched=1.7e9, full_prec=True)
assert O.keep_sbdb(blob) is False and not os.path.exists(O.SBDB)          # off: nothing kept
O.set_enabled(True)
assert O.enabled() and O.keep_sbdb(blob) and os.path.isfile(O.SBDB)
assert O.sbdb_fallback(16.0)["data"] == blob["data"] and O.sbdb_fallback(17.0) is not None
assert O.sbdb_fallback(18.0) is None                                     # a list to H 17 cannot stand in for H 18

# orbit files: kept when on; the fallback needs a file whose span covers the window
cache = tempfile.mkdtemp()
for name in ("PySyzygos_asteroid_3200_2019-07-28_2019-07-30.bsp", "PySyzygos_asteroid_3200_2019-07-27_2019-08-02.bsp",
             "PySyzygos_asteroid_32000_2019-07-01_2019-09-01.bsp"):
    open(os.path.join(cache, name), "w").write("x")
    assert O.keep_spk(os.path.join(cache, name))
f = O.spk_fallback("3200", "2019-07-28", "2019-07-30")
assert f and os.path.basename(f).startswith("PySyzygos_asteroid_3200_2019-07-")       # never asteroid 32000
assert os.path.basename(O.spk_fallback("3200", "2019-07-28", "2019-08-01")) == "PySyzygos_asteroid_3200_2019-07-27_2019-08-02.bsp"
assert O.spk_fallback("3200", "2019-07-20", "2019-07-30") is None and O.spk_fallback("99", "2019-07-28", "2019-07-29") is None

# size data: from the copied size cache first, else from the list
json.dump({"3200": dict(fetched=1.7e9, source="sbdb.api", phys=dict(diameter=dict(value="6.25")))}, open(O.PHYS, "w"))
assert O.phys_fallback("3200")["phys"]["diameter"]["value"] == "6.25"
e = O.phys_fallback("433")                                                   # not in the size cache: the list
assert e["phys"]["diameter"]["value"] == "16.84" and e["phys"]["H"]["value"] == "10.4"
assert O.phys_fallback("12345") is None

# an empty cache (e.g. /dev/shm after a restart) is filled from a fresh offline copy, without a download
import time
from pysyzygos import pick as P, sbdb as SB
P.net.urlopen = lambda *a, **k: (_ for _ in ()).throw(AssertionError("no download expected"))
fresh = dict(blob, fields=P.SBDB_FIELDS, data=[[""] * len(P.SBDB_FIELDS)] * 3, fetched=time.time() - 86400)
assert O.keep_sbdb(fresh)
cache_file = os.path.join(cache, "PySyzygos_sbdb_cache.json")
fields, data, fetched = P.fetch_sbdb(17.0, cache_file)
assert len(data) == 3 and abs(fetched - fresh["fetched"]) < 1 and os.path.isfile(cache_file), "restored, not downloaded"
assert P.fetch_sbdb(17.0, cache_file)[1] == data                         # then from the cache itself
os.remove(cache_file)
O.keep_sbdb(dict(fresh, fetched=time.time() - 40 * 86400))               # an old copy is not used: a download
try:
    P.fetch_sbdb(17.0, cache_file)
    raise SystemExit("an expired offline copy was used instead of a download")
except AssertionError:
    pass
# no network: the old copy after all, and the pick records it (pick_meta warnings, GUI and report in orange)
P.net.urlopen = lambda *a, **k: (_ for _ in ()).throw(OSError("network unreachable"))
P.WARNINGS.clear()
assert len(P.fetch_sbdb(17.0, cache_file)[1]) == 3
assert len(P.WARNINGS) == 1 and "JPL SBDB did not answer" in P.WARNINGS[0] and "40 days old" in P.WARNINGS[0]
# the size data: the cache file is restored from the offline copy when missing
phys_cache = os.path.join(cache, SB.FILE)
assert not os.path.exists(phys_cache) and SB.load(cache)["3200"]["phys"]["diameter"]["value"] == "6.25"
assert os.path.isfile(phys_cache)

st = O.status()
assert st["enabled"] and st["sbdb"]["count"] == 3 and st["orbits"] == 3 and "3 asteroids (H < 17)" in O.status_text(st)
O.set_enabled(False)
assert not O.enabled() and os.path.isfile(O.SBDB)                           # off keeps the copies
O.remove()
assert not os.path.exists(O.DIR)
print("OFFLINE TESTS PASSED")
