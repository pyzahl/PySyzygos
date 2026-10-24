"""occultdata.py - optional add-on: asteroid data that D. Herald maintains for the Occult program and IOTA publishes
for download. PySyzygos reads them as independent reference data (they do not change the predictions yet):

    diameters      AsteroidDiameters.bin: weighted mean diameter + uncertainty per numbered asteroid from the infrared
                   surveys (NEOWISE, AKARI AcuA, IRAS, MSX, TNO set); negative = estimated from H only
    diameters_all  AsteroidDiametersAll.bin: the weighted value of each survey, with the albedo
    magnitudes     HGsHG1G2_Magnitudes.csv: H, G in Gaia-style g and r (and sHG1G2, oblateness, pole) for ~122,000
                   asteroids (A&A 687, A38, 2024); V from g and r as Occult converts it
    binaries       BinaryAsteroids.csv: known and suspected asteroid satellites with orbital elements
    observations   Asteroid~Observations.xml: the occultation results archive (fitted profile per event), the
                   up-to-date version of what the NASA PDS archive publishes about yearly (occultations.py)
    gaia_doubles   Gaia_Doubles.csv: Gaia DR3 non-single-star solutions (orbits, accelerations), G < 16

Files: <data folder>/occult_data/ (the zip's files as published) + datasets.json (per dataset: server date, download
time, source) + derived look-up files (observations.json, gaia_doubles.idx.npy). Source: URL_OCCULT_DATA + the zip name
(case-sensitive server), or an existing Occult "Resource Files" folder (import_folder).

Layouts (Occult help pages, checked against the files 2026-10-19; where the help page differs, the files win):
    AsteroidDiameters.bin   n = size/3 entries: int16 diameter x 10 (km) for numbers 1..n, then uint8 uncertainty x 5
                            from byte 2n (the help page's "1,100,000" / "660000" are the old 550,000-entry layout)
    AsteroidDiametersAll    9-byte records sorted by number: int32 number, int16 dia x 10, uint8 uncertainty x 2.5,
                            uint8 source, uint8 albedo x 500 (AsteroidDias_Indiv: albedo and source swapped)

    pysyzygos occult-data [status]              # what is installed, server dates
    pysyzygos occult-data add <name ...|all>    # download (or update) datasets
    pysyzygos occult-data remove <name ...|all>
    pysyzygos occult-data update                # download the installed datasets that changed on the server
    pysyzygos occult-data import <folder>       # copy from an Occult "Resource Files" folder
    pysyzygos occult-data show <number>         # everything the installed datasets know about an asteroid
"""
from pysyzygos.version import __version__
from pysyzygos import urls as U
import csv, io, json, os, shutil, sys, time, zipfile

import numpy as np

DIR = "occult_data"
META = "datasets.json"
DATASETS = {
    "diameters": dict(zip="AsteroidDiameters.zip", files=("AsteroidDiameters.bin",),
                      text="asteroid diameters, weighted mean of the infrared surveys"),
    "diameters_all": dict(zip="AsteroidDiametersAll.zip", files=("AsteroidDiametersAll.bin",),
                          text="diameter and albedo of each infrared survey"),
    "magnitudes": dict(zip="AsteroidMagnitudes.zip", files=("HGsHG1G2_Magnitudes.csv",),
                       text="H, G in g and r for ~122,000 asteroids (A&A 687, A38)"),
    "binaries": dict(zip="BinaryAsteroids.zip", files=("BinaryAsteroids.csv", "BinaryAsteroid_SatelliteNames.txt"),
                     text="asteroid satellites with orbits"),
    "observations": dict(zip="Asteroid_Observations.zip",
                         files=("Asteroid~Observations.xml", "FileFormat AsteroidObservations.htm"),
                         text="occultation results archive (profiles measured per event)"),
    "gaia_doubles": dict(zip="Gaia_Doubles.zip", files=("Gaia_Doubles.csv", "Gaia_Doubles.inx"),
                         text="Gaia DR3 non-single stars (orbits, accelerations), G < 16"),
}
SOURCES = {0: "spacecraft", 1: "NEOWISE", 2: "AKARI AcuA", 3: "IRAS", 4: "MSX", 5: "TNO/Centaurs"}
QUALITY = {0: "unreliable", 1: "astrometry only", 2: "limits on size", 3: "reliable size",
           4: "better than shape models", 5: "short event, no astrometry", 6: "one star of a double"}
SHAPE_FIT = {0: "not fitted", 1: "bad occultation data", 2: "model wrong", 3: "minimum diameter",
             4: "diameter, no fit", 5: "poor fit", 6: "good fit", 7: "not constrained"}
_CACHE = {}


def folder(base=None):
    """The add-on's folder: <data folder>/occult_data (base: another data folder, for tests)."""
    if base is None:
        from pysyzygos import home
        base = home.HOME
    return os.path.join(base, DIR)


def _meta(d):
    try:
        with open(os.path.join(d, META), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save_meta(d, meta):
    tmp = os.path.join(d, META + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=1)
    os.replace(tmp, os.path.join(d, META))


def _keys(names):
    """Dataset keys from command-line names ('all' = every dataset)."""
    if not names or "all" in names:
        return list(DATASETS)
    bad = [n for n in names if n not in DATASETS]
    if bad:
        raise SystemExit(f"unknown dataset(s): {', '.join(bad)}; known: {', '.join(DATASETS)}")
    return list(names)


def installed(key, base=None):
    """True if all of the dataset's files are in the folder."""
    d = folder(base)
    return all(os.path.isfile(os.path.join(d, f)) for f in DATASETS[key]["files"])


def status(base=None):
    """[{key, text, zip, installed, bytes, server_date, downloaded, source}] for every dataset."""
    d, meta = folder(base), _meta(folder(base))
    out = []
    for k, ds in DATASETS.items():
        have = installed(k, base)
        size = sum(os.path.getsize(os.path.join(d, f)) for f in ds["files"]) if have else 0
        m = meta.get(k, {}) if have else {}
        out.append(dict(key=k, text=ds["text"], zip=ds["zip"], installed=have, bytes=size,
                        server_date=m.get("server_date", ""), downloaded=m.get("downloaded", ""),
                        source=m.get("source", "")))
    return out


def _request(url, method="GET"):
    import urllib.request
    return urllib.request.Request(url, method=method, headers={"User-Agent": f"PySyzygos/{__version__}"})


def server_date(key):
    """The server's Last-Modified of the dataset's zip (HEAD request), or '' if it cannot be reached."""
    from pysyzygos import net
    try:
        with net.urlopen(_request(U.URL_OCCULT_DATA + DATASETS[key]["zip"], "HEAD"), timeout=30) as r:
            return r.headers.get("Last-Modified", "")
    except OSError:
        return ""


def check_updates(base=None):
    """{key: server date} of the installed datasets whose zip on the server differs from the installed one."""
    meta, out = _meta(folder(base)), {}
    for k in DATASETS:
        if installed(k, base):
            new = server_date(k)
            if new and new != meta.get(k, {}).get("server_date"):
                out[k] = new
    return out


def _replace(src, dst):
    from pysyzygos.gaia_local import replace_file           # retries Windows' "file in use"
    replace_file(src, dst)


def add(key, base=None, log=print):
    """Download one dataset (also to update it): the zip to a temporary file, then only the expected files out of it
    (by name; nothing else in the archive is written), then the derived look-up file. Returns the server date."""
    from pysyzygos import net
    ds, d = DATASETS[key], folder(base)
    os.makedirs(d, exist_ok=True)
    url = U.URL_OCCULT_DATA + ds["zip"]
    tmp = os.path.join(d, ds["zip"] + f".{os.getpid()}.tmp")
    log(f"{key}: downloading {url}")
    try:
        with net.urlopen(_request(url), timeout=120) as r, open(tmp, "wb") as f:
            date = r.headers.get("Last-Modified", "")
            shutil.copyfileobj(r, f, 1 << 20)
        with zipfile.ZipFile(tmp) as z:
            names = {os.path.basename(n): n for n in z.namelist()}
            missing = [f for f in ds["files"] if f not in names]
            if missing:
                raise RuntimeError(f"{ds['zip']} does not contain {', '.join(missing)}")
            for f in ds["files"]:
                part = os.path.join(d, f + ".part")
                with z.open(names[f]) as src, open(part, "wb") as dst:
                    shutil.copyfileobj(src, dst, 1 << 20)
                _replace(part, os.path.join(d, f))
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    _finish(key, d, dict(server_date=date, source=url), log)
    return date


def import_folder(src, base=None, log=print):
    """Copy the datasets found in an Occult 'Resource Files' folder (or its Gaia subfolder). Returns the keys."""
    d, done = folder(base), []
    for k, ds in DATASETS.items():
        found = {}
        for f in ds["files"]:
            for sub in ("", "Gaia"):
                p = os.path.join(src, sub, f)
                if os.path.isfile(p):
                    found[f] = p
                    break
        if len(found) != len(ds["files"]):
            continue
        os.makedirs(d, exist_ok=True)
        for f, p in found.items():
            part = os.path.join(d, f + ".part")
            shutil.copyfile(p, part)
            _replace(part, os.path.join(d, f))
        date = time.strftime("%a, %d %b %Y %H:%M:%S GMT",
                             time.gmtime(max(os.path.getmtime(p) for p in found.values())))
        log(f"{k}: copied from {src}")
        _finish(k, d, dict(server_date="", file_date=date, source=os.path.abspath(src)), log)
        done.append(k)
    return done


def _finish(key, d, info, log):
    _CACHE.clear()
    if key == "observations":
        n = build_observations(d)
        log(f"{key}: {n} asteroids with observed events indexed")
        from pysyzygos import observed                       # the events themselves: a results database (Results tab)
        observed.build(os.path.join(d, observed.XML_FILE), os.path.join(d, observed.DB_FILE),
                       os.path.join(d, observed.CSV_FILE), log=log)
    elif key == "gaia_doubles":
        n = build_doubles_index(d)
        log(f"{key}: {n} entries indexed")
    meta = _meta(d)
    meta[key] = dict(info, downloaded=time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()), version=__version__)
    _save_meta(d, meta)


def remove(key, base=None):
    """Delete a dataset's files (and its derived look-up file). Returns True if something was deleted."""
    d, gone = folder(base), False
    extra = {"observations": ("observations.json", "observations.db", "observations_log.csv",
                              "observations_log.runs.jsonl", "observations.db-wal", "observations.db-shm"),
             # (obs_check.jsonl / .md stay: the check's results, an hour of work; a new download applies them again)
             "gaia_doubles": ("gaia_doubles.idx.npy",)}.get(key, ())
    for f in DATASETS[key]["files"] + extra:
        p = os.path.join(d, f)
        if os.path.isfile(p):
            os.remove(p)
            gone = True
    meta = _meta(d)
    if meta.pop(key, None) is not None:
        _save_meta(d, meta)
    _CACHE.clear()
    return gone


# ----------------------------------------------------------------------------------------------- readers
def _f(x):
    try:
        v = float(x)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def diameter(number, base=None):
    """{'d': km, 'u': km, 'from_h': bool} from AsteroidDiameters.bin, or None (not installed, unknown number)."""
    key = ("diameters", base)
    if key not in _CACHE:
        p = os.path.join(folder(base), "AsteroidDiameters.bin")
        if not os.path.isfile(p):
            return None
        raw = np.fromfile(p, dtype=np.uint8)
        n = len(raw) // 3
        _CACHE[key] = (raw[:2 * n].view("<i2").copy(), raw[2 * n:3 * n].copy())
    dia, unc = _CACHE[key]
    try:
        i = int(str(number).strip()) - 1
    except ValueError:
        return None
    if not 0 <= i < len(dia) or dia[i] == 0:
        return None
    return dict(d=abs(int(dia[i])) / 10.0, u=int(unc[i]) / 5.0, from_h=bool(dia[i] < 0))


ALL_DTYPE = np.dtype([("num", "<i4"), ("dia", "<i2"), ("unc", "u1"), ("source", "u1"), ("albedo", "u1")])


def diameters_all(number, base=None):
    """[{'d', 'u', 'albedo', 'source'}] of each infrared survey (AsteroidDiametersAll.bin), [] if none."""
    key = ("diameters_all", base)
    if key not in _CACHE:
        p = os.path.join(folder(base), "AsteroidDiametersAll.bin")
        if not os.path.isfile(p):
            return []
        _CACHE[key] = np.fromfile(p, dtype=ALL_DTYPE)
    rec = _CACHE[key]
    try:
        n = int(str(number).strip())
    except ValueError:
        return []
    i, j = np.searchsorted(rec["num"], n, "left"), np.searchsorted(rec["num"], n, "right")
    return [dict(d=int(r["dia"]) / 10.0, u=int(r["unc"]) / 2.5, albedo=int(r["albedo"]) / 500.0 or None,
                 source=SOURCES.get(int(r["source"]), f"source {int(r['source'])}")) for r in rec[i:j]]


MAG_COLS = ("number", "Hg", "Hg_u", "Gg", "Hr", "Hr_u", "Gr", "Hg2", "Hg2_u", "G1g", "G2g", "Hr2", "Hr2_u", "G1r",
            "G2r", "R", "pole_ra", "pole_dec", "R_u", "pole_ra_u", "pole_dec_u")


def magnitudes(number, base=None):
    """The asteroid's row of HGsHG1G2_Magnitudes.csv by column position (the header repeats names), plus 'HV' =
    Hg - 0.03 - 0.42 (Hg - Hr) (Occult's g, r to V conversion); None if not listed."""
    key = ("magnitudes", base)
    if key not in _CACHE:
        p = os.path.join(folder(base), "HGsHG1G2_Magnitudes.csv")
        if not os.path.isfile(p):
            return None
        rows = {}
        with open(p, encoding="utf-8", errors="replace") as f:
            next(f, None)
            for line in f:
                parts = line.strip().split(",")
                if parts and parts[0].strip().isdigit():
                    rows[parts[0].strip()] = parts
        _CACHE[key] = rows
    parts = _CACHE[key].get(str(number).strip())
    if not parts:
        return None
    out = {c: _f(v) for c, v in zip(MAG_COLS[1:], parts[1:])}
    out["number"] = int(parts[0])
    if out.get("Hg") is not None and out.get("Hr") is not None:
        out["HV"] = round(out["Hg"] - 0.03 - 0.42 * (out["Hg"] - out["Hr"]), 2)
    return out


BIN_COLS = ("number", "name", "satellite", "dia_km", "a_km", "period_d", "e", "i", "epoch_jd", "M", "peri", "node",
            "ref_frame")


def binaries(number, base=None):
    """[{BIN_COLS...}] satellites of the asteroid in BinaryAsteroids.csv (ref_frame 1 ecliptic, 2 equatorial)."""
    key = ("binaries", base)
    if key not in _CACHE:
        p = os.path.join(folder(base), "BinaryAsteroids.csv")
        if not os.path.isfile(p):
            return []
        rows = {}
        with open(p, encoding="utf-8", errors="replace", newline="") as f:
            r = csv.reader(f)
            next(r, None)
            for parts in r:
                if not parts or not parts[0].strip():
                    continue
                e = {c: (v.strip() if c in ("number", "name", "satellite") else _f(v)) for c, v in zip(BIN_COLS, parts)}
                rows.setdefault(e["number"], []).append(e)
        _CACHE[key] = rows
    return _CACHE[key].get(str(number).strip(), [])


# --------------------------------------------------------------------- the occultation results archive
def _date(s):
    """'2019|7|29|11.3' -> '2019-07-29'."""
    p = (s or "").split("|")
    try:
        return f"{int(p[0]):04d}-{int(p[1]):02d}-{int(p[2]):02d}"
    except (ValueError, IndexError):
        return ""


def extract_observations(xml_file):
    """Per numbered asteroid, in the schema of occultations.py (n, first, last, q, best; shape_dia), from the XML:
    best = the best-quality (then latest) event with quality >= 2 whose axes were not assumed; shape_dia = the median
    volume-equivalent diameter of the 'good fit' shape-model fits (code 6; mid of their min/max), with the number of
    events. Also satellites: number of events with a fitted satellite."""
    import xml.etree.ElementTree as ET
    ast, last = {}, ""
    for _, el in ET.iterparse(xml_file, events=("end",)):
        if el.tag != "Event":
            continue
        a = (el.findtext("Details/Asteroid") or "").split("|")
        num = a[0].strip() if a else ""
        if num.isdigit():
            date = _date(el.findtext("Date"))
            last = max(last, date)
            e = ast.setdefault(num, dict(name=a[1].strip() if len(a) > 1 else "", n=0, first=None, last=None, q={},
                                         best=None, good=[], sat=0))
            e["n"] += 1
            e["first"] = min(e["first"] or date, date)
            e["last"] = max(e["last"] or date, date)
            fit = (el.findtext("Details/EventFits/EllipticFit") or "").split("|")
            unc = (el.findtext("Details/EventFits/EllipseUncertainty") or "").split("|")
            q = int(_f(fit[5]) or 0) if len(fit) > 6 else 0
            e["q"][str(q)] = e["q"].get(str(q), 0) + 1
            major, minor = (_f(fit[2]), _f(fit[3])) if len(fit) > 6 else (None, None)
            if 2 <= q <= 4 and fit[6].strip() == "0" and major and minor:
                cand = dict(date=date, q=q, major=major, minor=minor, pa=_f(fit[4]),
                            major_u=_f(unc[2]) if len(unc) > 3 else None, minor_u=_f(unc[3]) if len(unc) > 3 else None)
                b = e["best"]
                if b is None or (q, date) > (b["q"], b["date"]):
                    e["best"] = cand
            for x in el.iter("Fit"):
                p = (x.text or "").split("|")
                if len(p) > 6 and (_f(p[3]) or 0) == 6 and _f(p[5]) and _f(p[6]):
                    e["good"].append((_f(p[5]) + _f(p[6])) / 2.0)
            if el.find(".//Satellite") is not None:
                e["sat"] += 1
        el.clear()
    for e in ast.values():
        g = e.pop("good")
        if g:
            e["shape_dia"] = dict(d=round(float(np.median(g)), 1), events=len(g), method="median of good fits")
    return dict(meta=dict(source="IOTA asteroid occultation results (D. Herald), Occult's Asteroid~Observations.xml",
                          label="IOTA / Occult archive", url=U.URL_OCCULT_DATA, events_until=last or None,
                          asteroids=len(ast)), asteroids=ast)


def build_observations(d):
    data = extract_observations(os.path.join(d, "Asteroid~Observations.xml"))
    tmp = os.path.join(d, "observations.json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, separators=(",", ":"))
    os.replace(tmp, os.path.join(d, "observations.json"))
    return data["meta"]["asteroids"]


def observations_file(base=None):
    """observations.json if the archive is installed, else None (occultations.py then uses the PDS extract)."""
    p = os.path.join(folder(base), "observations.json")
    return p if os.path.isfile(p) else None


# ------------------------------------------------------------------------------------ Gaia non-single stars
DBL_IDX = np.dtype([("ra", "<f8"), ("dec", "<f8"), ("off", "<i8")])


def build_doubles_index(d):
    """gaia_doubles.idx.npy: RA, Dec and the byte offset of each row of Gaia_Doubles.csv, sorted by RA."""
    p = os.path.join(d, "Gaia_Doubles.csv")
    ra, dec, off = [], [], []
    with open(p, "rb") as f:
        f.readline()
        pos = f.tell()
        for line in iter(f.readline, b""):
            parts = line.split(b",", 2)
            if len(parts) > 2:
                try:
                    ra.append(float(parts[0]))
                    dec.append(float(parts[1]))
                    off.append(pos)
                except ValueError:
                    pass
            pos = f.tell()
    idx = np.empty(len(ra), DBL_IDX)
    idx["ra"], idx["dec"], idx["off"] = ra, dec, off
    idx.sort(order="ra")
    tmp = os.path.join(d, "gaia_doubles.idx.tmp.npy")
    np.save(tmp, idx)
    _replace(tmp, os.path.join(d, "gaia_doubles.idx.npy"))
    return len(idx)


def gaia_doubles_near(ra_deg, dec_deg, radius_arcsec=3.0, base=None):
    """Rows of Gaia_Doubles.csv within radius of (ra, dec) (epoch 2016.0 positions): [{column: value, 'sep_arcsec'}]."""
    d = folder(base)
    p, ip = os.path.join(d, "Gaia_Doubles.csv"), os.path.join(d, "gaia_doubles.idx.npy")
    if not (os.path.isfile(p) and os.path.isfile(ip)):
        return []
    key = ("doubles", base)
    if key not in _CACHE:
        with open(p, encoding="utf-8", errors="replace") as f:
            head = [h.strip() for h in f.readline().split(",")]
        _CACHE[key] = (np.load(ip), head)
    idx, head = _CACHE[key]
    r = radius_arcsec / 3600.0
    w = r / max(np.cos(np.radians(dec_deg)), 1e-6)
    out = []
    spans = [(ra_deg - w, ra_deg + w)]
    if spans[0][0] < 0:
        spans.append((spans[0][0] + 360.0, 360.0))
    if spans[0][1] > 360:
        spans.append((0.0, spans[0][1] - 360.0))
    with open(p, encoding="utf-8", errors="replace") as f:
        for lo, hi in spans:
            for row in idx[np.searchsorted(idx["ra"], lo):np.searchsorted(idx["ra"], hi, "right")]:
                dra = (row["ra"] - ra_deg + 180.0) % 360.0 - 180.0
                sep = np.hypot(dra * np.cos(np.radians(dec_deg)), row["dec"] - dec_deg) * 3600.0
                if sep <= radius_arcsec:
                    f.seek(int(row["off"]))
                    vals = f.readline().rstrip("\r\n").split(",")
                    e = {h: v.strip() for h, v in zip(head, vals)}
                    e["sep_arcsec"] = round(float(sep), 2)
                    out.append(e)
    return out


MODELS = {"oc": "astrometric orbit", "ac": "astrometric orbit (low S/N)", "avc": "astrometric orbit (low S/N)",
          "otsc": "orbit (a priori known)", "otsvc": "orbit (a priori known)", "asb1c": "astrometric + spectroscopic orbit",
          "eb": "eclipsing binary", "es": "eclipsing + spectroscopic", "sb1": "spectroscopic binary",
          "sb1c": "spectroscopic binary", "sb2": "double-lined spectroscopic binary",
          "sb2c": "double-lined spectroscopic binary", "acc7": "acceleration (7 par.)", "acc9": "acceleration (9 par.)"}


def star_text(ra_deg, dec_deg, radius_arcsec=3.0, base=None):
    """Lines for Gaia DR3 non-single-star solutions within radius of the star (3": Occult's 'probable match')."""
    out = []
    for e in gaia_doubles_near(ra_deg, dec_deg, radius_arcsec, base):
        m = e.get("Model", "")
        bits = [MODELS.get(m, m)]
        if e.get("Period(d)"):
            bits.append(f"P {float(e['Period(d)']):.4g} d")
        if e.get("Semimajor"):
            bits.append(f"a {float(e['Semimajor']):g} mas")
        if e.get("Ecc"):
            bits.append(f"e {float(e['Ecc']):g}")
        out.append(f"Gaia non-single star ({e['sep_arcsec']:g}\" off): " + ", ".join(bits)
                   + f" [Gaia DR3 {e.get('ID', '')}]")
    return out


# --------------------------------------------------------------------------------------------- summary
def summary(number, base=None):
    """Text lines about the asteroid from the installed datasets (favorites panel, 'show')."""
    lines = []
    dm = diameter(number, base)
    if dm:
        lines.append((f"Diameter (IR surveys, weighted): {dm['d']:g} ± {dm['u']:g} km" if dm["u"] else
                      f"Diameter: {dm['d']:g} km") if not dm["from_h"] else
                     f"Diameter: {dm['d']:g} km, estimated from H (no infrared measurement)")
    alls = diameters_all(number, base)
    if alls:
        lines.append("By survey: " + "; ".join(
            f"{x['source']} {x['d']:g}" + (f" ± {x['u']:g}" if x["u"] else "") + " km" + (f" (albedo {x['albedo']:.3f})" if x["albedo"] else "")
            for x in alls))
    m = magnitudes(number, base)
    if m:
        lines.append(f"H (g, r): {m.get('Hg')} / {m.get('Hr')}, G {m.get('Gg')} / {m.get('Gr')}"
                     + (f", H_V {m['HV']:.2f}" if m.get("HV") is not None else "")
                     + (f"; oblate, pole RA {m['pole_ra']:g}° Dec {m['pole_dec']:g}°"
                        if m.get("pole_ra") is not None and m.get("pole_dec") is not None else ""))
    for s in binaries(number, base):
        lines.append(f"Satellite {s['satellite'] or '(unnamed)'}: " + ", ".join(
            x for x in (f"D {s['dia_km']:g} km" if s["dia_km"] else "", f"a {s['a_km']:g} km" if s["a_km"] else "",
                        f"P {s['period_d']:g} d" if s["period_d"] else "") if x))
    return lines


# --------------------------------------------------------------------------------------------- CLI
def main(argv=None):
    a = sys.argv[1:] if argv is None else list(argv)
    cmd = a[0] if a else "status"
    if cmd == "add":
        if len(a) < 2:
            raise SystemExit(f"name the dataset(s) to download, or all: {', '.join(DATASETS)}")
        for k in _keys(a[1:]):
            add(k)
    elif cmd == "remove":
        if len(a) < 2:
            raise SystemExit("name the dataset(s) to remove, or all")
        for k in _keys(a[1:]):
            print(f"{k}: {'removed' if remove(k) else 'not installed'}")
    elif cmd == "update":
        new = check_updates()
        if not new:
            print("All installed datasets are up to date.")
        for k in new:
            add(k)
    elif cmd == "import":
        if len(a) < 2:
            raise SystemExit("usage: pysyzygos occult-data import <Occult 'Resource Files' folder>")
        done = import_folder(a[1])
        print(f"Imported: {', '.join(done) if done else 'nothing (no dataset files found there)'}")
    elif cmd == "show":
        if len(a) < 2:
            raise SystemExit("usage: pysyzygos occult-data show <asteroid number>")
        from pysyzygos import occultations
        for line in summary(a[1]) + [occultations.text(a[1])]:
            if line:
                print(line)
        return 0
    elif cmd != "status":
        raise SystemExit(__doc__)
    print(f"Occult data (optional add-on) in {folder()}:")
    for s in status():
        when = s["server_date"] or s["source"]
        print(f"  [{'x' if s['installed'] else ' '}] {s['key']:14s} {s['text']}"
              + (f"  ({s['bytes'] / 1e6:.1f} MB, {when})" if s["installed"] else f"  ({s['zip']})"))
    return 0


if __name__ == "__main__":
    main()
