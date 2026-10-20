"""Planets and moons as targets (pysyzygos.bodies): prefixes, kinds, deflectors, size and brightness rules, and the
kernel built from Horizons vectors. No network and no SPICE: stand-ins follow the real call contracts."""
import sys, os, tempfile, types
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
from pysyzygos import bodies as B

# prefixes: readable, case-insensitive, never an asteroid number
assert B.parse("M:Io")["naif"] == 501 and B.parse("m:io")["alias"] == "M:IO" and B.parse("P:Jupiter")["kind"] == "planet"
assert B.parse("P:Io") is None, "Io is a moon, not a planet"
assert B.parse("501") is None and B.parse("218001") is None and B.parse("X:Io") is None and B.parse("M:") is None
assert B.kind("M:Ganymede") == "moon" and B.kind("30819") == "asteroid" and B.name("m:callisto") == "Callisto"
assert B.GROUPS["jupiter"][0] == "P:Jupiter" and {"M:Io", "M:Europa", "M:Ganymede", "M:Callisto"} <= set(B.GROUPS["jupiter"])
assert all(B.parse(t) for g in B.GROUPS.values() for t in g), "every group member resolves"
assert set(B.GROUPS) == {"mars", "jupiter", "saturn", "uranus", "neptune", "pluto"}
major, small = B.featured("jupiter")
assert major[0] == "P:Jupiter" and "M:Ganymede" in major and all((B.parse(t)["radius_km"] or 0) < 150 for t in small)
assert B.parse("P:Pluto")["kind"] == "dwarf" and B.parse("M:Titan")["center"] == 6 and B.deflectors("M:Titan") == ("10", "5")
# the satellite table: Horizons values, estimates flagged, unusable ones left out of the groups
if B.parse("M:Himalia"):
    assert B.parse("M:Himalia")["naif"] == 506 and 70 < B.parse("M:Himalia")["radius_km"] < 100
    assert all(B.usable(B.parse(t)) for t in B.GROUPS["jupiter"])
sats = B.fill_estimates([dict(naif=518, name="X", radius_km=None, h=14.0), dict(naif=618, name="Y", radius_km=10.0, h=None),
                         dict(naif=55501, name="Z", radius_km=None, h=None)])
assert sats[0]["radius_est"] and abs(sats[0]["radius_km"] * 2 - 1329 / 0.05 ** 0.5 * 10 ** (-14 / 5)) < 0.1
assert sats[1]["h_est"] and sats[1]["h"] > 0 and sats[2]["radius_km"] is None and sats[2]["h"] is None

# light deflection: the target's own system is left out
assert B.deflectors("30819") == ("10", "5", "6") and B.deflectors("M:Io") == ("10", "6") and B.deflectors("P:Jupiter") == ("10", "6")
assert B.sigma3_km("M:Io") > 0 and B.sigma3_km("30819") is None

# size and brightness rules
spice = types.SimpleNamespace(bodvrd=lambda body, item, n: (3, [71492.0, 71492.0, 66854.0] if body == "599" else [1829.4, 1819.4, 1815.7]))
j, io = B.size(spice, "P:Jupiter"), B.size(spice, "M:Io")
assert j["r_km"] == 71492.0 and j["r_min_km"] == 66854.0 and j["H"] is None, "planet: equatorial radius, no H (no drop filter)"
assert abs(io["r_km"] - np.mean([1829.4, 1819.4, 1815.7])) < 1e-9 and io["H"] == B.parse("M:Io")["h"] and io["G"] == B.MOON_G
assert abs(io["H"] - (-1.68)) < 0.3, "Io's H within 0.3 mag of the literature V(1,0)"

# the kernel: Horizons vectors -> type 13 segment, alias set, cached
calls, written = [], []
B._horizons_states = lambda naif, center, start, stop, step_min=20, timeout=120: (
    calls.append((naif, center, start, stop)) or (np.array([0.0, 1200.0, 2400.0]), np.zeros((3, 6))))
class Spice:
    def et2utc(self, et, f, p): return "2026-10-%02dT00:00:00" % (8 + int(et // 86400))
    def spkopn(self, path, name, n): open(path, "w").close(); return 1
    def spkw13(self, h, body, center, frame, first, last, segid, degree, n, states, epochs):
        written.append((body, center, frame, degree, n))
    def spkcls(self, h): pass
    def furnsh(self, path): written.append(("furnsh", os.path.basename(path)))
    pool = {}
    def pcpool(self, name, values): Spice.pool[name] = list(values)        # kernel pool (kernels.body_alias)
    def pipool(self, name, values):
        Spice.pool[name] = list(values)
        for n, c in zip(Spice.pool["NAIF_BODY_NAME"], values):
            written.append(("alias", n, c))
    def bodn2c(self, name):
        names = Spice.pool.get("NAIF_BODY_NAME", [])
        if name not in names:
            raise Exception("SPICE(NOTFOUND)")
        return Spice.pool["NAIF_BODY_CODE"][names.index(name)]
cache = tempfile.mkdtemp()
p = B.ensure_kernel(Spice(), "M:Io", 2 * 86400.0, 4 * 86400.0, cache)
assert os.path.isfile(p) and calls == [(501, 5, "2026-10-08", "2026-10-14")], calls
assert (501, 5, "J2000", 7, 3) in written and ("alias", "M:IO", 501) in written
B.ensure_kernel(Spice(), "M:Io", 2 * 86400.0, 4 * 86400.0, cache)
assert len(calls) == 1, "cached: Horizons asked once"
# the optional NAIF kernel: used (no Horizons) when it covers the window, else Horizons as before
local = tempfile.mkdtemp()
open(os.path.join(local, "jup365.bsp"), "w").close()
class LocalSpice(Spice):
    def __init__(self, lo, hi): self.lo, self.hi = lo, hi
    def spkcov(self, path, idcode): return ("cov", idcode)
    def wncard(self, cov): return 1
    def wnfetd(self, cov, i): return (self.lo, self.hi)
calls.clear(); written.clear()
p = B.ensure_kernel(LocalSpice(-1e10, 1e10), "M:Europa", 0.0, 86400.0, tempfile.mkdtemp(), folder=local)
assert p.endswith("jup365.bsp") and calls == [] and ("alias", "M:EUROPA", 502) in written
p = B.ensure_kernel(LocalSpice(0.0, 10.0), "M:Europa", 0.0, 86400.0, tempfile.mkdtemp(), folder=local)
assert not p.endswith("jup365.bsp") and len(calls) == 1, "window not covered: Horizons"
assert B.naif_kernel("jupiter", local).endswith("jup365.bsp") and B.naif_kernel("jupiter", tempfile.mkdtemp()) is None
print("BODIES TESTS PASSED")
