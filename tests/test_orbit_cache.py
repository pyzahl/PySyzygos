"""search.py orbit files: a cached file of another window is reused when it covers the search window and is at most
orbit_max_age_days old (never one of another asteroid or one too old); horizons_up() says False at once for a host that
refuses connections and stays False for the run; a Horizons server fault (answer without SPK, e.g. "wldini(): missing
required file") marks it down too and raises ConnectionError (so fetch_target_orbit takes cached files), while "No
matches found" stays a per-object error. The functions are taken from search.py's source (it is not import-safe); no
network, no SPICE."""
import ast, os, sys, tempfile, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
from pathlib import Path
from types import SimpleNamespace

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src', 'pysyzygos', 'search.py')
tree = ast.parse(open(SRC, encoding="utf-8").read())
WANT = {"_spk_file", "_spk_stale", "_fresh_spk", "horizons_up", "HORIZONS", "HORIZONS_FAULTS", "_horizons_spk", "horizons_command",
        "WARNINGS", "OLD_ORBITS"}
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


class ConnErr(Exception):
    pass


class Resp:
    status_code = 200

    def __init__(self, data):
        self.data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self.data


ANSWER = {}
ns["requests"] = SimpleNamespace(ConnectionError=ConnErr, get=lambda *a, **k: Resp(ANSWER["data"]))
ns["base64"] = __import__("base64")
ns["HORIZONS"].clear(); ns["HORIZONS"]["up"] = True
ANSWER["data"] = {"result": "No matches found."}
try:
    ns["_horizons_spk"]("99999999", ep); raise AssertionError("no error")
except RuntimeError as e:
    assert "no such object" in str(e)
assert ns["HORIZONS"]["up"] is True                                               # one object: Horizons stays up
ANSWER["data"] = {"result": "\nwldini(): missing required file LTKERNL\n\n ERROR in VLRDC: Var not declared: IP_ADDR\n"}
try:
    ns["_horizons_spk"]("3200", ep); raise AssertionError("no error")
except ConnErr as e:                                                              # network-like: cached files used
    assert "server error" in str(e)
assert ns["HORIZONS"]["up"] is False and ns["horizons_up"]() is False             # no more requests this run
assert "server error" in ns["WARNINGS"]["horizons"]                                # for the report header
ANSWER["data"] = {"spk": "eHl6"}
assert ns["_horizons_spk"]("3200", ep) == b"xyz"
print("ORBIT CACHE TESTS PASSED")

# run warnings (report header, orange): every fallback and skip of the run, not only in the log
W = {"WARNINGS", "OLD_ORBITS", "NOTED", "NOTE_TEXT", "run_note", "run_warnings", "SKIPPED"}
wcode = [n for n in tree.body if getattr(n, "name", None) in W
         or isinstance(n, ast.Assign) and any(getattr(t, "id", None) in W for t in n.targets)]
wn = dict(sys=sys, EARTH_PCK={})                                   # set at start-up (kernels)
exec(compile(ast.Module(wcode, []), SRC, "exec"), wn)
assert wn["run_warnings"]() == []                                                  # a clean run: no line
wn["WARNINGS"]["horizons"] = "JPL Horizons answered with a server error (wldini() ...)"
wn["OLD_ORBITS"].update({"63": "2026-10-20", "7876": "2026-10-25"})
wn["SKIPPED"].append("204890")
wn["run_note"]("size_stale", "63"); wn["run_note"]("size_stale", "63")             # once per target
wn["run_note"]("skip_size", "1")
w = wn["run_warnings"]()
assert w[0].startswith("JPL Horizons answered with a server error"), w
assert "2 orbit(s) from older cached files (downloaded 2026-10-20 to 2026-10-25)" in w, w
assert "1 asteroid(s) skipped without an orbit: 204890" in w, w
assert any(x.startswith("1 target(s) with size data from an older cache") and x.endswith(": 63") for x in w), w
assert any(x.startswith("1 target(s) skipped without size data") for x in w), w
wn["EARTH_PCK"]["long_term"] = "Earth orientation after 2027-01-20 from the long-term prediction x.bpc"
assert wn["run_warnings"]()[1].startswith("Earth orientation after 2027-01-20"), wn["run_warnings"]()
print("RUN WARNINGS TESTS PASSED")
