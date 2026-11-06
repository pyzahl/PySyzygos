"""An anywhere-on-Earth result starred as a favorite: its site is the event's own point (geo.earth_site: coordinates,
'(ocean)' off the land, offline), not the site chosen in the header; older ones are corrected (backfill)."""
import os, sys, tempfile, json
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
from pysyzygos import geo, favorites

assert geo.on_land(46.99, 9.64) and geo.on_land(-80, 30) and geo.on_land(72, -40)
assert not geo.on_land(0, -30) and not geo.on_land(20, -150) and not geo.on_land(30, 179.9)
assert geo.earth_site(46.99, 9.64)["name"] == "46.99° N, 9.64° E"
assert geo.earth_site(-12.5, -170.2)["name"] == "12.50° S, 170.20° W (ocean)"
d = tempfile.mkdtemp()
header_site = dict(name="Home-Deck", lat=40.95, lon=-72.93, ele=61.0)
rec = dict(target_id="617", best_utc="2026-01-04T22:42:00", scope="earth", ground_lat="47.1", ground_lon="10.2")
ok, msg = favorites.add(dict(rec), dict(site=header_site), map_dir=d, folder=d)
e = favorites.load(d)[0]
assert ok and e["site"]["scope"] == "earth" and e["site"]["lat"] == 47.1 and "N" in e["site"]["name"], e["site"]
ok, _ = favorites.add(dict(rec, target_id="3200", scope="site"), dict(site=header_site), map_dir=d, folder=d)
assert favorites.load(d)[0]["site"]["name"] == "Home-Deck"                  # a site's search: the site, as before
# older favorites: the header's site -> the event's own point
items = favorites.load(d)
for x in items:
    if x["record"].get("scope") == "earth":
        x["site"] = header_site
favorites._save(items, d)
assert favorites.backfill_earth_sites(d) == 1 and favorites.backfill_earth_sites(d) == 0
assert next(x for x in favorites.load(d) if x["record"]["target_id"] == "617")["site"]["scope"] == "earth"
print("EARTH SITE TESTS PASSED")
