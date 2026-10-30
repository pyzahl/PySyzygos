"""cleanup.py - remove what PySyzygos downloaded and generated, for a fresh start (e.g. to test an install), keeping the
large local Gaia catalogs (their star files, as from Zenodo or a build).

    pysyzygos cleanup                    list what would be deleted, with sizes (nothing is deleted)
    pysyzygos cleanup --yes              delete it
    pysyzygos cleanup --keep-results     ... but keep the run outputs (results database, picks, pre-screens, maps, ...)
    pysyzygos cleanup --orbits           only the cached orbit files (the next search downloads them again)
    pysyzygos cleanup --cache            only the caches (orbit files, the asteroid list, size data, exports)
    pysyzygos cleanup --all --yes        also your settings: sites.py, pysyzygos_config.py, csv_exports.py, GUI state,
                                        favorites, and the data-folder setting of `pysyzygos setup --home`: a start like
                                        a first install (setup asks for your site again; without --all it keeps it)

Deleted (in the data folder, see `pysyzygos setup --status`):
  downloads      SPICE kernels, NAIF planet kernels, the MPC observatory list, old caches
  caches         PySyzygos's own files in cache_path (asteroid and body SPKs, SBDB caches, CSV exports) - nothing else there
  catalog extras in every gaia_dr3_* folder: the bright-star indexes and the high-RUWE supplement (setup restores
                 both: rebuilt in a minute, the supplement downloaded from Zenodo in minutes); the star files are kept;
                 a whole gaia_dr3_*.old folder (the catalog before an upgrade to the new format)
  run outputs    results database, logs, reports, maps, picks, pre-screens, targets.py, OWC-check outputs, backups
Never deleted: owc_refs/, owc_reference.*, private-docs/, release/, run.sh, .venv, the program, git, the catalogs'
star files. Afterwards `pysyzygos setup` sets everything up again (with --all it asks for your site again).
"""
from pysyzygos.version import __version__
import argparse, glob, os, shutil, sys, tempfile

KERNEL_FILES = ("naif*.tls", ".lsk_checked", "de440.bsp", "pck00010.tpc", "earth_latest_high_prec.bpc")
NAIF_FILES = ("jup365.bsp", "sat441.bsp", "nep097.bsp", "plu060.bsp", "mar099.bsp")   # bodies.NAIF_KERNELS
DOWNLOADS = KERNEL_FILES + NAIF_FILES + ("earth_1962_*_combined.bpc", "data/ObsCodes.html", "jpl_asteroids_spice.csv",
                                         "sbdb_cache.json", "owc_cache.json", "weather_cache.json",
                                         "occult_data")                     # occultdata.py add-on
CACHE_PATTERNS = ("PySyzygos_asteroid_*.bsp", "PySyzygos_body_*.bsp", "PySyzygos_sbdb_cache.json",
                  "PySyzygos_sbdb_phys.json", "pysyzygos_exports",
                  "PyOccult_asteroid_*.bsp", "PyOccult_body_*.bsp", "PyOccult_sbdb_cache.json",   # names before 1.0.0
                  "PyOccult_sbdb_phys.json", "pyoccult_exports")
ORBIT_PATTERNS = ("PySyzygos_asteroid_*.bsp", "PySyzygos_body_*.bsp", "PyOccult_asteroid_*.bsp", "PyOccult_body_*.bsp")
OUTPUTS = ("pysyzygos.db", "pysyzygos.db-wal", "pysyzygos.db-shm", "owc_check.db", "owc_check.db-wal", "owc_check.db-shm",
           "hits_log.csv", "hits_report.html", "hits_report.md", "bodies_log.csv", "bodies_report.html",
           "earth_log.csv", "earth_log.runs.jsonl", "earth_report.html", "observed_report.html", "obs_checks",
           "owc_check_hits.csv", "pick_events.csv", "pick_candidates.csv", "targets.py", "maps", "picks", "prescreen", "logs",
           "build", "*.runs.jsonl", "*.log", "*~", "#*#", ".#*", "*.tmp",
           "pyoccult.db", "pyoccult.db-wal", "pyoccult.db-shm")                   # name before 1.0.0
SETTINGS = ("sites.py", "pysyzygos_config.py", "csv_exports.py", "gui_state.json", "server_auth.json", "favorites", "offline", "horizons",
            "pyoccult_config.py", "pyoccult_config.py.pre-1.0")                    # names before 1.0.0
LIST_MAX = 25                       # items listed per category (the rest summed up)
NEVER = {"owc_refs", "owc_reference.txt", "owc_reference.csv", "private-docs", "release", "run.sh", ".venv", ".git",
         "src", "tests", "pyproject.toml", "uv.lock"}


def cache_path():
    """cache_path of the user's config (only read if there is one: loading the config would create it), else the
    default (/dev/shm, or the system temp folder)."""
    if (os.path.isfile("pysyzygos_config.py") or os.path.isfile("pyoccult_config.py")) and os.path.isfile("sites.py"):
        try:
            from pysyzygos import config as C
            return C.cache_path
        except Exception:
            pass
    return "/dev/shm" if os.path.isdir("/dev/shm") else tempfile.gettempdir()


def _size(p):
    if os.path.islink(p) or os.path.isfile(p):
        return os.lstat(p).st_size
    total = 0
    for root, _, files in os.walk(p):
        for f in files:
            fp = os.path.join(root, f)
            if not os.path.islink(fp):
                total += os.path.getsize(fp)
    return total


def _inside(p, root):
    rp, rr = os.path.realpath(p), os.path.realpath(root)
    return rp == rr or rp.startswith(rr + os.sep)


def plan(keep_results=False, everything=False):
    """[(category, path)] to delete, in the current folder (the data folder) and cache_path."""
    home = os.getcwd()
    out = []

    def add(cat, pattern, root=home):
        for p in sorted(glob.glob(os.path.join(root, pattern))):
            name = os.path.relpath(p, home).split(os.sep)[0] if root == home else ""
            if root == home and (name in NEVER or not _inside(p, home)):
                continue
            out.append((cat, p))

    for f in DOWNLOADS:
        add("downloads", f)
    cp = cache_path()
    if os.path.isdir(cp) and os.path.realpath(cp) != os.path.realpath(home):
        for pat in CACHE_PATTERNS:
            add("caches", pat, cp)
    for d in sorted(glob.glob(os.path.join(home, "gaia_dr3_*"))):
        if os.path.isdir(d) and d.endswith(".unpack"):               # an interrupted Zenodo unpack
            out.append(("catalog extras", d))
            continue
        if os.path.isdir(d) and d.endswith(".old"):                  # the catalog before an upgrade (starcat.swap_in)
            out.append(("catalog extras", d))
            continue
        if not os.path.isfile(os.path.join(d, "catalog.json")):
            continue
        for pat in ("bright_*", "supplement", "*.tmp", "*.csv.gz.tmp"):
            add("catalog extras", os.path.join(os.path.basename(d), pat))
    if not keep_results:
        for f in OUTPUTS:
            add("run outputs", f)
    if everything:
        for f in SETTINGS:
            add("your settings", f)
        from pysyzygos import home as H
        for p in (H.POINTER, H.LEGACY_POINTER):
            if os.path.isfile(p):
                out.append(("your settings", p))
    seen, uniq = set(), []
    for c, p in out:
        if p not in seen:
            seen.add(p)
            uniq.append((c, p))
    return uniq


def _gb(n):
    return f"{n / 1e9:.2f} GB" if n >= 1e8 else f"{n / 1e6:.1f} MB" if n >= 1e5 else f"{n / 1e3:.0f} kB"


def empty_cache(cp=None, orbits_only=False):
    """Delete PySyzygos's own files in cache_path right away (the GUI's System tab, --orbits / --cache): the orbit
    files only, or all its caches. Offline copies (offline/) are kept. Returns (files, bytes)."""
    cp = cp or cache_path()
    n = size = 0
    for pat in ORBIT_PATTERNS if orbits_only else CACHE_PATTERNS:
        for p in glob.glob(os.path.join(cp, pat)):
            try:
                size += _size(p)
                shutil.rmtree(p) if os.path.isdir(p) and not os.path.islink(p) else os.remove(p)
                n += 1
            except OSError as e:
                print(f"not deleted: {p} ({e})", file=sys.stderr)
    return n, size


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=f"PySyzygos {__version__}")
    ap.add_argument("--yes", action="store_true", help="really delete (without it: only list)")
    ap.add_argument("--keep-results", action="store_true", help="keep the run outputs (results, picks, pre-screens, maps)")
    ap.add_argument("--all", dest="everything", action="store_true",
                    help="also your settings (sites.py, pysyzygos_config.py, favorites, ...) and the data-folder setting")
    ap.add_argument("--orbits", action="store_true", help="only delete the cached orbit files (no --yes needed)")
    ap.add_argument("--cache", action="store_true", help="only delete the caches in cache_path (no --yes needed)")
    a = ap.parse_args(argv)
    if a.orbits or a.cache:
        n, size = empty_cache(orbits_only=a.orbits)
        print(f"{cache_path()}: deleted {n} {'orbit files' if a.orbits else 'cache files'} ({_gb(size)})")
        return 0
    items = plan(a.keep_results, a.everything)
    print(f"data folder: {os.getcwd()}")
    if not items:
        mine = [f for f in SETTINGS if os.path.exists(f)]
        print("nothing to clean" + (f"; your settings stay ({', '.join(mine)}): --all removes them too"
                                     if mine and not a.everything else ""))
        return 0
    sizes = {p: _size(p) for _, p in items}
    by_cat = {}
    for c, p in items:
        by_cat.setdefault(c, []).append(p)
    for c, ps in by_cat.items():
        print(f"\n{c} ({_gb(sum(sizes[p] for p in ps))}):")
        if c == "caches":                                           # many small files: one line per kind
            for pat in CACHE_PATTERNS:
                m = [p for p in ps if glob.fnmatch.fnmatch(os.path.basename(p), pat)]
                if m:
                    print(f"  {os.path.join(os.path.dirname(m[0]), pat)}  {len(m)} file(s), {_gb(sum(sizes[p] for p in m))}")
            continue
        for p in ps[:LIST_MAX]:
            shown = os.path.relpath(p) if _inside(p, os.getcwd()) else p
            print(f"  {shown}{'/' if os.path.isdir(p) and not os.path.islink(p) else ''}  {_gb(sizes[p])}")
        if len(ps) > LIST_MAX:
            print(f"  ... and {len(ps) - LIST_MAX} more ({_gb(sum(sizes[p] for p in ps[LIST_MAX:]))})")
    total = sum(sizes.values())
    kept = [d for d in sorted(glob.glob("gaia_dr3_*")) if os.path.isfile(os.path.join(d, "catalog.json"))]
    print(f"\ntotal {_gb(total)} in {len(items)} items; kept: " + (", ".join(f"{d}/ (star files)" for d in kept) or "-")
          + ", owc_refs/, private-docs/, release/, .venv")
    mine = [f for f in SETTINGS if os.path.exists(f)]
    settings_note = ""
    if not a.everything and mine:
        settings_note = (f"Your settings stay ({', '.join(mine)}): setup keeps your site. For a start like a first "
                         f"install (setup asks for the site again), use: pysyzygos cleanup --all --yes")
        print(settings_note)
    if not a.yes:
        print("nothing deleted (a dry run): add --yes to delete. Close the GUI and any runs first.")
        return 0
    failed = 0
    for _, p in items:
        try:
            if os.path.isdir(p) and not os.path.islink(p):
                shutil.rmtree(p)
            else:
                os.remove(p)
        except OSError as e:
            failed += 1
            print(f"  could not delete {p}: {e}")
    print(f"deleted {len(items) - failed} items ({_gb(total)})." + (f" {failed} failed." if failed else "")
          + " Run `pysyzygos setup` to set PySyzygos up again." + (f"\n{settings_note}" if settings_note else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
