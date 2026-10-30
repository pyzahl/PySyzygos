"""Cloud forecast (pysyzygos.weather): the request, the cache per site, values at the event time, the table badge.
No network: weather._get is replaced by a stand-in that answers like Open-Meteo."""
import sys, os, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
from pysyzygos import weather, urls as U

T0 = 1793577600                                    # 2026-11-02 00:00 UTC
calls = []
def fake_get(url, timeout=30):
    calls.append(url)
    assert url.startswith(U.URL_OPEN_METEO + "?") and "cloud_cover_low" in url and "timeformat=unixtime" in url, url
    ts = [T0 + 3600 * k for k in range(-24, 48)]
    tot = [10.0] * len(ts)
    tot[24], tot[25] = 20.0, 80.0                  # 00:00 and 01:00 UTC
    return dict(hourly=dict(time=ts, cloud_cover=tot, cloud_cover_low=[0.0] * len(ts),
                            cloud_cover_mid=[5.0] * len(ts), cloud_cover_high=tot,
                            precipitation_probability=[None] * len(ts), visibility=[24140.0] * len(ts)))
weather._get = fake_get

fav = lambda key, lat, lon, utc: dict(key=key, site=dict(lat=lat, lon=lon, tz="America/New_York"),
                                      record=dict(best_utc=utc, target_id="3200"))
items = [fav("a", 40.95497, -72.92809, "2026-11-02T00:30:00.0"),
         fav("b", 40.95490, -72.92811, "2026-11-02T01:09:10.4"),       # same site (same 0.01 deg cell): one request
         fav("c", 46.99, 9.64, "2026-11-01T22:00:00"),                   # another site
         fav("d", 46.99, 9.64, "2026-12-30T22:00:00")]                   # beyond 16 days: no request for it
now = T0 - 2 * 86400
with tempfile.TemporaryDirectory() as d:
    sites, n, errors = weather.check(items, d, now=now)
    assert (sites, n, errors) == (2, 3, []) and len(calls) == 2, (sites, n, errors, calls)
    cache = weather.load(d)
    assert set(cache) == {"40.95,-72.93", "46.99,9.64"}, cache.keys()
    w = weather.info(40.95497, -72.92809, "2026-11-02T00:30:00", cache)
    assert abs(w["total"] - 50.0) < 1e-9 and w["low"] == 0.0 and abs(w["vis_km"] - 24.14) < 1e-9, w
    assert len(w["strip"]) == 7 and w["strip"][3][0] == T0, w["strip"]
    assert weather.short(w) == "⛅ 50 %" and weather.level(w["total"]) == "part"
    assert "rain" not in weather.text(w) and "low 0 %" in weather.text(w), weather.text(w)
    assert "UTC" in weather.strip_html(w, "America/New_York") and "EST" in weather.strip_html(w, "America/New_York")
    assert weather.info(40.95497, -72.92809, "2026-12-30T00:00:00", cache) is None      # outside the forecast
    assert weather.info(10.0, 10.0, "2026-11-02T00:30:00", cache) is None               # no forecast there
    assert weather.symbol(5) == "🌙" and weather.symbol(95) == "☁" and weather.level(95) == "cloudy"

# a failing site is reported, the others are kept
def bad_get(url, timeout=30):
    if "latitude=46.99" in url:
        raise OSError("HTTP 503 Service Unavailable")
    return fake_get(url)
weather._get = bad_get
with tempfile.TemporaryDirectory() as d:
    sites, n, errors = weather.check(items, d, now=now)
    assert sites == 2 and len(errors) == 1 and "503" in errors[0] and list(weather.load(d)) == ["40.95,-72.93"]
print("test_weather: all OK")
