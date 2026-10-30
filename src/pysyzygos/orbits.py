"""orbits.py - fast, vectorised asteroid positions from SBDB osculating elements, for screening many asteroids.

Why: Horizons SPKs are exact but one web request per asteroid; a two-body (Kepler) orbit drifts by ~0.5-2' over a few
months, far more than a shadow corridor (~5"). This integrates the elements with the gravity of the Sun and the planets
(DE440 via SPICE), thousands of asteroids at once, and returns astrometric geocentric directions (same 'CN' convention
as the solver). Final predictions still use the exact Horizons SPK (search.py).

Model: barycentric equations of motion, Sun + planet-system barycentres 1-9 (Earth-Moon as EMB), RK4 with a fixed step
(shorter for small perihelion distances: `step_for`), Hermite interpolation between steps, one-step light-time
correction, the Sun's relativistic term (Phaethon, q 0.14 AU: 104 km at the site without it). No asteroid
perturbers, no non-gravitational forces. Not for close Earth approaches (flagged).

Needs spiceypy with an LSK and de440.bsp loaded (call serially: SPICE is not thread-safe).
"""
from pysyzygos.version import __version__
import numpy as np

AU_KM = 149597870.7
OBLIQ_J2000 = np.radians(84381.448 / 3600.0)           # IAU 1976 obliquity: SBDB ecliptic J2000 -> ICRF/J2000
# GM in AU^3/day^2 (DE440): Sun, then planet-system barycentres 1..9
GM_SUN = 2.9591220828411956e-04
GM_BODIES = {1: 4.9125001948893182e-11, 2: 7.2434523326441187e-10, 3: 8.9970116036316091e-10,
             4: 9.5495488297258119e-11, 5: 2.8253458252257917e-07, 6: 8.4597059933762903e-08,
             7: 1.2920265649682399e-08, 8: 1.5243573478851939e-08, 9: 2.1750964648933581e-12}
DAY = 86400.0


def jd_to_et(jd):
    return (np.asarray(jd, float) - 2451545.0) * DAY


def elements_to_state(a, e, i, om, w, ma, epoch_jd):
    """Heliocentric equatorial J2000 state (AU, AU/day) from SBDB heliocentric ecliptic J2000 elements (deg, AU)."""
    a, e = np.asarray(a, float), np.asarray(e, float)
    i, om, w, M = (np.radians(np.asarray(x, float)) for x in (i, om, w, ma))
    E = M + e * np.sin(M)
    for _ in range(30):                                                         # Newton, fine up to e ~ 0.98
        E = E - (E - e * np.sin(E) - M) / (1 - e * np.cos(E))
    cE, sE = np.cos(E), np.sin(E)
    b = a * np.sqrt(1 - e ** 2)
    n = np.sqrt(GM_SUN / a ** 3)
    xp, yp = a * (cE - e), b * sE
    vxp, vyp = -a * n * sE / (1 - e * cE), b * n * cE / (1 - e * cE)
    cO, sO, ci, si, cw, sw = np.cos(om), np.sin(om), np.cos(i), np.sin(i), np.cos(w), np.sin(w)
    P = np.stack([cO * cw - sO * sw * ci, sO * cw + cO * sw * ci, sw * si], -1)        # perifocal -> ecliptic
    Q = np.stack([-cO * sw - sO * cw * ci, -sO * sw + cO * cw * ci, cw * si], -1)
    r = P * xp[..., None] + Q * yp[..., None]
    v = P * vxp[..., None] + Q * vyp[..., None]
    c, s = np.cos(OBLIQ_J2000), np.sin(OBLIQ_J2000)
    R = np.array([[1, 0, 0], [0, c, -s], [0, s, c]])                                  # ecliptic -> equatorial
    return r @ R.T, v @ R.T


def _bodies(spice, et):
    """Barycentric positions (AU) of the Sun and barycentres 1..9 at times et: (T, 10, 3), and their GMs (10,)."""
    ids = [10] + list(GM_BODIES)
    pos = np.stack([np.asarray(spice.spkpos(str(b), et, "J2000", "NONE", "0")[0]) for b in ids], axis=1) / AU_KM
    return pos, np.array([GM_SUN] + list(GM_BODIES.values()))


C_AU_DAY = 299792.458 * DAY / AU_KM                     # speed of light, AU/day


def _accel(r, bp, gm, v=None):
    """r (N,3) barycentric AU; bp (B,3), bp[0] = Sun; gm (B,) -> (N,3) AU/day^2. With v (N,3) AU/day: + the Sun's
    relativistic term (1PN, Schwarzschild, heliocentric r and v; the Sun's own velocity ~0.01 km/s is neglected)."""
    d = r[:, None, :] - bp[None, :, :]
    a = -np.einsum("b,nbk->nk", gm, d / np.linalg.norm(d, axis=2, keepdims=True) ** 3)
    if v is None:
        return a
    rs = d[:, 0]
    rn = np.linalg.norm(rs, axis=1, keepdims=True)
    mu = gm[0]
    return a + mu / (C_AU_DAY ** 2 * rn ** 3) * ((4 * mu / rn - np.sum(v * v, 1, keepdims=True)) * rs
                                                 + 4 * np.sum(rs * v, 1, keepdims=True) * v)


Q_REF_AU = 1.0       # perihelion distance from which on the base step is used


def step_for(a, e, step_days=0.5):
    """RK4 step (days) per asteroid: the base step, halved until it is <= step_days x (q / Q_REF_AU)^1.5 (the orbital
    time scale at perihelion). With 0.5 d for all, an orbit through a perihelion inside ~0.5 AU drifted: Phaethon
    (q 0.14 AU, perihelion 2026-09) 9,200 km off at its 2026-11-02 events, so pick and pre-screens missed them; at
    q 0.17 18,500 km after 120 days. Measured with 0.01 d as reference: no change for q > 0.55 AU."""
    q = np.asarray(a, float) * (1 - np.asarray(e, float))
    ratio = np.clip(q / Q_REF_AU, 1e-3, 1.0) ** 1.5
    return step_days / 2.0 ** np.ceil(np.maximum(-np.log2(ratio), 0.0))


def propagate(spice, el, et_out, step_days=0.5):
    """Barycentric states at the times et_out (s, sorted) for N asteroids with elements el (dict of arrays a, e, i, om,
    w, ma, epoch [JD TDB]). Asteroids are grouped by epoch and step (`step_for`: step_days, shorter for small
    perihelion distances). Returns r, v: (N, T, 3) in AU and AU/day."""
    et_out = np.asarray(et_out, float)
    N, T = len(el["a"]), len(et_out)
    r_out, v_out = np.empty((N, T, 3)), np.empty((N, T, 3))
    steps = step_for(el["a"], el["e"], step_days)
    for ep, step_days in sorted({(float(x), float(h)) for x, h in zip(el["epoch"], steps)}):
        sel = np.where((el["epoch"] == ep) & (steps == step_days))[0]
        rh, vh = elements_to_state(*(el[k][sel] for k in ("a", "e", "i", "om", "w", "ma")), ep)
        et0 = jd_to_et(ep)
        sun = np.asarray(spice.spkezr("SUN", et0, "J2000", "NONE", "0")[0]) / AU_KM
        r, v = rh + sun[:3], vh + sun[3:] * DAY                                     # heliocentric -> barycentric
        # integration grid: from the epoch to every output time, fixed step (sign follows direction)
        t_end = et_out[-1] if abs(et_out[-1] - et0) >= abs(et_out[0] - et0) else et_out[0]
        span = (t_end - et0) / DAY
        n_steps = max(1, int(np.ceil(abs(span) / step_days)))
        lo, hi = min(et0, et_out[0]), max(et0, et_out[-1])
        n_steps = max(n_steps, int(np.ceil((hi - lo) / DAY / step_days)))
        grid = np.linspace(et0, et0 + np.sign(span or 1) * n_steps * step_days * DAY, n_steps + 1) \
            if not (et_out[0] < et0 < et_out[-1]) else None
        if grid is None:                                                             # epoch inside the window: two legs
            raise NotImplementedError("element epoch inside the output window")
        h = (grid[1] - grid[0]) / DAY
        mids = grid[:-1] + 0.5 * (grid[1] - grid[0])
        bp_g, gm = _bodies(spice, grid)
        bp_m, _ = _bodies(spice, mids)
        R, V = [r], [v]
        for k in range(n_steps):                                                     # classic RK4
            a1 = _accel(r, bp_g[k], gm, v)
            r2, v2 = r + 0.5 * h * v, v + 0.5 * h * a1
            a2 = _accel(r2, bp_m[k], gm, v2)
            r3, v3 = r + 0.5 * h * v2, v + 0.5 * h * a2
            a3 = _accel(r3, bp_m[k], gm, v3)
            r4, v4 = r + h * v3, v + h * a3
            a4 = _accel(r4, bp_g[k + 1], gm, v4)
            r = r + h / 6 * (v + 2 * v2 + 2 * v3 + v4)
            v = v + h / 6 * (a1 + 2 * a2 + 2 * a3 + a4)
            R.append(r); V.append(v)
        R, V = np.stack(R, 1), np.stack(V, 1)                                        # (n, steps+1, 3)
        acc = np.stack([_accel(R[:, k], bp_g[k], gm, V[:, k]) for k in range(len(grid))], 1)
        rr, vv = hermite(grid, R, V, acc, et_out)
        r_out[sel], v_out[sel] = rr, vv
    return r_out, v_out


def hermite(grid, R, V, A, t):
    """Quintic Hermite interpolation of positions/velocities (from r, v, a at the grid nodes) at times t."""
    order = np.argsort(grid)
    grid, R, V, A = grid[order], R[:, order], V[:, order], A[:, order]
    k = np.clip(np.searchsorted(grid, t) - 1, 0, len(grid) - 2)
    h = (grid[k + 1] - grid[k]) / DAY
    s = ((t - grid[k]) / DAY / h)[None, :, None]
    h = h[None, :, None]
    p0, p1, v0, v1, a0, a1 = R[:, k], R[:, k + 1], V[:, k] * h, V[:, k + 1] * h, A[:, k] * h * h, A[:, k + 1] * h * h
    s2, s3, s4, s5 = s * s, s ** 3, s ** 4, s ** 5
    H = [1 - 10 * s3 + 15 * s4 - 6 * s5, s - 6 * s3 + 8 * s4 - 3 * s5, 0.5 * (s2 - 3 * s3 + 3 * s4 - s5),
         0.5 * (s3 - 2 * s4 + s5), -4 * s3 + 7 * s4 - 3 * s5, 10 * s3 - 15 * s4 + 6 * s5]
    dH = [(-30 * s2 + 60 * s3 - 30 * s4), (1 - 18 * s2 + 32 * s3 - 15 * s4), 0.5 * (2 * s - 9 * s2 + 12 * s3 - 5 * s4),
          0.5 * (3 * s2 - 8 * s3 + 5 * s4), (-12 * s2 + 28 * s3 - 15 * s4), (30 * s2 - 60 * s3 + 30 * s4)]
    r = H[0] * p0 + H[1] * v0 + H[2] * a0 + H[3] * a1 + H[4] * v1 + H[5] * p1
    v = (dH[0] * p0 + dH[1] * v0 + dH[2] * a0 + dH[3] * a1 + dH[4] * v1 + dH[5] * p1) / h
    return r, v


def astrometric(spice, r_bary, v_bary, et):
    """Astrometric geocentric vectors (km) at times et from barycentric asteroid states (N,T,3) AU / AU/day:
    light-time corrected (asteroid at t - tau), no aberration - the 'CN' convention of the solver."""
    earth = np.asarray(spice.spkpos("EARTH", et, "J2000", "NONE", "0")[0]) / AU_KM      # (T,3)
    g = r_bary - earth[None]
    for _ in range(2):
        tau = np.linalg.norm(g, axis=-1, keepdims=True) * AU_KM / 299792.458 / DAY   # days
        g = r_bary - v_bary * tau - earth[None]
    return g * AU_KM
