"""paths.py - ground track of an asteroid shadow as KML for Google My Maps / Earth.

Needs the same SPICE state as the main tool: LSK, planetary SPK, Earth PCK (ITRF93) and the
asteroid SPK loaded, and the asteroid number string aliased (kernels.body_alias; fetch_target_orbit does that).

v2: SpiceyPy's surfpt() returns only the point and raises NotFoundError when the ray misses the Earth
(v1 unpacked a (point, found) tuple, which crashed near the ends of the time window).
"""
from pysyzygos.version import __version__
import numpy as np
import spiceypy as spice
from spiceypy.utils.exceptions import NotFoundError
from xml.sax.saxutils import escape

AU_KM = 149597870.7


C_KM_S = 299792.458                     # km/s


def plane_basis(star_vector):
    """Fundamental-plane axes in J2000: x east, y north, z toward the star (same as besselian_offsets)."""
    z = star_vector / np.linalg.norm(star_vector)
    x = np.cross([0.0, 0.0, 1.0], z)
    if np.linalg.norm(x) < 1e-12:                 # star at a celestial pole
        x = np.array([1.0, 0.0, 0.0])
    x = x / np.linalg.norm(x)
    y = np.cross(z, x)
    return x, y, z


LIMIT_PASSES = 5          # limit lines: offset across the motion relative to their ground point, at most this many passes


def bary_velocity(tid, et, ast0):
    """The asteroid's barycentric velocity (km/s, J2000) at its emission time et - |ast0|/c (ast0: geocentric 'CN')."""
    return np.asarray(spice.spkezr(tid, et - float(np.linalg.norm(ast0)) / C_KM_S, 'J2000', 'NONE', '0')[0][3:])


# Math: PL.2, PL.3 (slide PL), AS.1 (slide AS): from a point of the geocentric plane down the ray along -z to the
# ground, moved by v_perp dtau for that ground point's own light time.
def ground_point(base, ast0, v_bary, z_ax, R, radii, iterations=4):
    """The ground point (ITRF93, km) of the plane point base (J2000, from the Earth's centre, in the plane through it
    perpendicular to z_ax): a ray from 2 Earth radii out on the star side along -z_ax to the first intersection with
    the ellipsoid radii (a, b, c); the point sees the asteroid dtau = (|A - E| - |A - G|)/c sooner than the geocentre,
    so the axis moves by the asteroid's barycentric velocity across the star x dtau (iterated from dtau = 0). ast0:
    the asteroid from the Earth's centre ('CN'), v_bary: bary_velocity, R: pxform('J2000', 'ITRF93', et). Shared by
    shadow_path and search.earth_point. Raises NotFoundError where the ray misses the Earth."""
    from pysyzygos import earth
    v_perp = v_bary - (v_bary @ z_ax) * z_ax
    dist0 = float(np.linalg.norm(ast0))
    dtau = 0.0
    for _ in range(iterations):                                     # geocentric light time first, then the point's
        vertex = base + v_perp * dtau + 2.0 * earth.A_KM * z_ax
        point = spice.surfpt(R @ vertex, R @ (-z_ax), *radii)
        p_j = R.T @ point
        # the distance from the point to the asteroid where the point sees it (dtau further on its orbit): with
        # ast0 alone the radial motion during dtau (~0.6 km) was left out, a few cm
        dtau = (dist0 - float(np.linalg.norm(ast0 + v_bary * dtau - p_j))) / C_KM_S
    return point


# Math: PT.1-PT.4, PL.1-PL.4, PD.1, PD.3 (slides PG, PT, PL, PD), AS.1 (slide AS): the geocentric plane, the lines on it,
# the ray to the ground; each ground point G's centre line shifted by v_perp (|A - E| - |A - G|)/c (light time
# from that point, as LT.1 for the site; in the code ast0 = A - E = a, p_j = G - E, dtau = PL.3).
def shadow_path(target_id, star_dir, et_best, r_km, sigma3_km, half_span=None, step=None, sat_km=None, height_km=None):
    """Ground track of the shadow axis and its limits.

    Returns {name: [(et, lon_deg, lat_deg, duration_s_or_None), ...]} for
    'center', 'edge_plus', 'edge_minus' (+/- r_km), 'sigma1_plus', 'sigma1_minus' (+/- (r_km + sigma3_km / 3), the
    1-sigma limits) and 'sigma_plus', 'sigma_minus' (+/- (r_km + sigma3_km)); with sat_km (a known satellite's distance
    plus radius, binaries.zone_km) also 'satellite_plus', 'satellite_minus' (+/- (r_km + sat_km)): where the
    satellite's shadow can pass. With height_km (the site's height above the WGS84 ellipsoid, |h| >= 1 m) also
    'center_height': the center line on the surface raised by that height (where an observer at the site's height
    sees the central event; the other lines are at height 0, as Occult's), shifted by about h / tan(star altitude)
    towards the star's azimuth.
    '+' is the side 90 deg counter-clockwise of the shadow's motion in the plane (x east, y north).
    duration_s is the centre-line duration 2*r/(shadow speed relative to the ground point).

    Samples where a line does not touch the Earth (shadow off the disk, or a limit line beyond the
    terminator) are skipped, so lines can have different lengths and may be empty.
    half_span / step (s) default to values derived from the shadow speed: the span covers about
    1.3 Earth radii of along-track motion on each side of the axis's closest approach to the Earth's centre (not of
    et_best, the observer's, which can be near one end of the track), the step about 100 km of along-track motion.
    An explicit half_span is centred on et_best.
    """
    from pysyzygos import earth                          # WGS84: points on its surface, height 0 (as Occult)
    a, b, c = earth.A_KM, earth.A_KM, earth.C_KM
    flat = earth.F
    x_ax, y_ax, z_ax = plane_basis(star_dir)
    M = np.vstack((x_ax, y_ax, z_ax))
    tid = str(target_id)

    def axis_velocity(et):                              # shadow velocity on the plane, km/s
        p0, _ = spice.spkpos(tid, et - 0.5, 'J2000', 'CN', 'EARTH')
        p1, _ = spice.spkpos(tid, et + 0.5, 'J2000', 'CN', 'EARTH')
        return (M @ (p1 - p0))[:2]

    v_best = axis_velocity(et_best)
    speed = np.linalg.norm(v_best)
    if speed < 1e-6:
        raise ValueError("shadow does not move on the fundamental plane")
    if step is None:
        step = max(1.0, min(60.0, 100.0 / speed))
    k0 = 0
    if half_span is None:
        # et_best is the closest approach at the observer's site, which can lie near one end of the track: centre
        # the span on the axis's closest approach to the Earth's centre instead (whole steps, so et_best stays on
        # the grid); 1.3 Earth radii either side of it cover the whole crossing
        ast_best, _ = spice.spkpos(tid, et_best, 'J2000', 'CN', 'EARTH')
        xy = (M @ ast_best)[:2]
        k0 = int(round(-(xy @ v_best) / speed ** 2 / step))
        half_span = 1.3 * a / speed
    n_steps = int(np.ceil(half_span / step))
    ets = et_best + step * (k0 + np.arange(-n_steps, n_steps + 1))

    offsets = {'center': 0.0, 'edge_plus': r_km, 'edge_minus': -r_km,
               'sigma1_plus': r_km + sigma3_km / 3.0, 'sigma1_minus': -(r_km + sigma3_km / 3.0),
               'sigma_plus': r_km + sigma3_km, 'sigma_minus': -(r_km + sigma3_km)}
    if sat_km:
        offsets.update(satellite_plus=r_km + sat_km, satellite_minus=-(r_km + sat_km))
    out = {k: [] for k in offsets}
    last_n = {}                                     # per limit line: the converged direction of the previous sample
    radii = {}
    if height_km is not None and abs(height_km) >= 0.001:              # the center line at the site's height
        offsets['center_height'] = 0.0
        out['center_height'] = []
        radii['center_height'] = (a + height_km, b + height_km, c + height_km)   # the height-h surface to < 1 cm up to 5 km

    for et in ets:
        ast0, _ = spice.spkpos(tid, et, 'J2000', 'CN', 'EARTH')          # same convention as the solver
        v_axis = axis_velocity(et)
        n = np.array([-v_axis[1], v_axis[0]]) / np.linalg.norm(v_axis)
        n3 = n[0] * x_ax + n[1] * y_ax                                  # J2000 unit vector across the track
        axis_pt = ast0 - (ast0 @ z_ax) * z_ax                           # shadow axis point in the plane through the geocentre
        R = spice.pxform('J2000', 'ITRF93', et)
        R1 = spice.pxform('J2000', 'ITRF93', et + 1.0)
        # each ground point gets the asteroid's light dtau = (|A| - |A - P|)/c sooner than the geocentre (up to 21 ms),
        # so it sees the asteroid dtau later on its orbit: the axis moves by the asteroid's BARYCENTRIC velocity
        # (across the star direction) x dtau (as search.besselian_offsets, which takes the light time from the site)
        v_bary = bary_velocity(tid, et, ast0)

        for name, off in offsets.items():
            # start 2 Earth radii out on the star side of the plane and look along -z (the light direction);
            # the first surface intersection is the star-facing side of the Earth
            try:
                # a limit line: a site there has its closest approach when its offset is across the shadow's motion
                # RELATIVE TO IT (the ground turns with the Earth), not across the geocentric motion (n3): up to
                # ~0.7 % of the offset closer for slow shadows (PD.3). Started from the previous sample's direction,
                # refined until it changes the point by less than 1 cm (mostly no extra ray)
                n_use = last_n.get(name, n) if off else n
                point = ground_point(axis_pt + off * (n_use[0] * x_ax + n_use[1] * y_ax), ast0, v_bary, z_ax, R,
                                     radii.get(name, (a, b, c)))
                for _ in range(LIMIT_PASSES if off else 0):
                    v_rel = v_axis - (M @ (R1.T @ point - R.T @ point))[:2]
                    nr = np.array([-v_rel[1], v_rel[0]]) / np.linalg.norm(v_rel)
                    if abs(off) * np.linalg.norm(nr - n_use) < 1e-5:     # the direction holds to 1 cm
                        break
                    n_use = nr
                    point = ground_point(axis_pt + off * (nr[0] * x_ax + nr[1] * y_ax), ast0, v_bary, z_ax, R,
                                         radii.get(name, (a, b, c)))
                last_n[name] = n_use
            except NotFoundError:
                continue                                                # this line misses the Earth at this time
            lon, lat, _ = spice.recgeo(point, a, flat)
            dur = None
            if name == 'center':
                v_ground = (M @ (R1.T @ point - R.T @ point))[:2]       # same ground point, one second later
                dur = 2.0 * r_km / np.linalg.norm(v_axis - v_ground)
            out[name].append((et, np.degrees(lon), np.degrees(lat), dur))
    return out


# Math: PD.2 (slide PD): the site-height shift: horizontal displacement h / tan(alt) towards the star's azimuth (the
# ray meets the raised surface h / sin(alt) earlier), its component across the ground track (the axis's ground
# points 30 s apart).
def height_shift_km(target_id, star_dir, et, lon_deg, lat_deg, h_km):
    """How far the center line at the site's height (h_km above the WGS84 ellipsoid) lies from the one at height 0,
    across the ground track at the site: km, signed ('+' = towards the A side, shadow_path's 'edge_plus'); None with
    the star below 1 deg. A ray along the star direction meets the raised surface h / sin(alt) before the ellipsoid,
    h / tan(alt) horizontally towards the star's azimuth. The ground track's direction comes from the shadow axis's
    ground points at et -+ 30 s (Earth-fixed: the Earth's rotation turns it away from the plane's along-track
    direction); where the axis misses the Earth then, the horizontal part of the plane's across-track vector."""
    from pysyzygos import earth
    a, c = earth.A_KM, earth.C_KM
    x_ax, y_ax, z_ax = plane_basis(star_dir)
    lon, lat = np.radians(lon_deg), np.radians(lat_deg)
    R = spice.pxform('J2000', 'ITRF93', et)
    up = np.array([np.cos(lat) * np.cos(lon), np.cos(lat) * np.sin(lon), np.sin(lat)])     # ITRF93 from here on
    zf = R @ z_ax
    sin_alt = float(up @ zf)
    if sin_alt < np.sin(np.radians(1.0)):
        return None
    tid = str(target_id)
    p0, _ = spice.spkpos(tid, et - 0.5, 'J2000', 'CN', 'EARTH')
    p1, _ = spice.spkpos(tid, et + 0.5, 'J2000', 'CN', 'EARTH')
    v = np.array([(p1 - p0) @ x_ax, (p1 - p0) @ y_ax])
    n = np.array([-v[1], v[0]]) / np.linalg.norm(v)
    n3 = R @ (n[0] * x_ax + n[1] * y_ax)                                # across the track, as in shadow_path
    try:
        pts = []
        for t in (et - 30.0, et + 30.0):
            ast = np.asarray(spice.spkpos(tid, t, 'J2000', 'CN', 'EARTH')[0])
            Rt = spice.pxform('J2000', 'ITRF93', t)
            axis_pt = ast - (ast @ z_ax) * z_ax                        # as shadow_path: the point's own light time
            pts.append(np.asarray(ground_point(axis_pt, ast, bary_velocity(tid, t, ast), z_ax, Rt, (a, a, c))))
        along = pts[1] - pts[0]
        along -= (along @ up) * up
        across = np.cross(up, along)                                    # left of the ground motion
        if across @ n3 < 0:                                             # the A side, as the plane's
            across = -across
    except NotFoundError:
        across = n3 - (n3 @ up) * up
    across /= np.linalg.norm(across)
    toward_star = zf - sin_alt * up                                     # horizontal, length cos(alt)
    return float(h_km / sin_alt * (toward_star @ across))


# Math: FP.3 (slide FP): the plane is perpendicular to the star, not level: a site g from the center line on the
# ground, across the track, is g / k in the plane; k = 1 / sqrt(1 - (n . u)^2), between 1 and 1 / sin(star altitude).
def ground_scale(v_rel_xy, star_dir, up):
    """k = ground distance / plane distance for a site: n is the unit vector across the shadow's motion relative to
    the site (in the plane, from v_rel_xy = its (xi, eta) velocity; at the closest approach the site's offset is along
    n), u the site's vertical (J2000). A horizontal step across the ground track changes the plane offset by
    sqrt(1 - (n . u)^2) per km. NaN when the star is too low (k above 60, below ~1 deg) or the shadow does not move."""
    x_ax, y_ax, _ = plane_basis(star_dir)
    v = np.asarray(v_rel_xy, float)
    nv = float(np.hypot(*v))
    if nv < 1e-12:
        return float("nan")
    n3 = (-v[1] * x_ax + v[0] * y_ax) / nv
    u = np.asarray(up, float) / np.linalg.norm(up)
    q = 1.0 - float(n3 @ u) ** 2
    return float(1.0 / np.sqrt(q)) if q > 1.0 / 3600.0 else float("nan")


def site_probability(miss_km, r_km, sigma1_km):
    """Chance (0-1) that the shadow covers a site miss_km from the predicted centre line. The shadow covers +/- r_km
    across the track; the path itself is uncertain across the track with a normal error of sigma1_km (1 sigma).
    Horizons' RSS value is the whole error ellipse, so using it across the track is on the safe side (the chance
    is rather underestimated far from the path and overestimated near it). Without an uncertainty: 1 or 0."""
    import math
    d, r = abs(float(miss_km)), float(r_km)
    if not sigma1_km or sigma1_km <= 0:
        return 1.0 if d <= r else 0.0
    phi = lambda x: 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))
    return max(0.0, min(1.0, phi((r - d) / sigma1_km) - phi((-r - d) / sigma1_km)))


def path_error(target_id, utc_time):
    """The asteroid's plane-of-sky position uncertainty from JPL Horizons at utc_time (quantities 37 and 38):
    dict(sigma3_km = 3-sigma RSS converted to km at the asteroid, smaa_mas / smia_mas = the 1-sigma error ellipse's
    semi-axes (mas), pa_deg = position angle of its major axis, from north through east), the ellipse values None
    where Horizons gives none. None if Horizons has no covariance for the object or the query fails.
    Horizons' Theta is measured from the RA axis (east) towards north, so PA = 90 - Theta (as OccultWatcher shows it).
    A busy Horizons (HTTP 503, e.g. several queries at once) is asked again up to 3 times after a short pause."""
    from astroquery.jplhorizons import Horizons
    from astropy.time import Time
    import time as _time
    try:
        for k in range(4):
            try:
                eph = Horizons(id=str(target_id), id_type='smallbody', location='500',
                               epochs=Time(utc_time, scale='utc').jd).ephemerides(quantities='20,37,38')
                break
            except Exception as e:
                if "503" not in str(e) or k == 3:
                    raise
                _time.sleep(1.5 * (k + 1))
        names = list(eph.colnames)
        col = next((c for c in names if 'RSS' in c.upper()), None) or \
              next((c for c in names if '3SIGMA' in c.upper() or 'POS' in c.upper()), None)
        if col is None:
            raise KeyError(f"no 3-sigma position column among {names}")
        rss_arcsec = float(eph[col][0])
        delta_km = float(eph['delta'][0]) * AU_KM
        out = dict(sigma3_km=rss_arcsec * np.pi / 648000.0 * delta_km, smaa_mas=None, smia_mas=None, pa_deg=None)
        try:
            out.update(smaa_mas=float(eph['SMAA_3sigma'][0]) / 3 * 1000, smia_mas=float(eph['SMIA_3sigma'][0]) / 3 * 1000,
                       pa_deg=(90.0 - float(eph['Theta_3sigma'][0])) % 180.0)
        except (KeyError, ValueError, TypeError):
            pass
        return out
    except Exception as e:                                              # optional lookup: report and fall back
        print(f"No Horizons uncertainty for {target_id}: {e}")
        return None


def path_sigma3_km(target_id, utc_time):
    """3-sigma plane-of-sky position uncertainty (RSS) from Horizons, converted to km at the asteroid; None if
    Horizons has no covariance for the object or the query fails."""
    e = path_error(target_id, utc_time)
    return e["sigma3_km"] if e else None


def write_shadow_kml(paths, filename, title, observer=None, tick_every=10):
    """Write the lines from shadow_path() as KML. observer = (lon_deg, lat_deg) adds a pin.
    Time ticks (UTC, centre-line duration) every tick_every points along the centre line."""
    def line(name, pts, color, width):
        if len(pts) < 2:
            return ""
        coords = " ".join(f"{p[1]:.6f},{p[2]:.6f},0" for p in pts)
        return (f"<Placemark><name>{escape(name)}</name><Style><LineStyle><color>{color}</color>"
                f"<width>{width}</width></LineStyle></Style><LineString><tessellate>1</tessellate>"
                f"<coordinates>{coords}</coordinates></LineString></Placemark>")

    def pin(name, lon, lat, text=""):
        return (f"<Placemark><name>{escape(name)}</name><description>{escape(text)}</description>"
                f"<Point><coordinates>{lon:.6f},{lat:.6f},0</coordinates></Point></Placemark>")

    parts = [line("Centre line", paths['center'], "ff00ff00", 3),             # KML colours are aabbggrr
             line("Shadow limit A", paths['edge_plus'], "ff0000ff", 2),
             line("Shadow limit B", paths['edge_minus'], "ff0000ff", 2),
             line("1-sigma limit A", paths.get('sigma1_plus', []), "ffff66cc", 1),
             line("1-sigma limit B", paths.get('sigma1_minus', []), "ffff66cc", 1),
             line("3-sigma limit A", paths['sigma_plus'], "ff00ffff", 2),
             line("3-sigma limit B", paths['sigma_minus'], "ff00ffff", 2)]
    if paths.get('center_height'):                                          # the center line at the site's height
        parts.append(line(paths.get('center_height_name') or "Center line at site height",
                          paths['center_height'], "ff00aa00", 2))
    if paths.get('satellite_plus'):                                         # known satellite: where its shadow can pass
        parts += [line("Satellite zone A", paths['satellite_plus'], "ffffaa00", 1),
                  line("Satellite zone B", paths['satellite_minus'], "ffffaa00", 1)]
    for label, pts in paths.get('pm_alts') or []:                          # 2-parameter star: other proper motions
        parts.append(line(f"Proper motion {label}", pts, "ffcc66ff", 1))
    for i, (et, lon, lat, dur) in enumerate(paths['center']):
        if i % tick_every == 0:
            parts.append(pin(spice.et2utc(et, 'ISOC', 0)[11:16] + " UTC", lon, lat,
                             f"max duration {dur:.2f} s" if dur else ""))
    if observer is not None:
        parts.append(pin("Observer", observer[0], observer[1]))

    kml = ('<?xml version="1.0" encoding="UTF-8"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
           f"<name>{escape(title)}</name>" + "".join(parts) + "</Document></kml>")
    with open(filename, "w", encoding="utf-8") as f:
        f.write(kml)
    return filename
