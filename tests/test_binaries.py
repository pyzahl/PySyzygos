"""Known asteroid satellites (pysyzygos.binaries): extract from the two PDS archives, the satellite zone, the labels."""
import _testtmp  # noqa: F401  (temporary files of this run in one folder, removed at exit)
import sys, os, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
from pysyzygos import binaries as B

d = tempfile.mkdtemp()
# Johnston's compilation: fixed-width table, layout in its PDS4 label (1-based field_location)
fields = [("AST_NUMBER", 1, 7), ("AST_NAME", 9, 16), ("COMPANION_DESIGNATION", 26, 20), ("PRIMARY_DIAMETER", 47, 8),
          ("COMPANION_DIAMETER", 56, 8), ("BINARY_SEMIMAJOR_AXIS", 65, 11), ("BINARY_ORBITAL_PERIOD", 77, 11)]
label = "<Table_Character>" + "".join(
    f"<Field_Character><name>{n}</name><field_location unit='byte'>{loc}</field_location>"
    f"<field_length unit='byte'>{ln}</field_length></Field_Character>" for n, loc, ln in fields) + "</Table_Character>"
def row(*vals):
    out = ""
    for (n, loc, ln), v in zip(fields, vals):
        out = out.ljust(loc - 1) + str(v).rjust(ln) if n not in ("AST_NAME", "COMPANION_DESIGNATION") \
            else out.ljust(loc - 1) + str(v).ljust(ln)
    return out
tab = "\n".join([row(22, "Kalliope", "I Linus", "166.20", "28.00", "1.099E+03", "3.596E+00"),
                 row(87, "Sylvia", "I Romulus", "271.00", "10.80", "1.351E+03", "3.650E+00"),
                 row(87, "Sylvia", "II Remus", "271.00", "10.60", "7.020E+02", "-9.99E+00"),
                 row(0, "", "S/2000 X", "1.0", "0.3", "2.0E+00", "1.0")]) + "\n"
os.makedirs(os.path.join(d, "bin"))
open(os.path.join(d, "bin", "binarytable.xml"), "w").write(label)
open(os.path.join(d, "bin", "binarytable.tab"), "w").write(tab)
rows = B.read_compilation(os.path.join(d, "bin"))
assert len(rows) == 4 and rows[0]["companion"] == "I Linus" and rows[0]["a_km"] == 1099.0 and rows[2]["period_d"] is None
# occultations archive: satellites seen in events
os.makedirs(os.path.join(d, "occ"))
open(os.path.join(d, "occ", "Asteroid_2024Mar.psv"), "w").write(
    "SEQ_NUM|OBS_DATE|AST_DESIG|AST_NAME|SAT_NAME_1|SAT_SEP_1|SAT_PA_1|SAT_MAJOR_1|SAT_MINOR_1|SAT_SEP_2\n"
    "1|2006-11-07|22|Kalliope|(22) 1 = Linus|246|10|28|28|\n"
    "2|1977-03-05|6|Hebe||524.3|0|||\n"
    "3|2020-01-01|5|Astraea||0.0|0|||\n")
out = os.path.join(d, "bin.json")
assert B.build(os.path.join(d, "bin"), os.path.join(d, "occ"), out) == 3          # 22, 87, 6 (not 0, not 5)
B._DATA = None
B.load(out)
assert B.short(22) == "+moon" and B.short("87") == "+2 moons" and B.short(6) == "+moon?" and B.short(5) == ""
assert B.zone_km(22) == 1099.0 + 14.0 and B.zone_km(87) == 1351.0 + 5.4 and B.zone_km(6) is None
t = B.text(22)
assert t.startswith("Satellites (Johnston 2019): Linus D 28 km, 1099 km from the primary, period 3.60 d"), t
assert "seen in occultations: 2006-11-07 at 246 mas ((22) 1 = Linus)" in t, t
assert "not confirmed" in B.text(6) and B.text(5) == ""
print("BINARY TESTS PASSED")
