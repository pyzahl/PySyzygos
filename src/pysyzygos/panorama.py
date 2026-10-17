"""panorama.py - a site's 360-degree photo (equirectangular, 2:1, as a GoPro MAX / Insta360 / phone 'photo sphere'
saves it) as a picture of its horizon: the horizon line read from a photo whose sky was made transparent, the
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


def profile(im):
    """Horizon altitude (deg) per STEP_DEG column from the left edge, from the alpha channel (transparent = sky): per
    column the first row below which ground continues for ~0.3 deg (a wire or bird in the sky does not count); the
    altitude of the highest such column in each STEP_DEG bin; below 0 deg kept (valley views). None without alpha."""
    if "A" not in im.getbands():
        return None
    a = np.asarray(im.getchannel("A")) >= OPAQUE
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


def save(src, site_name, folder=FOLDER, source=""):
    """Thumbnail + profile of photo src (path or bytes) as folder/<site>.jpg / .json. Returns the .jpg path (relative
    to the data folder, as stored in sites.py) and the meta dict."""
    im = _image(src)
    check_size(im)
    prof = profile(im)
    os.makedirs(folder, exist_ok=True)
    base = os.path.join(folder, slug(site_name))
    meta = dict(version=__version__, source=os.path.basename(source or ""), size=list(im.size), step_deg=STEP_DEG,
                created=time.strftime("%Y-%m-%d %H:%M"),
                profile=None if prof is None else [round(float(x), 2) for x in prof])
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


def svg(jpg, az_left, pts=None, margin=None, star=None, alt_range=(-10, 70), width=900, label=""):
    """The photo with north at the left (azimuth 0..360), altitudes alt_range, the horizon line pts (white), the margin
    above it (dashed red) and star (az, alt) as a red ring with label. The photo embedded as a data URI."""
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
