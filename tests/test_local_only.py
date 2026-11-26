"""Search with local data only (2026-11-25): net.block() refuses every internet connection at once (Python sockets;
curl via a dead proxy), local sockets still work; the path uncertainty without Horizons comes from the cached
Horizons answer nearest in date (scaled to the distance), else the sigma table, else None (the default)."""
import _testtmp  # noqa: F401  (temporary files of this run in one folder, removed at exit)
import ast, json, os, socket, sys, tempfile, time, types
from datetime import datetime
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
from pysyzygos import net

# --- the network block
os.environ["https_proxy"] = "http://proxy.example:8080"
net.block("test")
for call in (lambda: socket.getaddrinfo("example.org", 443), lambda: socket.create_connection(("192.0.2.1", 443), 1)):
    try:
        call()
        raise AssertionError("connection not refused")
    except OSError as ex:
        assert "no network: test" in str(ex), ex
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
try:
    s.connect(("192.0.2.1", 443))
    raise AssertionError("connect not refused")
except OSError as ex:
    assert "no network" in str(ex)
finally:
    s.close()
try:
    net.urlopen("https://example.org/", timeout=1)
    raise AssertionError("urlopen not refused")
except OSError:
    pass
assert os.environ["https_proxy"] == "http://127.0.0.1:9" and os.environ["no_proxy"] == ""
a, b = socket.socketpair(socket.AF_UNIX)                          # local sockets still work
path = os.path.join(tempfile.mkdtemp(), "s")
srv = socket.socket(socket.AF_UNIX)
srv.bind(path)
srv.listen(1)
cli = socket.socket(socket.AF_UNIX)
cli.connect(path)
for x in (a, b, srv, cli):
    x.close()
net._unblock()
assert os.environ["https_proxy"] == "http://proxy.example:8080" and socket.getaddrinfo is not None
assert not net.BLOCKED

# --- cached_path_error (excerpt of search.py, stand-ins for SPICE, components and the sigma table)
SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src', 'pysyzygos', 'search.py')
WANT = {"_sigma_cache", "cached_path_error", "SIGMA_CACHE", "SIGMA_NEAR_DAYS", "_SIGMA_TABLE"}
tree = ast.parse(open(SRC, encoding="utf-8").read())
code = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in WANT
        or isinstance(n, ast.Assign) and any(getattr(t, "id", None) in WANT for t in n.targets)]
cache_dir = tempfile.mkdtemp()
config = types.SimpleNamespace(cache_path=cache_dir, orbit_max_age_days=7)
DIST = {"2026-11-29": 2.0e8, "2026-12-01": 3.0e8}                 # km: the target's distance on these days


class Spice:
    def str2et(self, t):
        return t[:10]

    def spkpos(self, target, et, *a):
        if et not in DIST:
            raise RuntimeError("not covered")
        return [np.array([DIST[et], 0.0, 0.0])], 0.0


comp = types.SimpleNamespace(system=lambda t: str(t).split("+")[0])
ns = dict(config=config, os=os, json=json, time=time, datetime=datetime, np=np, spice=Spice(), components=comp)
exec(compile(ast.Module(code, []), SRC, "exec"), ns)
old = time.time() - 100 * 86400                                   # any age counts here
with open(os.path.join(cache_dir, ns["SIGMA_CACHE"]), "w") as fh:
    json.dump({"5335|2026-11-29": dict(sigma3_km=30.0, smaa_mas=10.0, smia_mas=2.0, pa_deg=80.0, t=old),
               "5335|2026-10-01": dict(sigma3_km=99.0, smaa_mas=1.0, smia_mas=1.0, pa_deg=0.0, t=old),
               "617|2026-12-30": dict(sigma3_km=5.0, smaa_mas=1.0, smia_mas=1.0, pa_deg=0.0, t=old)}, fh)
ns["_SIGMA_TABLE"].append({247102: 40.0})
p = ns["cached_path_error"]("5335", "2026-12-01T03:00:00")        # nearest day 11-29, scaled by 3/2
assert p["from"] == "cache 2026-11-29" and abs(p["sigma3_km"] - 45.0) < 1e-9 and p["smaa_mas"] == 10.0, p
assert "t" not in p
p = ns["cached_path_error"]("5335", "2026-12-05T00:00:00")        # distance not covered: as cached
assert p["from"] == "cache 2026-11-29" and p["sigma3_km"] == 30.0, p
assert ns["cached_path_error"]("617+S1", "2026-12-29T00:00:00")["from"] == "cache 2026-12-30"   # a body: its system
p = ns["cached_path_error"]("247102", "2026-12-01T00:00:00")      # not cached: the sigma table (1 sigma x 3)
assert p["from"] == "table" and p["sigma3_km"] == 120.0 and p["smaa_mas"] is None, p
assert ns["cached_path_error"]("5335", "2027-03-01T00:00:00") is None    # > 30 days from any cached day: default
assert ns["cached_path_error"]("2026 ED138", "2026-12-01T00:00:00") is None
print("LOCAL ONLY TESTS PASSED")
