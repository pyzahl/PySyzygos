"""astrometry.py - astrometric corrections of a star's direction at an event (see ABOUT.md Part 6).

Gaia DR3 gives barycentric directions free of light deflection. The asteroid comes from SPICE ('CN': light-time
corrected, no aberration, no deflection). Two corrections make the star match what the observer really sees relative
to the asteroid:

  stellar parallax   the star seen from the Earth instead of the solar system barycentre (Gaia parallax > 0 only)
  light deflection   the gravitational bending by the Sun, Jupiter and Saturn. The asteroid's light is bent too,
                     less because it is closer; since the asteroid stays undeflected (SPICE), the star is moved by
                     the difference star minus asteroid, which keeps their relative geometry right.

Deflection of a source in direction p seen from an observer at distance E from a body (unit vector e from the body to
the observer), q = unit vector from the body to the source (q = p for a star), PPN formula for a finite source
(Explanatory Supplement, 3rd ed.; IAU SOFA iauLd):

    dp = (2 GM / c^2 E) * p x (e x q) / (1 + q.e) = (2 GM / c^2 E) * (e (p.q) - q (p.e)) / (1 + q.e)

For a star (q = p) the numerator is e - (p.e) p. Before 2026-10-15 that star form was used for the asteroid too, which
underestimated the asteroid's deflection where q and p differ (Phaethon 2019-07-29: 1.99 instead of 2.43 mas; found
in the comparison with Occult, VERIFICATION.md section 3).

(4.07 mas at elongation 90 deg from the Sun, 1.75" at the solar limb). Pure math; SPICE is passed in, so this module
has no state and the tests can use a stand-in. Used by pysyzygos.handle_star.
"""
from pysyzygos.version import __version__
import numpy as np

C_KM_S = 299792.458
PC_KM = 3.0856775814913673e13
RAD2MAS = np.degrees(1.0) * 3.6e6
# GM, km^3/s^2 (DE440); planets as system barycentres (de440.bsp has them; mas-level deflection is insensitive to it)
# Bodies by NAME, never by a numeric string: searches make asteroid numbers SPICE names (kernels.body_alias), so
# "5", "6", "10", "399" can mean asteroids 5, 6, 10, 399 in a run that has them as targets (found 2026-10-23).
SUN, JUPITER, SATURN = "SUN", "JUPITER BARYCENTER", "SATURN BARYCENTER"
DEFLECTORS = (SUN, JUPITER, SATURN)
GM = {SUN: 1.32712440041279419e11, JUPITER: 1.267127641e8, SATURN: 3.79405848418e7}
BODY_NAMES = {SUN: "Sun", JUPITER: "Jupiter", SATURN: "Saturn"}

# Gaia (E)DR3 proper-motion bias of bright stars: the frame of their proper motions spins against the ICRF by up to
# 80 micro-arcsec/yr for G < 13. Cantat-Gaudin & Brandt 2021, A&A 649, A124 (arXiv:2103.07432), Table 1 and their
# Python function edr3ToICRF (Appendix A): G_min, G_max, omega_X, omega_Y, omega_Z (micro-arcsec/yr).
GAIA_SPIN = np.array([
    (0.0, 9.0, 18.4, 33.8, -11.3), (9.0, 9.5, 14.0, 30.7, -19.4), (9.5, 10.0, 12.8, 31.4, -11.8),
    (10.0, 10.5, 13.6, 35.7, -10.5), (10.5, 11.0, 16.2, 50.0, 2.1), (11.0, 11.5, 19.4, 59.9, 0.2),
    (11.5, 11.75, 21.8, 64.2, 1.0), (11.75, 12.0, 17.7, 65.6, -1.9), (12.0, 12.25, 21.3, 74.8, 2.1),
    (12.25, 12.5, 25.7, 73.6, 1.0), (12.5, 12.75, 27.3, 76.6, 0.5), (12.75, 13.0, 34.9, 68.9, -2.9)])


# Math: ST1.1 (slide ST1): the bright-star frame spin removed from Gaia's proper motions.
def gaia_pm_bias(pmra, pmdec, ra, dec, g):
    """Gaia DR3 proper motions (pmra* = pmra cos dec, pmdec; mas/yr) corrected for the bright-star frame spin
    (Cantat-Gaudin & Brandt 2021, edr3ToICRF, vectorised): unchanged for G >= 13 or a missing G. ra, dec in degrees.
    Only for Gaia's own proper motions (not for proper motions taken from other catalogs)."""
    pmra, pmdec = np.array(pmra, float, ndmin=1), np.array(pmdec, float, ndmin=1)
    ra, dec, g = (np.broadcast_to(np.asarray(v, float), pmra.shape) for v in (ra, dec, g))
    i = np.searchsorted(GAIA_SPIN[:, 1], np.nan_to_num(g, nan=99.0), side="right")    # bin with G_min <= G < G_max
    ok = i < len(GAIA_SPIN)
    wx, wy, wz = (np.where(ok, GAIA_SPIN[np.minimum(i, len(GAIA_SPIN) - 1), k], 0.0) for k in (2, 3, 4))
    sa, ca, sd, cd = np.sin(np.radians(ra)), np.cos(np.radians(ra)), np.sin(np.radians(dec)), np.cos(np.radians(dec))
    corr_ra = -sd * ca * wx - sd * sa * wy + cd * wz
    corr_dec = sa * wx - ca * wy
    return pmra - corr_ra / 1000.0, pmdec - corr_dec / 1000.0


def unit(v):
    v = np.asarray(v, float)
    return v / np.linalg.norm(v)


def angle_mas(a, b):
    """Angle between two unit vectors, mas (accurate for tiny angles)."""
    return float(np.arctan2(np.linalg.norm(np.cross(a, b)), np.dot(a, b)) * RAD2MAS)


# Math: ST2.2 (slide ST2): f(q) times 2GM/(c^2 E) for one body; q = p for the star, q_b for the asteroid.
def deflect(p, obs_from_body_km, q, gm):
    """Deflection vector (to add to p) of a source in direction p (unit), observer at obs_from_body_km from the body,
    q = unit vector from the body to the source (q = p for a star at infinity)."""
    obs = np.asarray(obs_from_body_km, float)
    E = np.linalg.norm(obs)
    e = obs / E
    den = 1.0 + float(np.dot(q, e))
    if den < 1e-12:                                   # source exactly behind the body: not observable anyway
        return np.zeros(3)
    q = np.asarray(q, float)
    return (2.0 * gm / (C_KM_S ** 2 * E)) * (e * float(np.dot(p, q)) - q * float(np.dot(p, e))) / den


# Math: ST2.1 (slide ST2): the star seen from the Earth's centre instead of the barycentre.
def parallax_dir(u_bary, plx_mas, earth_from_ssb_km):
    """The star's direction from the Earth instead of the barycentre (unchanged if the parallax is not > 0)."""
    if not plx_mas or not np.isfinite(plx_mas) or plx_mas <= 0:
        return np.asarray(u_bary, float)
    return unit(np.asarray(u_bary, float) * (1000.0 / plx_mas) * PC_KM - np.asarray(earth_from_ssb_km, float))


# Math: ST2.1-ST2.3 (slide ST2): parallax, deflection star minus asteroid summed over the bodies,
# then the unit vector s used by the solver.
def corrected_star_dir(spice, u_bary, plx_mas, et, target, parallax=True, deflection=True, bodies=DEFLECTORS):
    """(direction, info): the star's corrected J2000 direction at et (unit vector) and the sizes of the corrections,
    info = {'parallax_mas', 'deflection_mas', 'deflection_by': {body: mas}}. target: the asteroid's SPICE name/id."""
    p = unit(u_bary)
    info = {"parallax_mas": 0.0, "deflection_mas": 0.0, "deflection_by": {}}
    if parallax:
        earth = np.asarray(spice.spkpos("EARTH", et, "J2000", "NONE", "0")[0])
        p2 = parallax_dir(p, plx_mas, earth)
        info["parallax_mas"] = angle_mas(p, p2)
        p = p2
    if deflection:
        ast = np.asarray(spice.spkpos(str(target), et, "J2000", "CN", "EARTH")[0])   # Earth -> asteroid (as the solver)
        p0, shift = p, np.zeros(3)
        for b in bodies:
            body = np.asarray(spice.spkpos(b, et, "J2000", "CN", "EARTH")[0])        # Earth -> body
            obs_from_body = -body
            d = deflect(p, obs_from_body, p, GM[b]) - deflect(p, obs_from_body, unit(ast - body), GM[b])
            info["deflection_by"][BODY_NAMES.get(b, b)] = float(np.linalg.norm(d) * RAD2MAS)
            shift += d
        p = unit(p0 + shift)
        info["deflection_mas"] = angle_mas(p0, p)
    return p, info
