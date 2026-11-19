"""Sensor list (pysyzygos.cameras): sizes from pixels x pixel size, labels for the Site tab's list."""
import _testtmp  # noqa: F401  (temporary files of this run in one folder, removed at exit)
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
from pysyzygos import cameras as C

names = [s[0] for s in C.SENSORS]
assert len(names) == len(set(names)), "one entry per sensor"
for s in C.SENSORS:
    w, h = C.sensor_mm(s)
    assert 3.0 < w < 40.0 and 2.0 < h < 30.0 and w >= h, (s, w, h)
    lab = C.label(s)
    assert lab.startswith(s[0] + ":") and lab.endswith(f"({s[4]})"), lab
    if s[1]:
        assert abs(w - s[1] * s[3] / 1000) < 0.01 and abs(h - s[2] * s[3] / 1000) < 0.01
        assert f"{s[1]} x {s[2]} px" in lab and "µm" in lab
find = lambda text: [s[0] for s in C.SENSORS if text.lower() in C.label(s).lower()]    # as the list's search
assert find("QHY174") == ["Sony IMX174"] and find("dvti") == ["Sony IMX174", "Sony IMX430 mono"]
assert find("astrid") == ["Sony IMX296 mono, global shutter"] and find("QHY600") == ["Sony IMX455"]
assert C.sensor_mm(next(s for s in C.SENSORS if s[0] == "Sony IMX290")) == (5.61, 3.18)   # the form's 5.6 x 3.2
print("CAMERA TESTS PASSED")
