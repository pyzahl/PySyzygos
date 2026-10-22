"""search.py orbit files: a cached file of another window is reused when it covers the search window and is at most
orbit_max_age_days old (never one of another asteroid or one too old); horizons_up() says False at once for a host that
refuses connections and stays False for the run. The functions are taken from search.py's source (it is not
import-safe); no network, no SPICE."""
import ast, os, sys, tempfile, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
from pathlib import Path
from types import SimpleNamespace

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src', 'pysyzygos', 'search.py')
tree = ast.parse(open(SRC, encoding="utf-8").read())
WANT = {"_spk_file", "_spk_stale", "_fresh_spk", "horizons_up", "HORIZONS"}
code = [n for n in tree.body if getattr(n, "name", None) in WANT
        or isinstance(n, ast.Assign) and any(getattr(t, "id", None) in WANT for t in n.targets)]
assert len(code) == len(WANT), [getattr(n, "name", None) for n in code]
cache = tempfile.mkdtemp()
config = SimpleNamespace(cache_path=cache, orbit_max_age_days=3)
U = SimpleNamespace(URL_JPL_HORIZONS_API="https://127.0.0.1:1/api/horizons.api")      # port 1: refused at once
ns = dict(config=config, Path=Path, time=time, os=os, U=U, print=lambda *a, **k: None)
exec(compile(ast.Module(code, []), SRC, "exec"), ns)


def make(name, age_days=0.0):
    p = os.path.join(cache, name)
    open(p, "w").write("x")
    t = time.time() - age_days * 86400
    os.utime(p, (t, t))
    return p


ep = {"start": "2026-10-20", "stop": "2026-10-27"}
assert ns["_fresh_spk"]("3200", ep) is None                                       # nothing cached
make("PySyzygos_asteroid_32000_2026-10-19_2026-11-10.bsp")                        # another asteroid
make("PySyzygos_asteroid_3200_2026-10-22_2026-11-10.bsp")                         # does not cover the start
assert ns["_fresh_spk"]("3200", ep) is None
old = make("PySyzygos_asteroid_3200_2026-10-01_2026-11-30.bsp", age_days=5)       # covers, but older than 3 days
assert ns["_fresh_spk"]("3200", ep) is None
wide = make("PySyzygos_asteroid_3200_2026-10-19_2026-11-10.bsp", age_days=1.2)   # yesterday's longer search
assert str(ns["_fresh_spk"]("3200", ep)) == wide
own = make("PySyzygos_asteroid_3200_2026-10-20_2026-10-27.bsp", age_days=0.1)    # the window's own file first
assert str(ns["_fresh_spk"]("3200", ep)) == own
os.utime(own, (time.time() - 4 * 86400,) * 2)                                     # own too old: the covering one
assert str(ns["_fresh_spk"]("3200", ep)) == wide
config.orbit_max_age_days = 1                                                     # stricter: none of them
assert ns["_fresh_spk"]("3200", ep) is None

t0 = time.time()
assert ns["horizons_up"]() is False and time.time() - t0 < 5                      # refused: no waiting
U.URL_JPL_HORIZONS_API = "https://localhost/never-asked"
assert ns["horizons_up"]() is False and ns["HORIZONS"] == {"up": False}           # probed once per run
print("ORBIT CACHE TESTS PASSED")
