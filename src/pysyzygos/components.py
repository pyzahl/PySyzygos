"""components.py - the bodies of a binary asteroid, each with its own JPL ephemeris.

    pysyzygos binary <favorite key>          each body's shadow path and timing at the favorite's site
    pysyzygos binary --list                  which asteroids JPL has per-body ephemerides for (asked anew)

JPL's orbit of a binary asteroid such as (617) Patroclus describes the system (one orbit for the pair): the point
the search, the pick and Occult's predictions use, where no body need be. JPL Horizons also has ephemerides of the
bodies (primary 920000617 = Patroclus, satellites 120000617 = Menoetius, 220000617, ...; k * 1e8 + 2e7 + number),
as state vectors only (no SPK): they become a small SPK of type 13 (as bodies.ensure_kernel for planets' moons).
Only a few asteroids have them (KNOWN, 7 on 2026-11-04 out of 185 with a satellite of 1 km or more: Patroclus, Quaoar,
Orcus, Salacia, Haumea, Eris, Kagara; Pluto and Charon are planets & moons, bodies.py). For these the search takes
each body as a target of its own instead of the system point ('617+P', '617+S1': JPL ids k * 1e8 + 2e7 + number),
with Johnston's sizes and the system's H shared by area, and every hit's map shows all bodies (search_bodies,
path lines 'Body n ...'); the pick widens its margin for them by the moons' distance (pick_margin_km). Results for
other binaries are marked (+moon) and the Favorites panel computes each body on request where JPL has them.

Writes favorites/<key>/binary/: bodies.json, bodies.md (a table per body: offset from the system point, closest
approach at the site, D and R when the site is inside its shadow) and bodies.kml (each body's center line and
shadow limits; the favorite's own map has the system's path); the favorite gets the summary as its field 'binary'.
"""
import argparse, json, math, os, re, sys, tempfile, time
from datetime import datetime, timedelta, timezone

import numpy as np

from pysyzygos.version import __version__

KINDS = (("primary", 9), ("satellite I", 1), ("satellite II", 2), ("satellite III", 3))
KNOWN = ("617", "50000", "90482", "120347", "136108", "136199", "469705")   # JPL per-body ephemerides, 2026-11-04
ID_RE = re.compile(r"^(\d+)\+(P|S\d)$")             # a body as a search target: '617+P', '617+S1'


def is_component(target):
    return bool(ID_RE.match(str(target).strip()))


def system(target):
    """'617' for '617+S1' (any other target unchanged): SBDB data, orbit class and path uncertainty are the system's."""
    m = ID_RE.match(str(target).strip())
    return m.group(1) if m else str(target).strip()


def kind_of(target):
    """'primary' / 'satellite I' / ... of a body target, '' otherwise."""
    m = ID_RE.match(str(target).strip())
    if not m:
        return ""
    return "primary" if m.group(2) == "P" else next(k for k, n in KINDS if n == int(m.group(2)[1:]))


def known(cache_dir=None):
    """The asteroid numbers with per-body ephemerides: KNOWN and those the cache found (pick margins: no network)."""
    out = set(KNOWN)
    try:
        if cache_dir is None:
            from pysyzygos import config
            cache_dir = config.cache_path
        with open(os.path.join(cache_dir, CACHE), encoding="utf-8") as fh:
            out |= {n for n, v in json.load(fh).items() if v.get("bodies")}
    except Exception:
        pass
    return out


def pick_margin_km(number):
    """Extra screening margin for a binary whose bodies are searched separately: the farthest moon's distance plus
    its radius (binaries.zone_km); 0 for any other asteroid."""
    from pysyzygos import binaries
    return float(binaries.zone_km(number) or 0.0) if str(number) in known() else 0.0


def body_size(target, system_size):
    """The search's size dict of a body (r_km, r_min_km, r_max_km, source, H, G): Johnston's diameter (+-10 %), the
    system's H shared by area (each body's light: its share of the summed cross-sections); None if no size."""
    number, kind = system(target), kind_of(target)
    rad = sizes(number)
    r = rad.get(kind)
    if not r:
        return None
    H, G = (system_size or {}).get("H"), (system_size or {}).get("G")
    if H is not None and rad:
        H = H - 2.5 * math.log10(r * r / sum(v * v for v in rad.values()))
    return dict(r_km=r, r_min_km=0.9 * r, r_max_km=1.1 * r, H=H, G=G,
                source=f"Johnston 2019 binary compilation ({kind}), H shared by area")
CACHE = "PySyzygos_components.json"               # in cache_path: which asteroids have per-body ephemerides
CACHE_DAYS = 30
OUT = "binary"                                    # favorites/<key>/binary/


def naif_id(number, k):
    """JPL's id of a binary's body: k = 9 primary, 1, 2, ... satellites (k * 1e8 + 2e7 + number)."""
    return k * 10 ** 8 + 2 * 10 ** 7 + int(number)


def alias(number, kind):
    """The body's SPICE name: '617+P' (primary), '617+S1' (satellite I), ..."""
    k = dict(KINDS)[kind]
    return f"{number}+P" if k == 9 else f"{number}+S{k}"


def _horizons_name(naif, timeout=60):
    """The body's name in Horizons ('(617) Patroclus I Menoetius'), or None when Horizons has no such body."""
    import requests
    from pysyzygos import urls as U
    r = requests.get(U.URL_JPL_HORIZONS_API, params=dict(format="json", COMMAND=f"'{naif}'", OBJ_DATA="YES",
                                                          MAKE_EPHEM="NO"), timeout=timeout)
    r.raise_for_status()
    text = r.json().get("result", "") or ""
    if "out of bounds" in text or "No matches" in text or "JPL/HORIZONS" not in text:
        return None
    m = re.search(r"JPL/HORIZONS\s+(.+?)\s{2,}", text)
    return m.group(1).strip() if m else str(naif)


def available(number, cache_dir=None, log=print):
    """[dict(kind, naif, name)] of the bodies JPL has ephemerides for (primary first), [] if none; asked once per
    CACHE_DAYS (cache file in cache_path)."""
    number = str(number).strip()
    if not number.isdigit() or int(number) >= 10 ** 7:
        return []
    if cache_dir is None:
        from pysyzygos import config
        cache_dir = config.cache_path
    path = os.path.join(cache_dir, CACHE)
    try:
        with open(path, encoding="utf-8") as fh:
            cache = json.load(fh)
    except (OSError, ValueError):
        cache = {}
    hit = cache.get(number)
    if hit and time.time() - hit.get("t", 0) < CACHE_DAYS * 86400:
        return hit["bodies"]
    out = []
    for kind, k in KINDS:
        name = _horizons_name(naif_id(number, k))
        if name is None:
            if kind == "primary":
                break                                  # no per-body ephemerides for this asteroid
            break
        out.append(dict(kind=kind, naif=naif_id(number, k), name=name))
    cache[number] = dict(t=time.time(), bodies=out)
    fd, tmp = tempfile.mkstemp(dir=cache_dir, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(cache, fh)
    os.replace(tmp, path)
    return out


def ensure_kernel(spice, number, body, et0, et1, cache_dir):
    """Load the body's ephemeris for et0..et1 (Horizons vectors relative to the Sun, 20-min steps, as a type-13 SPK,
    cached) and set its SPICE name alias(number, kind). Returns the alias."""
    from pysyzygos import bodies, kernels
    t0 = spice.et2utc(et0 - bodies.PAD_DAYS * 86400.0, "ISOC", 0)[:10]
    t1 = spice.et2utc(et1 + bodies.PAD_DAYS * 86400.0, "ISOC", 0)[:10]
    path = os.path.join(cache_dir, f"PySyzygos_component_{body['naif']}_{t0}_{t1}.bsp")
    if not os.path.isfile(path):
        ets, states = bodies._horizons_states(body["naif"], 10, t0, t1)
        fd, tmp = tempfile.mkstemp(dir=cache_dir, suffix=".bsp")
        os.close(fd)
        os.remove(tmp)                                  # spkopn wants a new file
        h = spice.spkopn(tmp, "PySyzygos binary body", 0)
        spice.spkw13(h, body["naif"], 10, "J2000", float(ets[0]), float(ets[-1]), f"{body['naif']} from JPL Horizons",
                     7, len(ets), states, ets)
        spice.spkcls(h)
        os.replace(tmp, path)
    spice.furnsh(path)
    name = alias(number, body["kind"])
    kernels.body_alias(spice, name, body["naif"])
    return name


def sizes(number):
    """{kind: radius km} from W. R. Johnston's compilation (binaries.py): primary d1, each satellite its d2."""
    from pysyzygos import binaries
    s = binaries.lookup(number) or {}
    out = {}
    for i, c in enumerate(s.get("sats") or []):
        if c.get("d1_km") and "primary" not in out:
            out["primary"] = c["d1_km"] / 2.0
        if c.get("d2_km"):
            out[f"satellite {'I' * (i + 1) if i < 3 else i + 1}"] = c["d2_km"] / 2.0
    return out


def short_name(body, number=None):
    """'Menoetius' from '(617) Patroclus I Menoetius'; for the primary its name from Johnston's list ('Patroclus')."""
    n = re.sub(r"^\(\d+\)\s*", "", body.get("name") or "").strip()
    if body["kind"] == "primary":
        from pysyzygos import binaries
        s = binaries.lookup(number) if number else None
        return (s or {}).get("name") or next((w for w in n.split() if not w.isdigit()), "primary")
    m = re.match(r".*?\s(?:I|II|III|IV)\s+(.+)$", n)
    return m.group(1) if m else (n or body["kind"])


# ------------------------------------------------------------------------------------------- one event
# Math: OB.1, LT.1, FP.1, FP.2, CA.1 (slides OB, LT, FP, CA): each body seen from the site, its closest approach.
def site_pass(spice, name, star_dir, site_itrf, t_guess, span_s=1800.0):
    """(t_ca, d_km, v_kms) of the body's shadow axis at the site (light time from the site), plane through the site."""
    from scipy.optimize import minimize_scalar
    from pysyzygos.paths import plane_basis
    x_ax, y_ax, _ = plane_basis(star_dir)

    def xy(t):
        v = np.asarray(spice.spkcpo(name, t, "J2000", "OBSERVER", "CN", site_itrf, "EARTH", "ITRF93")[0][:3])
        return np.array([v @ x_ax, v @ y_ax])
    r = minimize_scalar(lambda dt: float(np.hypot(*xy(t_guess + dt))), bounds=(-span_s, span_s), method="bounded",
                        options={"xatol": 1e-4, "maxiter": 500})
    t = t_guess + float(r.x)
    return t, float(r.fun), float(np.hypot(*(xy(t + 0.5) - xy(t - 0.5))))


def event(key, folder=None, log=print):
    """Each body of the favorite's binary asteroid for its event: writes favorites/<key>/binary/ and the favorite's
    'binary' field. Returns the summary dict."""
    import spiceypy as spice
    from pysyzygos import config, earth, favorites, kernels, obscheck, paths, screen
    from pysyzygos.pathcheck import entry_of
    folder = folder or favorites.DIR
    e = entry_of(key, folder)
    r, site = e.get("record") or {}, e.get("site") or {}
    number = str(r.get("target_id") or "").strip()
    if not number.isdigit():
        raise SystemExit(f"{key}: not a numbered asteroid")
    bodies_ = available(number, config.cache_path, log)
    if not bodies_:
        raise SystemExit(f"{number}: JPL has no ephemerides of this asteroid's bodies (only the system's orbit)")
    screen.load_kernels(spice)
    et_best = spice.str2et(str(r["best_utc"]))
    ra, dec = math.radians(float(r["star_ra"])), math.radians(float(r["star_dec"]))
    star_dir = np.array([math.cos(dec) * math.cos(ra), math.cos(dec) * math.sin(ra), math.sin(dec)])
    day = datetime.fromisoformat(str(r["best_utc"])[:19])
    tmp = tempfile.mkdtemp(prefix="binary_")
    fn = os.path.join(tmp, "system.bsp")
    with open(fn, "wb") as fh:
        fh.write(obscheck.horizons_spk(number, (day - timedelta(days=1)).strftime("%Y-%m-%d"),
                                       (day + timedelta(days=1)).strftime("%Y-%m-%d")))
    lat, lon = float(site.get("lat")), float(site.get("lon"))
    h_m = float(site.get("ele_wgs84") if site.get("ele_wgs84") not in (None, "") else
                (float(site.get("ele") or 0.0) + float(site.get("geoid_m") or 0.0)))
    site_itrf = spice.georec(math.radians(lon), math.radians(lat), h_m / 1000.0, earth.A_KM, earth.F)
    sig3 = 3.0 * float(r.get("path_sigma1_km") or 0.0) or float(getattr(config, "default_sigma3_km", 30.0))
    rad = sizes(number)
    x_ax, y_ax, _ = paths.plane_basis(star_dir)
    out = dict(version=__version__, made=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"), key=key,
               target=number, name=r.get("target_name", ""), event_utc=str(r["best_utc"]),
               site=dict(name=site.get("name", ""), lat=lat, lon=lon, h_m=round(h_m, 1)), sigma3_km=round(sig3, 2),
               bodies=[])
    lines = []
    try:
        spice.furnsh(fn)
        kernels.body_alias(spice, "BINARY_SYSTEM", int(spice.spkobj(fn)[0]))
        p_sys = np.asarray(spice.spkpos("BINARY_SYSTEM", et_best, "J2000", "CN", "EARTH")[0])
        for i, b in enumerate(bodies_, 1):
            nm = ensure_kernel(spice, number, b, et_best - 86400.0, et_best + 86400.0, config.cache_path)
            d = np.asarray(spice.spkpos(nm, et_best, "J2000", "CN", "EARTH")[0]) - p_sys
            r_km = rad.get(b["kind"])
            t, dist, v = site_pass(spice, nm, star_dir, site_itrf, et_best)
            x = dict(kind=b["kind"], name=short_name(b, number), horizons=b["name"], naif=b["naif"], r_km=r_km,
                     dx_km=round(float(d @ x_ax), 2), dy_km=round(float(d @ y_ax), 2),
                     ca_utc=spice.et2utc(t, "ISOC", 2), ca_km=round(dist, 2), speed_kms=round(v, 4))
            if r_km and dist < r_km:
                half = math.sqrt(r_km * r_km - dist * dist) / v
                x.update(inside=True, d_utc=spice.et2utc(t - half, "ISOC", 2), r_utc=spice.et2utc(t + half, "ISOC", 2),
                         duration_s=round(2 * half, 2))
            else:
                x.update(inside=False, outside_km=round(dist - (r_km or 0.0), 2) if r_km else None)
            try:
                bp = paths.shadow_path(nm, star_dir, t, r_km or 1.0, sig3)
                lines += [(f"Body {i} center {x['name']}", bp["center"]),
                          (f"Body {i} limit {x['name']} A", bp["edge_plus"]), (f"Body {i} limit {x['name']} B", bp["edge_minus"])]
            except Exception as ex:
                log(f"binary: no path for {x['name']}: {ex}")
            out["bodies"].append(x)
            log(f"binary: {x['name']} ({b['kind']}): {x['dx_km']:+.0f}, {x['dy_km']:+.0f} km from the system point; "
                f"closest {x['ca_utc'][11:]} UT, {dist:.1f} km" + (f", inside: D {x['d_utc'][11:]} R {x['r_utc'][11:]}"
                                                                  if x["inside"] else ""))
    finally:
        try:
            spice.unload(fn)
        except Exception:
            pass
        os.remove(fn)
        os.rmdir(tmp)
    d = os.path.join(folder, key, OUT)
    os.makedirs(d, exist_ok=True)
    _write_kml(lines, os.path.join(d, "bodies.kml"), f"{r.get('target_name', number)}: each body", (lon, lat),
               site.get("name", ""))
    with open(os.path.join(d, "bodies.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1)
    with open(os.path.join(d, "bodies.md"), "w", encoding="utf-8") as fh:
        fh.write(markdown(out))
    out["kml"] = os.path.relpath(os.path.join(d, "bodies.kml"), folder).replace(os.sep, "/")
    favorites.set_field(key, "binary", out, folder)
    return out


def _write_kml(lines, path, title, observer, site_name):
    from xml.sax.saxutils import escape
    col = {"Body 1": "ffeb6325", "Body 2": "ff27180f", "Body 3": "ff88940d", "Body 4": "ff0953b4"}   # as report.LINE_STYLES
    parts = []
    for name, pts in lines:
        if len(pts) < 2:
            continue
        c = next((v for k, v in col.items() if name.startswith(k)), "ff999999")
        coords = " ".join(f"{p[1]:.6f},{p[2]:.6f},0" for p in pts)
        parts.append(f"<Placemark><name>{escape(name)}</name><Style><LineStyle><color>{c}</color><width>"
                     f"{3 if ' center ' in name else 2}</width></LineStyle></Style><LineString><tessellate>1</tessellate>"
                     f"<coordinates>{coords}</coordinates></LineString></Placemark>")
    parts.append(f"<Placemark><name>{escape(site_name or 'Site')}</name><Point><coordinates>{observer[0]:.6f},"
                 f"{observer[1]:.6f},0</coordinates></Point></Placemark>")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write('<?xml version="1.0" encoding="UTF-8"?>\n<kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
                 f"<name>{escape(title)}</name>" + "".join(parts) + "</Document></kml>\n")


def markdown(out):
    """The summary as a Markdown table (Favorites panel)."""
    rows = ["| Body | Offset from the system point (km E, N) | Closest at the site (UT) | Distance (km) | "
            "Radius (km) | At the site |", "|---|---|---|---:|---:|---|"]
    for b in out["bodies"]:
        at = (f"**inside**: D {b['d_utc'][11:]}, R {b['r_utc'][11:]} ({b['duration_s']:.2f} s)" if b.get("inside") else
              f"outside by {b['outside_km']:.1f} km" if b.get("outside_km") is not None else "size unknown")
        rows.append(f"| {b['name']} ({b['kind']}) | {b['dx_km']:+.1f}, {b['dy_km']:+.1f} | {b['ca_utc'][11:]} | "
                    f"{b['ca_km']:.1f} | {b['r_km'] or '?'} | {at} |")
    return (f"**{out['name']}**, {out['event_utc'][:19].replace('T', ' ')} UT at {out['site']['name']}: each body "
            f"as JPL predicts it (Horizons {', '.join(str(b['naif']) for b in out['bodies'])}); the search and its map "
            f"use the system's orbit, a point between the bodies. Path uncertainty (3-sigma, the system's): "
            f"{out['sigma3_km']:.0f} km. Computed {out['made'][:16].replace('T', ' ')} UT.\n\n" + "\n".join(rows) + "\n")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=f"PySyzygos {__version__}")
    ap.add_argument("key", nargs="?", help="the favorite's key (favorites/<key>/)")
    ap.add_argument("--list", action="store_true", help="ask JPL which binaries have per-body ephemerides (every "
                    "asteroid with a confirmed satellite of 1 km or more; ~3 min) and cache the answers")
    a = ap.parse_args(argv)
    if a.list:
        from pysyzygos import binaries, config
        nums = sorted({n for n, s in binaries.load()["systems"].items() for c in s.get("sats") or []
                       if (c.get("d2_km") or 0) >= 1}, key=int)
        try:
            os.remove(os.path.join(config.cache_path, CACHE))     # ask anew
        except OSError:
            pass
        found = [(n, available(n, config.cache_path)) for n in nums]
        for n, b in found:
            if b:
                print(n, "; ".join(x["name"] for x in b))
        print(f"{sum(1 for _, b in found if b)} of {len(nums)} binaries have per-body ephemerides at JPL "
              f"(components.KNOWN lists {len(KNOWN)})")
        return 0
    if not a.key:
        ap.error("a favorite's key, or --list")
    out = event(a.key)
    print(markdown(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
