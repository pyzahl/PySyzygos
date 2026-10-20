"""steps.py: step table and the machine-readable summary line (parts listed under their step, 'other' for the
rest, wrapped functions counted and timed, parse), as pick, search and the GUI use them."""
import io, os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
from pysyzygos import steps as ST

S = ST.Steps("search")
S.t0 = time.time() - 10.0                                   # the command started 10 s ago
S.add("hit: path uncertainty", 2.0, 4, "hits", group="pass 2")   # a part, added before its step
S.add("start-up", 1.0)
f = S.wrap("exact solve", lambda x: x * 2, "solves", group="pass 2")
assert f(3) == 6 and f(4) == 8
S.add("pass 2", 6.0, 12, "candidates")
with S.step("results", 3, "events"):
    pass
sm = S.summary()
names = [r["name"] for r in sm["steps"]]
assert names[:5] == ["start-up", "pass 2", "hit: path uncertainty", "exact solve", "results"], names
assert names[-1] == "other" and 2.9 < sm["steps"][-1]["s"] < 3.1           # 10 - (1 + 6 + ~0)
r = {x["name"]: x for x in sm["steps"]}
assert r["exact solve"]["n"] == 2 and r["exact solve"]["group"] == "pass 2" and r["hit: path uncertainty"]["n"] == 4
out = io.StringIO()
S.emit(out)
lines = out.getvalue().splitlines()
assert lines[1].startswith("Steps of this search") and any(l.startswith("    hit: path uncertainty") for l in lines)
back = ST.parse(lines[-1])
assert back["tool"] == "search" and [x["name"] for x in back["steps"]] == names
assert ST.parse("other text") is None and ST.parse(ST.MARK + "{broken") is None
S2 = ST.Steps("x")
S2.add("pass 1", 0.0)                                       # placeholder: fixes the order
S2.add("pass 1", 2.0, 8, "asteroids")
assert S2.summary()["steps"][0] == dict(name="pass 1", s=2.0, n=8, unit="asteroids", group="")
print("STEPS TESTS PASSED")
