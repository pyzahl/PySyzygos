"""gaia_local.py - local, magnitude-limited copy of Gaia DR3 for the corridor search.

Why: the Gaia archive (TAP) can take many minutes per strip query or hang. The full gaia_source table is on ESA's CDN as
3386 gzipped CSV files (753 GB). This tool streams them once, keeps only what the search needs (G <= gmax, 5-parameter
astrometry, ruwe < 1.4; 7 columns as binary, ~40 bytes/star, about 19 GB for G <= 18), and deletes each download.
Afterwards a corridor lookup reads only the few files its strip touches, in about a second, without network.

    pysyzygos gaia build                 # dir and gmax from pysyzygos_config (gaia_local_dir, gaia_local_gmax)
    pysyzygos gaia build --workers 6     # resumable: rerun after an interruption, finished files are skipped
    pysyzygos gaia status
    pysyzygos gaia zenodo --gmax 16    # ready-made copy (G <= 16 or 18) from Zenodo instead of building
    pysyzygos gaia supplement --dir gaia_dr3_g18 --gmax 16   # <dir>/supplement: high-RUWE and 2-parameter stars
                                                            #   (from Zenodo, or --source esa to build it)

Layout of the catalog folder:
    catalog.json                      gmax, cuts and the list of source files (written first)
    GaiaSource_xxxxxx-yyyyyy.npy      the kept stars of one source file, structured array DTYPE, sorted by source_id
    GaiaSource_xxxxxx-yyyyyy.cells.npy  1x1 deg sky cells that file has stars in (the lookup index)
    GaiaSource_xxxxxx-yyyyyy.hpm.npy  its stars with proper motion > HIGH_PM_MAS (they can leave the strip pad)
The .npy of a file is written last, atomically; its presence means that file is done.

Network only (no SPICE), so the build uses processes freely. Standard library + numpy, pandas, requests.
"""
from pysyzygos.version import __version__
from pysyzygos import urls as U
import argparse, json, math, os, re, shutil, sys, tempfile, time
from concurrent.futures import ProcessPoolExecutor, as_completed
import numpy as np
import pandas as pd

BUCKET = U.URL_GAIA_DR3_LISTING                                       # S3-style listing behind the CDN (urls)
PREFIX = U.GAIA_DR3_LISTING_PREFIX
COLS = ["source_id", "ra", "dec", "parallax", "pmra", "pmdec", "phot_g_mean_mag"]
DTYPE = np.dtype([("source_id", "<i8"), ("ra", "<f8"), ("dec", "<f8"), ("parallax", "<f4"),
                  ("pmra", "<f4"), ("pmdec", "<f4"), ("phot_g_mean_mag", "<f4")])
HIGH_PM_MAS = 1500.0                                                  # must match the corridor pm pad (pm_pad_mas)
RUWE_MAX = 1.4
# The supplement (<catalog>/supplement/): the stars the main catalog leaves out, flagged: RUWE >= RUWE_MAX (often
# unresolved doubles: position less certain) and 2-parameter sources (no parallax or proper motion: the position
# drifts by the unknown motion since 2016). OWC predicts events on both; PySyzygos does with the supplement.
SUPPLEMENT = "supplement"
KIND_MAIN, KIND_RUWE, KIND_2P = 0, 1, 2
KIND_2P_UCAC5, KIND_2P_UCAC4 = 3, 4                   # 2-parameter stars with a proper motion from UCAC5 / UCAC4
KIND_2P_EPOCH = 5                                     # ... from UCAC4's central-epoch position to Gaia's (starcat.pm_epoch)
PM_SOURCE = {KIND_2P_UCAC5: "UCAC5", KIND_2P_UCAC4: "UCAC4", KIND_2P_EPOCH: "UCAC4 epoch to Gaia"}
PM_UNKNOWN_MAS_YR = 10.0                               # 1 sigma per axis of an unknown proper motion (stars G 10-16)
SUPP_DTYPE = np.dtype(DTYPE.descr + [("ruwe", "<f4"), ("ra_error", "<f4"), ("dec_error", "<f4"), ("kind", "u1"),
                                      ("pm_error", "<f4")])  # pm_error: of a cross-matched pm (supplement_pm), mas/yr


class Progress:
    """Progress of a long step, so it never looks stuck: in a terminal one line rewritten in place (about once a
    second), else (log file, nohup) a new line every 30 s. p(done, note) updates, p.finish(text) ends it."""

    def __init__(self, label, total, fmt=lambda x: f"{x / 1e9:.2f} GB", rate=lambda r: f"{r / 1e6:.1f} MB/s", start=0,
                 every=30.0):
        self.label, self.total, self.fmt, self.rate, self.start = label, max(total, 1), fmt, rate, start
        self.tty = sys.stdout.isatty()
        self.every = 1.0 if self.tty else every                      # a log file / the GUI: a line every `every` s
        self.t0 = self.last = time.time()
        self.width = 0

    def _out(self, text, end=False):
        if self.tty:
            print("\r" + text.ljust(self.width), end="\n" if end else "", flush=True)
            self.width = 0 if end else len(text)
        else:
            print(text, flush=True)

    def __call__(self, done, note="", force=False):
        now = time.time()
        if not force and now - self.last < self.every:
            return
        self.last = now
        el = max(now - self.t0, 1e-3)
        r = (done - self.start) / el
        eta = (self.total - done) / r if r > 0 else float("nan")
        eta_s = "?" if eta != eta else (f"{eta / 3600:.0f} h {eta % 3600 / 60:02.0f} min" if eta >= 3600
                                        else f"{eta // 60:.0f} min {eta % 60:02.0f} s")
        self._out(f"   {self.label}: {self.fmt(done)} of {self.fmt(self.total)} ({100 * done / self.total:.0f} %), "
                  f"{self.rate(r)}, ETA {eta_s}{note}")

    def finish(self, text):
        self._out(f"   {self.label}: {text} in {(time.time() - self.t0) / 60:.1f} min", end=True)


# ----------------------------------------------------------------------------------------------- sky cells
def cell_of(ra_deg, dec_deg, size=1.0):
    """Plain ra/dec grid of size x size deg: cell = dec_band * n_ra + ra_band (n_ra = 360/size)."""
    n_dec, n_ra = int(round(180 / size)), int(round(360 / size))
    di = np.clip(np.floor((np.asarray(dec_deg, float) + 90.0) / size), 0, n_dec - 1).astype(np.int64)
    ri = (np.floor((np.asarray(ra_deg, float) % 360.0) / size).astype(np.int64)) % n_ra
    return di * n_ra + ri


def cells_near(ra_deg, dec_deg, w_deg, size=1.0):
    """All cells within w_deg (per point) of the points (a numpy array). The box ra +/- w/cos(dec), dec +/- w around
    each point is probed at steps below one cell, so no cell is skipped; near a pole the whole dec band is taken."""
    n_dec, n_ra = int(round(180 / size)), int(round(360 / size))
    ra, dec, w = np.broadcast_arrays(*(np.atleast_1d(np.asarray(x, float)) for x in (ra_deg, dec_deg, w_deg)))
    out = []
    kd = int(np.ceil(w.max() / (0.5 * size))) if len(w) else 1
    for fd in np.linspace(-1, 1, 2 * kd + 1):
        d = np.clip(dec + fd * w, -90, 90)
        cosd = np.cos(np.radians(np.minimum(np.abs(d) + w, 90.0)))
        wr = np.where(cosd > 0.02, w / np.maximum(cosd, 0.02), 360.0)
        polar = wr >= 180.0
        ok = ~polar
        if ok.any():
            kr = int(np.ceil(wr[ok].max() / (0.5 * size)))
            for fr in np.linspace(-1, 1, 2 * kr + 1):
                out.append(cell_of(ra[ok] + fr * wr[ok], d[ok], size))
        for di in np.unique(np.clip(np.floor((d[polar] + 90.0) / size), 0, n_dec - 1).astype(np.int64)):
            out.append(np.arange(di * n_ra, di * n_ra + n_ra))
    return np.unique(np.concatenate(out)) if out else np.empty(0, np.int64)


def near_path_mask(S, U, w_deg, chunk_deg=0.05):
    """Boolean mask of the unit vectors S (n,3) within w_deg (per path sample) of the path U (m,3): coarse discs per
    path chunk (<= chunk_deg long), a superset of the exact strip (the candidate scan does the exact test)."""
    ang = np.degrees(np.arccos(np.clip(np.sum(U[:-1] * U[1:], axis=1), -1, 1)))
    cum = np.concatenate(([0.0], np.cumsum(ang)))
    edges = np.unique(np.concatenate((np.searchsorted(cum, np.arange(0, cum[-1], chunk_deg)), [len(U) - 1])))
    C, cosr = [], []
    for i0, i1 in zip(edges[:-1], edges[1:]):
        c = U[i0:i1 + 1].mean(axis=0)
        c /= np.linalg.norm(c)
        r = np.degrees(np.arccos(np.clip(U[i0:i1 + 1] @ c, -1, 1))).max() + 1.2 * w_deg[i0:i1 + 1].max()
        C.append(c); cosr.append(math.cos(math.radians(r)))
    if not C:
        C, cosr = [U[0]], [math.cos(math.radians(1.2 * w_deg[0]))]
    C, cosr = np.array(C), np.array(cosr)
    keep = np.zeros(len(S), bool)
    for k in range(0, len(C), 64):                                                   # (stars x discs) in blocks
        keep |= ((S @ C[k:k + 64].T) >= cosr[None, k:k + 64]).any(axis=1)
    return keep


# ----------------------------------------------------------------------------------------------- build
def list_files(timeout=90):
    """[(file name, size bytes)] of gaia_source on the CDN (paged S3 listing)."""
    import requests
    out, marker = [], None
    while True:
        p = dict(prefix=PREFIX, delimiter="/")
        if marker:
            p["marker"] = marker
        r = requests.get(BUCKET, params=p, timeout=timeout)
        r.raise_for_status()
        t = r.text
        ks = re.findall(r"<Key>([^<]+)</Key>.*?<Size>(\d+)</Size>", t, re.S)
        out += [(k.rsplit("/", 1)[1], int(s)) for k, s in ks]
        if "<IsTruncated>true" in t and ks:
            marker = ks[-1][0]
        else:
            files = [(n, s) for n, s in out if n.startswith("GaiaSource_") and n.endswith(".csv.gz")]
            if not files:                     # e.g. a proxy's or portal's page instead of the listing
                raise RuntimeError(f"no Gaia source files in the listing at {BUCKET} (got {len(t)} bytes that are "
                                   f"not the file list: blocked by a proxy or firewall?)")
            return files


def _download(name, dst, tries=4):
    import requests
    for k in range(tries):
        try:
            with requests.get(U.URL_GAIA_DR3_FILES + name, stream=True, timeout=120) as r:
                r.raise_for_status()
                with open(dst, "wb") as f:
                    for c in r.iter_content(1 << 20):
                        f.write(c)
            return
        except Exception as e:
            if k == tries - 1:
                raise
            print(f"  retry {name}: {str(e)[:100]}", flush=True)
            time.sleep(10 * (k + 1))


def replace_file(src, dst, tries=40, wait=0.25):
    """os.replace(src, dst), retried for ~10 s on Windows' "file in use" (WinError 32 / PermissionError): Windows refuses
    to rename a file that is still memory-mapped or open anywhere, and virus scanners (Defender) often hold a freshly
    written large file for a moment. Linux and macOS rename at once. Raises the last error with an explanation."""
    import gc
    for k in range(tries):
        try:
            os.replace(src, dst)
            return
        except PermissionError as e:
            if k == tries - 1:
                raise PermissionError(f"{e} - the file is still in use (another PySyzygos run or the GUI using this "
                                      f"catalog, or a virus scanner); close them, delete leftover *.tmp files in "
                                      f"{os.path.dirname(os.path.abspath(dst))} and rerun") from None
            gc.collect()                                             # drop memory maps that are only waiting for it
            time.sleep(wait)


def _save_atomic(path, arr):
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    with os.fdopen(fd, "wb") as f:
        np.save(f, arr)
    replace_file(tmp, path)


def process_file(name, out_dir, gmax, ruwe_max=RUWE_MAX, supplement=False):
    """Download one source file, keep the useful stars, write .cells/.hpm then the .npy (done marker). Returns stats.
    supplement: keep the opposite (RUWE >= ruwe_max or no parallax/proper motion), as SUPP_DTYPE with the flags."""
    stem = name[:-len(".csv.gz")]
    final = os.path.join(out_dir, stem + ".npy")
    if os.path.isfile(final):
        return name, None, None, 0.0
    t0 = time.time()
    fd, gz = tempfile.mkstemp(dir=out_dir, suffix=".csv.gz.tmp")
    os.close(fd)
    try:
        _download(name, gz)
        df = pd.read_csv(gz, compression="gzip", comment="#", na_values=["null"],
                         usecols=COLS + ["ruwe"] + (["ra_error", "dec_error"] if supplement else []))
    finally:
        os.remove(gz)
    n_in = len(df)
    main = df.pmra.notna() & df.parallax.notna() & (df.ruwe < ruwe_max)
    if not supplement:
        df = df[(df.phot_g_mean_mag <= gmax) & main]
        arr = np.empty(len(df), DTYPE)
        for c in COLS:
            arr[c] = df[c].to_numpy()
    else:
        df = df[(df.phot_g_mean_mag <= gmax) & ~main & df.ra.notna() & df.dec.notna()]
        two_p = (df.pmra.isna() | df.parallax.isna()).to_numpy()
        arr = np.zeros(len(df), SUPP_DTYPE)
        for c in COLS + ["ruwe", "ra_error", "dec_error"]:
            arr[c] = df[c].fillna(0.0).to_numpy()                     # no parallax/pm: 0 (flagged KIND_2P)
        arr["kind"] = np.where(two_p, KIND_2P, KIND_RUWE)
    arr.sort(order="source_id")
    _save_atomic(os.path.join(out_dir, stem + ".cells.npy"), np.unique(cell_of(arr["ra"], arr["dec"])))
    pm = np.hypot(arr["pmra"].astype(float), arr["pmdec"].astype(float))
    _save_atomic(os.path.join(out_dir, stem + ".hpm.npy"), arr[pm > HIGH_PM_MAS])
    _save_atomic(final, arr)
    return name, n_in, len(arr), time.time() - t0


def build(out_dir, gmax=18.0, workers=6, supplement=False):
    """Build (or resume) a local catalog in out_dir; supplement: the supplement of the catalog in out_dir, in
    out_dir/supplement (kind 'supplement' in its catalog.json)."""
    if supplement:
        if not os.path.isfile(os.path.join(out_dir, "catalog.json")):
            sys.exit(f"{out_dir}: no catalog there to add a supplement to")
        out_dir = os.path.join(out_dir, SUPPLEMENT)
    os.makedirs(out_dir, exist_ok=True)
    man_path = os.path.join(out_dir, "catalog.json")
    print("listing ESA's Gaia DR3 files ...", flush=True)
    files = list_files()
    kind = "supplement" if supplement else "main"
    if os.path.isfile(man_path):
        man = json.load(open(man_path))
        if abs(man["gmax"] - gmax) > 1e-9 or man["ruwe_max"] != RUWE_MAX or man.get("kind", "main") != kind:
            sys.exit(f"{out_dir} holds a {man.get('kind', 'main')} catalog with gmax {man['gmax']}, ruwe cut "
                     f"{man['ruwe_max']}; use another folder")
    man = dict(gmax=gmax, ruwe_max=RUWE_MAX, high_pm_mas=HIGH_PM_MAS, source=U.URL_GAIA_DR3_FILES, kind=kind,
               files=[n for n, _ in files], created=time.strftime("%Y-%m-%d %H:%M:%S"))
    if supplement:
        man["contents"] = (f"stars the main catalog leaves out: RUWE >= {RUWE_MAX} (kind {KIND_RUWE}) and 2-parameter "
                           f"sources without parallax/proper motion (kind {KIND_2P}; stored as 0)")
    fd, tmp = tempfile.mkstemp(dir=out_dir, suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(man, f, indent=1)
    replace_file(tmp, man_path)
    for t in os.listdir(out_dir):                                       # leftovers of an interrupted run
        if t.endswith(".tmp"):
            os.remove(os.path.join(out_dir, t))
    todo = [n for n, _ in files if not os.path.isfile(os.path.join(out_dir, n[:-len(".csv.gz")] + ".npy"))]
    total_gb = sum(s for n, s in files if n in set(todo)) / 1e9
    print(f"{len(files)} source files, {len(todo)} to do ({total_gb:.0f} GB to download), G <= {gmax}, {workers} workers",
          flush=True)
    t0, done, kept, seen, failed = time.time(), 0, 0, 0, []
    ex = ProcessPoolExecutor(max_workers=workers) if workers > 0 else None       # workers <= 0: serial (tests)
    futs = {ex.submit(process_file, n, out_dir, gmax, RUWE_MAX, supplement): n for n in todo} if ex else {}
    prog = Progress("ESA build", len(todo), fmt=lambda x: f"{x:.0f} files", rate=lambda r: f"{r * 60:.1f} files/min")
    prog(0, " (first files take a minute or two)", force=True)
    stream = ((n, None) for n in todo) if ex is None else ((futs[f], f) for f in as_completed(futs))
    try:
        for name, fut in stream:
            try:
                _, n_in, n_keep, dt = process_file(name, out_dir, gmax, RUWE_MAX, supplement) if fut is None \
                    else fut.result()
            except Exception as e:                  # this file failed after its retries: go on, a rerun resumes it
                failed.append(name)
                print(f"\n   failed: {name}: {str(e)[:160]}", flush=True)
                if len(failed) >= max(3, workers) and done == len(failed) - 1:
                    raise RuntimeError(f"the first {len(failed)} Gaia files all failed to download from "
                                       f"{U.URL_GAIA_DR3_FILES}: offline, server down, or blocked by a proxy or "
                                       f"firewall. Last error: {str(e)[:200]}") from None
                continue
            finally:
                done += 1
            if n_in is not None:
                seen, kept = seen + n_in, kept + n_keep
            prog(done, f", {kept/1e6:.1f} M of {seen/1e6:.1f} M stars kept", force=done == len(todo))
    finally:
        if ex is not None:
            ex.shutdown(cancel_futures=True)
    if todo:
        prog.finish(f"{done - len(failed)} files, {kept/1e6:.1f} M stars kept")
    st = status(out_dir)
    print(f"done: {st['done']}/{st['total']} files, {st['gb']:.1f} GB")
    if failed:
        print(f"{len(failed)} files failed (network); rerun setup to fetch just those (it resumes)")
    if st["complete"] and not supplement:
        BrightIndex(out_dir, 15.0)                                           # for pick.py


# ----------------------------------------------------------------------------------------------- supplement pm
def _xmatch(rows, cat, radius_arcsec=3.0, tries=3):
    """CDS XMatch of rows (DataFrame source_id, ra, dec, g) with a VizieR catalog: DataFrame of all pairs."""
    import io, requests
    buf = rows[["source_id", "ra", "dec", "g"]].to_csv(index=False, float_format="%.9f").encode()
    for k in range(tries):
        try:
            r = requests.post(U.URL_CDS_XMATCH, timeout=600, files={"cat1": ("cat1.csv", buf)},
                              data=dict(request="xmatch", distMaxArcsec=radius_arcsec, RESPONSEFORMAT="csv",
                                        colRA1="ra", colDec1="dec", cat2=cat))
            r.raise_for_status()
            return pd.read_csv(io.StringIO(r.text))
        except Exception as e:
            if k == tries - 1:
                raise RuntimeError(f"CDS XMatch with {cat} failed: {str(e)[:200]}") from None
            time.sleep(10 * (k + 1))


def _sep_arcsec(ra1, de1, ra2, de2):
    return 3600.0 * np.degrees(np.arccos(np.clip(
        np.sin(np.radians(de1)) * np.sin(np.radians(de2)) + np.cos(np.radians(de1)) * np.cos(np.radians(de2))
        * np.cos(np.radians(ra2 - ra1)), -1.0, 1.0)))


def pick_ucac5(m):
    """Best UCAC5 partner per Gaia star (XMatch pairs m): its Gaia DR1 position (2015.0) within 0.2" of the DR3 one
    (2016.0) and G within 0.5 mag. Returns DataFrame source_id, pmra, pmdec, pm_error."""
    if m.empty:
        return pd.DataFrame(columns=["source_id", "pmra", "pmdec", "pm_error"])
    m = m.dropna(subset=["RAgaia", "DEgaia", "pmRAug", "pmDEug"]).copy()
    m["sep"] = _sep_arcsec(m.ra, m.dec, m.RAgaia, m.DEgaia)
    m = m[(m.sep <= 0.2) & ((m.Gmag - m.g).abs() <= 0.5)].sort_values("sep").drop_duplicates("source_id")
    err = np.maximum(m.e_pmRAug.fillna(9.9), m.e_pmDEug.fillna(9.9))
    return pd.DataFrame(dict(source_id=m.source_id, pmra=m.pmRAug, pmdec=m.pmDEug, pm_error=err))


def pick_ucac4(m):
    """Best UCAC4 partner per Gaia star: its J2000 position moved with its pm to 2016.0 within 0.5" of Gaia's, and
    its magnitude (f.mag, else V) within 1 mag of G."""
    if m.empty:
        return pd.DataFrame(columns=["source_id", "pmra", "pmdec", "pm_error"])
    m = m.dropna(subset=["RAJ2000", "DEJ2000", "pmRA", "pmDE"]).copy()
    dt = 2016.0 - 2000.0
    de = m.DEJ2000 + m.pmDE / 3.6e6 * dt
    ra = m.RAJ2000 + m.pmRA / 3.6e6 * dt / np.cos(np.radians(m.DEJ2000))
    m["sep"] = _sep_arcsec(m.ra, m.dec, ra, de)
    mag = m["f.mag"].fillna(m.get("Vmag"))
    m = m[(m.sep <= 0.5) & ((mag - m.g).abs() <= 1.0)].sort_values("sep").drop_duplicates("source_id")
    err = np.maximum(m.e_pmRA.fillna(9.9), m.e_pmDE.fillna(9.9))
    return pd.DataFrame(dict(source_id=m.source_id, pmra=m.pmRA, pmdec=m.pmDE, pm_error=err))


def supplement_pm(catalog_dir, chunk=50000, log=print):
    """Proper motions for the supplement's 2-parameter stars (Gaia DR3 has none for them), as OWC/Occult take them
    from other catalogs: CDS XMatch with UCAC5 (Zacharias et al. 2017; pm from Gaia DR1 and UCAC, positions at 2015.0,
    so a match is unambiguous within 0.2"), then UCAC4 for the rest. Matched stars get pmra/pmdec, pm_error and kind
    KIND_2P_UCAC5 / KIND_2P_UCAC4 (Gaia's 2016 position is kept); the others stay KIND_2P. Rewrites the supplement's
    star files (SUPP_DTYPE with pm_error), records it in its catalog.json and drops its bright-star index (rebuilt on
    use). Needs the network (~3 min for ~570k stars). Returns the counts."""
    sd = supplement_dir(catalog_dir)
    man_path = os.path.join(sd, "catalog.json")
    man = json.load(open(man_path))
    stems = [n[:-len(".csv.gz")] for n in man["files"]]
    parts = []
    for s in stems:
        a = np.load(os.path.join(sd, s + ".npy"), mmap_mode="r")
        m = np.asarray(a["kind"]) == KIND_2P
        if m.any():
            b = np.array(a[m])
            parts.append(pd.DataFrame(dict(source_id=b["source_id"], ra=b["ra"], dec=b["dec"],
                                           g=b["phot_g_mean_mag"].astype(float))))
        del a
    rows = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=["source_id", "ra", "dec", "g"])
    log(f"   {len(rows)} 2-parameter stars: proper motions from UCAC5, then UCAC4 (CDS XMatch, {chunk} per request)")
    found = {}
    for cat, pick, kind in (("vizier:I/340/ucac5", pick_ucac5, KIND_2P_UCAC5), ("vizier:I/322A/out", pick_ucac4, KIND_2P_UCAC4)):
        todo = rows[~rows.source_id.isin(found)]
        t0, got = time.time(), 0
        for i in range(0, len(todo), chunk):
            p = pick(_xmatch(todo.iloc[i:i + chunk], cat))
            for sid, pa, pd_, pe in zip(p.source_id.astype("int64"), p.pmra, p.pmdec, p.pm_error):
                found[int(sid)] = (float(pa), float(pd_), float(pe), kind)
            got += len(p)
            log(f"   {cat.split(':')[1]}: {min(i + chunk, len(todo))}/{len(todo)} stars, {got} with a proper motion, "
                f"{time.time() - t0:.0f} s")
    new5 = sum(1 for v in found.values() if v[3] == KIND_2P_UCAC5)
    new4 = len(found) - new5
    n5 = n4 = n_none = 0                                           # totals over the files, not only this run's matches
    for s in stems:                                                # rewrite every star file with the new fields
        path = os.path.join(sd, s + ".npy")
        a = np.load(path)
        out = np.zeros(len(a), SUPP_DTYPE)
        for k in a.dtype.names:
            if k in SUPP_DTYPE.names:
                out[k] = a[k]
        for i in np.where(out["kind"] == KIND_2P)[0]:
            v = found.get(int(out["source_id"][i]))
            if v:
                out["pmra"][i], out["pmdec"][i], out["pm_error"][i], out["kind"][i] = v
        hpath = os.path.join(sd, s + ".hpm.npy")                 # its fast movers: the same layout (joined in lookups)
        if os.path.exists(hpath):
            _save_atomic(hpath, _as_dtype(np.load(hpath), SUPP_DTYPE))
        _save_atomic(path, out)
        n5 += int((out["kind"] == KIND_2P_UCAC5).sum())
        n4 += int((out["kind"] == KIND_2P_UCAC4).sum())
        n_none += int((out["kind"] == KIND_2P).sum())
    for f in glob_bright(sd):
        os.remove(f)
    # a rerun only looks at the stars still without a proper motion; the record counts all of them (before
    # 2026-10-16 it counted only this run's matches, so a rerun reported "0 from UCAC5, 0 from UCAC4")
    log(f"   this run: {new5} new from UCAC5, {new4} from UCAC4 (of {len(rows)} still without before)")
    man.update(pm_xmatch=dict(two_param=n5 + n4 + n_none, ucac5=n5, ucac4=n4, none=n_none,
                              date=time.strftime("%Y-%m-%d"), method="CDS XMatch: UCAC5 (Gaia DR1 2015.0 pos <= 0.2\", "
                              "dG <= 0.5), then UCAC4 (pos at 2016 <= 0.5\", dmag <= 1)"))
    fd, tmp = tempfile.mkstemp(dir=sd, suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(man, f, indent=1)
    replace_file(tmp, man_path)
    log(f"   proper motions: {n5} from UCAC5, {n4} from UCAC4, {n_none} still without (of {n5 + n4 + n_none})")
    return man["pm_xmatch"]


def _as_dtype(a, dtype):
    """a (structured) in the layout dtype: common fields copied, missing ones 0 (older supplement files have no
    pm_error)."""
    if a.dtype == dtype:
        return a
    out = np.zeros(len(a), dtype)
    for k in a.dtype.names or ():
        if k in dtype.names:
            out[k] = a[k]
    return out


def glob_bright(d):
    return [os.path.join(d, f) for f in os.listdir(d) if f.startswith("bright_")]


def has_supplement_pm(catalog_dir):
    try:
        return "pm_xmatch" in json.load(open(os.path.join(supplement_dir(catalog_dir), "catalog.json")))
    except (OSError, ValueError):
        return False


# ----------------------------------------------------------------------------------------------- ready-made copy
ZENODO_DOI = "10.5281/zenodo.23113337"                               # concept DOI: always the newest version
ZENODO_API = U.URL_ZENODO_CATALOG_RECORD
ZENODO_GMAX = (16.0, 18.0)                                            # limits published there (gaia_dr3_g16, gaia_dr3_g18)
# the high-RUWE supplement there (since version 2, 2026-10-11): independent of the main catalog's limit (the same
# RUWE / astrometry cut), so it serves any catalog folder; top folder 'supplement/'
ZENODO_SUPPLEMENT = {16.0: "gaia_dr3_g18_supplement_g16.tar.xz"}


def zenodo_files(gmax, stem=None):
    """{name: (size, url)} of the archive for this limit (or the file stem) and its .sha256 in the newest Zenodo
    version."""
    import requests
    stem = stem or f"gaia_dr3_g{gmax:g}.tar.xz"
    r = requests.get(ZENODO_API, timeout=60)
    r.raise_for_status()
    files = {f["key"]: (f["size"], f["links"]["self"]) for f in r.json()["files"]}
    if stem not in files or stem + ".sha256" not in files:
        sys.exit(f"Zenodo record {ZENODO_DOI} has no {stem}; build from ESA instead")
    return {k: files[k] for k in (stem, stem + ".sha256")}


def _fetch_resume(url, size, dst, tries=6):
    """Download url to dst (resumes a partial dst with an HTTP Range request); progress every ~5 %."""
    import requests
    for k in range(tries):
        have = os.path.getsize(dst) if os.path.isfile(dst) else 0
        if have >= size:
            return
        try:
            hdr = {"Range": f"bytes={have}-"} if have else {}
            with requests.get(url, stream=True, timeout=120, headers=hdr) as r:
                r.raise_for_status()
                if have and r.status_code != 206:                            # server ignored the Range: start over
                    have = 0
                got = 0
                prog = Progress("download", size, start=have, every=10.0)
                prog(have, " (resumed)" if have else " (starting)", force=True)
                with open(dst, "ab" if have else "wb") as f:
                    for c in r.iter_content(1 << 20):
                        f.write(c)
                        got += len(c)
                        prog(have + got)
                prog.finish(f"{(have + got) / 1e9:.2f} GB")
            if os.path.getsize(dst) >= size:
                return
        except Exception as e:
            if k == tries - 1:
                raise
            print(f"   retry: {str(e)[:100]}", flush=True)
            time.sleep(10 * (k + 1))
    raise RuntimeError(f"download of {url} incomplete after {tries} tries; rerun to resume")


def _sha256(path):
    import hashlib
    h, done = hashlib.sha256(), 0
    prog = Progress("SHA-256 check", os.path.getsize(path), every=10.0)
    with open(path, "rb") as f:
        for c in iter(lambda: f.read(1 << 22), b""):
            h.update(c)
            done += len(c)
            prog(done)
    prog.finish("done")
    return h.hexdigest()


def unpack_archive(archive, out_dir, need="catalog.json"):
    """Unpack a catalog .tar.xz (one top folder, any name) into out_dir. Unpacks into out_dir.unpack first, then moves
    the files over (overwriting a partial build of the same limit), so an interruption leaves no half-written files.
    need: the file the archive must hold (moved last: its presence marks the unpack done)."""
    import tarfile
    stage = os.path.abspath(out_dir) + ".unpack"
    shutil.rmtree(stage, ignore_errors=True)
    os.makedirs(stage)
    n = 0
    prog = Progress(f"unpack into {out_dir}", os.path.getsize(archive), fmt=lambda x: f"{x / 1e9:.2f} GB",
                    rate=lambda r: f"{r / 1e6:.1f} MB/s", every=10.0)
    with open(archive, "rb") as raw, tarfile.open(fileobj=raw, mode="r|xz") as tf:   # streaming: one pass, low memory
        for m in tf:
            prog(raw.tell(), f", {n} files")
            parts = m.name.replace("\\", "/").split("/")[1:]            # drop the archive's own top folder
            if not m.isfile() or not parts or os.path.isabs(m.name) or ".." in parts:
                continue
            m.name = "/".join(parts)
            try:
                tf.extract(m, stage, filter="data")
            except TypeError:                                            # Python without extraction filters
                tf.extract(m, stage)
            n += 1
    prog.finish(f"{n} files")
    if not os.path.isfile(os.path.join(stage, need)):
        sys.exit(f"{archive} holds no {need}: not a PySyzygos catalog archive")
    os.makedirs(out_dir, exist_ok=True)
    for f in sorted(os.listdir(stage), key=lambda f: f == need):           # the marker file last
        replace_file(os.path.join(stage, f), os.path.join(out_dir, f))
    os.rmdir(stage)


def fetch_zenodo(out_dir, gmax=18.0, keep_archive=False, supplement=False):
    """Install the ready-made catalog for G <= gmax (16 or 18) from Zenodo instead of building it: download (resumable),
    check the SHA-256, unpack into out_dir. The archive goes next to out_dir and is deleted afterwards unless
    keep_archive. No bright-star index inside: BrightIndex(out_dir) builds it. supplement: the high-RUWE supplement
    (G <= gmax, see ZENODO_SUPPLEMENT) into out_dir/supplement, out_dir being the catalog's folder."""
    import requests
    if supplement:
        if float(gmax) not in ZENODO_SUPPLEMENT:
            sys.exit(f"Zenodo has the supplement for G <= {', '.join(f'{g:g}' for g in ZENODO_SUPPLEMENT)} only, "
                     f"not {gmax:g}; build it from ESA instead")
        files = zenodo_files(gmax, ZENODO_SUPPLEMENT[float(gmax)])
        out_dir = supplement_dir(out_dir)
    elif float(gmax) not in ZENODO_GMAX:
        sys.exit(f"Zenodo has catalogs for G <= {', '.join(f'{g:g}' for g in ZENODO_GMAX)} only, not {gmax:g}; "
                 f"build from ESA instead")
    else:
        files = zenodo_files(gmax)
    (name, (size, url)), (sha_name, (_, sha_url)) = files.items()
    archive = os.path.join(os.path.dirname(os.path.abspath(out_dir)), name)
    need = (0 if os.path.isfile(archive) else size - (os.path.getsize(archive + ".part")
                                                     if os.path.isfile(archive + ".part") else 0)) + 1.4 * size
    free = shutil.disk_usage(os.path.dirname(archive)).free
    if free < need:
        sys.exit(f"not enough disk space next to {out_dir}: {need / 1e9:.1f} GB needed (archive + unpacked), "
                 f"{free / 1e9:.1f} GB free")
    want = requests.get(sha_url, timeout=60).text.split()[0].lower()
    print(f"   Zenodo {ZENODO_DOI}: {name}, {size / 1e9:.2f} GB", flush=True)
    if not os.path.isfile(archive):
        _fetch_resume(url, size, archive + ".part")
        if _sha256(archive + ".part") != want:
            os.remove(archive + ".part")
            sys.exit(f"{name}: SHA-256 mismatch (corrupt download, deleted); rerun to download again")
        replace_file(archive + ".part", archive)
    elif _sha256(archive) != want:
        sys.exit(f"{archive} exists but its SHA-256 does not match Zenodo's; delete it and rerun")
    unpack_archive(archive, out_dir)
    if not keep_archive:
        os.remove(archive)
    st = status(out_dir)
    print(f"   done: {st['done']}/{st['total']} files, {st['gb']:.1f} GB" + ("" if keep_archive else
                                                                          f"; {name} deleted"), flush=True)
    return st


def find_catalogs(root="."):
    """Local catalogs in the sub-folders of root: list of (folder, gmax, complete, gb), brightest limit first."""
    out = []
    for d in sorted(os.listdir(root)):
        p = os.path.join(root, d)
        if os.path.isfile(os.path.join(p, "catalog.json")):
            st = status(p)
            out.append((d, st.get("gmax"), st["complete"], st["gb"]))
    return sorted(out, key=lambda c: (c[1] if c[1] is not None else 99, c[0]))


def _format2(d):
    from pysyzygos import starcat
    return starcat.is_format2(d) or os.path.isfile(os.path.join(d, "build.json"))


def status(out_dir):
    if _format2(out_dir):                                            # the new format (starcat.py)
        from pysyzygos import starcat
        return starcat.status(out_dir)
    man_path = os.path.join(out_dir, "catalog.json")
    if not os.path.isfile(man_path):
        return dict(total=0, done=0, gb=0.0, complete=False)
    man = json.load(open(man_path))
    have = {f for f in os.listdir(out_dir) if f.endswith(".npy") and f.count(".") == 1}
    done = sum((n[:-len(".csv.gz")] + ".npy") in have for n in man["files"])
    gb = sum(os.path.getsize(os.path.join(out_dir, f)) for f in have) / 1e9
    return dict(total=len(man["files"]), done=done, gb=gb, complete=done == len(man["files"]), gmax=man["gmax"])


# ----------------------------------------------------------------------------------------------- supplement use
def supplement_dir(catalog_dir):
    return os.path.join(catalog_dir, SUPPLEMENT)


def has_supplement(catalog_dir):
    """Is there a complete supplement in this catalog's folder? (A format-2 catalog holds those stars itself.)"""
    from pysyzygos import starcat
    if starcat.is_format2(catalog_dir):
        return True
    d = supplement_dir(catalog_dir)
    return os.path.isfile(os.path.join(d, "catalog.json")) and status(d)["complete"]


def use_supplement():
    """Use the supplement where there is one? Env PYSYZYGOS_SUPPLEMENT (0/1, set by the GUI per run), else config
    gaia_supplement (default True)."""
    v = os.environ.get("PYSYZYGOS_SUPPLEMENT")
    if v is not None:
        return v.strip().lower() not in ("0", "false", "no", "off", "")
    try:
        from pysyzygos import config as C
        return bool(getattr(C, "gaia_supplement", True))
    except Exception:
        return True


def star_flag(kind, ruwe=None):
    """Short text for a supplement star: 'RUWE 1.65', '2-param, NO proper motion', '2-param, pm UCAC5', or '' for a
    main-catalog star."""
    try:
        k = int(kind)
    except (TypeError, ValueError):
        return ""
    if k == KIND_RUWE:
        return f"RUWE {float(ruwe):.2f}" if ruwe is not None and np.isfinite(float(ruwe)) else "RUWE >= 1.4"
    if k == KIND_2P:
        return "2-param, NO proper motion"
    return f"2-param, pm {PM_SOURCE[k]}" if k in PM_SOURCE else ""


def pm_source(kind):
    """Where the star's proper motion comes from, by its kind: 'Gaia DR3' (5/6-parameter stars, also high RUWE),
    'UCAC5', 'UCAC4', 'UCAC4 epoch to Gaia' (2-parameter stars: ABOUT.md 2.4.1), or 'none' (2-parameter star
    without any; its 2016.0 position is used)."""
    try:
        k = int(kind)
    except (TypeError, ValueError):
        return ""
    return "none" if k == KIND_2P else PM_SOURCE.get(k, "Gaia DR3")


def star_sigma_mas(kind, ruwe, pos_err, pm_err, years):
    """1-sigma position uncertainty (mas, per axis) of a supplement star `years` after Gaia's 2016.0, or None for a
    main-catalog star (its Gaia errors are tiny; the online check adds them). 2-parameter star: position error and the
    proper motion's error (cross-matched) or, without one, an unknown motion of PM_UNKNOWN_MAS_YR per axis, times the
    years. High-RUWE star: Gaia's errors scaled by RUWE (they are underestimated for such stars), position + motion."""
    try:
        k = int(kind)
    except (TypeError, ValueError):
        return None
    f = lambda x, d: d if x is None or not np.isfinite(float(x)) or float(x) <= 0 else float(x)
    t = max(float(years), 0.0)
    if k == KIND_2P or k in PM_SOURCE:
        pm = PM_UNKNOWN_MAS_YR if k == KIND_2P else f(pm_err, PM_UNKNOWN_MAS_YR)
        return float(np.hypot(f(pos_err, 1.0), pm * t))
    if k == KIND_RUWE:
        e = f(pos_err, 0.1) * max(f(ruwe, 1.4), 1.0)
        return float(np.hypot(e, e * t))                     # Gaia's pm error ~ its position error per year
    return None


def _frame(arr):
    """DataFrame of catalog rows (DTYPE or SUPP_DTYPE): COLS + star_kind (0 main) + ruwe (NaN for main: < 1.4)."""
    df = pd.DataFrame({k: arr[k].astype(np.float64) if k != "source_id" else arr[k] for k in COLS})
    names = arr.dtype.names or ()
    df["star_kind"] = arr["kind"].astype(np.int64) if "kind" in names else 0
    df["ruwe"] = arr["ruwe"].astype(np.float64) if "ruwe" in names else np.nan
    df["pos_err"] = np.maximum(arr["ra_error"], arr["dec_error"]).astype(np.float64) \
        if "ra_error" in names else np.nan                   # mas at 2016.0 (supplement only)
    df["pm_err"] = arr["pm_error"].astype(np.float64) if "pm_error" in names else np.nan   # cross-matched pm, mas/yr
    return df


# ----------------------------------------------------------------------------------------------- lookup
class LocalGaia:
    """Read side. LocalGaia(dir).corridor_stars(plan) -> DataFrame like the archive query (epoch 2016.0), with
    star_kind / ruwe; with supplement (default use_supplement()) the supplement's stars are merged in, flagged."""

    def __new__(cls, out_dir, allow_partial=False, supplement=None):
        from pysyzygos import starcat
        if starcat.is_format2(out_dir):                              # the new format: its own reader, same methods
            return starcat.StarCatalog(out_dir, supplement=supplement)
        return super().__new__(cls)

    def __init__(self, out_dir, allow_partial=False, supplement=None):
        self.dir = out_dir
        self.sup = None
        if (use_supplement() if supplement is None else supplement) and has_supplement(out_dir):
            self.sup = LocalGaia(supplement_dir(out_dir), supplement=False)
        man = json.load(open(os.path.join(out_dir, "catalog.json")))
        self.gmax = man["gmax"]
        st = status(out_dir)
        if not st["complete"] and not allow_partial:
            raise RuntimeError(f"local Gaia catalog in {out_dir} is incomplete ({st['done']}/{st['total']} files); "
                               f"run: pysyzygos setup  (resumes)")
        self.stems = [n[:-len(".csv.gz")] for n in man["files"]
                      if os.path.isfile(os.path.join(out_dir, n[:-len(".csv.gz")] + ".npy"))]
        self.by_cell = {}
        for i, s in enumerate(self.stems):
            for c in np.load(os.path.join(out_dir, s + ".cells.npy")).tolist():
                self.by_cell.setdefault(c, []).append(i)
        self._hpm = None

    def high_pm(self):
        if self._hpm is None:
            dt = self._dtype()
            self._hpm = np.concatenate([_as_dtype(np.load(os.path.join(self.dir, s + ".hpm.npy")), dt)
                                        for s in self.stems] or [np.empty(0, dt)])
        return self._hpm

    def cone(self, ra_deg, dec_deg, radius_deg, mag_cap=None):
        """Stars (DataFrame, epoch 2016.0) within radius_deg of (ra, dec), G <= mag_cap. For small fields (previews)."""
        from pysyzygos.corridor import _unit
        cap = self.gmax if mag_cap is None else min(mag_cap, self.gmax)
        c = _unit(ra_deg, dec_deg)
        files = sorted({i for k in cells_near([ra_deg], [dec_deg], [radius_deg]).tolist() for i in self.by_cell.get(k, ())})
        parts = []
        for i in files:
            a = np.load(os.path.join(self.dir, self.stems[i] + ".npy"), mmap_mode="r")
            a = a[a["phot_g_mean_mag"] <= cap]
            if len(a):
                parts.append(np.asarray(a[_unit(a["ra"], a["dec"]) @ c >= math.cos(math.radians(radius_deg))]))
        dt = self._dtype()
        df = _frame(np.concatenate([_as_dtype(p, dt) for p in parts]) if parts else np.empty(0, dt))
        if self.sup is not None:
            df = pd.concat([df, self.sup.cone(ra_deg, dec_deg, radius_deg, mag_cap)], ignore_index=True)
        return df

    def _dtype(self):
        return SUPP_DTYPE if json.load(open(os.path.join(self.dir, "catalog.json"))).get("kind") == "supplement" \
            else DTYPE

    def corridor_stars(self, plan, include_high_pm=True, chunk_deg=0.05):
        """Stars (G <= plan mag_cap) within margin_km/distance + pad of the plan's path, plus the high-pm stars."""
        from pysyzygos.corridor import _radec, _unit
        path = plan["path"]
        U, D = path["u"], path["delta_km"]
        w = np.degrees(plan["margin_km"] / D) + plan["pad_arcsec"] / 3600.0              # half-width per sample, deg
        cap = plan["mag_cap"]
        if cap > self.gmax + 1e-9 and not self.dir.endswith(SUPPLEMENT):
            print(f"{plan['target']}: magnitude cap {cap:.1f} is fainter than the local catalog (G <= {self.gmax}); using {self.gmax}")
        ra, dec = _radec(U)
        files = sorted({i for c in cells_near(ra, dec, 1.5 * w).tolist() for i in self.by_cell.get(c, ())})
        parts = []
        for i in files:
            a = np.load(os.path.join(self.dir, self.stems[i] + ".npy"), mmap_mode="r")
            a = a[a["phot_g_mean_mag"] <= cap]
            if len(a):
                parts.append(np.asarray(a[near_path_mask(_unit(a["ra"], a["dec"]), U, w, chunk_deg)]))
        if include_high_pm:
            h = self.high_pm()
            parts.append(h[h["phot_g_mean_mag"] <= cap])
        dt = self._dtype()
        df = _frame(np.concatenate([_as_dtype(p, dt) for p in parts]) if parts else np.empty(0, dt))
        if self.sup is not None:
            sp = dict(plan, mag_cap=min(cap, self.sup.gmax))
            df = pd.concat([df, self.sup.corridor_stars(sp, include_high_pm, chunk_deg)], ignore_index=True)
        return df.drop_duplicates("source_id").reset_index(drop=True)


def index_gmax(mag_limit):
    """Limit of the bright-star index serving a magnitude limit: whole magnitudes, at least 15, so changing the
    aperture does not build a new index every time."""
    return max(15.0, float(math.ceil(mag_limit - 1e-9)))


class BrightIndex:
    """Stars with G <= gmax (default 15, ~32 M stars, 1.3 GB) from the local catalog, sorted by a fine sky cell and,
    within a cell, by magnitude (so a lookup with a bright cap reads only the bright end of each cell). For screening many
    asteroids at once (screen.py). Built once from the catalog (~15 s) and saved next to it as
    bright_G<gmax>.v2.npy + .v2.offsets.npy; opened memory-mapped."""
    CELL = 0.25                                                                       # deg

    def __init__(self, catalog_dir, gmax=15.0):
        self.dir, self.gmax = catalog_dir, float(gmax)
        stem = os.path.join(catalog_dir, f"bright_G{self.gmax:.1f}.v2")
        if not (os.path.isfile(stem + ".npy") and os.path.isfile(stem + ".offsets.npy")):
            self._build(stem)
        self.stars = np.load(stem + ".npy", mmap_mode="r")
        self.offsets = np.load(stem + ".offsets.npy")

    def _build(self, stem):
        man = json.load(open(os.path.join(self.dir, "catalog.json")))
        if man["gmax"] < self.gmax:
            raise ValueError(f"local catalog goes to G {man['gmax']}, cannot index G <= {self.gmax}")
        if not status(self.dir)["complete"]:
            raise RuntimeError(f"local Gaia catalog in {self.dir} is incomplete; run: pysyzygos setup")
        # Low-memory build (any limit, any RAM): 1) count stars per cell, 2) write each file's stars into their cell's
        # slots of a memory-mapped output, 3) sort each cell by G, a block of cells at a time. Peak memory: one source
        # file's selection or one block, not the whole index (a G <= 16 index is ~3.7 GB, G <= 18 ~11 GB).
        t0 = time.time()
        files = [os.path.join(self.dir, n[:-len(".csv.gz")] + ".npy") for n in man["files"]]
        n_cells = int(round(180 / self.CELL)) * int(round(360 / self.CELL))
        counts, dtype = np.zeros(n_cells, np.int64), None
        prog = Progress(f"bright-star index G <= {self.gmax:g}", 2 * len(files), fmt=lambda x: f"{x:.0f} file reads",
                        rate=lambda r: f"{r:.0f} files/s")

        def selected(path):
            a = np.load(path, mmap_mode="r")
            sel = np.asarray(a[np.asarray(a["phot_g_mean_mag"]) <= self.gmax])
            return sel, cell_of(sel["ra"], sel["dec"], self.CELL)

        for i, f in enumerate(files, 1):
            sel, cell = selected(f)
            counts += np.bincount(cell, minlength=n_cells)
            dtype = sel.dtype
            prog(i)
        offsets = np.concatenate([[0], np.cumsum(counts)]).astype(np.int64)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(stem), suffix=".tmp")
        os.close(fd)
        out = np.lib.format.open_memmap(tmp, mode="w+", dtype=dtype, shape=(int(offsets[-1]),))
        cursor = offsets[:-1].copy()
        for i, f in enumerate(files, 1):
            sel, cell = selected(f)
            order = np.argsort(cell, kind="stable")
            sel, cell = sel[order], cell[order]
            rank = np.arange(len(cell)) - np.searchsorted(cell, cell, side="left")      # place within its cell
            out[cursor[cell] + rank] = sel
            cursor += np.bincount(cell, minlength=n_cells)
            prog(len(files) + i)
        prog.finish("read; sorting by G within cells")
        block, i = 4_000_000, 0
        while i < len(out):
            j = int(offsets[np.searchsorted(offsets, i + block, side="right") - 1])     # end on a cell boundary
            if j <= i:
                j = int(offsets[np.searchsorted(offsets, i, side="right")])           # one cell larger than a block
            blk = np.array(out[i:j])                                  # a copy: a view would keep the file mapped
            out[i:j] = blk[np.lexsort((blk["phot_g_mean_mag"], cell_of(blk["ra"], blk["dec"], self.CELL)))]
            i = j
        out.flush()
        n_stars = len(out)
        blk = None
        del out                                                       # unmapped before the rename (Windows needs it)
        _save_atomic(stem + ".offsets.npy", offsets)                  # offsets first: the .npy of the stars marks done
        replace_file(tmp, stem + ".npy")
        print(f"bright-star index G <= {self.gmax}: {n_stars / 1e6:.1f} M stars in {time.time() - t0:.0f} s -> {stem}.npy")

    def near_path(self, U, w_deg, mag_cap=None, sample_deg=None):
        """Stars (structured array) within w_deg (per sample) of the path U (m,3 unit vectors), G <= mag_cap.
        A superset of the exact strip (coarse discs); the candidate scan does the exact test."""
        from pysyzygos.corridor import _radec, _unit
        if len(U) == 0:
            return self.stars[:0]
        # cells: path points every ~CELL/5 are enough (the strip is far narrower than a cell)
        ang = np.degrees(np.arccos(np.clip(np.sum(U[:-1] * U[1:], axis=1), -1, 1)))
        cum = np.concatenate(([0.0], np.cumsum(ang)))
        pick = np.unique(np.concatenate((np.searchsorted(cum, np.arange(0, cum[-1], sample_deg or self.CELL / 5)),
                                         [len(U) - 1])))
        ra, dec = _radec(U[pick])
        cells = cells_near(ra, dec, 1.5 * float(np.max(w_deg)) + self.CELL / 5, self.CELL)   # + half the sample spacing
        lo, hi = self.offsets[cells], self.offsets[cells + 1]
        if mag_cap is not None and mag_cap < self.gmax:                    # each cell is sorted by G: cut its tail
            g = self.stars["phot_g_mean_mag"]
            hi = np.array([a + np.searchsorted(g[a:b], mag_cap, "right") for a, b in zip(lo, hi)], np.int64)
        idx = np.concatenate([np.arange(a, b) for a, b in zip(lo, hi) if b > a] or [np.empty(0, np.int64)])
        a = np.asarray(self.stars[idx])
        if len(a) == 0:
            return a
        return a[near_path_mask(_unit(a["ra"], a["dec"]), U, w_deg)]


COMMON_DTYPE = np.dtype(DTYPE.descr + [("ruwe", "<f4"), ("kind", "u1")])


def _common(a):
    out = np.zeros(len(a), COMMON_DTYPE)
    for k in DTYPE.names:
        out[k] = a[k]
    names = a.dtype.names or ()
    out["ruwe"] = a["ruwe"] if "ruwe" in names else np.nan
    out["kind"] = a["kind"] if "kind" in names else KIND_MAIN
    return out


class MergedIndex:
    """The bright-star index of a catalog and of its supplement as one: near_path returns COMMON_DTYPE rows (the main
    catalog's fields + ruwe + kind)."""

    def __init__(self, main, sup):
        self.main, self.sup, self.gmax = main, sup, main.gmax

    def near_path(self, U, w_deg, mag_cap=None, sample_deg=None):
        a = self.main.near_path(U, w_deg, mag_cap, sample_deg)
        b = self.sup.near_path(U, w_deg, None if mag_cap is None else min(mag_cap, self.sup.gmax), sample_deg)
        return np.concatenate([_common(a), _common(b)])


def open_index(catalog_dir, gmax, supplement=None):
    """The bright-star index for a pick or pre-screen: the catalog's, merged with its supplement's when there is one
    and it is in use (use_supplement()). Builds missing indexes (main process before workers start). A format-2
    catalog is its own index (sorted by cell and G)."""
    from pysyzygos import starcat
    if starcat.is_format2(catalog_dir):
        return starcat.StarCatalog(catalog_dir, supplement=supplement)
    main = BrightIndex(catalog_dir, gmax)
    if (use_supplement() if supplement is None else supplement) and has_supplement(catalog_dir):
        sd = supplement_dir(catalog_dir)
        sg = min(float(gmax), float(json.load(open(os.path.join(sd, "catalog.json")))["gmax"]))
        return MergedIndex(main, BrightIndex(sd, sg))
    return main


def default_dir():
    try:
        from pysyzygos import config as C
        return getattr(C, "gaia_local_dir", None), getattr(C, "gaia_local_gmax", 16.0)
    except ImportError:
        return None, 16.0


def main():
    d0, g0 = default_dir()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=f"PySyzygos {__version__}")
    ap.add_argument("cmd", choices=["build", "supplement", "supplement-pm", "status", "zenodo"],
                    help="supplement: build (or resume) <dir>/supplement, the high-RUWE and 2-parameter stars")
    ap.add_argument("--dir", default=d0 or "gaia_dr3_local", help="catalog folder (default: config gaia_local_dir)")
    ap.add_argument("--gmax", type=float, default=g0, help="faintest G kept (default: config gaia_local_gmax or 16)")
    ap.add_argument("--workers", type=int, default=6, help="parallel download/parse processes")
    ap.add_argument("--keep-archive", action="store_true", help="zenodo: keep the downloaded .tar.xz")
    ap.add_argument("--source", choices=["zenodo", "esa"], default="zenodo",
                    help="supplement: ready-made from Zenodo (G 16, minutes; default) or built from ESA's files (~2 h)")
    a = ap.parse_args()
    if a.cmd == "build":
        build(a.dir, a.gmax, a.workers)
    elif a.cmd == "supplement-pm":
        supplement_pm(a.dir)
    elif a.cmd == "supplement":
        if a.source == "zenodo" and float(a.gmax) in ZENODO_SUPPLEMENT:
            fetch_zenodo(a.dir, a.gmax, a.keep_archive, supplement=True)
        else:
            build(a.dir, a.gmax, a.workers, supplement=True)
        if has_supplement(a.dir):
            if not has_supplement_pm(a.dir):                     # proper motions for its 2-parameter stars
                supplement_pm(a.dir)
            BrightIndex(supplement_dir(a.dir), 15.0)
    elif a.cmd == "zenodo":
        if fetch_zenodo(a.dir, a.gmax, a.keep_archive)["complete"]:
            BrightIndex(a.dir, 15.0)                                         # for pick.py
    else:
        print(status(a.dir))


if __name__ == "__main__":
    sys.exit(main())
