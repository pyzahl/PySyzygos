"""horizon.py - a site's own horizon (trees, buildings, hills): OccultWatcher's [User Horizon] format, the horizon height
at an azimuth, and whether a star is behind it or near it.

Format (OccultWatcher's UserHorizon.txt, so the same file serves both programs):

    Name = <station name>
    0, 30        # azimuth, altitude in whole degrees; one point per line
    35, 15
    ...
    360, 30

The first point is at azimuth 0, the last at 360; azimuths rise; at most two points share an azimuth (a vertical
step). Lines starting with # and empty lines are ignored. Several stations can be in one file.

Like OccultWatcher, PySyzygos uses the horizon to WARN: a star behind the horizon line is marked 'behind', one closer
to it than the site's margin (in any direction on the sky) 'near'. Optionally (site key horizon_filter) events behind
it are left out. Standard library only.
"""
from pysyzygos.version import __version__
import math, re


class HorizonError(ValueError):
    pass


def parse(text):
    """{station name: [(az, alt), ...]} from a UserHorizon.txt text. Raises HorizonError with the line number when a
    station's points break the format's rules."""
    out, name, pts, start = {}, None, [], 0
    text = text.lstrip("\ufeff")                                 # byte-order mark (Windows editors, OccultWatcher)
    for k, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = re.fullmatch(r"name\s*=\s*(.+)", line, re.I)
        if m:
            if name is not None:
                out[name] = check(pts, name, start)
            name, pts, start = m[1].strip(), [], k
            continue
        m = re.fullmatch(r"(-?\d+)\s*,\s*(-?\d+)", line)
        if not m or name is None:
            raise HorizonError(f"line {k}: '{line}' is not 'Name = ...' or 'azimuth, altitude' (whole degrees)")
        pts.append((int(m[1]), int(m[2])))
    if name is not None:
        out[name] = check(pts, name, start)
    if not out:
        raise HorizonError("no 'Name = ...' station in the file")
    return out


def check(pts, name="", line=0):
    """The points if they follow the rules (0 first, 360 last, rising azimuths, at most two per azimuth, altitudes
    0..90), else HorizonError."""
    where = f"station '{name}' (from line {line})" if name else "the horizon"
    if len(pts) < 2 or pts[0][0] != 0 or pts[-1][0] != 360:
        raise HorizonError(f"{where}: the first point must be at azimuth 0 and the last at 360")
    for (a0, _), (a1, _) in zip(pts, pts[1:]):
        if a1 < a0:
            raise HorizonError(f"{where}: azimuths must rise ({a0} then {a1})")
    for i in range(len(pts) - 2):
        if pts[i][0] == pts[i + 1][0] == pts[i + 2][0]:
            raise HorizonError(f"{where}: more than two points at azimuth {pts[i][0]}")
    for a, h in pts:
        if not 0 <= h <= 90:
            raise HorizonError(f"{where}: altitude {h} at azimuth {a} is outside 0..90")
    return [tuple(p) for p in pts]


def to_text(name, pts):
    """The station in the file format (for saving or for OccultWatcher)."""
    return "Name = " + name + "\n" + "\n".join(f"{int(a)}, {int(h)}" for a, h in pts) + "\n"


def altitude(pts, az):
    """Horizon altitude (deg) at azimuth az: straight lines between the points; at a vertical step the higher side."""
    az = float(az) % 360.0
    best = None
    for (a0, h0), (a1, h1) in zip(pts, pts[1:]):
        if a0 <= az <= a1:
            h = max(h0, h1) if a1 == a0 else h0 + (h1 - h0) * (az - a0) / (a1 - a0)
            best = h if best is None else max(best, h)
    return float(best if best is not None else 0.0)


def _sep(az1, alt1, az2, alt2):
    a1, h1, a2, h2 = (math.radians(x) for x in (az1, alt1, az2, alt2))
    c = math.sin(h1) * math.sin(h2) + math.cos(h1) * math.cos(h2) * math.cos(a1 - a2)
    return math.degrees(math.acos(max(-1.0, min(1.0, c))))


def assess(pts, star_alt, star_az, margin_deg=15.0):
    """(flag, horizon altitude at the star's azimuth, angular distance to the horizon line in deg): flag 'behind'
    (below the line), 'near' (above it, but closer than margin_deg in any direction) or ''. Without a horizon
    (pts empty): ('', None, None)."""
    if not pts or star_alt is None or star_az is None:
        return "", None, None
    h = altitude(pts, star_az)
    if star_alt < h:
        return "behind", h, 0.0
    sep = star_alt - h
    for (a0, h0), (a1, h1) in zip(pts, pts[1:]):                 # the line, sampled every half degree
        n = max(1, int(math.ceil(max(abs(a1 - a0), abs(h1 - h0)) / 0.5)))
        for i in range(n + 1):
            t = i / n
            sep = min(sep, _sep(star_az, star_alt, a0 + (a1 - a0) * t, h0 + (h1 - h0) * t))
    return ("near" if sep < margin_deg else ""), h, sep


def svg(pts, width=360, height=90, star=None):
    """A small profile of the horizon (azimuth 0..360 left to right, altitude 0..90 up), filled; star: (az, alt)."""
    sx, sy = width / 360.0, height / 90.0
    poly = " ".join(f"{a * sx:.1f},{height - h * sy:.1f}" for a, h in pts)
    s = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}">',
         f'<rect width="{width}" height="{height}" fill="#e0f2fe"/>',
         f'<polygon points="0,{height} {poly} {width},{height}" fill="#6b7280" fill-opacity="0.75"/>']
    for a, lab in ((0, "N"), (90, "E"), (180, "S"), (270, "W"), (360, "N")):
        x = a * sx
        s.append(f'<line x1="{x:.1f}" y1="0" x2="{x:.1f}" y2="{height}" stroke="#94a3b8" stroke-width="0.5"/>'
                 f'<text x="{min(max(x, 6), width - 6):.1f}" y="10" font-size="9" text-anchor="middle" '
                 f'fill="#334155">{lab}</text>')
    if star:
        s.append(f'<circle cx="{star[0] * sx:.1f}" cy="{height - star[1] * sy:.1f}" r="3.5" fill="#dc2626"/>')
    s.append("</svg>")
    return "".join(s)
