"""setup.py - one-time setup of everything PySyzygos needs locally. Safe to rerun: finished parts are skipped,
an interrupted catalog build or download continues where it stopped.

    pysyzygos setup                   # kernels + the star catalog (asks the limit and its parts in a terminal)
    pysyzygos setup --source zenodo   # catalog: the ready-made G <= 16 from Zenodo, no question
    pysyzygos setup --source esa      # catalog: build it from ESA's Gaia files instead (any limit)
    pysyzygos setup --groups quality,extras   # the catalog's optional parts (all, none); on an installed catalog
                                      #   adds or removes parts to match
    pysyzygos setup --upgrade-catalog # replace a catalog of the old format (before 1.3.0) by the new one
    pysyzygos setup --no-gaia         # SPICE kernels only
    pysyzygos setup --status          # show what is there
    pysyzygos setup --no-geoip        # do not guess your site from your IP address
    pysyzygos setup --gmax 18         # a catalog to G 18 (built from ESA's files; own folder gaia_dr3_g18)
    pysyzygos setup --gmax 17 --dir /data/gaia_g17
    pysyzygos setup --home ~/PySyzygos      # keep all data in this folder from now on (default for installed copies)

  0. Your observing site (sites.py, private): if missing, guessed from your IP address (ipinfo.io), or from a city or
     place name (Open-Meteo geocoding), or typed in; non-interactive runs copy sites_example.py.

  1. SPICE kernels (naif0012.tls, de440.bsp, pck00010.tpc, earth_latest_high_prec.bpc; ~120 MB) into this folder.
  2. The star catalog (starcat.py, format 2), G <= gaia_local_gmax, into gaia_local_dir (pysyzygos_config.py): all Gaia
     DR3 stars to that limit, sorted by sky cell and G, in parts: core (2.4 GB for G <= 16; needed), quality (1.6 GB:
     Gaia's errors and flags without network) and extras (0.8 GB: colours, radial velocity, Teff). Two ways:
       zenodo: the ready-made G <= 16 (doi:10.5281/zenodo.23113337), SHA-256 checked, unpacked; parts added any time.
       esa:    built here from ESA's bulk files (753 GB streamed, about 2 h), any limit; then proper motions of the
               2-parameter stars from UCAC5/UCAC4 (CDS XMatch). Resumable.
     In a terminal setup asks for the limit (Enter = 16), the parts (Enter = core + quality) and, for G 16, the source
     (Enter = zenodo). A catalog of the old format (before 1.3.0) keeps working; setup offers the upgrade (installed
     next to it, swapped in, the old one deleted on request).
"""
from pysyzygos.version import __version__
import argparse, json, os, shutil, sys

from pysyzygos import home, starcat
from pysyzygos.home import PKG


def own_data(folder):
    """True if folder holds data of your own (not just the files PySyzygos creates from its templates)."""
    if not os.path.isdir(folder):
        return False
    example = os.path.join(PKG, "templates", "sites_example.py")
    for n in os.listdir(folder):
        if n in ("__pycache__", "pysyzygos_config.py"):
            continue
        if n == "sites.py":
            with open(os.path.join(folder, n)) as f, open(example) as g:
                if f.read() == g.read():
                    continue
        return True
    return False


def choose_home(argv):
    """The data folder for this and all later runs: `--home <folder>` sets it; the first setup of an installed copy
    (no setting, not a checkout) asks for it. Saved in home.POINTER; returns the folder."""
    if "--home" in argv:
        i = argv.index("--home")
        if i + 1 >= len(argv):
            sys.exit("--home needs a folder")
        old, new = home.HOME, home.save(argv[i + 1])
        home.HOME, home.SOURCE = new, "setting"
        print(f"data folder: {new}  (saved in {home.POINTER})")
        if os.path.realpath(old) != os.path.realpath(new) and own_data(old):
            print(f"   your files are still in {old}: move what you want to keep yourself (sites.py, "
                  f"pysyzygos_config.py, picks/, favorites/, ...; the Gaia catalog folders can be moved or linked)")
    elif home.SOURCE == "default" and sys.stdin.isatty() and "--status" not in argv:
        print("PySyzygos keeps its data in one folder: your sites and settings, the SPICE kernels, the Gaia catalog "
              "(3-11 GB),\nsaved picks, favorites and results.")
        k = input(f"   data folder [Enter = {home.DEFAULT}]: ").strip()
        home.HOME, home.SOURCE = home.save(k or home.DEFAULT), "setting"
        print(f"   data folder: {home.HOME}  (saved in {home.POINTER}; change it later with --home)")
    os.makedirs(home.HOME, exist_ok=True)
    return home.HOME


HOME = choose_home(sys.argv)
os.chdir(HOME)                                                      # kernels, catalogs, sites.py live in the data folder
EXAMPLE = os.path.join(PKG, "templates", "sites_example.py")
from pysyzygos import geo

SITES_HINT = """   Edit sites.py and enter your observing site(s), then rerun or just start searching:
     - lat, lon: geodetic degrees, longitude east-positive (west is negative); ele: metres
     - optional view: min_alt, max_sun_alt, reach_km; equipment: aperture_cm, frames, mag_adjust, extinction
       (all keys are explained at the top of pysyzygos/templates/sites_example.py in the PySyzygos code)
     - default_site names the site used; PYSYZYGOS_SITE=<name> picks another one for a single run
   sites.py stays private (it is in .gitignore)."""


APPROX = "APPROXIMATE"                       # marker in a generated sites.py: position not yet the exact one


def _get_json(url, timeout=10):
    return geo.get_json(url, timeout)


def _elevation(lat, lon):
    return geo.elevation(lat, lon)


def _ip_guess():
    """(lat, lon, ele, label) from the IP address (ipinfo.io; city level, 10-100 km, wrong behind a VPN), or None."""
    r = geo.ip_location()
    if r is None:
        print("   IP lookup failed")
    return r


def _city(name):
    """Pick a place from Open-Meteo's geocoding: (lat, lon, ele, label) or None."""
    res = geo.places(name)
    if not res:
        print(f"   no place called {name!r} found (or offline)")
        return None
    for i, (lat, lon, ele, label) in enumerate(res, 1):
        print(f"   {i}. {label}: {lat:.4f}, {lon:.4f}, {ele or 0:.0f} m")
    k = input(f"   which one [1-{len(res)}, Enter = 1]: ").strip() or "1"
    if not (k.isdigit() and 1 <= int(k) <= len(res)):
        return None
    return res[int(k) - 1]


def _manual():
    """lat, lon, ele typed in (ele empty: looked up). (lat, lon, ele, label) or None."""
    try:
        lat = float(input("   latitude, deg (north positive): "))
        lon = float(input("   longitude, deg (east positive, west negative): "))
        e = input("   elevation, m (Enter: look it up): ").strip()
    except ValueError:
        print("   not a number")
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 360):
        print("   out of range")
        return None
    return lat, (lon + 180) % 360 - 180, float(e) if e else _elevation(lat, lon), "entered by hand"


def _write_sites(lat, lon, ele, label, approx):
    from datetime import date
    from pysyzygos import geoid
    note = (f"  # {APPROX} ({label}): replace with your exact position" if approx else f"  # {label}")
    with open("sites.py", "w") as f:
        f.write(f"""# Your observing sites (not in git). Layout and optional keys: see src/pysyzygos/templates/sites_example.py.
# pysyzygos_config.py uses `default_site`, or the site named in the environment variable PYSYZYGOS_SITE.
# Created by setup.py on {date.today()}.

sites = {{
    "home": dict(lat={lat:.5f}, lon={lon:.5f}, ele={ele or 0:.0f}, name="Home",{note}
                 geoid_m={geoid.height(lat, lon):.1f},  # geoid above the WGS84 ellipsoid (EGM96); ele is above sea level
                 aperture_cm=25, min_alt=10),
}}

default_site = "home"
""")


def ensure_sites(geoip=True):
    """Create sites.py if the user has none yet (never overwrites). Interactive: guess the site from the IP address,
    or ask for a place name or lat/lon/ele; otherwise copy sites_example.py. True if just created."""
    if os.path.isfile("sites.py"):
        return False
    if not os.path.isfile(EXAMPLE):
        sys.exit(f"sites.py and {EXAMPLE} are both missing: reinstall PySyzygos (git checkout or pip)")
    if sys.stdin.isatty():
        print("No sites.py yet: let us set up your observing site.")
        guess = None
        if geoip:
            print("   looking up your approximate location from your IP address (ipinfo.io) ...")
            guess = _ip_guess()
        while True:
            if guess:
                lat, lon, ele, label = guess
                print(f"   {label}: {lat:.4f}, {lon:.4f}, {ele or 0:.0f} m")
                k = input("   [Enter] use it, [c]ity or place name, [m]anual lat/lon/ele, [s]kip (example site): ")
            else:
                k = input("   [c]ity or place name, [m]anual lat/lon/ele, [s]kip (example site): ")
            k = k.strip().lower()
            if guess and k == "":
                _write_sites(*guess, approx=guess[3] != "entered by hand")
                break
            if k.startswith("c"):
                guess = _city(input("   city or place: ").strip()) or guess
            elif k.startswith("m"):
                guess = _manual() or guess
            elif k.startswith("s"):
                shutil.copyfile(EXAMPLE, "sites.py")
                break
        print("   wrote sites.py")
        print(SITES_HINT)
        print()
        return True
    shutil.copyfile(EXAMPLE, "sites.py")
    print("WARNING: no sites.py found: created it from the example (site: New York City Hall).")
    print(SITES_HINT)
    print()
    return True


SITES_CREATED = ensure_sites(geoip="--no-geoip" not in sys.argv)   # before the config reads it
from pysyzygos import config
from pysyzygos import gaia_local as gaia
from pysyzygos.kernels import KERNELS, download_kernels


def planet_kernels(download, ask):
    """Optional: NAIF's satellite kernels for planets and moons (offline; else Horizons per search)."""
    from pysyzygos import bodies
    for group, (fname, size) in bodies.NAIF_KERNELS.items():
        if bodies.naif_kernel(group):
            continue
        if not download and ask:
            k = input(f"4. planets and moons ({group} system): their positions come from JPL Horizons with each search "
                      f"(online, small).\n   Download NAIF's {fname} ({size}) for offline use instead? [y/N]: ")
            download = k.strip().lower().startswith("y")
        if download:
            bodies.download_naif(group)


def show_status(d=None):
    print(f"  data folder                  {home.describe()}")
    with open("sites.py") as f:
        example = f.read() == open(EXAMPLE).read() if os.path.isfile(EXAMPLE) else False
    s = config.site
    if s.get("ele_ref") == "ellipsoid":
        height = f"{s['ele']:g} m (WGS84)"
    elif "geoid_m" in s:
        height = f"{s['ele']:g} m MSL {s['geoid_m']:+.1f} m geoid"
    else:
        height = f"{s['ele']:g} m (no geoid height yet: pysyzygos setup --geoid)"
    print(f"  site {config.site_name!r:26s} {config.LAT:.4f} {config.LON:.4f}, {height}, "
          f"{config.pick_aperture_cm:g} cm, stars G <= {config.MAG_MIN:g}" + ("   <- example site" if example else ""))
    if example:
        print("  WARNING: sites.py is still the example; enter your own site" + (" (see above)" if SITES_CREATED else ":"))
        if not SITES_CREATED:
            print(SITES_HINT)
    elif APPROX in open("sites.py").read():
        print("  WARNING: the site position in sites.py is approximate (from your IP address or a place name);"
              " replace it with your exact position (GPS, map) before observing.")
    from pysyzygos.kernels import LSK, lsk_file
    for k in KERNELS:
        k = os.path.basename(lsk_file(".")) if k == LSK else k                # the newest leap-second kernel
        print(f"  {k:28s} {'ok' if os.path.isfile(k) else 'missing'}")
    from pysyzygos import kernels as KK
    h = KK.historic_earth_pck(".")
    print(f"  {'Earth orientation < 2000':28s} " + (f"ok ({os.path.basename(h)})" if h else
          "not downloaded (only for dates before 2000: pysyzygos setup --historic-earth)"))
    from pysyzygos import bodies
    for group, (fname, size) in bodies.NAIF_KERNELS.items():
        print(f"  {fname:28s} {'ok (planets and moons offline)' if bodies.naif_kernel(group) else 'not downloaded: planets and moons via JPL Horizons (optional: --planet-kernels, ' + size + ')'}")
    d = d or getattr(config, "gaia_local_dir", None)
    if not d:
        print("  local Gaia catalog            gaia_local_dir not set in pysyzygos_config.py")
        return
    st = gaia.status(d)
    if starcat.is_format2(d):
        pmx = st.get("pm_xmatch") or {}
        newer = starcat.update_available(d)
        print(f"  star catalog {d:18s}  data version {starcat.data_version(d)}"
              + (f" (update: {newer}, pysyzygos setup --update-catalog)" if newer else "")
              + f", G <= {st['gmax']:g}, {st['n_stars'] / 1e6:.1f} M stars, {st['gb']:.1f} GB; "
              f"parts: {', '.join(st['groups'])}" + (f"; 2-param stars with pm {pmx['ucac5'] + pmx['ucac4']} of "
                                                       f"{pmx['two_param']}" if pmx else ""))
        _list_catalogs(d)
        return
    print(f"  local Gaia catalog {d:12s}  {st['done']}/{st['total'] or '?'} files, {st['gb']:.1f} GB"
          + (" (complete)" if st["complete"] else "") + ("; old format: pysyzygos setup --upgrade-catalog"
                                                         if st["complete"] else ""))
    gmax = index_limit(d)
    have = os.path.isfile(os.path.join(d, f"bright_G{gmax:.1f}.v2.npy"))
    print(f"  bright-star index G <= {gmax:<5g}  {'ok' if have else 'missing'}")
    ss = gaia.status(gaia.supplement_dir(d))
    pmx = {}
    if ss["complete"]:
        try:
            pmx = json.load(open(os.path.join(gaia.supplement_dir(d), "catalog.json"))).get("pm_xmatch", {})
        except (OSError, ValueError):
            pass
    print(f"  high-RUWE supplement         " + (f"ok, G <= {ss['gmax']:g}, {ss['gb']:.1f} GB" + (
          f"; 2-param stars with pm: {pmx['ucac5'] + pmx['ucac4']} of {pmx['two_param']} (UCAC5 {pmx['ucac5']}, "
          f"UCAC4 {pmx['ucac4']})" if pmx else "; 2-param stars without pm (setup --supplement adds them)")
          if ss["complete"] else
          f"incomplete {ss['done']}/{ss['total']} (pysyzygos setup --supplement resumes)" if ss["total"] else
          "not built (optional: pysyzygos setup --supplement)"))
    _list_catalogs(d)


def _list_catalogs(d):
    found = gaia.find_catalogs(".")
    if len(found) > 1 or (found and found[0][0] != d):
        print("  catalogs found (choose with gaia_local_dir, or PYSYZYGOS_CATALOG=<folder> for one run):")
        for f, g, ok, gb in found:
            v = starcat.data_version(f) if ok else ""
            print(f"    {f:18s} G <= {g:g}, {gb:.1f} GB" + ("" if ok else ", INCOMPLETE")
                  + (", old format" if v == "1" else f", data version {v}" if v else "")
                  + (f" (update: {starcat.update_available(f)})" if v and v != "1" and starcat.update_available(f)
                     else "") + ("   <- in use" if f == d else ""))


def supplement_step(d, gmax, want, sup_gmax, workers, ask, source="auto"):
    """3b. The high-RUWE supplement of catalog d: with --supplement, or offered on a first-time setup in a terminal,
    from Zenodo (G 16, ~0.35 GB, minutes; source auto/zenodo) or built from ESA's files (source esa, other limits, or
    to resume a partial ESA build); else only mentioned."""
    sd = gaia.supplement_dir(d)
    st = gaia.status(sd)
    if st["complete"]:
        print(f"3b. high-RUWE supplement: complete ({st['gb']:.1f} GB)")
        supplement_pm_step(d)
        return
    partial = st["total"] and st["done"]
    if not want and ask:
        zen = source in ("auto", "zenodo") and float(sup_gmax) in gaia.ZENODO_SUPPLEMENT and not partial
        how = ("resume the build from ESA's files" if partial else
               f"G <= {sup_gmax:g}: ~8 M stars, 0.4 GB, " + ("a 0.35 GB download from Zenodo" if zen
                                                             else "about 2 h from ESA's files"))
        k = input(f"3b. high-RUWE supplement: the stars the catalog leaves out (Gaia RUWE >= 1.4, often unresolved "
                  f"doubles, and 2-parameter sources); OWC predicts events on them, PySyzygos flags them.\n"
                  f"   {how}; [Enter] install it (recommended), or [s]kip: ").strip().lower()
        want = k != "s"
    if not want:
        print(f"3b. high-RUWE supplement: {'incomplete ' + str(st['done']) + '/' + str(st['total']) if partial else 'not built'}"
              f" (optional: pysyzygos setup --supplement)")
        return
    zen = source in ("auto", "zenodo") and float(sup_gmax) in gaia.ZENODO_SUPPLEMENT and not partial
    print(f"3b. high-RUWE supplement G <= {sup_gmax:g} in {sd}" + (" (resuming)" if partial else "")
          + (" from Zenodo" if zen else " from ESA's files"))
    try:
        if zen:
            gaia.fetch_zenodo(d, sup_gmax, supplement=True)
        else:
            gaia.build(d, sup_gmax, workers, supplement=True)
    except (OSError, RuntimeError, ValueError, KeyError) as e:
        print(f"   supplement not finished: {str(e)[:200]}\n   rerun: pysyzygos setup --supplement (it resumes)")
        return
    if gaia.status(sd)["complete"]:
        supplement_pm_step(d)
        gaia.BrightIndex(sd, min(index_limit(d), sup_gmax))
        print("   ok: used by picks, searches and pre-screens (GUI header '+ high-RUWE stars', config gaia_supplement)")


def supplement_pm_step(d):
    """Proper motions for the supplement's 2-parameter stars (UCAC5, then UCAC4; Gaia has none for them), once."""
    if gaia.has_supplement_pm(d):
        return
    print("3c. proper motions for the supplement's 2-parameter stars (UCAC5 / UCAC4 via CDS XMatch, a few minutes)")
    try:
        gaia.supplement_pm(d)
    except (OSError, RuntimeError, ValueError) as e:
        print(f"   not done ({str(e)[:200]}): their events stay flagged 'NO proper motion'; rerun setup later")


def index_limit(d):
    """Bright-star index limit for the pick tool: whole magnitudes >= 15, but never past the catalog's own limit."""
    lim = gaia.index_gmax(getattr(config, "pick_cam_limit", 15.0))
    try:
        import json
        lim = min(lim, json.load(open(os.path.join(d, "catalog.json")))["gmax"])
    except (OSError, ValueError, KeyError):
        pass
    return float(lim)


ZENODO_GB = {16.0: 3.2}                             # download size of core + quality, for the question only


def catalog_source(source, d, gmax, st):
    """'zenodo' or 'esa' for a new catalog d (status st) to G <= gmax; source is the --source option. Zenodo has the
    ready-made G <= 16; every other limit is a local build from ESA's files."""
    ready = float(gmax) in starcat.ZENODO_STEM
    if source == "zenodo" and not ready:
        sys.exit(f"   Zenodo has the catalog for G <= 16 only, not {gmax:g}: use --source esa")
    if source != "auto":
        return source
    if not ready:
        print(f"   G <= {gmax:g}: built from ESA's files (753 GB streamed, about 2 h)")
        return "esa"
    if st["done"]:
        print(f"   resuming the ESA build ({st['done']}/{st['total']} files done); --source zenodo downloads instead")
        return "esa"
    if not sys.stdin.isatty():
        return "zenodo"
    k = input(f"   [Enter] download the ready-made catalog (Zenodo or a mirror, the faster; ~{ZENODO_GB[16.0]:g} GB), or [b]uild it from "
              f"ESA's files (753 GB streamed, about 2 h): ").strip().lower()
    return "esa" if k.startswith("b") else "zenodo"


def ask_gmax(default):
    """Ask for the catalog's magnitude limit (terminal only). Returns a float G."""
    print("   Faintest star (Gaia G) kept in the local catalog; fainter stars are never searched:")
    print(f"     16   2.4-4.8 GB on disk; ready-made on Zenodo; enough for most telescopes")
    print("     other limits (e.g. 17, 18 for large apertures) are built here from ESA's files (753 GB streamed, about "
          "2 h; G <= 18: ~300 M stars, 9-18 GB)")
    while True:
        k = input(f"   limit [Enter = {default:g}]: ").strip()
        try:
            g = float(k) if k else default
        except ValueError:
            continue
        if 6.0 <= g <= 21.0:
            return g
        print("   a Gaia G between 6 and 21, please")


def catalog_target(gmax_arg, dir_arg):
    """(folder, gmax) for the Gaia build: --gmax / --dir, else the config. One folder holds one limit: a folder named
    gaia_dr3_g<N> is used only for G <= N, any other limit goes to its own gaia_dr3_g<gmax> (unless --dir)."""
    import re
    cfg_dir = getattr(config, "gaia_local_dir", None) or "gaia_dr3_g16"
    cfg_gmax = float(getattr(config, "gaia_local_gmax", 16.0))
    gmax = cfg_gmax if gmax_arg is None else float(gmax_arg)
    m = re.fullmatch(r"gaia_dr3_g(\d+(?:\.\d+)?)", os.path.basename(os.path.normpath(cfg_dir)))
    fits = float(m.group(1)) == gmax if m else gmax == cfg_gmax
    d = dir_arg or (cfg_dir if fits else f"gaia_dr3_g{gmax:g}")
    return d, gmax


def network_failure(e, d, source):
    """Message for a failed catalog step (no traceback): what failed, the likely cause, how to go on."""
    other = {"zenodo": "--source esa (build from ESA's files)", "esa": "--source zenodo (ready-made, G <= 16 or 18)"}
    if isinstance(e, PermissionError):                       # not the network: a file in use (Windows) or no write access
        return (f"\n   catalog step failed: {type(e).__name__}: {str(e)[:400]}\n"
                f"   Likely: a file in {d} is in use (the GUI or another PySyzygos run with this catalog, a virus "
                f"scanner) or not writable. Close other PySyzygos windows, delete leftover tmp*.tmp files in {d}, "
                f"then rerun setup (it resumes).")
    return (f"\n   catalog step failed: {type(e).__name__}: {str(e)[:300]}\n"
            f"   Likely: offline, the server is down, or a proxy/firewall blocks the address (see urls.py).\n"
            f"   - behind a proxy: export https_proxy=http://<proxy>:<port>  (and HTTPS_PROXY), then rerun\n"
            f"   - rerun later: setup resumes, files already in {d} are kept\n"
            + (f"   - or try the other source: pysyzygos setup {other[source]}\n" if source in other else "")
            + "   - or copy a finished catalog folder from another computer (gaia_dr3_g16 / gaia_dr3_g18)")


# ----------------------------------------------------------------------------------------------- star catalog
GROUP_GB = {"core": 2.4, "quality": 1.6, "extras": 0.8}       # G <= 16 on disk (starcat.py)


def parse_groups(text):
    """--groups text -> list of optional parts ('none'/'core': none, 'all': every one)."""
    t = (text or "").strip().lower()
    if t in ("", "none", "core"):
        return []
    if t == "all":
        return list(starcat.GROUPS)
    out = [g.strip() for g in t.split(",") if g.strip()]
    bad = [g for g in out if g not in starcat.GROUPS]
    if bad:
        sys.exit(f"--groups: unknown part(s) {', '.join(bad)}; choose from {', '.join(starcat.GROUPS)}, all or none")
    return out


def ask_groups(build=False):
    """The optional parts of a new catalog (terminal question). Returns a list."""
    q, e = GROUP_GB["quality"], GROUP_GB["extras"]
    print("   The catalog's parts (sizes for G <= 16):")
    print(f"     core      {GROUP_GB['core']:g} GB  {starcat.GROUP_TEXT['core']}")
    print(f"     quality   {q:g} GB  {starcat.GROUP_TEXT['quality']}")
    print(f"     extras    {e:g} GB  {starcat.GROUP_TEXT['extras']}")
    print("   Parts can be removed later (System tab, pysyzygos catalog remove) and, for the ready-made catalog, added "
          "later." + (" For a build from ESA's files they can only be added by a new build." if build else ""))
    k = input(f"   [Enter] core + quality ({GROUP_GB['core'] + q:.1f} GB, recommended), [m]inimal core only, "
              f"[a]ll ({sum(GROUP_GB.values()):.1f} GB): ").strip().lower()
    return [] if k.startswith("m") else list(starcat.GROUPS) if k.startswith("a") else ["quality"]


def install_catalog(d, gmax, groups, source, workers, keep_archive):
    """A new format-2 catalog in d: the ready-made one from Zenodo (G <= 16) or a build from ESA's files (any limit;
    then the proper motions of its 2-parameter stars from UCAC5/UCAC4). Returns the source used."""
    if starcat.is_format2(d):                                     # finished earlier (e.g. an upgrade's <folder>.new)
        print(f"   {d}: complete")
        return None
    src = catalog_source(source, d, gmax, starcat.status(d))
    if src == "zenodo":
        starcat.fetch(d, gmax, groups, keep_archive)
    else:
        st = starcat.build(d, gmax, workers, groups=groups)
        if st["complete"] and not st.get("pm_xmatch"):
            print("   proper motions for the 2-parameter stars (UCAC5 / UCAC4 via CDS XMatch, a few minutes)")
            try:
                starcat.xmatch(d)
            except (OSError, RuntimeError, ValueError) as e:
                print(f"   not done ({str(e)[:200]}): their events stay flagged 'NO proper motion'; later: "
                      f"pysyzygos catalog xmatch --dir {d}")
    return src


def catalog_step(a):
    """Step 2: the star catalog. Format 2 (starcat.py) for new installs; an old-format catalog is kept unless it is
    upgraded (--upgrade-catalog, or asked in a terminal): the new one is installed next to it and swapped in.
    Returns (folder, new_install)."""
    tty = sys.stdin.isatty()
    d, gmax = catalog_target(a.gmax, a.dir)
    st = gaia.status(d)
    groups = None if a.groups is None else parse_groups(a.groups)
    src = None
    try:
        if starcat.is_format2(d):
            print(f"2. star catalog G <= {st['gmax']:g} in {d}: complete, data version {starcat.data_version(d)} "
                  f"({', '.join(st['groups'])}; {st['gb']:.1f} GB)")
            newer = starcat.update_available(d)
            if newer and (a.update_catalog or (tty and input(
                    f"   data version {newer} is published ({starcat.DATA_TEXT.get(newer, '')}): [u]pdate now, or "
                    f"[Enter] later: ").strip().lower().startswith("u"))):
                old = starcat.update(d, a.keep_archive)
                print(f"   ok: {d} is now data version {starcat.data_version(d)}; the previous one is in {old}")
                if a.delete_old or (tty and input(f"   delete {old}? [Enter] yes, [k]eep: ").strip().lower() != "k"):
                    shutil.rmtree(old)
                    print(f"   deleted {old}")
                st = gaia.status(d)
            elif newer:
                print(f"   data version {newer} is published: pysyzygos setup --update-catalog (or the System tab)")
            for g in [g for g in (groups or []) if g not in st["groups"]]:
                starcat.add_group(d, g, a.keep_archive)
            for g in [g for g in st["groups"][1:] if groups is not None and g not in groups]:
                starcat.remove_group(d, g)
                print(f"   removed: {g}")
            return d, SITES_CREATED
        if st["complete"]:                                         # the old format (before 1.3.0)
            print(f"2. local Gaia catalog G <= {st['gmax']:g} in {d}: the old format (before 1.3.0)")
            up = a.upgrade_catalog
            if not up and tty:
                gm = st["gmax"]
                how = (f"the ready-made G <= {gm:g} from Zenodo" if float(gm) in starcat.ZENODO_STEM else
                       "a build from ESA's files (753 GB streamed, ~2 h)")
                k = input(f"   The new catalog: one sort order for every lookup, the high-RUWE and 2-parameter stars "
                          f"included, Gaia's errors and flags offline;\n   {how}, installed next to the old one and "
                          f"swapped in.\n   [u]pgrade now, or [Enter] keep the old one for now: ").strip().lower()
                up = k.startswith("u")
            if up:
                gmax = float(st["gmax"]) if a.gmax is None else gmax
                new = starcat.staging_dir(d)
                print(f"   new catalog G <= {gmax:g} in {new}, then swapped in")
                if groups is None:
                    groups = ask_groups(build=float(gmax) not in starcat.ZENODO_STEM) if tty else ["quality"]
                src = install_catalog(new, gmax, groups, a.source, a.workers, a.keep_archive)
                if not starcat.is_format2(new):
                    sys.exit(f"\n   the new catalog in {new} is not complete yet: rerun setup --upgrade-catalog "
                             f"to resume (nothing is lost)")
                ready = src is None                                      # a finished .new: only swapped in
                old = starcat.swap_in(d)
                for g in starcat.groups_present(d)[1:]:                  # parts not chosen (a .new built with all)
                    if g not in groups and not ready:                    # (a finished one keeps its parts: an
                                                                         # xref part took hours to build)
                        starcat.remove_group(d, g)
                        print(f"   removed the part not chosen: {g}")
                gb = sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(old) for f in fs) / 1e9
                print(f"   ok: the new catalog is in {d}; the old one moved to {old} ({gb:.1f} GB)")
                if a.delete_old or (tty and input(f"   delete {old}? [Enter] yes, [k]eep: ").strip().lower() != "k"):
                    shutil.rmtree(old)
                    print(f"   deleted {old}")
                else:
                    print(f"   delete it when it is no longer needed (or: pysyzygos cleanup lists it)")
                return d, SITES_CREATED
            print("   kept (upgrade later: pysyzygos setup --upgrade-catalog, or the System tab)")
            print("3. bright-star index")
            gaia.BrightIndex(d, index_limit(d))
            print("   ok")
            supplement_step(d, gmax, a.supplement, min(a.supplement_gmax, gmax), a.workers,
                            ask=tty and SITES_CREATED, source=a.source)
            return d, SITES_CREATED
        # a new catalog (or the rest of an interrupted build)
        if st["total"] and not os.path.isfile(os.path.join(d, "build.json")):
            sys.exit(f"   {d} holds a half-built catalog of the old format: delete that folder and rerun setup")
        if a.gmax is None and tty and not st["total"]:
            print("2. star catalog")
            d, gmax = catalog_target(ask_gmax(gmax if float(gmax) in starcat.ZENODO_STEM else 16.0), a.dir)
        else:
            print(f"2. star catalog G <= {gmax:g} in {d}" + (" (resuming the build)" if st["total"] else ""))
        if groups is None:
            groups = ask_groups(build=float(gmax) not in starcat.ZENODO_STEM) if tty and not st["total"] else ["quality"]
        src = install_catalog(d, gmax, groups, a.source, a.workers, a.keep_archive)
        if not starcat.is_format2(d):
            sys.exit(f"\n   catalog {d} is not complete yet: rerun setup to resume (nothing is lost)")
        print(f"   ok: {', '.join(starcat.status(d)['groups'])}")
    except (OSError, RuntimeError, ValueError, KeyError) as e:      # network (requests' errors are OSErrors), disk
        sys.exit(network_failure(e, d, src))
    if d != getattr(config, "gaia_local_dir", None) or gmax != float(getattr(config, "gaia_local_gmax", 16.0)):
        print(f"\n   To search with this catalog, set in pysyzygos_config.py:\n"
              f"       gaia_local_dir = \"{d}\"\n       gaia_local_gmax = {gmax:g}")
    return d, True


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=f"PySyzygos {__version__}")
    ap.add_argument("--no-gaia", action="store_true", help="kernels only")
    ap.add_argument("--status", action="store_true", help="only show what is installed")
    ap.add_argument("--no-geoip", action="store_true", help="do not guess the site from the IP address")
    ap.add_argument("--workers", type=int, default=6, help="parallel Gaia downloads")
    ap.add_argument("--gmax", type=float, help="faintest Gaia G kept in the local catalog (default: config "
                                               "gaia_local_gmax, 16); a new limit needs its own folder")
    ap.add_argument("--dir", help="catalog folder (default: config gaia_local_dir, or gaia_dr3_g<gmax> for another --gmax)")
    ap.add_argument("--source", choices=["auto", "zenodo", "esa"], default="auto",
                    help="catalog from Zenodo (ready-made, G <= 16 or 18) or built from ESA's files; auto asks")
    ap.add_argument("--keep-archive", action="store_true", help="keep the downloaded Zenodo .tar.xz")
    ap.add_argument("--planet-kernels", action="store_true",
                    help="download NAIF's satellite kernels for planets and moons (Jupiter: jup365.bsp, 1.1 GB) for "
                         "offline use; otherwise their positions come from JPL Horizons per search")
    ap.add_argument("--groups", help="optional parts of the star catalog: quality, extras (comma-separated), all or "
                                      "none (default: asked; without a terminal: quality); on an installed catalog "
                                      "adds or removes parts to match")
    ap.add_argument("--upgrade-catalog", action="store_true",
                    help="replace an old-format catalog (before 1.3.0) by the new one: installed next to it "
                         "(<folder>.new), then swapped in; the old one goes to <folder>.old")
    ap.add_argument("--update-catalog", action="store_true",
                    help="bring an installed new-format catalog (G <= 16, ready-made) to the newest published data "
                         "version (e.g. 2.0 -> 2.1: the epoch proper motions and the star names): the parts that "
                         "changed are downloaded into <folder>.new, then swapped in")
    ap.add_argument("--delete-old", action="store_true",
                    help="with --upgrade-catalog / --update-catalog: delete the old catalog once the new one is complete and swapped in "
                         "(otherwise asked in a terminal, kept without one)")
    ap.add_argument("--supplement", action="store_true",
                    help="also install the catalog's high-RUWE supplement: the stars the catalog leaves out (Gaia "
                         "RUWE >= 1.4, 2-parameter), flagged in the results; ~8 M stars to G 16: 0.35 GB from Zenodo "
                         "(--source esa: built from ESA's files, ~2 h), then proper motions for its 2-parameter stars "
                         "from UCAC5/UCAC4 (a few minutes)")
    ap.add_argument("--supplement-gmax", type=float, default=16.0,
                    help="faintest G of the supplement (default 16, at most the catalog's limit)")
    ap.add_argument("--historic-earth", action="store_true",
                    help="also download NAIF's historic Earth orientation file (earth_1962_*_combined.bpc, ~31 MB) "
                         "for search windows before 2000 (earth_latest_high_prec.bpc starts 2000-01-01); a search "
                         "before 2000 fetches it by itself when online")
    ap.add_argument("--home", metavar="FOLDER", help="use FOLDER as the data folder from now on (saved as a setting; "
                                                     "files are not moved)")
    ap.add_argument("--geoid", action="store_true",
                    help="look up each site's geoid height (EGM96) and save it in sites.py (geoid_m); sites.py's "
                         "elevations are above sea level, the computation adds it (comments in sites.py are not kept)")
    a = ap.parse_args()
    if a.geoid:
        from pysyzygos import sitesfile
        sites, default = sitesfile.load_sites()
        sitesfile.save_sites(sites, default, by="pysyzygos setup --geoid")
        for name, s in sites.items():
            ref = "height above the ellipsoid" if s.get("ele_ref") == "ellipsoid" else "geoid"
            print(f"  {name:28s} ele {s['ele']:g} m, {ref} {s['geoid_m']:+.1f} m -> {s['ele'] + s['geoid_m']:.1f} m above WGS84")
        print("saved sites.py")
        sys.exit(0)
    if a.status:
        show_status(catalog_target(a.gmax, a.dir)[0] if (a.gmax is not None or a.dir) else None)
        sys.exit(0)
    print("1. SPICE kernels")
    if not download_kernels(config.earth_pck_max_age):
        sys.exit("kernel download failed (see above); rerun setup when the address is reachable, or copy the kernel "
                 "files (*.tls, *.bsp, *.tpc, *.bpc) from another computer into this folder")
    if a.historic_earth:
        from pysyzygos import kernels as KK
        h = KK.historic_earth_pck(".") or KK.download_historic_earth_pck(".")
        print(f"   historic Earth orientation: {h or 'not available (offline?), rerun later'}")
    d, new_install = None, False
    if not a.no_gaia:
        d, new_install = catalog_step(a)
    planet_kernels(a.planet_kernels, ask=sys.stdin.isatty() and new_install)
    print()
    show_status(d)
    if not a.no_gaia:
        print("\n  Another catalog later: pysyzygos setup --gmax 18   (any limit other than 16 is built from ESA's "
              "files, about 2 h);\n  it goes into its own folder gaia_dr3_g<limit>, and the GUI's catalog selector "
              "lists it.")


if __name__ == "__main__":
    sys.exit(main())
