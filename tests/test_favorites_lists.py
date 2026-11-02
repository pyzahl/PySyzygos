"""favorites.py saved lists (save_list / lists / load_list replace and add / delete_list, PREVIOUS) and the map of all
paths (glance_data / write_glance). Temporary folder; no network, no SPICE."""
import json, os, re, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
from pysyzygos import favorites as F

tmp = tempfile.mkdtemp()
maps, fav = os.path.join(tmp, "maps"), os.path.join(tmp, "favorites")
os.makedirs(maps)
KML = """<?xml version="1.0" encoding="UTF-8"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document>
<Placemark><name>Centre line</name><LineString><coordinates>-73,40,0 -72,41,0 -71,42,0</coordinates></LineString></Placemark>
<Placemark><name>Shadow limit A</name><LineString><coordinates>-73,40.1,0 -71,42.1,0</coordinates></LineString></Placemark>
<Placemark><name>3-sigma limit A</name><LineString><coordinates>-73,40.5,0 -71,42.5,0</coordinates></LineString></Placemark>
<Placemark><name>Observer</name><Point><coordinates>-72.9,40.9,0</coordinates></Point></Placemark>
</Document></kml>"""
recs = [dict(target_id="3200", target_name="3200 Phaethon (1983 TB)", best_utc="2026-11-02T01:09:10.379", mag="11.2"),
        dict(target_id="63", target_name="63 Ausonia (A861 GA)", best_utc="2026-11-05T03:00:00.000", mag="10.1")]
for r in recs:
    stem = F.key_of(r["target_id"], r["best_utc"])
    open(os.path.join(maps, stem + ".kml"), "w").write(KML)
    open(os.path.join(maps, stem + ".svg"), "w").write("<svg/>")
run = dict(site=dict(name="Home", lat=40.9, lon=-72.9))
for r in recs:
    assert F.add(r, run, maps, fav)[0]
keys = [e["key"] for e in F.load(fav)]
os.makedirs(os.path.join(fav, keys[0], "pathcheck", "run"))
open(os.path.join(fav, keys[0], "pathcheck", "run", "big.db"), "w").write("x")     # not copied into a list
open(os.path.join(fav, keys[0], "pathcheck", "orbit.bsp"), "w").write("x")

# save: default name from the last added entry's date; a second save under that name is refused unless overwrite
name = F.default_list_name(F.load(fav))
assert re.fullmatch(r"favorites \d{4}-\d\d-\d\d", name), name
ok, msg = F.save_list(folder=fav)
assert ok and "2 favorites" in msg, msg
assert not F.save_list(name, fav)[0] and F.save_list(name, fav, overwrite=True)[0]
slug = F.list_slug(name)
saved = os.path.join(fav, F.LISTS, slug)
assert os.path.isfile(os.path.join(saved, "files", keys[0], os.path.basename(F.load(fav)[0]["files"]["kml"])))
assert not os.path.exists(os.path.join(saved, "files", keys[0], "pathcheck", "run"))
assert not os.path.exists(os.path.join(saved, "files", keys[0], "pathcheck", "orbit.bsp"))
ls = F.lists(fav)
assert [m["name"] for m in ls] == [name] and ls[0]["n"] == 2 and ls[0]["span"] == "2026-11-02 to 2026-11-05", ls
assert F.list_slug("a/b: c") == "a_b_c" and F.list_slug("..") == "list"

# saved or changed since: decides whether replacing them asks first
assert F.saved_as(fav) == name
F.update(keys[0], fav, note="changed")
assert F.saved_as(fav) is None
F.update(keys[0], fav, note="")
assert F.saved_as(fav) == name
# replace: the current ones go to PREVIOUS, the list's entries and files come back
assert F.remove_many(keys, fav)[0] and not F.load(fav)
assert not os.path.isdir(os.path.join(fav, keys[0]))
ok, msg = F.load_list(slug, fav)
assert ok and "2 favorites" in msg and "before" not in msg, msg
assert sorted(e["key"] for e in F.load(fav)) == sorted(keys)
assert os.path.isfile(os.path.join(fav, F.load(fav)[0]["files"]["kml"]))
F.update(keys[0], fav, status="observed", note="negative")
F.remove(keys[1], fav)
ok, msg = F.load_list(slug, fav)                                  # replace again: the edited one-entry list is kept
assert ok and F.PREVIOUS in msg, msg
assert any(m["name"] == F.PREVIOUS and m["n"] == 1 for m in F.lists(fav))
assert {e["key"]: e["status"] for e in F.load(fav)}[keys[0]] == "planned"
ok, msg = F.load_list(F.PREVIOUS, fav)                             # back to the state before (PREVIOUS loads itself)
assert ok and [(e["key"], e["status"], e["note"]) for e in F.load(fav)] == [(keys[0], "observed", "negative")]
assert os.path.isfile(os.path.join(fav, F.load(fav)[0]["files"]["kml"]))
assert not os.path.isdir(os.path.join(fav, keys[1]))               # replaced: its folder went with it
ok, msg = F.load_list(slug, fav, mode="add")                       # add: only the missing one
assert ok and "added 1 favorite" in msg, msg
assert len(F.load(fav)) == 2 and {e["key"]: e["note"] for e in F.load(fav)}[keys[0]] == "negative"
assert not F.load_list("nope", fav)[0] and not F.delete_list("nope", fav)[0]
assert F.delete_list(slug, fav)[0] and all(m["slug"] != slug for m in F.lists(fav))

# the map of all paths: lines center / shadow / 1-sigma only, title with target and date, one color each
d = F.glance_data(fav)
assert [x["title"] for x in d] == ["(3200) Phaethon · 2026-11-02 01:09 UT", "(63) Ausonia · 2026-11-05 03:00 UT"], d
assert [ln["kind"] for ln in d[0]["lines"]] == ["Centre", "Shadow limit"] and d[0]["sites"] == [[40.9, -72.9]]
assert d[0]["color"] != d[1]["color"]
from pysyzygos import report as R
only = [R.event_key("63", "2026-11-05T03:00:00.000")]
assert [x["key"] for x in F.glance_data(fav, only)] == [F.key_of("63", "2026-11-05T03:00")]
path, n = F.write_glance(fav)
page = open(path, encoding="utf-8").read()
data = json.loads(re.search(r'id="glancedata" type="application/json">(.*?)</script>', page, re.S).group(1))
assert n == 2 and len(data) == 2 and "__" not in page.replace("__proto__", ""), "placeholders left"
assert "leaflet" in page and "2 of 2 favorites" in page
# past observed events -> the list "observed": moved (or copied), added to what it holds, newer copy wins
k3200, k63 = F.key_of("3200", "2026-11-02T01:09"), F.key_of("63", "2026-11-05T03:00")
F.update(k3200, fav, status="observed", note="negative")
F.update(k63, fav, status="observed", note="later")
assert F.past_observed(fav, now="2026-11-03T00:00:00") == [k3200]               # 63 not yet happened
assert not F.archive_observed(fav, now="2026-11-01T00:00:00")[0]
ok, msg = F.archive_observed(fav, move=False, now="2026-11-03T00:00:00")
assert ok and "added to the list" in msg and "(1 in it)" in msg, msg
assert len(F.load(fav)) == 2                                                    # copy only
F.update(k3200, fav, note="negative, checked")
ok, msg = F.archive_observed(fav, now="2026-11-10T00:00:00")                    # both now: moved
assert ok and "2 observed events moved" in msg and "(2 in it)" in msg, msg
assert not F.load(fav) and not os.path.isdir(os.path.join(fav, k3200))
obs = json.load(open(os.path.join(fav, F.LISTS, "observed", "list.json")))
assert [e["key"] for e in obs["entries"]] == [k63, k3200] and obs["entries"][1]["note"] == "negative, checked"
assert os.path.isfile(os.path.join(fav, F.LISTS, "observed", "files", k3200, os.path.basename(obs["entries"][1]["files"]["kml"])))
assert F.load_list("observed", fav)[0] and len(F.load(fav)) == 2                 # and back
F.update(k63, fav, status="planned")                                            # a list of the user's own name
ok, msg = F.archive_observed(fav, name="my observed events", now="2026-11-10T00:00:00")
assert ok and "\u201cmy observed events\u201d (1 in it)" in msg, msg
assert [e["key"] for e in F.load(fav)] == [k63]
assert any(m["name"] == "my observed events" and m["slug"] == "my_observed_events" for m in F.lists(fav))
# when the prediction was computed: the search run, else when added; orbit solution if known
e = dict(run=dict(run_utc="2026-10-30T01:47:07"), added="2026-10-30T01:48:37",
         phys=dict(orbit=["JPL#1029 of 2026-10-28", "condition code U 0"]))
assert F.predicted_utc(e) == "2026-10-30T01:47:07" and F.predicted_utc(dict(added="2026-10-01T00:00:00")) == "2026-10-01T00:00:00"
assert F.prediction_text(e) == "predicted 2026-10-30 01:47 UT (search run), orbit JPL#1029 of 2026-10-28; added 2026-10-30 01:48 UT"
assert F.prediction_text({}) == "prediction time not known"
assert 'pred. ' not in open(F.write_page(fav), encoding="utf-8").read()          # the panel only, not the table
print("FAVORITES LISTS TESTS PASSED")
