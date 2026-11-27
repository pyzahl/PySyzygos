"""prescreen_slices.py - shared whole-Earth pre-screens in slices, downloaded on demand.

A whole-Earth pre-screen of 70 days at G 16 is ~9 GB (86 M events + index), and xz packs it only to ~7 GB. Most of it
is faint stars (G 15-16: ~58 % of the events) and small asteroids (H >= 17: about half). So the publisher splits it
into disjoint slices by star magnitude G and asteroid H (`split`), each slice sorted by time, uncompressed, with a
table of the row where each UTC day starts and SHA-256 checksums per block of rows. A user downloads only the slices
up to their own limits and only the rows of their window (HTTP Range requests: the mirror only has to serve files),
and `fetch` merges them into one ordinary local whole-Earth pre-screen (<name>.global.npy + .idx.npy + .json), which
the pick uses as before.

    pysyzygos prescreen split prescreen/<global>.global.npy --to SHARE [--synced]       # publisher (manager)
    pysyzygos prescreen fetch [name] --start 2026-12-01 --days 30 --gmax 15 [--hmax 17]   # user

Mirror: SHARE/prescreen_slices.json (the list; prescreens.json, the packed archives' list, stays as it is, so older
PySyzygos versions are not affected) and SHARE/<name>.slices/<name>.<key>.npy + .idx.npy per slice. Slice keys:
G-13_H-17 (G <= 13, H < 17), G13-14_H-17, ..., G15-16_H17- (H >= 17).
Rows kept by fetch: the tracks touching the window (+- each event's half duration, as select()), G <= gmax.
Window boundaries: UTC days of the published window (ET from its et0 plus whole days: leap seconds inside the window
would shift by a second; none are scheduled).
"""
from pysyzygos.version import __version__
import datetime as dt, hashlib, json, math, os, shutil, sys, time
import numpy as np
from pysyzygos import prescreen as PS
from pysyzygos import shadowtrack as ST

MANIFEST = "prescreen_slices.json"
G_EDGES = (13.0, 14.0, 15.0, 16.0)          # slices: G <= 13, 13 < G <= 14, ..., up to the build's cam_limit
H_SPLIT = 17.0                              # H < 17 (the pick's hmax 17), H >= 17
BLOCK_ROWS = 250_000                        # rows per checksum block (20 MB of events, 6 MB of index)
CHUNK = 2_000_000                           # rows per pass while splitting / merging (memory-mapped files)
G_TOL = 1e-4                                # as PS.select: a star of exactly the limit is in


def _fmt(x):
    return "" if x is None else f"{x:g}"


def slice_key(g_lo, g_hi, h_lo, h_hi):
    return f"G{_fmt(g_lo)}-{_fmt(g_hi)}_H{_fmt(h_lo)}-{_fmt(h_hi)}"


def bands(edges, cam_limit):
    """[(lo, hi)] magnitude bands: (None, e0), (e0, e1), ..., the last up to max(last edge, cam_limit)."""
    e = sorted(float(x) for x in edges if float(x) < float(cam_limit) - 1e-9) + [float(cam_limit)]
    return list(zip([None] + e[:-1], e))


def h_by_number(cache=None):
    """float32 array: H of each numbered asteroid (NaN where unknown), from the SBDB bulk list (pick's cache)."""
    import tempfile
    from pysyzygos import pick as P
    fields, data, _ = P.fetch_sbdb(None, cache or os.path.join(tempfile.gettempdir(), "PySyzygos_sbdb_cache.json"))
    i_s, i_h = fields.index("spkid"), fields.index("H")
    nums, hs = [], []
    for r in data:
        try:
            spk, h = int(r[i_s]), float(r[i_h])
        except (TypeError, ValueError):
            continue
        nums.append(spk - 20000000 if spk >= 20000000 else spk - 2000000)
        hs.append(h)
    out = np.full(max(nums) + 1 if nums else 1, np.nan, np.float32)
    out[np.array(nums)] = hs
    return out


def _sha(b):
    return hashlib.sha256(b).hexdigest()


def _data_offset(path, rows, itemsize):
    return os.path.getsize(path) - rows * itemsize


# ---------------------------------------------------------------------------------------------- publisher
def split(path, dest, g_edges=G_EDGES, h_split=H_SPLIT, h_of=None, sbdb_cache=None, block_rows=BLOCK_ROWS,
          synced=False, log=print):
    """Cut a whole-Earth pre-screen into slices (G bands x H < h_split / >= h_split) in dest/<name>.slices/, and add its
    entry to dest/prescreen_slices.json (replacing one of the same name). h_of: array of H by asteroid number
    (default: the SBDB list); an unknown H counts as small H (the slice every user takes). synced: dest is the mirror's
    own folder (its list is the mirror's: entries whose folder is gone are left out). Returns the entry."""
    if not PS.is_global(path):
        sys.exit("only whole-Earth pre-screens (.global.npy) are sliced")
    m = PS.read_meta(path)
    if not PS.has_index(path):
        log("no index yet: building it first")
        PS.index(path)
    name = os.path.basename(path)[:-len(".global.npy")]
    a = np.load(path, mmap_mode="r")
    ix = np.load(PS._idx_path(path), mmap_mode="r")
    n = len(a)
    h_of = h_by_number(sbdb_cache) if h_of is None else np.asarray(h_of, np.float32)
    gb = bands(g_edges, m["cam_limit"])
    hb = [(None, float(h_split)), (float(h_split), None)]
    inner = np.array([hi for _, hi in gb[:-1]]) + G_TOL

    def sid(lo, hi):                                            # slice number of rows lo:hi
        num = np.asarray(a["number"][lo:hi])
        h = np.full(len(num), np.nan, np.float32)
        ok = (num >= 0) & (num < len(h_of))
        h[ok] = h_of[num[ok]]
        return np.searchsorted(inner, np.asarray(a["g"][lo:hi]), side="left") * 2 + (h >= h_split)

    t0 = time.time()
    counts = np.zeros(len(gb) * 2, np.int64)
    for lo in range(0, n, CHUNK):
        counts += np.bincount(sid(lo, min(n, lo + CHUNK)), minlength=len(counts))
    folder = os.path.join(dest, name + ".slices")
    tmp = folder + ".part"
    if os.path.isdir(tmp):
        shutil.rmtree(tmp)
    os.makedirs(tmp)
    keys, ev, ex = [], [], []
    for gi, (glo, ghi) in enumerate(gb):
        for hi_, (hlo, hhi) in enumerate(hb):
            k = slice_key(glo, ghi, hlo, hhi)
            c = int(counts[gi * 2 + hi_])
            keys.append((k, glo, ghi, hlo, hhi))
            ev.append(np.lib.format.open_memmap(os.path.join(tmp, f"{name}.{k}.npy"), "w+", ST.DTYPE, (c,)))
            ex.append(np.lib.format.open_memmap(os.path.join(tmp, f"{name}.{k}.idx.npy"), "w+", ix.dtype, (c,)))
    log(f"{name}: {n} events into {len(keys)} slices ({', '.join(f'{k[0]} {c}' for k, c in zip(keys, counts))})")
    cur = np.zeros(len(keys), np.int64)
    for lo in range(0, n, CHUNK):
        hi = min(n, lo + CHUNK)
        s = sid(lo, hi)
        blk, iblk = np.array(a[lo:hi]), np.array(ix[lo:hi])
        for j in range(len(keys)):
            mk = s == j
            c = int(mk.sum())
            if c:
                ev[j][cur[j]:cur[j] + c] = blk[mk]               # source sorted by time: each slice stays sorted
                ex[j][cur[j]:cur[j] + c] = iblk[mk]
                cur[j] += c
        log(f"   {hi}/{n} rows ({hi / n:.0%}), {PS._hms(time.time() - t0)}")
    et0 = float(m["et0"])
    slices = []
    for j, (k, glo, ghi, hlo, hhi) in enumerate(keys):
        e, x = ev[j], ex[j]
        e.flush()
        x.flush()
        rows = len(e)
        et = np.asarray(e["et"])
        if rows:
            k0 = int(math.floor((et[0] - et0) / 86400.0))
            k1 = int(math.ceil((et[-1] - et0) / 86400.0)) + 1
        else:
            k0 = k1 = 0
        day_rows = np.searchsorted(et, et0 + 86400.0 * np.arange(k0, k1 + 1), side="left").tolist()
        blocks = [[_sha(np.array(e[b:b + block_rows]).tobytes()), _sha(np.array(x[b:b + block_rows]).tobytes())]
                  for b in range(0, rows, block_rows)]
        f_ev, f_ix = f"{name}.{k}.npy", f"{name}.{k}.idx.npy"
        del et
        slices.append(dict(key=k, g_lo=glo, g_hi=ghi, h_lo=hlo, h_hi=hhi, file=f_ev, idx_file=f_ix, rows=rows,
                           offset=_data_offset(os.path.join(tmp, f_ev), rows, ST.DTYPE.itemsize),
                           idx_offset=_data_offset(os.path.join(tmp, f_ix), rows, ix.dtype.itemsize),
                           bytes=os.path.getsize(os.path.join(tmp, f_ev)), idx_bytes=os.path.getsize(os.path.join(tmp, f_ix)),
                           day0=k0, day_rows=day_rows, blocks=blocks))
    del ev, ex, e, x                                        # unmapped before the rename (Windows)
    if os.path.isdir(folder):
        shutil.rmtree(folder)
    os.replace(tmp, folder)
    entry = {k: m.get(k) for k in PS.SHARE_KEYS}
    entry.update(name=name, kind="sliced", catalog=PS.catalog_info(m.get("catalog", "")), folder=name + ".slices",
                 g_edges=[float(x) for x in g_edges], h_split=float(h_split), block_rows=int(block_rows),
                 itemsize=ST.DTYPE.itemsize, idx_itemsize=int(ix.dtype.itemsize), dtype=str(ST.DTYPE.descr),
                 idx_dtype=str(ix.dtype.descr), slices=slices, total_bytes=sum(s["bytes"] + s["idx_bytes"] for s in slices),
                 published=time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()), published_with=__version__)
    mp = os.path.join(dest, MANIFEST)
    lists = [load(mp)]
    man = merge([x for x in lists if x] + [dict(prescreens=[entry])])
    if synced:
        man = dict(man, prescreens=[e for e in man["prescreens"] if folder_ok(dest, e)])
    write(man, mp)
    log(f"{folder}: {len(slices)} slices, {entry['total_bytes'] / 1e9:.2f} GB in {PS._hms(time.time() - t0)}; "
        f"{mp}: {len(man['prescreens'])} sliced pre-screen(s)")
    return entry


def load(src):
    return PS.load_manifest(src)


def merge(mans):
    out = PS.merge_manifests(mans)
    return dict(out, about="PySyzygos shared pre-screens in slices: pysyzygos prescreen fetch NAME --gmax G --start D --days N")


def write(man, path):
    PS.write_manifest(man, path)


def folder_state(dest, e):
    """'ok' (every slice file there with its size), 'incomplete' (some there) or 'missing' in a local share folder."""
    d = os.path.join(dest, e["folder"])
    if not os.path.isdir(d):
        return "missing"
    good = all(os.path.isfile(os.path.join(d, s[f])) and os.path.getsize(os.path.join(d, s[f])) == s[b]
               for s in e["slices"] for f, b in (("file", "bytes"), ("idx_file", "idx_bytes")))
    return "ok" if good else "incomplete"


def folder_ok(dest, e):
    return folder_state(dest, e) != "missing"


def withdraw(name, dest, log=print):
    """Drop a sliced pre-screen from dest's list and delete its folder. Returns True if anything was there."""
    mp = os.path.join(dest, MANIFEST)
    man = load(mp) or dict(prescreens=[])
    keep = [e for e in man.get("prescreens", []) if e.get("name") != name]
    found = len(keep) != len(man.get("prescreens", []))
    for d in (os.path.join(dest, name + ".slices"), os.path.join(dest, name + ".slices.part")):
        if os.path.isdir(d):
            shutil.rmtree(d)
            found = True
            log(f"   deleted {d}")
    if os.path.exists(mp):
        write(merge([dict(prescreens=keep)]), mp)
    return found


# ---------------------------------------------------------------------------------------------- user
def remote_list(mirror_list=None, log=print):
    """(mirror, sliced list) of the first mirror that has one, or (None, None)."""
    for mr in (PS.mirrors() if mirror_list is None else mirror_list):
        try:
            return mr, json.loads(PS._get(mr + MANIFEST))
        except Exception as e:
            log(f"   {mr}: no sliced list ({str(e)[:80]})")
    return None, None


def _range(url, start, length, retries=3):
    """length bytes of url from start (file:// or HTTP Range)."""
    if url.startswith("file://"):
        with open(url[len("file://"):], "rb") as f:
            f.seek(start)
            return f.read(length)
    import requests
    last = None
    for k in range(retries):
        try:
            r = requests.get(url, headers={"Range": f"bytes={start}-{start + length - 1}"}, timeout=120)
            if r.status_code == 206 and len(r.content) == length:
                return r.content
            if r.status_code == 200:
                raise RuntimeError(f"{url}: the server ignores byte ranges")
            last = f"HTTP {r.status_code}, {len(r.content)} bytes"
        except RuntimeError:
            raise
        except Exception as e:
            last = str(e)[:120]
        time.sleep(2 * (k + 1))
    raise RuntimeError(f"{url}: bytes {start}+{length}: {last}")


def choose(e, gmax=None, hmax=None):
    """The slices of entry e a pick with star limit gmax and H limit hmax (None: all) needs, and the merged file's
    (cam_limit, hmax)."""
    gmax = float(e["cam_limit"]) if gmax is None else min(float(gmax), float(e["cam_limit"]))
    out = [s for s in e["slices"] if (s["g_lo"] is None or s["g_lo"] < gmax - 1e-9)
           and (hmax is None or s["h_lo"] is None or s["h_lo"] < float(hmax) - 1e-9)]
    big_h = any(s["h_hi"] is None for s in out)
    m_hmax = e.get("hmax") if big_h else max(s["h_hi"] for s in out)
    if m_hmax is not None and e.get("hmax") is not None:
        m_hmax = min(m_hmax, e["hmax"])
    return out, gmax, m_hmax


def window_et(e, start, days):
    """ET of the requested window (start: UTC date) from the entry's et0 (whole days from its start)."""
    d0 = (dt.date.fromisoformat(str(start)) - dt.date.fromisoformat(str(e["start"]))).days
    w0 = float(e["et0"]) + d0 * 86400.0
    return w0, w0 + float(days) * 86400.0


def out_name(start, days, gmax, hmax):
    return f"global__{start}_{float(days):g}d_G{float(gmax):g}" + ("" if hmax is None else f"_H{float(hmax):g}")


def span(e):
    """(first day, end day) of an entry's window (UTC dates)."""
    s0 = dt.date.fromisoformat(str(e["start"]))
    return s0, s0 + dt.timedelta(days=float(e["days"]))


def plan_fetch(e, start=None, days=None, gmax=None, hmax=None):
    """What a fetch of entry e downloads: (start, days, slices, cam_limit, hmax of the merged file, w0, w1, plan
    [(slice, first block, last block + 1)], bytes). start/days default to the whole window (days: to its end);
    ValueError for a window outside it. Also the GUI's size estimate."""
    e_start, e_end = span(e)
    start = dt.date.fromisoformat(str(start)) if start else e_start
    days = float(days) if days else float((e_end - start).days)
    if start < e_start or start + dt.timedelta(days=days) > e_end or days <= 0:
        raise ValueError(f"window {start} + {days:g} d not inside {e['name']} ({e_start} .. {e_end})")
    sl, g_lim, m_hmax = choose(e, gmax, hmax)
    w0, w1 = window_et(e, start, days)
    a0, a1 = w0 - PS.HALF_MAX_S, w1 + PS.HALF_MAX_S
    br, isz, xsz = int(e["block_rows"]), int(e["itemsize"]), int(e["idx_itemsize"])
    plan = []
    for s in sl:
        if not s["rows"]:
            continue
        j0 = max(0, int(math.floor((a0 - float(e["et0"])) / 86400.0)) - s["day0"])
        j1 = min(len(s["day_rows"]) - 1, int(math.ceil((a1 - float(e["et0"])) / 86400.0)) - s["day0"])
        r0 = s["day_rows"][min(j0, len(s["day_rows"]) - 1)]
        r1 = s["day_rows"][max(j1, 0)] if j1 < len(s["day_rows"]) - 1 else s["rows"]
        if r1 > r0:
            plan.append((s, r0 // br, (r1 - 1) // br + 1))
    need = sum((min(b1 * br, s["rows"]) - b0 * br) * (isz + xsz) for s, b0, b1 in plan)
    return start, days, sl, g_lim, m_hmax, w0, w1, plan, need


def fit_window(e, start, days):
    """The pick's window clipped to entry e's: (start, days), or None if they do not overlap."""
    e_start, e_end = span(e)
    try:
        s0 = dt.date.fromisoformat(str(start))
    except (TypeError, ValueError):
        s0 = e_start
    s1 = s0 + dt.timedelta(days=float(days or 1))
    a, b = max(s0, e_start), min(s1, e_end)
    return (a, float((b - a).days)) if b > a else None


def fetch(name="latest", start=None, days=None, gmax=None, hmax=None, folder=PS.DIR, mirror_list=None, log=print):
    """Download the slices of a shared sliced pre-screen a pick needs (stars to gmax, asteroids to hmax (None: all),
    the window start + days, default the whole one) and merge them into one local whole-Earth pre-screen. Blocks are
    checked against their SHA-256 and kept until the merge (a rerun resumes). Returns the .global.npy path."""
    mr, man = remote_list(mirror_list, log)
    if not man:
        sys.exit("no mirror has sliced pre-screens (offline?)")
    e = PS._choose(man.get("prescreens", []), name)
    if e is None:
        sys.exit(f"no sliced pre-screen '{name}'; available: " + ", ".join(x["name"] for x in man.get("prescreens", [])))
    try:
        start, days, sl, g_lim, m_hmax, w0, w1, plan, need = plan_fetch(e, start, days, gmax, hmax)
    except ValueError as x:
        sys.exit(str(x))
    br, isz, xsz = int(e["block_rows"]), int(e["itemsize"]), int(e["idx_itemsize"])
    idx_dtype = ST.IDX_DTYPE
    if xsz != idx_dtype.itemsize or isz != ST.DTYPE.itemsize:
        sys.exit(f"{e['name']}: records of {isz}/{xsz} B, this version reads {ST.DTYPE.itemsize}/{ST.IDX_DTYPE.itemsize} B: update PySyzygos")
    os.makedirs(folder, exist_ok=True)
    if shutil.disk_usage(folder).free < 2.2 * need:
        sys.exit(f"not enough disk space in {folder}: ~{2.2 * need / 1e9:.1f} GB needed")
    base = out_name(start, days, g_lim, m_hmax)
    have = os.path.join(folder, base + ".global.npy")
    if os.path.isfile(have) and os.path.isfile(PS._meta_path(have)):      # the same window and limits, finished
        if str(PS.read_meta(have).get("built")) == str(e.get("built")):
            log(f"{have}: already here (the same build, window and limits)")
            return have
    log(f"{e['name']}: {start} + {days:g} d, G <= {g_lim:g}, H {'all' if m_hmax is None else f'< {m_hmax:g}'}: "
        f"{len(plan)} slice(s), ~{need / 1e9:.2f} GB to download from {mr} (whole pre-screen "
        f"{e['total_bytes'] / 1e9:.1f} GB)")
    cache = os.path.join(folder, f".{base}.fetch")
    os.makedirs(cache, exist_ok=True)
    url = mr + e["folder"] + "/"
    t0, got = time.time(), 0
    for s, b0, b1 in plan:
        for b in range(b0, b1):
            n_b = min(br, s["rows"] - b * br)
            ok = True
            for f, off, sz, h in ((s["file"], s["offset"], isz, s["blocks"][b][0]),
                                  (s["idx_file"], s["idx_offset"], xsz, s["blocks"][b][1])):
                p = os.path.join(cache, f"{f}.{b}")
                if os.path.isfile(p) and os.path.getsize(p) == n_b * sz:
                    with open(p, "rb") as fh:
                        if _sha(fh.read()) == h:
                            continue                                 # downloaded before (resume)
                data = _range(url + f, off + b * br * sz, n_b * sz)
                if _sha(data) != h:
                    ok = False
                    break
                with open(p + ".tmp", "wb") as fh:
                    fh.write(data)
                os.replace(p + ".tmp", p)
                got += len(data)
            if not ok:
                sys.exit(f"{s['key']} block {b}: SHA-256 mismatch (the mirror changed or a broken transfer); run again")
        log(f"   {s['key']}: blocks {b0}..{b1 - 1}, {PS._hms(time.time() - t0)}, {got / 1e6:.0f} MB downloaded")
    # merge: the rows of the window (track touches it) and G <= limit, sorted by time
    def blocks():
        for s, b0, b1 in plan:
            for b in range(b0, b1):
                ev = np.fromfile(os.path.join(cache, f"{s['file']}.{b}"), ST.DTYPE)
                ex = np.fromfile(os.path.join(cache, f"{s['idx_file']}.{b}"), idx_dtype)
                mk = (ev["et"] + ev["half"] >= w0) & (ev["et"] - ev["half"] <= w1) & (ev["g"] <= g_lim + G_TOL)
                yield ev[mk], ex[mk]
    n = sum(len(x) for x, _ in blocks())
    out = os.path.join(folder, base + ".global.npy")
    tmp_e, tmp_x = out + ".unsorted.npy", out + ".unsorted.idx.npy"
    ue = np.lib.format.open_memmap(tmp_e, "w+", ST.DTYPE, (n,))
    ux = np.lib.format.open_memmap(tmp_x, "w+", idx_dtype, (n,))
    i = 0
    for ev, ex in blocks():
        ue[i:i + len(ev)], ux[i:i + len(ev)] = ev, ex
        i += len(ev)
    order = np.argsort(ue["et"], kind="stable")
    se = np.lib.format.open_memmap(out + ".part.npy", "w+", ST.DTYPE, (n,))
    sx = np.lib.format.open_memmap(PS._idx_path(out) + ".part.npy", "w+", idx_dtype, (n,))
    for c in range(0, n, CHUNK):
        o = order[c:c + CHUNK]
        se[c:c + len(o)], sx[c:c + len(o)] = ue[o], ux[o]
    n_ast = int(len(np.unique(se["number"]))) if n else 0
    se.flush()
    sx.flush()
    del ue, ux, se, sx, order
    PS.L_replace(out + ".part.npy", out)
    PS.L_replace(PS._idx_path(out) + ".part.npy", PS._idx_path(out))
    for p in (tmp_e, tmp_x):
        os.remove(p)
    meta = {k: e.get(k) for k in PS.SHARE_KEYS}
    meta.update(name="global", kind="global", start=str(start), days=days, et0=w0, et1=w1, cam_limit=g_lim,
                hmax=m_hmax, n_events=n, n_asteroids=n_ast, dtype=str(ST.DTYPE.descr), region=None,
                catalog=(e.get("catalog") or {}).get("folder", ""), sliced_from=e["name"],
                slices=[s["key"] for s, _, _ in plan], fetched=time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()))
    with open(PS._meta_path(out) + ".tmp", "w") as f:
        json.dump(meta, f, indent=1)
    os.replace(PS._meta_path(out) + ".tmp", PS._meta_path(out))       # last: list_files sees it only now
    shutil.rmtree(cache, ignore_errors=True)
    log(f"{out}: {n} events of {n_ast} asteroids, ready (pick --prescreen auto uses it)")
    return out
