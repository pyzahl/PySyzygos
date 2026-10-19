"""starcat.py (catalog format 2): a build from made-up ESA source files (stand-in download, no network), positions
exact to far below Gaia's precision, the order (cell, then G), lookups against brute force (cone, path strip, fast
movers), the supplement switch, the proper-motion cross-match (stand-in), optional parts (remove, pack, fetch from
'Zenodo' stand-ins), the swap of an upgrade, and no memory map left on a file when it is renamed (Windows)."""
import gzip, json, math, os, shutil, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
import numpy as np
import pandas as pd
from pysyzygos import gaia_local as GL, starcat as SC

rng = np.random.default_rng(7)
N = 30000
ra = rng.uniform(0, 360, N)
dec = np.degrees(np.arcsin(rng.uniform(-1, 1, N)))
ra[:40], dec[:40] = 359.9999999, rng.uniform(-60, 60, 40)                    # at the 0/360 seam
dec[40:50], dec[50:60] = 89.99999, -89.99999                                  # at the poles
ra[60:70], dec[60:70] = 120.0, 30.0                                           # several stars at one point (sort ties)
dense = slice(100, 3100)                                                      # a dense field for the path test
ra[dense], dec[dense] = rng.uniform(80, 82, 3000), rng.uniform(19, 21, 3000)
g = rng.uniform(6, 17.5, N)
pmra, pmdec, plx = rng.normal(0, 20, N), rng.normal(0, 20, N), rng.uniform(0.1, 10, N)
pmra[3200:3210] = 2500.0                                                      # fast movers (hpm)
ruwe = np.where(rng.uniform(0, 1, N) < 0.1, 2.5, 1.0)
two_p = rng.uniform(0, 1, N) < 0.05
df = pd.DataFrame(dict(source_id=np.arange(N, dtype=np.int64) * 1000 + 4295806720, ra=ra, dec=dec,
                       parallax=np.where(two_p, np.nan, plx), pmra=np.where(two_p, np.nan, pmra),
                       pmdec=np.where(two_p, np.nan, pmdec), phot_g_mean_mag=g, ruwe=ruwe))
for c in SC.ERR_COLS:
    df[c] = rng.uniform(0.01, 0.2, N)
for c in SC.CORR_COLS:
    df[c] = rng.uniform(-0.9, 0.9, N)
df["non_single_star"] = np.where(rng.uniform(0, 1, N) < 0.02, 1, 0)
df["ipd_frac_multi_peak"] = rng.integers(0, 10, N)
df["duplicated_source"] = np.where(rng.uniform(0, 1, N) < 0.01, "True", "False")
df["phot_bp_mean_mag"], df["phot_rp_mean_mag"] = g + 0.4, g - 0.5
df["radial_velocity"] = np.where(rng.uniform(0, 1, N) < 0.3, rng.normal(0, 40, N), np.nan)
df["radial_velocity_error"] = np.where(np.isnan(df.radial_velocity), np.nan, 1.5)
df["teff_gspphot"] = rng.uniform(3500, 9000, N)
df["phot_bp_mean_mag"] = df.phot_bp_mean_mag.where(rng.uniform(0, 1, N) > 0.02)  # some without BP
GMAX = 16.0

# three made-up ESA source files; the stand-in download writes one as gzipped CSV like ESA's (# lines, null)
files = [(f"GaiaSource_{k:06d}-{k + 1:06d}.csv.gz", 100) for k in range(3)]
shuffled = df.sample(frac=1, random_state=1)
chunks = {n: shuffled.iloc[i::3] for i, (n, _) in enumerate(files)}
def fake_download(name, dst, tries=4):
    with gzip.open(dst, "wt") as f:
        f.write("# made-up Gaia file\n")
        chunks[name].to_csv(f, index=False, na_rep="null")
GL._download = fake_download

# no file may still be memory-mapped when it is renamed (Windows refuses that)
real_replace = GL.replace_file
def checked_replace(src, dst, *a, **k):
    if os.path.isfile("/proc/self/maps"):
        maps = open("/proc/self/maps").read()
        assert os.path.abspath(src) not in maps, f"{src} still memory-mapped at its rename"
    return real_replace(src, dst, *a, **k)
GL.replace_file = checked_replace

root = tempfile.mkdtemp()
d = os.path.join(root, "gaia_dr3_g16")
st = SC.build(d, GMAX, workers=0, files=files)
keep = df[df.phot_g_mean_mag <= GMAX].set_index("source_id")
assert st["complete"] and st["n_stars"] == len(keep) and st["groups"] == ["core", "quality", "extras"], st
assert not os.path.exists(os.path.join(d, "parts")) and not os.path.exists(os.path.join(d, "build.json"))
assert GL.status(d)["complete"] and GL.find_catalogs(root)[0][0] == "gaia_dr3_g16"

# positions: exact to ~1e-11 deg; G to 0.5 mmag; order: cell, then G
cat = SC.StarCatalog(d, supplement=True)
allrows = cat.frame(np.arange(st["n_stars"]), full=True).set_index("source_id")
assert len(allrows) == len(keep) and allrows.index.is_unique
x = keep.loc[allrows.index]
dra = ((allrows.ra - x.ra + 180) % 360 - 180) * np.cos(np.radians(x.dec))
assert np.abs(dra).max() < 1e-10 and np.abs(allrows.dec - x.dec).max() < 1e-10, (np.abs(dra).max(), np.abs(allrows.dec - x.dec).max())
assert np.abs(allrows.phot_g_mean_mag - x.phot_g_mean_mag).max() <= 0.0005 + 2e-6     # millimag, as float32
cells = np.searchsorted(cat.offsets, np.arange(st["n_stars"]), side="right") - 1
assert (np.diff(cells) >= 0).all()
gg = cat.core["g"]
assert all((np.diff(gg[a:b].astype(int)) >= 0).all() for a, b in zip(cat.offsets[:-1], cat.offsets[1:]) if b - a > 1)
assert (cells == SC.cell_of(allrows.ra.to_numpy(), allrows.dec.to_numpy())).all()

# kinds and the quality / extras columns
kind = np.where(x.pmra.isna(), SC.KIND_2P, np.where(x.ruwe < 1.4, SC.KIND_MAIN, SC.KIND_RUWE))
assert (allrows.star_kind.to_numpy() == kind).all()
assert (allrows.duplicated_source.to_numpy() == (x.duplicated_source == "True").to_numpy()).all()
assert (allrows.non_single_star.to_numpy() == x.non_single_star.to_numpy()).all()
assert np.allclose(allrows.ra_error, x.ra_error, rtol=1e-3) and np.allclose(allrows.ruwe, x.ruwe, rtol=1e-3)
assert np.abs(allrows.ra_pmra_corr - x.ra_pmra_corr).max() <= 0.5 / 127 + 1e-9
assert np.isnan(allrows.phot_bp_mean_mag[x.phot_bp_mean_mag.isna()]).all()
assert np.allclose(allrows.radial_velocity.dropna(), x.radial_velocity.dropna()[allrows.radial_velocity.dropna().index],
                   rtol=1e-3, atol=0.05)
assert (allrows.parallax[x.pmra.isna()] == 0).all()                         # 2-parameter: stored 0

# the old reader names: LocalGaia and open_index hand a format-2 folder to starcat
assert isinstance(GL.LocalGaia(d, supplement=True), SC.StarCatalog) and isinstance(GL.open_index(d, 15), SC.StarCatalog)
assert GL.has_supplement(d)

# cone: exactly the stars within the radius (brute force)
from pysyzygos.corridor import _unit
def brute_cone(r0, d0, rad, cap=99):
    u = _unit(keep.ra.to_numpy(), keep.dec.to_numpy())
    m = (u @ _unit(r0, d0) >= math.cos(math.radians(rad))) & (keep.phot_g_mean_mag.to_numpy() <= cap)
    return set(keep.index[m])
for (r0, d0, rad, cap) in ((81.0, 20.0, 0.3, 99), (81.0, 20.0, 0.3, 12.0), (0.01, 10.0, 2.0, 99), (10.0, 89.5, 1.0, 99)):
    got = set(cat.cone(r0, d0, rad, None if cap == 99 else cap).source_id)
    assert got == brute_cone(r0, d0, rad, cap), (r0, d0, rad, cap)

# path strip: every star within w of the path is returned (a superset is allowed)
t = np.linspace(0, 1, 400)
pra, pde = 80.2 + 1.6 * t, 19.5 + 1.0 * t
U = _unit(pra, pde)
w = np.full(len(U), 0.05)
got = set(cat.near_path(U, w, 14.0)["source_id"])
u = _unit(keep.ra.to_numpy(), keep.dec.to_numpy())
near = (u @ U.T).max(axis=1) >= math.cos(math.radians(0.05))
want = set(keep.index[near & (keep.phot_g_mean_mag.to_numpy() <= 14.0)])
assert want and want <= got, len(want - got)
assert all(keep.phot_g_mean_mag[s] <= 14.0 + 0.0005 for s in got)
plan = dict(target="t", path=dict(u=U, delta_km=np.full(len(U), 1.5e8)), margin_km=1.5e8 * math.radians(0.05),
            pad_arcsec=0.0, mag_cap=14.0)
cs = cat.corridor_stars(plan)
hpm = set(keep.index[(np.hypot(keep.pmra, keep.pmdec) > 1500) & (keep.phot_g_mean_mag <= 14.0)])
assert want <= set(cs.source_id) and hpm <= set(cs.source_id) and cs.source_id.is_unique
assert set(cat.high_pm()["source_id"]) == set(keep.index[np.hypot(keep.pmra, keep.pmdec) > 1500])

# the supplement switch: off = main-catalog stars only
main_only = SC.StarCatalog(d, supplement=False)
assert set(main_only.cone(81.0, 20.0, 0.3).star_kind) == {0}
assert set(main_only.near_path(U, w, 14.0)["kind"]) <= {0}

# proper motions for 2-parameter stars from a stand-in cross-match: UCAC5 finds every other one
def fake_fetch(rows, cat_name):
    if "ucac5" not in cat_name:
        return pd.DataFrame()
    r = rows.iloc[::2]
    return pd.DataFrame(dict(source_id=r.source_id, RAgaia=r.ra, DEgaia=r.dec, Gmag=r.g, g=r.g, ra=r.ra, dec=r.dec,
                             pmRAug=5.0, pmDEug=-3.0, e_pmRAug=1.2, e_pmDEug=0.8))
GL.pick_ucac4 = lambda m: pd.DataFrame(columns=["source_id", "pmra", "pmdec", "pm_error"])
pmx = SC.xmatch(d, fetch=fake_fetch, log=lambda *a: None)
n2 = int((kind == SC.KIND_2P).sum())
assert pmx["ucac5"] == (n2 + 1) // 2 and pmx["none"] == n2 // 2 and SC.status(d)["pm_xmatch"]["ucac5"] == pmx["ucac5"]
cat = SC.StarCatalog(d, supplement=True)
f5 = cat.frame(np.arange(st["n_stars"]))
f5 = f5[f5.star_kind == SC.KIND_2P_UCAC5]
assert len(f5) == pmx["ucac5"] and (f5.pmra == 5.0).all() and np.allclose(f5.pm_err, 1.2, rtol=1e-3)

# the star's Gaia flags and error ellipse from the local catalog (doubles.star_flags, as the online check)
from pysyzygos import doubles
sid = int(keep.index[(keep.non_single_star == 1) & keep.pmra.notna()][0])
near = cat.cone(keep.ra[sid], keep.dec[sid], 3 / 3600)
fl = doubles.star_flags(near, sid, 10.0)
assert fl["gaia_nss"] == 1 and abs(fl["gaia_ruwe"] - keep.ruwe[sid]) < 0.01 and fl["star_err_smaa_mas"] > 0, fl
assert doubles.fields([], 10.0, 15.0, "local", fl)["double_hint"].startswith("Gaia: non-single star")

# the cross-reference part: UCAC4 from made-up zone files (J2000 positions = ours moved back by Gaia's proper
# motion), TYC / HIP from a stand-in for the Gaia archive; one Gaia star per UCAC4 star; magnitudes must agree
import struct
sel = keep[(keep.phot_g_mean_mag < 12) & keep.pmra.notna()].head(6)
zones = {}
def j2000(sid):
    r = keep.loc[sid]
    de = r.dec + r.pmdec * (-16) / 3.6e6
    ra = r.ra + r.pmra * (-16) / 3.6e6 / np.cos(np.radians(r.dec))
    return ra % 360, de
rec = lambda ra, de, mag: struct.pack("<iihh", int(round(ra * 3.6e6)), int(round((de + 90) * 3.6e6)), int(mag * 1000),
                                       int(mag * 1000)) + bytes(66)
want = {}
for i, xs in enumerate(sel.index):
    ra, de = j2000(xs)
    z = int((de + 90) // 0.2) + 1
    mag = keep.loc[xs].phot_g_mean_mag + (3.0 if i == 5 else 0.3)      # the last one: 3 mag off, no match
    zones.setdefault(z, []).append((ra, de, mag))
    if i < 5:
        want[xs] = (z, len(zones[z]))
fetch = lambda url: b"".join(rec(*x) for x in sorted(zones.get(int(url[-3:]), []), key=lambda x: x[0]))
for z, lst in zones.items():                                              # running numbers follow the RA order
    order = sorted(range(len(lst)), key=lambda k: lst[k][0])
    for xs, (zz, k) in list(want.items()):
        if zz == z:
            want[xs] = (z, order.index(k - 1) + 1)
tyc_sid, hip_sid = int(sel.index[0]), int(sel.index[1])
def fake_query(q):
    lo, hi = (int(x) for x in q.split("BETWEEN")[1].split("AND"))
    if "tycho2" in q:
        rows = [(tyc_sid, "1876-1234-1")] if lo <= tyc_sid <= hi else []
    else:
        rows = [(hip_sid, "12345")] if lo <= hip_sid <= hi else []
    return pd.DataFrame(rows, columns=["source_id", "original_ext_source_id"])
gc.collect() if "gc" in globals() else None
SC.build_xref(d, zones=sorted(zones), fetch=fetch, query=fake_query, log=lambda *a: None, tyc_parts=4)
assert "xref" in SC.groups_present(d)
cat = SC.StarCatalog(d, supplement=True)
for xs, (z, k) in want.items():
    nm = cat.names(xs, keep.ra[xs], keep.dec[xs])
    assert nm["star_ucac4"] == f"{z:03d}-{k:06d}", (xs, nm, z, k)
assert cat.names(int(sel.index[5]), keep.ra[sel.index[5]], keep.dec[sel.index[5]])["star_ucac4"] == ""   # 3 mag off
assert cat.names(tyc_sid, keep.ra[tyc_sid], keep.dec[tyc_sid])["star_tyc"] == "1876-1234-1"
assert cat.names(hip_sid, keep.ra[hip_sid], keep.dec[hip_sid])["star_hip"] == "12345"
assert SC.tyc_name(SC.tyc_id(9537, 12121, 3)) == "9537-12121-3" and SC.ucac4_name(SC.ucac4_id(900, 999999)) == "900-999999"
# two Gaia stars at one UCAC4 star: only the nearer one gets it
a0 = int(sel.index[0]); ra0, de0 = j2000(a0)
twin = SC.match_ucac4(d, zones=[int((de0 + 90) // 0.2) + 1], fetch=lambda url: rec(ra0, de0, keep.phot_g_mean_mag[a0]),
                      log=lambda *a: None)[0]
assert int((twin > 0).sum()) == 1
# epoch proper motions: UCAC4 records with central epochs 1998.0 at Gaia's position moved back by (-3, -10) mas/yr;
# a precise one replaces UCAC5 (error 1.2) or gives a star without pm one, an imprecise one (100 mas) keeps UCAC5
core = np.load(os.path.join(d, "core.npy"), mmap_mode="r")
k2 = SC.kind_of(np.asarray(core["flags"]))
r_none, r_u5a, r_u5b = int(np.where(k2 == SC.KIND_2P)[0][0]), *(int(x) for x in np.where(k2 == SC.KIND_2P_UCAC5)[0][:2])
offs = np.load(os.path.join(d, "offsets.npy"))
def ucac_rec(row, sig):
    c = core[row]
    ra, de = (float(x[0]) for x in SC.decode(np.searchsorted(offs, [row], side="right") - 1, [c["dra"]], [c["ddec"]]))
    de_c = de + 10.0 * 18 / 3.6e6                                         # 1998.0: 18 years before, pm (-3, -10)
    ra_c = ra + 3.0 * 18 / 3.6e6 / np.cos(np.radians(de))
    # J2000 = central epoch + UCAC4's own (bad) pm (+20, +20) mas/yr x 2 years
    ra_j, de_j = ra_c + 20.0 * 2 / 3.6e6 / np.cos(np.radians(de)), de_c + 20.0 * 2 / 3.6e6
    return struct.pack("<iihhbbbbbbbbhhhhbb", int(round(ra_j * 3.6e6)), int(round((de_j + 90) * 3.6e6)), 10000, 10000,
                       0, 0, 0, sig - 128, sig - 128, 0, 0, 0, 9800, 9800, 200, 200, 0, 0) + bytes(48)
recs = np.frombuffer(b"".join(ucac_rec(r, s) for r, s in ((r_none, 10), (r_u5a, 10), (r_u5b, 100))), SC.UCAC4_REC)
pmra_e, pmde_e, sra, sde, ok_e = SC.epoch_pm(recs[:1], *SC.decode(np.searchsorted(offs, [r_none], side="right") - 1,
                                                                   [core[r_none]["dra"]], [core[r_none]["ddec"]]))
assert ok_e.all() and abs(pmra_e[0] + 3.0) < 0.01 and abs(pmde_e[0] + 10.0) < 0.01, (pmra_e, pmde_e)   # not +20
assert abs(sde[0] - np.hypot(10, SC.EPOCH_GAIA_POS_ERR) / 18) < 1e-6
core = None
gc.collect() if "gc" in globals() else None
cnt = SC.choose_pm(d, [r_none, r_u5a, r_u5b], recs, dry_run=True)
assert cnt == dict(candidates=3, replaced={"2": 1, "3": 1, "4": 0}, kept=1), cnt
SC.choose_pm(d, [r_none, r_u5a, r_u5b], recs)
core = np.load(os.path.join(d, "core.npy"), mmap_mode="r")
k3 = SC.kind_of(np.asarray(core["flags"][[r_none, r_u5a, r_u5b]]))
assert list(k3) == [SC.KIND_2P_EPOCH, SC.KIND_2P_EPOCH, SC.KIND_2P_UCAC5], k3
assert abs(core["pmdec"][r_u5a] + 10.0) < 0.01 and core["pmra"][r_u5b] == 5.0
core = None
gc.collect() if "gc" in globals() else None
assert GL.star_flag(SC.KIND_2P_EPOCH) == "2-param, pm UCAC4 epoch to Gaia"
assert GL.star_sigma_mas(SC.KIND_2P_EPOCH, 0, 2.0, 0.6, 10.0) == float(np.hypot(2.0, 6.0))
from pysyzygos import report as RP
assert RP.star_label(dict(star="1", star_ucac4="573-029535"))[0] == "UCAC4 573-029535"
cat = None

# switch a part off (files kept) and on again; add_group switches a kept part on without a download
import gc
cat = main_only = near = f5 = allrows = None                 # no memory map may stay on a file that is renamed
gc.collect()
SC.disable_group(d, "quality")
assert SC.groups_present(d) == ["core", "extras", "xref"] and SC.disabled_groups(d) == ["quality"]
assert SC.StarCatalog(d).quality is None and os.path.isfile(os.path.join(d, "quality.npy.off"))
gc.collect()
assert "quality" not in json.load(open(os.path.join(d, "catalog.json")))["groups"]
assert SC.enable_group(d, "quality") and SC.groups_present(d) == ["core", "quality", "extras", "xref"] and not SC.disabled_groups(d)
SC.disable_group(d, "quality")
gc.collect()
SC.add_group(d, "quality")                                   # no download: the kept files are used
assert SC.groups_present(d) == ["core", "quality", "extras", "xref"]
assert SC.StarCatalog(d).quality is not None
gc.collect()
SC.disable_group(d, "extras")
SC.remove_group(d, "extras")                                 # delete also removes kept files
assert not SC.disabled_groups(d) and not any(f.startswith("extras") for f in os.listdir(d))
SC.ZENODO_STEM[16.0] = "gaia_dr3_g16_v2"
cat = SC.StarCatalog(d, supplement=True)

# optional parts: remove one; pack; fetch core + parts from 'Zenodo' (stand-ins) into a fresh folder
SC.remove_group(d, "extras")                                 # (already gone: no error)
SC.remove_group(d, "xref")
assert SC.groups_present(d) == ["core", "quality"] and "phot_bp_mean_mag" not in SC.StarCatalog(d).cone(81, 20, 0.2)
out = os.path.join(root, "release")
SC.ZENODO_STEM[16.0] = "gaia_dr3_g16_v2"
arch = SC.pack(d, out)
assert sorted(os.path.basename(a) for a in arch) == ["gaia_dr3_g16_v2_core.tar.xz", "gaia_dr3_g16_v2_quality.tar.xz"]
zen = {os.path.basename(p): (os.path.getsize(p), "file://" + p) for p in arch}
zen.update({k + ".sha256": (0, v[1] + ".sha256") for k, v in list(zen.items())})
GL._fetch_resume = lambda url, size, dst, tries=6: shutil.copyfile(url[len("file://"):], dst)
d2 = os.path.join(root, "other", "gaia_dr3_g16")
os.makedirs(os.path.dirname(d2))
st2 = SC.fetch(d2, 16.0, groups=("quality",), files=zen, mirror_list=[])
assert st2["complete"] and st2["groups"] == ["core", "quality"] and st2["n_stars"] == st["n_stars"]
assert (np.load(os.path.join(d2, "core.npy")) == np.load(os.path.join(d, "core.npy"))).all()
assert not [f for f in os.listdir(os.path.dirname(d2)) if f.endswith(".tar.xz")]          # archives deleted
SC.remove_group(d2, "quality")
nq = SC.StarCatalog(d2)
assert nq.quality is None
fl = doubles.star_flags(nq.cone(keep.ra[sid], keep.dec[sid], 3 / 3600), sid, 10.0)
assert fl["gaia_nss"] == 1 and "star_err_smaa_mas" not in fl, fl              # core flags only, no ellipse
nq = None
SC.fetch(d2, 16.0, groups=("quality",), files=zen, mirror_list=[])            # added again later: only the part
assert SC.groups_present(d2) == ["core", "quality"]
# a mirror only (not on Zenodo): the checksum from the stored table, else the mirror's .sha256; a wrong stored one
# refuses the download
SC.ARCHIVE_SHA256.clear()
d3 = os.path.join(root, "mirror", "gaia_dr3_g16")
os.makedirs(os.path.dirname(d3))
st3 = SC.fetch(d3, 16.0, groups=("quality",), files={}, mirror_list=["file://" + out + "/"])
assert st3["complete"] and st3["groups"] == ["core", "quality"]
d4 = os.path.join(root, "mirror2", "gaia_dr3_g16")
os.makedirs(os.path.dirname(d4))
SC.ARCHIVE_SHA256["gaia_dr3_g16_v2_core.tar.xz"] = (None, "0" * 64)
try:
    SC.fetch(d4, 16.0, groups=(), files={}, mirror_list=["file://" + out + "/"])
    raise AssertionError("a file with another checksum was accepted")
except SystemExit as e:
    assert "SHA-256 mismatch" in str(e), e
assert not SC.is_format2(d4)
os.environ["PYSYZYGOS_CATALOG_MIRROR"] = "https://example.org/cat"
assert SC.mirrors()[0] == "https://example.org/cat/"
del os.environ["PYSYZYGOS_CATALOG_MIRROR"]
# a part of another build is refused
other = json.load(open(os.path.join(d2, "quality.json")))
other["build_id"] = "0" * 16
json.dump(other, open(os.path.join(d2, "quality.json"), "w"))
assert not SC.group_ok(d2, "quality") and SC.groups_present(d2) == ["core"]

# upgrade: the new catalog is built next to the old one (.new) and swapped in; the old one goes to .old
old = os.path.join(root, "up", "gaia_dr3_g16")
os.makedirs(old)
json.dump(dict(gmax=16.0, ruwe_max=1.4, files=[]), open(os.path.join(old, "catalog.json"), "w"))
shutil.copytree(d, SC.staging_dir(old))
assert SC.swap_in(old) == old + ".old" and SC.is_format2(old) and not os.path.exists(SC.staging_dir(old))
assert os.path.isfile(os.path.join(old + ".old", "catalog.json"))

# data versions and the update 2.0 -> 2.1: the core and the changed parts from the mirror into <d>.new, extras (the
# same in both) copied over, then swapped in
def fake_part(dd, g):
    m = json.load(open(os.path.join(dd, "catalog.json")))
    np.save(os.path.join(dd, f"{g}.npy"), np.zeros(m["n_stars"], SC.GROUPS[g]))
    json.dump(dict(group=g, build_id=m["build_id"], n_stars=m["n_stars"]), open(os.path.join(dd, f"{g}.json"), "w"))
def set_version(dd, v):
    m = json.load(open(os.path.join(dd, "catalog.json")))
    m.pop("pm_epoch", None); m.pop("data_version", None)
    if v:
        m["data_version"] = v
    json.dump(m, open(os.path.join(dd, "catalog.json"), "w"))
d21 = os.path.join(root, "v21", "gaia_dr3_g16"); shutil.copytree(d, d21)
set_version(d21, "2.1"); fake_part(d21, "xref")
out21 = os.path.join(root, "release21")
SC.pack(d21, out21, groups=["core", "quality", "xref"])
d20 = os.path.join(root, "v20", "gaia_dr3_g16"); shutil.copytree(d, d20)
set_version(d20, None); fake_part(d20, "extras")
assert SC.data_version(d20) == "2.0" and SC.update_available(d20) == "2.1" and SC.update_available(d21) is None
assert SC.data_version(os.path.join(root, "nothing")) == ""
SC.ARCHIVE_SHA256.clear()
gc.collect()
prev = SC.update(d20, log=lambda *a: None, files={}, mirror_list=["file://" + out21 + "/"])
assert prev == d20 + ".old" and SC.data_version(d20) == "2.1" and SC.update_available(d20) is None
assert SC.groups_present(d20) == ["core", "quality", "extras", "xref"], SC.groups_present(d20)
assert SC.data_version(prev) == "2.0" and not os.path.exists(SC.staging_dir(d20))
print("STARCAT TESTS PASSED")
