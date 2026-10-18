"""pathcheck.py without SPICE: Occult's listing format (parser, signs, our export layout), the header facts, the plane
fit on synthetic data, the summary and the report."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
import numpy as np
from pysyzygos import pathcheck as P

# Occult's layout (made-up numbers): sign apart for short degrees, "- 0" for negative values under 1 deg
occult = """Occultation of HIP 1 by 9999 Test on 2019 Jul 29, at MSL

                   Centre                Star  Star  Sun|      Path Limit 1   |      Path Limit 2   |      Error Limit 1  |      Error Limit 2  |   Alt
  E. Longitude    Latitude      U.T.      Alt   Az   Alt| Longitude   Latitude| Longitude   Latitude| Longitude   Latitude| Longitude   Latitude|   Crn
      o  '  "     o  '  "    h  m  s       o     o     o|   o  '  "    o  '  "|   o  '  "    o  '  "|   o  '  "    o  '  "|   o  '  "    o  '  "|

   - 15 40 42   -44 19  9   11  3 39.82    4   348    21 - 15 41 58  -44  9 25 - 15 39 17  -44 29 21 - 15 42 11  -44  7 40 - 15 39  1  -44 31 18   ....
   - 29 45 36   - 9 57 38   11  6  8.09   39   357    37 - 29 44 33  - 9 56 21 - 29 46 40  - 9 58 56 - 29 44 22  - 9 56  7 - 29 46 51  - 9 59 10   0.49
   - 34 43 38   - 0 59  6   11  7 26.58   48     2    38 - 34 42 35  - 0 57 56 - 34 44 42  - 1  0 17 - 34 42 24  - 0 57 43 - 34 44 53  - 1  0 29   0.49
   -100  3 54    38  5 38   11 18 33.78   41    65    -5 -100  3 10   38  7  8 -100  4 37   38  4  8 -100  3  2   38  7 24 -100  4 46   38  3 52   0.47

Uncertainty in time = +/- 0 secs
"""
rows, title = P.parse_listing(occult)
assert title.startswith("Occultation of HIP 1") and len(rows) == 4, (title, len(rows))
r0, r1, r2, r3 = rows
assert abs(r0["lon"] - -(15 + 40 / 60 + 42 / 3600)) < 1e-12 and abs(r0["lat"] - -(44 + 19 / 60 + 9 / 3600)) < 1e-12
assert abs(r1["lat"] - -(9 + 57 / 60 + 38 / 3600)) < 1e-12                     # "- 9 57 38"
assert abs(r2["lat"] - -(59 / 60 + 6 / 3600)) < 1e-12                          # "- 0 59  6": negative below 1 deg
assert abs(r3["lon"] - -(100 + 3 / 60 + 54 / 3600)) < 1e-12 and r3["sun_alt"] == -5
assert abs(r0["sec"] - (11 * 3600 + 3 * 60 + 39.82)) < 1e-9 and r1["star_alt"] == 39 and r1["star_az"] == 357
assert abs(r2["l2"][1] - -(1 + 0 / 60 + 17 / 3600)) < 1e-12

# our export layout reads back the same (fmt_dms / fmt_ut)
def joined(text):                                   # the sign apart, as the parser joins it
    t = text.split()
    return [t[0] + t[1]] + t[2:] if t[0] == "-" else t
for v in (-15.6783, -0.9850, 0.0599, 38.0939, -100.065, 179.99):
    s = P.fmt_dms(v)
    assert abs(P.dms(joined(s)) - v) <= 0.5 / 3600 + 1e-12, (v, s)
line = (f"  {P.fmt_dms(-29.76)} {P.fmt_dms(-9.9606, 2)}   {P.fmt_ut(40000.25)}    39   357    37"
        + "".join(" " + P.fmt_dms(-29.7) + " " + P.fmt_dms(-9.9, 2) for _ in range(4)))
back, _ = P.parse_listing(line)
assert len(back) == 1 and abs(back[0]["sec"] - 40000.25) < 1e-6 and abs(back[0]["lat"] - -9.9606) < 1 / 3600

# header facts (from Occult's plot header, pasted)
h = P.parse_header(" RA   5 20 54.7283 (astrometric)\n Dec  40 53  5.373\n Dia = 5.0 +-0.4km\n JPL#1016+Ephem")
assert h["jpl"] == "1016" and abs(h["star_ra"] - 80.22803458) < 1e-7 and abs(h["star_dec"] - 40.88482583) < 1e-7
assert h["dia_km"] == 5.0 and P.parse_header("nothing here") == dict(jpl=None, star_ra=None, star_dec=None, dia_km=None)
assert P.parse_header("Dec = -12 30 0.0")["star_dec"] == -12.5

# the plane fit recovers a known constant offset and a known Earth-rotation angle (noise 20 m)
rng = np.random.default_rng(5)
n = 300
drx, dry = rng.normal(0, 4000, n), rng.normal(0, 4000, n)            # km per radian, like points across the Earth
ang = 0.16 * P.OMEGA_EARTH                                            # 160 ms of UT1
px = 0.069 + drx * ang + rng.normal(0, 0.02, n)
py = -0.096 + dry * ang + rng.normal(0, 0.02, n)
fit = P.fit_plane(px, py, np.zeros(n), np.zeros(n), drx, dry)
cx, cy, ang_fit = fit["rot"][0], fit["rot"][1], fit["rot"][2]
assert abs(cx - 0.069) < 0.005 and abs(cy + 0.096) < 0.005 and abs(ang_fit / P.OMEGA_EARTH - 0.16) < 0.003, fit["rot"]
assert fit["const"][2] > fit["rot"][3]                                # the rotation term lowers the rms here

# summary, result line and report
pts = [dict(utc=40000 + i, star_alt=a, across=c, along=-0.15, dt=-0.011, dist=0.2, w_occ=5.5, w_our=6.9, px=0.07,
            py=-0.1, dvx=0, dvy=0, drx=0, dry=0, dist_target=1.42e8) for i, (a, c) in
       enumerate(zip([4, 30, 60, 65, 40, 3], [0.001, 0.02, -0.025, 0.03, 0.0, 0.011]))]
st = P.summary(pts)
assert st["all"]["n"] == 6 and st["alt20"]["n"] == 4 and abs(st["alt20"]["dt_mean"] + 0.011) < 1e-12
fit0 = P.fit_plane(np.full(6, 0.07), np.full(6, -0.1), np.zeros(6), np.zeros(6), rng.normal(0, 4000, 6), rng.normal(0, 4000, 6))
v = P.verdict(st, fit0, 1.449, 10.8)
assert "within the listing's rounding" in v and "Occult later by 11 ms" in v, v
meta = dict(target_name="9999 Test", best_utc="2019-07-29T11:12:00", version="t", run_utc="now", orbit="JPL#1017, x",
            star="1", star_ra=80.0, star_dec=40.0)
md = P.markdown(meta, title, h, pts, st, fit0, 1.449, 10.8, 6.25)
assert "**Different orbit solutions**" in md and "| Orbit | JPL#1016 |" in md and "**Result:**" in md
assert md.count("\n| ") >= len(P.sample_rows(pts)) + 4

# tolerant import: only the centre's longitude, latitude and time are needed; extra columns are ignored
LON, LAT, SEC = -(15 + 40 / 60 + 42 / 3600), -(44 + 19 / 60 + 9 / 3600), 11 * 3600 + 3 * 60 + 39.82
def one(text, n=1, alt=None, date=None):
    rows, _ = P.parse_listing(text)
    assert len(rows) == n, (text[:60], len(rows))
    r = rows[0]
    assert abs(r["lon"] - LON) < 2e-5 and abs(r["lat"] - LAT) < 2e-5 and abs(r["sec"] - SEC) < 0.02, (r, text[:60])
    assert r["star_alt"] == alt and r.get("date") == date, r
    return rows
# CSV: other columns before and between, the limits' columns not taken for the centre
one("Nr,Limit 1 Lon,Limit 1 Lat,Center Longitude,Center Latitude,UT,Star Alt,Sun Alt,Remark\n"
    f"1,-15.70,-44.15,{LON:.6f},{LAT:.6f},11:03:39.82,4,21,ok\n", alt=4.0)
# semicolon, decimal commas (a German spreadsheet), decimal hours
one("Zeit (UT);Breite (lat);Länge (lon);Dauer\n"
    f"{SEC / 3600:.7f}".replace(".", ",") + f";{LAT:.6f};{LON:.6f};3,2\n".replace(".", ","))
# tabs, degrees-minutes-seconds with symbols and hemisphere letters, ISO date-time with the date
one("time\tlatitude\tlongitude\taltitude of star\n"
    "2019-07-29T11:03:39.82Z\t44°19'09\"S\t15°40'42\"W\t39\n", alt=39.0, date="2019-07-29")
# spaces with a header row (one token per column); a units row and a note are skipped
one("lon lat utc alt\n deg deg hms deg\n" f"{LON:.6f} {LAT:.6f} 11:03:39.82 12\n# end\n", alt=12.0)
# Occult's layout cut down to the centre and time (no alt/az, no limits), and with extra columns at the end
cut = "   - 15 40 42   -44 19  9   11  3 39.82\n"
r = one(cut)[0]
assert r["l1"] is None and r["sun_alt"] is None
one("   - 15 40 42   -44 19  9   11  3 39.82    4   348    21   ....  0.49  x\n", alt=4.0)
# not a path: no rows (a sentence with numbers, a short table without names)
assert P.parse_listing("Uncertainty in time = +/- 0 secs\n1 2 3\n")[0] == []
assert P.angle("−0 59 6") < 0 and abs(P.angle("15d40m42s") - 15.678333) < 1e-5
assert P.ut_time("2019 Jul 29 11:03:39")[1] == "2019-07-29" and P.ut_time("11h03m39.8s")[0] == 39819.8
print("PATHCHECK TESTS PASSED")
