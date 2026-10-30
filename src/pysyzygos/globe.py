"""globe.py - whole-Earth view of an event as SVG: the whole Earth as seen from the star at the event time, with the
shadow path (centre line, shadow limits, 1- and 3-sigma limits, minute marks), the shadow axis off the Earth, day
side and terminator, the observer's site, a header with the event parameters (star, durations,
time per km and per mas, drop, Sun and Moon, 1-sigma error, asteroid size, parallax and motion) and a 2 deg star
chart with the asteroid's motion in 24 h steps. On an A4 page (default, globe_page) two more panels below: the
geometry at true scale (Earth, asteroid, Sun, Jupiter, Saturn, the star's direction; AU) and the light paths with the
light deflection exaggerated (the star's ray bent by the Sun and planets, the asteroid on it, where it would stand
without deflection, and the shift that moves the shadow on the Earth).

    globe_data(spice, ...)   collects the geometry with SPICE (passed in; called by pysyzygos.write_globe)
    render_svg(d)            pure drawing from that dict (testable without SPICE)

Coastlines and borders: data/ne_110m_earth.json (Natural Earth 1:110m, public domain).
"""
from pysyzygos.version import __version__
import json, math, os
import numpy as np

W, H = 1024, 800                    # canvas of the whole-Earth view, px (the square page)
PAGES = {"A4": 1448, "square": H}   # page height for the width W: A4 portrait (210 x 297 mm), or the view alone
PAGE_MM = {"A4": (210, 297)}
CX, CY, RPX = 512, 470, 300         # Earth disk centre and radius on the canvas
from pysyzygos.earth import A_KM, C_KM   # WGS84 ellipsoid (as the shadow paths)
AU_KM = 1.495978707e8
RAD2MAS = math.degrees(1.0) * 3.6e6
LINES = (("center", "#111827", 2.4, None), ("edge_plus", "#dc2626", 1.4, None), ("edge_minus", "#dc2626", 1.4, None),
         ("sigma1_plus", "#7c3aed", 1.0, "2 3"), ("sigma1_minus", "#7c3aed", 1.0, "2 3"),
         ("sigma_plus", "#d97706", 1.0, "6 4"), ("sigma_minus", "#d97706", 1.0, "6 4"),
         ("satellite_plus", "#0891b2", 1.0, "1 4"), ("satellite_minus", "#0891b2", 1.0, "1 4"))   # known satellite
# styles: "color" (blue sea, land, dark night side, globe) or "lines" (black on white, printer friendly)
STYLE = {
    "color": dict(sea="#1d4e89", land="#7b8f55", land_edge="#56663a", night=0.5, day=None, grid="#ffffff",
                  grid_op=0.22, coast=None, border="#e5e7eb", path={"center": "#fde047", "edge": "#f87171",
                  "sigma1": "#c4b5fd", "sigma": "#fdba74", "satellite": "#5eead4"}, mark="#fde047", label="#ffffff", halo="#0f172a",
                  site="#22d3ee", legend="yellow: centre line (dots: minutes UT) \u00b7 red: shadow limits \u00b7 "
                  "violet dotted: 1-sigma \u00b7 orange dashed: 3-sigma", legend2="dashed: shadow axis off the Earth "
                  "\u00b7 dark: night side \u00b7 cyan: site"),
    "lines": dict(sea="#f8fafc", land=None, land_edge=None, night=None, day="#fde68a", grid="#94a3b8", grid_op=1.0,
                  coast="#1f2937", border="#6b7280", path=None, mark="#111", label="#111", halo=None, site="#0369a1",
                  legend="black: centre line (dots: minutes UT) \u00b7 red: shadow limits \u00b7 violet dotted: "
                  "1-sigma \u00b7 orange dashed: 3-sigma", legend2="dashed: shadow axis off the Earth \u00b7 "
                  "yellow: day side \u00b7 blue: site"),
}


def _land_path(proj, lon, lat):
    """SVG path data of a land polygon for drawing inside the disk clip. Every vertex is mapped with an extended
    orthographic projection: angular distance c from the point under the star, r = sin(c) on the visible side and
    2 - sin(c) beyond the limb (continuous, orientation-preserving, the far side lies outside the disk and is clipped).
    A polygon containing the far-side point (the antipode) comes out inside out; it is detected by comparing its
    orientation on the map with its orientation in lon/lat, and drawn as the outside of its outline (even-odd with an
    enclosing square). None if nothing of it can be visible."""
    P = geodetic_to_itrf(lon, lat) @ proj.R.T
    P = P / np.linalg.norm(P, axis=1)[:, None]
    phi0 = np.arctan2(P @ proj.y, P @ proj.x)
    dphi = np.abs((np.diff(np.append(phi0, phi0[0])) + np.pi) % (2 * np.pi) - np.pi)
    if (dphi > math.radians(10)).any():                               # long steps around the centre (near the
        pts = []                                                      # antipode): subdivide along the great circle
        for k in range(len(P)):
            a_, b_ = P[k], P[(k + 1) % len(P)]
            pts.append(a_)
            m = int(dphi[k] / math.radians(5))
            om = math.acos(max(-1.0, min(1.0, float(a_ @ b_))))
            for i in range(1, m + 1 if om > 1e-9 else 1):
                t = i / (m + 1)
                pts.append((math.sin((1 - t) * om) * a_ + math.sin(t * om) * b_) / math.sin(om))
        P = np.array(pts)
    X, Y, Z = P @ proj.x, P @ proj.y, P @ proj.z
    c = np.arccos(np.clip(Z, -1.0, 1.0))
    phi = np.arctan2(Y, X)
    r = np.where(Z >= 0, np.sin(c), 2.0 - np.sin(c))
    mx, my = r * np.cos(phi), r * np.sin(phi)                         # unit-disk coordinates, y up
    area = lambda x, y: float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))
    lo, la = np.asarray(lon, float), np.asarray(lat, float)
    inside_out = (area(mx, my) > 0) != (area(lo, la) > 0)             # contains the antipode
    if not inside_out and not (Z > 0).any():
        return None
    d = "M" + " L".join(f"{CX + a * RPX:.1f},{CY - b * RPX:.1f}" for a, b in zip(mx, my)) + " Z"
    if inside_out:
        q = 2.2 * RPX
        d = (f"M{CX - q:.0f},{CY - q:.0f} L{CX + q:.0f},{CY - q:.0f} L{CX + q:.0f},{CY + q:.0f} "
             f"L{CX - q:.0f},{CY + q:.0f} Z " + d)
    return d

_EARTH = None


def earth_lines():
    """{'coast': [[lon, lat, ...], ...], 'borders': [...]} from data/ne_110m_earth.json (cached)."""
    global _EARTH
    if _EARTH is None:
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "ne_110m_earth.json")
        try:
            with open(p, encoding="utf-8") as f:
                _EARTH = json.load(f)
        except (OSError, ValueError):
            _EARTH = {"coast": [], "borders": []}
    return _EARTH


def geodetic_to_itrf(lon_deg, lat_deg):
    """Points on the ellipsoid surface (height 0), km; arrays of lon, lat in degrees."""
    lon, lat = np.radians(np.asarray(lon_deg, float)), np.radians(np.asarray(lat_deg, float))
    e2 = 1 - (C_KM / A_KM) ** 2
    n = A_KM / np.sqrt(1 - e2 * np.sin(lat) ** 2)
    return np.stack([n * np.cos(lat) * np.cos(lon), n * np.cos(lat) * np.sin(lon), n * (1 - e2) * np.sin(lat)], -1)


def _esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ------------------------------------------------------------------------------------------- drawing (pure)
class _Proj:
    """ITRF km -> canvas px for the Earth at the event time, seen from the star (x east right, y north up)."""
    def __init__(self, R, basis):
        self.R, (self.x, self.y, self.z) = np.asarray(R, float), (np.asarray(b, float) for b in basis)

    def __call__(self, itrf):
        p = np.atleast_2d(itrf) @ self.R.T                              # J2000
        X, Y, Z = p @ self.x, p @ self.y, p @ self.z
        return CX + X / A_KM * RPX, CY - Y / A_KM * RPX, Z > 0

    def plane(self, X, Y):                                              # fundamental-plane km -> px
        return CX + np.asarray(X) / A_KM * RPX, CY - np.asarray(Y) / A_KM * RPX


def _polylines(px, py, vis, style):
    """SVG polylines of the visible runs of a projected line."""
    out, run = [], []
    for x, y, v in zip(px, py, vis):
        if v:
            run.append(f"{x:.1f},{y:.1f}")
        elif run:
            if len(run) > 1:
                out.append(f'<polyline points="{" ".join(run)}" {style}/>')
            run = []
    if len(run) > 1:
        out.append(f'<polyline points="{" ".join(run)}" {style}/>')
    return out


def _day_side(R, basis, sun_dir_j2000, n=90):
    """Polygon (canvas px) of the visible day side: limb arc where the Sun is up, then the terminator arc."""
    x, y, z = basis
    s = np.asarray(sun_dir_j2000, float)
    p = np.cross(z, s)
    if np.linalg.norm(p) < 1e-9:
        return None
    p /= np.linalg.norm(p)
    pts = []
    for axis, keep in ((z, s), (s, z)):                                 # limb (n.z = 0), then terminator (n.s = 0)
        q = np.cross(axis, p)
        for t in np.linspace(0, math.pi, n):
            v = math.cos(t) * p + math.sin(t) * q
            if v @ keep < 0:
                v = math.cos(t) * p - math.sin(t) * q
            pts.append(v)
        p = -p
    P = np.array(pts) * A_KM
    X, Y = P @ x, P @ y
    return [f"{CX + a / A_KM * RPX:.1f},{CY - b / A_KM * RPX:.1f}" for a, b in zip(X, Y)]


def render_svg(d):
    """SVG text from globe_data()'s dict. d['page']: 'A4' (default: the view and the two geometry panels below,
    sized 210 x 297 mm for printing) or 'square' (the view alone)."""
    proj = _Proj(d["R"], d["basis"])
    page = d.get("page", "A4") if d.get("page", "A4") in PAGES else "A4"
    PH = PAGES[page] if d.get("system") or page == "square" else H
    size = (f'width="{PAGE_MM[page][0]}mm" height="{PAGE_MM[page][1]}mm"' if PH != H and page in PAGE_MM
            else f'width="{W}" height="{PH}"')
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {PH}" {size} '
         f'font-family="ui-monospace,Menlo,Consolas,monospace" font-size="11">',
         f'<rect width="{W}" height="{PH}" fill="#ffffff"/>']
    # header: title line and three columns
    o.append(f'<text x="8" y="18" font-size="15" font-weight="700" fill="#111">{_esc(d["title"])}</text>')
    for col, x in zip(d["columns"], (8, 395, 735)):
        for i, line in enumerate(col):
            o.append(f'<text x="{x}" y="{36 + 13 * i}" fill="#111">{_esc(line)}</text>')
    top = 48 + 13 * max(len(c) for c in d["columns"]) - 6               # header bottom line
    o.append(f'<line x1="0" y1="{top}" x2="{W}" y2="{top}" stroke="#111" stroke-width="1.2"/>')
    o.append(f'<clipPath id="plot"><rect x="0" y="{top + 1}" width="{W}" height="{H - top - 44}"/></clipPath>'
             f'<g clip-path="url(#plot)">')                            # globe and axis stay below the header
    st = STYLE.get(d.get("style", "color"), STYLE["color"])
    E = earth_lines()
    # globe: sea, land, night or day side, grid, coast, borders
    o.append(f'<circle cx="{CX}" cy="{CY}" r="{RPX}" fill="{st["sea"]}" stroke="#111" stroke-width="1.4"/>')
    if st["land"]:
        o.append(f'<clipPath id="disk"><circle cx="{CX}" cy="{CY}" r="{RPX}"/></clipPath><g clip-path="url(#disk)">')
        for ring in E.get("land", []):
            path = _land_path(proj, ring[0::2], ring[1::2])
            if path:
                o.append(f'<path d="{path}" fill="{st["land"]}" fill-rule="evenodd" stroke="{st["land_edge"]}" '
                         f'stroke-width="0.5"/>')
        o.append("</g>")
    if st["night"]:
        night = _day_side(proj.R, (proj.x, proj.y, proj.z), -np.asarray(d["sun_dir"], float))
        if night:
            o.append(f'<polygon points="{" ".join(night)}" fill="#000" fill-opacity="{st["night"]}"/>')
    if st["day"]:
        day = _day_side(proj.R, (proj.x, proj.y, proj.z), d["sun_dir"])
        if day:
            o.append(f'<polygon points="{" ".join(day)}" fill="{st["day"]}" fill-opacity="0.35" stroke="#b45309" '
                     f'stroke-width="0.8" stroke-dasharray="1 2"/>')
    grid = f'fill="none" stroke="{st["grid"]}" stroke-opacity="{st["grid_op"]}" stroke-width="0.6"'
    for lat in range(-60, 61, 30):
        lon = np.linspace(-180, 180, 181)
        o += _polylines(*proj(geodetic_to_itrf(lon, np.full_like(lon, lat))), grid)
    for lon0 in range(-180, 180, 30):
        lat = np.linspace(-90, 90, 91)
        o += _polylines(*proj(geodetic_to_itrf(np.full_like(lat, lon0), lat)), grid)
    for key, style in (("coast", f'fill="none" stroke="{st["coast"]}" stroke-width="0.9"' if st["coast"] else None),
                       ("borders", f'fill="none" stroke="{st["border"]}" stroke-opacity="0.7" stroke-width="0.6" '
                                   f'stroke-dasharray="1.5 2"')):
        if not style:
            continue
        for ln in E.get(key, []):
            o += _polylines(*proj(geodetic_to_itrf(ln[0::2], ln[1::2])), style)
    # shadow axis off the Earth (fundamental plane), with minute ticks
    ax = d.get("axis") or []
    if ax:
        X, Y = np.array([a[1] for a in ax]), np.array([a[2] for a in ax])
        sx, sy = proj.plane(X, Y)
        out = np.hypot(X, Y) > A_KM
        o += _polylines(sx, sy, out, 'fill="none" stroke="#111" stroke-width="1" stroke-dasharray="3 3"')
        for i, ((et, Xk, Yk), ok) in enumerate(zip(ax, out)):
            if ok and abs(et - round(et / 60) * 60) < 0.5:
                j = i + 1 if i + 1 < len(ax) else i - 1
                dx, dy = (ax[j][1] - Xk, ax[j][2] - Yk) if j > i else (Xk - ax[j][1], Yk - ax[j][2])
                n = math.hypot(dx, dy) or 1.0
                px, py = proj.plane(Xk, Yk)
                tx, ty = -dy / n * 5, -dx / n * 5                         # perpendicular on the canvas (y down)
                o.append(f'<line x1="{px - tx:.1f}" y1="{py - ty:.1f}" x2="{px + tx:.1f}" y2="{py + ty:.1f}" '
                         f'stroke="#111" stroke-width="1"/>')
                o.append(f'<text x="{px + 2 * tx + 3:.1f}" y="{py + 2 * ty + 4:.1f}" fill="#111" font-size="10">'
                         f'{_esc(d["minute_label"](et))}</text>')
    # shadow path on the Earth
    for name, col, wid, dash in LINES:
        if st["path"]:
            col = st["path"][name.split("_")[0]]
        pts = (d.get("paths") or {}).get(name) or []
        if len(pts) > 1:
            a = np.array([[p[1], p[2]] for p in pts], float)
            style = f'fill="none" stroke="{col}" stroke-width="{wid}"' + (f' stroke-dasharray="{dash}"' if dash else "")
            o += _polylines(*proj(geodetic_to_itrf(a[:, 0], a[:, 1])), style)
    centre = (d.get("paths") or {}).get("center") or []
    if len(centre) > 1:                                                 # minute marks on the ground track
        ets = np.array([p[0] for p in centre])
        for m in range(int(math.ceil(ets[0] / 60)), int(math.floor(ets[-1] / 60)) + 1):
            t = m * 60.0
            k = int(np.searchsorted(ets, t))
            if not 0 < k < len(ets):
                continue
            f = (t - ets[k - 1]) / (ets[k] - ets[k - 1])
            lon = centre[k - 1][1] + f * (((centre[k][1] - centre[k - 1][1] + 180) % 360) - 180)
            lat = centre[k - 1][2] + f * (centre[k][2] - centre[k - 1][2])
            px, py, vis = proj(geodetic_to_itrf([lon], [lat]))
            if vis[0]:
                halo = (f' stroke="{st["halo"]}" stroke-width="2.5" paint-order="stroke"' if st["halo"] else "")
                o.append(f'<circle cx="{px[0]:.1f}" cy="{py[0]:.1f}" r="2" fill="{st["mark"]}"/>'
                         f'<text x="{px[0] + 4:.1f}" y="{py[0] - 4:.1f}" fill="{st["label"]}" font-size="10"{halo}>'
                         f'{_esc(d["minute_label"](t))}</text>')
    # the observer's site
    if d.get("site"):
        lon, lat, name = d["site"]
        px, py, vis = proj(geodetic_to_itrf([lon], [lat]))
        if vis[0]:
            halo = (f' stroke="{st["halo"]}" stroke-width="2.5" paint-order="stroke"' if st["halo"] else "")
            o.append(f'<circle cx="{px[0]:.1f}" cy="{py[0]:.1f}" r="4" fill="none" stroke="{st["site"]}" stroke-width="2"/>'
                     f'<text x="{px[0] + 7:.1f}" y="{py[0] + 12:.1f}" fill="{st["site"]}" font-size="11"{halo}>{_esc(name)}</text>')
    o.append("</g>")
    # legend
    o.append(f'<text x="8" y="{H - 30}" fill="#374151" font-size="10">{st["legend"]}</text>')
    sat = "" if not (d.get("paths") or {}).get("satellite_plus") else \
        " \u00b7 " + ("teal" if st["path"] else "blue") + " dotted: satellite zone (known moon)"
    o.append(f'<text x="8" y="{H - 18}" fill="#374151" font-size="10">{st["legend2"]}{sat}</text>')
    o += _inset(d.get("inset"))
    if PH != H:
        o.append(f'<line x1="0" y1="{H}" x2="{W}" y2="{H}" stroke="#111" stroke-width="1.2"/>')
        ph = (PH - H - 34) / 2                                  # two panels, one above the other, full width
        o += _panel_true_scale(d["system"], 8, H + 8, W - 16, ph)
        o += _panel_light(d["system"], 8, H + 12 + ph, W - 16, ph)
    o.append(f'<text x="8" y="{PH - 5}" fill="#374151" font-size="10">{_esc(d["footer"])}</text>')
    o.append("</svg>")
    return "\n".join(o)


# ------------------------------------------------------------------------------------------- geometry panels (pure)
class _Box:
    """Data coordinates -> page px inside a plot area. equal: one scale for both axes, the ranges centred (true
    scale); else each axis fills the area."""
    def __init__(self, x0, y0, w, h, xr, yr, equal=True):
        self.x0, self.y0, self.w, self.h = x0, y0, w, h
        kx, ky = w / (xr[1] - xr[0]), h / (yr[1] - yr[0])
        self.kx = self.ky = min(kx, ky) if equal else None
        if not equal:
            self.kx, self.ky = kx, ky
        self.cx, self.cy = (xr[0] + xr[1]) / 2, (yr[0] + yr[1]) / 2

    def __call__(self, x, y):
        return self.x0 + self.w / 2 + (x - self.cx) * self.kx, self.y0 + self.h / 2 - (y - self.cy) * self.ky

    def inv_x(self, px):
        return self.cx + (px - self.x0 - self.w / 2) / self.kx

    def inv_y(self, py):
        return self.cy - (py - self.y0 - self.h / 2) / self.ky


class _Labels:
    """Labels placed next to points without overlapping each other or the marked points (a few candidate spots)."""
    CH = 0.6                                                    # character width / font size (monospace)

    def __init__(self, x0, y0, w, h):
        self.area, self.taken = (x0, y0, x0 + w, y0 + h), []

    def block(self, px, py, r):
        self.taken.append((px - r, py - r, px + r, py + r))

    def _free(self, b, pad=3):
        a = self.area
        if b[0] < a[0] or b[1] < a[1] or b[2] > a[2] or b[3] > a[3]:
            return False
        return all(b[2] + pad < t[0] or b[0] - pad > t[2] or b[3] + pad < t[1] or b[1] - pad > t[3] for t in self.taken)

    def place(self, px, py, lines, color, size=13, gap=8, prefer=("ne", "se", "e", "nw", "sw", "w", "n", "s")):
        tw, th = max(len(t) for t in lines) * self.CH * size, len(lines) * 1.2 * size

        def spots(g):
            sp = dict(ne=(px + g, py - g - th), se=(px + g, py + g), e=(px + g, py - th / 2),
                      nw=(px - g - tw, py - g - th), sw=(px - g - tw, py + g), w=(px - g - tw, py - th / 2),
                      n=(px - tw / 2, py - g - th), s=(px - tw / 2, py + g))
            return [sp[k] for k in prefer]
        lead = []
        for g in (gap, 2.5 * gap + 6, 4.5 * gap + 14):            # nearest free spot; farther out if all are taken
            hit = next(((x, y) for x, y in spots(g) if self._free((x, y, x + tw, y + th))), None)
            if hit:
                x, y = hit
                if g > gap:                                     # a leader line to a label moved away
                    cx_, cy_ = min(max(px, x), x + tw), min(max(py, y), y + th)
                    lead = [f'<line x1="{px:.1f}" y1="{py:.1f}" x2="{cx_:.1f}" y2="{cy_:.1f}" stroke="{color}" '
                            f'stroke-width="{LW["lead"]}" stroke-opacity="0.7"/>']
                break
        else:
            x, y = spots(gap)[0]
        self.taken.append((x, y, x + tw, y + th))
        return lead + [f'<text x="{x:.1f}" y="{y + (i + 0.85) * 1.2 * size:.1f}" fill="{color}" font-size="{size}">'
                       f'{_esc(t)}</text>' for i, t in enumerate(lines)]


PCOL = dict(Earth="#2563eb", Sun="#f59e0b", Jupiter="#b45309", Saturn="#a16207", target="#4b5563", star="#dc2626",
            grid="#e5e7eb", axis="#6b7280", text="#111827", note="#374151")
PSIZE = dict(Earth=6, Sun=12, Jupiter=8, Saturn=7, target=4.5)
FS = dict(title=14, sub=13, label=13, note=12, tick=12)          # panel font sizes (px on the 1024 px wide page)
LW = dict(ray=2.6, line=2.0, axis=1.2, grid=1.0, lead=1.2)      # line widths, px (1 px = 0.2 mm on A4)
DEFL_SHOWN_MAS = 0.001                                          # Jupiter, Saturn marked in the light panel from this
MARGIN_L, MARGIN_B, TITLE_H = 58, 38, 38                        # panel space for the y axis, x axis, titles


def _ticks(lo, hi, n=6):
    """Tick values between lo and hi at a human step: 1, 2, 2.5 or 5 x 10^k."""
    if not hi > lo:
        return [lo]
    raw = (hi - lo) / n
    e = 10 ** math.floor(math.log10(raw))
    step = next(m * e for m in (1, 2, 2.5, 5, 10) if m * e >= raw * (1 - 1e-9))
    return [round(k * step, 12) for k in range(int(math.ceil(lo / step - 1e-9)), int(math.floor(hi / step + 1e-9)) + 1)]


def _fmt(v):
    return f"{v:g}" if abs(v) >= 1e-3 or v == 0 else f"{v:.1e}"


def _frame(box, x0, y0, w, h, title, xlabel, ylabel):
    """Panel title, plot frame, grid and both axes with ticks (data units)."""
    o = []
    for i, t in enumerate(title):
        o.append(f'<text x="{x0 + w / 2:.1f}" y="{y0 + 14 + 17 * i:.1f}" text-anchor="middle" '
                 f'font-size="{FS["title"] if i == 0 else FS["sub"]}" font-weight="{700 if i == 0 else 400}" '
                 f'fill="{PCOL["text"]}">{_esc(t)}</text>')
    px0, py0, pw, ph = box.x0, box.y0, box.w, box.h
    for t in _ticks(box.inv_x(px0), box.inv_x(px0 + pw)):
        px, _ = box(t, 0)
        o.append(f'<line x1="{px:.1f}" y1="{py0:.1f}" x2="{px:.1f}" y2="{py0 + ph:.1f}" stroke="{PCOL["grid"]}" '
                 f'stroke-width="{LW["grid"]}"/><line x1="{px:.1f}" y1="{py0 + ph:.1f}" x2="{px:.1f}" '
                 f'y2="{py0 + ph + 5:.1f}" stroke="{PCOL["axis"]}" stroke-width="{LW["axis"]}"/>'
                 f'<text x="{px:.1f}" y="{py0 + ph + 18:.1f}" text-anchor="middle" font-size="{FS["tick"]}" '
                 f'fill="{PCOL["note"]}">{_fmt(t)}</text>')
    for t in _ticks(box.inv_y(py0 + ph), box.inv_y(py0), n=5):
        _, py = box(0, t)
        o.append(f'<line x1="{px0:.1f}" y1="{py:.1f}" x2="{px0 + pw:.1f}" y2="{py:.1f}" stroke="{PCOL["grid"]}" '
                 f'stroke-width="{LW["grid"]}"/><line x1="{px0 - 5:.1f}" y1="{py:.1f}" x2="{px0:.1f}" y2="{py:.1f}" '
                 f'stroke="{PCOL["axis"]}" stroke-width="{LW["axis"]}"/>'
                 f'<text x="{px0 - 8:.1f}" y="{py + 4:.1f}" text-anchor="end" font-size="{FS["tick"]}" '
                 f'fill="{PCOL["note"]}">{_fmt(t)}</text>')
    o.append(f'<rect x="{px0:.1f}" y="{py0:.1f}" width="{pw:.1f}" height="{ph:.1f}" fill="none" '
             f'stroke="{PCOL["axis"]}" stroke-width="{LW["axis"]}"/>')
    o.append(f'<text x="{px0 + pw / 2:.1f}" y="{py0 + ph + 34:.1f}" text-anchor="middle" font-size="{FS["note"]}" '
             f'fill="{PCOL["note"]}">{_esc(xlabel)}</text>')
    yc = py0 + ph / 2
    o.append(f'<text x="{x0 + 12:.1f}" y="{yc:.1f}" text-anchor="middle" font-size="{FS["note"]}" '
             f'fill="{PCOL["note"]}" transform="rotate(-90 {x0 + 12:.1f} {yc:.1f})">{_esc(ylabel)}</text>')
    return o


def _plot_area(x0, y0, w, h):
    return x0 + MARGIN_L, y0 + TITLE_H, w - MARGIN_L - 6, h - TITLE_H - MARGIN_B


def _arrow(x1, y1, x2, y2, col, lw):
    a = math.atan2(y2 - y1, x2 - x1)
    p = [(x2, y2), (x2 - 11 * math.cos(a) + 5 * math.sin(a), y2 - 11 * math.sin(a) - 5 * math.cos(a)),
         (x2 - 11 * math.cos(a) - 5 * math.sin(a), y2 - 11 * math.sin(a) + 5 * math.cos(a))]
    return [f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2 - 9 * math.cos(a):.1f}" y2="{y2 - 9 * math.sin(a):.1f}" '
            f'stroke="{col}" stroke-width="{lw}"/>',
            f'<polygon points="{" ".join(f"{u:.1f},{v:.1f}" for u, v in p)}" fill="{col}"/>']


def _panel_true_scale(sy, x0, y0, w, h):
    """The geometry at true scale (AU, equal on both axes), in the plane of the star's direction (x, to the right)
    and the Sun (y, up); Jupiter and Saturn projected (their distance from the plane noted). The rays are straight:
    the deflection (mas) is invisible at this scale."""
    pts = [(0.0, 0.0), (sy["x_target"] + 1.0, 0.0)] + [(b["x"], b["y"]) for b in sy["bodies"]]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    pad = 0.1 * max(max(xs) - min(xs), max(ys) - min(ys), 1.0)
    area = _plot_area(x0, y0, w, h)
    box = _Box(*area, (min(xs) - pad, max(xs) + pad), (min(ys) - pad, max(ys) + pad), equal=True)
    o = _frame(box, x0, y0, w, h, ["True scale, seen from above the plane of the star's direction and the Sun",
                                   "(Jupiter and Saturn projected; the light deflection, mas, is invisible here: "
                                   "rays straight)"],
               "AU along the star's direction (to the star: right)", "AU")
    L = _Labels(*area)
    ex, ey = box(0, 0)
    tx_, ty_ = box(sy["x_target"], 0.0)
    sx, sy_ = box(min(max(xs) + pad * 0.7, box.inv_x(area[0] + area[2] - 4)), 0)
    for b in sy["bodies"]:
        L.block(*box(b["x"], b["y"]), PSIZE[b["kind"]] + 3)
    L.block(ex, ey, PSIZE["Earth"] + 3)
    L.block(tx_, ty_, PSIZE["target"] + 3)
    L.taken.append((ex, sy_ - 4, sx, sy_ + 4))                  # keep labels off the star's line
    sun = next(b for b in sy["bodies"] if b["kind"] == "Sun")
    spx, spy = box(sun["x"], sun["y"])
    o.append(f'<line x1="{ex:.1f}" y1="{ey:.1f}" x2="{spx:.1f}" y2="{spy:.1f}" stroke="{PCOL["Sun"]}" '
             f'stroke-width="{LW["line"]}" stroke-dasharray="3 4"/>')
    o += _arrow(ex, ey, sx, sy_, PCOL["star"], LW["ray"])
    for b in sy["bodies"]:
        px, py = box(b["x"], b["y"])
        o.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="{PSIZE[b["kind"]]}" fill="{PCOL[b["kind"]]}"/>')
    o.append(f'<circle cx="{ex:.1f}" cy="{ey:.1f}" r="{PSIZE["Earth"]}" fill="{PCOL["Earth"]}"/>'
             f'<circle cx="{tx_:.1f}" cy="{ty_:.1f}" r="{PSIZE["target"]}" fill="{PCOL["target"]}"/>')
    o += L.place(ex, ey, ["Earth"], PCOL["Earth"], size=FS["label"], prefer=("sw", "s", "nw", "w", "se"))
    o += L.place(tx_, ty_, [sy["target_name"], f"{sy['x_target']:.2f} AU"], PCOL["target"], size=FS["label"],
                 prefer=("s", "se", "sw", "n"))
    o += L.place(sx, sy_, ["to the star", sy["star_name"]], PCOL["star"], size=FS["label"],
                 prefer=("e", "ne", "se", "nw", "sw", "n", "s"))
    for b in sy["bodies"]:
        px, py = box(b["x"], b["y"])
        lines = [b["name"], f"{b['dist']:.2f} AU"]
        if b["kind"] == "Sun":
            lines[1] += f", {sy['elong']:.0f}° from the star"
        elif abs(b["w"]) > 0.05:
            lines[1] += f", {b['w']:+.2f} AU off the plane"
        west = ("nw", "sw", "w", "ne", "se", "e", "n", "s")       # bodies behind the Earth: labels on their far side
        o += L.place(px, py, lines, PCOL[b["kind"]], size=FS["label"],
                     prefer=west if b["x"] < 0 else ("ne", "se", "e", "nw", "sw", "w", "n", "s"))
    note = [f"The Earth (radius 4e-5 AU) and {sy['target_name']} are points here;",
            f"{sy['target_name']} is {sy['x_target']:.2f} AU away on the star's line."]
    o += _corner_note(L, area, note)
    return o


def _corner_note(L, inner, lines, size=None, order=(0, 1, 2, 3)):
    """A note in the first free corner of the plot area: 0 top left, 1 top right, 2 bottom left, 3 bottom right (tried
    in this order)."""
    size = size or FS["note"]
    x0, y0, w, h = inner
    tw, th = max(len(t) for t in lines) * L.CH * size, len(lines) * 1.2 * size
    corners = ((x0 + 6, y0 + 4), (x0 + w - tw - 6, y0 + 4), (x0 + 6, y0 + h - th - 4), (x0 + w - tw - 6, y0 + h - th - 4))
    corners = [corners[k] for k in order]
    x, y = next(((x, y) for x, y in corners if L._free((x, y, x + tw, y + th))), corners[0])
    L.taken.append((x, y, x + tw, y + th))
    return [f'<text x="{x:.1f}" y="{y + (i + 0.85) * 1.2 * size:.1f}" fill="{PCOL["note"]}" font-size="{size}">'
            f'{_esc(t)}</text>' for i, t in enumerate(lines)]


def _panel_light(sy, x0, y0, w, h):
    """The light paths: x = distance along the star's direction (AU), y = sideways offset of the rays in mas as seen
    from the Earth at the target's distance (y_AU / x_target): the undeflected line (star, target and Earth in one
    line, the target there as a ghost), the star's ray that reaches the Earth (bent by the Sun and planets), the target
    on it (the star is hidden) at the shift that moves the shadow. The Sun is marked at the panel's edge (off scale)."""
    xs, ys = np.asarray(sy["curve_x"]), np.asarray(sy["curve_y"])
    xt = sy["x_target"]
    mas = lambda y_au: y_au / xt * RAD2MAS                       # sideways AU -> mas at the target's distance
    ym = np.array([mas(y) for y in ys])
    yt = mas(sy["y_target"])
    sun = next(b for b in sy["bodies"] if b["kind"] == "Sun")
    xr = (-0.25, max(2.6, 1.5 * xt))
    lo, hi = min(0.0, float(ym.min()), yt), max(0.0, float(ym.max()), yt)
    span = max(hi - lo, 1e-6)
    yr = (lo - 0.55 * span, hi + 0.75 * span)
    area = _plot_area(x0, y0, w, h)
    box = _Box(*area, xr, yr, equal=False)
    o = _frame(box, x0, y0, w, h, ["Light paths: distances along the star's direction true, sideways offsets in mas",
                                   f"(light deflection by the Sun, Jupiter and Saturn, as applied by the search)"],
               "AU along the star's direction (to the star: right)", f"mas at {sy['target_name']}'s distance")
    L = _Labels(*area)
    ex, ey = box(0, 0)
    gx, gy = box(xt, 0)
    rx, ry = box(xt, yt)
    far = box(xr[1], 0)
    o.append(f'<line x1="{ex:.1f}" y1="{ey:.1f}" x2="{far[0]:.1f}" y2="{far[1]:.1f}" stroke="#9ca3af" '
             f'stroke-width="{LW["line"]}" stroke-dasharray="7 5"/>')
    keep = xs <= xr[1]
    pts = " ".join(f"{a:.1f},{b:.1f}" for a, b in (box(x, y) for x, y in zip(xs[keep], ym[keep])))
    o.append(f'<polyline points="{pts}" fill="none" stroke="{PCOL["star"]}" stroke-width="{LW["ray"]}"/>')
    near = [(x, y) for x, y in zip(xs, ym) if x <= xt] + [(xt, yt)]
    pts = " ".join(f"{a:.1f},{b:.1f}" for a, b in (box(x, y) for x, y in near))
    o.append(f'<polyline points="{pts}" fill="none" stroke="{PCOL["target"]}" stroke-width="7" stroke-opacity="0.3"/>')
    # the Sun (and Jupiter, Saturn where they deflect the star's light), off scale: a marker on the panel's edge on
    # their side of the line (up: the Sun's side), at their distance along the star's line, with a broken line and
    # their true distance from the line
    defl = {n: a for n, a, _ in sy["by_body"]}
    labels_later, edge_slot = [], {}
    for b in sy["bodies"]:
        if b["kind"] != "Sun" and defl.get(b["name"], 0.0) < DEFL_SHOWN_MAS:
            continue
        off = math.hypot(b["y"], b["w"])
        up = b["y"] >= 0 or b["kind"] == "Sun"
        el = math.degrees(math.atan2(off, b["x"]))
        r = PSIZE[b["kind"]]
        y_edge = yr[1] if up else yr[0]
        if xr[0] <= b["x"] <= xr[1]:
            mx, my = box(b["x"], y_edge)
            my += (r + 4) * (1 if up else -1)
            fx, fy = box(b["x"], 0.0)                            # its foot on the star's line
            a_, z_ = (my + r + 3, fy - 5) if up else (fy + 5, my - r - 3)
            if z_ - a_ > 30:                                     # a broken distance line: the zigzag = off scale
                mid = (a_ + z_) / 2
                zz = " ".join(f"{mx + dx:.1f},{mid + dy:.1f}" for dx, dy in ((0, -9), (-6, -5), (6, 1), (-6, 7), (0, 11)))
                o.append(f'<polyline points="{mx:.1f},{a_:.1f} {zz} {mx:.1f},{z_:.1f}" fill="none" '
                         f'stroke="{PCOL[b["kind"]]}" stroke-width="{LW["line"]}"/>')
                L.taken.append((mx - 8, a_, mx + 8, z_))
                labels_later.append((mx + 6, mid, [f"{off:.2f} AU"], PCOL[b["kind"]], ("e", "w")))
            text = [f"{b['name']} ({el:.0f}° from the star, {defl.get(b['name'], 0):.2f} mas)"]
        else:
            left = b["x"] < xr[0]
            k = edge_slot.get((left, up), 0)
            edge_slot[(left, up)] = k + 1
            mx, my = box(xr[0] if left else xr[1], y_edge)
            mx += (r + 4 + 34 * k) * (1 if left else -1)
            my += (r + 4) * (1 if up else -1)
            where = "behind the Earth" if left else "beyond"
            text = [f"{b['name']} ({where}, {el:.0f}° from the star, {defl.get(b['name'], 0):.2f} mas;",
                    f"{off:.2f} AU off the line, {'this' if up else 'the other'} side)"]
        o.append(f'<circle cx="{mx:.1f}" cy="{my:.1f}" r="{r}" fill="{PCOL[b["kind"]]}"/>')
        L.block(mx, my, r + 3)
        right = mx > box.x0 + box.w / 2
        labels_later.append((mx, my, text, PCOL[b["kind"]], ("w", "sw", "nw", "s", "n") if right
                             else ("e", "se", "ne", "s", "n")))
    for px, py, r in ((ex, ey, 7), (gx, gy, 7), (rx, ry, 7)):
        L.block(px, py, r)
    L.taken.append((min(ex, far[0]), ey - 4, max(ex, far[0]), ey + 4))
    curve_px = [box(x, y) for x, y in zip(xs[keep], ym[keep])]
    for a, b in zip(curve_px[::4], curve_px[4::4]):             # keep the note and labels off the ray
        L.taken.append((min(a[0], b[0]), min(a[1], b[1]) - 3, max(a[0], b[0]), max(a[1], b[1]) + 3))
    by = ", ".join(f"{n} {a:.2f}" for n, a, _ in sy["by_body"] if a >= 0.005) or "below 0.005"
    note = [f"Bent by {sy['star_mas']:.2f} mas in all ({by});",
            f"grey: {sy['target_name']}'s own light, the same path, {sy['target_mas']:.2f} mas.",
            f"The star's light passes {sy['target_name']} {sy['shift_mas']:.2f} mas off",
            f"the straight line: the shadow moves {sy['shift_km']:.1f} km."]
    o += _corner_note(L, area, note, order=(2, 3, 1, 0))
    o.append(f'<circle cx="{ex:.1f}" cy="{ey:.1f}" r="{PSIZE["Earth"]}" fill="{PCOL["Earth"]}"/>'
             f'<circle cx="{gx:.1f}" cy="{gy:.1f}" r="5" fill="#fff" stroke="{PCOL["target"]}" stroke-width="2"/>'
             f'<circle cx="{rx:.1f}" cy="{ry:.1f}" r="5" fill="{PCOL["target"]}"/>')
    if abs(ry - gy) > 12:
        o += _arrow(gx, gy + (6 if ry > gy else -6), rx, ry - (6 if ry > gy else -6), PCOL["text"], LW["line"])
    L.taken.append((gx - 7, min(gy, ry), gx + 7, max(gy, ry)))   # the shift arrow
    for px, py, text, col, pref in labels_later:
        o += L.place(px, py, text, col, size=FS["label"], gap=6, prefer=pref)
    o += L.place(ex, ey, ["Earth"], PCOL["Earth"], size=FS["label"], prefer=("nw", "sw", "n", "s", "w"))
    o += L.place(gx, gy, [f"{sy['target_name']} without deflection"], PCOL["target"], size=FS["label"],
                 prefer=("n", "ne", "nw", "s"))
    o += L.place(rx, ry, [f"{sy['target_name']} on the star's ray:", "the star is hidden"], PCOL["target"],
                 size=FS["label"], prefer=("s", "sw", "se", "n"))
    o += L.place((gx + rx) / 2 + 4, (gy + ry) / 2, [f"{sy['shift_mas']:.2f} mas = {sy['shift_km']:.1f} km"],
                 PCOL["text"], size=FS["label"], prefer=("e", "w"))
    o += L.place(*box(xs[keep][-1], ym[keep][-1]), ["the star's light that", "reaches the Earth"], PCOL["star"],
                 size=FS["label"], prefer=("nw", "sw", "n", "s"))
    return o


def _inset(ins):
    """2 deg star chart, north up, east left, with the asteroid's motion in 24 h steps (bottom right)."""
    if not ins:
        return []
    size, x0, y0 = 220, W - 236, H - 290
    f = ins["field_arcmin"]
    s = size / f
    px = lambda xi: x0 + size / 2 - xi * s
    py = lambda eta: y0 + size / 2 - eta * s
    o = [f'<rect x="{x0}" y="{y0}" width="{size}" height="{size}" fill="#fff" stroke="#111"/>',
         f'<text x="{x0 + size / 2}" y="{y0 - 6}" text-anchor="middle" font-size="10" fill="#111">'
         f'{f / 60:g}° square, to G {ins["mag_limit"]:.1f}</text>',
         f'<text x="{x0 + size / 2}" y="{y0 + size + 14}" text-anchor="middle" font-size="10" fill="#111">'
         f'Motion in 24 h steps</text>']
    for xi, eta, g in ins["stars"]:
        if abs(xi) < f / 2 and abs(eta) < f / 2:
            r = max(0.7, min(4.5, 0.9 + 0.55 * (ins["mag_limit"] + 0.5 - g)))
            o.append(f'<circle cx="{px(xi):.1f}" cy="{py(eta):.1f}" r="{r:.1f}" fill="#111"/>')
    o.append(f'<circle cx="{px(0):.1f}" cy="{py(0):.1f}" r="7" fill="none" stroke="#6b7280"/>')
    tr = ins.get("track") or []
    for (a, b), col in zip(zip(tr, tr[1:]), ("#15803d", "#6b7280")):
        o.append(f'<line x1="{px(a[0]):.1f}" y1="{py(a[1]):.1f}" x2="{px(b[0]):.1f}" y2="{py(b[1]):.1f}" '
                 f'stroke="{col}" stroke-width="1.3"/>')
    return o


# ------------------------------------------------------------------------------------------- data (SPICE)
def gnomonic(ra, dec, ra0, dec0):
    """Arcmin offsets (xi east, eta north) of ra, dec (deg) about ra0, dec0."""
    ra, dec, ra0, dec0 = (np.radians(np.asarray(v, float)) for v in (ra, dec, ra0, dec0))
    c = np.sin(dec0) * np.sin(dec) + np.cos(dec0) * np.cos(dec) * np.cos(ra - ra0)
    xi = np.cos(dec) * np.sin(ra - ra0) / c
    eta = (np.cos(dec0) * np.sin(dec) - np.sin(dec0) * np.cos(dec) * np.cos(ra - ra0)) / c
    return np.degrees(xi) * 60, np.degrees(eta) * 60


def _hms(deg, sign=False):
    v = deg / 15 if not sign else abs(deg)
    h = int(v); m = int((v - h) * 60); s = ((v - h) * 60 - m) * 60
    if sign:
        return f"{'-' if deg < 0 else '+'}{h:2d} {m:02d} {s:06.3f}"
    return f"{h:2d} {m:02d} {s:07.4f}"


def system_data(spice, et, target, star_dir, target_name="target", star_name=""):
    """The geometry panels' data: positions of the Sun, Jupiter, Saturn and the target in the plane of the star's
    direction s (x) and the Sun (y), AU (w: off the plane); the light deflection (astrometry.deflect, by the Sun,
    Jupiter and Saturn, as the search applies it) of a source at distance x on the star's line; the star's ray that
    reaches the Earth, y(x) = x (d_star - d(x)) (a point on it is seen where the star is seen); the target on it and
    the shift that moves the shadow."""
    from pysyzygos import astrometry as A
    s = np.asarray(star_dir, float) / np.linalg.norm(star_dir)
    geo = lambda b: np.asarray(spice.spkpos(b, et, "J2000", "CN", "EARTH")[0])
    pos = {"Sun": (A.SUN, geo(A.SUN)), "Jupiter": (A.JUPITER, geo(A.JUPITER)), "Saturn": (A.SATURN, geo(A.SATURN))}
    ast = geo(str(target))
    sun = pos["Sun"][1]
    e2 = sun - (sun @ s) * s
    if np.linalg.norm(e2) < 1e-9 * np.linalg.norm(sun):
        e2 = np.cross(s, [0.0, 0.0, 1.0])
    e2 /= np.linalg.norm(e2)
    e3 = np.cross(s, e2)
    bodies = [dict(name=n, kind=n, x=float(v @ s / AU_KM), y=float(v @ e2 / AU_KM), w=float(v @ e3 / AU_KM),
                   dist=float(np.linalg.norm(v) / AU_KM)) for n, (_, v) in pos.items()]

    def defl(D, only=None):
        tot = np.zeros(3)
        for n, (b, v) in pos.items():
            if only and n != only:
                continue
            q = s if D == math.inf else A.unit(D * AU_KM * s - v)
            tot = tot + A.deflect(s, -v, q, A.GM[b])
        return tot
    x_t = float(np.linalg.norm(ast) / AU_KM)
    d_inf, d_t = defl(math.inf), defl(x_t)
    shift = d_inf - d_t
    xmax = max(2.6, 1.7 * x_t)
    curve_x = np.concatenate([np.linspace(0.0, x_t, 60)[1:], np.linspace(x_t, xmax, 80)[1:]])
    curve_y = np.array([x * float((d_inf - defl(x)) @ e2) for x in curve_x])
    y_t = x_t * float(shift @ e2)
    elong = math.degrees(math.acos(float(np.clip(sun @ s / np.linalg.norm(sun), -1, 1))))
    return dict(bodies=bodies, x_target=x_t, y_target=y_t, curve_x=[0.0] + curve_x.tolist(),
                curve_y=[0.0] + curve_y.tolist(), elong=elong, target_name=target_name, star_name=star_name,
                star_mas=float(np.linalg.norm(d_inf) * RAD2MAS), target_mas=float(np.linalg.norm(d_t) * RAD2MAS),
                shift_mas=float(np.linalg.norm(shift) * RAD2MAS),
                shift_km=float(np.linalg.norm(shift) * np.linalg.norm(ast)),
                by_body=[(n, float(np.linalg.norm(defl(math.inf, n)) * RAD2MAS),
                          float(np.linalg.norm(defl(x_t, n)) * RAD2MAS)) for n in pos])


def globe_data(spice, record, target, star_dir, paths, sigma3_km, site=None, stars=None, size=None,
               run_utc="", corrections=None, of_date=None, style="color", page="A4"):
    """The dict render_svg() draws. record: the hits_log record of the event; target: SPICE name of the asteroid;
    star_dir: the (corrected) J2000 unit vector used by the search; paths: paths.shadow_path() result;
    site: (lon_deg, lat_deg, name); stars: (ra, dec, g) arrays at the event date for the 2 deg chart;
    size: the size dict of the search (r_km, r_min_km, r_max_km, source); of_date: (ra_deg, dec_deg) true of date."""
    from pysyzygos.paths import plane_basis
    et = float(record["best_et"])
    basis = plane_basis(np.asarray(star_dir, float))
    x_ax, y_ax, z_ax = basis
    R = spice.pxform("ITRF93", "J2000", et)
    sun = np.asarray(spice.spkpos("SUN", et, "J2000", "LT+S", "EARTH")[0])
    ast = np.asarray(spice.spkpos(str(target), et, "J2000", "CN", "EARTH")[0])
    dist = float(np.linalg.norm(ast))
    v = float(record.get("speed_kms") or 0) or 1e-9
    # shadow axis in the fundamental plane, 1 s steps near whole minutes would be costly: 20 s steps, minutes exact
    span = 1.6 * A_KM / v
    ts = sorted(set(np.arange(et - span, et + span, 20.0).tolist() +
                    [m * 60.0 for m in range(int((et - span) // 60) + 1, int((et + span) // 60) + 1)]))
    axis = []
    for t in ts:
        a = np.asarray(spice.spkpos(str(target), t, "J2000", "CN", "EARTH")[0])
        axis.append((t, float(a @ x_ax), float(a @ y_ax)))
    # asteroid motion: hourly dRA (s of time) and dDec (arcsec)
    _, ra1, de1 = spice.recrad(spice.spkpos(str(target), et - 1800, "J2000", "CN", "EARTH")[0])
    _, ra2, de2 = spice.recrad(spice.spkpos(str(target), et + 1800, "J2000", "CN", "EARTH")[0])
    dra_s = ((math.degrees(ra2 - ra1) + 180) % 360 - 180) * 240.0
    ddec = math.degrees(de2 - de1) * 3600
    elong = math.degrees(math.acos(float(np.clip(np.dot(star_dir, sun / np.linalg.norm(sun)), -1, 1))))
    km_per_mas = dist / RAD2MAS
    ra_d = math.degrees(math.atan2(star_dir[1], star_dir[0])) % 360
    dec_d = math.degrees(math.asin(float(np.clip(star_dir[2], -1, 1))))
    centre = (paths or {}).get("center") or []
    t0, t1 = (centre[0][0], centre[-1][0]) if centre else (et, et)
    utc = lambda t, n=0: spice.et2utc(t, "ISOC", n)
    hm = lambda t: f"{utc(t)[11:13]}h {utc(t)[14:16]}m"
    size = size or {}
    r, r0, r1 = (float(record.get(k) or size.get(k) or 0) for k in ("r_km", "r_min_km", "r_max_km"))
    sig = (sigma3_km or 0) / 3
    corr = corrections or {}
    name = str(record.get("target_name") or target).strip()
    from pysyzygos.report import star_label
    star_name, star_others = star_label(record)
    title = f"{name} occults {star_name} on {utc(et)[:10]} from {hm(t0)} to {hm(t1)} UT"
    left = ["Star:" + (f" {star_name}" if star_name.startswith("UCAC4") else ""),
            *([f" {star_others}"] if star_others else []),
            f" G {float(record['mag']):.2f}",
            f" RA  = {_hms(ra_d)} (J2000, as used)",
            f" Dec = {_hms(dec_d, True)}",
            (f" [of Date: {_hms(of_date[0])}  {_hms(of_date[1], True)}]" if of_date else " [of Date: n/a]"),
            f" parallax {float(corr.get('parallax_mas', 0)):.2f} mas, deflection {float(corr.get('deflection_mas', 0)):.2f} mas applied",
            f"Prediction of {run_utc[:16].replace('T', ' ')} UT"]
    mid = [f"Durations: Max = {float(record.get('max_duration_s') or 0):.2f} secs",
           f"1km = {1 / v:.3f} secs, 1mas = {km_per_mas / v:.3f} secs",
           f"Mag Drop: {float(record.get('mag_drop') or 0):.1f}",
           f"Sun : Dist = {elong:.0f}°",
           (f"Moon: Dist = {float(record['moon_sep_deg']):.0f}°, illum = {float(record.get('moon_illum_pct') or 0):.0f}%"
            if record.get("moon_sep_deg") not in (None, "") and not _nan(record.get("moon_sep_deg")) else "Moon: -"),
           f"1σ Err: ±{sig:.1f} km = {sig / km_per_mas:.1f} mas (Horizons RSS)" if sig else "1σ Err: n/a"]
    right = ["Asteroid:",
             f" Mv = {float(record.get('m_ast') or 0):.1f}",
             f" Dia = {2 * r:.1f} ({2 * r0:.1f}-{2 * r1:.1f}) km, {2 * r / km_per_mas:.0f} mas",
             f" Parallax = {math.degrees(math.asin(A_KM / dist)) * 3600:.3f}\"",
             f" Hourly dRA = {dra_s:+.3f}s",
             f"        dDec = {ddec:+.2f}\"",
             f" Dist = {dist / AU_KM:.3f} AU"]
    inset = None
    if stars is not None:
        ra_s, dec_s, g = stars
        xi, eta = gnomonic(ra_s, dec_s, ra_d, dec_d)
        def sky(t):
            _, a, b = spice.recrad(spice.spkpos(str(target), t, "J2000", "CN", "EARTH")[0])
            tx, ty = gnomonic([math.degrees(a)], [math.degrees(b)], ra_d, dec_d)
            return float(tx[0]), float(ty[0])

        x0, y0 = sky(et)
        track = []
        for day in (-86400.0, 86400.0):           # the motion over +-1 day; a short search's orbit file may end
            for dt in (day, day / 4, day / 24):   # sooner: then a shorter step, drawn to a full day (straight there)
                try:
                    x, y = sky(et + dt)
                except Exception:                 # SPICE: not covered by the orbit file
                    continue
                k = day / dt
                track.append((x0 + k * (x - x0), y0 + k * (y - y0)))
                break
            else:
                track.append((x0, y0))
            if day < 0:
                track.append((x0, y0))
        inset = dict(field_arcmin=120.0, mag_limit=min(float(record["mag"]) + 1.5, 13.0),
                     stars=list(zip(np.ravel(xi).tolist(), np.ravel(eta).tolist(), np.ravel(g).tolist())), track=track)
    system = None
    if page != "square":
        short = name.split("(")[0].strip()                  # "(2026 ED138)" (unnumbered): empty, then the name
        short = " ".join(short.split()[1:]) if len(short.split()) > 1 and short.split()[0].isdigit() else short
        system = system_data(spice, et, target, star_dir, short or name, star_name)
    return dict(R=R, basis=basis, sun_dir=sun / np.linalg.norm(sun), paths=paths, axis=axis, site=site, style=style,
                title=title, columns=(left, mid, right), inset=inset, page=page, system=system,
                minute_label=lambda t: utc(t)[14:16],
                footer=f"PySyzygos {__version__} · orbit JPL Horizons · size: "
                       f"{str(record.get('size_source') or size.get('source') or '').split(' (ref')[0]} · "
                       f"Earth as seen from the star at {utc(et)[11:19]} UT")


def _nan(v):
    try:
        return math.isnan(float(v))
    except (TypeError, ValueError):
        return True
