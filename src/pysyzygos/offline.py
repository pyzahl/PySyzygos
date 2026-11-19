"""offline.py - copies of downloaded orbit data, for picks and searches without network.

The pick's asteroid list (JPL SBDB, all elements) and the asteroid orbit files of searches (JPL Horizons SPK) are cached
in config.cache_path, which is /dev/shm (in memory, lost when the computer restarts) where it exists. When switched on,
every download is also copied here, <data folder>/offline/ (the list compressed: 103 MB -> 34 MB for H < 17), and
without network the pick and the search fall back to these copies, saying how old they are. Plan online, observe
offline: a search window run once online can be run again offline.

    pysyzygos offline on | off       # switch the copies on / off (off keeps the copies; remove deletes them)
    pysyzygos offline copy           # copy what is in the cache now
    pysyzygos offline status | remove

Switched on by the file offline/enabled (so the GUI's System tab and command-line runs agree).
"""
from pysyzygos.version import __version__
import glob, gzip, json, os, re, shutil, sys, tempfile, time

DIR = "offline"                                             # relative to the data folder (every command runs there)
MARK = os.path.join(DIR, "enabled")
SBDB = os.path.join(DIR, "sbdb_list.json.gz")
SPK_DIR = os.path.join(DIR, "orbits")
PHYS = os.path.join(DIR, "sbdb_phys.json")                  # the per-asteroid size cache (sbdb.py), copied
_list = None                                                 # the copied asteroid list, once loaded
SPK_RE = re.compile(r"PySyzygos_asteroid_(.+)_(\d{4}-\d\d-\d\d)_(\d{4}-\d\d-\d\d)\.bsp$")


def use_dir(folder):
    """Put the copies in another folder (tests: never the data folder's real copies)."""
    global DIR, MARK, SBDB, SPK_DIR, PHYS, _list
    DIR = folder
    MARK, SBDB = os.path.join(DIR, "enabled"), os.path.join(DIR, "sbdb_list.json.gz")
    SPK_DIR, PHYS, _list = os.path.join(DIR, "orbits"), os.path.join(DIR, "sbdb_phys.json"), None


def enabled():
    return os.path.isfile(MARK)


def set_enabled(on):
    if on:
        os.makedirs(DIR, exist_ok=True)
        open(MARK, "w").close()
    elif os.path.isfile(MARK):
        os.remove(MARK)


def keep_sbdb(blob):
    """Compressed copy of the pick's asteroid list (the cache's JSON blob), when switched on. Never raises."""
    if not enabled():
        return False
    try:
        fd, tmp = tempfile.mkstemp(prefix="pysyzygos-", dir=DIR, suffix=".tmp")
        with gzip.open(os.fdopen(fd, "wb"), "wt", compresslevel=6) as f:
            json.dump(blob, f)
        os.replace(tmp, SBDB)
        return True
    except OSError as e:
        print(f"(offline copy of the asteroid list failed: {e})", file=sys.stderr)
        return False


def sbdb_fallback(want_hmax):
    """The copied asteroid list (blob) if it covers H < want_hmax (inf: all numbered), else None."""
    try:
        with gzip.open(SBDB, "rt") as f:
            blob = json.load(f)
    except (OSError, ValueError):
        return None
    return blob if blob.get("hmax", 0) >= want_hmax else None


def keep_spk(path):
    """Copy of an asteroid orbit file (Horizons SPK), when switched on. Never raises."""
    if not enabled():
        return False
    try:
        os.makedirs(SPK_DIR, exist_ok=True)
        dest = os.path.join(SPK_DIR, os.path.basename(path))
        shutil.copyfile(path, dest + ".tmp")
        os.replace(dest + ".tmp", dest)
        return True
    except OSError as e:
        print(f"(offline copy of {os.path.basename(path)} failed: {e})", file=sys.stderr)
        return False


def spk_fallback(target_id, start, stop, folders=()):
    """An orbit file of this asteroid whose time span covers start..stop (ISO dates), from the offline copies and the
    given folders (e.g. the cache); the newest file first. Path or None."""
    hits = []
    for d in (SPK_DIR,) + tuple(folders):
        for f in glob.glob(os.path.join(d, f"PySyzygos_asteroid_{target_id}_*.bsp")):
            m = SPK_RE.search(os.path.basename(f))
            if m and m[1] == str(target_id) and m[2] <= start and stop <= m[3]:
                hits.append((os.path.getmtime(f), f))
    return max(hits)[1] if hits else None


def phys_fallback(number):
    """Size data (an sbdb.py cache entry) for one asteroid without network: from the copied size cache, else from the
    copied asteroid list (diameter, albedo, H, G of every asteroid there). None if neither has it."""
    global _list
    n = str(number).strip()
    try:
        with open(PHYS) as f:
            e = json.load(f).get(n)
        if e:
            return e
    except (OSError, ValueError):
        pass
    if _list is None:
        try:
            with gzip.open(SBDB, "rt") as f:
                b = json.load(f)
            i_name = b["fields"].index("full_name")
            _list = (b["fields"], {(r[i_name] or "").split()[0]: r for r in b["data"] if r[i_name]}, b.get("fetched"))
        except (OSError, ValueError, KeyError):
            _list = (None, {}, None)
    fields, rows, fetched = _list
    r = rows.get(n)
    if not r:
        return None
    from pysyzygos import sbdb
    return sbdb.entry_from_bulk(dict(zip(fields, r)), fetched or 0)


def status():
    """dict: enabled, the list (size, date, H limit, count), the orbit files (count, size)."""
    out = dict(enabled=enabled(), sbdb=None, orbits=0, orbits_mb=0.0)
    if os.path.isfile(SBDB):
        try:
            with gzip.open(SBDB, "rt") as f:
                b = json.load(f)
            out["sbdb"] = dict(mb=os.path.getsize(SBDB) / 1e6, fetched=b.get("fetched"), hmax=b.get("hmax"),
                               count=len(b.get("data", [])))
        except (OSError, ValueError):
            out["sbdb"] = dict(mb=os.path.getsize(SBDB) / 1e6, fetched=None, hmax=None, count=None)
    files = glob.glob(os.path.join(SPK_DIR, "*.bsp"))
    out["orbits"], out["orbits_mb"] = len(files), sum(os.path.getsize(f) for f in files) / 1e6
    return out


def status_text(st=None):
    st = st or status()
    lines = [f"offline copies: {'on' if st['enabled'] else 'off'} ({os.path.abspath(DIR)})"]
    s = st["sbdb"]
    if s:
        when = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(s["fetched"])) if s.get("fetched") else "?"
        lim = "all numbered" if s.get("hmax") in (None, float("inf")) or (s.get("hmax") or 0) > 99 else f"H < {s['hmax']:g}"
        lines.append(f"  asteroid list: {s.get('count') or '?'} asteroids ({lim}), from {when}, {s['mb']:.0f} MB")
    else:
        lines.append("  asteroid list: no copy")
    lines.append(f"  orbit files: {st['orbits']} ({st['orbits_mb']:.1f} MB)")
    return "\n".join(lines)


def copy_now(cache_path):
    """Copy what is in the cache now (the asteroid list and the orbit files). Returns (list copied, n orbit files)."""
    set_enabled(True)
    ok = False
    lst = os.path.join(cache_path, "PySyzygos_sbdb_cache.json")
    if os.path.isfile(lst):
        try:
            with open(lst) as f:
                ok = keep_sbdb(json.load(f))
        except (OSError, ValueError):
            ok = False
    n = sum(keep_spk(f) for f in glob.glob(os.path.join(cache_path, "PySyzygos_asteroid_*.bsp")))
    phys = os.path.join(cache_path, "PySyzygos_sbdb_phys.json")
    if os.path.isfile(phys):
        shutil.copyfile(phys, PHYS + ".tmp")
        os.replace(PHYS + ".tmp", PHYS)
    return ok, n


def remove():
    shutil.rmtree(DIR, ignore_errors=True)


def main(argv=None):
    a = sys.argv[1:] if argv is None else argv
    cmd = a[0] if a else "status"
    if cmd == "on":
        set_enabled(True)
    elif cmd == "off":
        set_enabled(False)
    elif cmd == "copy":
        from pysyzygos import config
        ok, n = copy_now(config.cache_path)
        print(f"copied: asteroid list {'yes' if ok else 'no (none in the cache)'}, {n} orbit files")
    elif cmd == "remove":
        remove()
    elif cmd != "status":
        sys.exit(__doc__)
    print(status_text())


if __name__ == "__main__":
    main()
