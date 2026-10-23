"""Test pysyzygos/paths.py with a stand-in 'spiceypy' that follows the real contract:
surfpt() returns ONLY the point and raises NotFoundError on a miss (as in the user's traceback).
Geometry (ellipsoid intersection, geodetic lon/lat, Earth rotation) is exact; only ephemerides are synthetic."""
import sys, types, importlib.util
import numpy as np

A, C = 6378.137, 6356.7523142           # WGS84-like: oblate Earth
OMEGA = 7.2921159e-5                    # rad/s
ET0 = 8.45e8
D_AST = 1.6e8                           # km
V_EARTH = np.array([12.0, -25.0, 9.0])  # km/s, the Earth's barycentric velocity in the stand-in (not zero, so the test
                                        # sees whether the asteroid's barycentric or relative velocity is used)
C_KMS = 299792.458
star_ra, star_dec = np.radians(70.0), np.radians(10.0)
STAR = np.array([np.cos(star_dec)*np.cos(star_ra), np.cos(star_dec)*np.sin(star_ra), np.sin(star_dec)])


class NotFoundError(Exception):
    pass


def make_stub(xi0, eta0, vxi, veta):
    z = STAR
    x = np.cross([0, 0, 1.0], z); x /= np.linalg.norm(x)
    y = np.cross(z, x)
    s = types.ModuleType('spiceypy')

    def spkpos(tid, et, frame, corr, obs):
        t = et - ET0
        return D_AST * z + (xi0 + vxi*t) * x + (eta0 + veta*t) * y, 0.0

    def spkezr(tid, et, frame, corr, obs):            # barycentric state: velocity = relative + the Earth's
        assert (frame, corr, obs) == ('J2000', 'NONE', '0')
        v = vxi * x + veta * y + V_EARTH
        return np.concatenate([np.zeros(3), v]), 0.0

    def pxform(frm, to, et):                         # ITRF = Rz(+theta) * J2000, theta = OMEGA*(et-ET0)
        th = OMEGA * (et - ET0)
        c, sn = np.cos(th), np.sin(th)
        Rz = np.array([[c, sn, 0], [-sn, c, 0], [0, 0, 1.0]])   # J2000 -> ITRF
        return Rz if (frm, to) == ('J2000', 'ITRF93') else Rz.T

    def bodvrd(body, item, n):
        return n, np.array([A, A, C])

    def surfpt(positn, u, a, b, c):
        v = np.asarray(positn, float); d = np.asarray(u, float); d = d / np.linalg.norm(d)
        S = np.array([1/a**2, 1/b**2, 1/c**2])
        qa = np.sum(S*d*d); qb = 2*np.sum(S*v*d); qc = np.sum(S*v*v) - 1
        disc = qb*qb - 4*qa*qc
        if disc < 0:
            raise NotFoundError("Spice returns not found for function: surfpt")
        t = (-qb - np.sqrt(disc)) / (2*qa)
        if t < 0:
            raise NotFoundError("Spice returns not found for function: surfpt")
        return v + t*d                                # point only, like spiceypy

    def recgeo(p, re, f):
        rp = re*(1-f); lon = np.arctan2(p[1], p[0]); r = np.hypot(p[0], p[1])
        e2 = 1 - (rp/re)**2; lat = np.arctan2(p[2], r*(1-e2))
        for _ in range(20):
            N = re/np.sqrt(1 - e2*np.sin(lat)**2)
            h = r/np.cos(lat) - N
            lat = np.arctan2(p[2], r*(1 - e2*N/(N+h)))
        N = re/np.sqrt(1 - e2*np.sin(lat)**2)
        return lon, lat, r/np.cos(lat) - N

    def et2utc(et, fmt, prec): return "2026-10-03T07:07:33"

    for f in (spkpos, spkezr, pxform, bodvrd, surfpt, recgeo, et2utc):
        setattr(s, f.__name__, f)
    ex = types.ModuleType('spiceypy.utils.exceptions'); ex.NotFoundError = NotFoundError
    ut = types.ModuleType('spiceypy.utils'); ut.exceptions = ex
    s.utils = ut
    sys.modules.update({'spiceypy': s, 'spiceypy.utils': ut, 'spiceypy.utils.exceptions': ex})
    return s, x, y, z


def load_module():
    import os, sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))   # for pysyzygos.version
    spec = importlib.util.spec_from_file_location('pysyzygos_paths', __import__('os').path.join(__import__('os').path.dirname(__import__('os').path.abspath(__file__)), '..', 'src', 'pysyzygos', 'paths.py'))
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


def geodetic_to_xyz(lon_deg, lat_deg, a=A, c=C):
    lon, lat = np.radians(lon_deg), np.radians(lat_deg)
    e2 = 1 - (c/a)**2
    N = a/np.sqrt(1 - e2*np.sin(lat)**2)
    return np.array([N*np.cos(lat)*np.cos(lon), N*np.cos(lat)*np.sin(lon), N*(1-e2)*np.sin(lat)])


def run_case(label, xi0, eta0, vxi, veta, r=2.0, s3=6.0, expect_empty=False, expect_missing=()):
    s, x, y, z = make_stub(xi0, eta0, vxi, veta)
    m = load_module()
    paths = m.shadow_path('4272', STAR, ET0, r, s3)           # defaults: auto span and step
    print(f"\n== {label}: speed {np.hypot(vxi, veta):.2f} km/s, points per line:",
          {k: len(v) for k, v in paths.items()})
    offs = {'center': 0.0, 'edge_plus': r, 'edge_minus': -r, 'sigma1_plus': r+s3/3, 'sigma1_minus': -(r+s3/3),
            'sigma_plus': r+s3, 'sigma_minus': -(r+s3)}
    if expect_empty:
        assert all(len(v) == 0 for v in paths.values()), "expected no points"
        print("   all lines empty, no exception")
        m.write_shadow_kml(paths, '/tmp/empty.kml', 'empty')
        return paths
    for k, v_ in paths.items():
        if k in expect_missing:
            assert len(v_) == 0, f"{k} should miss the Earth entirely but has {len(v_)} points"
        else:
            assert len(v_) >= 3, f"{k} has only {len(v_)} points"

    worst_plane, worst_dur = 0.0, 0.0
    v = np.array([vxi, veta]); nrm = np.array([-v[1], v[0]]) / np.linalg.norm(v)
    for name, off in offs.items():
        for et, lon, lat, dur in paths[name]:
            t = et - ET0
            R = s.pxform('J2000', 'ITRF93', et)
            p_j2000 = R.T @ geodetic_to_xyz(lon, lat)
            # (1) ground point must lie on the offset shadow axis as that point sees it: its own light time is
            #     dtau = (|A| - |A + vb dtau - P|)/c shorter than the geocentre's (the distance to where the point sees
            #     the asteroid), and in that time the asteroid moves with its barycentric velocity vb (relative + the
            #     Earth's), across the star direction
            A_ = s.spkpos('4272', et, 'J2000', 'CN', '399')[0]
            P_ = s.pxform('ITRF93', 'J2000', et) @ geodetic_to_xyz(lon, lat)
            vb = vxi * x + veta * y + V_EARTH
            dtau = 0.0
            for _ in range(5):
                dtau = (np.linalg.norm(A_) - np.linalg.norm(A_ + vb * dtau - P_)) / C_KMS
            want = np.array([xi0 + vxi*t, eta0 + veta*t]) + off*nrm + dtau * np.array([vb @ x, vb @ y])
            got = np.array([p_j2000 @ x, p_j2000 @ y])
            worst_plane = max(worst_plane, np.linalg.norm(got - want))
            # (2) must be the star-facing side
            assert p_j2000 @ z > 0, "point on the far side of the Earth"
            # (3) centre-line duration vs an independent calculation
            if name == 'center':
                p1 = s.pxform('ITRF93', 'J2000', et + 1.0) @ geodetic_to_xyz(lon, lat)
                vg = np.array([(p1 - p_j2000) @ x, (p1 - p_j2000) @ y])
                worst_dur = max(worst_dur, abs(dur - 2*r/np.linalg.norm(v - vg)))
    print(f"   max plane-position error {worst_plane:.2e} km, max duration error {worst_dur:.2e} s")
    assert worst_plane < 1e-6 and worst_dur < 1e-6
    c = paths['center']
    print(f"   centre line covers {c[0][0]-ET0:+.0f} s .. {c[-1][0]-ET0:+.0f} s, duration range "
          f"{min(p[3] for p in c):.3f}..{max(p[3] for p in c):.3f} s")
    return paths


# 1) typical central pass, 6 km/s
p1 = run_case("central pass", xi0=1500.0, eta0=-2500.0, vxi=5.0, veta=3.3)
# 2) slow shadow (1 km/s), as for 70141: span must auto-extend
p2 = run_case("slow shadow", xi0=-800.0, eta0=1200.0, vxi=-0.8, veta=0.6)
# 3) grazing: axis only just inside the limb, so some lines miss the Earth entirely
LIMB = np.sqrt(A**2*np.sin(star_dec)**2 + C**2*np.cos(star_dec)**2)   # N-S semi-axis of the projected silhouette
print(f"projected N-S limb radius {LIMB:.3f} km")
p3 = run_case("grazing pass (axis 5 km inside the limb; +8 km limit line is outside)",
              xi0=0.0, eta0=LIMB-5.0, vxi=7.0, veta=0.0, expect_missing=('sigma_plus',))
# 4) misses the Earth completely
p4 = run_case("complete miss", xi0=-30000.0, eta0=20000.0, vxi=6.0, veta=0.0, expect_empty=True)

# 5) the observer's closest approach (ET0) near the end of the track: the axis is 6000 km past the Earth's centre at
#    ET0, so a span centred on ET0 (1.3 Earth radii, as before) missed the first part of the crossing; the whole
#    crossing from limb to limb must be there (Phaethon 2019-07-29: the path started 3 minutes late)
p5 = run_case("observer near the end of the track", xi0=6000.0, eta0=1000.0, vxi=6.0, veta=0.0)
first, last = p5['center'][0][0] - ET0, p5['center'][-1][0] - ET0
step5 = 100.0 / 6.0
x_limb = np.sqrt(A**2 - 1000.0**2 / (1 - (1 - (C/A)**2) * np.cos(star_dec)**2))   # roughly where the axis meets the limb
print(f"   centre line {first:+.0f} .. {last:+.0f} s; the axis enters near {(-x_limb - 6000) / 6:+.0f} s, leaves near "
      f"{(x_limb - 6000) / 6:+.0f} s")
assert first <= (-x_limb - 6000) / 6 + 2 * step5 + 60, "the path starts late"    # +60 s: limb shape, rough
assert last >= (x_limb - 6000) / 6 - 2 * step5 - 60, "the path ends early"
# explicit half_span: still centred on et_best (as before)
m5 = load_module()
make_stub(6000.0, 1000.0, 6.0, 0.0)
e5 = m5.shadow_path('4272', STAR, ET0, 2.0, 6.0, half_span=0.0, step=1.0)
assert e5['center'] and abs(e5['center'][0][0] - ET0) < 1e-9, "an explicit span must stay on et_best"

# KML for the grazing case: well-formed, and lines with <2 points are dropped
m = load_module()
m.write_shadow_kml(p3, '/tmp/graze.kml', 'Graze & <test>', observer=(-74.006, 40.713))
import xml.etree.ElementTree as ET
root = ET.parse('/tmp/graze.kml').getroot()
ns = {'k': 'http://www.opengis.net/kml/2.2'}
print("\nKML (grazing case): linestrings", len(root.findall('.//k:LineString', ns)),
      "placemarks", len(root.findall('.//k:Placemark', ns)))
# the centre line at the site's height (height_km): its points lie h above the ellipsoid on the shadow axis, and
# height_shift_km equals the separation of the two lines across the ground track, measured on dense lines
s6, x6, y6, z6 = make_stub(1500.0, -2500.0, 5.0, 3.3)
m6 = load_module()
H_KM = 2.0
p6 = m6.shadow_path('4272', STAR, ET0, 2.0, 6.0, half_span=20.0, step=1.0, height_km=H_KM)
assert len(p6['center_height']) == len(p6['center']) > 30
for (et, lon, lat, _), (et0, lon0, lat0, _) in zip(p6['center_height'], p6['center']):
    R = s6.pxform('J2000', 'ITRF93', et)
    # the raised point itself: from lon/lat and the height, back to J2000, then onto the plane
    lo, la = np.radians(lon), np.radians(lat)
    n_ = np.array([np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)])
    p_h = R.T @ (geodetic_to_xyz(lon, lat) + H_KM * n_)
    p_0 = R.T @ geodetic_to_xyz(lon0, lat0)
    assert abs((p_h - p_0) @ x6) < 1e-3 and abs((p_h - p_0) @ y6) < 1e-3, "not on the same axis point"
assert m6.shadow_path('4272', STAR, ET0, 2.0, 6.0, half_span=5.0, step=1.0).keys() == p6.keys() - {'center_height'}
site_lon, site_lat = p6['center'][20][1], p6['center'][20][2]               # a site on the centre line, at ET0
shift = m6.height_shift_km('4272', STAR, ET0, site_lon, site_lat, H_KM)
o = geodetic_to_xyz(site_lon, site_lat)
lo, la = np.radians(site_lon), np.radians(site_lat)
e_ = np.array([-np.sin(lo), np.cos(lo), 0.0]); n_ = np.array([-np.sin(la) * np.cos(lo), -np.sin(la) * np.sin(lo), np.cos(la)])
enu = lambda pts: np.array([[(geodetic_to_xyz(p[1], p[2]) - o) @ e_, (geodetic_to_xyz(p[1], p[2]) - o) @ n_] for p in pts])
Cl, Hl = enu(p6['center']), enu(p6['center_height'])
t = np.array([p[0] for p in p6['center']]) - ET0
fc = [np.polyfit(t, Cl[:, k], 3) for k in (0, 1)]
fh = [np.polyfit(t, Hl[:, k], 3) for k in (0, 1)]
tan = np.array([np.polyval(np.polyder(fc[k]), 0.0) for k in (0, 1)]); tan /= np.linalg.norm(tan)
nrm = np.array([-tan[1], tan[0]])
# the raised line's point nearest the site's centre point: where its offset is perpendicular to the tangent
tt = np.linspace(-20, 20, 40001)
Hp = np.c_[np.polyval(fh[0], tt), np.polyval(fh[1], tt)]
Cp = np.array([np.polyval(fc[0], 0.0), np.polyval(fc[1], 0.0)])
sep = (Hp[np.argmin(np.abs((Hp - Cp) @ tan))] - Cp) @ nrm
print(f"site height shift: function {shift:+.4f} km, measured {abs(sep):.4f} km across")
assert abs(abs(shift) - abs(sep)) < 0.002, (shift, sep)
# the sign: '+' = the edge_plus side (A)
ep = enu(p6['edge_plus'])[20]
assert np.sign(shift) == np.sign((ep - Cp) @ ((Hp[np.argmin(np.abs((Hp - Cp) @ tan))] - Cp))), "sign"
# a site where the star is below 1 deg: None (here the antipode of the centre point)
assert m6.height_shift_km('4272', STAR, ET0, site_lon - 180.0, -site_lat, H_KM) is None
print("height shift: ok")

# chance that the shadow covers a site (site_probability)
P = load_module().site_probability
assert P(0, 5, 0) == 1.0 and P(6, 5, 0) == 0.0                     # no uncertainty: inside or not
assert abs(P(0, 5, 5) - 0.6827) < 1e-3                              # centre, radius = 1 sigma: +/- 1 sigma
assert abs(P(5, 5, 1e-6) - 0.5) < 1e-3                              # exactly on the edge, tiny error: half
assert P(0, 5, 2) > P(3, 5, 2) > P(8, 5, 2) > P(20, 5, 2) > 0      # falls off with the offset
assert P(-3, 5, 2) == P(3, 5, 2)                                    # symmetric
assert P(20, 1, 3) < 1e-6 and 0 <= P(1e9, 1, 1) <= 1
print("site probability: ok")
print("ALL TESTS PASSED")
