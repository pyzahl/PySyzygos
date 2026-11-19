"""CSV exports (pysyzygos.exports): the column file (template + the user's copy), shown values as the tables show them,
raw columns, "*", functions; Results rows from the results database."""
import _testtmp  # noqa: F401  (temporary files of this run in one folder, removed at exit)
import sys, os, csv, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
from pysyzygos import exports as X, db

home = tempfile.mkdtemp()
cols = X.spec("results", home)                                  # creates the user's copy from the template
assert os.path.isfile(os.path.join(home, X.FILE)) and cols[0] == ("Asteroid", "asteroid")
with open(os.path.join(home, X.FILE), "w") as f:                # the user changes one list only
    f.write('EXPORTS = {"pick": [("Number", "raw:number")]}\n')
assert X.spec("pick", home) == [("Number", "raw:number")] and X.spec("bodies", home)[0] == ("Body", "body")

# a results list in a database: one event, logged twice (rerun) -> one row, as the report
d = tempfile.mkdtemp()
con = db.connect(os.path.join(d, "t.db"))
run, _ = db.start_run(con, "corridor")
rec = dict(target_id="30819", target_name="30819 (1990 RL2)", best_utc="2026-10-11T22:47:45.589", best_et=1.0,
           star=2514569868519950720, mag=9.67, mag_drop=7.33, max_duration_s=0.62, star_alt=42.0, star_az=135.0,
           min_distance=2.1, margin_km=-1.0, r_km=3.1, p_site=0.52, size_source="NEOWISE")
db.add_event(con, run, rec)
db.add_event(con, run, rec)
db.finish_run(con, run, dict(site=dict(name="Test", lat=47.0, lon=9.6)))
con.close()
rows = X.results_rows(os.path.join(d, "t.db"), "main")
assert len(rows) == 1
shown, raw = rows[0]
assert shown["asteroid"] == "(30819) 1990 RL2" and shown["event_time"] == "2026-Oct-11 22:47:46"
assert shown["altitude"] == "42° SE" and shown["shadow_dist"] == "2.1 km, inside" and shown["chance"] == "52 %"
assert raw["star"] == "2514569868519950720", "raw values as the log CSV writes them"

out = os.path.join(d, "r.csv")
X.write("results", rows, out, home=home)
got = list(csv.reader(open(out, encoding="utf-8-sig")))
assert got[0][:3] == ["Asteroid", "Event time (UT)", "Star mag"] and got[1][2] == "9.67" and got[1][-1] == "52 %"
assert open(out, "rb").read(3) == b"\xef\xbb\xbf", "UTF-8 with BOM (spreadsheets)"
X.write("x", rows, out, columns=[("Gaia", "raw:star"), ("Two", lambda sh, r: sh["star_mag"] + "!"), "*"])
got = list(csv.reader(open(out, encoding="utf-8-sig")))
assert got[0][:3] == ["Gaia", "Two", "target_id"] and "star" not in got[0] and got[1][:2] == ["2514569868519950720", "9.67!"]

# the pick table's values
s = X.pick_shown(dict(number="5523", name="5523 Luminet", H="13.456", star_mag="10.04", D_est="True", utc="x"), ["5523"])
assert s["target"] == "✓" and s["H"] == "13.46" and s["name"] == "5523 Luminet *"
assert s["star_mag"] == "10.04"                                     # no Sun altitude: no twilight mark
# twilight: the Sun above -12 deg at the site is marked next to the star magnitude (report, CSV, pick table)
from pysyzygos import report as R
assert R.twilight_text(None) == "" and R.twilight_text(-18) == "" and R.twilight_text(-12.0) == ""
assert R.twilight_text(-8.2) == "☼ −8°" and R.twilight_text(1.0) == "☼ 1°"
assert "civil" in R.twilight_mark(dict(sun=-3.0)) and "nautical" in R.twilight_mark(dict(sun=-8.0))
assert R.twilight_mark(dict(sun=-15.0)) == ""
t = X.pick_shown(dict(number="3200", name="3200 Phaethon", star_mag="7.29", sun_alt="-8.2", utc="x"), [])
assert t["star_mag"] == "7.29 ☼ −8°", t["star_mag"]
assert X.pick_shown(dict(number="1", star_mag="9.0", sun_alt="-20", utc="x"), [])["star_mag"] == "9.00"
print("EXPORTS TESTS PASSED")
