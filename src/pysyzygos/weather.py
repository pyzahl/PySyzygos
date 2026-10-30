"""weather.py - cloud forecast for the favorites' sites at their event times (Open-Meteo).

Open-Meteo (https://open-meteo.com, free, no key) answers hourly forecasts for any place on the Earth up to 16 days
ahead, from the best model for that place ("best_match": e.g. HRRR/NAM in the US, ICON-D2 in central Europe, else the
global ECMWF IFS/GFS/ICON). One request per site, on click only (GUI Favorites "Cloud forecast"); the answers are kept
in <data folder>/weather_cache.json and shown in the favorites table (symbol and total cloud cover at the event) and
in the panel (the hours around it, low/mid/high cloud, rain chance, visibility). Clouds are hard to forecast: trust
the last 1-3 days only. Standard library only.
"""
from pysyzygos.version import __version__, __url__
from pysyzygos import net                      # https with certifi's certificate authorities
from pysyzygos import urls as U
import json, math, os, tempfile, time, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timezone

CACHE = "weather_cache.json"
FIELDS = ("cloud_cover", "cloud_cover_low", "cloud_cover_mid", "cloud_cover_high", "precipitation_probability",
          "visibility")
DAYS = 16                         # Open-Meteo's longest forecast
PAST_H = 6                        # events this long ago still get the latest forecast
STRIP_H = 3                       # the panel shows the event's hour +- this many hours
UA = f"PySyzygos/{__version__} (+{__url__})"


def site_key(lat, lon):
    """Cache key of a site: position to 0.01 deg (~1 km; the models' grids are 3-25 km)."""
    return f"{float(lat):.2f},{float(lon):.2f}"


def _get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with net.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as ex:                         # name the request: which one failed, and how
        raise OSError(f"HTTP {ex.code} {ex.reason} for {url}") from None
    except urllib.error.URLError as ex:
        raise OSError(f"{ex.reason} for {url}") from None


def forecast(lat, lon):
    """Hourly forecast at the site: dict(fetched, model, time [unix s UTC], <FIELDS> lists)."""
    q = urllib.parse.urlencode(dict(latitude=f"{float(lat):.4f}", longitude=f"{float(lon):.4f}",
                                    hourly=",".join(FIELDS), timezone="UTC", timeformat="unixtime",
                                    forecast_days=DAYS))
    j = _get(f"{U.URL_OPEN_METEO}?{q}")
    h = j.get("hourly") or {}
    if not h.get("time"):
        raise OSError(f"no hourly forecast in the answer for {lat}, {lon}")
    return dict(fetched=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"), model="best_match",
                time=h["time"], **{k: h.get(k) or [None] * len(h["time"]) for k in FIELDS})


def load(folder="."):
    try:
        with open(os.path.join(folder, CACHE), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save(cache, folder):
    fd, tmp = tempfile.mkstemp(dir=os.path.abspath(folder), suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(cache, f)
    os.replace(tmp, os.path.join(folder, CACHE))


def _unix(utc):
    s = str(utc).strip().replace(" ", "T").rstrip("Z")
    return datetime.fromisoformat(s[:19]).replace(tzinfo=timezone.utc).timestamp()


def in_range(utc, now=None):
    """True when Open-Meteo has a forecast for this time (from PAST_H ago to DAYS ahead)."""
    now = time.time() if now is None else now
    t = _unix(utc)
    return now - PAST_H * 3600 <= t <= now + DAYS * 86400 - 3600


def check(entries, folder=".", now=None):
    """Fetch the forecast for every site with a favorite in range (entries: favorites.load()). Returns (sites,
    events, errors)."""
    sites, n = {}, 0
    for e in entries:
        s, r = e.get("site") or {}, e.get("record") or {}
        if s.get("lat") is None or s.get("lon") is None or not r.get("best_utc") or not in_range(r["best_utc"], now):
            continue
        sites[site_key(s["lat"], s["lon"])] = (s["lat"], s["lon"])
        n += 1
    cache, errors = load(folder), []
    for k, (lat, lon) in sites.items():
        try:
            cache[k] = forecast(lat, lon)
        except Exception as ex:                                   # network trouble: keep going, report it
            errors.append(f"site {k}: {str(ex)[:300]}")
    if sites:
        _save(cache, folder)
    return len(sites), n, errors


def _at(fc, field, t):
    """The field linearly between the hours around t (None outside the forecast or when missing)."""
    ts, vs = fc["time"], fc.get(field) or []
    if not ts or t < ts[0] or t > ts[-1]:
        return None
    i = min(max(0, int((t - ts[0]) // 3600)), len(ts) - 2)
    a, b = vs[i], vs[i + 1]
    if a is None or b is None:
        return a if b is None else b
    f = (t - ts[i]) / max(ts[i + 1] - ts[i], 1)
    return a + (b - a) * f


def info(lat, lon, utc, cache):
    """The forecast at the event: dict(total, low, mid, high, rain, vis_km, fetched, strip [(hour unix, total, low,
    mid, high, rain)]) or None (no forecast for this site and time)."""
    if lat is None or lon is None or not utc:
        return None
    fc = cache.get(site_key(lat, lon))
    if not fc:
        return None
    t = _unix(utc)
    tot = _at(fc, "cloud_cover", t)
    if tot is None:
        return None
    vis = _at(fc, "visibility", t)
    h0 = int(t // 3600) * 3600
    strip = []
    for k in range(-STRIP_H, STRIP_H + 1):
        hh = h0 + k * 3600
        if hh in fc["time"]:
            i = fc["time"].index(hh)
            strip.append((hh, *(fc[f][i] for f in FIELDS[:5])))
    return dict(total=tot, low=_at(fc, "cloud_cover_low", t), mid=_at(fc, "cloud_cover_mid", t),
                high=_at(fc, "cloud_cover_high", t), rain=_at(fc, "precipitation_probability", t),
                vis_km=None if vis is None else vis / 1000.0, fetched=fc.get("fetched", ""), strip=strip)


def symbol(total):
    """Sky symbol for a total cloud cover (%): clear night, partly cloudy, mostly cloudy, overcast."""
    if total is None:
        return ""
    return "🌙" if total <= 20 else "⛅" if total <= 50 else "🌥" if total <= 80 else "☁"


def level(total):
    """'clear' | 'part' | 'cloudy' (CSS class of the badge)."""
    return "clear" if total <= 20 else "part" if total <= 60 else "cloudy"


def _pct(v):
    return "–" if v is None else f"{v:.0f} %"


def short(w):
    """'🌙 12 %' for the table."""
    return f"{symbol(w['total'])} {w['total']:.0f} %" if w else ""


def text(w):
    """One line for the hover and the panel."""
    if not w:
        return ""
    out = (f"Cloud cover at the event {_pct(w['total'])} (low {_pct(w['low'])}, mid {_pct(w['mid'])}, high "
           f"{_pct(w['high'])})")
    if w.get("rain") is not None:
        out += f", rain chance {_pct(w['rain'])}"
    if w.get("vis_km") is not None:
        out += f", visibility {w['vis_km']:.0f} km"
    return out + f". Open-Meteo forecast of {w['fetched'][:16].replace('T', ' ')} UTC"


def strip_html(w, tz=None):
    """The hours around the event as a small HTML table (UTC hours, local in the hover when tz is given)."""
    if not w or not w.get("strip"):
        return ""
    try:
        from zoneinfo import ZoneInfo
        z = ZoneInfo(tz) if tz else None
    except Exception:
        z = None
    head, row = [], []
    for hh, tot, lo, mid, hi, rain in w["strip"]:
        d = datetime.fromtimestamp(hh, timezone.utc)
        loc = f" ({d.astimezone(z):%H:%M %Z})" if z else ""
        tip = f"{d:%Y-%m-%d %H:%M} UTC{loc}: low {_pct(lo)}, mid {_pct(mid)}, high {_pct(hi)}, rain {_pct(rain)}"
        col = "#15803d" if tot is not None and tot <= 20 else "#b45309" if tot is not None and tot <= 60 else "#64748b"
        head.append(f'<th style="padding:0 6px;font-weight:500">{d:%H}h</th>')
        row.append(f'<td title="{tip}" style="padding:0 6px;text-align:center;color:{col}">{symbol(tot)}<br>'
                   f'{"–" if tot is None else f"{tot:.0f}"}</td>')
    return ('<table style="font-size:.8rem;border-collapse:collapse"><tr><th style="text-align:left;'
            'font-weight:500;padding-right:6px">UTC</th>' + "".join(head) + '</tr><tr><td style="padding-right:6px">'
            'clouds %</td>' + "".join(row) + "</tr></table>")
