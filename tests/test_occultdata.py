"""occultdata.py: the optional Occult data add-on. Synthetic files in the published layouts (diameters with the
uncertainties at byte 2n, 9-byte survey records, the magnitudes CSV by column position, binaries, the observation
archive XML, Gaia doubles with an RA wrap), download through a stand-in (only the expected files of the zip are
written), import from an Occult folder, update check, removal, and occultations.py using the add-on's archive."""
import io, json, os, struct, sys, tempfile, zipfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
import numpy as np
from pysyzygos import occultdata as O, occultations as OC

base = tempfile.mkdtemp()
d = O.folder(base)
os.makedirs(d)

# AsteroidDiameters.bin: int16 dia x 10 for numbers 1..n, then uint8 uncertainty x 5 from byte 2n
n = 10
dia = np.zeros(n, "<i2")
unc = np.zeros(n, "u1")
dia[0], unc[0] = 9520, 0                       # (1): 952 km, no uncertainty (spacecraft)
dia[3], unc[3] = 51, 5                         # (4): 5.1 +- 1.0 km
dia[7] = -16                                   # (8): 1.6 km from H
open(os.path.join(d, "AsteroidDiameters.bin"), "wb").write(dia.tobytes() + unc.tobytes())
assert O.diameter(4, base) == dict(d=5.1, u=1.0, from_h=False)
assert O.diameter("8", base) == dict(d=1.6, u=0.0, from_h=True)
assert O.diameter(2, base) is None and O.diameter(11, base) is None and O.diameter("x", base) is None

# AsteroidDiametersAll.bin: 9-byte records sorted by number (num, dia, unc x 2.5, source, albedo x 500)
rec = b"".join(struct.pack("<ihBBB", *r) for r in [(1, 9520, 0, 0, 75), (1, 10416, 213, 2, 35), (4, 51, 2, 1, 214)])
open(os.path.join(d, "AsteroidDiametersAll.bin"), "wb").write(rec)
a1 = O.diameters_all(1, base)
assert [x["source"] for x in a1] == ["spacecraft", "AKARI AcuA"] and a1[1]["d"] == 1041.6 and a1[1]["u"] == 85.2
assert O.diameters_all(4, base)[0]["albedo"] == 0.428 and O.diameters_all(5, base) == []

# magnitudes: by position (the header repeats names), V from g and r
open(os.path.join(d, "HGsHG1G2_Magnitudes.csv"), "w", encoding="utf-8").write(
    "Asteroid,H0green, H0±, G, H0red, H0±, G, H0green\n4,13.73,0.1,0.26,13.10,0.1,0.25\n")
m = O.magnitudes(4, base)
assert m["Hg"] == 13.73 and m["Gr"] == 0.25 and m["HV"] == round(13.73 - 0.03 - 0.42 * (13.73 - 13.10), 2)
assert O.magnitudes(5, base) is None

# binaries
open(os.path.join(d, "BinaryAsteroids.csv"), "w").write(
    "Number,Name,Satellite name,Dia(km),a,Period(days),e,i,epoch,MA,peri,node,RefFrame\n"
    "4,Vesta,Test,28,1098.600,3.595606,,94.18,2457754.50,323.200,,284.30, 2\n")
open(os.path.join(d, "BinaryAsteroid_SatelliteNames.txt"), "w").write("(4) 1 = Test\n")
b = O.binaries(4, base)
assert b[0]["satellite"] == "Test" and b[0]["a_km"] == 1098.6 and b[0]["e"] is None and b[0]["ref_frame"] == 2

# observation archive: best = quality >= 2 with measured (not assumed) axes; good shape fits -> median diameter
xml = """<AsteroidOccultations><FileVersion>2.15</FileVersion>
<Event><Date>2019|7|29|11.3</Date><Details><Asteroid>4|Vesta|0|0|0|0|0|0|0|0|5.0|0.4|16</Asteroid>
 <EventFits><EllipticFit>-0.2|-0.1|5.8|4.7|118.8|3|0|0|0|0</EllipticFit><EllipseUncertainty>0.08|0.06|0.16|0.20|8.6</EllipseUncertainty>
 </EventFits><ShapeModelFit><Fit>DAMIT|1|1.02|6|0|5.2|5.4|x</Fit></ShapeModelFit></Details></Event>
<Event><Date>2021|10|3|17.0</Date><Details><Asteroid>4|Vesta|0|0|0|0|0|0|0|0|5.0|0.4|16</Asteroid>
 <EventFits><EllipticFit>0|0|5.0|5.0|0|1|1|0|0|0</EllipticFit><EllipseUncertainty>||||</EllipseUncertainty></EventFits>
 </Details></Event>
<Event><Date>1822|5|20|22.4</Date><Details><Asteroid>P4M00|Mars|0</Asteroid>
 <EventFits><EllipticFit>0|0|6787|6787|0|0|1|0|0|0</EllipticFit></EventFits></Details></Event>
</AsteroidOccultations>"""
open(os.path.join(d, "Asteroid~Observations.xml"), "w").write(xml)
open(os.path.join(d, "FileFormat AsteroidObservations.htm"), "w").write("<html></html>")
assert O.build_observations(d) == 1                                    # Mars (not numbered) left out
obs = json.load(open(O.observations_file(base)))
v = obs["asteroids"]["4"]
assert v["n"] == 2 and v["q"] == {"3": 1, "1": 1} and v["best"]["major"] == 5.8 and v["best"]["date"] == "2019-07-29"
assert v["shape_dia"]["d"] == 5.3 and obs["meta"]["events_until"] == "2021-10-03"
OC._DATA = None
OC.load(O.observations_file(base))
t = OC.text(4)
assert t.startswith("Occultations (IOTA / Occult archive, to 2021-10-03): 2 events 2019-2021") and "(1 event," in t
OC._DATA = None

# Gaia non-single stars: index by RA, cone with the RA wrap at 0/360
open(os.path.join(d, "Gaia_Doubles.csv"), "w").write(
    "RA, Dec, Gmag, Semimajor, Period(d), ID, Model\n359.99990,10.0,11.0,.5,100,1,oc\n"
    "0.00010,10.0,12.0,,5,2,sb1\n10.0,-5.0,9.0,,,3,acc7\n")
open(os.path.join(d, "Gaia_Doubles.inx"), "wb").write(b"\0")
assert O.build_doubles_index(d) == 3
near = O.gaia_doubles_near(0.0, 10.0, 3.0, base)
assert sorted(e["ID"] for e in near) == ["1", "2"] and all(e["sep_arcsec"] < 1 for e in near)
assert [e["ID"] for e in O.gaia_doubles_near(10.0, -5.0, 1.0, base)] == ["3"]
assert O.star_text(10.0, -5.0, base=base)[0].startswith("Gaia non-single star (0\" off): acceleration (7 par.)")

# summary lines
s = O.summary(4, base)
assert s[0] == "Diameter (IR surveys, weighted): 5.1 ± 1 km" and any(x.startswith("Satellite Test") for x in s)
assert O.summary(1, base)[0] == "Diameter: 952 km"
assert O.summary(8, base)[0].startswith("Diameter: 1.6 km, estimated from H")

# download through a stand-in: only the dataset's own files are written (a '../evil' member is ignored)
O._CACHE.clear()
blob = io.BytesIO()
with zipfile.ZipFile(blob, "w") as z:
    z.writestr("BinaryAsteroids.csv", "Number,Name\n22,Kalliope,Linus,28\n")
    z.writestr("BinaryAsteroid_SatelliteNames.txt", "(22) 1 = Linus\n")
    z.writestr("../evil.txt", "x")


class Resp(io.BytesIO):
    headers = {"Last-Modified": "Sat, 02 Aug 2025 07:08:20 GMT"}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


from pysyzygos import net
calls = []
net.urlopen = lambda req, timeout=30, **k: calls.append((req.get_method(), req.full_url)) or Resp(blob.getvalue())
assert O.add("binaries", base, log=lambda *a: None) == "Sat, 02 Aug 2025 07:08:20 GMT"
assert calls[-1] == ("GET", "https://www.occultations.org/sw/occult/BinaryAsteroids.zip")
assert not os.path.exists(os.path.join(base, "evil.txt")) and not os.path.exists(os.path.join(d, "evil.txt"))
assert not [f for f in os.listdir(d) if f.endswith((".tmp", ".part"))]
assert O.binaries(22, base)[0]["name"] == "Kalliope"
st = {x["key"]: x for x in O.status(base)}
assert st["binaries"]["installed"] and st["binaries"]["server_date"].startswith("Sat, 02 Aug 2025")
assert O.check_updates(base) == {k: "Sat, 02 Aug 2025 07:08:20 GMT" for k in
                                 ("diameters", "diameters_all", "magnitudes", "observations", "gaia_doubles")}
assert calls[-1][0] == "HEAD"
Resp.headers = {"Last-Modified": "Mon, 19 Oct 2026 13:27:25 GMT"}
assert "binaries" in O.check_updates(base)
net.urlopen = lambda *a, **k: (_ for _ in ()).throw(OSError("offline"))
assert O.check_updates(base) == {}                                   # no network: nothing claimed

# import from an Occult 'Resource Files' folder (Gaia subfolder too), then removal
src = tempfile.mkdtemp()
os.makedirs(os.path.join(src, "Gaia"))
open(os.path.join(src, "AsteroidDiameters.bin"), "wb").write(dia.tobytes() + unc.tobytes())
open(os.path.join(src, "Gaia", "Gaia_Doubles.csv"), "w").write("RA, Dec, Gmag, ID, Model\n1.0,2.0,9,7,oc\n")
open(os.path.join(src, "Gaia", "Gaia_Doubles.inx"), "wb").write(b"\0")
assert sorted(O.import_folder(src, base, log=lambda *a: None)) == ["diameters", "gaia_doubles"]
assert O.gaia_doubles_near(1.0, 2.0, 1.0, base)[0]["ID"] == "7"
st = {x["key"]: x for x in O.status(base)}
assert st["diameters"]["source"] == os.path.abspath(src) and st["diameters"]["server_date"] == ""
assert O.remove("gaia_doubles", base) and not os.path.exists(os.path.join(d, "gaia_doubles.idx.npy"))
assert not O.installed("gaia_doubles", base) and O.gaia_doubles_near(1.0, 2.0, 1.0, base) == []
assert O.remove("gaia_doubles", base) is False
assert "gaia_doubles" not in json.load(open(os.path.join(d, O.META)))
print("test_occultdata: all passed")
