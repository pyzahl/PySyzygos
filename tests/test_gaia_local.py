import sys, os, glob, gzip, math, tempfile, numpy as np, pandas as pd
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
from pysyzygos import corridor as C
from pysyzygos import gaia_local as L
rng = np.random.default_rng(3)

# ---------- synthetic path (as in test_corridor): 20 days, ~0.4 deg/day, distance ~2 AU
STEP = 600.0
ets = np.arange(0.0, 20*86400 + STEP, STEP); t = ets/86400.0
u0 = C._unit(100.0, 20.0); e, n = C._basis(u0)
v = u0 + e*np.radians(0.40)*t[:, None] + n*np.radians(0.06)*t[:, None] - e*np.radians(0.004)*t[:, None]**2
U = v/np.linalg.norm(v, axis=1, keepdims=True)
D = (2.0 + 0.15*np.sin(t/7))*C.AU_KM
path = dict(ets=ets, u=U, delta_km=D, step_s=STEP, sun_au=U*0 + np.array([2.6, 0.5, 0.1]), earth_au=U*D[:, None]/C.AU_KM)
plan = C.plan_corridor('X', ets[0], ets[-1], dict(r_max_km=15.0, H=None, G=None), 18.0, 200.0, path=path)
w = np.degrees(plan['margin_km']/D) + plan['pad_arcsec']/3600.0

# ---------- synthetic Gaia: field stars + stars placed just inside / outside the strip + a few high-pm stars
N = 60000
ra = rng.uniform(95, 112, N); dec = rng.uniform(14, 30, N)
k = rng.integers(0, len(U), 3000); f = rng.uniform(-2, 2, 3000)                         # +/- 2 half-widths off the path
eb = np.cross([0, 0, 1.0], U[k]); eb /= np.linalg.norm(eb, axis=1, keepdims=True); nb = np.cross(U[k], eb)
side = np.where((rng.random(3000) < 0.5)[:, None], eb, nb)
P = U[k] + (f*np.radians(w[k]))[:, None]*side; P /= np.linalg.norm(P, axis=1, keepdims=True)
r2, d2 = C._radec(P)
ra = np.concatenate((ra, r2, [10.0, 200.0])); dec = np.concatenate((dec, d2, [-40.0, 60.0]))
M = len(ra)
g = rng.uniform(9, 21, M)
pmra, pmdec = rng.normal(0, 8, M), rng.normal(0, 8, M)
pmra[-2:] = [3000.0, -2500.0]; g[-2:] = [9.0, 12.0]                                     # high-pm, far from the path
ruwe = np.where(rng.random(M) < 0.05, 2.0, 1.0)
nopm = rng.random(M) < 0.03
ruwe[-2:] = 1.0; nopm[-2:] = False
src = pd.DataFrame(dict(solution_id=1, source_id=np.arange(M) + 10**15, ra=ra, dec=dec, parallax=rng.uniform(0.1, 5, M),
                        pmra=pmra, pmdec=pmdec, ruwe=ruwe, phot_g_mean_mag=g, ra_error=0.05, dec_error=0.04,
                        other="x"))
src.loc[nopm, ["pmra", "pmdec", "parallax"]] = np.nan

cdn = tempfile.mkdtemp(); out = tempfile.mkdtemp()
names = []
shuf = src.sample(frac=1, random_state=1)
for i, idx in enumerate(np.array_split(np.arange(M), 3)):
    part = shuf.iloc[idx]
    nm = f"GaiaSource_{i:06d}-{i:06d}.csv.gz"; names.append(nm)
    with gzip.open(os.path.join(cdn, nm), "wt") as fh:
        fh.write("# ECSV header line\n# another\n")
        part.to_csv(fh, index=False, na_rep="null")
downloads = []
L.list_files = lambda timeout=90: [(nm, os.path.getsize(os.path.join(cdn, nm))) for nm in names]
def fake_download(name, dst, tries=4):
    downloads.append(name); open(dst, "wb").write(open(os.path.join(cdn, name), "rb").read())
L._download = fake_download

# ---------- 1. partial catalog is refused, full build, resume does nothing
L.process_file(names[0], out, 18.0) if os.makedirs(out, exist_ok=True) is None else None
import json; json.dump(dict(gmax=18.0, ruwe_max=L.RUWE_MAX, files=names), open(os.path.join(out, "catalog.json"), "w"))
try:
    L.LocalGaia(out); raise SystemExit("partial catalog accepted")
except RuntimeError as ex:
    print("partial refused:", str(ex)[:60])
L.build(out, 18.0, workers=0)
assert L.status(out)["complete"] and len(downloads) == 3
L.build(out, 18.0, workers=0); assert len(downloads) == 3, "resume re-downloaded"
assert not [x for x in os.listdir(out) if x.endswith(".tmp")]

# ---------- 2. filtering
lg = L.LocalGaia(out)
allk = np.concatenate([np.load(os.path.join(out, s + ".npy")) for s in lg.stems])
want = src[(src.phot_g_mean_mag <= 18) & src.pmra.notna() & (src.ruwe < 1.4)]
assert len(allk) == len(want) and set(allk["source_id"]) == set(want.source_id)
assert all((np.diff(np.load(os.path.join(out, s + ".npy"))["source_id"]) > 0).all() for s in lg.stems)
print("kept", len(allk), "of", M)

# ---------- 3. corridor lookup = superset of brute force, and small
cap = 17.0; plan["mag_cap"] = cap
got = lg.corridor_stars(plan)
S = C._unit(want.ra.to_numpy(), want.dec.to_numpy())
ang = np.degrees(np.arccos(np.clip(S @ U.T, -1, 1)))                                   # (stars, samples) deg
inside = (ang <= w[None, :]).any(axis=1) & (want.phot_g_mean_mag.to_numpy() <= cap)
need = set(want.source_id[inside])
print("strip stars (brute force)", len(need), " returned", len(got))
assert need <= set(got.source_id), f"missed {len(need - set(got.source_id))}"
assert len(got) < 3 * len(need) + 10
assert {10**15 + M - 2, 10**15 + M - 1} <= set(got.source_id), "high-pm stars missing"
assert (got.phot_g_mean_mag <= cap).all() and list(got.columns) == L.COLS + ["star_kind", "ruwe", "pos_err", "pm_err"]

# ---------- 4. the candidate scan works on the local stars, cap above gmax is clipped
cands = C.corridor_candidates(plan, local=lg, verbose=True)[1]
assert len(cands) > 0
plan["mag_cap"] = 19.0; assert (lg.corridor_stars(plan).phot_g_mean_mag <= 18.0).all()

# ---------- 5. cells near the pole take the whole band
c = L.cells_near([10.0], [89.7], [0.5]); assert len(c) >= 360, len(c)
c = L.cells_near([359.99], [0.0], [0.05]); assert L.cell_of(0.01, 0.0).item() in c
# ---------- Windows: a file must not be memory-mapped any more when it is renamed into place (WinError 32 there; Linux
# allows it, so check /proc/self/maps at the moment of the rename)
if os.path.exists("/proc/self/maps"):
    real_replace = L.replace_file
    mapped = []
    def checked_replace(src, dst, *a, **k):
        maps = open("/proc/self/maps").read()
        if os.path.abspath(src) in maps:
            mapped.append(src)
        return real_replace(src, dst, *a, **k)
    L.replace_file = checked_replace
    for f in glob.glob(os.path.join(out, "bright_G17.0.v2*")):
        os.remove(f)
    L.BrightIndex(out, 17.0)
    L.replace_file = real_replace
    assert not mapped, f"still memory-mapped while renamed (Windows: WinError 32): {mapped}"
    print("no file mapped at rename: ok")

# ---------- supplement: the stars the main catalog leaves out (RUWE >= 1.4, no parallax/pm), flagged by kind
L.build(out, 18.0, workers=0, supplement=True)
sup_dir = os.path.join(out, L.SUPPLEMENT)
assert L.status(sup_dir)["complete"] and json.load(open(os.path.join(sup_dir, "catalog.json")))["kind"] == "supplement"
sup = np.concatenate([np.load(os.path.join(sup_dir, n[:-len(".csv.gz")] + ".npy")) for n in names])
mainc = np.concatenate([np.load(os.path.join(out, n[:-len(".csv.gz")] + ".npy")) for n in names])
bright = src[src.phot_g_mean_mag <= 18.0]
assert len(sup) + len(mainc) == len(bright), "main + supplement = every star"
assert not set(sup["source_id"].tolist()) & set(mainc["source_id"].tolist())
exp2p = bright[bright.pmra.isna()]
exp_ruwe = bright[bright.pmra.notna() & (bright.ruwe >= L.RUWE_MAX)]
assert (sup["kind"] == L.KIND_2P).sum() == len(exp2p) and (sup["kind"] == L.KIND_RUWE).sum() == len(exp_ruwe)
assert np.all(sup["pmra"][sup["kind"] == L.KIND_2P] == 0) and np.all(sup["ruwe"][sup["kind"] == L.KIND_RUWE] >= 1.4)
assert np.allclose(sup["ra_error"], 0.05)
print("supplement:", len(sup), "stars,", int((sup["kind"] == L.KIND_2P).sum()), "2-parameter")
# proper motions for the 2-parameter stars from UCAC5 / UCAC4 (CDS XMatch, here a stand-in): good partners taken,
# a close neighbour at the wrong 2015 position or with the wrong magnitude rejected, files rewritten
two = sup[sup["kind"] == L.KIND_2P]
good5, good4, wrong = two[:300], two[300:400], two[400:450]
def fake_xmatch(rows, cat, radius_arcsec=3.0, tries=3):
    r = rows.set_index("source_id")
    out = []
    if "ucac5" in cat:
        for s_ in good5["source_id"]:
            if s_ in r.index:
                q = r.loc[s_]
                out.append(dict(source_id=s_, ra=q.ra, dec=q.dec, g=q.g, RAgaia=q.ra + 0.02 / 3600, DEgaia=q.dec,
                                Gmag=q.g + 0.1, pmRAug=-4.0, pmDEug=-13.0, e_pmRAug=1.7, e_pmDEug=1.6))
        for s_ in wrong["source_id"]:                    # a neighbour 1" away, and one 2 mag fainter: both rejected
            if s_ in r.index:
                q = r.loc[s_]
                out.append(dict(source_id=s_, ra=q.ra, dec=q.dec, g=q.g, RAgaia=q.ra, DEgaia=q.dec + 1.0 / 3600,
                                Gmag=q.g, pmRAug=50.0, pmDEug=50.0, e_pmRAug=1, e_pmDEug=1))
                out.append(dict(source_id=s_, ra=q.ra, dec=q.dec, g=q.g, RAgaia=q.ra, DEgaia=q.dec, Gmag=q.g + 2.0,
                                pmRAug=60.0, pmDEug=60.0, e_pmRAug=1, e_pmDEug=1))
    else:
        for s_ in good4["source_id"]:
            if s_ in r.index:
                q = r.loc[s_]                            # J2000 position: 16 years of pm before Gaia's 2016 one
                out.append(dict(source_id=s_, ra=q.ra, dec=q.dec, g=q.g, RAJ2000=q.ra,
                                DEJ2000=q.dec - 10.0 * 16 / 3.6e6, pmRA=0.0, pmDE=10.0, e_pmRA=3.0, e_pmDE=5.0,
                                **{"f.mag": q.g + 0.3, "Vmag": q.g + 0.5}))
    cols = ["source_id", "ra", "dec", "g"]
    return pd.DataFrame(out) if out else pd.DataFrame(columns=cols)
real_xm = L._xmatch
L._xmatch = fake_xmatch
L.BrightIndex(os.path.join(out, L.SUPPLEMENT), 16.0)          # an index to be dropped
stats = L.supplement_pm(out, chunk=137, log=lambda *a: None)
L._xmatch = real_xm
assert stats["ucac5"] == len(good5) and stats["ucac4"] == len(good4), stats
assert L.has_supplement_pm(out) and not L.glob_bright(os.path.join(out, L.SUPPLEMENT))
sup2 = np.concatenate([np.load(os.path.join(out, L.SUPPLEMENT, n[:-len(".csv.gz")] + ".npy")) for n in names])
by = {int(x["source_id"]): x for x in sup2}
x5, x4, xw = by[int(good5["source_id"][0])], by[int(good4["source_id"][0])], by[int(wrong["source_id"][0])]
assert x5["kind"] == L.KIND_2P_UCAC5 and x5["pmra"] == -4.0 and abs(x5["pm_error"] - 1.7) < 1e-6
assert x4["kind"] == L.KIND_2P_UCAC4 and x4["pmdec"] == 10.0 and abs(x4["pm_error"] - 5.0) < 1e-6
assert xw["kind"] == L.KIND_2P and xw["pmra"] == 0, "a wrong partner must be rejected"
assert len(sup2) == len(sup) and sup2.dtype == L.SUPP_DTYPE
# a rerun finds nothing new (only the stars still without are asked) but must keep the totals in catalog.json
L._xmatch = fake_xmatch
stats2 = L.supplement_pm(out, chunk=137, log=lambda *a: None)
L._xmatch = real_xm
assert (stats2["ucac5"], stats2["ucac4"], stats2["none"]) == (stats["ucac5"], stats["ucac4"], stats["none"]), (stats, stats2)
print("supplement pm: UCAC5", stats["ucac5"], "UCAC4", stats["ucac4"], "rejected wrong partners, rerun totals: ok")

# merged lookup: with the supplement (default) its stars come too, flagged; without, the main catalog only
assert L.has_supplement(out)
lg_main, lg_all = L.LocalGaia(out, supplement=False), L.LocalGaia(out, supplement=True)
c0 = lg_main.cone(104.0, 22.0, 3.0)
c1 = lg_all.cone(104.0, 22.0, 3.0)
assert (c0.star_kind == 0).all() and c0.ruwe.isna().all() and len(c1) > len(c0)
extra = c1[c1.star_kind > 0]
assert len(c1) == len(c0) + len(extra) and set(extra.star_kind) <= {L.KIND_RUWE, L.KIND_2P, L.KIND_2P_UCAC5, L.KIND_2P_UCAC4}
assert (extra[extra.star_kind == L.KIND_RUWE].ruwe >= 1.4).all()
s_all = lg_all.corridor_stars(plan)
assert (s_all.star_kind > 0).any() and len(s_all) > len(lg_main.corridor_stars(plan))
assert L.star_flag(L.KIND_RUWE, 1.654) == "RUWE 1.65" and L.star_flag(0) == ""
assert L.star_flag(L.KIND_2P) == "2-param, NO proper motion" and L.star_flag(L.KIND_2P_UCAC5) == "2-param, pm UCAC5"
# position uncertainty at the event: unknown proper motion 10 mas/yr per axis x years; a known one: its error
assert abs(L.star_sigma_mas(L.KIND_2P, 0, 2.2, None, 10.78) - (2.2**2 + 107.8**2) ** 0.5) < 1e-6
assert abs(L.star_sigma_mas(L.KIND_2P_UCAC5, 0, 2.2, 1.7, 10.78) - (2.2**2 + (1.7 * 10.78)**2) ** 0.5) < 1e-6
assert L.star_sigma_mas(L.KIND_RUWE, 1.65, 0.05, None, 10.78) < 2 and L.star_sigma_mas(0, None, None, None, 10) is None
# merged bright index: the same stars along the path, plus the supplement's, with kind and ruwe
mi = L.open_index(out, 16.0, supplement=True)
assert isinstance(mi, L.MergedIndex)
ww = np.full(len(U), 0.3)
a_m, a_all = L.BrightIndex(out, 16.0).near_path(U, ww, 14.0), mi.near_path(U, ww, 14.0)
assert a_all.dtype == L.COMMON_DTYPE and (a_all["kind"] > 0).any() and (a_all["kind"] == 0).sum() == len(a_m)
assert not isinstance(L.open_index(out, 16.0, supplement=False), L.MergedIndex)

# network failures in the ESA build: blocked downloads stop early with a message, a single failure is skipped
import types
real_list, real_proc = L.list_files, L.process_file
fail_dir = tempfile.mkdtemp()
L.list_files = lambda timeout=90: [(f"GaiaSource_{i}.csv.gz", 1) for i in range(6)]
def blocked(name, out_dir, gmax, ruwe_max=None, supplement=False):
    raise OSError("403 Forbidden (proxy)")
L.process_file = blocked
try:
    L.build(fail_dir, 17.0, workers=0)
    raise AssertionError("a fully blocked build must stop")
except RuntimeError as e:
    assert "the first 3 Gaia files all failed" in str(e) and "proxy" in str(e), e
def one_bad(name, out_dir, gmax, ruwe_max=None, supplement=False):
    if name.endswith("_2.csv.gz"):
        raise OSError("timeout")
    open(os.path.join(out_dir, name[:-len(".csv.gz")] + ".npy"), "wb").close()
    return name, 10, 5, 0.1
L.process_file = one_bad
L.build(fail_dir, 17.0, workers=0)                                   # goes on; the failed file is left for a rerun
assert L.status(fail_dir)["done"] == 5 and not L.status(fail_dir)["complete"]
L.list_files, L.process_file = real_list, real_proc
# a proxy's page instead of the S3 listing
import requests
real_get = requests.get
requests.get = lambda *a, **k: types.SimpleNamespace(text="<html>Access denied by policy</html>", raise_for_status=lambda: None)
import importlib.util
spec = importlib.util.spec_from_file_location("gaia_fresh", L.__file__)          # the real list_files (stubbed above)
fresh = importlib.util.module_from_spec(spec); spec.loader.exec_module(fresh)
try:
    fresh.list_files()
    raise AssertionError("an empty listing must raise")
except RuntimeError as e:
    assert "no Gaia source files" in str(e), e
requests.get = real_get
assert [L.pm_source(k) for k in (0, 1, 2, 3, 4, 5)] == ["Gaia DR3", "Gaia DR3", "none", "UCAC5", "UCAC4",
                                                        "UCAC4 epoch to Gaia"]
print("GAIA LOCAL TESTS PASSED")
