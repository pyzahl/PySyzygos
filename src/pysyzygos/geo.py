"""geo.py - approximate observer positions: from the IP address (ipinfo.io), a place name (Open-Meteo geocoding),
observatories with their MPC codes (Minor Planet Center), ground elevation and time zone (Open-Meteo). Used by setup.py and
gui.py. Standard library only. parse_coords(): site coordinates pasted as text in the usual formats. on_land(),
earth_site(): an event's own point (anywhere on Earth searches) as a favorite's site, offline.

All results are approximate: IP positions are city level (10-100 km off, wrong behind a VPN), place names give the town
centre. Use an exact position (GPS, map) for observing.
"""
from pysyzygos.version import __version__
from pysyzygos import net                      # https with certifi's certificate authorities
from pysyzygos import urls as U
import json, re, urllib.parse, urllib.request


def get_json(url, timeout=10):
    req = urllib.request.Request(url, headers={"User-Agent": "PySyzygos"})
    with net.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def elevation(lat, lon):
    """Ground elevation (m) from Open-Meteo, or None."""
    try:
        return float(get_json(f"{U.URL_OPENMETEO_ELEVATION}?latitude={lat}&longitude={lon}")["elevation"][0])
    except Exception:
        return None


MPC_OBSCODES_URL = U.URL_MPC_OBSCODES
_MPC = None


def mpc_geodetic(lon_e, rho_cos, rho_sin, a=6378.137, f=1 / 298.257223563):
    """(lat_deg, lon_deg in -180..180, height_m) from the MPC parallax constants rho*cos(phi'), rho*sin(phi') (in Earth
    equatorial radii) and the east longitude; geodetic on the WGS84 ellipsoid (iterative)."""
    import math
    x, z = rho_cos * a, rho_sin * a
    e2 = f * (2 - f)
    lat = math.atan2(z, x * (1 - e2))
    for _ in range(8):
        n = a / math.sqrt(1 - e2 * math.sin(lat) ** 2)
        h = x / math.cos(lat) - n if abs(math.cos(lat)) > 1e-9 else abs(z) - n * (1 - e2)
        lat = math.atan2(z, x * (1 - e2 * n / (n + h)))
    return math.degrees(lat), (lon_e + 180.0) % 360.0 - 180.0, h * 1000.0


def mpc_observatories(folder="data", url=MPC_OBSCODES_URL):
    """The MPC observatory codes (Minor Planet Center ObsCodes.html: about 2500 observatories with their official
    code) as a list of dicts code, name, lat, lon, ele (m), ele_ok, sorted by code. Downloaded once into
    <folder>/ObsCodes.html (not in git), then read from there; [] if neither works. Codes without a position
    (spacecraft, roving observers) are skipped. ele_ok is False when the parallax constants have fewer than 5
    decimals: the height is then only good to about a kilometre (look it up instead)."""
    global _MPC
    if _MPC is not None:
        return _MPC
    import os, tempfile
    path = os.path.join(folder, "ObsCodes.html")
    if not os.path.isfile(path):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "PySyzygos"})
            with net.urlopen(req, timeout=30) as r:
                data = r.read()
            os.makedirs(folder, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=folder, suffix=".tmp")
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
            os.chmod(tmp, 0o644)
            os.replace(tmp, path)
        except Exception:
            return []
    out = []
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.rstrip("\r\n")
                code, lon_s, c_s, s_s, name = line[0:3], line[4:13], line[13:21], line[21:30], line[30:].strip()
                if len(line) < 31 or not code.strip() or code == "Cod" or not lon_s.strip() or not c_s.strip():
                    continue
                try:
                    lon_e, rc, rs = float(lon_s), float(c_s), float(s_s)
                except ValueError:
                    continue
                if rc == 0.0 and rs == 0.0:                                 # geocentric (500)
                    continue
                lat, lon, ele = mpc_geodetic(lon_e, rc, rs)
                dec = min(len(c_s.strip().split(".")[-1]), len(s_s.strip().lstrip("+-").split(".")[-1]))
                out.append(dict(code=code.strip(), name=name, lat=lat, lon=lon, ele=ele, ele_ok=dec >= 5))
    except OSError:
        return []
    _MPC = sorted(out, key=lambda o: o["code"])
    return _MPC


def timezone(lat, lon):
    """IANA time zone name at a place (e.g. "Europe/Zurich") from Open-Meteo, or None."""
    try:
        return get_json(f"{U.URL_OPENMETEO_FORECAST}?latitude={lat}&longitude={lon}"
                        f"&timezone=auto&forecast_days=1&daily=sunrise").get("timezone") or None
    except Exception:
        return None


def ip_location():
    """(lat, lon, ele, label) from the IP address, or None. Sends the IP address to ipinfo.io."""
    try:
        d = get_json(U.URL_IPINFO)
        lat, lon = (float(x) for x in d["loc"].split(","))
        return lat, lon, elevation(lat, lon), ", ".join(x for x in (d.get("city"), d.get("region"), d.get("country")) if x)
    except Exception:
        return None


def places(name, count=5):
    """Places matching a name: list of (lat, lon, ele, label), best first (Open-Meteo geocoding). Empty if none/offline."""
    try:
        res = get_json(U.URL_OPENMETEO_GEOCODING + "?"
                       + urllib.parse.urlencode(dict(name=name, count=count))).get("results", [])
    except Exception:
        return []
    return [(r["latitude"], r["longitude"], r.get("elevation"),
             ", ".join(x for x in (r["name"], r.get("admin1"), r.get("country")) if x)) for r in res]


# ---------------------------------------------------------------- an event's own point (anywhere on Earth)
_LAND = None


def on_land(lat, lon):
    """True if the point is on land (Natural Earth 1:110m land polygons, data/ne_110m_earth.json; coasts to ~10 km)."""
    global _LAND
    if _LAND is None:
        import os
        try:
            with open(os.path.join(os.path.dirname(__file__), "data", "ne_110m_earth.json"), encoding="utf-8") as fh:
                _LAND = [list(zip(r[0::2], r[1::2])) for r in json.load(fh).get("land", [])]
        except (OSError, ValueError):
            _LAND = []
    lon = (float(lon) + 180.0) % 360.0 - 180.0
    lat = float(lat)
    inside = False
    for ring in _LAND:
        n = len(ring)
        for i in range(n):                                   # ray casting (even-odd), longitudes as given
            (x1, y1), (x2, y2) = ring[i], ring[(i + 1) % n]
            if (y1 > lat) != (y2 > lat) and lon < x1 + (lat - y1) * (x2 - x1) / (y2 - y1):
                inside = not inside
    return inside


def earth_site(lat, lon):
    """A favorite's site for an event of an anywhere-on-Earth search: the event's own point (where the shadow's
    center is best seen), named by its coordinates, '(ocean)' off the land; not the site chosen in the header."""
    lat, lon = float(lat), float(lon)
    name = (f"{abs(lat):.2f}\u00b0 {'N' if lat >= 0 else 'S'}, {abs(lon):.2f}\u00b0 {'E' if lon >= 0 else 'W'}"
            + ("" if on_land(lat, lon) else " (ocean)"))
    return dict(name=name, lat=round(lat, 5), lon=round(lon, 5), ele=0.0, scope="earth")


# ---------------------------------------------------------------- coordinates pasted as text
_NORM = [("\u2032", "'"), ("\u2019", "'"), ("\u2018", "'"), ("\u00b4", "'"), ("`", "'"), ("\u2033", '"'),
         ("\u201d", '"'), ("\u201c", '"'), ("''", '"'), ("\u00ba", "\u00b0"), ("\u02da", "\u00b0"),
         ("\u2212", "-"), ("\u2013", "-"), ("\u2014", "-"), ("\u00a0", " ")]
_LABEL = re.compile(r"(?<![a-z])(latitude|lat|longitude|long|lng|lon|altitude|alt|elevation|elev|ele|height|"
                    r"breite|l\u00e4nge|laenge|h\u00f6he|hoehe|h(?=\s*[:=]))(?![a-z])\s*[:=]?", re.I)
_KIND = {"latitude": "lat", "lat": "lat", "breite": "lat", "longitude": "lon", "long": "lon", "lng": "lon",
         "lon": "lon", "l\u00e4nge": "lon", "laenge": "lon"}
_NUM = re.compile(r"[+-]?\d+(?:\.\d+)?")
_HEMI = re.compile(r"(?<![a-z])([nsew])(?![a-z])", re.I)


def _angle(seg):
    """(degrees, hemisphere letter or None) from one coordinate: decimal degrees, degrees + decimal minutes, or
    degrees, minutes, seconds (any of the symbols ° ' " d m s : or spaces), signed or with N/S/E/W."""
    hemi = _HEMI.findall(seg)
    nums = _NUM.findall(_HEMI.sub(" ", seg))
    if not nums or len(nums) > 3:
        raise ValueError(f"not a coordinate: {seg.strip()!r}")
    neg = nums[0].startswith("-")
    d, m, s = (abs(float(x)) for x in nums + ["0"] * (3 - len(nums)))
    if m >= 60 or s >= 60:
        raise ValueError(f"minutes or seconds >= 60 in {seg.strip()!r}")
    h = hemi[-1].upper() if hemi else None
    v = d + m / 60.0 + s / 3600.0
    return (-v if neg or h in ("S", "W") else v), h


def _height(seg):
    """Metres from '132 m', '433 ft', '0.13 km', '132'."""
    m = re.search(r"([+-]?\d+(?:\.\d+)?)\s*(km|m|ft|feet|foot|')?", seg, re.I)
    if not m:
        raise ValueError(f"not a height: {seg.strip()!r}")
    unit = (m.group(2) or "m").lower()
    return float(m.group(1)) * {"km": 1000.0, "m": 1.0, "ft": 0.3048, "feet": 0.3048, "foot": 0.3048, "'": 0.3048}[unit]


def _split_unlabeled(text):
    """Coordinate segments of text without labels."""
    parts = [p for p in re.split(r"[,;\n\t/|]+", text) if p.strip()]
    if len(parts) > 1:
        return parts
    letters = list(_HEMI.finditer(text))
    if len(letters) >= 2:                                           # N 37 01 27 W 121 57 19  or  37 01 27 N 121 ... W
        lead = text.strip()[:1].upper() in "NSEW"
        cuts = [m.start() for m in letters[1:]] if lead else [m.end() for m in letters[:-1]]
        bounds = [0] + cuts + [len(text)]
        return [text[a:b] for a, b in zip(bounds, bounds[1:]) if text[a:b].strip()]
    degs = list(re.finditer(r"[+-]?\d+(?:\.\d+)?\s*\u00b0", text))
    if len(degs) >= 2:                                              # 37°01'27" -121°57'19"
        bounds = [0] + [m.start() for m in degs[1:]] + [len(text)]
        return [text[a:b] for a, b in zip(bounds, bounds[1:]) if text[a:b].strip()]
    nums = _NUM.findall(text)
    if 2 <= len(nums) <= 3 and not re.search(r"[\u00b0'\":]", text):   # 37.0242 -121.9553 [132]
        return nums
    toks = text.split()
    if ":" in text and len(toks) >= 2 and all(re.fullmatch(r"[+-]?[\d.:]+(km|m|ft)?", x, re.I) for x in toks):
        return toks                                                 # 37:01:27 -121:57:19 132m
    return [text]


def parse_coords(text, field=None):
    """Site coordinates from pasted text, e.g. 'Lng: -121° 57' 19", Lat: +37° 01' 27", Alt: 132 m',
    '37.02417, -121.95528', '37°01'27"N 121°57'19"W', 'N 37 01.45 W 121 57.32', '37:01:27 -121:57:19 132m'.
    Labels (lat/latitude, lon/lng/long/longitude, alt/elevation/height) in any order; without labels N/S and E/W
    decide, else latitude first (as Google Maps copies them), then longitude, then the height. Heights in m, ft or km.
    field ('lat', 'lon', 'ele'): where a single unlabeled value was pasted. Returns dict(lat, lon, ele) with None for
    what the text does not give; longitudes east-positive in -180..180. Raises ValueError if nothing usable."""
    t = str(text or "")
    for a, b in _NORM:
        t = t.replace(a, b)
    out = dict(lat=None, lon=None, ele=None)
    labels = list(_LABEL.finditer(t))
    if labels:
        for m, end in zip(labels, [x.start() for x in labels[1:]] + [len(t)]):
            seg = t[m.end():end].strip(" ,;\t\n")
            kind = _KIND.get(m.group(1).lower(), "ele")
            if seg:
                out[kind] = _height(seg) if kind == "ele" else _angle(seg)[0]
    else:
        order = []
        for seg in _split_unlabeled(t):
            if re.search(r"\d\s*(km|m|ft|feet)\b", seg, re.I) and not re.search(r"[\u00b0'\"]", seg):
                out["ele"] = _height(seg)
                continue
            v, h = _angle(seg)
            if h in ("N", "S"):
                out["lat"] = v
            elif h in ("E", "W"):
                out["lon"] = v
            else:
                order.append(v)
        if len(order) == 1 and field in ("lat", "lon", "ele") and out["lat"] is None and out["lon"] is None:
            out[field] = order.pop()
        for k in ("lat", "lon", "ele"):
            if order and out[k] is None:
                out[k] = order.pop(0)
        if out["lat"] is not None and abs(out["lat"]) > 90 and out["lon"] is not None and abs(out["lon"]) <= 90:
            out["lat"], out["lon"] = out["lon"], out["lat"]           # longitude given first
    if out["lon"] is not None and out["lon"] > 180:
        out["lon"] -= 360.0
    if out["lat"] is not None and abs(out["lat"]) > 90:
        raise ValueError(f"latitude {out['lat']:g} beyond +-90")
    if out["lon"] is not None and abs(out["lon"]) > 180:
        raise ValueError(f"longitude {out['lon']:g} beyond +-180")
    if all(v is None for v in out.values()):
        raise ValueError("no coordinates found")
    return out
