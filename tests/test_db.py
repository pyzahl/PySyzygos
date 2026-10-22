"""Results database (pysyzygos.db): series, events, updates, exports, the one-time imports of an old hit log and
favorites.json."""
import sys, os, csv, json, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
import numpy as np
from pysyzygos import db

d = tempfile.mkdtemp()
log = os.path.join(d, "hits_log.csv")
# an old hit log with its run summaries: imported once into an empty database
with open(log, "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["target_id", "best_utc", "best_et", "star", "mag"])
    w.writerow(["30819", "2026-10-11T22:47:45.589", "844000000.0", "2514569868519950720", "9.67"])
with open(os.path.join(d, "hits_log.runs.jsonl"), "w") as f:
    f.write(json.dumps(dict(run_utc="2026-10-06T10:00:00", hits=1)) + "\n")
con = db.connect(os.path.join(d, "test.db"))
assert db.import_log(con, log) == 1 and db.import_log(con, log) == 0, "once"
assert [r["target_id"] for r in db.events(con)] == ["30819"] and db.runs(con)[0]["hits"] == 1

# a run in the current series: numpy values are stored, the export has consistent columns
run, series = db.start_run(con, "corridor")
assert series == db.current_series(con)
db.add_event(con, run, dict(target_id="282", best_utc="2026-10-08T20:03:34.525", best_et=np.float64(1.5),
                            star=np.int64(123456789012345678), mag=12.5, p_site=float("nan"), new_col="x"))
db.update_events(con, [dict(target_id="282", best_utc="2026-10-08T20:03:34.525")], [dict(double_hint="companion")])
db.finish_run(con, run, dict(run_utc="2026-10-08T12:00:00", hits=1))
assert db.export(con, log) == 2
rows = list(csv.DictReader(open(log)))
assert [r["target_id"] for r in rows] == ["30819", "282"]
assert rows[1]["star"] == "123456789012345678" and rows[1]["p_site"] == "" and rows[1]["double_hint"] == "companion"
assert rows[0]["new_col"] == "" and set(rows[0]) == set(rows[1]), "same columns for all rows"
runs = [json.loads(ln) for ln in open(os.path.join(d, "hits_log.runs.jsonl"))]
assert [r["run_utc"] for r in runs] == ["2026-10-06T10:00:00", "2026-10-08T12:00:00"]
assert db.find_event(con, "282", "2026-10-08T20:03")["double_hint"] == "companion"
assert db.last_run(con)["run_utc"] == "2026-10-08T12:00:00"

# a fresh results list: a new series; the old one stays in the database
run2, s2 = db.start_run(con, "corridor", new_series=True)
assert s2 == series + 1 and db.events(con) == [] and len(db.events(con, series)) == 2
assert db.export(con, log) == 0 and not os.path.exists(log), "no events: no CSV (as an empty hit log before)"
run3, s3 = db.start_run(con, "corridor", new_series=True)
assert s3 == s2 + 1, "a series with a run (even without events) is closed by the next fresh start"
run4, s4 = db.start_run(con, "corridor", new_series=True)
assert s4 == s3 + 1

# contacts (for planets/eclipses later)
eid = db.add_event(con, run4, dict(target_id="M:Io", best_utc="2026-11-01T01:00:00", best_et=1.0),
                   kind="moon", contacts=[("D", "2026-11-01T00:59:00", 0.0, {"pa": 10}), ("R", "2026-11-01T01:01:00", 2.0, None)])
assert [r[0] for r in con.execute("SELECT label FROM contacts WHERE event_id=? ORDER BY et", (eid,))] == ["D", "R"]
assert db.events(con, kind="moon")[0]["target_id"] == "M:Io" and db.events(con, kind="asteroid") == []

# favorites: favorites.json imported once, kept as .migrated
fav = os.path.join(d, "favorites")
os.makedirs(fav)
json.dump([dict(key="282_20261008T2003", status="planned")], open(os.path.join(fav, "favorites.json"), "w"))
assert db.favorites_import(con, os.path.join(fav, "favorites.json")) == 1
assert os.path.isfile(os.path.join(fav, "favorites.json.migrated")) and db.favorites_load(con)[0]["status"] == "planned"
db.favorites_save(con, [dict(key="a"), dict(key="b")])
assert [e["key"] for e in db.favorites_load(con)] == ["a", "b"]
# results lists: a "bodies" list beside "main", with its own series; numbers unique across lists
main_now = db.current_series(con)
rb, sb = db.start_run(con, "corridor", lst="bodies")
assert sb != main_now and db.current_series(con) == main_now and db.current_series(con, "bodies") == sb
db.add_event(con, rb, dict(target_id="P:Jupiter", best_utc="2026-10-11T02:52:18", best_et=2.0), kind="planet")
assert [r["target_id"] for r in db.events(con, lst="bodies")] == ["P:Jupiter"]
assert all(r["target_id"] != "P:Jupiter" for r in db.events(con))
rb2, sb2 = db.start_run(con, "corridor", new_series=True, lst="bodies")
assert sb2 > sb and db.current_series(con) == main_now and db.events(con, lst="bodies") == []
assert db.export(con, os.path.join(d, "bodies_log.csv"), lst="bodies") == 0
# the hits view: typed columns (numbers as text from old CSV imports converted; '', 'nan' -> NULL), chance in %,
# RUWE from either field; where_keys: the current series of a list, read only, a bad condition -> ValueError
rh, sh = db.start_run(con, "corridor", new_series=True)
db.add_event(con, rh, dict(target_id="3200", best_utc="2026-11-01T01:00:00.123", mag=10.5, mag_drop=2.0,
                           max_duration_s=1.5, p_site=0.4, star_ruwe=None, gaia_ruwe=1.7, star_flag="RUWE 1.70",
                           sun_alt=-20.0, star_alt=30.0))
db.add_event(con, rh, dict(target_id="4089", best_utc="2026-11-02T01:00:00", mag="12.25", mag_drop="nan",
                           max_duration_s="", p_site="0.05", star_flag="", sun_alt="-8.5"))
con.commit()
row = con.execute("SELECT mag, mag_drop, duration, chance, ruwe, star_flag FROM hits WHERE target='4089'").fetchone()
assert tuple(row) == (12.25, None, None, 5.0, None, ""), tuple(row)
assert tuple(con.execute("SELECT chance, ruwe FROM hits WHERE target='3200'").fetchone()) == (40.0, 1.7)
dbp = os.path.join(d, "test.db")
con.commit()
assert db.where_keys(dbp, "mag < 11") == [("3200", "2026-11-01T01:00:00.123")]
assert {t for t, _ in db.where_keys(dbp, "1=1")} == {"3200", "4089"}                # only the current series
assert db.where_keys(dbp, "chance >= 5 AND sun_alt < -10") == [("3200", "2026-11-01T01:00:00.123")]
assert db.where_keys(dbp, "mag_drop IS NULL") == [("4089", "2026-11-02T01:00:00")]   # 'nan' is NULL, never 0
for bad in ("mag <", "1=1; DELETE FROM events", "nosuchcolumn > 1"):
    try:
        db.where_keys(dbp, bad)
        raise AssertionError(f"accepted: {bad}")
    except ValueError:
        pass
n = con.execute("SELECT count(*) FROM events").fetchone()[0]
try:                                                     # a condition that would write: the connection is read-only
    db.where_keys(dbp, "(SELECT 1 FROM (SELECT load_extension('x'))) = 1")
except ValueError:
    pass
assert con.execute("SELECT count(*) FROM events").fetchone()[0] == n
assert {h[0] for h in db.HITS} >= {"mag", "mag_drop", "duration", "chance", "ruwe", "star_alt", "sun_alt"}
# the filter bar as SQL (a template for custom conditions): AND-joined; unknown RUWE/drop/chance pass, as in the bar
q = db.filter_to_sql({"mag": 12.5, "ruwe": 1.4, "hide": ["sup", "twi"], "only": ["moon"]})
assert q == ("mag <= 12.5 AND (ruwe IS NULL OR ruwe <= 1.4) AND star_flag = '' AND sun_alt <= -12 "
             "/* only +moon: no SQL column */"), q
assert db.filter_to_sql({}) == "" and db.filter_to_sql(None) == ""
assert db.where_keys(dbp, db.filter_to_sql({"mag": 11, "ruwe": 2.0})) == [("3200", "2026-11-01T01:00:00.123")]
assert {t for t, _ in db.where_keys(dbp, db.filter_to_sql({"hide": ["sup"]}))} == {"4089"}
assert db.where_keys(dbp, db.filter_to_sql({"only": ["moon"]}))                          # the comment is valid SQL
# several connections opening at once (GUI start: a background task and the page) must not fail on the view
import threading
errs, par = [], os.path.join(d, "parallel.db")
def opener():
    try:
        for _ in range(20):
            db.connect(par).close()
    except Exception as ex:
        errs.append(repr(ex))
ts = [threading.Thread(target=opener) for _ in range(6)]
[t.start() for t in ts]
[t.join() for t in ts]
assert not errs, errs[:2]
print("DB TESTS PASSED")
