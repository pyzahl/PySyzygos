"""starinfo.py - known double stars (WDS) and variable stars (AAVSO VSX) at each result's star.

After a search (search.star_info_check, like the Gaia online double check) every event star is looked up in
    WDS  the Washington Double Star Catalog (Mason+; maintained at Georgia State University since 2025, the
         current file: URL_WDS_SUMMARY): measured pairs with first/last PA and separation, magnitudes, notes;
    VSX  the AAVSO International Variable Star Index (Watson+): known and suspected variables, type, range, period.
Where:
    local    the copies in <data folder>/star_info/ (optional, `pysyzygos star-info add wds|vsx`, System tab):
             wds.npy (WDS from GSU, ~160k rows, ~15 MB) and vsx.npy (VSX from the VizieR archive, the 2.1 GB vsx.dat
             streamed, only rows with a brightest magnitude <= mag_max kept: G 16 ~5 M rows, ~0.2 GB), each sorted
             by RA, + <name>.json (source, server date, rows). Look-up < 1 ms per star, offline.
    online   one VizieR cone per star (B/wds/wds and B/vsx/vsx in one request; CDS, else CfA; ONLINE_THREADS at a
             time): ~0.15-0.4 s per request (measured 2026-11-21), ~10 s per 100 event stars. VizieR's WDS copy
             lags GSU's by days to weeks.
    mode     config star_info / env PYSYZYGOS_STAR_INFO (GUI System checkbox): auto (local copy when installed,
             else online), local, online, off. Online stops after ONLINE_MAX stars (a run warning: the local copies
             have no such limit).
Match: WDS rows whose primary lies within WDS_RADIUS of the star, or whose companion does (the star may be the B
component: primary position + last PA/separation); VSX rows within VSX_RADIUS with a magnitude range the star's G
fits (+- VSX_DMAG; other bands than G/V: wider). Both positions are tested at the event and moved back to J2000 with
the star's proper motion (WDS/VSX positions are J2000; many VSX ones Gaia's at 2016: within the radius either way).
Record fields (end of the record): wds, wds_sep_arcsec, wds_dmag, var, var_type, var_amp_mag, star_info.
Reference only: the drop and the path do not use them.
"""
import json, math, os, sys, time
import numpy as np

from pysyzygos.version import __version__
from pysyzygos import urls as U

FOLDER = "star_info"
WDS_RADIUS = 5.0              # arcsec, primary or companion position vs the star
VSX_RADIUS = 3.0              # arcsec
ROLE_MIN = 1.0               # arcsec: the star is called the companion only when the primary is further off
SEARCH_ARCSEC = 60.0          # local/online cone: primaries up to this far (the star may be a companion)
VSX_DMAG = 1.5                # the star's G within the variable's range +- this (G, V bands; others 2 x)
VSX_MAG_MAX = 17.0            # local copy: rows brighter than this at maximum (G 16 catalog + colour margin)
ONLINE_THREADS = 3
ONLINE_MAX = 500              # online look-ups per run (more: the local copies)
ONLINE_TIMEOUT = 30
FIELDS = ("wds", "wds_sep_arcsec", "wds_dmag", "var", "var_type", "var_amp_mag", "star_info")

WDS_DT = np.dtype([("ra", "<f8"), ("dec", "<f8"), ("wds", "S10"), ("disc", "S7"), ("comp", "S5"), ("first", "<i2"),
                   ("last", "<i2"), ("nobs", "<i2"), ("pa1", "<i2"), ("pa2", "<i2"), ("sep1", "<f4"), ("sep2", "<f4"),
                   ("mag1", "<f4"), ("mag2", "<f4"), ("sp", "S9"), ("notes", "S4")])
VSX_DT = np.dtype([("ra", "<f8"), ("dec", "<f8"), ("oid", "<u4"), ("vflag", "u1"), ("type", "S12"), ("max", "<f4"),
                   ("min", "<f4"), ("amp", "u1"), ("band", "S4"), ("period", "<f4")])
VSX_LRECL = 209               # vsx.dat: fixed-width lines (+ newline)
VFLAG = {0: "", 1: "suspected", 2: "constant or not existing", 3: "possible duplicate"}
CATALOGS = {
    "wds": dict(text="Washington Double Star Catalog (GSU, current)", urls=lambda: [U.URL_WDS_SUMMARY],
                approx="21 MB download, 12 MB kept"),
    "vsx": dict(text="AAVSO Variable Star Index (VizieR copy)", urls=lambda: [U.URL_VSX_DAT] + U.URL_VSX_DAT_MIRRORS,
                approx="2.2 GB streamed (~2 min), 0.29 GB kept"),
}
_CACHE = {}


# ------------------------------------------------------------------------------------------------ files
def folder(base=None):
    return os.path.join(base or os.getcwd(), FOLDER)


def paths(name, base=None):
    d = folder(base)
    return os.path.join(d, f"{name}.npy"), os.path.join(d, f"{name}.json")


def installed(name, base=None):
    npy, meta = paths(name, base)
    return os.path.isfile(npy) and os.path.isfile(meta)


def meta(name, base=None):
    try:
        return json.load(open(paths(name, base)[1], encoding="utf-8"))
    except (OSError, ValueError):
        return None


def status(base=None):
    """[{name, text, installed, rows, bytes, server_date, built, mag_max, approx}]"""
    out = []
    for name, c in CATALOGS.items():
        m = meta(name, base) or {}
        npy = paths(name, base)[0]
        out.append(dict(name=name, text=c["text"], approx=c["approx"], installed=installed(name, base),
                        rows=m.get("rows"), bytes=os.path.getsize(npy) if os.path.isfile(npy) else 0,
                        server_date=m.get("server_date"), built=m.get("built"), mag_max=m.get("mag_max"),
                        source=m.get("source")))
    return out


def remove(name, base=None):
    for p in paths(name, base):
        if os.path.isfile(p):
            os.remove(p)
    _CACHE.pop((name, base), None)


def _save(name, arr, info, base=None):
    """Sorted by RA, written atomically (temp + os.replace), the meta file last."""
    os.makedirs(folder(base), exist_ok=True)
    arr = arr[np.argsort(arr["ra"], kind="stable")]
    npy, mp = paths(name, base)
    tmp = npy[:-4] + ".tmp.npy"
    np.save(tmp, arr)
    os.replace(tmp, npy)
    info = dict(info, rows=int(len(arr)), built=time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
                version=__version__)
    with open(mp + ".tmp", "w", encoding="utf-8") as f:
        json.dump(info, f, indent=1)
    os.replace(mp + ".tmp", mp)
    _CACHE.pop((name, base), None)
    return info


def _open(url, timeout=60):
    import requests
    r = requests.get(url, stream=True, timeout=timeout, headers={"User-Agent": f"PySyzygos/{__version__}"})
    r.raise_for_status()
    if "html" in (r.headers.get("Content-Type") or "").lower():
        r.close()
        raise OSError(f"{url}: an HTML page instead of the catalog file (server down?)")
    return r


def _first(urls, log):
    err = None
    for u in urls:
        try:
            return u, _open(u)
        except Exception as ex:                                  # noqa: BLE001 - next source
            log(f"  {u}: {str(ex)[:160]}")
            err = ex
    raise OSError(f"no source answered: {err}")


# ------------------------------------------------------------------------------------------------ WDS
def _f(s, nan=np.nan):
    try:
        return float(s)
    except ValueError:
        return nan


def _i(s):
    try:
        return int(s)
    except ValueError:
        return -1


def wds_precise(s):
    """'000006.64+752859.8' -> (ra, dec) degrees; None when blank or malformed."""
    s = s.strip()
    if len(s) < 17 or s[9] not in "+-":
        return None
    try:
        ra = (int(s[0:2]) + int(s[2:4]) / 60 + float(s[4:9]) / 3600) * 15
        d = int(s[10:12]) + int(s[12:14]) / 60 + float(s[14:]) / 3600
    except ValueError:
        return None
    return ra, (-d if s[9] == "-" else d)


def wds_row(line):
    """One line of wdsweb_summ2.txt (format wdsweb_format.txt, columns 1-130) -> a WDS_DT tuple, or None (header,
    no precise position)."""
    if len(line) < 130:
        return None
    p = wds_precise(line[112:130])
    if p is None:
        return None
    return (p[0], p[1], line[0:10].strip(), line[10:17].strip(), line[17:22].strip(), _i(line[23:27]),
            _i(line[28:32]), _i(line[33:37]), _i(line[38:41]), _i(line[42:45]), _f(line[46:51]), _f(line[52:57]),
            _f(line[58:63]), _f(line[64:69]), line[70:79].strip(), line[107:111].strip())


def build_wds(base=None, log=print):
    url, r = _first(CATALOGS["wds"]["urls"](), log)
    log(f"WDS: downloading {url} ...")
    rows, skipped = [], 0
    for raw in r.iter_lines():
        line = raw.decode("latin-1")
        t = wds_row(line)
        if t is None:
            skipped += line[:5].strip().isdigit()
        else:
            rows.append(t)
    if len(rows) < 1000:
        raise OSError(f"WDS: only {len(rows)} rows read: not the catalog file?")
    info = _save("wds", np.array(rows, dtype=WDS_DT),
                 dict(source=url, server_date=r.headers.get("Last-Modified"), no_position=skipped), base)
    log(f"WDS: {info['rows']} pairs kept ({skipped} without a precise position left out)")
    return info


# ------------------------------------------------------------------------------------------------ VSX
def _col(a, i, j):
    """Byte columns i..j-1 (0-based) of a (n, VSX_LRECL+1) uint8 array -> stripped bytes array."""
    return np.char.strip(np.ascontiguousarray(a[:, i:j]).view(f"S{j - i}").ravel())


def _num(b, dt="<f8"):
    return np.where(b == b"", b"nan", b).astype(dt)


def vsx_block(a, mag_max):
    """Fixed-width vsx.dat lines (n, 210 bytes) -> VSX_DT rows with a brightest magnitude <= mag_max (or none)."""
    vflag = _num(_col(a, 40, 41), "<f4")
    mx, mn = _num(_col(a, 95, 102), "<f4"), _num(_col(a, 120, 127), "<f4")
    keep = ~(mx > mag_max) & (vflag != 2)                          # NaN magnitude kept; 'constant' dropped
    a = a[keep]
    out = np.zeros(len(a), VSX_DT)
    out["oid"] = _num(_col(a, 0, 8)).astype("<u4")
    out["vflag"] = vflag[keep].astype("u1")
    out["ra"], out["dec"] = _num(_col(a, 42, 51)), _num(_col(a, 52, 61))
    out["type"] = _col(a, 62, 92).astype("S12")
    out["max"], out["min"] = mx[keep], mn[keep]
    out["amp"] = (_col(a, 116, 117) == b"Y")
    out["band"] = _col(a, 105, 115).astype("S4")
    out["period"] = _num(_col(a, 158, 177), "<f4")
    return out


def vsx_lines_slow(lines, mag_max):
    """Lines of other lengths (a last short line, CRLF): one by one, padded to the fixed width."""
    ok = [ln.rstrip(b"\r\n").ljust(VSX_LRECL)[:VSX_LRECL] + b"\n" for ln in lines if len(ln.strip()) > 60]
    if not ok:
        return np.zeros(0, VSX_DT)
    return vsx_block(np.frombuffer(b"".join(ok), np.uint8).reshape(-1, VSX_LRECL + 1), mag_max)


def build_vsx(base=None, mag_max=VSX_MAG_MAX, log=print, chunk_lines=200000):
    url, r = _first(CATALOGS["vsx"]["urls"](), log)
    size = int(r.headers.get("Content-Length") or 0)
    log(f"VSX: streaming {url} ({size / 1e9:.1f} GB), keeping rows brighter than {mag_max:g} mag at maximum ...")
    w = VSX_LRECL + 1
    parts, buf, done, n_all, t0, shown = [], b"", 0, 0, time.time(), 0.0
    for data in r.iter_content(chunk_lines * w):
        done += len(data)
        buf += data
        k = buf.rfind(b"\n") + 1                                   # whole lines only
        if not k:
            continue
        lines, buf = buf[:k], buf[k:]
        a = np.frombuffer(lines, np.uint8).reshape(-1, w) if len(lines) % w == 0 else None
        if a is not None and (a[:, -1] == 10).all():
            parts.append(vsx_block(a, mag_max))
            n_all += len(a)
        else:                                                      # other line lengths: one by one
            ls = lines.splitlines(keepends=True)
            parts.append(vsx_lines_slow(ls, mag_max))
            n_all += len(ls)
        if time.time() - shown > 15:
            shown = time.time()
            pct = f"{100 * done / size:.0f} %" if size else f"{done / 1e9:.2f} GB"
            print(f"  VSX: {pct}, {n_all:,} rows read, {sum(len(p) for p in parts):,} kept, "
                  f"{time.time() - t0:.0f} s", flush=True)
    if buf.strip():
        parts.append(vsx_lines_slow([buf], mag_max))
        n_all += 1
    arr = np.concatenate(parts) if parts else np.zeros(0, VSX_DT)
    if n_all < 100000:
        raise OSError(f"VSX: only {n_all} rows read: not the catalog file?")
    arr = arr[np.isfinite(arr["ra"]) & np.isfinite(arr["dec"])]
    info = _save("vsx", arr, dict(source=url, server_date=r.headers.get("Last-Modified"), mag_max=mag_max,
                                  rows_read=n_all), base)
    log(f"VSX: {info['rows']:,} of {n_all:,} variables kept (brightest magnitude <= {mag_max:g}), "
        f"{time.time() - t0:.0f} s")
    return info


def add(name, base=None, mag_max=VSX_MAG_MAX, log=print):
    return build_wds(base, log) if name == "wds" else build_vsx(base, mag_max, log)


# ------------------------------------------------------------------------------------------------ matching
def _load(name, base=None):
    key = (name, base)
    if key not in _CACHE:
        _CACHE[key] = np.load(paths(name, base)[0], mmap_mode="r") if installed(name, base) else None
    return _CACHE[key]


def _near(arr, ra, dec, radius_arcsec):
    """Rows of an RA-sorted array within radius (a box first, then the true separation), with 'sep' (arcsec)."""
    r = radius_arcsec / 3600.0
    w = min(180.0, r / max(math.cos(math.radians(dec)), 1e-6))
    spans = [(ra - w, ra + w)]
    if ra - w < 0:
        spans.append((ra - w + 360.0, 360.0))
    if ra + w > 360:
        spans.append((0.0, ra + w - 360.0))
    rows = [np.array(arr[np.searchsorted(arr["ra"], lo):np.searchsorted(arr["ra"], hi, "right")]) for lo, hi in spans]
    rows = np.concatenate(rows) if rows else arr[:0]
    rows = rows[np.abs(rows["dec"] - dec) <= r]
    return rows, sep_arcsec(ra, dec, rows["ra"], rows["dec"])


def sep_arcsec(ra1, de1, ra2, de2):
    ra1, de1, ra2, de2 = (np.radians(np.asarray(x, float)) for x in (ra1, de1, ra2, de2))
    h = np.sin((de2 - de1) / 2) ** 2 + np.cos(de1) * np.cos(de2) * np.sin((ra2 - ra1) / 2) ** 2
    return np.degrees(2 * np.arcsin(np.sqrt(np.clip(h, 0, 1)))) * 3600.0


def offset(ra, dec, pa_deg, sep_arcsec_):
    """Position sep_arcsec at position angle pa (north through east) from (ra, dec) (small angles)."""
    pa, s = math.radians(pa_deg), sep_arcsec_ / 3600.0
    return ((ra + s * math.sin(pa) / max(math.cos(math.radians(dec)), 1e-6)) % 360.0, dec + s * math.cos(pa))


def positions(rec):
    """The star at the event (record star_ra/dec) and moved back to J2000 with its proper motion (mas/yr)."""
    ra, dec = float(rec["star_ra"]), float(rec["star_dec"])
    out = [(ra, dec)]
    try:
        pmra, pmdec = float(rec.get("star_pmra") or "nan"), float(rec.get("star_pmdec") or "nan")
        yr = int(str(rec.get("best_utc", ""))[:4]) - 2000
    except ValueError:
        return out
    if math.isfinite(pmra) and math.isfinite(pmdec) and yr:
        out.append((ra - pmra * yr / 3.6e6 / max(math.cos(math.radians(dec)), 1e-6), dec - pmdec * yr / 3.6e6))
    return out


def _s(x):
    return x.decode("latin-1").strip() if isinstance(x, bytes) else str(x).strip()


def match_wds(rows, where):
    """WDS rows (dicts: ra, dec, disc, comp, first, last, nobs, pa2, sep2, mag1, mag2, notes, wds) whose primary or
    companion is within WDS_RADIUS of any of the star's positions -> [(row, role 'A'|'B', distance)] closest pair first."""
    out = []
    for w in rows:
        d_a = min(float(sep_arcsec(ra, dec, w["ra"], w["dec"])) for ra, dec in where)
        role, d = "A", d_a
        pa, sep = w.get("pa2"), w.get("sep2")
        if pa is not None and sep is not None and pa >= 0 and np.isfinite(sep) and sep > 0:
            cra, cdec = offset(w["ra"], w["dec"], pa, sep)
            d_b = min(float(sep_arcsec(ra, dec, cra, cdec)) for ra, dec in where)
            if d_b < d_a and d_a > ROLE_MIN:                  # sub-arcsec pairs: positions cannot tell
                role, d = "B", d_b
        if d <= WDS_RADIUS:
            out.append((w, role, d))
    out.sort(key=lambda t: (t[0].get("sep2") if np.isfinite(t[0].get("sep2", np.nan)) else 1e9))
    return out


def match_vsx(rows, where, g):
    out = []
    for v in rows:
        d = min(float(sep_arcsec(ra, dec, v["ra"], v["dec"])) for ra, dec in where)
        if d > VSX_RADIUS or v.get("vflag") == 2:
            continue
        mx, mn = v.get("max"), v.get("min")
        if g is not None and mx is not None and np.isfinite(mx):
            lo, hi = mx, (mx + mn if v.get("amp") else mn) if mn is not None and np.isfinite(mn) else mx
            band = (v.get("band") or "").strip()
            tol = VSX_DMAG * (1 if band in ("G", "V", "Vj", "CV", "") else 2)
            if not (lo - tol <= g <= max(lo, hi) + tol):
                continue
        out.append((v, d))
    out.sort(key=lambda t: t[1])
    return out


def wds_text(m):
    w, role, d = m
    f = lambda x, nd=1: "?" if x is None or not np.isfinite(x) else f"{x:.{nd}f}"
    span = (f"{w['first']}-{w['last']}" if w.get("first", -1) > 0 and w.get("last", -1) > 0 else "")
    sep_t = "<0.1\"" if np.isfinite(w.get("sep2", np.nan)) and w["sep2"] < 0.05 else f"{f(w.get('sep2'))}\""
    t = (f"WDS {w['wds']} {w['disc']} {w['comp']}".rstrip() + f": {sep_t} PA {w.get('pa2', '?')}°, "
         f"mag {f(w.get('mag1'), 2)}/{f(w.get('mag2'), 2)}" + (f", {span}" if span else "") +
         (f", {w['nobs']} obs." if w.get("nobs", -1) > 0 else "") + (f", notes {w['notes']}" if w.get("notes") else ""))
    return t + (" (the star is the companion)" if role == "B" else "")


def vsx_text(m):
    v, d = m
    f = lambda x: "?" if x is None or not np.isfinite(x) else f"{x:.2f}"
    band = (v.get("band") or "").strip()
    rng = (f"{f(v['max'])} amp. {f(v['min'])}" if v.get("amp") else
           f"{f(v['max'])}-{f(v['min'])}" if v.get("min") is not None and np.isfinite(v["min"]) else f(v["max"]))
    p = v.get("period")
    name = (v.get("name") or "").strip() or f"VSX {v.get('oid')}"
    return (f"{name}: {v.get('type') or '?'} {rng} {band}".rstrip() +
            (f", P {p:.6g} d" if p is not None and np.isfinite(p) and p > 0 else "") +
            (f" ({VFLAG[v['vflag']]})" if VFLAG.get(v.get("vflag")) else ""))


def fields(wds_m, vsx_m, source):
    """Record fields from the matches."""
    out = dict(wds="", wds_sep_arcsec="", wds_dmag="", var="", var_type="", var_amp_mag="", star_info=source)
    if wds_m:
        out["wds"] = "; ".join(wds_text(m) for m in wds_m[:4])
        w = wds_m[0][0]
        out["wds_sep_arcsec"] = "" if not np.isfinite(w.get("sep2", np.nan)) else f"{w['sep2']:.2f}"
        if np.isfinite(w.get("mag1", np.nan)) and np.isfinite(w.get("mag2", np.nan)):
            out["wds_dmag"] = f"{w['mag2'] - w['mag1']:.2f}"
    if vsx_m:
        v = vsx_m[0][0]
        out["var"] = "; ".join(vsx_text(m) for m in vsx_m[:2])
        out["var_type"] = (v.get("type") or "").strip()
        amp = v["min"] if v.get("amp") else (v["min"] - v["max"] if v.get("min") is not None else np.nan)
        out["var_amp_mag"] = f"{amp:.2f}" if amp is not None and np.isfinite(amp) else ""
    return out


def _dicts(arr, sep, kind):
    out = []
    for r in arr:
        d = {k: (_s(r[k]) if arr.dtype[k].kind == "S" else r[k].item()) for k in arr.dtype.names}
        out.append(d)
    return out


def local_rows(name, ra, dec, base=None):
    arr = _load(name, base)
    if arr is None:
        return None
    rows, sep = _near(arr, ra, dec, SEARCH_ARCSEC if name == "wds" else VSX_RADIUS * 3)
    return _dicts(rows, sep, name)


# ------------------------------------------------------------------------------------------------ online (VizieR)
WDS_ONLINE = {"WDS": "wds", "Disc": "disc", "Comp": "comp", "Obs1": "first", "Obs2": "last", "Nobs": "nobs",
              "pa1": "pa1", "pa2": "pa2", "sep1": "sep1", "sep2": "sep2", "mag1": "mag1", "mag2": "mag2",
              "SpType": "sp", "Notes": "notes"}
VSX_ONLINE = {"OID": "oid", "Name": "name", "V": "vflag", "Type": "type", "max": "max", "min": "min",
              "f_min": "amp", "n_max": "band", "Period": "period"}


def parse_asu(text):
    """A VizieR ASU tab-separated answer with several tables -> {'B/wds/wds': [rows], 'B/vsx/vsx': [rows]}."""
    out, cur, head, skip = {}, None, None, 0
    for ln in text.splitlines():
        if ln.startswith("#Name:"):
            name = ln.split(":", 1)[1].strip()
            cur, head = (name if name.count("/") == 2 else None), None
            continue
        if ln.startswith("#") or not ln.strip():
            if head is not None and not ln.strip():
                cur, head = None, None
            continue
        if cur is None:
            continue
        if head is None:
            head, skip = [h.strip() for h in ln.split("\t")], 2       # then units and dashes
            continue
        if skip:
            skip -= 1
            continue
        v = [x.strip() for x in ln.split("\t")]
        if len(v) >= len(head):
            out.setdefault(cur, []).append(dict(zip(head, v)))
    return out


def _online_rows(rows, names, ints=("first", "last", "nobs", "pa1", "pa2", "oid", "vflag")):
    out = []
    for r in rows:
        try:
            d = dict(ra=float(r["_RAJ2000"]), dec=float(r["_DEJ2000"]))
        except (KeyError, ValueError):
            continue
        for k, ours in names.items():
            x = r.get(k, "")
            if ours == "amp":
                d[ours] = x == "Y"
            elif ours in ints:
                d[ours] = _i(x)
            elif ours in ("sep1", "sep2", "mag1", "mag2", "max", "min", "period"):
                d[ours] = _f(x)
            else:
                d[ours] = x
        if "vflag" in d and d["vflag"] < 0:
            d["vflag"] = 0
        out.append(d)
    return out


def online_rows(ra, dec, fetch=None, which=("wds", "vsx")):
    """WDS and VSX rows around (ra, dec) from VizieR (one request). Raises OSError when no server answers."""
    import urllib.parse
    from pysyzygos import net
    src = " ".join({"wds": "B/wds/wds", "vsx": "B/vsx/vsx"}[w] for w in which)
    q = urllib.parse.urlencode({"-source": src, "-c": f"{ra:.6f} {dec:+.6f}", "-c.rs": f"{SEARCH_ARCSEC:g}",
                                "-out.add": "_RAJ,_DEJ", "-out.all": "", "-out.max": "200", "-oc.form": "d"})
    if fetch is None:
        text = net.read_first([U.URL_VIZIER_ASU] + U.URL_VIZIER_ASU_MIRRORS, q, timeout=ONLINE_TIMEOUT, ok=net.asu_ok)
    else:
        text = fetch(U.URL_VIZIER_ASU + "?" + q)
    t = parse_asu(text)
    return dict(wds=_online_rows(t.get("B/wds/wds", []), WDS_ONLINE) if "wds" in which else None,
                vsx=_online_rows(t.get("B/vsx/vsx", []), VSX_ONLINE) if "vsx" in which else None)


# ------------------------------------------------------------------------------------------------ the run's check
def mode():
    m = (os.environ.get("PYSYZYGOS_STAR_INFO") or "").strip().lower()
    if not m:
        try:
            from pysyzygos import config
            m = str(getattr(config, "star_info", "auto") or "auto").lower()
        except Exception:                                         # noqa: BLE001 - config not loadable (tests)
            m = "auto"
    if m in ("1", "on", "true", "yes"):
        m = "auto"
    if m in ("0", "false", "no", "none"):
        m = "off"
    return m if m in ("auto", "local", "online", "off") else "auto"


def check(records, base=None, how=None, fetch=None, log=print):
    """Look up each record's star: [field dicts] (same order) and a note for the run's warnings ('' none).
    how: auto | local | online | off (default mode())."""
    how = how or mode()
    if how == "off" or not records:
        return [], ""
    local = {n: (installed(n, base) and how in ("auto", "local")) for n in CATALOGS}
    online = [n for n in CATALOGS if not local[n] and how in ("auto", "online")]
    note, t0 = "", time.time()
    res = [dict(wds=None, vsx=None) for _ in records]
    for i, r in enumerate(records):
        for n in CATALOGS:
            if local[n]:
                res[i][n] = local_rows(n, float(r["star_ra"]), float(r["star_dec"]), base)
    if online:
        todo = list(range(len(records)))
        if len(todo) > ONLINE_MAX:
            note = (f"WDS/VSX online look-up stopped after {ONLINE_MAX} of {len(todo)} event stars: download the "
                    f"local copies (System tab) for big searches")
            todo = todo[:ONLINE_MAX]
        from concurrent.futures import ThreadPoolExecutor
        def one(i):
            try:
                return i, online_rows(float(records[i]["star_ra"]), float(records[i]["star_dec"]), fetch, online)
            except OSError as ex:
                return i, ex
        again = []
        with ThreadPoolExecutor(ONLINE_THREADS) as ex:
            for i, got in ex.map(one, todo):
                if isinstance(got, Exception):
                    again.append(i)
                    continue
                for n in online:
                    res[i][n] = got[n]
        failed = 0
        for i in again:                                            # once more, one at a time (VizieR's hiccups)
            got = one(i)[1]
            if isinstance(got, Exception):
                failed += 1
                continue
            for n in online:
                res[i][n] = got[n]
        if failed:
            note = ((note + "; ") if note else "") + (f"WDS/VSX online look-up failed for {failed} of {len(todo)} "
                                                      f"event stars (VizieR not reachable)")
    out = []
    src = "+".join(f"{n} {'local' if local[n] else 'online'}" for n in CATALOGS if local[n] or n in online)
    for r, got in zip(records, res):
        if got["wds"] is None and got["vsx"] is None:
            out.append(dict.fromkeys(FIELDS, ""))
            continue
        where = positions(r)
        try:
            g = float(r.get("mag"))
        except (TypeError, ValueError):
            g = None
        out.append(fields(match_wds(got["wds"] or [], where), match_vsx(got["vsx"] or [], where, g), src))
    log(f"* Double and variable stars ({src or 'none'}): {sum(1 for o in out if o['wds'])} event star(s) in the "
        f"WDS, {sum(1 for o in out if o['var'])} variable, {time.time() - t0:.1f} s")
    return out, note


# ------------------------------------------------------------------------------------------------ command line
def main(argv=None):
    import argparse
    from pysyzygos.__main__ import safe_console
    safe_console()
    ap = argparse.ArgumentParser(prog="pysyzygos star-info",
                                 description="Known double stars (WDS) and variable stars (AAVSO VSX): local copies "
                                             "and look-ups (starinfo.py)")
    ap.add_argument("cmd", choices=["status", "add", "remove", "lookup"])
    ap.add_argument("what", nargs="*", help="add/remove: wds, vsx or all; lookup: RA DEC (degrees) [G]")
    ap.add_argument("--mag-max", type=float, default=VSX_MAG_MAX,
                    help=f"VSX: keep variables brighter than this at maximum (default {VSX_MAG_MAX:g})")
    ap.add_argument("--online", action="store_true", help="lookup: ask VizieR even when local copies exist")
    ap.add_argument("--version", action="version", version=__version__)
    a = ap.parse_args(argv)
    names = list(CATALOGS) if not a.what or a.what == ["all"] else a.what
    if a.cmd == "status":
        for s in status():
            print(f"{s['name']}: {s['text']}: " + (f"installed, {s['rows']:,} rows, {s['bytes'] / 1e6:.0f} MB, "
                                                   f"server date {s['server_date'] or '?'}, built {s['built']}"
                                                   + (f", mag <= {s['mag_max']:g}" if s.get("mag_max") else "")
                                                   if s["installed"] else f"not installed ({s['approx']})"))
        print(f"look-ups after a search: {mode()}")
        return 0
    if a.cmd in ("add", "remove"):
        bad = [n for n in names if n not in CATALOGS]
        if bad:
            ap.error(f"unknown: {', '.join(bad)} (wds, vsx, all)")
        rc = 0
        for n in names:
            if a.cmd == "remove":
                remove(n)
                print(f"{n}: removed")
                continue
            try:
                add(n, mag_max=a.mag_max)
            except Exception as ex:                               # noqa: BLE001 - reported, next catalog
                print(f"{n}: FAILED: {ex}")
                rc = 1
        return rc
    if len(a.what) < 2:
        ap.error("lookup RA DEC [G]")
    rec = dict(star_ra=a.what[0], star_dec=a.what[1], mag=a.what[2] if len(a.what) > 2 else "", best_utc="2000")
    out, note = check([rec], how="online" if a.online else "auto")
    for k, v in (out[0] if out else {}).items():
        print(f"{k}: {v}")
    if note:
        print("WARNING:", note)
    return 0


if __name__ == "__main__":
    sys.exit(main())
