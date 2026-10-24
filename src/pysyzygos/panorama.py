"""panorama.py - a site's 360-degree photo (equirectangular, 2:1, as a GoPro MAX / Insta360 / phone 'photo sphere'
saves it) as a picture of its horizon: the horizon line read from a photo whose sky was made transparent (else,
for a clear blue sky, found automatically: sky_mask), the
azimuth reference (the azimuth at the photo's left edge, set by hand or fitted to the site's UserHorizon points), a
thumbnail kept in the data folder (horizons/), and an SVG with the horizon line, the margin and the star drawn on it.

Equirectangular: column x is azimuth az_left + 360 x / W, row y altitude 90 - 180 y / H (the camera level; a tilted
photo shows as a wavy horizon: level it in the camera's app before). Files: horizons/<name>.jpg (STEP_DEG per pixel)
and horizons/<name>.json (profile from the transparent sky, source, size). Needs Pillow.
"""
from pysyzygos.version import __version__
import base64, io, json, math, os, re, time
import numpy as np

STEP_DEG = 0.25                                                # thumbnail and profile resolution (deg per pixel)
FOLDER = "horizons"
SKY_FILL = (36, 64, 107)                                       # transparent sky in the thumbnail
OPAQUE = 128                                                   # alpha from which a pixel is ground


def _image(src):
    from PIL import Image
    im = Image.open(io.BytesIO(src) if isinstance(src, (bytes, bytearray)) else src)
    im.load()
    return im


def check_size(im):
    w, h = im.size
    if abs(w - 2 * h) > max(2, w // 200):
        raise ValueError(f"{w} x {h} pixels is not a 360-degree equirectangular photo (width = 2 x height)")


def sky_mask(rgb):
    """Sky pixels (bool, H x W) of an equirectangular photo with a reasonably clear sky, for a photo without a
    transparent sky: blue enough (also the darker zenith) or bright and grey (haze, glare near the Sun), and connected
    to the top rows (so blue roofs, cars or water below the skyline do not count); the top 3 deg (stitched zenith)
    count as sky, holes inside the sky (clouds) are filled. Blue gaps in foliage stay ground (branches block too).
    Checked on two real panoramas (a London park, a garden): the line follows tree crowns and roof edges."""
    from scipy import ndimage
    f = np.asarray(rgb, float)[..., :3]
    r, g, b = f[..., 0], f[..., 1], f[..., 2]
    v, mn = f.max(axis=2), f.min(axis=2)
    sat = (v - mn) / np.maximum(v, 1.0)
    cand = ((b > r + 8) & (b >= g - 5) & (v > 70)) | ((v > 200) & (sat < 0.18))
    p = 8                                                       # the photo wraps around: pad with its other edge, so
    cand = np.pad(cand, ((p, p), (p, p)), mode="wrap")          # the smoothing does not eat into the left/right edges
    cand[:p], cand[-p:] = cand[p:p + 1], cand[-p - 1:-p]        # (top/bottom: repeated, not wrapped)
    cand = ndimage.binary_opening(cand, iterations=1)
    lab, _ = ndimage.label(cand)
    top = set(np.unique(lab[p: p + max(2, f.shape[0] // 40)]).tolist()) - {0}
    sky = ndimage.binary_closing(np.isin(lab, list(top)), iterations=2)[p:-p, p:-p]
    sky[: max(1, f.shape[0] // 60)] = True
    return ndimage.binary_fill_holes(sky)


def ground(im):
    """(ground mask, how): from the alpha channel when the photo has a transparent sky ('transparent sky'), else
    from sky_mask ('sky detection'); (None, '') when neither gives a usable sky (less than 2 % of the photo)."""
    if "A" in im.getbands():
        a = np.asarray(im.getchannel("A")) >= OPAQUE
        if not a.all():
            return a, "transparent sky"
    sky = sky_mask(np.asarray(im.convert("RGB")))
    if sky[sky.shape[0] // 60:].mean() < 0.02:                  # (almost) no sky found below the zenith rows
        return None, ""
    return ~sky, "sky detection"


def profile(im):
    """Horizon altitude (deg) per STEP_DEG column from the left edge, from the ground mask (ground(): transparent
    sky, else sky detection): per column the first row below which ground continues for ~0.3 deg (a wire or bird in
    the sky does not count); the altitude of the highest such column in each STEP_DEG bin; below 0 deg kept (valley
    views). None without a usable sky."""
    a, _ = ground(im)
    if a is None:
        return None
    h, w = a.shape
    k = max(3, int(round(h / 600)))                            # ~0.3 deg of ground
    run = np.ones_like(a)
    for i in range(k):
        run[:h - i] &= a[i:]
        run[h - i:] = False
    first = np.where(run.any(0), run.argmax(0), h - 1)        # first row with k ground rows below it
    alt = 90.0 - 180.0 * first / h
    n = int(round(360 / STEP_DEG))
    edges = np.linspace(0, w, n + 1).astype(int)
    return np.array([alt[edges[i]:max(edges[i + 1], edges[i] + 1)].max() for i in range(n)])


def thumbnail(im, width=int(360 / STEP_DEG)):
    """The photo at STEP_DEG per pixel, RGB, transparent sky filled with SKY_FILL; JPEG bytes."""
    from PIL import Image
    im = im.convert("RGBA")
    bg = Image.new("RGBA", im.size, SKY_FILL + (255,))
    rgb = Image.alpha_composite(bg, im).convert("RGB").resize((width, width // 2), Image.LANCZOS)
    out = io.BytesIO()
    rgb.save(out, "JPEG", quality=85)
    return out.getvalue()


def slug(name):
    return re.sub(r"[^A-Za-z0-9_-]+", "_", str(name)).strip("_") or "site"


def photo_time(src):
    """When the photo was taken, from its EXIF data (read before the photo is shrunk: the saved copy has none):
    dict(utc, local, how) with utc an ISO time ('...Z') when known, local the camera's local time
    'YYYY-MM-DD HH:MM:SS' when only that is known; how: 'GPS time (UTC)', 'camera time with its time-zone offset' or
    'camera time (its time zone unknown: taken as the site's)'. None without a time."""
    import datetime as dt
    from PIL import Image
    try:
        im = Image.open(io.BytesIO(src) if isinstance(src, (bytes, bytearray)) else src)
        exif = im.getexif()
    except Exception:
        return None
    gps = exif.get_ifd(0x8825) if exif else {}
    try:                                                          # GPSDateStamp (29) 'YYYY:MM:DD', GPSTimeStamp (7)
        y, m, d = (int(x) for x in str(gps[29]).split(":"))
        h, mi, s = (float(x) for x in gps[7])
        t = dt.datetime(y, m, d, tzinfo=dt.timezone.utc) + dt.timedelta(hours=h, minutes=mi, seconds=s)
        return dict(utc=t.strftime("%Y-%m-%dT%H:%M:%S") + "Z", local=None, how="GPS time (UTC)")
    except (KeyError, ValueError, TypeError):
        pass
    sub_ifd = exif.get_ifd(0x8769) if exif else {}
    raw = sub_ifd.get(36867) or sub_ifd.get(36868) or (exif.get(306) if exif else None)   # DateTimeOriginal, ..., DateTime
    if not raw:
        return None
    try:
        t = dt.datetime.strptime(str(raw).strip()[:19], "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None
    frac = str(sub_ifd.get(37521) or "").strip()                 # SubSecTimeOriginal
    if frac.isdigit():
        t += dt.timedelta(seconds=float("0." + frac))
    off = str(sub_ifd.get(36881) or "").strip()                  # OffsetTimeOriginal '+02:00'
    m = re.fullmatch(r"([+-])(\d\d):(\d\d)", off)
    if m:
        tz = dt.timezone((1 if m[1] == "+" else -1) * dt.timedelta(hours=int(m[2]), minutes=int(m[3])))
        u = t.replace(tzinfo=tz).astimezone(dt.timezone.utc)
        return dict(utc=u.strftime("%Y-%m-%dT%H:%M:%S") + "Z", local=None, how="camera time with its time-zone offset")
    return dict(utc=None, local=t.strftime("%Y-%m-%d %H:%M:%S"), how="camera time (its time zone unknown: taken as the site's)")


def photo_location(src):
    """Where the photo was taken, from its EXIF GPS data: dict(lat, lon, alt_m (or None)), or None (no or an empty
    GPS fix: GoPro exports have empty fields)."""
    from PIL import Image
    try:
        im = Image.open(io.BytesIO(src) if isinstance(src, (bytes, bytearray)) else src)
        g = im.getexif().get_ifd(0x8825)
    except Exception:
        return None
    def deg(v, ref):
        d, m, s = (float(x) for x in v)
        x = d + m / 60.0 + s / 3600.0
        return -x if str(ref).strip().upper() in ("S", "W") else x
    try:
        lat, lon = deg(g[2], g.get(1, "N")), deg(g[4], g.get(3, "E"))
    except (KeyError, ValueError, TypeError, ZeroDivisionError):
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 360) or (abs(lat) < 1e-9 and abs(lon) < 1e-9):
        return None
    alt = None
    try:
        ref = g.get(5, 0) or 0
        ref = ref[0] if isinstance(ref, (bytes, bytearray)) and ref else ref     # GPSAltitudeRef: a byte
        alt = float(g[6]) * (-1.0 if int(ref) == 1 else 1.0)
    except (KeyError, ValueError, TypeError, ZeroDivisionError):
        pass
    return dict(lat=round(lat, 6), lon=round(lon - 360.0 if lon > 180 else lon, 6), alt_m=alt)


def save(src, site_name, folder=FOLDER, source=""):
    """Thumbnail + profile of photo src (path or bytes) as folder/<site>_<YYYYmmdd-HHMMSS>.jpg / .json: a new file
    each time, so a photo loaded into the form never replaces the one a saved site uses (the site changes only when
    saved). Returns the .jpg path (relative to the data folder, as stored in sites.py) and the meta dict."""
    taken, where = photo_time(src), photo_location(src)          # (the saved thumbnail has no EXIF)
    im = _image(src)
    check_size(im)
    prof = profile(im)
    how = ground(im)[1] if prof is not None else ""
    os.makedirs(folder, exist_ok=True)
    base = os.path.join(folder, f"{slug(site_name)}_{time.strftime('%Y%m%d-%H%M%S')}")
    meta = dict(version=__version__, source=os.path.basename(source or ""), size=list(im.size), step_deg=STEP_DEG,
                created=time.strftime("%Y-%m-%d %H:%M"),
                profile=None if prof is None else [round(float(x), 2) for x in prof], profile_from=how, taken=taken, where=where)
    for path, data in ((base + ".jpg", thumbnail(im)), (base + ".json", json.dumps(meta).encode())):
        with open(path + ".tmp", "wb") as f:
            f.write(data)
        os.replace(path + ".tmp", path)
    return base + ".jpg", meta


def load_meta(jpg):
    try:
        with open(os.path.splitext(jpg)[0] + ".json") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def at_azimuth(prof, az_left):
    """The profile resampled to azimuths 0, STEP_DEG, ... (north first)."""
    prof = np.asarray(prof, float)
    n = len(prof)
    idx = np.round(((np.arange(n) * 360.0 / n - az_left) % 360.0) / (360.0 / n)).astype(int) % n
    return prof[idx]


def points(prof, az_left, tol_deg=1.0):
    """UserHorizon points (whole degrees, 0 first, 360 last, altitudes 0..90) from the profile: per whole degree the
    highest altitude (rounded up), then simplified (Douglas-Peucker, tol_deg) without cutting off a peak."""
    alt = at_azimuth(prof, az_left)
    per = int(round(1.0 / (360.0 / len(alt))))
    deg = np.array([alt[i * per:(i + 1) * per].max() for i in range(360)])
    deg = np.clip(np.ceil(deg), 0, 90)
    xs = np.arange(361)
    ys = np.append(deg, deg[0])
    keep = np.zeros(361, bool)
    keep[[0, 360]] = True
    stack = [(0, 360)]
    while stack:
        a, b = stack.pop()
        if b - a < 2:
            continue
        t = (xs[a + 1:b] - a) / (b - a)
        line = ys[a] + (ys[b] - ys[a]) * t
        err = ys[a + 1:b] - line
        i = int(np.argmax(np.abs(err)))
        if abs(err[i]) > tol_deg:
            m = a + 1 + i
            keep[m] = True
            stack += [(a, m), (m, b)]
    out = [(int(x), int(y)) for x, y in zip(xs[keep], ys[keep])]
    out[-1] = (360, out[0][1])
    return out


def fit_az_left(prof, pts, step=STEP_DEG):
    """The azimuth at the photo's left edge that best lays its profile over the horizon points pts: the smallest
    scatter of the altitude differences around their median (so a constant offset, from points rounded to whole
    degrees or a camera above the ground, does not pull it sideways); only where the horizon is above 2 deg in
    either, so flat parts do not decide. Returns (az_left, median absolute difference deg)."""
    from pysyzygos import horizon
    n = len(prof)
    az = np.arange(n) * 360.0 / n
    h = np.array([horizon.altitude(pts, a) for a in az])
    best = (0.0, np.inf, np.inf)
    for az0 in np.arange(0.0, 360.0, step):
        p = at_azimuth(prof, az0)
        m = (p > 2) | (h > 2)
        if m.sum() < n // 20:
            continue
        diff = p[m] - h[m]
        spread = float(np.median(np.abs(diff - np.median(diff))))
        if spread < best[2]:
            best = (float(az0), float(np.median(np.abs(diff))), spread)
    return best[:2]


def sun_altaz(lat, lon, utc):
    """(azimuth from north through east, altitude) of the Sun's centre in degrees at a site (geodetic lat, east lon)
    and time (aware datetime): NOAA's solar position formulas (accuracy ~0.01 deg; with refraction), for lining up a
    photo by the Sun in it. Standard library only."""
    from datetime import timezone
    t = utc.astimezone(timezone.utc)
    jd = t.timestamp() / 86400.0 + 2440587.5
    T = (jd - 2451545.0) / 36525.0
    L0 = (280.46646 + T * (36000.76983 + 0.0003032 * T)) % 360.0
    M = 357.52911 + T * (35999.05029 - 0.0001537 * T)
    e = 0.016708634 - T * (0.000042037 + 0.0000001267 * T)
    Mr = math.radians(M)
    C = (math.sin(Mr) * (1.914602 - T * (0.004817 + 0.000014 * T)) + math.sin(2 * Mr) * (0.019993 - 0.000101 * T)
         + math.sin(3 * Mr) * 0.000289)
    om = 125.04 - 1934.136 * T
    lam = math.radians(L0 + C - 0.00569 - 0.00478 * math.sin(math.radians(om)))
    eps0 = 23 + (26 + (21.448 - T * (46.815 + T * (0.00059 - T * 0.001813))) / 60) / 60
    eps = math.radians(eps0 + 0.00256 * math.cos(math.radians(om)))
    dec = math.asin(math.sin(eps) * math.sin(lam))
    y = math.tan(eps / 2) ** 2
    L0r = math.radians(L0)
    eot = 4 * math.degrees(y * math.sin(2 * L0r) - 2 * e * math.sin(Mr) + 4 * e * y * math.sin(Mr) * math.cos(2 * L0r)
                           - 0.5 * y * y * math.sin(4 * L0r) - 1.25 * e * e * math.sin(2 * Mr))      # minutes
    minutes = t.hour * 60 + t.minute + t.second / 60 + t.microsecond / 6e7
    ha = math.radians(((minutes + eot + 4 * lon) / 4 - 180 + 180) % 360 - 180)
    la = math.radians(lat)
    alt = math.asin(math.sin(la) * math.sin(dec) + math.cos(la) * math.cos(dec) * math.cos(ha))
    az = math.degrees(math.atan2(math.sin(ha), math.cos(ha) * math.sin(la) - math.tan(dec) * math.cos(la))) + 180
    h = math.degrees(alt)
    if h > -0.575:                                              # refraction (NOAA)
        te = math.tan(math.radians(h))
        r = (58.1 / te - 0.07 / te ** 3 + 0.000086 / te ** 5) if h > 5 else \
            (1735 + h * (-518.2 + h * (103.4 + h * (-12.79 + h * 0.711)))) if h > -0.575 else 0
        h += r / 3600
    return az % 360.0, h


def sun_in_photo(jpg, min_px=30):
    """(degrees from the photo's left edge, altitude) of the Sun's disk in the photo: the centre of the largest
    saturated white area above the photo's horizon (min_px pixels at least), or None. With sun_altaz at the photo's
    time this gives the azimuth at the left edge (Sun's azimuth minus the first value); the altitude difference shows
    how level the photo is (glare can shift the centre a little: ~1 deg seen)."""
    from scipy import ndimage
    from PIL import Image
    im = np.asarray(Image.open(jpg).convert("RGB")).astype(float)
    h, w, _ = im.shape
    bright = im.min(axis=2) > 250
    bright[h // 2 + h // 18:] = False                           # not below 10 deg under the photo's horizon
    lab, n = ndimage.label(bright)
    if not n:
        return None
    sizes = ndimage.sum(bright, lab, range(1, n + 1))
    k = int(np.argmax(sizes)) + 1
    if sizes[k - 1] < min_px:
        return None
    cy, cx = ndimage.center_of_mass(bright, lab, k)
    return float(cx / w * 360.0), float(90.0 - cy / h * 180.0)


def svg(jpg, az_left, pts=None, margin=None, star=None, alt_range=(-10, 70), width=900, label="", sun=None):
    """The photo with north at the left (azimuth 0..360, ticks every 5 and 10 deg), altitudes alt_range, the horizon
    line pts (white), the margin above it (dashed red), star (az, alt) as a red ring with label, and sun (az, alt) as
    a yellow disk (to line the photo up by the Sun in it). The photo embedded as a data URI."""
    lo, hi = alt_range
    s = width / 360.0                                          # px per degree, both ways
    height = (hi - lo) * s
    with open(jpg, "rb") as f:
        uri = "data:image/jpeg;base64," + base64.b64encode(f.read()).decode()
    y = lambda alt: (hi - alt) * s
    x0 = (az_left % 360.0) * s
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
           f'viewBox="0 0 {width} {height:.1f}" width="{width}" height="{height:.0f}">',
           f'<clipPath id="pc"><rect width="{width}" height="{height:.1f}"/></clipPath><g clip-path="url(#pc)">']
    for dx in (x0 - width, x0):
        out.append(f'<image x="{dx:.1f}" y="{-(90 - hi) * s:.1f}" width="{width}" height="{width / 2:.1f}" '
                   f'preserveAspectRatio="none" href="{uri}" xlink:href="{uri}"/>')
    for a in range(int(math.ceil(lo / 10)) * 10, hi + 1, 10):
        out.append(f'<line x1="0" x2="{width}" y1="{y(a):.1f}" y2="{y(a):.1f}" stroke="#fff" stroke-opacity="'
                   f'{0.6 if a == 0 else 0.25}" stroke-width="{1 if a == 0 else 0.6}"/>'
                   f'<text x="3" y="{y(a) - 2:.1f}" font-size="10" fill="#fff" fill-opacity="0.8">{a}°</text>')
    for a, lab in ((0, "N"), (45, "NE"), (90, "E"), (135, "SE"), (180, "S"), (225, "SW"), (270, "W"), (315, "NW"),
                   (360, "N")):
        out.append(f'<line x1="{a * s:.1f}" x2="{a * s:.1f}" y1="0" y2="{height:.1f}" stroke="#fff" '
                   f'stroke-opacity="0.25" stroke-width="0.6"/><text x="{min(max(a * s, 8), width - 8):.1f}" y="12" '
                   f'font-size="11" font-weight="bold" fill="#fff" text-anchor="middle">{lab}</text>')
    for a in range(5, 360, 5):                                   # azimuth ticks: 5 deg short, 10 deg longer + number
        tick = 7 if a % 10 == 0 else 4
        out.append(f'<line x1="{a * s:.1f}" x2="{a * s:.1f}" y1="0" y2="{tick}" stroke="#fff" stroke-width="0.8"/>'
                   f'<line x1="{a * s:.1f}" x2="{a * s:.1f}" y1="{height - tick:.1f}" y2="{height:.1f}" stroke="#fff" '
                   f'stroke-width="0.8"/>')
        if a % 10 == 0 and a % 45:
            out.append(f'<text x="{a * s:.1f}" y="{height - 9:.1f}" font-size="9" fill="#fff" text-anchor="middle" '
                       f'stroke="#000" stroke-width="2" stroke-opacity="0.5" paint-order="stroke">{a}</text>')
    if sun is not None and sun[0] is not None and sun[1] is not None:
        ux, uy = (sun[0] % 360.0) * s, y(sun[1])
        out.append(f'<circle cx="{ux:.1f}" cy="{uy:.1f}" r="9" fill="none" stroke="#facc15" stroke-width="2.5"/>'
                   f'<circle cx="{ux:.1f}" cy="{uy:.1f}" r="2.5" fill="#facc15"/>'
                   f'<text x="{ux:.1f}" y="{uy - 13:.1f}" font-size="11" font-weight="bold" fill="#facc15" '
                   f'text-anchor="middle" stroke="#000" stroke-width="3" paint-order="stroke">Sun '
                   f'{sun[0]:.1f}°</text>')
    if pts:
        line = " ".join(f"{a * s:.1f},{y(h):.1f}" for a, h in pts)
        out.append(f'<polyline points="{line}" fill="none" stroke="#fff" stroke-width="1.6"/>')
        if margin:
            line = " ".join(f"{a * s:.1f},{y(min(h + margin, 90)):.1f}" for a, h in pts)
            out.append(f'<polyline points="{line}" fill="none" stroke="#f87171" stroke-width="1" '
                       f'stroke-dasharray="5,4"/>')
    if star is not None and star[0] is not None and star[1] is not None:
        sx, sy = (star[0] % 360.0) * s, y(star[1])
        out.append(f'<circle cx="{sx:.1f}" cy="{sy:.1f}" r="7" fill="none" stroke="#ef4444" stroke-width="2.5"/>'
                   f'<circle cx="{sx:.1f}" cy="{sy:.1f}" r="1.8" fill="#ef4444"/>')
        if label:
            anchor = "end" if sx > width * 0.8 else "start"
            dx = -10 if anchor == "end" else 10
            out.append(f'<text x="{sx + dx:.1f}" y="{sy - 8:.1f}" font-size="12" font-weight="bold" fill="#fff" '
                       f'stroke="#000" stroke-width="3" paint-order="stroke" text-anchor="{anchor}">{label}</text>')
    out.append("</g></svg>")
    return "".join(out)
