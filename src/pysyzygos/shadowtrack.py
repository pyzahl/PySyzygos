"""shadowtrack.py - the shadow of an asteroid on the Earth from a few stored numbers (pre-screens).

Per event (asteroid, star, closest approach to the Earth's centre at tc) the shadow axis moves across the
fundamental plane (z towards the star, x east, y north, through the Earth's centre) almost uniformly for the few
minutes to hours it takes to cross the Earth. Stored: the star direction and a quadratic in time

    x(t) = x0 + vx dt + ax dt^2,   y(t) = y0 + vy dt + ay dt^2,   dt = t - tc,   |dt| <= half

(km, km/s, km/s^2), fitted to the integrated orbit at -half, 0, +half, with the largest misfit at 9 points (err, km).
This is the classical idea of Besselian elements (eclipse and occultation geometry), enough to decide which events can be seen from a site or a region:

- site test: the site's position in the plane at the same times (the Earth's rotation from SPICE on a 1-min grid);
  kept if the shadow line passes within radius + reach + err of it with the star up and the Sun down there;
- region test: the ground track of the shadow axis (the plane point projected onto the Earth along the star
  direction, sampled), kept if it touches a lat/lon box widened by radius + reach + half the sample spacing, with
  the star up and the Sun down at that point.
Both are supersets on purpose (loose margins); the pick then computes every kept asteroid exactly.
"""
import math
import numpy as np

OMEGA = 7.2921150e-5                         # Earth's rotation, rad/s (sidereal)
EARTH_R_KM = 6378.137
TOL_KM = 10.0                                # extra margin of the site test (sampling, site height, geoid)
TOL_DEG = 1.0                                # extra margin of the star and Sun altitude limits
N_SAMPLES = 81                               # samples along +-half: site test (segment distances: exact enough)
N_TRACK = 161                                # samples along +-half: ground tracks (vs 1281: none missed, 13 % extra)

# one event of a global pre-screen: 80 bytes
DTYPE = np.dtype([("number", "i4"), ("star", "i8"), ("et", "f8"), ("g", "f4"), ("m_ast", "f4"), ("geo_miss", "f4"),
                  ("sx", "f4"), ("sy", "f4"), ("sz", "f4"), ("x0", "f4"), ("y0", "f4"), ("vx", "f4"), ("vy", "f4"),
                  ("ax", "f4"), ("ay", "f4"), ("half", "f4"), ("r_km", "f4"), ("err", "f4")])


def in_box(lat, lon, box, margin_km):
    """Boolean array: (lat, lon) within the box widened by margin_km (scalar or broadcastable; longitudes wrap)."""
    dlat = margin_km / 111.2
    ok = (lat >= box["lat_min"] - dlat) & (lat <= box["lat_max"] + dlat)
    dlon = margin_km / (111.2 * np.maximum(np.cos(np.radians(lat)), 0.02))
    width = (box["lon_max"] - box["lon_min"]) % 360.0 or (360.0 if box["lon_max"] != box["lon_min"] else 0.0)
    rel = (lon - box["lon_min"]) % 360.0                         # 0..360 east of the box's west edge
    return ok & ((rel <= width + dlon) | (rel >= 360.0 - dlon))


def plane(sdir):
    """Fundamental-plane basis (x east, y north) for star directions sdir (k,3)."""
    x = np.cross([0.0, 0.0, 1.0], sdir)
    x /= np.linalg.norm(x, axis=1, keepdims=True)
    return x, np.cross(sdir, x)


def interp(g, ets, t):
    """Cubic Lagrange interpolation of g (T,3) sampled at the uniform times ets, at times t (any shape) -> (...,3)."""
    t = np.asarray(t, float)
    step = ets[1] - ets[0]
    x = (t.ravel() - ets[0]) / step
    j = np.clip(np.floor(x).astype(int) - 1, 0, len(ets) - 4)
    s = x - j
    w = np.stack([-(s - 1) * (s - 2) * (s - 3) / 6, s * (s - 2) * (s - 3) / 2, -s * (s - 1) * (s - 3) / 2,
                  s * (s - 1) * (s - 2) / 6], 1)
    out = np.einsum("kq,kqx->kx", w, np.stack([g[j + q] for q in range(4)], 1))
    return out.reshape(t.shape + (3,))


def frames(spice, t0, t1, step_s=600.0):
    """Earth orientation and Sun direction on a grid covering t0..t1: dict(ets, rot (T,3,3) J2000->ITRF93,
    sun_u (T,3) geocentric unit vectors)."""
    ets = np.arange(t0 - 2 * step_s, t1 + 3 * step_s, step_s)
    sun = np.asarray(spice.spkpos("10", ets, "J2000", "LT+S", "399")[0])
    rot = np.array([spice.pxform("J2000", "ITRF93", float(t)) for t in ets])
    return dict(ets=ets, rot=rot, sun_u=sun / np.linalg.norm(sun, axis=1, keepdims=True), step=step_s)


# ---------------------------------------------------------------- elements
# Math: PS.1 (slide PS): the shadow elements, a quadratic in time fitted at -half, 0, +half.
def fit(px, py, half):
    """Quadratic elements from plane positions px, py (c,9) at dt = half * linspace(-1, 1, 9). Returns dict of
    x0, y0, vx, vy, ax, ay (c,) and err (c,): the largest misfit (km) at the 9 points."""
    h = half[:, None]
    out = {}
    for a, p in (("x", px), ("y", py)):
        p0, pm, pp = p[:, 4], p[:, 0], p[:, 8]
        out[a + "0"] = p0
        out["v" + a] = (pp - pm) / (2 * half)
        out["a" + a] = (pp - 2 * p0 + pm) / (2 * half * half)
    dt = h * np.linspace(-1, 1, 9)[None, :]
    ex = px - (out["x0"][:, None] + out["vx"][:, None] * dt + out["ax"][:, None] * dt * dt)
    ey = py - (out["y0"][:, None] + out["vy"][:, None] * dt + out["ay"][:, None] * dt * dt)
    out["err"] = np.sqrt(ex * ex + ey * ey).max(axis=1)
    return out


# Math: PS.1 (slide PS): the shadow axis in the plane from the stored elements.
def positions(ev, tau):
    """Plane positions (c,n) of the shadow axis of events ev (DTYPE array) at times tau (c,n)."""
    dt = tau - ev["et"][:, None]
    f = lambda k: ev[k].astype(float)[:, None]
    return f("x0") + f("vx") * dt + f("ax") * dt * dt, f("y0") + f("vy") * dt + f("ay") * dt * dt


def star_dirs(ev):
    s = np.stack([ev["sx"], ev["sy"], ev["sz"]], 1).astype(float)
    return s / np.linalg.norm(s, axis=1, keepdims=True)


def sample_times(tc, half, n=N_SAMPLES):
    return tc[:, None] + half[:, None] * np.linspace(-1, 1, n)[None, :]


# ---------------------------------------------------------------- ground track (build and region test)
def _track(px, py, tau, sdir, fr, r_km, reach_km, sin_alt, sin_sun, latlon=True):
    """The samples of shadow-axis ground tracks: plane positions px, py (c,s) at times tau (c,s), star directions sdir
    (c,3); fr = frames(). Returns dict: ok (c,s) = on the Earth (or within radius + reach of its limb) with the star
    above and the Sun below the limits; lat, lon (deg; None if not latlon); gs (half step to the neighbours, km);
    star_up, sun_up (sines); r_km (c,1). Every test is widened by what can change between two samples, so a
    continuous track cannot pass a condition between samples, and the sky test by the distance an observer can be from
    the axis (radius + reach: their star and Sun altitudes differ by up to that / R radians): a superset."""
    R = EARTH_R_KM
    ets, rot, sun_u = fr["ets"], fr["rot"], fr["sun_u"]
    ex, ny = plane(sdir)
    r_km = np.broadcast_to(np.asarray(r_km, float), (len(px),))[:, None]
    rho = np.hypot(px, py)
    depth = np.sqrt(np.maximum(R * R - rho * rho, 0.0))                           # towards the star (day side of it)
    scale = np.where(rho > R, R / np.maximum(rho, 1e-9), 1.0)                     # off the limb: the nearest limb point
    s = (px * scale)[..., None] * ex[:, None, :] + (py * scale)[..., None] * ny[:, None, :] \
        + depth[..., None] * sdir[:, None, :]                                      # (c,s,3) J2000, km
    gs = _half_steps(s)                                                            # (c,s) km on the ground
    ps = _half_steps(np.stack([px, py], 2))                                        # (c,s) km in the plane
    on = rho < R + r_km + reach_km + ps
    up = s / np.linalg.norm(s, axis=2, keepdims=True)
    star_up = np.einsum("csx,cx->cs", up, sdir)
    # an observer within radius + reach of the axis IN THE PLANE can be much farther away on the ground (the plane
    # is stretched by 1/sin(star altitude)): the largest ground distance, and their sky differs by up to that / R
    dg = ground_reach(star_up, r_km + reach_km, sin_alt)                           # (c,s) km
    tol = (gs + dg) / R                                                            # radians (>= change of sin(alt))
    i = np.clip(np.round((tau - ets[0]) / fr["step"]).astype(int), 0, len(ets) - 1)
    sun_up = np.einsum("csx,csx->cs", up, sun_u[i])
    out = dict(ok=on & (star_up > sin_alt - tol) & (sun_up < sin_sun + tol), gs=gs, dg=dg, star_up=star_up,
               sun_up=sun_up, r_km=r_km, lat=None, lon=None)
    if latlon:
        ang = OMEGA * (tau - ets[i])                                              # spin since the grid time
        itrf = np.einsum("csij,csj->csi", rot[i], s)
        ca, sa = np.cos(ang), np.sin(ang)
        x, y = ca * itrf[..., 0] + sa * itrf[..., 1], -sa * itrf[..., 0] + ca * itrf[..., 1]
        out["lat"] = np.degrees(np.arcsin(np.clip(itrf[..., 2] / R, -1, 1)))
        out["lon"] = np.degrees(np.arctan2(y, x))
    return out


# Math: RE.1-RE.3 (slide RE): plane reach rho -> largest ground distance; altitude from |proj| = R cos h.
def ground_reach(sin_h, rho_km, sin_min):
    """The largest ground distance (km) between the shadow axis's ground point A, where the star is at altitude h
    (sin_h), and an observer P within rho_km of the axis in the fundamental plane who sees the star at least at
    altitude asin(sin_min). The plane is the orthographic projection along the star: |proj| = R cos(h), so
    cos h_P lies within cos h_A -+ rho/R, which bounds sin h_P; the chord |PA|^2 = (plane distance)^2 + R^2 (sin h_P -
    sin h_A)^2 then bounds the arc. Exact for low stars, where a plane km is many ground km."""
    R = EARTH_R_KM
    q = rho_km / R
    cA = np.sqrt(np.maximum(1.0 - sin_h * sin_h, 0.0))
    c_lo, c_hi = cA - q, cA + q
    s_hi = np.where(c_lo <= 0.0, 1.0, np.sqrt(np.maximum(1.0 - c_lo * c_lo, 0.0)))
    s_lo = np.maximum(np.where(c_hi >= 1.0, -1.0, np.sqrt(np.maximum(1.0 - c_hi * c_hi, 0.0))), sin_min)
    d = np.maximum(np.maximum(s_hi - sin_h, sin_h - s_lo), 0.0)
    chord = np.sqrt(rho_km * rho_km + (R * d) ** 2)
    return 2.0 * R * np.arcsin(np.minimum(chord / (2.0 * R), 1.0))


def ground_track(px, py, tau, sdir, fr, r_km, box, reach_km, sin_alt, sin_sun):
    """keep (c,) and where (c,4: lat, lon, sun alt, star alt of the first matching sample) for shadow-axis ground
    tracks (see _track): kept if a sample passes the sky tests and, with a box, lies inside the box widened by
    radius + reach (+ half the step to the neighbours). box None: no region test. A superset."""
    t = _track(px, py, tau, sdir, fr, r_km, reach_km, sin_alt, sin_sun, latlon=box is not None)
    ok, lat, lon = t["ok"], t["lat"], t["lon"]
    if box is not None:
        ok = ok & in_box(lat, lon, box, t["dg"] + t["gs"])
    first = np.argmax(ok, axis=1)
    c_ = np.arange(len(px))
    if lat is None:
        lat, lon = np.full(px.shape, np.nan), np.full(px.shape, np.nan)
    sun_up, star_up = t["sun_up"], t["star_up"]
    where = np.stack([lat[c_, first], lon[c_, first], np.degrees(np.arcsin(np.clip(sun_up[c_, first], -1, 1))),
                      np.degrees(np.arcsin(np.clip(star_up[c_, first], -1, 1)))], 1)
    return ok.any(axis=1), where


# ---------------------------------------------------------------- the index: a lat/lon box per track
IDX_DTYPE = np.dtype([("lat_lo", "f4"), ("lat_hi", "f4"), ("lon_w", "f4"), ("lon_width", "f4"),
                      ("sin_lo", "f4"), ("sin_hi", "f4")])                       # star altitude range (sines)
POLAR_LAT = 80.0                             # a track reaching beyond this latitude gets all longitudes


def track_bounds(t):
    """Per track (from _track with lat/lon): the latitude range and the longitude arc (west end, width east, deg) of
    its usable samples (ok), each widened by its half step + the ground reach of its observers (ground_reach): IDX_DTYPE values (c,). A track with no usable
    sample gets NaN (no pick can see it); one near a pole, or one whose longitudes are ambiguous (steps between
    samples not much smaller than the largest gap), all longitudes."""
    ok, lat, lon = t["ok"], t["lat"], t["lon"]
    pad = t["gs"] + t["r_km"]                                                      # km: the shadow's own width
    c = len(ok)
    out = np.full(c, np.nan, IDX_DTYPE)
    n = ok.sum(axis=1)
    has = n > 0
    dlat = pad / 111.2
    out["lat_lo"] = np.where(has, np.where(ok, lat - dlat, 999.0).min(axis=1), np.nan)
    out["lat_hi"] = np.where(has, np.where(ok, lat + dlat, -999.0).max(axis=1), np.nan)
    dlon = np.where(ok, pad / (111.2 * np.maximum(np.cos(np.radians(lat)), 0.05)), 0.0).max(axis=1)
    L = np.sort(np.where(ok, lon, np.nan), axis=1)                                 # NaN last
    last = np.clip(n - 1, 0, None)
    rows = np.arange(c)
    gaps = np.diff(L, axis=1)                                                      # between sorted neighbours
    wrap = L[:, 0] + 360.0 - L[rows, last]
    gaps = np.concatenate([np.nan_to_num(gaps, nan=-1.0), wrap[:, None]], axis=1)
    g = np.argmax(gaps, axis=1)
    big = gaps[rows, g]
    is_wrap = g == gaps.shape[1] - 1
    nxt = L[rows, np.clip(g + 1, 0, L.shape[1] - 1)]
    w = np.where(is_wrap, L[:, 0], nxt)
    width = np.where(is_wrap, L[rows, last] - L[:, 0], 360.0 - big)
    # the largest step in time order between usable neighbours (the track passes those longitudes)
    dl = np.abs(((np.diff(lon, axis=1) + 180.0) % 360.0) - 180.0)
    step = np.where(ok[:, 1:] & ok[:, :-1], dl, 0.0).max(axis=1)
    full = (np.maximum(np.abs(out["lat_lo"]), np.abs(out["lat_hi"])) > POLAR_LAT) | (big < 4 * step + 1e-9) | \
        (width + 2 * dlon >= 360.0)
    out["lon_w"] = np.where(has, np.where(full, -180.0, ((w - dlon + 180.0) % 360.0) - 180.0), np.nan)
    out["lon_width"] = np.where(has, np.where(full, 360.0, width + 2 * dlon), np.nan)
    ds = t["gs"] / EARTH_R_KM                                                      # altitude change to a neighbour
    out["sin_lo"] = np.where(has, np.where(ok, t["star_up"] - ds, 9.0).min(axis=1), np.nan)
    out["sin_hi"] = np.where(has, np.where(ok, t["star_up"] + ds, -9.0).max(axis=1), np.nan)
    return out


def _reach_pad(b, rho_km, sin_min, n=33):
    """Per index row: the largest ground distance of an observer within rho_km (plane) of the track, over the
    track's star altitude range (ground_reach on n points + 3 %: it is smooth but not monotonic)."""
    u = np.linspace(0.0, 1.0, n)[None, :]
    sh = b["sin_lo"].astype(float)[:, None] + (b["sin_hi"] - b["sin_lo"]).astype(float)[:, None] * u
    rho = np.broadcast_to(np.asarray(rho_km, float), (len(b),))[:, None]
    return 1.03 * ground_reach(np.clip(sh, -1, 1), rho, sin_min).max(axis=1) + 1.0


def bounds(spice, ev, reach_km, min_alt, max_sun_alt, block=5000):
    """The index (IDX_DTYPE, one per event) of events ev (DTYPE): the box of each track's usable part with the
    build's limits (reach_km, min_alt, max_sun_alt), so every pick or region within those limits is covered."""
    out = np.zeros(len(ev), IDX_DTYPE)
    # the same margins as the site and region tests (TOL_DEG, TOL_KM), so the index never drops what they keep
    sin_alt = math.sin(math.radians(min_alt - TOL_DEG))
    sin_sun = math.sin(math.radians(max_sun_alt + TOL_DEG))
    reach_km = reach_km + TOL_KM
    for b0 in range(0, len(ev), block):
        e = ev[b0:b0 + block]
        tau = sample_times(e["et"], e["half"].astype(float), N_TRACK)
        fr = frames(spice, tau.min(), tau.max())
        px, py = positions(e, tau)
        t = _track(px, py, tau, star_dirs(e), fr, e["r_km"].astype(float) + e["err"].astype(float), reach_km,
                   sin_alt, sin_sun)
        out[b0:b0 + block] = track_bounds(t)
    return out


def near_site(b, ev, lat, lon, reach_km, min_alt):
    """Index rows b (IDX_DTYPE) of events ev whose track box comes near enough to the site that an observer there
    within reach_km (plane) can see the shadow with the star above min_alt: the box widened per event by the ground
    reach over its star altitude range (TOL_KM, TOL_DEG margins as the site test)."""
    km = _reach_pad(b, ev["r_km"].astype(float) + ev["err"].astype(float) + reach_km + TOL_KM,
                    math.sin(math.radians(min_alt - TOL_DEG)))
    dlat = km / 111.2
    edge = np.minimum(np.abs(lat) + dlat, 89.0)
    dlon = km / (111.2 * np.maximum(np.cos(np.radians(edge)), 0.02))
    ok = (b["lat_lo"] - dlat <= lat) & (b["lat_hi"] + dlat >= lat)
    rel = (lon - b["lon_w"]) % 360.0
    return ok & ((rel <= b["lon_width"] + dlon) | (rel >= 360.0 - dlon))


def hits_box(b, ev, box, reach_km, min_alt):
    """Index rows b of events ev whose track box, widened like near_site, overlaps the region box."""
    km = _reach_pad(b, ev["r_km"].astype(float) + ev["err"].astype(float) + reach_km + TOL_KM,
                    math.sin(math.radians(min_alt - TOL_DEG)))
    dlat = km / 111.2
    ok = (b["lat_lo"] - dlat <= box["lat_max"]) & (b["lat_hi"] + dlat >= box["lat_min"])
    edge = np.minimum(np.maximum(np.abs(box["lat_min"]), np.abs(box["lat_max"])) + dlat, 89.0)
    dlon = km / (111.2 * np.maximum(np.cos(np.radians(edge)), 0.02))
    bwidth = (box["lon_max"] - box["lon_min"]) % 360.0 or 360.0
    w = b["lon_w"] - dlon
    width = b["lon_width"] + 2 * dlon
    return ok & ((width >= 360.0) | (bwidth >= 360.0) | ((box["lon_min"] - w) % 360.0 <= width)
                 | ((w - box["lon_min"]) % 360.0 <= bwidth))


def _half_steps(p):
    """Half the distance from each sample to the farther of its neighbours along axis 1: p (c,s,k) -> (c,s)."""
    d = np.linalg.norm(np.diff(p, axis=1), axis=2) if p.shape[1] > 1 else np.zeros((p.shape[0], 0))
    out = np.zeros(p.shape[:2])
    if d.shape[1]:
        out[:, :-1] = d
        out[:, 1:] = np.maximum(out[:, 1:], d)
    return 0.5 * out


def region_mask(spice, ev, box, reach_km, min_alt, max_sun_alt, block=5000):
    """Events (DTYPE array) whose ground track touches the box (see ground_track): keep (c,), where (c,4)."""
    keep, where = np.zeros(len(ev), bool), np.full((len(ev), 4), np.nan)
    if not len(ev):
        return keep, where
    sin_alt = math.sin(math.radians(min_alt - TOL_DEG))
    sin_sun = math.sin(math.radians(max_sun_alt + TOL_DEG))
    for b0 in range(0, len(ev), block):
        e = ev[b0:b0 + block]
        tau = sample_times(e["et"], e["half"].astype(float), N_TRACK)
        fr = frames(spice, tau.min(), tau.max())
        px, py = positions(e, tau)
        r = e["r_km"].astype(float) + e["err"].astype(float)
        keep[b0:b0 + block], where[b0:b0 + block] = ground_track(px, py, tau, star_dirs(e), fr, r, box, reach_km,
                                                                 sin_alt, sin_sun)
    return keep, where


# ---------------------------------------------------------------- site test
# Math: PS.2 (slide PS): the site test, shadow line within r + reach + err of the site, star up, Sun down.
def site_mask(spice, ev, lat, lon, ele_m, reach_km, min_alt, max_sun_alt, block=20000):
    """Events (DTYPE array) whose shadow passes within radius + reach (+ err + TOL_KM) of the site while the star is
    above min_alt and the Sun below max_sun_alt there (limits widened by TOL_DEG). Returns keep (c,)."""
    from pysyzygos import screen as SC
    keep = np.zeros(len(ev), bool)
    if not len(ev):
        return keep
    site = SC.Site(spice, lat, lon, ele_m)
    sin_alt = math.sin(math.radians(min_alt - TOL_DEG))
    sin_sun = math.sin(math.radians(max_sun_alt + TOL_DEG))
    t_lo = float((ev["et"] - ev["half"]).min()) - 120.0
    t_hi = float((ev["et"] + ev["half"]).max()) + 120.0
    grid = np.arange(t_lo - 180.0, t_hi + 240.0, 60.0)                             # site position every minute
    pos, up = site.at(grid)
    sgrid = np.arange(t_lo - 1200.0, t_hi + 1800.0, 600.0)
    sun = np.asarray(spice.spkpos("10", sgrid, "J2000", "LT+S", "399")[0])
    sun /= np.linalg.norm(sun, axis=1, keepdims=True)
    for b0 in range(0, len(ev), block):
        e = ev[b0:b0 + block]
        tau = sample_times(e["et"], e["half"].astype(float))                       # (c,n)
        px, py = positions(e, tau)
        sdir = star_dirs(e)
        ex, ny = plane(sdir)
        S = interp(pos, grid, tau)                                                  # (c,n,3)
        U = interp(up, grid, tau)
        U /= np.linalg.norm(U, axis=2, keepdims=True)
        rx = px - np.einsum("cnx,cx->cn", S, ex)
        ry = py - np.einsum("cnx,cx->cn", S, ny)
        # closest distance on each segment between samples (relative motion linear there)
        ax_, ay_ = rx[:, :-1], ry[:, :-1]
        dx, dy = np.diff(rx, axis=1), np.diff(ry, axis=1)
        u = np.clip(-(ax_ * dx + ay_ * dy) / np.maximum(dx * dx + dy * dy, 1e-12), 0.0, 1.0)
        dist = np.hypot(ax_ + u * dx, ay_ + u * dy)                                 # (c,n-1)
        star_up = np.einsum("cnx,cx->cn", U, sdir)
        sun_up = np.einsum("cnx,cnx->cn", U, interp(sun, sgrid, tau))
        ok_end = (star_up > sin_alt) & (sun_up < sin_sun)
        thr = (e["r_km"].astype(float) + e["err"].astype(float) + reach_km + TOL_KM)[:, None]
        keep[b0:b0 + block] = ((dist <= thr) & (ok_end[:, :-1] | ok_end[:, 1:])).any(axis=1)
    return keep
