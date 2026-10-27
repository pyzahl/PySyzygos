import os, sys, re, json, time, types, functools, tempfile, numpy as np
from pathlib import Path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
from pysyzygos import sbdb as pysyzygos_sbdb
from pysyzygos import offline as _offline
_offline.use_dir(tempfile.mkdtemp())          # never the data folder's real offline copies
# sbdb_phys + get_asteroid_size from pysyzygos.py (not importable: kernel setup at import), with a stand-in SBDB
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src', 'pysyzygos', 'search.py')).read()
code = src[src.index("SIZE_OVERRIDES = {}"):src.index("def get_asteroid_ra_dec(")]

calls = []
class RequestException(Exception): pass
DB = {"19": dict(object=dict(fullname="19 Fortuna (A852 QA)"),
                 phys_par=[dict(name="diameter", value="225", sigma="3", ref="NEOWISE"), dict(name="H", value="7.3")]),
      "5": dict(object=dict(fullname="5 Astraea"), phys_par=[dict(name="H", value="6.9"), dict(name="albedo", value="0.27")]),
      "7": dict(object=dict(fullname="nothing"), phys_par=[])}
online = [True]
class Resp:
    def __init__(s, js): s.js = js
    def raise_for_status(s): pass
    def json(s): return s.js
def get(url, params, timeout):
    calls.append(params["sstr"])
    if not online[0]: raise RequestException("offline")
    return Resp(DB[params["sstr"]])
cache_dir = tempfile.mkdtemp()
cfg = types.SimpleNamespace(cache_path=cache_dir, sbdb_max_age_days=30)
ns = dict(U=__import__('pysyzygos.urls', fromlist=['urls']), np=np, re=re, json=json, time=time, os=os, Path=Path, functools=functools, config=cfg, sbdb_cache=pysyzygos_sbdb,
          requests=types.SimpleNamespace(get=get, RequestException=RequestException),
          run_note=lambda kind, item: NOTES.append((kind, item)))   # search's run warnings (stale size data)
NOTES = []
exec(code, ns)

s = ns['get_asteroid_size']("19"); print(s)
assert abs(s['r_km'] - 112.5) < 1e-9 and s['H'] == 7.3 and "NEOWISE" in s['source'] and calls == ["19"]
ns['get_asteroid_size'].cache_clear()
s2 = ns['get_asteroid_size']("19"); assert s2 == s and calls == ["19"], "disk cache not used"
data = json.loads((Path(cache_dir) / "PySyzygos_sbdb_phys.json").read_text())
assert data["19"]["phys"]["_fullname"] == "19 Fortuna (A852 QA)"
assert not [f for f in os.listdir(cache_dir) if f.endswith(".tmp")]

a = ns['get_asteroid_size']("5"); assert a['source'] == "H + SBDB albedo" and a['r_min_km'] > 0
assert ns['get_asteroid_size']("7") is None, "no diameter and no H must give None"
assert set(json.loads((Path(cache_dir) / "PySyzygos_sbdb_phys.json").read_text())) == {"19", "5", "7"}

ns['SIZE_OVERRIDES']["19"] = (100.0, 40.0, "occultation chords")
ns['get_asteroid_size'].cache_clear()
o = ns['get_asteroid_size']("19"); assert o['r_km'] == 100.0 and o['r_min_km'] == 0.0 and o['H'] == 7.3

# expiry: refetch; offline after expiry: stale data is used; offline without cache: None, nothing cached
cfg.sbdb_max_age_days = 0
ns['get_asteroid_size'].cache_clear(); n0 = len(calls)
ns['sbdb_phys']("5"); assert len(calls) == n0 + 1
online[0] = False
assert ns['sbdb_phys']("5")["H"]["value"] == "6.9"
assert ns['sbdb_phys']("99") is None and "99" not in json.loads((Path(cache_dir) / "PySyzygos_sbdb_phys.json").read_text())

# bulk entries (pick tool) give the same size as per-object entries, and never replace a newer per-object entry
online[0] = True; cfg.sbdb_max_age_days = 30
api = pysyzygos_sbdb.entry_from_api(dict(object=dict(fullname="9 Metis", orbit_class=dict(code="MBA",
                                                    name="Main-belt Asteroid")), phys_par=[
    dict(name="diameter", value="190", sigma="4", ref="NEOWISE"), dict(name="extent", value="222x182x130"),
    dict(name="H", value="6.3"), dict(name="G", value="0.17")]))
bulk = pysyzygos_sbdb.entry_from_bulk(dict(full_name="     9 Metis (A848 HA)", diameter="190", diameter_sigma="4",
                                          extent="222x182x130", H="6.3", G="0.17", albedo="", **{"class": "MBA"}),
                                     fetched=time.time())
sizes = []
for e in (api, bulk):
    pysyzygos_sbdb.put({"9": e}, cache_dir, keep_newer=False); ns['get_asteroid_size'].cache_clear()
    sizes.append({k: v for k, v in ns['get_asteroid_size']("9").items() if k != "source"})
print("api ", sizes[0]); print("bulk", sizes[1]); assert sizes[0] == sizes[1]
assert bulk["phys"]["_fullname"] == "9 Metis (A848 HA)"
assert api["phys"]["_class"]["value"] == bulk["phys"]["_class"]["value"] == "MBA"          # the orbit class, both ways
assert pysyzygos_sbdb.entry_from_api(dict(object=dict(fullname="x")))["phys"]["_class"]["value"] == ""   # none: kept
# known (even empty): used from the cache; an entry from before the orbit class is fetched once more
pysyzygos_sbdb.put({"9": dict(api, fetched=time.time() + 100)}, cache_dir)            # newer per-object entry
assert pysyzygos_sbdb.put({"9": bulk}, cache_dir) == 0 and pysyzygos_sbdb.get("9", cache_dir)[0]["source"] == "sbdb.api"
print("SIZE CACHE TESTS PASSED")
