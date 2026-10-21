"""corridor.py - all stars an asteroid can occult in one run, from the local Gaia copy, in one vectorized scan.

Why: an asteroid's shadow can only reach the Earth if a star lies within (Earth radius + shadow radius + your travel
reach) of its path, which is a few arcseconds wide. Instead of ~200 overlapping 10' archive cones per asteroid, this module
  1. samples the asteroid's astrometric path once for the whole run (SPICE, same 'CN' convention as the solver),
  2. caps the Gaia magnitude per target: a drop >= min_drop needs  m_star <= m_ast + 2.5*log10(1/(10^(0.4*min_drop)-1))
     (2.54 mag for 0.1), so a 15.5 mag asteroid never needs stars fainter than ~18.5,
  3. takes the stars within margin_km/distance + a proper-motion pad of the path from the local Gaia copy
     (gaia_local.LocalGaia; the Gaia archive was far too slow for this), plus all high-proper-motion stars,
  4. scans all star/time pairs at once (matrix product) and returns the candidates, each with an estimated
     closest-approach time, to be refined by the exact solver (star_test).

Only numpy and pandas are required at import; astropy (propagation) is imported when used, spiceypy only by
asteroid_path() (SPICE is not thread-safe: call it serially).
"""
from pysyzygos.version import __version__
import math
import numpy as np
import pandas as pd

EARTH_R_KM = 6378.137
AU_KM = 149597870.7
GAIA_EPOCH_YEAR = 2016.0


# ----------------------------------------------------------------------------------------------- small geometry
def _unit(ra_deg, dec_deg):
    ra, dec = np.radians(np.asarray(ra_deg, float)), np.radians(np.asarray(dec_deg, float))
    return np.stack((np.cos(dec) * np.cos(ra), np.cos(dec) * np.sin(ra), np.sin(dec)), axis=-1)


def _radec(v):
    v = np.asarray(v, float)
    v = v / np.linalg.norm(v, axis=-1, keepdims=True)
    return np.degrees(np.arctan2(v[..., 1], v[..., 0])) % 360.0, np.degrees(np.arcsin(np.clip(v[..., 2], -1, 1)))


def _basis(c):
    """East and north unit vectors of the tangent plane at unit vector c."""
    e = np.cross([0.0, 0.0, 1.0], c)
    if np.linalg.norm(e) < 1e-9:
        e = np.array([1.0, 0.0, 0.0])
    e = e / np.linalg.norm(e)
    return e, np.cross(c, e)


# ----------------------------------------------------------------------------------------------- magnitude cap
# Math: CO.4 (slide CO): the faintest useful star from the drop rule (+0.5 mag safety).
def limiting_star_mag(H, G, ast_from_sun_au, ast_from_earth_au, mag_limit, min_drop=0.1, safety=0.5):
    """Faintest Gaia G worth querying for this asteroid over the run.

    A drop >= min_drop needs F_star/F_ast >= 10^(0.4*min_drop) - 1, i.e. m_star <= m_ast + dm_cut. The cap uses the
    FAINTEST asteroid magnitude over the run (the largest allowed star magnitude) plus `safety` (H-G is good to
    ~0.3 mag). Returns (cap, m_ast_faintest). With no H the cap is just mag_limit.
    """
    if H is None or not np.isfinite(H) or not min_drop or min_drop <= 0:    # no H, or no drop limit: no cap
        return float(mag_limit), float("nan")
    G = 0.15 if G is None or not np.isfinite(G) else G
    s = np.asarray(ast_from_sun_au, float)
    e = np.asarray(ast_from_earth_au, float)
    r, d = np.linalg.norm(s, axis=1), np.linalg.norm(e, axis=1)
    R = np.linalg.norm(s - e, axis=1)                                   # Sun-Earth distance
    cosa = np.clip((r ** 2 + d ** 2 - R ** 2) / (2 * r * d), -1, 1)
    half = np.tan(np.arccos(cosa) / 2)
    phi1, phi2 = np.exp(-3.33 * half ** 0.63), np.exp(-1.87 * half ** 1.22)
    m = H + 5 * np.log10(r * d) - 2.5 * np.log10((1 - G) * phi1 + G * phi2)
    dm_cut = -2.5 * math.log10(10 ** (0.4 * min_drop) - 1.0)
    return float(min(mag_limit, m.max() + dm_cut + safety)), float(m.max())


# ----------------------------------------------------------------------------------------------- the path
def asteroid_path(target_id, et0, et1, step_s=600.0):
    """Sample the asteroid with SPICE (needs the kernels and the target SPK loaded; call serially).
    Returns dict(ets, u, delta_km, earth_au, sun_au, sun_idx): u = astrometric ('CN') unit vectors from Earth's centre
    at every step; sun_au (Sun -> asteroid, for the brightness only) every 6 h, at the sample indices sun_idx."""
    import spiceypy as spice
    ets = np.arange(et0, et1 + step_s, step_s)
    tid = str(target_id)
    ast = np.asarray(spice.spkpos(tid, ets, "J2000", "CN", "399")[0])
    sun_idx = np.unique(np.append(np.arange(0, len(ets), max(1, int(round(6 * 3600 / step_s)))), len(ets) - 1))
    sun = np.asarray(spice.spkpos(tid, ets[sun_idx], "J2000", "LT", "10")[0])
    delta = np.linalg.norm(ast, axis=1)
    return dict(ets=ets, u=ast / delta[:, None], delta_km=delta, sun_au=sun / AU_KM, earth_au=ast / AU_KM,
                sun_idx=sun_idx, step_s=step_s)


# ----------------------------------------------------------------------------------------------- the plan
# Math: CO.2 (slide CO): the proper-motion pad of the strip, mu_max |t - 2016.0| + 2 arcsec.
def pad_for_pm(pm_pad_mas, ets):
    """Pad (arcsec) so that every star with proper motion <= pm_pad_mas/yr stays inside the strip through the run."""
    last_year = 2000.0 + float(np.max(ets)) / (365.25 * 86400.0)
    return pm_pad_mas / 1000.0 * abs(last_year - GAIA_EPOCH_YEAR) + 2.0


# Math: CO.1, CO.2 (slide CO): margin = Earth radius + r_max + reach; strip half-width per sample.
def plan_corridor(target_id, et0, et1, size, mag_lim, max_shadow_dist, min_drop=0.1, step_s=600.0,
                  pm_pad_mas=1500.0, path=None):
    """Everything that needs SPICE. size needs r_max_km and optional H, G. Strip half-width per path sample:
    margin_km / distance + pad_arcsec (stars faster than pm_pad_mas/yr are added separately, see LocalGaia.high_pm)."""
    path = path or asteroid_path(target_id, et0, et1, step_s)
    k = path.get("sun_idx", slice(None))                                # samples that have the Sun vector
    cap, m_faint = limiting_star_mag(size.get("H"), size.get("G"), path["sun_au"], path["earth_au"][k], mag_lim, min_drop)
    margin_km = EARTH_R_KM + float(size["r_max_km"]) + float(max_shadow_dist)
    pad = pad_for_pm(pm_pad_mas, path["ets"])
    U = path["u"]
    ang = np.degrees(np.arccos(np.clip(np.sum(U[:-1] * U[1:], axis=1), -1, 1)))
    w = np.degrees(margin_km / path["delta_km"]) + pad / 3600.0
    info = dict(path_deg=float(ang.sum()), area_deg2=float(np.sum(ang * (w[:-1] + w[1:]))))
    return dict(target=str(target_id), path=path, mag_cap=cap, m_ast_faint=m_faint, margin_km=margin_km, pad_arcsec=pad,
                info=info, pm_pad_mas=pm_pad_mas, mag_lim=mag_lim, step_s=path["step_s"])


# ----------------------------------------------------------------------------------------------- candidates
def propagate_linear(df, years):
    """Cheap proper-motion propagation for the prefilter (no parallax)."""
    dec = np.radians(df["dec"].to_numpy())
    ra = df["ra"].to_numpy() + df["pmra"].to_numpy() / np.maximum(np.cos(dec), 1e-6) * years / 3.6e6
    de = df["dec"].to_numpy() + df["pmdec"].to_numpy() * years / 3.6e6
    return ra % 360.0, de


# Math: CO.3 (slide CO): the coarse cut at the samples, then the refined minimum (kept below 1.05
# margin).
def find_candidates(stars, path, margin_km, slack=1.05, block_cells=2.5e7):
    """Scan all stars against all path samples at once. Returns a DataFrame with one row per local minimum:
    star (row in `stars`), j (grid index), et_guess (parabolic estimate), d_km (estimated geocentric miss).

    Rule: the plane distance is chord x distance. Between grid samples the asteroid moves v*step, so a star whose true
    miss is `margin` can show up to sqrt(margin^2 + (v*step/2)^2) at the nearest sample; that is the coarse cut, then the
    path is interpolated finely around each surviving minimum to get the miss and the time, kept if below margin*slack.
    """
    ets, U, D, step = path["ets"], path["u"], path["delta_km"], path["step_s"]
    cols = ["star", "j", "et_guess", "d_km"]
    if len(stars) == 0:
        return pd.DataFrame(columns=cols)
    mid_year = 2000.0 + float(ets.mean()) / (365.25 * 86400.0)
    ra, dec = propagate_linear(stars, mid_year - GAIA_EPOCH_YEAR)
    S = _unit(ra, dec)
    ang_speed = np.linalg.norm(np.diff(U, axis=0), axis=1) / step
    vmax = float((ang_speed * 0.5 * (D[:-1] + D[1:])).max()) + 0.5       # km/s, + Earth rotation
    margin_c = math.hypot(margin_km, vmax * step / 2.0)
    n, m = len(S), len(ets)
    block = max(20, int(block_cells // max(n, 1)))
    out = []
    for a in range(0, m, block):
        b = min(m, a + block)
        lo, hi = max(0, a - 1), min(m, b + 1)
        d2 = np.maximum(2.0 - 2.0 * (S @ U[lo:hi].T), 0.0) * (D[lo:hi] ** 2)[None, :]     # squared plane distance (km^2)
        pad_l = np.full((n, 1), np.inf) if lo == 0 else None
        pad_r = np.full((n, 1), np.inf) if hi == m else None
        full = np.hstack([x for x in (pad_l, d2, pad_r) if x is not None])
        # full column c corresponds to grid index (lo - 1 + c) when a left pad was added, else lo + c
        left = 1 if lo == 0 else 0
        idx = np.arange(full.shape[1]) + lo - left
        cmid = full[:, 1:-1]
        is_min = (cmid <= full[:, :-2]) & (cmid < full[:, 2:]) & (cmid < margin_c ** 2)
        js = idx[1:-1]
        keep = (js >= a) & (js < b)
        is_min &= keep[None, :]
        si, cj = np.nonzero(is_min)
        out.extend(zip(si.tolist(), js[cj].tolist()))
    return _refine_candidates(S, U, D, ets, step, np.array(out, dtype=int).reshape(-1, 2), margin_km * slack)


def _refine_candidates(S, U, D, ets, step, pairs, limit_km, n_tau=121, chunk=4000):
    """Exact-ish closest approach for each (star, grid index) pair: quadratic (Lagrange) interpolation of the path through
    j-1, j, j+1 sampled every step/60 s, then a parabola through the three lowest d^2. Keeps d <= limit_km."""
    cols = ["star", "j", "et_guess", "d_km"]
    if len(pairs) == 0:
        return pd.DataFrame(columns=cols)
    m = len(ets)
    tau = np.linspace(-1.0, 1.0, n_tau)
    L = np.stack((tau * (tau - 1) / 2, 1 - tau ** 2, tau * (tau + 1) / 2))            # (3, n_tau) Lagrange weights
    rows = []
    for a in range(0, len(pairs), chunk):
        pr = pairs[a:a + chunk]
        jb = np.clip(pr[:, 1], 1, m - 2)
        Uu = np.stack((U[jb - 1], U[jb], U[jb + 1]), axis=1)                           # (k, 3 pts, 3 xyz)
        Dd = np.stack((D[jb - 1], D[jb], D[jb + 1]), axis=1)                           # (k, 3)
        ut = np.einsum("kpx,pt->ktx", Uu, L)
        ut /= np.linalg.norm(ut, axis=2, keepdims=True)
        dt_ = np.einsum("kp,pt->kt", Dd, L)
        d2 = np.maximum(2.0 - 2.0 * np.einsum("kx,ktx->kt", S[pr[:, 0]], ut), 0.0) * dt_ ** 2
        i0 = np.clip(d2.argmin(axis=1), 1, n_tau - 2)
        k = np.arange(len(pr))
        ym, y0, yp = d2[k, i0 - 1], d2[k, i0], d2[k, i0 + 1]
        den = ym - 2 * y0 + yp
        dl = np.where(den > 0, np.clip(0.5 * (ym - yp) / np.where(den > 0, den, 1.0), -1, 1), 0.0)
        ymin = np.where(den > 0, y0 - 0.25 * (ym - yp) * dl, y0)
        dtau = tau[1] - tau[0]
        t_est = ets[jb] + (tau[i0] + dl * dtau) * step
        d_est = np.sqrt(np.maximum(ymin, 0.0))
        for s_i, j_i, t_i, d_i in zip(pr[:, 0], pr[:, 1], t_est, d_est):
            if d_i <= limit_km:
                rows.append((int(s_i), int(j_i), float(t_i), float(d_i)))
    return pd.DataFrame(rows, columns=cols)


# Math: CO.5 (slide CO): the exact solver's bracket around a candidate, 2 x 1.3 margin / v.
def solver_bracket_s(plan, j, factor=1.3, max_s=4 * 3600.0):
    """Full width (s) of the exact solver's search interval around a candidate at grid index j.

    The scan finds the closest approach to the Earth's CENTRE. The observer is up to margin_km (Earth radius + reach +
    shadow radius) off the centre in the fundamental plane, so the local closest approach can be up to margin_km / v
    earlier or later (v = shadow speed over the plane, ~5-25 km/s: 4-20 min). Never below one grid step either side;
    capped at max_s for near-stationary asteroids."""
    path = plan["path"]
    U, D, step = path["u"], path["delta_km"], path["step_s"]
    j0, j1 = max(int(j) - 1, 0), min(int(j) + 1, len(U) - 1)
    v = np.linalg.norm(U[j1] - U[j0]) / ((j1 - j0) * step) * D[int(j)]          # km/s relative to the Earth's centre
    half = factor * plan["margin_km"] / max(v, 1e-3)
    return 2.0 * float(np.clip(half, step, max_s / 2.0))


# Math: ST1.1 (slide ST1): applies the frame-spin correction (Gaia's own proper motions only).
def gaia_pm(df, pm_bias=True):
    """(pmra*, pmdec) in mas/yr of the stars in df, with Gaia's bright-star proper-motion bias removed when pm_bias
    (astrometry.gaia_pm_bias; G < 13). Proper motions not from Gaia (supplement kinds 3, 4: UCAC5, UCAC4) and rows
    without phot_g_mean_mag stay as they are."""
    pmra, pmdec = df["pmra"].to_numpy(float), df["pmdec"].to_numpy(float)
    if not pm_bias or "phot_g_mean_mag" not in df:
        return pmra, pmdec
    from pysyzygos.astrometry import gaia_pm_bias
    g = df["phot_g_mean_mag"].to_numpy(float).copy()
    if "star_kind" in df:
        g[df["star_kind"].to_numpy() >= 3] = np.nan                  # proper motion from UCAC: no Gaia bias
    return gaia_pm_bias(pmra, pmdec, df["ra"].to_numpy(float), df["dec"].to_numpy(float), g)


# Math: ST1.2 (slide ST1): space motion from J2016.0 (TCB) to the event with astropy/ERFA pmsafe.
def propagate_exact(df, utc_time, pm_bias=True, rv=True):
    """Astropy space motion for the surviving stars only (same recipe as fetch_and_propagate_stars). Adds
    ra_YYYYMMDD / dec_YYYYMMDD. df must have ra, dec, parallax, pmra, pmdec (and phot_g_mean_mag for the
    proper-motion bias correction, gaia_pm; source_id for the radial velocity of fast nearby stars, starrv, which
    adds the perspective acceleration: up to 75 mas by 2026 for Barnard's star; 0 for the others)."""
    import astropy.units as u
    from astropy.coordinates import SkyCoord
    from astropy.time import Time
    t = Time(utc_time, scale="utc")
    plx = np.clip(df["parallax"].fillna(0.0).to_numpy(), 0.01, None)
    pmra, pmdec = gaia_pm(df, pm_bias)
    v_r = np.zeros(len(df))
    if rv and "source_id" in df:
        from pysyzygos.starrv import rv_for
        v_r = rv_for(df["source_id"].to_numpy())
    sc = SkyCoord(ra=df["ra"].values * u.deg, dec=df["dec"].values * u.deg, distance=(1000.0 / plx) * u.pc,
                  pm_ra_cosdec=pmra * u.mas / u.yr, pm_dec=pmdec * u.mas / u.yr, radial_velocity=v_r * u.km / u.s,
                  obstime=Time("2016-01-01T12:00:00", scale="tcb"), frame="icrs")
    new = sc.apply_space_motion(new_obstime=t)
    out = df.copy()
    tag = t.datetime.strftime("%Y%m%d")
    out[f"ra_{tag}"], out[f"dec_{tag}"] = new.ra.deg, new.dec.deg
    return out


# ----------------------------------------------------------------------------------------------- one-call helpers
def corridor_candidates(plan, local, include_high_pm=True, verbose=True):
    """plan -> (stars, candidates). local: a gaia_local.LocalGaia (or anything with corridor_stars(plan,
    include_high_pm) returning Gaia rows at epoch 2016.0). Candidates index into `stars`."""
    stars = local.corridor_stars(plan, include_high_pm)
    cands = find_candidates(stars, plan["path"], plan["margin_km"])
    if verbose:
        i = plan["info"]
        print(f"{plan['target']}: G <= {plan['mag_cap']:.1f}"
              + (f" (asteroid faintest {plan['m_ast_faint']:.1f})" if np.isfinite(plan['m_ast_faint']) else "")
              + f", path {i['path_deg']:.2f} deg, strip {i['area_deg2'] * 3600:.1f} arcmin^2, "
              f"{len(stars)} stars, {len(cands)} candidates")
    return stars, cands
