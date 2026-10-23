"""preview.py - event preview: the star field around the occulted star at the event time, as an SVG image.

Shows the stars of the local Gaia catalog (moved by proper motion to the event date) in a finder field a few times
larger than the camera's field of view, the camera frame centred on the target star, the target star, the asteroid's
position and its track (+/- 1 h), a scale bar and the north/east directions. Orientation: north up, east left, as seen
on the sky (a telescope may flip or rotate this). A magnifier in the top right corner (`zoom`, 10-50 arcsec) shows
the target star with its close neighbours: each star as a sharp core plus a halo of the seeing's size (where halos
overlap, the stars blend in a camera), neighbours labelled with G difference and separation, the asteroid's track
with second ticks, and per neighbour (hover) when the asteroid passes it and how far its shadow path lies from the
target star's.

Standard library + numpy; the caller supplies the stars and the asteroid track (search.py does, with SPICE).
"""
from pysyzygos.version import __version__
import math
import numpy as np

SIZE = 560                                 # image width and height, px (field area)
DENSE_START, DENSE_KEEP = 4000, 1500      # very dense field (> DENSE_START stars): only the brightest DENSE_KEEP are
                                           # drawn normally, the fainter ones as small dim dots
ZOOM_PX = 184                              # magnifier box, px (top right corner of the field)
ZOOM_MIN, ZOOM_MAX, ZOOM_DEFAULT = 10.0, 50.0, 30.0   # its field, arcsec (auto: 3 x the nearest neighbour's distance)
ZOOM_DMAG = 6.0                            # neighbours labelled up to this much fainter than the target


def camera_fov_arcmin(focal_mm, sensor_mm):
    """(width, height) of the camera field of view in arcmin."""
    return tuple(2 * math.degrees(math.atan(s / 2 / focal_mm)) * 60 for s in sensor_mm)


def _gnomonic(ra, dec, ra0, dec0):
    """Tangent-plane coordinates (arcmin) of (ra, dec) around (ra0, dec0): xi east, eta north."""
    ra, dec, ra0, dec0 = (np.radians(np.asarray(x, float)) for x in (ra, dec, ra0, dec0))
    cosc = np.sin(dec0) * np.sin(dec) + np.cos(dec0) * np.cos(dec) * np.cos(ra - ra0)
    xi = np.cos(dec) * np.sin(ra - ra0) / cosc
    eta = (np.cos(dec0) * np.sin(dec) - np.sin(dec0) * np.cos(dec) * np.cos(ra - ra0)) / cosc
    return np.degrees(xi) * 60, np.degrees(eta) * 60


def zoom_field_arcsec(sep_nearest=None, fixed=None):
    """The magnifier's field (arcsec): fixed if given, else 3 x the nearest neighbour's separation, 10-50 arcsec;
    30 arcsec without a neighbour within 25 arcsec."""
    if fixed:
        return float(np.clip(fixed, 1.0, 600.0))
    if sep_nearest is None or sep_nearest > 25.0:
        return ZOOM_DEFAULT
    return float(np.clip(3.0 * sep_nearest, ZOOM_MIN, ZOOM_MAX))


def _zoom_svg(z, target, field_scale, ox, oy):
    """The magnifier (module doc) as SVG elements; box at (ox, oy) in the field's pixels.
    z: dict(stars=dict(ra, dec, g), field_arcsec, track=[(s, ra, dec)] (seconds from the event), delta_km, r_km,
    seeing_arcsec)."""
    S, fa = ZOOM_PX, float(z["field_arcsec"])
    k = S / fa                                                          # px per arcsec
    c = S / 2
    out = [f'<g transform="translate({ox:.1f},{oy:.1f})">',
           '<defs><clipPath id="zclip"><rect width="%d" height="%d"/></clipPath>'
           '<radialGradient id="zhalo"><stop offset="0" stop-color="#f8fafc" stop-opacity="1"/>'
           '<stop offset="0.5" stop-color="#f8fafc" stop-opacity="0.45"/>'
           '<stop offset="1" stop-color="#f8fafc" stop-opacity="0"/></radialGradient></defs>' % (S, S),
           f'<rect width="{S}" height="{S}" fill="#02040a" stroke="#f43f5e" stroke-width="1.2"/>',
           '<g clip-path="url(#zclip)">']
    st = z.get("stars") or {}
    xi, eta = _gnomonic(st.get("ra", []), st.get("dec", []), target["ra"], target["dec"])
    xi, eta = np.asarray(xi, float) * 60, np.asarray(eta, float) * 60   # arcsec
    g = np.asarray(st.get("g", []), float)
    g0 = float(target["g"])
    # the asteroid's track: direction and speed for the per-star passing times and shadow offsets
    tr = z.get("track") or []
    u = rate = None
    if len(tr) > 1:
        ts = np.array([p[0] for p in tr], float)
        txi, teta = _gnomonic([p[1] for p in tr], [p[2] for p in tr], target["ra"], target["dec"])
        txi, teta = np.asarray(txi, float) * 60, np.asarray(teta, float) * 60
        d = np.array([txi[-1] - txi[0], teta[-1] - teta[0]])
        rate = float(np.hypot(*d) / (ts[-1] - ts[0])) if ts[-1] > ts[0] else None   # arcsec/s
        u = d / max(np.hypot(*d), 1e-12)
    seeing = float(z.get("seeing_arcsec") or 2.0)
    halo = max(seeing * k, 3.0)                                         # px: halo radius ~ the seeing FWHM
    labels = []
    for i in np.argsort(-g):                                            # faint first
        x, y = c - xi[i] * k, c - eta[i] * k
        if not (-halo <= x <= S + halo and -halo <= y <= S + halo):
            continue
        dg = g[i] - g0
        f = 10 ** (-0.4 * dg)                                           # flux relative to the target
        core = float(np.clip(1.4 + 3.6 * f ** 0.5, 1.2, 6.5))
        op = float(np.clip(0.25 + 0.6 * f ** 0.5, 0.18, 0.85))
        sep = float(np.hypot(xi[i], eta[i]))
        is_target = sep < 0.05 and abs(dg) < 0.3
        tip = f"G {g[i]:.2f}"
        if not is_target:
            pa = math.degrees(math.atan2(xi[i], eta[i])) % 360.0
            tip += f" (\u0394G {dg:+.2f}), {sep:.2f}\u2033 at PA {pa:.0f}\u00b0 from the target star"
            if u is not None and rate:
                along = xi[i] * u[0] + eta[i] * u[1]                    # arcsec along the asteroid's motion
                across = -xi[i] * u[1] + eta[i] * u[0]
                tip += f"; the asteroid passes it {along / rate:+.1f} s from the event"
                if z.get("delta_km"):
                    tip += (f", its shadow path {abs(math.radians(across / 3600.0) * z['delta_km']):,.0f} km "
                            f"from the target star's")
            if dg <= ZOOM_DMAG:
                labels.append((sep, x, y, core, f"\u0394G {dg:+.1f} \u00b7 {sep:.1f}\u2033"))
        out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{halo:.1f}" fill="url(#zhalo)" fill-opacity="{op:.2f}"/>'
                   f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{core:.1f}" fill="#f8fafc"><title>{_esc(tip)}</title></circle>')
    if len(tr) > 1:                                                     # the track, ticks in seconds
        pts = " ".join(f"{c - a * k:.1f},{c - b * k:.1f}" for a, b in zip(txi, teta))
        out.append(f'<polyline points="{pts}" fill="none" stroke="#f59e0b" stroke-width="1.2" stroke-dasharray="3 3"/>')
        for t_, a, b in zip(ts, txi, teta):
            out.append(f'<circle cx="{c - a * k:.1f}" cy="{c - b * k:.1f}" r="{2.2 if t_ == 0 else 1.3}" '
                       f'fill="#f59e0b"><title>{t_:+.0f} s</title></circle>')
    # the target star: open ring; neighbours: labels (closest first, no overlaps, at most 6)
    out.append(f'<circle cx="{c}" cy="{c}" r="{max(halo, 8) + 3:.1f}" fill="none" stroke="#f43f5e" '
               f'stroke-width="1" stroke-opacity="0.8"/>')
    placed = []
    for sep, x, y, core, text in sorted(labels)[:6]:
        lx, ly = x + core + 4, y - core - 2
        anchor = ""
        if lx + 70 > S:
            lx, anchor = x - core - 4, ' text-anchor="end"'
        while any(abs(ly - b) < 11 and abs(lx - a) < 70 for a, b in placed):
            ly += 11
        placed.append((lx, ly))
        out.append(f'<text x="{lx:.1f}" y="{ly:.1f}" fill="#fbbf24" font-size="10"{anchor}>{_esc(text)}</text>')
    out.append('</g>')
    # title strip (field, seeing) and bottom strip (scale bar, the asteroid's apparent size)
    bar = next((b for b in (1, 2, 5, 10, 20) if b * k >= S / 6), 20)
    out.append(f'<g font-size="10"><rect width="{S}" height="16" fill="#02040a" fill-opacity="0.75"/>'
               f'<text x="5" y="12" fill="#f43f5e">zoom {fa:.0f}\u2033</text>'
               f'<text x="{S - 5}" y="12" fill="#cbd5e1" text-anchor="end">seeing {seeing:.1f}\u2033 (halos)</text>'
               f'<rect y="{S - 16}" width="{S}" height="16" fill="#02040a" fill-opacity="0.75"/>'
               f'<path d="M6,{S - 8} h{bar * k:.1f}" stroke="#cbd5e1" stroke-width="1.5"/>'
               f'<text x="{bar * k + 10:.1f}" y="{S - 4}" fill="#cbd5e1">{bar}\u2033</text>')
    if z.get("delta_km") and z.get("r_km"):
        out.append(f'<text x="{S - 5}" y="{S - 4}" fill="#f59e0b" text-anchor="end"><title>the asteroid\'s track as '
                   f'seen from your site, dots every {abs(tr[1][0] - tr[0][0]) if len(tr) > 1 else 0:.0f} s; its '
                   f'apparent diameter</title>asteroid \u2300 {2 * math.degrees(z["r_km"] / z["delta_km"]) * 3.6e6:.0f} mas</text>')
    out.append('</g>')
    out.append('</g>')
    return out


def _esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def render_svg(stars, target, track, fov_arcmin, field_factor=3.0, title="", subtitle="", min_field_arcmin=10.0,
               disks=None, body_name=None, field_arcmin=None, corridor_arcsec=None, corridor_km=None, zoom=None):
    """SVG text of the preview.
    stars: dict of arrays ra, dec (deg, at the event date), g (Gaia G)
    target: dict ra, dec, g (the occulted star)
    track: list of (minutes from the event, ra, dec) of the asteroid; must include 0
    fov_arcmin: (width, height) of the camera field.
    disks: planets and moons to draw at their angular size, [dict(ra, dec, r_arcsec, label, main)] (main: the
    occulting body; moon: marked with a "+" whatever its size); body_name: the occulting body's name for the legend (a planet or moon) instead of "asteroid";
    field_arcmin: the field size instead of the camera-based one (planets and moons: zoomed to their system).
    corridor_arcsec: half-width of the searched strip around the track (dotted lines; corridor_km for the legend).
    zoom: the magnifier (_zoom_svg's z), None for none."""
    fw, fh = fov_arcmin
    field = field_arcmin or max(field_factor * max(fw, fh), min_field_arcmin)   # square finder field, arcmin
    scale = SIZE / field                                               # px per arcmin
    cx = cy = SIZE / 2
    px = lambda xi: cx - xi * scale                                    # east left
    py = lambda eta: cy - eta * scale                                  # north up
    head = 74
    W, H = SIZE, SIZE + head
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
           f'font-family="system-ui,sans-serif">',
           f'<rect width="{W}" height="{H}" fill="#0b1020"/>',
           f'<text x="12" y="22" fill="#e5e7eb" font-size="15" font-weight="600">{_esc(title)}</text>',
           f'<text x="12" y="42" fill="#9ca3af" font-size="12">{_esc(subtitle)}</text>',
           f'<g transform="translate(0,{head})">',
           f'<rect width="{SIZE}" height="{SIZE}" fill="#05070f"/>']
    # stars, faint first so bright ones are drawn on top
    xi, eta = _gnomonic(stars["ra"], stars["dec"], target["ra"], target["dec"])
    g = np.asarray(stars["g"], float)
    order = np.argsort(-g)
    X, Y = px(np.asarray(xi, float)), py(np.asarray(eta, float))
    inside = (X >= 0) & (X <= SIZE) & (Y >= 0) & (Y <= SIZE)
    g_in = np.sort(g[inside])
    g_dim = float(g_in[DENSE_KEEP]) if len(g_in) > DENSE_START else None   # very dense: fainter than this dimmed
    g_max = float(g_in[-1]) if len(g_in) else 0.0
    for k in order:
        if not inside[k]:
            continue
        if g_dim is not None and g[k] > g_dim:                         # small, dim dot, fading towards the limit
            t = (g[k] - g_dim) / max(g_max - g_dim, 0.1)
            r, op = 0.85 - 0.4 * t, 0.38 - 0.22 * t
        else:
            r, op = float(np.clip(0.8 + 0.55 * (16.5 - g[k]), 0.7, 7.5)), min(1.0, 0.45 + 0.08 * (16.5 - g[k]))
        out.append(f'<circle cx="{X[k]:.1f}" cy="{Y[k]:.1f}" r="{r:.2f}" fill="#f8fafc" fill-opacity="'
                   f'{op:.2f}"><title>G {g[k]:.2f}</title></circle>')
    # camera frame
    out.append(f'<rect x="{cx - fw * scale / 2:.1f}" y="{cy - fh * scale / 2:.1f}" width="{fw * scale:.1f}" '
               f'height="{fh * scale:.1f}" fill="none" stroke="#38bdf8" stroke-width="1.5" stroke-dasharray="6 4"/>')
    out.append(f'<text x="{cx - fw * scale / 2 + 4:.1f}" y="{cy - fh * scale / 2 - 6:.1f}" fill="#38bdf8" '
               f'font-size="11">camera {fw:.1f}′ × {fh:.1f}′</text>')
    # translucent backing for the legend and scale bar (bottom left)
    leg_h = 56 + (18 if corridor_arcsec and track else 0)
    out.append(f'<rect x="8" y="{SIZE - 10 - leg_h}" width="320" height="{leg_h}" rx="4" fill="#05070f" fill-opacity="0.8"/>')
    # asteroid track and position
    if track:
        t = np.array([p[0] for p in track], float)
        axi, aeta = _gnomonic([p[1] for p in track], [p[2] for p in track], target["ra"], target["dec"])
        pts = " ".join(f"{px(a):.1f},{py(b):.1f}" for a, b in zip(axi, aeta))
        out.append(f'<polyline points="{pts}" fill="none" stroke="#f59e0b" stroke-width="1.5" stroke-dasharray="3 3"/>')
        if corridor_arcsec and len(t) > 1:                              # searched strip: track +/- half-width
            tx, ty = np.gradient(np.asarray(axi, float)), np.gradient(np.asarray(aeta, float))
            n = np.hypot(tx, ty)
            n[n == 0] = 1.0
            w = corridor_arcsec / 60.0                                  # arcmin
            for sgn in (1, -1):
                pts = " ".join(f"{px(a + sgn * w * -b_ / nn):.1f},{py(b + sgn * w * a_ / nn):.1f}"
                               for a, b, a_, b_, nn in zip(axi, aeta, tx, ty, n))
                out.append(f'<polyline points="{pts}" fill="none" stroke="#a3e635" stroke-width="1.2" '
                           f'stroke-dasharray="1 4" stroke-linecap="round" stroke-opacity="0.8"/>')
            out.append(f'<g font-size="11" fill="#a3e635"><path d="M16,{SIZE - 70} h22" stroke="#a3e635" stroke-width="1.2" '
                       f'stroke-dasharray="1 4" stroke-linecap="round"/><text x="44" y="{SIZE - 66}">search corridor '
                       f'±{corridor_arcsec:.1f}″' + (f' (±{corridor_km:,.0f} km)' if corridor_km else '') + '</text></g>')
        if len(t) > 1:                                                  # arrow at the end: direction of motion
            x1, y1, x0, y0 = px(axi[-1]), py(aeta[-1]), px(axi[-2]), py(aeta[-2])
            ang = math.atan2(y1 - y0, x1 - x0)
            a1, a2 = ang + 2.6, ang - 2.6
            out.append(f'<path d="M{x1:.1f},{y1:.1f} L{x1 + 7 * math.cos(a1):.1f},{y1 + 7 * math.sin(a1):.1f} '
                       f'M{x1:.1f},{y1:.1f} L{x1 + 7 * math.cos(a2):.1f},{y1 + 7 * math.sin(a2):.1f}" '
                       f'stroke="#f59e0b" stroke-width="1.5"/>')
        i0 = int(np.argmin(np.abs(t)))
        ax, ay = px(axi[i0]), py(aeta[i0])
        out.append(f'<path d="M{ax:.1f},{ay - 5:.1f} L{ax + 5:.1f},{ay:.1f} L{ax:.1f},{ay + 5:.1f} L{ax - 5:.1f},{ay:.1f} Z" '
                   f'fill="none" stroke="#f59e0b" stroke-width="1.5"><title>asteroid at the event</title></path>')
        out.append(f'<g font-size="11" fill="#f59e0b"><path d="M16,{SIZE - 52} h22" stroke="#f59e0b" stroke-width="1.5" '
                   f'stroke-dasharray="3 3"/><text x="44" y="{SIZE - 48}">{_esc(body_name or "asteroid")} track '
                   f'{t[0]:+.0f} to {t[-1]:+.0f} min, '
                   f'◇ at the event</text></g>')
    # planets and moons at their angular size (the occulting body brighter), labelled
    placed = []                                                         # label positions (no overlaps)
    for dk in disks or []:
        dxi, deta = _gnomonic([dk["ra"]], [dk["dec"]], target["ra"], target["dec"])
        x, y, rr = px(dxi[0]), py(deta[0]), max(dk["r_arcsec"] / 60.0 * scale, 2.0)
        if -rr <= x <= SIZE + rr and -rr <= y <= SIZE + rr:
            fill = "#fde68a" if dk.get("main") else "#cbd5e1"
            out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{rr:.1f}" fill="{fill}" fill-opacity="0.35" stroke="{fill}" '
                       f'stroke-width="1.2"><title>{_esc(dk["label"])}: radius {dk["r_arcsec"]:.1f}″</title></circle>')
            if dk.get("moon"):                                          # every moon: a "+" at its centre
                k = max(4.0, rr + 3.0)
                out.append(f'<path d="M{x - k:.1f},{y:.1f} H{x + k:.1f} M{x:.1f},{y - k:.1f} V{y + k:.1f}" '
                           f'stroke="#22d3ee" stroke-width="1.3"><title>{_esc(dk["label"])}</title></path>')
            left = x + rr + 4 + 7 * len(dk["label"]) > SIZE - 4             # near the right edge: label on the left
            lx, ly = (x - rr - 4, y - rr - 2) if left else (x + rr + 4, y - rr - 2)
            while any(abs(ly - py_) < 12 and abs(lx - px_) < 60 for px_, py_ in placed):
                ly += 12
            placed.append((lx, ly))
            out.append(f'<text x="{lx:.1f}" y="{ly:.1f}" fill="{fill}" font-size="11"'
                       + (' text-anchor="end"' if left else '') + f'>{_esc(dk["label"])}</text>')
    # target star
    r = 11
    out.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="#f43f5e" stroke-width="1.8"/>')
    out.append(f'<path d="M{cx - r - 9},{cy} H{cx - r - 2} M{cx + r + 2},{cy} H{cx + r + 9} '
               f'M{cx},{cy - r - 9} V{cy - r - 2} M{cx},{cy + r + 2} V{cy + r + 9}" stroke="#f43f5e" stroke-width="1.8"/>')
    out.append(f'<text x="{cx + r + 12}" y="{cy + 4}" fill="#f43f5e" font-size="12">G {target["g"]:.2f}</text>')
    if zoom:                                                            # magnifier, top right, with a leader line
        ox, oy = SIZE - ZOOM_PX - 8, 8
        out.append(f'<path d="M{cx + 8},{cy - 8} L{ox},{oy + ZOOM_PX}" stroke="#f43f5e" stroke-width="0.8" '
                   f'stroke-opacity="0.6" stroke-dasharray="2 3"/>')
        out += _zoom_svg(zoom, target, scale, ox, oy)
    # compass (north up, east left) and scale bar
    out.append(f'<g stroke="#9ca3af" stroke-width="1.5" fill="#9ca3af" font-size="12">'
               f'<path d="M{SIZE - 30},{SIZE - 30} V{SIZE - 70} M{SIZE - 30},{SIZE - 30} H{SIZE - 70}"/>'
               f'<text x="{SIZE - 35}" y="{SIZE - 75}" stroke="none">N</text>'
               f'<text x="{SIZE - 86}" y="{SIZE - 26}" stroke="none">E</text></g>')
    bar = max(1, round(field / 5))                                      # arcmin
    out.append(f'<g stroke="#9ca3af" stroke-width="2" font-size="12" fill="#9ca3af">'
               f'<path d="M16,{SIZE - 22} H{16 + bar * scale:.1f}"/>'
               f'<text x="16" y="{SIZE - 30}" stroke="none">{bar}′</text></g>')
    out.append("</g>")
    out.append(f'<text x="12" y="60" fill="#6b7280" font-size="11">'
               f'field {field:.0f}′ · stars to G {float(np.max(g)) if len(g) else 0:.1f}'
               + (f' · dense: fainter than G {g_dim:.1f} dimmed' if g_dim is not None else '') + ' · N up, E left</text>')
    out.append("</svg>")
    return "\n".join(out)
