"""report.kml_to_data: the map data of a paths KML; a path across the date line stays one continuous line (a web map
would otherwise draw the step from -179.8 to +178.8 deg as a straight line across the whole map: a false second
"path"), placed next to the observer; minute marks follow their line."""
import _testtmp  # noqa: F401  (temporary files of this run in one folder, removed at exit)
import os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
from pysyzygos import report as R

lons = [-33.4, -60.0, -100.0, -140.0, -179.8, 178.8, 171.0]
lats = [16.8, 30.0, 40.0, 41.0, 40.5, 40.0, 36.4]
coords = " ".join(f"{lo},{la},0" for lo, la in zip(lons, lats))
kml = (f'<kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
       f'<Placemark><name>Centre line</name><LineString><coordinates>{coords}</coordinates></LineString></Placemark>'
       f'<Placemark><name>09:09 UTC</name><Point><coordinates>171.0,36.4,0</coordinates></Point></Placemark>'
       f'<Placemark><name>Observer</name><Point><coordinates>-72.86,40.87,0</coordinates></Point></Placemark>'
       f'</Document></kml>')
path = os.path.join(tempfile.mkdtemp(), "t.kml")
open(path, "w").write(kml)
d = R.kml_to_data(path)
pts = d["lines"][0]["pts"]
assert max(abs(b[1] - a[1]) for a, b in zip(pts, pts[1:])) < 50, "no jump across the map"
assert pts[0][1] == -33.4 and abs(pts[5][1] - (178.8 - 360)) < 1e-6 and abs(pts[-1][1] - (171.0 - 360)) < 1e-6
mark = next(p for p in d["pins"] if p["name"] == "09:09 UTC")
assert abs(mark["lon"] - (171.0 - 360)) < 1e-6, "the minute mark stays on its line"
assert next(p for p in d["pins"] if p["name"] == "Observer")["lon"] == -72.86
print("KML MAP TESTS PASSED")
