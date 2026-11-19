"""Earlier occultations (pysyzygos.occultations): extract from the PDS archive tables, lookup and the display line."""
import _testtmp  # noqa: F401  (temporary files of this run in one folder, removed at exit)
import sys, os, tempfile, json
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
from pysyzygos import occultations as O

d = tempfile.mkdtemp()
summary = ["SEQ_NUM|OBS_DATE|AST_DESIG|AST_NAME|MAJOR_AXIS|MINOR_AXIS|MAJOR_AXIS_PA|FIT_QUAL_CODE|USED_ASSUMED_DIA_FLAG|"
           "MAJOR_AXIS_UNCERT|MINOR_AXIS_UNCERT",
           "1|1991-05-01|5|Astraea|108.0|108.0|0|2|1|1|1",           # size assumed: not a measured profile
           "2|2008-06-06|5|Astraea|119.1|101.7|30|3|0|2.0|1.5",       # reliable size
           "3|2021-01-01|5|Astraea|110.0|100.0|10|3|0|3|3",           # same quality, later: the best one
           "4|2015-02-02|5|Astraea|50|50|0|1|0|||",                   # astrometry only
           "5|2023-01-31|2727|Paton|8.9|8.9|0|1|1|||",
           "6|2020-01-01|29P|Schwassmann-Wachmann|60|60|0|2|0|||"]   # comet: skipped
diameters = ["Designation|Name|Diameter_Nominal|Uncert|Dia_1|Uncert_1|Events_1|Invalid_1|Model_Source_1|Model_Number_1",
             "5|Astraea|107.8|5.6|108|5|6|0|DAMIT|123"]
open(os.path.join(d, "AsteroidSummary_2024Mar.psv"), "w").write("\n".join(summary) + "\n")
open(os.path.join(d, "AsteroidDiameters_2024Mar.psv"), "w").write("\n".join(diameters) + "\n")
out = os.path.join(d, "occ.json")
assert O.build(d, out) == 2                                           # Astraea and Paton, no comet
O._DATA = None
O.FILE = out
O.load(out)
a = O.lookup(5)
assert a["n"] == 4 and a["first"] == "1991-05-01" and a["last"] == "2021-01-01" and a["q"] == {"2": 1, "3": 2, "1": 1}
assert a["best"]["date"] == "2021-01-01" and a["best"]["q"] == 3
assert a["shape_dia"]["d"] == 107.8 and a["shape_dia"]["events"] == 6 and a["shape_dia"]["models"] == ["DAMIT 123"]
t = O.text(5)
assert "4 events 1991-2021" in t and "shape-model diameter 107.8 ± 5.6 km (6 events)" in t, t
assert "best profile 2021-01-01: 110 × 100 km (reliable size)" in t and "to 2023-01" in t, t
assert O.text("2727").endswith("1 event 2023 (1 astrometry only)"), O.text("2727")
assert O.text("30819").endswith("none observed yet")
assert json.load(open(out))["meta"]["doi"] == "10.26033/ehqs-jp27"
print("OCCULTATION TESTS PASSED")
