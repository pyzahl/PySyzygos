"""components.py: a binary asteroid's bodies (JPL ids, SPICE names, sizes from Johnston's list, names, the summary
table); no SPICE, no network."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
from pysyzygos import components as K

assert K.naif_id(617, 9) == 920000617 and K.naif_id("617", 1) == 120000617 and K.naif_id(617, 2) == 220000617
assert K.alias(617, "primary") == "617+P" and K.alias(617, "satellite I") == "617+S1" and K.alias(617, "satellite II") == "617+S2"
sz = K.sizes(617)                                              # Johnston: Patroclus 106 km, Menoetius 98 km
assert sz == {"primary": 53.0, "satellite I": 49.0}, sz
assert K.sizes(5) == {}
assert K.short_name(dict(kind="satellite I", name="(617) Patroclus I Menoetius")) == "Menoetius"
assert K.short_name(dict(kind="primary", name="617"), "617") == "Patroclus"
assert K.available("2026 ED138") == [] and K.available("12345678") == []     # numbered, < 1e7 only (no network)
out = dict(name="617 Patroclus", event_utc="2026-01-04T22:45:09", site=dict(name="Seewis"), sigma3_km=123.0,
           made="2026-11-04T00:00:00", bodies=[
               dict(kind="primary", name="Patroclus", naif=920000617, r_km=53.0, dx_km=190.8, dy_km=33.8,
                    ca_utc="2026-01-04T22:45:24.00", ca_km=460.9, inside=False, outside_km=407.9),
               dict(kind="satellite I", name="Menoetius", naif=120000617, r_km=49.0, dx_km=-367.0, dy_km=152.3,
                    ca_utc="2026-01-04T22:43:53.10", ca_km=14.3, inside=True, d_utc="2026-01-04T22:43:41.12",
                    r_utc="2026-01-04T22:44:05.08", duration_s=23.97)])
md = K.markdown(out)
assert "| Menoetius (satellite I) | -367.0, +152.3 | 22:43:53.10 | 14.3 | 49.0 | **inside**: D 22:43:41.12" in md, md
assert "outside by 407.9 km" in md and "920000617, 120000617" in md
# a body as a search target: ids, system, kind; sizes and brightness for the search; pick margins
assert K.is_component("617+P") and K.is_component("617+S1") and not K.is_component("617") and not K.is_component("P:Io")
assert K.system("617+S1") == "617" and K.system("218001") == "218001" and K.kind_of("617+S1") == "satellite I"
assert K.kind_of("617+P") == "primary" and K.kind_of("617") == ""
bs = K.body_size("617+S1", dict(H=8.22, G=0.15))
import math
assert bs["r_km"] == 49.0 and abs(bs["H"] - (8.22 - 2.5 * math.log10(49.0 ** 2 / (53.0 ** 2 + 49.0 ** 2)))) < 1e-9, bs
assert K.body_size("617+S2", {}) is None
assert "617" in K.known("/nonexistent") and K.pick_margin_km("617") > 688 and K.pick_margin_km("218001") == 0.0
from pysyzygos import report as R
assert R.target_label("617+S1", "(617) Patroclus I Menoetius") == "(617) Patroclus I Menoetius"
assert R.sbdb_id("617+P") == "617" and "satellite I" in R.binary_mark("617+S1") and R.part_badge("617") == ""
from pysyzygos import obsreport as O
assert O._name_parts("617+S1", "(617) Patroclus I Menoetius") == ("617", "Patroclus")
print("COMPONENTS TESTS PASSED")
