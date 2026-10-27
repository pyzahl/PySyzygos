"""Asteroid groups for the pick (picks.GROUPS by JPL's orbit class): parsing, grouping, the SBDB rows carrying class,
PHA and satellites, and a saved pick naming its groups. No network, no SPICE."""
import os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
from pysyzygos import picks as P

assert P.parse_groups("all") == set(P.GROUP_NAMES) == {"main", "trojan", "marscross", "neo", "tno", "other"}
assert P.parse_groups("Trojan, neo,TNO") == {"trojan", "neo", "tno"}
assert P.parse_groups("jupitertrojans,everythingelse") == {"trojan", "other"}             # by name too
try:
    P.parse_groups("hilda")
    raise AssertionError("an unknown group must be refused")
except ValueError:
    pass
assert [P.group_of(c) for c in ("MBA", "IMB", "OMB", "TJN", "MCA", "APO", "AMO", "ATE", "IEO", "TNO", "CEN", "AST", "")] == \
    ["main"] * 3 + ["trojan", "marscross"] + ["neo"] * 4 + ["tno", "other", "other", "other"]

from pysyzygos import pick as K                                                        # rows from SBDB bulk data
fields = K.SBDB_FIELDS
row = lambda spk, cls, pha="N", sats=0: [spk, f"{spk - 20000000} X", "10.5", "0.15", "", "", "", "", "5.2", "0.05", "10",
                                         "0", "0", "0", "2461000.5", "0", "N", cls, pha, sats]
rows = K.build_rows(fields, [row(20000624, "TJN"), row(20099942, "ATE", "Y"), row(20000022, "MBA", sats=1)], 17.0)
by = {r["number"]: r for r in rows}
assert by[624]["group"] == "trojan" and by[99942]["group"] == "neo" and by[99942]["pha"] and by[22]["sats"] == 1
assert by[22]["group"] == "main" and by[624]["cls"] == "TJN"

# a saved pick with its groups: described as such (the Search tab names the pick it uses)
d = dict(site="S", start="2026-10-25", days=7.0, picked="", targets=["1"], groups=["trojan", "tno"])
assert P.describe(d).endswith(", groups Jupiter Trojans, TNO") and "groups" not in P.describe(dict(d, groups=None))
assert P.describe(dict(d, a_min=3.7, a_max=4.2)).endswith(", a 3.7-4.2 AU")             # a semi-major-axis range
assert P.describe(dict(d, groups=None, a_min=None, a_max=5.4)).endswith(", a -5.4 AU")
assert P.describe(dict(d, a_min=2.0, a_max=3.3, a_exclude=True)).endswith(", not a 2.0-3.3 AU")
assert by[624]["a"] == 5.2                                                             # rows carry a (AU)
# the live count (Pick tab): from a stand-in of the pick's cached SBDB list
import json
tmp = tempfile.mkdtemp()
cache = os.path.join(tmp, "PySyzygos_sbdb_cache.json")
data = [row(20000001, "MBA"), row(20000002, "MBA"), row(20000624, "TJN"), row(20099942, "ATE")]
data[0][fields.index("a")] = "2.2"; data[1][fields.index("a")] = "3.9"; data[3][fields.index("a")] = "0.92"
data[3][fields.index("H")] = "19.1"
data.append(row(20000005, "MBA")); data[-1][fields.index("e")] = "1.2"                   # unbound: not counted
json.dump(dict(fields=fields, data=data, hmax=99.0, full_prec=True), open(cache, "w"))
idx = P.count_index(cache)
assert P.count(idx) == (4, 4) and P.count(idx, 17) == (3, 3)
assert P.count(idx, None, ["neo"]) == (1, 4) and P.count(idx, 17, ["main"], 3.7, 4.2) == (1, 3)
assert P.count(idx, 17, None, 2.0, 3.3, True) == (2, 3)                                    # outside 2.0-3.3: 3.9 and 5.2
assert P.count_index(os.path.join(tmp, "missing.json")) is None

# the selection (pick and pre-screen build alike) and whether a restricted pre-screen holds a pick's asteroids
sel = P.selection
assert sel() == dict(groups=None, a_min=None, a_max=None, a_exclude=False) and not P.restricted(sel())
assert sel(set(P.GROUP_NAMES)) == sel() and sel(None, None, None, True)["a_exclude"] is False   # no range: no exclude
hv = sel({"neo", "tno", "trojan"})
assert P.restricted(hv) and hv["groups"] == ["neo", "tno", "trojan"]
assert P.selection_tag(hv) == "trojan-neo-tno" and P.selection_text(hv) == "groups Jupiter Trojans, NEO, TNO"
assert P.selection_tag(sel(["main"], 2.0, 3.0, True)) == "main_not-a2-3" and P.selection_tag(sel(None, 3.7)) == "a3.7-"
rows = [dict(group="main", a=2.5), dict(group="main", a=3.9), dict(group="neo", a=1.2), dict(group="trojan", a=5.2)]
assert [r["a"] for r in P.select_rows(rows, hv)] == [1.2, 5.2]
assert [r["a"] for r in P.select_rows(rows, sel(None, 3.7, 4.2))] == [3.9]
assert [r["a"] for r in P.select_rows(rows, sel(None, 2.0, 3.0, True))] == [3.9, 1.2, 5.2]
cov = P.selection_covers
assert cov(None, None) == [] and cov(None, hv) == []                         # a full pre-screen holds every pick
assert cov(hv, sel({"neo"})) == [] and cov(hv, hv) == []                      # fewer groups: fits
assert cov(hv, sel()) and "Main belt" in cov(hv, sel())[0]                    # all groups: would miss main belt events
assert cov(hv, sel({"neo", "main"})) and cov(hv, sel({"neo"}, 1.0, 2.0)) == []
hil = sel(None, 3.7, 4.2)                                                     # a pre-screen of the Hildas
assert cov(hil, sel(None, 3.8, 4.0)) == [] and cov(hil, sel(None, 3.6, 4.0)) and cov(hil, sel()) and \
    cov(hil, sel(None, 3.8, 4.0, True))
nomb = sel(None, 2.0, 3.3, True)                                              # all but the core main belt
assert cov(nomb, sel(None, 3.7, 4.2)) == [] and cov(nomb, sel(None, 1.5, 3.3, True)) == []
assert cov(nomb, sel(None, 3.0, 4.2)) and cov(nomb, sel(None, 2.5, 3.0, True)) and cov(nomb, sel())
print("PICK GROUPS TESTS PASSED")
