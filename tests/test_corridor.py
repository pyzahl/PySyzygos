import sys, math, re, os, tempfile, numpy as np, pandas as pd
sys.path.insert(0, __import__('os').path.join(__import__('os').path.dirname(__import__('os').path.abspath(__file__)), '..', 'src')); from pysyzygos import corridor as C
rng = np.random.default_rng(7)
AU = C.AU_KM

# ---------- synthetic asteroid path: 20 days, ~0.4 deg/day, curved, distance 2 AU
STEP = 600.0; DAYS = 20
ets = np.arange(0.0, DAYS*86400 + STEP, STEP)
t = ets/86400.0
u0 = C._unit(100.0, 20.0)
e, n = C._basis(u0)
def motion(t):
    t = np.asarray(t)[:, None]
    v = u0 + e*np.radians(0.40)*t + n*np.radians(0.06)*t - e*np.radians(0.004)*t**2 + n*np.radians(0.03)*np.sin(t/3)
    return v/np.linalg.norm(v, axis=1, keepdims=True)
u = motion(t)
delta = (2.0 + 0.15*np.sin(t/7))*AU
path = dict(ets=ets, u=u, delta_km=delta, step_s=STEP,
            sun_au=u*delta[:,None]/AU*0 + np.array([2.6,0.5,0.1]), earth_au=u*delta[:,None]/AU)
margin = C.EARTH_R_KM + 15.0 + 200.0
ang = np.degrees(np.arccos(np.clip(np.sum(u[:-1]*u[1:],1),-1,1))).sum(); print("path length deg", round(ang,2))

# ---------- 1. plan: path length and strip area from the half-width margin/distance + pad
pl0 = C.plan_corridor('X', ets[0], ets[-1], dict(r_max_km=15.0, H=None, G=None), 20.0, 200.0, path=path)
w_mean = np.degrees(margin/delta).mean() + pl0['pad_arcsec']/3600.0
print("path deg", round(pl0['info']['path_deg'], 2), "strip arcmin^2", round(pl0['info']['area_deg2']*3600, 1))
assert abs(pl0['info']['path_deg'] - ang) < 1e-9 and abs(pl0['info']['area_deg2'] / (2*w_mean*ang) - 1) < 0.02

# ---------- 2. synthetic Gaia catalogue around the path
N = 30000
jj = rng.integers(0, len(u), N); off = np.radians(rng.uniform(0, 30.0, N)/3600.0); th = rng.uniform(0, 2*np.pi, N)
sv = np.empty((N, 3))
for k in range(N):
    eb, nb = C._basis(u[jj[k]]); sv[k] = u[jj[k]] + off[k]*(math.cos(th[k])*eb + math.sin(th[k])*nb)
sv /= np.linalg.norm(sv, axis=1, keepdims=True)
bg = rng.uniform(-1, 1, (4000, 3)) * 0 + (u[len(u)//2] + rng.normal(0, 0.03, (4000, 3)))   # wide background far from the strip
sv = np.vstack([sv, bg/np.linalg.norm(bg, axis=1, keepdims=True)]); N = len(sv)
ra, dec = C._radec(sv)
cat = pd.DataFrame(dict(source_id=np.arange(N)+1, ra=ra, dec=dec, parallax=rng.uniform(0.1,10,N), pmra=rng.normal(0,15,N), pmdec=rng.normal(0,15,N),
                        phot_g_mean_mag=rng.uniform(8,20,N), ruwe=rng.uniform(0.8,1.3,N)))
hp = rng.choice(N, 40, replace=False); cat.loc[hp,'pmra'] = rng.choice([-1,1],40)*rng.uniform(2000,6000,40)   # high-pm stars
class FakeLocal:                           # stand-in for pysyzygos_gaia_local.LocalGaia: same call, cap applied
    calls = []
    def corridor_stars(self, plan, include_high_pm=True):
        FakeLocal.calls.append(plan['mag_cap'])
        return cat[(cat.phot_g_mean_mag <= plan['mag_cap']) & (cat.ruwe < 1.4)].reset_index(drop=True)
size = dict(r_max_km=15.0, H=12.0, G=0.15)

# ---------- 3. magnitude cap
cap, mf = C.limiting_star_mag(12.0, 0.15, np.array([[2.6,0.5,0.1]]), np.array([[1.5,0.4,0.1]]), 20.0)
print("mag cap", round(cap,2), "asteroid faintest", round(mf,2))
dm = -2.5*math.log10(10**(0.04)-1); assert abs(dm-2.5388) < 1e-3 and abs(cap-(mf+dm+0.5)) < 1e-9
assert C.limiting_star_mag(None, None, np.ones((1,3)), np.ones((1,3))*.5, 18.0) [0] == 18.0
assert C.limiting_star_mag(5.0, 0.15, np.array([[2.6,0.5,0.1]]), np.array([[1.5,0.4,0.1]]), 11.0)[0] == 11.0   # never above the config limit

# ---------- 4. plan + stars from the (stand-in) local catalogue at the plan's cap
plan = C.plan_corridor('X', ets[0], ets[-1], size, 20.0, 200.0, path=path)
print("plan cap", round(plan['mag_cap'], 2))
stars, cands = C.corridor_candidates(plan, FakeLocal())
assert FakeLocal.calls == [plan['mag_cap']] and stars.phot_g_mean_mag.max() <= plan['mag_cap']

# ---------- 5. candidate recall against a brute-force truth at 20 s steps
fine = np.arange(0.0, DAYS*86400, 30.0); tf = fine/86400.0
uf = motion(tf); df_ = (2.0 + 0.15*np.sin(tf/7))*AU
cat_c = cat[cat.phot_g_mean_mag <= plan['mag_cap']].reset_index(drop=True)
ra2, de2 = C.propagate_linear(cat_c, 2000.0 + ets.mean()/(365.25*86400) - 2016.0); S = C._unit(ra2, de2)
truth = np.zeros(len(S)); 
for a in range(0, len(S), 250):
    d = np.sqrt(np.maximum(2-2*(S[a:a+250] @ uf.T), 0))*df_[None,:]; truth[a:a+250] = d.min(axis=1)
want = set(cat_c.source_id[truth < margin*0.97])   # 3% inside the margin: the 30 s truth grid is slightly coarse
got = set(stars.source_id.iloc[cands.star]) if len(cands) else set()
print("truth within margin:", len(want), " candidates:", len(got), " missed:", len(want-got), " false:", len(got-want))
assert len(want) > 20 and not (want - got), "candidates missed stars"
# parabola time guess vs truth for close stars
close = cands.sort_values('d_km').head(5)
for _, row in close.iterrows():
    s = S_i = C._unit(*C.propagate_linear(stars.iloc[[int(row.star)]], 2000.0 + ets.mean()/(365.25*86400) - 2016.0))[0]
    dd = np.sqrt(np.maximum(2-2*(uf @ s),0))*df_; jt0 = fine[dd.argmin()]
    from scipy.optimize import minimize_scalar
    f = lambda tt: float(np.linalg.norm(C._unit(*C._radec(motion([tt/86400.0])[0])) * 0 + (S_i - motion([tt/86400.0])[0])) * (2.0 + 0.15*np.sin(tt/86400.0/7))*AU) if False else \
        float(math.sqrt(max(2 - 2*float(S_i @ motion([tt/86400.0])[0]), 0)) * (2.0 + 0.15*np.sin(tt/86400.0/7))*AU)
    res = minimize_scalar(f, bounds=(jt0-90, jt0+90), method='bounded', options={'xatol': 1e-4}); jt = res.x; dd = np.array([res.fun])
    print(f"  star {int(stars.source_id.iloc[int(row.star)])}: true {dd.min():8.1f} km @ {jt:10.0f} s   est {row.d_km:8.1f} km @ {row.et_guess:10.0f} s")
    assert abs(row.et_guess - jt) < 60 and abs(row.d_km - dd.min()) < 3

# ---------- 6. solver bracket: +/- margin/speed around the geocentric estimate, >= one step, capped
v = np.linalg.norm(u[11] - u[9]) / (2*STEP) * delta[10]
b = C.solver_bracket_s(plan, 10); print("shadow speed %.1f km/s, bracket %.0f s" % (v, b))
assert abs(b - 2*max(STEP, 1.3*plan['margin_km']/v)) < 1e-6
slow = dict(plan, path=dict(path, u=np.repeat(u[:1], len(u), 0) + np.linspace(0, 1e-6, len(u))[:, None]*e))
bs = C.solver_bracket_s(slow, 10); print("near-stationary bracket %.0f s" % bs); assert bs == 4*3600.0
slow2 = dict(plan, path=dict(path, u=(lambda w: w/np.linalg.norm(w, axis=1, keepdims=True))(u0 + np.radians(0.05)*t[:, None]*e)))
v2 = np.linalg.norm(slow2['path']['u'][11] - slow2['path']['u'][9]) / (2*STEP) * delta[10]
b2 = C.solver_bracket_s(slow2, 10); print("slow path %.1f km/s, bracket %.0f s" % (v2, b2))
assert 2*STEP < b2 < 4*3600 and abs(b2 - 2*1.3*plan['margin_km']/v2) < 1e-6
# a deep catalog's path can hold millions of stars: scanned in star blocks, the same candidates
rng = np.random.default_rng(1)
m = 400
ets_b = np.arange(m) * 600.0
ra_b, de_b = np.radians(np.linspace(10, 14, m)), np.radians(np.linspace(5, 6, m))
U_b = np.stack([np.cos(de_b) * np.cos(ra_b), np.cos(de_b) * np.sin(ra_b), np.sin(de_b)], 1)
path_b = dict(ets=ets_b, u=U_b, delta_km=np.full(m, 3e8), step_s=600.0)
nb = 20000
st_b = pd.DataFrame(dict(ra=rng.uniform(9.9, 14.1, nb), dec=rng.uniform(4.95, 6.05, nb), pmra=0.0, pmdec=0.0,
                         phot_g_mean_mag=15.0, source_id=np.arange(nb)))
one = C.find_candidates(st_b, path_b, 8000.0).sort_values(["star", "j"]).reset_index(drop=True)
blk = C.find_candidates(st_b, path_b, 8000.0, block_cells=20 * 777).sort_values(["star", "j"]).reset_index(drop=True)
assert len(one) > 20 and one.equals(blk), (len(one), len(blk))

print("ALL CORRIDOR TESTS PASSED")
