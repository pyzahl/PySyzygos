"""pysyzygos_favorites: add (with copies of map and preview), duplicates, status/note, remove, lookup in a hits log."""
import os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
from pysyzygos import favorites as F

tmp = tempfile.mkdtemp()
maps, fav = os.path.join(tmp, "maps"), os.path.join(tmp, "favorites")
os.makedirs(maps)
for ext in ("kml", "svg"):
    open(os.path.join(maps, f"17834_20261003T0253.{ext}"), "w").write(f"<{ext}/>")
log = os.path.join(tmp, "hits_log.csv")
open(log, "w").write("target_id,target_name,best_utc,mag\n17834,17834 (1998 HL43),2026-10-03T02:53:07.123,7.39\n"
                     "19714,19714 (1999 UD),2026-10-04T06:38:06.900,10.29\n")

rec = F.find_record(log, "17834", "2026-10-03T02:53:07")
assert rec and rec["mag"] == "7.39", rec
assert F.find_record(log, "17834", "2026-10-03T02:54:00") is None
run = dict(site=dict(name="S", lat=1.0, lon=2.0), run_utc="2026-10-03T12:00:00", limits={}, extra="dropped")
ok, msg = F.add(rec, run, maps, fav)
assert ok and "17834" in msg, msg
assert not F.add(rec, run, maps, fav)[0], "duplicate must be refused"
e = F.load(fav)[0]
assert e["key"] == "17834_20261003T0253" and e["status"] == "planned" and e["site"]["name"] == "S"
assert "extra" not in e["run"] and e["files"] == {"kml": "17834_20261003T0253/17834_20261003T0253.kml",
                                                   "svg": "17834_20261003T0253/17834_20261003T0253.svg"}
os.remove(os.path.join(maps, "17834_20261003T0253.svg"))                     # a later search deletes maps/ files:
assert open(os.path.join(fav, e["files"]["svg"])).read() == "<svg/>"        # the favorite keeps its copy
ok, msg = F.add(F.find_record(log, "19714", "2026-10-04T06:38:06"), None, maps, fav)
assert ok and "no map or preview" in msg, msg
assert F.keys(fav) == ["19714_20261004T0638", "17834_20261003T0253"], "newest first"
assert F.edited(fav) == []                                                    # new ones: planned, no note
assert F.update("17834_20261003T0253", fav, status="observed", note="clear, positive")[0]
assert F.edited(fav) == ["17834_20261003T0253"]                               # removing it from the results asks
assert F.update("19714_20261004T0638", fav, note="  ")[0] and F.edited(fav) == ["17834_20261003T0253"]   # blank note
assert not F.update("17834_20261003T0253", fav, status="bogus")[0]
assert F.load(fav)[1]["status"] == "observed" and F.load(fav)[1]["note"] == "clear, positive"
assert F.remove("17834_20261003T0253", fav)[0] and not F.remove("17834_20261003T0253", fav)[0]
assert not os.path.isdir(os.path.join(fav, "17834_20261003T0253")) and F.keys(fav) == ["19714_20261004T0638"]
# several at once, cleanup of past events, the page
open(log, "a").write("70141,70141 (1999 NE18),2099-01-03T07:07:42.5,14.06\n")
F.add(F.find_record(log, "17834", "2026-10-03T02:53:07"), run, maps, fav)
F.add(F.find_record(log, "70141", "2099-01-03T07:07:42"), run, maps, fav)
assert len(F.keys(fav)) == 3
assert F.update_many(["17834_20261003T0253", "70141_20990103T0707"], fav, status="clouded")[0]
assert not F.update_many(["17834_20261003T0253"], fav, status="bogus")[0]
assert sorted(e["status"] for e in F.load(fav)) == ["clouded", "clouded", "planned"]
ok, msg = F.cleanup("2050-01-01", fav)                                       # 2026 events are past, 2099 is not
assert ok and "2 favorites removed" in msg and F.keys(fav) == ["70141_20990103T0707"], (msg, F.keys(fav))
assert F.cleanup("2050-01-01", fav)[1].startswith("no favorites before")
page = F.write_page(fav)
html = open(page, encoding="utf-8").read()
assert 'class="favrow" data-key="70141_20990103T0707"' in html and 'id="favall"' in html and "favsetst" in html
from pysyzygos import report as R
assert 'class="mapbtn favbtn"' not in html, "no star buttons on the favorites page"
import re
assert not re.search(r"[,\s(]sel\s*=", R.FAVPAGE_JS if hasattr(R, "FAVPAGE_JS") else ""), \
    "a variable named sel replaces the selection helper sel() (mass actions broke in 0.12.0)"
assert F.remove_many(["70141_20990103T0707", "nope"], fav)[0] and F.keys(fav) == []
# size data kept with a favorite, the size line, the CSV, filling in old favorites
import csv
open(log, "a").write("")
rec = dict(target_id="21641", target_name="21641 Tiffanyko", best_utc="2026-10-06T04:26:25.5", mag="8.1",
           r_km="1.52", r_min_km="0.49", r_max_km="2.555",
           size_source="SBDB diameter (ref urn:nasa:pds:neowise_diameters_albedos::2.0 (http://x))")
cache = {"fetched": 1.0, "source": "sbdb_query", "phys": {"H": {"value": "14.92", "ref": "MPC"}, "albedo": {"value": "0.209", "ref": "N"},
                                  "diameter": {"value": "3.04", "ref": "N"}}}
assert F.add(rec, run, maps, fav, sbdb=cache)[0]
e = F.load(fav)[0]
assert e["phys"]["H"] == ["14.92", "MPC"] or e["phys"]["H"] == ("14.92", "MPC")
assert F.size_text(e) == "D 3.04 km (0.98-5.11 km, SBDB diameter, NEOWISE) · H 14.92 · albedo 0.209", F.size_text(e)
rows = list(csv.DictReader(open(os.path.join(fav, "favorites.csv"), encoding="utf-8")))
assert len(rows) == 1 and rows[0]["key"] == "21641_20261006T0426" and rows[0]["sbdb_H"] == "14.92"
assert rows[0]["site"] == "S" and rows[0]["r_km"] == "1.52" and rows[0]["status"] == "planned"
F.update("21641_20261006T0426", fav, status="observed")                    # every change rewrites the CSV
assert list(csv.DictReader(open(os.path.join(fav, "favorites.csv"))))[0]["status"] == "observed"
rec2 = dict(rec, target_id="17834", best_utc="2026-10-03T02:53:07")
F.add(rec2, run, maps, fav)                                                 # added without size data
assert F.shape_text(e) == "", "bulk rows hold no shape data"
full = dict(cache, source="sbdb.api", phys=dict(cache["phys"], rot_per={"value": "5.3", "ref": "LCDB"},
                                                 extent={"value": "18.2x10.5x8.9", "ref": "x"}, spec_B={"value": "S"},
                                                 orbit={"value": "JPL#23 of 2026-03-14", "ref": "U 0"}))
assert F.backfill_phys(lambda t: full if t == "17834" else None, fav) == 1
assert F.backfill_phys(lambda t: full, fav) == 1, "21641 came from a bulk row: fetched once more"
assert F.backfill_phys(lambda t: full, fav) == 0, "once per favorite"
assert F.shape_text(F.load(fav)[0]) == "axes 18.2 x 10.5 x 8.9 km · rotation 5.3 h · type S", F.load(fav)[0]
est = dict(F.load(fav)[0], record=dict(rec, size_source="H only, albedo assumed"))
assert F.size_text(est).endswith("* estimate, uncertain by a factor ~1.7"), F.size_text(est)
# preview and globe plot kept apart (report lookup, favorite copies, filling in later globes)
from pysyzygos import report as R
assert R.size_estimated({"size_src": "H only, albedo assumed"}) and not R.size_estimated({"size_src": "SBDB diameter"})
from datetime import datetime, timezone
when = datetime(2026, 10, 3, 2, 53, 7, tzinfo=timezone.utc)
open(os.path.join(maps, "17834_20261003T0253_globe.svg"), "w").write("<svg id='globe'/>")
assert R.find_kml(maps, "17834", when, "svg") is None, "only a globe there: no preview"
assert R.find_kml(maps, "17834", when, "globe").endswith("_globe.svg")
open(os.path.join(maps, "17834_20261003T0253.svg"), "w").write("<svg id='preview'/>")
assert R.find_kml(maps, "17834", when, "svg").endswith("17834_20261003T0253.svg")
F.remove_many(F.keys(fav), fav)
assert F.add(F.find_record(log, "17834", "2026-10-03T02:53:07"), run, maps, fav)[0]
e = F.load(fav)[0]
assert e["files"]["svg"].endswith("T0253.svg") and e["files"]["globe"].endswith("_globe.svg"), e["files"]
F.add(F.find_record(log, "19714", "2026-10-04T06:38:06"), run, maps, fav)          # no globe in maps for it
open(os.path.join(maps, "19714_20261004T0638_globe.svg"), "w").write("<svg/>")      # ... until a later search
assert F.backfill_globes(maps, fav) == 1 and F.backfill_globes(maps, fav) == 0
assert "globe" in F.load(fav)[0]["files"]
# close/double stars for favorites added before the check: filled in once, shown as a line
seen = []
def check(r):
    seen.append(r["target_id"])
    return dict(blend_n=1, blend_sep_arcsec=2.8, blend_g=17.4, mag_drop_blended=3.31, double_check="local",
                double_hint="companion G 17.4 at 2.8\u2033: drop 3.31 mag with its light", gaia_ruwe=float("nan"))
n0 = len(F.load(fav))
assert F.backfill_doubles(check, fav) == n0 and F.backfill_doubles(check, fav) == 0, "once per favorite"
e = F.load(fav)[0]
assert e["record"]["gaia_ruwe"] is None and F.double_text(e).endswith("with its light (local catalog)")
e["record"]["double_hint"] = ""
assert F.double_text(e) == "none known (local catalog)"
assert F.backfill_doubles(lambda r: None, fav) == 0
# OWC-style event summary: from the record (new fields of search.event_context) and, for older favorites, a
# one-time lookup (Horizons stand-in) plus From/To from the KML's minute marks
rec2 = dict(target_id="369152", target_name="369152 (2008 SJ52)", best_utc="2026-10-12T04:58:57.081", star="3160985089639151616",
            mag="8.05", m_ast="22.31", r_km="0.945", r_min_km="0.8", r_max_km="1.1", speed_kms="14.44", max_duration_s="0.13",
            mag_drop="14.26", moon_illum_pct="2.7", moon_sep_deg="108.8", star_ra="106.75688", star_dec="12.32521",
            path_sigma1_km="79.7", sigma_source="Horizons", kind="asteroid", double_check="local")
info = dict(F.event_info(dict(record=dict(rec2, dist_au="3.0826", sun_elong_deg="91.86", shadow_from_utc="2026-10-12T04:58:46",
                                          shadow_to_utc="2026-10-12T05:13:07"), key="k", version="x")))
ev, obj = dict(info["Event"]), dict(info["Object"])
assert ev["From"] == "04:58:46 UT" and ev["Solar elong."] == "92°" and ev["Shadow width"] == "1.9 km"
assert obj["Distance"] == "3.0826 au" and obj["Diameter (angular)"] == "0.85 mas"
assert set(info) == {"Prediction", "Event", "Star", "Object"} and "Satellites" in dict(info["Object"])
open(os.path.join(maps, "369152_20261012T0458.kml"), "w").write("<kml><name>04:59 UTC</name><name>05:13 UTC</name></kml>")
ok, msg = F.add(rec2, run, maps, fav)
assert ok, msg
calls = []
n = F.backfill_event(lambda tid, utc: calls.append(tid) or dict(dist_au=3.08, motion_ra_ash=20.75, motion_dec_ash=-10.72,
                                                                sun_elong_deg=91.86), fav)
e2 = next(x for x in F.load(fav) if x["key"] == "369152_20261012T0458")
assert e2["record"]["shadow_from_utc"] == "~2026-10-12T04:59" and abs(float(e2["record"]["m_combined"]) - 8.05) < 0.01
assert dict(dict(F.event_info(e2))["Event"])["From"] == "≈ 04:59 UT"
assert F.backfill_event(lambda tid, utc: calls.append(tid), fav) == 0 and len(calls) == n, "once per favorite"
# the star's proper motion and its source (record fields since 1.3.2; older records: from star_kind)
assert F.pm_text(dict(star_pmra=-4.0, star_pmdec=-13.0, star_pm_err=1.7, star_pm_source="UCAC5")) == \
    "-4.00, -13.00 \u00b1 1.70 mas/yr (UCAC5)"
assert F.pm_text(dict(star_kind="5")) == "UCAC4 epoch to Gaia" and F.pm_text({}) == "Gaia DR3"
assert F.pm_text(dict(star_kind="2")).startswith("none")
print("FAVORITES TESTS PASSED")
