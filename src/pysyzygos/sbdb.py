"""sbdb.py - shared on-disk cache of per-asteroid SBDB physical data (diameter, extent, H, G, albedo, name).

One JSON file, <cache_path>/PySyzygos_sbdb_phys.json, keyed by asteroid number:
    {"19": {"fetched": unix time, "source": "sbdb.api" | "sbdb_query", "phys": {name: {"value", "sigma", "ref"}, ...,
                                                                               "_fullname": "19 Fortuna (A852 QA)"}}}
Written by search.py (per-object SBDB API, all fields with references) and by pick.py (from its bulk
download: diameter, diameter sigma, extent, albedo, H, G, name; no references). pysyzygos.get_asteroid_size() derives the
size from it, the same way for either source. The raw data is cached, not the derived size, so SIZE_OVERRIDES and the
size rules always apply. Entries older than sbdb_max_age_days (config, default 30) are refetched.

Standard library only (the pick tool must not need SPICE/astropy).
"""
from pysyzygos.version import __version__
from pysyzygos import net                      # https with certifi's certificate authorities
import json, os, shutil, tempfile, time

FILE = "PySyzygos_sbdb_phys.json"
BULK_FIELDS = ["diameter", "diameter_sigma", "extent", "albedo", "H", "G"]     # needed in the pick tool's bulk query


def _config(name, default):
    try:
        from pysyzygos import config
        return getattr(config, name, default)
    except ImportError:
        return default


def cache_file(cache_path=None):
    return os.path.join(cache_path or _config("cache_path", tempfile.gettempdir()), FILE)


def max_age_s(max_age_days=None):
    return float(_config("sbdb_max_age_days", 30) if max_age_days is None else max_age_days) * 86400.0


def load(cache_path=None):
    path = cache_file(cache_path)
    if not os.path.isfile(path):                              # the cache emptied (e.g. /dev/shm after a restart):
        _restore_from_offline(path)                           # the offline copy, if there is one
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _restore_from_offline(path):
    """Copy the offline copy of the size data (offline.PHYS) into the empty cache; entries keep their dates, so stale
    ones are fetched again as usual. Never raises."""
    try:
        from pysyzygos import offline
        if os.path.isfile(offline.PHYS):
            fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
            os.close(fd)
            shutil.copyfile(offline.PHYS, tmp)
            os.replace(tmp, path)
    except Exception:
        pass


def get(number, cache_path=None, max_age_days=None):
    """(entry, fresh) for one asteroid; entry is None if not cached."""
    e = load(cache_path).get(str(number).strip())
    return e, bool(e) and time.time() - e.get("fetched", 0) < max_age_s(max_age_days)


def put(entries, cache_path=None, keep_newer=True):
    """Merge {number: entry} into the cache file (atomic). keep_newer: an existing entry fetched later is kept, so a
    bulk import never replaces a newer per-object lookup."""
    path = cache_file(cache_path)
    cache = load(cache_path)                                  # re-read: keep entries written meanwhile
    n_new = 0
    for k, e in entries.items():
        old = cache.get(str(k))
        if keep_newer and old and old.get("fetched", 0) > e.get("fetched", 0):
            continue
        cache[str(k)] = e
        n_new += 1
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(cache, f)
    os.replace(tmp, path)
    try:                                                      # a copy for use without network (offline.py), if on
        from pysyzygos import offline
        if offline.enabled():
            shutil.copyfile(path, offline.PHYS + ".tmp")
            os.replace(offline.PHYS + ".tmp", offline.PHYS)
    except OSError:
        pass
    return n_new


def entry_from_api(js, fetched=None):
    """Cache entry from one sbdb.api reply (with phys-par=1)."""
    phys = {q["name"]: q for q in js.get("phys_par", [])}
    phys["_fullname"] = js.get("object", {}).get("fullname")
    o = js.get("orbit") or {}
    if o.get("orbit_id"):                                         # the orbit solution (as OWC's "Orbit Date")
        phys["orbit"] = dict(name="orbit", value=f"JPL#{o['orbit_id']} of {str(o.get('soln_date', ''))[:10]}",
                             ref=f"condition code U {o.get('condition_code', '?')}, {o.get('n_obs_used', '?')} observations "
                                 f"{o.get('first_obs', '?')} to {o.get('last_obs', '?')}")
    return dict(fetched=fetched or time.time(), source="sbdb.api", phys=phys)


def get_full(number, cache_path=None, timeout=15):
    """Entry with all of SBDB's physical data for one asteroid (rotation period, pole, extent, taxonomic type, ...
    with references): the cached one if it came from the per-object API, else fetched now and cached. The pick tool's
    bulk rows hold only the size fields. Falls back to the cached entry (or None) if SBDB cannot be reached."""
    import urllib.parse, urllib.request
    from pysyzygos import urls as U
    n = str(number).strip()
    if not n.isdigit():                                           # a planet or moon (bodies.py): not in SBDB
        return None
    e, fresh = get(n, cache_path)
    if e and fresh and e.get("source") == "sbdb.api" and "orbit" in (e.get("phys") or {}):
        return e
    try:
        url = U.URL_JPL_SBDB_API + "?" + urllib.parse.urlencode({"sstr": n, "phys-par": 1})
        with net.urlopen(url, timeout=timeout) as r:
            js = json.load(r)
    except (OSError, ValueError):
        return e
    if "object" not in js:
        return e
    new = entry_from_api(js)
    put({n: new}, cache_path, keep_newer=False)
    return new


def entry_from_bulk(row, fetched):
    """Cache entry from one sbdb_query row (dict field -> value), in the same layout as entry_from_api."""
    phys = {}
    for name in ("diameter", "extent", "albedo", "H", "G"):
        v = row.get(name)
        if v not in (None, ""):
            phys[name] = dict(name=name, value=str(v), sigma=None, ref="SBDB bulk query")
    if "diameter" in phys and row.get("diameter_sigma") not in (None, ""):
        phys["diameter"]["sigma"] = str(row["diameter_sigma"])
    phys["_fullname"] = (row.get("full_name") or "").strip() or None
    return dict(fetched=fetched, source="sbdb_query", phys=phys)
