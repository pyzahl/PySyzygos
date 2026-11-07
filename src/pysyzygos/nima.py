"""nima.py - NIMA ephemerides of the Lucky Star project (LESIA, Paris Observatory) as an orbit source.

NIMA (Desmars et al. 2015) fits TNOs, Centaurs and some Trojans (414 objects, 2026-11) with weights per observation
and includes positions from stellar occultations and unpublished astrometry: for many TNOs it is several times more
precise than JPL's orbit, for others JPL has newer data. Checked 2026-11-06 for our TNO targets: 2007 JJ43 NIMA - JPL
56 mas (1,700 km; NIMA a year more data), Quaoar 2.7 mas (NIMA sigma 4, JPL 16), Rumina 48 mas (JPL newer data).

    index()           {target id: entry} of the objects on the NIMA page (cached a day: PySyzygos_nima_index.json)
    details(entry)    the object page: bsp path, last observation, sigma table (cached per version)
    kernel(entry)     the .bsp (SPICE, same body id as JPL's: 2000000 + number), cached per version
    choose(...)       NIMA or JPL for a target: mode "off" | "auto" (the newer last observation; a tie: NIMA) | "always"
    sigma_arcsec(..)  NIMA's 1-sigma position uncertainty (RA*cos dec, dec) at a date, from the page's table

The files are SPK type 3 relative to the Sun in J2000, like Horizons' (type 21): loaded after Horizons' file, the
same body id then means NIMA (SPICE: the last loaded file wins).
Standard library only (+ net for https); SPICE is passed in where needed (shift_component).
"""
from pysyzygos.version import __version__
from pysyzygos import net, urls as U
import json, os, re, time
import html as _html

MODES = ("off", "auto", "always")
INDEX_FILE = "PySyzygos_nima_index.json"
INDEX_MAX_AGE_S = 86400.0


def _get(url, timeout=60):
    with net.urlopen(url, timeout=timeout) as r:
        return r.read()


def _write_json(path, data):
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    os.replace(tmp, path)


def target_key(label, name):
    """Our target id of a NIMA entry: the number of '(50000) Quaoar', else the designation ('1996RR20' -> '1996 RR20');
    None for planets' satellites and the like (no minor-planet id)."""
    m = re.match(r"\((\d+)\)", label.strip())
    if m:
        return m.group(1)
    m = re.fullmatch(r"(\d{4})([A-Z]{2}\d*)", name.strip())
    return f"{m.group(1)} {m.group(2)}" if m else None


def parse_index(page):
    """{target id: entry} from the NIMA page's table (var Mtable = [[page id, name, label, version, updated y, m0, d,
    last observation y, m0, d, a, H], ...]; months from 0, as JavaScript's Date)."""
    i = page.index("var Mtable = ") + len("var Mtable = ")
    rows = json.loads(page[i:page.index(";", i)])
    out = {}
    for r in rows:
        key = target_key(r[2], r[1])
        if key:
            out[key] = dict(page=int(r[0]), name=r[1], label=r[2], version=int(r[3]),
                            updated=f"{int(r[4]):04d}-{int(r[5]) + 1:02d}-{int(r[6]):02d}",
                            last_obs=f"{int(r[7]):04d}-{int(r[8]) + 1:02d}-{int(r[9]):02d}", a_au=float(r[10]))
    return out


def index(cache_dir, max_age_s=INDEX_MAX_AGE_S, fetch=None):
    """The NIMA objects ({target id: entry}), from the cache when younger than max_age_s, else the page (an old cache
    when the page does not answer; {} without either). fetch(url) -> bytes stands in for the download (tests)."""
    path = os.path.join(cache_dir, INDEX_FILE)
    old = None
    try:
        with open(path, encoding="utf-8") as fh:
            old = json.load(fh)
        if time.time() - old["fetched"] < max_age_s:
            return old["objects"]
    except (OSError, ValueError, KeyError):
        pass
    try:
        objs = parse_index((fetch or _get)(U.URL_NIMA_INDEX).decode("utf-8", "replace"))
        _write_json(path, dict(fetched=time.time(), objects=objs, details=(old or {}).get("details", {})))
        return objs
    except Exception as e:
        print(f"NIMA: the list did not load ({type(e).__name__}: {str(e)[:80]})"
              + ("; using the cached one" if old else ""), flush=True)
        return (old or {}).get("objects", {})


def parse_details(page):
    """bsp path, version, last observation, number of observations, RMS and the sigma table [(YYYY-MM, s_ra, s_dec)]
    (arcsec, 1 sigma) of a NIMA object page."""
    bsp = re.search(r"data/nima/[^\"']+\.bsp", page)
    txt = _html.unescape(re.sub(r"\s+", " ", re.sub("<[^>]+>", " ", re.sub(r"<script.*?</script>", "", page,
                                                                            flags=re.S))))
    g = lambda pat: (re.search(pat, txt) or [None, None])[1]
    return dict(bsp=bsp.group(0) if bsp else None, version=g(r"Ephemeris version (NIMAv\d+)"),
                last_obs=g(r"Date of last observation (\d{4}-\d\d-\d\d)"),
                n_obs=int(g(r"Number of observations used in the fit (\d+)") or 0),
                rms_arcsec=float(g(r"RMS of observations ([\d.]+)") or "nan"),
                sigma=[[d, float(a), float(b)] for d, a, b in re.findall(r"(20\d\d-\d\d) ([\d.]+) ([\d.]+)", txt)])


def details(entry, cache_dir, fetch=None):
    """parse_details of the entry's page, cached in the index file per page and version."""
    path = os.path.join(cache_dir, INDEX_FILE)
    key = f"{entry['page']}:v{entry['version']}"
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        data = dict(fetched=0, objects={}, details={})
    if key in data.get("details", {}):
        return data["details"][key]
    d = parse_details((fetch or _get)(U.URL_NIMA_OBJECT + str(entry["page"])).decode("utf-8", "replace"))
    data.setdefault("details", {})[key] = d
    _write_json(path, data)
    return d


def kernel(key, entry, det, cache_dir, fetch=None):
    """Path of the .bsp of target key (entry, details) in cache_dir, downloaded once per version."""
    path = os.path.join(cache_dir, f"PySyzygos_nima_{key.replace(' ', '_')}_v{entry['version']}.bsp")
    if not os.path.isfile(path):
        blob = (fetch or _get)(U.URL_NIMA_BASE + det["bsp"])
        tmp = f"{path}.{os.getpid()}.tmp"
        with open(tmp, "wb") as fh:
            fh.write(blob)
        os.replace(tmp, path)
    return path


def jpl_last_obs(phys):
    """The last observation date of JPL's orbit solution from the SBDB cache entry's phys ('orbit' ref: '... to
    YYYY-MM-DD'), or None."""
    ref = ((phys or {}).get("orbit") or {}).get("ref") or ""
    m = re.search(r"to (\d{4}-\d\d-\d\d)", ref)
    return m.group(1) if m else None


def choose(mode, nima_last, jpl_last):
    """(use NIMA?, reason) for one target. auto: the orbit with the newer last observation; on the same date NIMA (it
    also fits occultation positions and unpublished astrometry); JPL's date unknown: NIMA."""
    if mode == "always":
        return True, "NIMA always"
    if mode != "auto" or not nima_last:
        return False, ""
    if not jpl_last:
        return True, f"NIMA: last observation {nima_last}, JPL's unknown"
    if nima_last >= jpl_last:
        return True, f"NIMA: last observation {nima_last} (JPL {jpl_last})"
    return False, f"JPL: last observation {jpl_last} (NIMA {nima_last})"


def sigma_arcsec(det, utc):
    """NIMA's 1-sigma uncertainty (RA*cos dec, dec) in arcsec at utc ('YYYY-MM...'): linear in the page's table
    (half-year steps), the nearest end outside it; None without a table."""
    tab = det.get("sigma") or []
    if not tab:
        return None
    t = lambda s: int(s[:4]) * 12 + int(s[5:7]) - 1 + (int(s[8:10]) - 1) / 30.0 if len(s) >= 10 else \
        int(s[:4]) * 12 + int(s[5:7]) - 1
    x = t(str(utc))
    pts = sorted((t(d), a, b) for d, a, b in tab)
    if x <= pts[0][0]:
        return pts[0][1], pts[0][2]
    for (x0, a0, b0), (x1, a1, b1) in zip(pts, pts[1:]):
        if x <= x1:
            f = (x - x0) / (x1 - x0)
            return a0 + f * (a1 - a0), b0 + f * (b1 - b0)
    return pts[-1][1], pts[-1][2]


def path_error(det, utc, delta_km):
    """paths.path_error's dict from NIMA's sigma table: sigma3_km (3 x the RSS, as Horizons' RSS column), the 1-sigma
    ellipse (axes along RA and dec, PA 90 when RA's is the larger)."""
    s = sigma_arcsec(det, utc)
    if s is None:
        return None
    import math
    sa, sd = s
    return dict(sigma3_km=3.0 * math.hypot(sa, sd) * math.pi / 648000.0 * delta_km,
                smaa_mas=max(sa, sd) * 1000.0, smia_mas=min(sa, sd) * 1000.0, pa_deg=90.0 if sa >= sd else 0.0)


def shift_components(spice, body_naifs, primary_naif, nima_naif, et0, et1, cache_dir, tag, step_s=1200.0):
    """A binary's bodies moved with NIMA: each body's JPL state plus (NIMA - JPL primary), as type-13 SPKs under the
    bodies' own ids, loaded after the JPL ones (so they win). NIMA fits the light of the system, which the primary
    dominates: the primary takes NIMA's position and each satellite keeps its JPL offset from it. All states are
    taken before any file is loaded (a loaded primary would change the satellites' offsets). Returns the paths."""
    import numpy as np
    ets = np.arange(et0, et1 + step_s, step_s)
    paths = {b: os.path.join(cache_dir, f"PySyzygos_nima_component_{b}_{tag}_{int(et0)}_{int(et1)}.bsp")
             for b in body_naifs}
    todo = [b for b in body_naifs if not os.path.isfile(paths[b])]
    if todo:
        state = lambda naif, et: np.array(spice.spkgeo(int(naif), float(et), "J2000", 10)[0])
        delta = np.array([state(nima_naif, et) - state(primary_naif, et) for et in ets])
        for b in todo:
            st = np.array([state(b, et) for et in ets]) + delta
            tmp = paths[b] + f".{os.getpid()}.tmp.bsp"
            if os.path.exists(tmp):
                os.remove(tmp)
            h = spice.spkopn(tmp, "PySyzygos NIMA-shifted body", 0)
            spice.spkw13(h, int(b), 10, "J2000", float(ets[0]), float(ets[-1]), f"{b} + NIMA {tag}", 7, len(ets), st,
                         ets)
            spice.spkcls(h)
            os.replace(tmp, paths[b])
    for b in body_naifs:
        spice.furnsh(paths[b])
    return list(paths.values())
