"""bodies.py - planets and their moons as occultation targets (major bodies), next to the asteroids.

A major body is given in the target list by a type prefix and its name, so it can never be mistaken for an asteroid
number: `P:Jupiter` (planet), `M:Io` (moon of a planet); later `L:Moon` (Earth's Moon). Groups (GROUPS) collect a
planet with its main moons, e.g. "jupiter": P:Jupiter, M:Io, M:Europa, M:Ganymede, M:Callisto.

Positions: de440 has only the planet systems' barycentres. For the planet itself and its moons PySyzygos asks JPL
Horizons for positions and velocities relative to the barycentre over the search window and writes them into a
small SPICE kernel (type 13, Hermite interpolation; 20 min steps reproduce Horizons to ~1 m), cached in cache_path,
like the asteroid orbits. Horizons uses the same ephemeris as NAIF's satellite kernels (e.g. jup365), so the
1 GB kernel download is not needed. The target name ("M:IO") becomes a SPICE alias of the body (kernels.body_alias), so the
search, maps and previews work with it unchanged.

Size: radii from the planet constants kernel (pck00010). Brightness: V(1,0) and a phase coefficient
(V = V10 + 5 log10(r delta) + beta * phase), used as H with G for the moons (the drop works as for asteroids); a
planet has no H: no drop filter, the run's star limit (MAG_MIN). Path uncertainty: rough
3-sigma values per body (SIGMA3_KM), since Horizons gives none for them.
"""
from pysyzygos.version import __version__
from pysyzygos import urls as U
import json, math, os, tempfile
import numpy as np

# the planets (P:), with Pluto as an asteroid-like dwarf planet (H, drop rule); V(1,0), phase coefficient mag/deg
SYSTEMS = {4: "mars", 5: "jupiter", 6: "saturn", 7: "uranus", 8: "neptune", 9: "pluto"}
PLANETS = {
    "mars":    dict(naif=499, center=4, kind="planet", v10=-1.60, beta=0.016),
    "jupiter": dict(naif=599, center=5, kind="planet", v10=-9.40, beta=0.005),
    "saturn":  dict(naif=699, center=6, kind="planet", v10=-8.88, beta=0.044),     # globe only: rings not modelled
    "uranus":  dict(naif=799, center=7, kind="planet", v10=-7.11, beta=0.002),
    "neptune": dict(naif=899, center=8, kind="planet", v10=-7.00, beta=0.0),
    "pluto":   dict(naif=999, center=9, kind="dwarf", v10=-0.75, beta=0.04),       # point-like: asteroid rules
}
SAT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "satellites.json")


def _sigma3(kind, radius_km):
    """Rough 3-sigma path uncertainty (km): planets 50, large moons 15, mid-size 50, small 200 (Horizons gives none
    for natural satellites; the small irregular moons' orbits are much less certain)."""
    if kind in ("planet", "dwarf"):
        return 50.0
    r = radius_km or 0.0
    return 15.0 if r >= 200 else 50.0 if r >= 20 else 200.0


def _registry():
    """name (lower case) -> entry: the planets, then every satellite of data/satellites.json (built from JPL
    Horizons: `python -m pysyzygos.bodies build`); the Galilean moons also without that file."""
    reg = {}
    for name, p in PLANETS.items():
        reg[name] = dict(p, name=name.capitalize(), prefix="P", group=name, radius_km=None, h=None,
                         sigma3=_sigma3(p["kind"], None))
    sats = [dict(naif=501, name="Io", radius_km=1821.5, h=-1.68), dict(naif=502, name="Europa", radius_km=1560.8, h=-1.41),
            dict(naif=503, name="Ganymede", radius_km=2631.2, h=-2.09), dict(naif=504, name="Callisto", radius_km=2410.3, h=-1.05)]
    try:
        with open(SAT_FILE, encoding="utf-8") as f:
            sats = json.load(f)["satellites"]
    except (OSError, ValueError, KeyError):
        pass
    for m in sats:
        system = m["naif"] // 100 if m["naif"] < 1000 else m["naif"] // 10000
        if system not in SYSTEMS:
            continue
        key = m["name"].lower()
        if key in reg:                                   # (no clash today; keep the planet / first one)
            continue
        reg[key] = dict(naif=m["naif"], center=system, kind="moon", prefix="M", group=SYSTEMS[system], name=m["name"],
                        radius_km=m.get("radius_km"), h=m.get("h"), v10=m.get("h"), beta=0.03,
                        estimated=bool(m.get("radius_est") or m.get("h_est")),
                        sigma3=_sigma3("moon", m.get("radius_km")))
    return reg


REGISTRY = _registry()


def _groups():
    """group -> [targets]: the planet, then its moons by size (moons without size or brightness left out)."""
    out = {}
    for b in REGISTRY.values():
        out.setdefault(b["group"], [])
    for g in out:
        members = [b for b in REGISTRY.values() if b["group"] == g]
        planet = [b for b in members if b["prefix"] == "P"]
        moons = sorted((b for b in members if b["prefix"] == "M" and usable(b)), key=lambda b: -(b["radius_km"] or 0))
        out[g] = [f"{b['prefix']}:{b['name']}" for b in planet + moons]
    return out


def featured(group, min_radius_km=150.0):
    """(major, smaller): a group's planet and its moons of at least min_radius_km, and the other usable moons."""
    major, small = [], []
    for t in GROUPS.get(group, []):
        b = parse(t)
        (major if b["prefix"] == "P" or (b.get("radius_km") or 0) >= min_radius_km else small).append(t)
    return major, small


def usable(b):
    """A moon can be searched when its size and brightness are known (the newest provisional ones have neither)."""
    return b["prefix"] == "P" or (b.get("radius_km") or 0) > 0 and b.get("h") is not None


GROUPS = _groups()
# optional NAIF satellite kernels for offline use (pysyzygos setup asks; then used instead of Horizons when they cover
# the body and window): file, size. Uranus: NAIF splits it per moon (up to 2 GB each): Horizons only.
NAIF_KERNELS = {"jupiter": ("jup365.bsp", "1.1 GB"), "saturn": ("sat441.bsp", "631 MB"),
                "neptune": ("nep097.bsp", "100 MB"), "pluto": ("plu060.bsp", "129 MB"), "mars": ("mar099.bsp", "1.1 GB")}
from pysyzygos.astrometry import DEFLECTORS        # light deflection: Sun, Jupiter and Saturn (by name)
CENTER_NAMES = {10: "SUN", 5: "JUPITER BARYCENTER", 6: "SATURN BARYCENTER"}
MOON_G = 0.5                                        # H-G slope for moons: a flatter phase curve than asteroids
LOADED = set()                                      # targets whose kernel is loaded in this process (previews)
STEP_MIN = 20                                       # Horizons sample step for the kernels
PAD_DAYS = 2.0                                      # kernel span: search window +/- this


def parse(target):
    """'M:Io' -> the registry entry with name and alias (dict), or None for anything else (an asteroid)."""
    t = str(target).strip()
    if len(t) < 3 or t[1] != ":":
        return None
    b = REGISTRY.get(t[2:].strip().lower())
    if b is None or b["prefix"] != t[0].upper():
        return None
    return dict(b, alias=f"{b['prefix']}:{b['name']}".upper(), target=f"{b['prefix']}:{b['name']}")


def is_body(target):
    return parse(target) is not None


def kind(target):
    b = parse(target)
    return b["kind"] if b else "asteroid"


def name(target):
    b = parse(target)
    return b["name"] if b else str(target)


def deflectors(target):
    """Bodies whose light deflection is applied (astrometry.corrected_star_dir): without the target's own system
    (for Jupiter or a Galilean moon the 'star minus target' deflection by Jupiter is undefined or dominated by the
    target being inside Jupiter's system)."""
    b = parse(target)
    return tuple(d for d in DEFLECTORS if not b or d != CENTER_NAMES.get(int(b["center"])))


def sigma3_km(target):
    b = parse(target)
    return b["sigma3"] if b else None


def _horizons_states(naif, center, start, stop, step_min=STEP_MIN, timeout=120):
    """(ets, states) of body naif relative to body center from JPL Horizons (ICRF, km, km/s, TDB)."""
    import requests
    p = dict(format="json", COMMAND=f"'{naif}'", EPHEM_TYPE="'VECTORS'", CENTER=f"'500@{center}'",
             START_TIME=f"'{start}'", STOP_TIME=f"'{stop}'", STEP_SIZE=f"'{step_min}m'", VEC_TABLE="'2'",
             REF_PLANE="'FRAME'", REF_SYSTEM="'ICRF'", OUT_UNITS="'KM-S'", CSV_FORMAT="'YES'", VEC_LABELS="'NO'",
             TIME_TYPE="'TDB'")
    r = requests.get(U.URL_JPL_HORIZONS_API, params=p, timeout=timeout)
    r.raise_for_status()
    text = r.json().get("result", "")
    if "$$SOE" not in text:
        raise RuntimeError(f"Horizons gave no vectors for {naif}: {text[:300]}")
    rows = [ln.split(",") for ln in text[text.index("$$SOE") + 5:text.index("$$EOE")].strip().splitlines()]
    jd = np.array([float(x[0]) for x in rows])
    states = np.array([[float(v) for v in x[2:8]] for x in rows])
    return (jd - 2451545.0) * 86400.0, states


def naif_kernel(group, folder="."):
    """Path of the downloaded NAIF satellite kernel of a group in folder, or None."""
    f = NAIF_KERNELS.get(group)
    p = os.path.join(folder, f[0]) if f else None
    return p if p and os.path.isfile(p) else None


def download_naif(group, folder="."):
    """Download a group's NAIF satellite kernel (curl into .part, renamed when complete). Returns the path or None."""
    import subprocess
    f = NAIF_KERNELS.get(group)
    if not f:
        return None
    path, part = os.path.join(folder, f[0]), os.path.join(folder, f[0] + ".part")
    if os.path.isfile(path):
        return path
    print(f"   downloading {f[0]} ({f[1]}) from NAIF ...", flush=True)
    try:
        subprocess.run(["curl", "-f", "-L", "-C", "-", "-o", part, U.URL_NAIF_SATELLITES + f[0]], check=True)
        os.replace(part, path)
        return path
    except (subprocess.CalledProcessError, OSError) as ex:
        print(f"   download failed ({ex}); rerun to resume (the .part file is kept), or use Horizons (default)")
        return None


def ensure_kernel(spice, target, et0, et1, cache_dir, folder="."):
    """Load the ephemeris of a major body for et0..et1 and set its alias: the group's NAIF satellite kernel if it was
    downloaded (offline) and covers the window, else a kernel built once from Horizons (cached; padded by
    PAD_DAYS). Returns the kernel path."""
    b = parse(target)
    local = naif_kernel(b["group"], folder)
    if local:
        cov = spice.spkcov(local, b["naif"]) if hasattr(spice, "spkcov") else None
        try:
            ok = cov is not None and spice.wncard(cov) > 0 and spice.wnfetd(cov, 0)[0] <= et0 and \
                spice.wnfetd(cov, spice.wncard(cov) - 1)[1] >= et1
        except Exception:
            ok = False
        if ok:
            spice.furnsh(local)
            from pysyzygos import kernels as K
            K.body_alias(spice, b["alias"], b["naif"])
            LOADED.add(b["target"])
            return local
    t0 = spice.et2utc(et0 - PAD_DAYS * 86400.0, "ISOC", 0)[:10]
    t1 = spice.et2utc(et1 + PAD_DAYS * 86400.0, "ISOC", 0)[:10]
    path = os.path.join(cache_dir, f"PySyzygos_body_{b['naif']}_{b['center']}_{t0}_{t1}.bsp")
    if not os.path.isfile(path):
        ets, states = _horizons_states(b["naif"], b["center"], t0, t1)
        fd, tmp = tempfile.mkstemp(dir=cache_dir, suffix=".bsp")
        os.close(fd)
        os.remove(tmp)                                             # spkopn wants a new file
        h = spice.spkopn(tmp, "PySyzygos major body", 0)
        spice.spkw13(h, b["naif"], b["center"], "J2000", float(ets[0]), float(ets[-1]),
                     f"{b['name']} from JPL Horizons", 7, len(ets), states, ets)
        spice.spkcls(h)
        os.replace(tmp, path)
    spice.furnsh(path)
    from pysyzygos import kernels as K
    K.body_alias(spice, b["alias"], b["naif"])
    LOADED.add(b["target"])
    return path


def size(spice, target):
    """The size dict of the search (as get_asteroid_size gives for asteroids): radius from the planet constants
    kernel (else the satellite table), H and G for moons and Pluto (Horizons' brightness as H, H-G law with G = MOON_G),
    none for the planets (no drop filter: a planet's light swamps it; the run's star limit only)."""
    b = parse(target)
    try:
        radii = np.asarray(spice.bodvcd(int(b["naif"]), "RADII", 3)[1], float)
        r_eq, r_pol, r_mean, src = float(radii[0]), float(radii[2]), float(radii.mean()), "NAIF planet constants"
    except Exception:                                    # small moons: the radius from JPL Horizons (satellite table)
        r_eq = r_pol = r_mean = float(b.get("radius_km") or 0.0)
        src = "JPL Horizons (satellite table)" + (", estimated" if b.get("estimated") else "")
    out = dict(r_km=r_eq if b["kind"] == "planet" else r_mean, r_min_km=r_pol, r_max_km=r_eq,
               source=("H only, albedo assumed: " if b.get("estimated") else "") + f"{src} (radius {r_eq:g} km)",
               H=None, G=None, D_est=bool(b.get("estimated")), kind=b["kind"], name=b["name"])
    if b["kind"] == "moon" and b.get("h") is not None:
        out.update(H=b["h"], G=MOON_G)
    elif b["kind"] == "dwarf":
        out.update(H=b["v10"], G=0.15)
    return out


def magnitude(spice, target, et):
    """Apparent V of a major body at et (V10 + 5 log10(r delta) + beta * phase angle)."""
    b = parse(target)
    tgt = np.asarray(spice.spkpos(b["alias"], et, "J2000", "LT", "EARTH")[0])
    sun = np.asarray(spice.spkpos(b["alias"], et, "J2000", "LT", "SUN")[0])
    au = 1.495978707e8
    d, r = np.linalg.norm(tgt) / au, np.linalg.norm(sun) / au
    phase = math.degrees(math.acos(float(np.clip(np.dot(tgt, sun) / (np.linalg.norm(tgt) * np.linalg.norm(sun)), -1, 1))))
    return b["v10"] + 5 * math.log10(r * d) + b["beta"] * phase


# ---------------------------------------------------------------- the satellite table (maintainers)
def _horizons(params, timeout=60):
    import requests
    r = requests.get(U.URL_JPL_HORIZONS_API, params=dict(format="json", **params), timeout=timeout)
    r.raise_for_status()
    return r.json().get("result", "")


def satellite_ids():
    """[(naif, name)] of every natural satellite of Mars to Pluto in Horizons' major-body list."""
    import re
    out = []
    for line in _horizons({"COMMAND": "'MB'"}).splitlines():
        m = re.match(r"^\s*(\d+)\s+(\S.*?)\s{2,}", line + "  ")
        if not m:
            continue
        i = int(m.group(1))
        system = i // 100 if i < 1000 else i // 10000
        if (400 < i < 1000 and i % 100 != 99 and system in SYSTEMS) or (50000 <= i < 100000 and system in SYSTEMS):
            out.append((i, m.group(2).strip()))
    return out


def satellite_entry(naif, name, date="2026-10-15"):
    """One satellite from a Horizons observer table: radius (angular diameter x distance) and H = APmag -
    5 log10(r delta), both None when Horizons does not know them."""
    text = _horizons({"COMMAND": f"'{naif}'", "EPHEM_TYPE": "'OBSERVER'", "CENTER": "'500@399'",
                      "START_TIME": f"'{date}'", "STOP_TIME": f"'{date} 01:00'", "STEP_SIZE": "'1h'",
                      "QUANTITIES": "'9,13,19,20'", "CSV_FORMAT": "'YES'"})
    entry = dict(naif=naif, name=name.replace(" ", "_"), radius_km=None, h=None)
    if "$$SOE" not in text:
        return entry
    lines = text[:text.index("$$SOE")].strip().splitlines()
    head = [h.strip() for h in lines[-2].split(",")] if len(lines) > 1 else []
    row = [v.strip() for v in text[text.index("$$SOE") + 5:].strip().splitlines()[0].split(",")]
    get = lambda col: (float(row[head.index(col)]) if col in head and row[head.index(col)] not in ("n.a.", "") else None)
    mag, diam, r, delta = get("APmag"), get("Ang-diam"), get("r"), get("delta")
    if diam and delta:
        entry["radius_km"] = round(diam / 2 / 206264.806 * delta * 1.495978707e8, 2)
    if mag is not None and r and delta:
        entry["h"] = round(mag - 5 * math.log10(r * delta), 2)
    return entry


def fill_estimates(sats):
    """Complete a missing size or brightness like for asteroids (D = 1329 km / sqrt(p) * 10^(-H/5)), flagged as
    estimates: no size -> from H with albedo 0.05 (mostly dark irregular moons); no brightness -> from the size with
    albedo 0.5 for Saturn's icy inner moons, 0.07 for the others. Moons with neither stay unusable."""
    for m in sats:
        system = m["naif"] // 100 if m["naif"] < 1000 else m["naif"] // 10000
        if m.get("radius_km") is None and m.get("h") is not None:
            m["radius_km"], m["radius_est"] = round(1329.0 / math.sqrt(0.05) * 10 ** (-m["h"] / 5) / 2, 2), True
        elif m.get("h") is None and m.get("radius_km"):
            p = 0.5 if system == 6 else 0.07
            m["h"], m["h_est"] = round(5 * math.log10(1329.0 / (2 * m["radius_km"] * math.sqrt(p))), 2), True
    return sats


def phase_correct(sats, date, kernels="."):
    """Horizons' APmag includes the phase dimming at `date`; turn h into an H for the H-G law the search uses
    (G = 0.5): H = mag - 5 log10(r delta) + 2.5 log10((1-G) phi1 + G phi2), with each system's phase angle from
    SPICE (de440: Sun - system barycentre - Earth). Estimated values (h_est) are already H."""
    import spiceypy as spice
    from pysyzygos.kernels import lsk_file
    for k in (lsk_file(kernels), os.path.join(kernels, "de440.bsp")):
        spice.furnsh(k)
    et = spice.str2et(date)
    alpha = {}
    for system in SYSTEMS:
        bary = spice.bodc2n(int(system))                                          # by name (asteroid numbers are names)
        e = np.asarray(spice.spkpos("EARTH", et, "J2000", "LT", bary)[0])               # body -> Earth
        sun = np.asarray(spice.spkpos("SUN", et, "J2000", "LT", bary)[0])               # body -> Sun
        alpha[system] = math.acos(float(np.dot(e, sun) / (np.linalg.norm(e) * np.linalg.norm(sun))))
    G = MOON_G
    for m in sats:
        system = m["naif"] // 100 if m["naif"] < 1000 else m["naif"] // 10000
        if m.get("h") is None or m.get("h_est") or system not in alpha:
            continue
        half = math.tan(alpha[system] / 2)
        phi = (1 - G) * math.exp(-3.33 * half ** 0.63) + G * math.exp(-1.87 * half ** 1.22)
        m["h"] = round(m["h"] + 2.5 * math.log10(phi), 2)
    return sats


def build_satellites(out=SAT_FILE, date="2026-10-15", pause=0.5):
    """Write data/satellites.json: every satellite of Mars to Pluto with radius and brightness from Horizons
    (one request per satellite, gently paced). Returns the number written."""
    import time
    sats = []
    ids = satellite_ids()
    for k, (naif, name) in enumerate(ids, 1):
        try:
            sats.append(satellite_entry(naif, name, date))
        except Exception as ex:                          # keep going; the entry stays without size/brightness
            sats.append(dict(naif=naif, name=name.replace(" ", "_"), radius_km=None, h=None))
            print(f"  {naif} {name}: {ex}")
        if k % 25 == 0:
            print(f"  {k}/{len(ids)}", flush=True)
        time.sleep(pause)
    phase_correct(sats, date)                            # before estimating: estimates from H are already H
    fill_estimates(sats)
    data = dict(meta=dict(source="JPL Horizons (major-body list; observer table: APmag, Ang-diam, r, delta); "
                                 "missing size or brightness estimated (radius_est, h_est)",
                          date=date, satellites=len(sats), usable=sum(1 for m in sats if m["radius_km"] and m["h"] is not None)),
                satellites=sats)
    tmp = out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=0)
    os.replace(tmp, out)
    return len(sats)


def remove_naif(group, folder="."):
    """Delete a group's NAIF kernel (and a partial download). True if something was deleted."""
    f = NAIF_KERNELS.get(group)
    gone = False
    for p in ((os.path.join(folder, f[0]), os.path.join(folder, f[0] + ".part")) if f else ()):
        if os.path.exists(p):
            os.remove(p)
            gone = True
    return gone


def kernels_status(folder="."):
    """[(group, file, size text, present, bytes)] of the optional NAIF kernels."""
    out = []
    for g, (fname, size) in NAIF_KERNELS.items():
        p = os.path.join(folder, fname)
        out.append((g, fname, size, os.path.isfile(p), os.path.getsize(p) if os.path.isfile(p) else 0))
    return out


def main():
    """pysyzygos planets [status] | add [system ...] | remove [system ...]: the optional NAIF kernels that make the
    planets' and moons' positions work offline (without them: JPL Horizons per search). Systems: """ + ", ".join(NAIF_KERNELS)
    import sys
    a = sys.argv[1:]
    if a and a[0] == "build":
        n = build_satellites()
        print(f"{n} satellites -> {SAT_FILE}")
        return 0
    if a and a[0] in ("add", "remove", "status"):
        groups = [g.lower() for g in a[1:]] or (list(NAIF_KERNELS) if a[0] != "remove" else [])
        bad = [g for g in groups if g not in NAIF_KERNELS]
        if bad:
            sys.exit(f"unknown system(s) {', '.join(bad)}; choose from {', '.join(NAIF_KERNELS)}")
        if a[0] == "add":
            for g in groups:
                print(f"{g}: {download_naif(g) or 'not downloaded'}", flush=True)
        elif a[0] == "remove":
            if not groups:
                sys.exit("name the system(s) to remove, e.g.: pysyzygos planets remove mars")
            for g in groups:
                print(f"{g}: {'removed' if remove_naif(g) else 'not there'}")
        for g, fname, size, have, n in kernels_status():
            print(f"  {g:8s} {fname:12s} " + (f"ok, {n / 1e9:.2f} GB (offline)" if have else
                                               f"not downloaded ({size}): positions from JPL Horizons per search"))
        return 0
    for g, members in GROUPS.items():
        print(f"{g}: {len(members)} targets: {' '.join(members[:12])}{' ...' if len(members) > 12 else ''}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
