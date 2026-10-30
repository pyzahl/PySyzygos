"""screen.py - find the actual occultation events at one site for many asteroids at once (pick tool engine).

For every asteroid (SBDB full-precision elements):
  1. positions every step_s over the window, integrated with the planets (orbits, ~0.01" vs Horizons),
  2. only times when the asteroid is above min_alt at the site and the Sun is below max_sun_alt are searched,
  3. the faintest useful star is set per asteroid by the drop rule (min_drop) and OWC's observability criterion
     (owc_limit: aperture, detection frames, MagAdjust), so small/fast asteroids only search bright stars.
     Durations for these rules use the upper size bound (an H-only size is uncertain by ~1.7x), i.e. an event is
     kept if it CAN be observable,
  4. stars along the visible path come from the bright-star index (gaia_local.BrightIndex),
  5. the corridor candidate scan finds closest approaches to the Earth's centre; each is then solved for the site
     (fundamental plane, observer on the rotating Earth), and kept if the shadow passes within r_max + reach.

Screening accuracy: asteroid positions ~2 km; star proper motion linear (no stellar parallax, like search.py today).
Stars faster than 1500 mas/yr are not searched. Final predictions: search.py with the exact Horizons SPK.

SPICE (not thread-safe): one process at a time per SPICE pool; screen() may run in worker processes, each loading the
kernels itself (load_kernels).
"""
from pysyzygos.version import __version__
import math, os
import pandas as pd
import numpy as np
from pysyzygos import orbits as O
from pysyzygos.corridor import find_candidates, propagate_linear, pad_for_pm, _unit, EARTH_R_KM, GAIA_EPOCH_YEAR

AU_KM = O.AU_KM
from pysyzygos.kernels import KERNELS


def load_kernels(spice, folder="."):
    from pysyzygos.kernels import EARTH_PCK, historic_earth_pck
    from pysyzygos.kernels import LSK, lsk_file
    for k in KERNELS:
        p = lsk_file(folder) if k == LSK else os.path.join(folder, k)          # the newest leap-second kernel
        if not os.path.isfile(p):
            raise FileNotFoundError(f"{p} missing: run  pysyzygos setup --no-gaia  (downloads the kernels)")
        if k == EARTH_PCK and historic_earth_pck(folder):   # before 2000: the historic file, loaded first (lower rank)
            spice.furnsh(historic_earth_pck(folder))
        spice.furnsh(p)


# ----------------------------------------------------------------------------------------------- detection model
def owc_limit(dur_s, opt):
    """OWC's General Observability Criterion: an event is observable if
    StarMag < 5 log10(Aperture_cm) + 2.5 log10(MaxDuration / DetectionFrames) + 8.5 + MagAdjust."""
    return (5 * math.log10(opt["aperture"]) + 2.5 * np.log10(np.maximum(dur_s, 1e-9) / opt["frames"]) + 8.5
            + opt.get("mag_adjust", 0.0))


def airmass(alt_deg):
    """Kasten & Young (1989)."""
    h = np.asarray(alt_deg, float)
    return 1.0 / (np.sin(np.radians(h)) + 0.50572 * (h + 6.07995) ** -1.6364)


def extinction_loss(alt_deg, opt):
    """Extra magnitudes lost to the atmosphere at this altitude, relative to the zenith (0 when extinction is off)."""
    k = opt.get("extinction", 0.0)
    return k * (airmass(alt_deg) - 1.0) if k else 0.0


def drop_cut(min_drop):
    """A drop >= min_drop needs the star no fainter than m_ast + drop_cut (2.54 mag for 0.1)."""
    return -2.5 * math.log10(10 ** (0.4 * min_drop) - 1.0)


def hg_mag(H, G, r_au, delta_au, cos_phase):
    t = np.tan(np.arccos(np.clip(cos_phase, -1, 1)) / 2)
    phi1, phi2 = np.exp(-3.33 * t ** 0.63), np.exp(-1.87 * t ** 1.22)
    return H + 5 * np.log10(r_au * delta_au) - 2.5 * np.log10((1 - G) * phi1 + G * phi2)


# ----------------------------------------------------------------------------------------------- site
class Site:
    def __init__(self, spice, lat_deg, lon_deg, alt_m):
        self.spice = spice
        from pysyzygos import earth                       # WGS84 (GPS) geodetic coordinates
        lat, lon = math.radians(lat_deg), math.radians(lon_deg)
        self.itrf = np.asarray(spice.georec(lon, lat, alt_m / 1000.0, earth.A_KM, earth.F))
        self.up_itrf = np.array([math.cos(lat) * math.cos(lon), math.cos(lat) * math.sin(lon), math.sin(lat)])
        self.lat, self.lon = lat_deg, lon_deg

    def at(self, et):
        """Observer position (km) and local vertical, geocentric J2000, at times et: (T,3), (T,3)."""
        R = np.array([self.spice.pxform("ITRF93", "J2000", float(t)) for t in np.atleast_1d(et)])
        return R @ self.itrf, R @ self.up_itrf


# ----------------------------------------------------------------------------------------------- helpers
def _interp(g, ets, t):
    """Cubic Lagrange interpolation of g (T,3) sampled at the uniform times ets, at times t (k,). Returns (k,3)."""
    step = ets[1] - ets[0]
    x = (np.asarray(t) - ets[0]) / step
    j = np.clip(np.floor(x).astype(int) - 1, 0, len(ets) - 4)
    s = x - j                                                                       # in [1, 2) for interior points
    w = np.stack([-(s - 1) * (s - 2) * (s - 3) / 6, s * (s - 2) * (s - 3) / 2, -s * (s - 1) * (s - 3) / 2,
                  s * (s - 1) * (s - 2) / 6], 1)
    return np.einsum("kq,kqx->kx", w, np.stack([g[j + q] for q in range(4)], 1))


def _plane(sdir):
    """Fundamental-plane basis (x east, y north) for star directions sdir (k,3)."""
    x = np.cross([0.0, 0.0, 1.0], sdir)
    x /= np.linalg.norm(x, axis=1, keepdims=True)
    return x, np.cross(sdir, x)


def solve_site(spice, site, g_of_t, sdir, t0, half_bracket, iters=6, dt=5.0):
    """Closest approach of the shadow axis to the observer, for k candidates at once. g_of_t(t (k,)) -> (k,3) km
    asteroid positions (astrometric geocentric); sdir (k,3). Newton on the plane offset. Returns t, miss (km),
    offset (k,2) east/north at closest approach, relative speed (km/s)."""
    ex, ny = _plane(sdir)

    def off(t):
        o, _ = site.at(t)
        d = g_of_t(t) - o
        return np.stack([np.sum(d * ex, 1), np.sum(d * ny, 1)], 1)

    t = np.asarray(t0, float).copy()
    lo, hi = t - half_bracket, t + half_bracket
    for _ in range(iters):
        p, q = off(t), off(t + dt)
        v = (q - p) / dt
        step = -np.sum(p * v, 1) / np.maximum(np.sum(v * v, 1), 1e-12)
        t = np.clip(t + step, lo, hi)
    p, q = off(t), off(t + dt)
    return t, np.hypot(p[:, 0], p[:, 1]), p, np.hypot(*(q - p).T) / dt


# ----------------------------------------------------------------------------------------------- the screen
# Math: CO.1-CO.4 (slide CO), the pick of slide PS: own orbits, corridor scan, site solve.
def screen(spice, rows, et0, et1, site, index, opt, step_s=600.0, chunk=1000, progress=None):
    """rows: list of dicts with number, name, H, G, D_km, D_max_km, a, e, i, om, w, ma, epoch (JD TDB).
    opt: reach_km, min_alt, max_sun_alt, min_drop, cam_limit, aperture, frames, mag_adjust, extinction. Returns a list of event dicts (one per asteroid/star/time)."""
    ets = np.arange(et0, et1 + step_s, step_s)
    obs, up = site.at(ets)
    sun = np.asarray(spice.spkpos("SUN", ets, "J2000", "LT+S", "EARTH")[0])
    sun_u = sun / np.linalg.norm(sun, axis=1, keepdims=True)
    dark = np.sum(sun_u * up, 1) < math.sin(math.radians(opt["max_sun_alt"]))
    sun_bary = np.asarray(spice.spkpos("SUN", ets, "J2000", "NONE", "0")[0]) / AU_KM
    sin_min = math.sin(math.radians(opt["min_alt"] - 3.0))                          # 3 deg looser than the final test
    pad = pad_for_pm(1500.0, ets)
    years = 2000.0 + ets.mean() / (365.25 * 86400.0) - GAIA_EPOCH_YEAR
    dm_drop = drop_cut(opt["min_drop"])
    events, n_searched = [], 0
    for c0 in range(0, len(rows), chunk):
        part = rows[c0:c0 + chunk]
        el = {k: np.array([r[k] for r in part], float) for k in ("a", "e", "i", "om", "w", "ma", "epoch")}
        r_b, v_b = O.propagate(spice, el, ets)
        g = O.astrometric(spice, r_b, v_b, ets)                                       # (n,T,3) km
        delta = np.linalg.norm(g, axis=2)
        U = g / delta[..., None]
        visible = (np.einsum("ntx,tx->nt", U, up) > sin_min) & dark[None, :]
        visible[:, 1:] |= visible[:, :-1].copy()                                      # one sample of slack each side
        visible[:, :-1] |= visible[:, 1:].copy()
        helio = r_b - sun_bary[None]
        rh = np.linalg.norm(helio, axis=2)
        cos_ph = np.sum(helio * g, 2) / (rh * delta)                               # phase angle at the asteroid
        speed = np.zeros_like(delta)                                                  # geocentric shadow speed, km/s
        speed[:, 1:] = np.linalg.norm(np.diff(U, axis=1), axis=2) / step_s * delta[:, 1:]
        speed[:, 0] = speed[:, 1]
        for k, row in enumerate(part):
            vis = visible[k]
            if not vis.any():
                continue
            m_ast = hg_mag(row["H"], row["G"], rh[k], delta[k] / AU_KM, cos_ph[k])
            # brightest-star rules on the visible part: drop, exposure (with the slowest relative speed ~ v - 0.5).
            # Detectability uses the upper size bound (an H-only size is uncertain by ~1.7x): "can be detectable".
            # No minimum duration here (user, 2026-10-29): any short dip is kept; the final search applies min_dur.
            dur_max = row["D_max_km"] / np.maximum(speed[k][vis] - 0.5, 0.3)
            cap = min(opt["cam_limit"], float(m_ast[vis].max()) + dm_drop, float(owc_limit(dur_max.max(), opt)))
            if cap < 0:
                continue
            margin = EARTH_R_KM + row["D_max_km"] / 2 + opt["reach_km"]
            w = np.degrees(margin / delta[k]) + pad / 3600.0
            idx = np.where(vis)[0]
            stars = index.near_path(U[k][idx], w[idx], cap)
            n_searched += 1
            if len(stars) == 0:
                continue
            sdf = pd.DataFrame({c: stars[c].astype(float) for c in ("ra", "dec", "pmra", "pmdec", "phot_g_mean_mag")})
            sdf["source_id"] = stars["source_id"]
            names = stars.dtype.names or ()
            kinds = stars["kind"] if "kind" in names else np.zeros(len(stars), np.uint8)       # supplement stars
            ruwes = stars["ruwe"] if "ruwe" in names else np.full(len(stars), np.nan)
            path = dict(ets=ets, u=U[k], delta_km=delta[k], step_s=step_s)
            cands = find_candidates(sdf, path, margin)
            if len(cands) == 0:
                continue
            # the site's event can be up to margin/speed (often 10-40 min) from the Earth-centre estimate: keep a candidate
            # if the asteroid is visible (up, Sun low enough) at any sample of its solver window, not only at et_guess;
            # the exact star and Sun altitude at the solved time are checked below (as corridor.solver_bracket_s)
            half = np.clip(1.3 * margin / np.maximum(speed[k][cands.j.to_numpy()], 1e-3), step_s, 4 * 3600.0)
            jg = (cands.et_guess.to_numpy() - ets[0]) / step_s
            j0 = np.clip(np.floor(jg - half / step_s).astype(int), 0, len(ets) - 1)
            j1 = np.clip(np.ceil(jg + half / step_s).astype(int), 0, len(ets) - 1)
            cvis = np.concatenate([[0], np.cumsum(vis)])
            keep = (cvis[j1 + 1] - cvis[j0]) > 0
            cands, half = cands[keep], half[keep]
            if len(cands) == 0:
                continue
            ra, de = propagate_linear(sdf.iloc[cands.star.to_numpy()], years)
            sdir = _unit(ra, de)
            gk = g[k]
            t, miss, offs, vrel = solve_site(spice, site, lambda tt: _interp(gk, ets, tt), sdir,
                                             cands.et_guess.to_numpy(), half)
            r_max = row["D_max_km"] / 2
            for q in np.where(miss <= r_max + opt["reach_km"])[0]:
                o, upv = site.at(t[q])
                star_alt = math.degrees(math.asin(float(sdir[q] @ upv[0])))
                s_ = np.asarray(spice.spkpos("SUN", float(t[q]), "J2000", "LT+S", "EARTH")[0])
                sun_alt = math.degrees(math.asin(float(s_ @ upv[0] / np.linalg.norm(s_))))
                if star_alt < opt["min_alt"] or sun_alt > opt["max_sun_alt"]:
                    continue
                m_s = float(sdf.phot_g_mean_mag.iloc[cands.star.iloc[q]])
                j = int(np.clip(round((t[q] - ets[0]) / step_s), 0, len(ets) - 1))
                m_a = float(m_ast[j])
                drop = 2.5 * math.log10(1 + 10 ** (0.4 * (m_a - m_s)))
                dur = row["D_km"] / max(vrel[q], 1e-6)                                # nominal size
                dur_hi = row["D_max_km"] / max(vrel[q], 1e-6)                         # upper size bound
                margin = float(owc_limit(dur_hi, opt)) - m_s - float(extinction_loss(star_alt, opt))
                if drop < opt["min_drop"] or margin <= 0:
                    continue
                events.append(dict(number=row["number"], spkid=row.get("spkid"), name=row["name"], H=row["H"], et=float(t[q]),
                                   star=int(sdf.source_id.iloc[cands.star.iloc[q]]), star_mag=m_s, star_ra=float(ra[q]),
                                   star_dec=float(de[q]), m_ast=m_a, drop=drop, dur_s=dur, dur_max_s=dur_hi,
                                   D_km=row["D_km"],
                                   D_est=row.get("D_est", False), speed_kms=float(vrel[q]), miss_km=float(miss[q]),
                                   inside=bool(miss[q] <= row["D_km"] / 2), star_alt=star_alt, sun_alt=sun_alt,
                                   mag_margin=margin, cc=row.get("cc"),
                                   star_kind=int(kinds[cands.star.iloc[q]]), star_ruwe=float(ruwes[cands.star.iloc[q]])))
        if progress:
            progress(min(c0 + chunk, len(rows)), len(rows), len(events), n_searched)
    return events
