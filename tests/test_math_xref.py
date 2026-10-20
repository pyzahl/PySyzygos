"""docs/math/check_xref.py: the code's '# Math:' comments cite only formulas and slides that exist on the math
slides (docs/math/math_slides.tex); a wrong reference, a reused formula number and a comment without a function
below are reported. Pure text, no LaTeX needed."""
import os, runpy, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
X = runpy.run_path(os.path.join(HERE, "..", "docs", "math", "check_xref.py"))

errors, uncited, rows, ids = X["check"]()
assert not errors, "\n".join(errors)
assert {"ST1", "ST2", "AS", "IN", "OB", "LT", "FG", "FP", "CA", "OV"} <= set(ids)
assert "search.besselian_offsets" in rows["FP.1"] and "astrometry.deflect" in rows["ST2.2"]

# stand-ins: slides with two formulas, code with a good, a wrong and a dangling reference
d = tempfile.mkdtemp()
tex = os.path.join(d, "s.tex")
open(tex, "w").write("\\begin{frame}{Plane}\\slideid{FP}\n\\[ x \\tag{FP.1} \\]\n$y$\\eqtag{FP.2}\n\\end{frame}\n")
src = os.path.join(d, "src")
os.makedirs(src)
open(os.path.join(src, "m.py"), "w").write(
    "# Math: FP.1-FP.2 (slide FP): ok\ndef good():\n    pass\n\n"
    "# Math: FP.3 (slide XY): wrong\ndef bad():\n    pass\n\n"
    "# Math: FP.1\nx = 1\n")
errors, uncited, rows, ids = X["check"](tex, src)
assert rows["FP.1"] == ["m.good", "m.?"] and rows["FP.2"] == ["m.good"] and not uncited
assert any("FP.3 is not on the slides" in e for e in errors) and any("slide XY does not exist" in e for e in errors)
assert any("no function right below" in e for e in errors) and len(errors) == 3
open(tex, "a").write("\\[ z \\tag{FP.1} \\]\n")
try:
    X["slides"](tex)
    raise AssertionError("a reused formula number must be refused")
except SystemExit as e:
    assert "used twice" in str(e)
print("MATH XREF TESTS PASSED")
