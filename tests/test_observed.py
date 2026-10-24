"""observed.py (the Occult archive as a results database), its report layout and SQL columns, and obscheck.py's
geometry (observed minus predicted in the track's frame, axes of date). A stand-in archive of two events in the
archive's format (lines as in Asteroid~Observations.xml). No SPICE, no network."""
import json, math, os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
import numpy as np
from pysyzygos import db, observed, report as R

XML = """<?xml version="1.0" encoding="utf-8"?>
<AsteroidOccultations><FileVersion>2.15</FileVersion>
  <Event>
    <Date>2021|5|19|18.0</Date>
    <Details>
      <Star>UCAC4|323-126197|3|4064355353554962304|17.9500220510|-25.406850380|0.12|0.08|0.06|0|17.97|-25.40|14.97|13.59|12.45|0</Star>
      <StarIssues>0.90|0|0|0|1.20|10|0.00|0.00|0.00|0.00|</StarIssues>
      <Asteroid>4337|Arecibo|-4.40539811|-0.52411502|-0.0028567|0.0001733|0.0000012|0.0000000|4.18929|0.00055|19.3|1.6|17.06</Asteroid>
      <EventFits>
        <SolveFlags>1|1|0|0|0|1|0|0|0</SolveFlags>
        <EllipticFit>0.00|0.00|24.70|13.00|88.0|1|0|0|0.00|0.00</EllipticFit>
        <EllipseUncertainty>0.10|0.10|||</EllipseUncertainty>
        <SatelliteFit>
          <Satellite>|0.0|0.0|0.0|0.0|24.920|96.268|1.000|1.500|13.500|8.500|88.0|3|4981</Satellite>
        </SatelliteFit>
      </EventFits>
      <Astrometry>
        <ReferenceTime>2021|5|19|17.9683789|0.096|0.00</ReferenceTime>
        <MainBody>4337|2466.30|-1166.60|1.6226|-0.7705|0.0008|0.0008|0|2|0|b|0.4|-0.4|0.00|0.00|9.00|-9.00</MainBody>
        <MainAtConjunction>4337|171.30|-1439.60|2021|5|19.75211|0.0000005|0.31|1.3186|0.82|5.216|0</MainAtConjunction>
        <MPC>2025 5 1|183411|X</MPC>
      </Astrometry>
    </Details>
    <Observations>
      <Prediction>1|+150 30  0.0|-33 36 15.0|17 58  0.0|JPL#57+Ephem</Prediction>
      <Observer>
        <ID>1|D Gault||0|Hawkesbury Heights, Nsw|AU|+150 38 27.9|-33 39 51.9|286| |30|3|a|a</ID>
        <Conditions>2|1|10.0||See CBET 4981</Conditions>
        <D>17 57 59.61|D|0.08||| </D>
        <R>17 58  1.89|R|0.12||| </R>
      </Observer>
      <Observer>
        <ID>2|D Gault||0|Hawkesbury Heights, Nsw|AU|+150 38 27.9|-33 39 51.9|286| |30|3|a|a</ID>
        <Conditions>2|1|10.0||</Conditions>
        <D>17 58  4.73|G|0.08||| </D>
        <R>17 58  5.30|B|0.08||| </R>
      </Observer>
      <Observer>
        <ID>3|P Nosworthy||0|Sydney|AU|+151  0  0.0|-33 50  0.0|50| |25|3|a|a</ID>
        <Conditions>2|1|10.0||</Conditions>
        <D>17 58  0.10|M|0.10||| </D>
        <R>17 58  0.10|M|0.10||| </R>
      </Observer>
    </Observations>
    <Added>2021|6|14</Added>
    <LastEdited>2025|5|23</LastEdited>
  </Event>
  <Event>
    <Date>2026|10|3|9.8</Date>
    <Details>
      <Star>Tycho2|1340-00412-1|3|3376112133115974272|6.4392065990|21.486638771|0.19|0.15|0.50|1|6.46614856|21.4713199|10.99|9.94|8.94|0</Star>
      <StarIssues>1.70|1|0|0|1.20|10|0.00|0.00|0.00|0.00|</StarIssues>
      <Asteroid>22493|1997 GP40|7.57752068|-0.71977175|-0.0057612|0.0002872|-0.0000001|0.0000001|3.25578|0.00064|4.0|0.4|20.14</Asteroid>
      <EventFits><EllipticFit>0.00|0.00|4.00|4.00|0.0|1|1|0|0.00|0.00</EllipticFit></EventFits>
      <Astrometry>
        <ReferenceTime>2026|10|3|9.7863428|0.010|0.00</ReferenceTime>
        <MainBody>22493|-3734.42|2949.27|-1.9107|1.5003|0.0008|0.0008|0|1|0|f4|0.4|-0.4|0.00|0.00|9.00|-9.00</MainBody>
      </Astrometry>
    </Details>
    <Observations>
      <Observer><ID>2|C Anderson||0|Twin Falls|ID|-114 28 13.2|+42 35  1.8|1120|N|60|3|a|a</ID>
        <D> 9 47 10.68|D|0.01|||</D><R> 9 47 10.96|R|0.01|||</R></Observer>
    </Observations>
    <Added>2026|10|18</Added><LastEdited>2026|10|18</LastEdited>
  </Event>
</AsteroidOccultations>
"""

tmp = tempfile.mkdtemp()
xml, dbp, csvp = (os.path.join(tmp, x) for x in ("obs.xml", "observations.db", "observations_log.csv"))
open(xml, "w", encoding="utf-8").write(XML)
assert observed.build(xml, dbp, csvp, log=lambda *a: None) == 2
con = db.connect(dbp)
recs = {r["target_id"]: r for r in db.events(con, lst="observed")}
a, g = recs["4337"], recs["22493"]
assert a["target_name"] == "4337 Arecibo" and a["star"] == "4064355353554962304" and a["mag"] == 13.59
assert a["best_utc"] == "2021-05-19T17:58:06.164", a["best_utc"]           # reference time 17.9683789 h
assert abs(a["star_ra"] - 17.9500220510 * 15) < 1e-9 and a["r_km"] == 9.65
assert (a["geo_x_km"], a["geo_y_km"], a["n_chords"], a["fit_quality"]) == (2466.3, -1166.6, 2, 1)
assert a["sat_cbet"] == "4981" and a["sat_sep_mas"] == 24.92 and a["sat_fit"] == "offset + size"
assert a["n_observers"] == 2 and a["n_positive"] == 2 and a["n_miss"] == 1          # D Gault once, two chords
assert a["max_duration_s"] == 2.28 and a["conj_utc"].startswith("2021-05-19T18:03:02"), (a["max_duration_s"], a["conj_utc"])
assert g["star_flag"] == "RUWE 1.70, duplicated source" and g["fit_assumed_size"] == 1
c = [tuple(x) for x in con.execute("SELECT label, utc FROM contacts ORDER BY utc")]
assert ("D", "2021-05-19T17:57:59.61") in c and ("G", "2021-05-19T17:58:04.73") in c and len(c) == 6, c
assert [k for k, _ in db.where_keys(dbp, "cbet <> ''", "observed")] == ["4337"]
assert {k for k, _ in db.where_keys(dbp, "fit_quality = 1 AND chords >= 1", "observed")} == {"4337", "22493"}
con.close()
assert os.path.isfile(csvp) and json.loads(open(os.path.splitext(csvp)[0] + ".runs.jsonl").readline())["events"] == 2
# the report: header lines and the observed layout (no site, no maps)
rows, _ = R.read_log(csvp)
ev = [R.build_event(r, 40.0, -75.0, os.devnull, tmp) for r in rows]
row = R.html_row_observed(next(e for e in ev if e["tid"] == "4337"))
assert "CBET 4981" in row and "2 / 2" in row and "1 miss" in row and "24.7 × 13.0" in row and "—" in row
assert all(e["kml"] is None and e["az"] is None for e in ev)               # archive rows: no site, no map lookups
hdr = R.header_info(dict(kind="observed", source="S", events=2, events_until="2026-10-03", file_date="d",
                         version="x", run_utc="t"), None, None)
assert hdr[0][0] == "Source" and "not checked yet" in hdr[1][1]

# obscheck: observed minus predicted in the track's frame; axes of date
from pysyzygos import obscheck as C
pr = dict(x=1000.0, y=0.0, vx=10.0, vy=0.0, dist_km=3e8)                     # moving east at 10 km/s
d = C.compare(dict(geo_x_km=1020.0, geo_y_km=5.0), pr)
assert (d["chk_along_km"], d["chk_across_km"], d["chk_along_s"]) == (20.0, 5.0, 2.0), d   # + across = left (north)
assert abs(d["chk_mas"] - math.degrees(math.hypot(20, 5) / 3e8) * 3.6e6) < 1e-3
try:
    import erfa                                                                 # (pyerfa, with astropy)
    z = np.array([0.6, 0.0, 0.8])
    x0, y0 = C.date_axes(0.0, z)                                                # J2000: the J2000 axes (frame bias only)
    assert abs(x0 @ np.array([0, 1.0, 0]) - 1) < 1e-6 and abs(y0 @ np.array([-0.8, 0, 0.6]) - 1) < 1e-6
    # precession turns the plane's north by ~ n t sin(RA) / cos(Dec) (n = 20.0"/yr): at RA 90 over 26 years
    # (Dec 53.1) 0.24 deg (+ nutation, ~0.004 deg here); at RA 0 hardly at all
    t26 = 26 * 365.25 * 86400
    ang = lambda z_: math.degrees(math.acos(np.clip(C.date_axes(t26, z_)[0] @ C.date_axes(0.0, z_)[0], -1, 1)))
    a90, a0 = ang(np.array([0.0, 0.6, 0.8])), ang(z)
    assert abs(a90 - 20.04 * 26 / 3600 / 0.6) < 0.01 and a0 < 0.01, (a90, a0)
except ImportError:
    print("(erfa not installed: axes of date not tested)")
assert C.ev_key(dict(target_id="1", best_utc="2026-01-02T03:04:05.678", star="9")) == "1|2026-01-02T03:04:05|9"
# the observers' chords at their sites (the measured data): main-star D and R paired per observer and site, misses
ch = C.load_chords(dbp)
pos, mis = ch[C.ev_key(a)]
assert len(pos) == 1 and pos[0]["observer"] == "D Gault" and pos[0]["d_utc"] == "2021-05-19T17:57:59.61"     # G/B: satellite
assert pos[0]["r_utc"] == "2021-05-19T17:58:01.89" and pos[0]["datum"] == "_" and abs(pos[0]["lat"] + 33.664417) < 1e-5
assert pos[0]["d_acc"] == 0.08 and pos[0]["include"] == "__" and pos[0]["d_pe"] == 0.0
assert [m["observer"] for m in mis] == ["P Nosworthy"]
# the report: per-site results on hover, their median shown
rec = dict(a, chk_site_dt_s=0.021, chk_across_km=1.2, chk_along_s=0.05,
           chk_chords=[dict(observer="D Gault", place="Hawkesbury", dt_mid_s=0.021, dist_km=3.4, dur_obs_s=2.28,
                            dur_pred_s=2.1, method="a", include="__")])
e = R.build_event({k: db._cell(v) for k, v in rec.items()}, None, None, os.devnull, tmp)
row = R.html_row_observed(e)
assert "+0.02 s" in row and "1 site" in row and "D Gault, Hawkesbury: mid-time +0.02 s" in row, row
# the best size: the chord through the fitted ellipse centred on the predicted axis
dur, mid = C.ellipse_chord(np.array([0.0, 3.0]), np.array([10.0, 0.0]), 5.0, 5.0, 0.0)      # circle r 5, 3 km off
assert abs(dur - 2 * 4.0 / 10.0) < 1e-12 and abs(mid) < 1e-12
dur, mid = C.ellipse_chord(np.array([0.0, 0.0]), np.array([10.0, 0.0]), 8.0, 2.0, 90.0)     # major axis east-west
assert abs(dur - 1.6) < 1e-12
dur, _ = C.ellipse_chord(np.array([0.0, 0.0]), np.array([10.0, 0.0]), 8.0, 2.0, 0.0)        # major axis north-south
assert abs(dur - 0.4) < 1e-12 and C.ellipse_chord(np.array([0.0, 9.0]), np.array([10.0, 0.0]), 8.0, 2.0, 0.0)[0] == 0.0
dur, mid = C.ellipse_chord(np.array([-3.0, 1.0]), np.array([10.0, 0.0]), 5.0, 5.0, 0.0)     # axis 3 km behind: later
assert abs(mid - 0.3) < 1e-12
assert C.best_size(dict(fit_major_km=10, fit_minor_km=8, fit_pa_deg=30, fit_assumed_size=0, fit_quality=3))[:3] == (5.0, 4.0, 30.0)
assert C.best_size(dict(fit_major_km=10, fit_minor_km=8, fit_assumed_size=1, fit_quality=1)) is None
print("OBSERVED TESTS PASSED")
