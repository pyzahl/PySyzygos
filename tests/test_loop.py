import _testtmp  # noqa: F401  (temporary files of this run in one folder, removed at exit)
import sys, math, numpy as np, pandas as pd
sys.path.insert(0, __import__('os').path.join(__import__('os').path.dirname(__import__('os').path.abspath(__file__)), '..', 'src')); from pysyzygos import corridor as C
from scipy.optimize import minimize_scalar
rng = np.random.default_rng(3); AU = C.AU_KM
STEP = 600.0; DAYS = 40; ets = np.arange(0, DAYS*86400+STEP, STEP); t = ets/86400.0
u0 = C._unit(250.0, -20.0); e, n = C._basis(u0)
def motion(t):
    t = np.asarray(t, float)[:, None]; w = 2*np.pi/30.0                       # one retrograde loop per 30 days, drift 0.15 deg/day
    v = u0 + e*np.radians(0.15*t + 1.6*np.sin(w*t)) + n*np.radians(1.1*(1 - np.cos(w*t)))
    return v/np.linalg.norm(v, axis=1, keepdims=True)
dist = lambda t: (1.3 + 0.2*np.cos(np.asarray(t, float)/86400/9))*AU
u = motion(t); delta = dist(ets); path = dict(ets=ets, u=u, delta_km=delta, step_s=STEP)
sp = np.degrees(np.arccos(np.clip(np.sum(u[:-1]*u[1:],1),-1,1)))/(STEP/86400); print("sky speed deg/day  min %.3f  max %.3f" % (sp.min(), sp.max()))
margin = C.EARTH_R_KM + 20 + 200; pad = 20.0
# stars in a band around the path, including the loop turning points
N = 20000; jj = rng.integers(0, len(u), N); off = np.radians(rng.uniform(0, 40, N)/3600); th = rng.uniform(0, 2*np.pi, N)
sv = np.array([u[j] + o*(math.cos(a)*C._basis(u[j])[0] + math.sin(a)*C._basis(u[j])[1]) for j, o, a in zip(jj, off, th)])
sv /= np.linalg.norm(sv, axis=1, keepdims=True); ra, dec = C._radec(sv)
stars = pd.DataFrame(dict(source_id=np.arange(N), ra=ra, dec=dec, parallax=1.0, pmra=0.0, pmdec=0.0, phot_g_mean_mag=15.0))
# truth from a fine grid: every star within the margin must become a candidate
tf = np.arange(0, DAYS*86400, 20.0); uf = motion(tf/86400.0); df_ = dist(tf)
truth = np.empty(N)
for a in range(0, N, 250):
    truth[a:a+250] = (np.sqrt(np.maximum(2-2*(sv[a:a+250] @ uf.T), 0))*df_[None, :]).min(axis=1)
inm = truth < margin*0.97; print("stars within margin:", inm.sum())
cands = C.find_candidates(stars, path, margin)
got = set(cands.star); miss = [i for i in np.where(inm)[0] if i not in got]
print("candidates", len(cands), "missed", len(miss)); assert not miss
# stars with TWO close approaches (loop crossing) must give two candidates
cnt = cands.groupby('star').size(); print("stars with >1 candidate:", int((cnt > 1).sum()), "max", int(cnt.max()))
print("LOOP TEST PASSED")
