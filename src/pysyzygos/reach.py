"""reach.py - the reach measured from the path's n-sigma limit (2026-11-14).

The reach (sites.py reach_km, config max_shadow_dist) is the distance an observer can travel. Before, it counted
from the shadow's edge: an event was kept if the site was within r + reach of the center line. Where the path's
uncertainty is larger than the reach, the shadow may well pass over a site that this missed. Now the reach counts
from the n-sigma limit line (the map's lines at r + n sigma from the center):

    kept if  distance from the center line < r + n * sigma1 + reach        n = 0, 1, 2, 3 (0 = as before)

for every target. A first version (2026-11-14) used it only for targets at least as large as the reach; a Horizons
sample (2026-11-15, 257 numbered asteroids) showed why that was wrong: 3 sigma > 50 km for ~90 % of the main-belt
asteroids below 50 km (median 241 km), all NEOs and Trojans sampled, while the large main-belt ones have ~5 km.
sigma is the path's 1 sigma as the map draws it (Horizons' RSS / 3, with the star's own uncertainty); its part across
the track is smaller (main belt: the error ellipse's minor axis ~0.5 of the major), a later refinement.
The distance from the center line stays as it was in the results (min_distance); the new fields say how far the
site is from the n-sigma limit.
Standard library only (numpy inside pick_widening_km, for arrays).
"""
from pysyzygos.version import __version__

N_MAX = 3
CAP_KM = 5000.0              # a 1-sigma uncertainty above this widens the reach by this only (orbits of no use)
STAR_CAP_MAS = 100.0         # largest star position uncertainty the corridor scan allows for (2-parameter stars)
FAR_AU = 5.5                 # beyond this (or JPL group TNO / 'other': Centaurs etc.) an asteroid is "far": rare
                             # (~1,150 events per 40 days worldwide, 0.005 % of a global pre-screen), its path often
                             # uncertain by more than the Earth (TNOs: 1 sigma 1,300-37,500 km, worst sampled
                             # ~128,000 km), and a wide strip costs nearly nothing there (100,000 km = 5" at 40 AU):
FAR_SIGMA_KM = 150000.0      # the pick's and pre-screens' allowance per sigma for far ones; the search: sigma uncapped
FAR_GROUPS = ("tno", "other")
NEAR_SIGMA_KM = 5000.0       # NEOs, Mars-crossers, Trojans without a sigma-table entry: allowance per sigma (the sample's
                             # largest 1 sigma: NEO 330, Mars-crosser 1,100, Trojan 430 km); with one: 1.5 x its sigma
TABLE_FACTOR = 1.5           # a sigma-table value (sigmatable.py, refreshed monthly) times this: it grows between queries
MAIN = "main"                # the main belt: the one group with a compromise (PICK_SIGMA_MAS, pre-screen edge); ABOUT 2.7.1
PICK_SIGMA_MAS = 200.0       # the pick has no orbit uncertainties: it allows this (asteroid and star together, 1 sigma)
                             # as an angle at the asteroid's distance (2002 XV93: 85 mas); the search applies the real one


def n_sigma(value):
    """n as an integer 0..N_MAX (None, junk -> 0)."""
    try:
        return max(0, min(N_MAX, int(round(float(value)))))
    except (TypeError, ValueError):
        return 0


def applies(n, *_):
    """Whether the n-sigma reach is used: n > 0 (any target; extra arguments of the first version are ignored)."""
    return n > 0


def widening_km(n, sigma1_km, cap_km=CAP_KM):
    """How much farther than r + reach an event may pass: n x the 1-sigma uncertainty (capped); 0 if unknown."""
    try:
        s = float(sigma1_km)
    except (TypeError, ValueError):
        return 0.0
    if not s > 0:
        return 0.0
    return n * min(s, cap_km)


def is_far(a_au=None, group=None, delta_km=None):
    """A far asteroid (FAR_AU): semi-major axis or distance beyond FAR_AU, or JPL group TNO / 'other' (Centaurs).
    An unknown group alone does not count."""
    try:
        if a_au is not None and float(a_au) > FAR_AU:
            return True
        if delta_km is not None and float(delta_km) > FAR_AU * 1.495978707e8:
            return True
    except (TypeError, ValueError):
        pass
    return bool(group) and str(group) in FAR_GROUPS


def cap_for(far, group=None):
    """The cap on sigma for the search's widening: CAP_KM for the main belt only (a few junk orbits); none for any
    other group or a far asteroid (nothing outside the main belt is cut)."""
    if far or (group and str(group) != MAIN):
        return float("inf")
    return CAP_KM


def is_main(group, a_au=None):
    """The main belt (the group with the documented compromise); unknown group: by a (1.78-5.0 AU)."""
    if group:
        return str(group) == MAIN
    try:
        return 1.78 <= float(a_au) <= 5.0
    except (TypeError, ValueError):
        return False


def allowance_km(n, delta_km, group=None, a_au=None, table_sigma1_km=None):
    """The pick's and pre-screens' widening (km) for one asteroid: n x its sigma allowance. Main belt: PICK_SIGMA_MAS at
    the distance (capped; the compromise). Far (TNOs, Centaurs) and near groups (NEOs, Mars-crossers, Trojans):
    TABLE_FACTOR x the sigma table's value when known, else FAR_SIGMA_KM / NEAR_SIGMA_KM. delta_km may be an array."""
    import numpy as np
    d = np.asarray(delta_km, float)
    if n <= 0:
        return 0.0 * d
    if is_main(group, a_au) and not is_far(a_au, group):
        return n * np.minimum(PICK_SIGMA_MAS * np.pi / 648000000.0 * d, CAP_KM)
    if table_sigma1_km is not None and table_sigma1_km == table_sigma1_km and table_sigma1_km > 0:
        return n * TABLE_FACTOR * float(table_sigma1_km) + 0.0 * d
    return n * (FAR_SIGMA_KM if is_far(a_au, group) else NEAR_SIGMA_KM) + 0.0 * d


def pick_widening_km(n, delta_km, far=False):
    """The pick's widening (km) at the asteroid's distance delta_km: n x PICK_SIGMA_MAS there, capped; for a far
    asteroid n x FAR_SIGMA_KM; 0 for n 0. delta_km may be a numpy array."""
    import numpy as np
    d = np.asarray(delta_km, float)
    if n <= 0:
        return 0.0 * d
    if far:
        return n * FAR_SIGMA_KM + 0.0 * d
    return n * np.minimum(PICK_SIGMA_MAS * np.pi / 648000000.0 * d, CAP_KM)


def delta_max_km(a_au, e):
    """An upper bound of the asteroid's distance from the Earth (aphelion + 1 AU), km: for a pre-screen's events,
    which keep no distance."""
    return (float(a_au) * (1.0 + float(e)) + 1.0) * 1.495978707e8


def fields(n, r_km, sigma1_km, min_distance_km, used):
    """The record fields (end of the record): reach_n (the n used; 0 when the rule did not apply), reach_from_km (the
    limit line the reach counts from: r + n sigma1), reach_dist_km (the site's distance beyond it; < 0 = inside)."""
    nn = n if used else 0
    try:
        lim = float(r_km) + nn * float(sigma1_km if nn else 0.0)
        return dict(reach_n=nn, reach_from_km=round(lim, 3), reach_dist_km=round(float(min_distance_km) - lim, 3))
    except (TypeError, ValueError):
        return dict(reach_n=nn, reach_from_km=float("nan"), reach_dist_km=float("nan"))
