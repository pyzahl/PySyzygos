"""pysyzygos_astrometry: light deflection and stellar parallax against known values, with a stand-in for SPICE."""
import math, os, sys
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
from pysyzygos import astrometry as A

AU = 1.495978707e8


class FakeSpice:
    """spkpos(target, et, frame, corr, observer) from fixed geocentric positions (km); observer '399' or '0' (SSB)."""
    def __init__(self, geo, earth_ssb=(0.0, 0.0, 0.0)):
        self.geo, self.earth = {k: np.asarray(v, float) for k, v in geo.items()}, np.asarray(earth_ssb, float)

    def spkpos(self, target, et, frame, corr, observer):
        assert frame == "J2000"
        if target == "EARTH" and observer == "0":
            return self.earth, 0.0
        assert observer == "EARTH", observer
        return self.geo[str(target)], 0.0


def star_at(elong_deg):
    """Earth at (1 AU, 0, 0) from the Sun: Earth->Sun = (-1, 0, 0); star at elongation elong in the x-y plane."""
    e = math.radians(elong_deg)
    return np.array([-math.cos(e), math.sin(e), 0.0])


FAR = 1e30                                                # a body/asteroid so far away it does not matter
sun = np.array([-AU, 0.0, 0.0])

# 1) star only (asteroid at infinity along the star: its deflection equals the star's -> use deflect() directly)
d90 = A.deflect(star_at(90), -sun, star_at(90), A.GM[A.SUN])
assert abs(np.linalg.norm(d90) * A.RAD2MAS - 4.07) < 0.01, np.linalg.norm(d90) * A.RAD2MAS
assert np.dot(d90, unit_sun := A.unit(sun)) < 0, "deflection pushes the star away from the Sun"
limb = math.degrees(math.asin(696000.0 / AU))
dl = np.linalg.norm(A.deflect(star_at(limb), -sun, star_at(limb), A.GM[A.SUN])) * A.RAD2MAS / 1000
assert abs(dl - 1.75) < 0.01, dl

# 1b) a source at a finite distance against a literal transcription of IAU SOFA iauLd (p1 = p + w p x (e x q),
#     w = 2GM/(c^2 E) / (1 + q.e)): the asteroid's own deflection (before 2026-10-15 the star form e - (p.e) p was
#     used for it too, wrong where q differs from p)
def sofa_ld(gm, p, q, e, em_km):
    return 2 * gm / A.C_KM_S ** 2 / em_km / max(float(q @ (q + e)), 1e-9) * np.cross(p, np.cross(e, q))
e_hat = np.array([1.0, 0.0, 0.0])
for elong, r_au in ((46.3, 1.0), (60, 2.5), (90, 2.5), (150, 2.5), (120, 1.2)):
    u = star_at(elong)
    b = 2 * float(e_hat @ u); D = (-b + math.sqrt(b * b - 4 * (1 - r_au ** 2))) / 2
    q = A.unit(u * D * AU - sun)
    got, ref = A.deflect(u, -sun, q, A.GM[A.SUN]), sofa_ld(A.GM[A.SUN], u, q, e_hat, AU)
    assert np.linalg.norm(got - ref) * A.RAD2MAS < 1e-9, (elong, got, ref)
assert np.allclose(A.deflect(star_at(70), -sun, star_at(70), A.GM[A.SUN]),
                   sofa_ld(A.GM[A.SUN], star_at(70), star_at(70), e_hat, AU), atol=1e-20)    # star: q = p

# 2) star minus asteroid, main-belt asteroid at r = 2.5 AU on the line of sight (table in ABOUT.md; values with the
#    finite-source formula, 2026-10-15)
for elong, want in ((90, 1.41), (60, 2.22), (150, 0.43)):
    u = star_at(elong)
    e_vec = np.array([1.0, 0.0, 0.0])                     # Sun -> Earth, AU
    b = 2 * float(e_vec @ u); D = (-b + math.sqrt(b * b - 4 * (1 - 2.5 ** 2))) / 2
    fs = FakeSpice({A.SUN: sun, A.JUPITER: [FAR, 0, 0], A.SATURN: [FAR, 0, 0], "AST": u * D * AU})
    p, info = A.corrected_star_dir(fs, u, 0.0, 0.0, "AST", parallax=False)
    assert abs(info["deflection_mas"] - want) < 0.01, (elong, info)
    assert abs(A.angle_mas(u, p) - want) < 0.01

# 3) Jupiter at 4.2 AU, star 60" from its centre, asteroid at 1.5 AU in front: ~6.36 mas
jup_dir = A.unit([0.3, 0.9, 0.1])
perp = A.unit(np.cross(jup_dir, [0, 0, 1]))
u = A.unit(math.cos(math.radians(60 / 3600)) * jup_dir + math.sin(math.radians(60 / 3600)) * perp)
fs = FakeSpice({A.SUN: [FAR, 0, 0], A.JUPITER: jup_dir * 4.2 * AU, A.SATURN: [0, 0, FAR], "AST": u * 1.5 * AU})
p, info = A.corrected_star_dir(fs, u, 0.0, 0.0, "AST", parallax=False)
assert abs(info["deflection_by"]["Jupiter"] - 6.36) < 0.05, info
assert np.dot(p - u, jup_dir) < 0, "pushed away from Jupiter"

# 4) stellar parallax: 1.198 mas at elongation 65.4 deg -> 1.198 x sin(65.4) = 1.09 mas towards the Sun
u = star_at(65.4)
fs = FakeSpice({A.SUN: sun, A.JUPITER: [FAR, 0, 0], A.SATURN: [0, 0, FAR], "AST": u * 2.4 * AU},
               earth_ssb=[AU, 0.0, 0.0])                  # SSB at the Sun: Earth 1 AU from it
p, info = A.corrected_star_dir(fs, u, 1.198, 0.0, "AST", deflection=False)
assert abs(info["parallax_mas"] - 1.198 * math.sin(math.radians(65.4))) < 0.002, info
assert np.dot(p - u, A.unit(sun)) > 0, "parallax moves the star towards the Sun"
for bad in (0.0, -0.5, float("nan"), None):                # no parallax, negative or missing: unchanged
    assert A.angle_mas(A.parallax_dir(u, bad, [AU, 0, 0]), u) == 0.0

# 5) both off: unchanged; both on: about the sum, directions opposite (16556-like case)
p, info = A.corrected_star_dir(fs, u, 1.198, 0.0, "AST", parallax=False, deflection=False)
assert A.angle_mas(p, u) == 0.0 and info["parallax_mas"] == 0.0 and info["deflection_mas"] == 0.0


# 6) Gaia bright-star proper-motion bias: against the paper's own function (Cantat-Gaudin & Brandt 2021,
#    arXiv:2103.07432, Appendix A; copied verbatim apart from the layout)
def edr3ToICRF(pmra, pmdec, ra, dec, G):
    if G >= 13:
        return pmra, pmdec
    def sind(x): return np.sin(np.radians(x))
    def cosd(x): return np.cos(np.radians(x))
    table1 = """ 0.0   9.0     18.4    33.8   -11.3
               9.0   9.5     14.0    30.7   -19.4
               9.5   10.0    12.8    31.4   -11.8
               10.0  10.5    13.6    35.7   -10.5
               10.5  11.0    16.2    50.0    2.1
               11.0  11.5    19.4    59.9    0.2
               11.5  11.75   21.8    64.2    1.0
               11.75 12.0    17.7    65.6    -1.9
               12.0  12.25   21.3    74.8    2.1
               12.25 12.5    25.7    73.6    1.0
               12.5  12.75   27.3    76.6    0.5
               12.75 13.0    34.9    68.9    -2.9 """
    table1 = np.fromstring(table1, sep=' ').reshape((12, 5)).T
    Gmin, Gmax = table1[0], table1[1]
    omegaX = table1[2][(Gmin <= G) & (Gmax > G)][0]
    omegaY = table1[3][(Gmin <= G) & (Gmax > G)][0]
    omegaZ = table1[4][(Gmin <= G) & (Gmax > G)][0]
    pmraCorr = -1 * sind(dec) * cosd(ra) * omegaX - sind(dec) * sind(ra) * omegaY + cosd(dec) * omegaZ
    pmdecCorr = sind(ra) * omegaX - cosd(ra) * omegaY
    return pmra - pmraCorr / 1000., pmdec - pmdecCorr / 1000.


rng = np.random.default_rng(7)
n = 3000
ra_, dec_ = rng.uniform(0, 360, n), np.degrees(np.arcsin(rng.uniform(-1, 1, n)))
g_ = np.concatenate([rng.uniform(3, 15, n - 8), [0.0, 9.0, 11.75, 12.999, 13.0, 8.999, 12.75, 14.0]])
pa_, pd_ = rng.normal(0, 30, n), rng.normal(0, 30, n)
got_a, got_d = A.gaia_pm_bias(pa_, pd_, ra_, dec_, g_)
ref = np.array([edr3ToICRF(pa_[k], pd_[k], ra_[k], dec_[k], g_[k]) for k in range(n)])
assert np.abs(got_a - ref[:, 0]).max() < 1e-12 and np.abs(got_d - ref[:, 1]).max() < 1e-12
a1, d1 = A.gaia_pm_bias([1.0], [2.0], [10.0], [20.0], [np.nan])      # no G: unchanged
assert a1[0] == 1.0 and d1[0] == 2.0
# HIP 24973 (G 7.29): +0.0324 / -0.0124 mas/yr (VERIFICATION.md section 3)
a2, d2 = A.gaia_pm_bias([0.0], [0.0], [80.2280], [40.8848], [7.29])
assert abs(a2[0] - 0.0324) < 2e-4 and abs(d2[0] + 0.0124) < 2e-4, (a2, d2)
# corridor.gaia_pm: only Gaia's proper motions are corrected (supplement kinds 3, 4 carry UCAC5 / UCAC4 ones)
import pandas as pd
from pysyzygos import corridor
df = pd.DataFrame(dict(ra=[80.228] * 4, dec=[40.885] * 4, pmra=[1.0] * 4, pmdec=[1.0] * 4,
                       phot_g_mean_mag=[7.29, 7.29, 7.29, 14.0], star_kind=[0, 1, 3, 0]))
cp, cd = corridor.gaia_pm(df)
assert cp[0] != 1.0 and cp[1] == cp[0] and cp[2] == 1.0 and cp[3] == 1.0, cp
assert np.all(corridor.gaia_pm(df, pm_bias=False)[0] == 1.0)
print("ASTROMETRY TESTS PASSED")
