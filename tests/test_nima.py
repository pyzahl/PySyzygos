"""NIMA ephemerides (nima.py): the list page's table, an object page, the choice JPL / NIMA, the uncertainty table,
the caches. Stand-ins for the pages and the .bsp download (excerpts of the real pages of 2026-11-06). No network,
no SPICE."""
import json, math, os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
from pysyzygos import nima, urls as U

LIST = ('<html>NIMA ephemeris ... <script>var Mtable = [[1374,"Quaoar","(50000) Quaoar",20,"2025",6,"31","2025",5,"12",'
        '43.16,2.501],[1197,"2007JJ43","(278361) 2007JJ43",11,"2024",7,"22","2024",4,"11",47.7,4.49],'
        '[258,"1996RR20","1996RR20",1,"2018",10,"29","2015",10,"02",39.5,6.8],'
        '[1500,"Triton","Triton",3,"2025",1,"01","2024",0,"05",30.1,-1.2]];</script></html>')
OBJ = ('<html><a href="data/nima/Quaoar/50000_Quaoar_nima_v20.bsp">bsp</a> <td>Ephemeris version</td><td>NIMAv20</td>'
       '<td>Date of last observation</td><td>2025-06-12</td><td>Number of observations used in the fit</td><td>1521</td>'
       '<td>RMS of observations</td><td>0.099 arcsec</td> Orbit quality date σ α (arcsec) σ δ (arcsec) '
       '<tr><td>2026-07</td><td>0.004</td><td>0.002</td></tr><tr><td>2027-01</td><td>0.006</td><td>0.002</td></tr>'
       '<script>var x = "2030-01 9 9";</script></html>')

calls = []
def fetch(url):
    calls.append(url)
    if url == U.URL_NIMA_INDEX:
        return LIST.encode()
    if url.startswith(U.URL_NIMA_OBJECT):
        return OBJ.encode()
    if url.endswith(".bsp"):
        return b"DAF/SPK fake"
    raise OSError(url)

# the list: numbers, designations, no entry for a planet's satellite; months from 0 (JavaScript)
idx = nima.parse_index(LIST)
assert set(idx) == {"50000", "278361", "1996 RR20"}, idx
q = idx["50000"]
assert q["version"] == 20 and q["updated"] == "2025-07-31" and q["last_obs"] == "2025-06-12" and q["page"] == 1374
assert idx["278361"]["last_obs"] == "2024-05-11"

# the object page (the script's numbers are not part of the table)
det = nima.parse_details(OBJ)
assert det["bsp"] == "data/nima/Quaoar/50000_Quaoar_nima_v20.bsp" and det["version"] == "NIMAv20"
assert det["last_obs"] == "2025-06-12" and det["n_obs"] == 1521 and abs(det["rms_arcsec"] - 0.099) < 1e-9
assert det["sigma"] == [["2026-07", 0.004, 0.002], ["2027-01", 0.006, 0.002]], det["sigma"]

# the choice: auto takes the newer last observation, NIMA on the same date or without JPL's
assert nima.choose("off", "2025-06-12", "2020-01-01")[0] is False
assert nima.choose("always", "2020-01-01", "2025-07-28")[0] is True
assert nima.choose("auto", "2024-05-11", "2023-04-17") == (True, "NIMA: last observation 2024-05-11 (JPL 2023-04-17)")
assert nima.choose("auto", "2025-06-12", "2025-07-28")[0] is False
assert nima.choose("auto", "2025-06-12", "2025-06-12")[0] is True
assert nima.choose("auto", "2025-06-12", None)[0] is True
assert nima.jpl_last_obs({"orbit": {"ref": "condition code U 2, 1058 observations 1954-05-25 to 2025-07-28"}}) \
    == "2025-07-28" and nima.jpl_last_obs({}) is None

# the uncertainty: linear between the table's half-years, the ends outside
assert nima.sigma_arcsec(det, "2026-07-01") == (0.004, 0.002)
s = nima.sigma_arcsec(det, "2026-10-01")
assert abs(s[0] - 0.005) < 2e-4 and s[1] == 0.002, s
assert nima.sigma_arcsec(det, "2030-01-01") == (0.006, 0.002) and nima.sigma_arcsec(det, "2020-01") == (0.004, 0.002)
pe = nima.path_error(det, "2026-07-01", 6.0e9)
assert pe["smaa_mas"] == 4.0 and pe["smia_mas"] == 2.0 and pe["pa_deg"] == 90.0
assert abs(pe["sigma3_km"] - 3 * math.hypot(0.004, 0.002) * math.pi / 648000 * 6.0e9) < 1e-6
assert nima.path_error(dict(sigma=[]), "2026-07-01", 6e9) is None

# caches: the list once a day, the details once per version, the .bsp once per version; an old list when offline
with tempfile.TemporaryDirectory() as d:
    assert nima.index(d, fetch=fetch) == idx and nima.index(d, fetch=fetch) == idx
    assert calls.count(U.URL_NIMA_INDEX) == 1
    assert nima.details(q, d, fetch=fetch) == det and nima.details(q, d, fetch=fetch) == det
    assert sum(c.startswith(U.URL_NIMA_OBJECT) for c in calls) == 1
    p = nima.kernel("50000", q, det, d, fetch=fetch)
    assert os.path.basename(p) == "PySyzygos_nima_50000_v20.bsp" and open(p, "rb").read() == b"DAF/SPK fake"
    nima.kernel("50000", q, det, d, fetch=fetch)
    assert sum(c.endswith(".bsp") for c in calls) == 1
    assert nima.index(d, max_age_s=0, fetch=lambda u: (_ for _ in ()).throw(OSError("offline"))) == idx
    data = json.load(open(os.path.join(d, nima.INDEX_FILE)))
    assert "1374:v20" in data["details"]
    assert nima.index(os.path.join(d, "none"), fetch=lambda u: (_ for _ in ()).throw(OSError("offline"))) == {}
print("NIMA TESTS PASSED")
