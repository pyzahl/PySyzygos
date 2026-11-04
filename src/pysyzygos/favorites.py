"""favorites.py - a hand-picked list of events from any search and any site, kept with everything known.

    pysyzygos.db (data folder), table favorites  the list (one entry per event, newest first; db.py; an older
                                                favorites/favorites.json is imported once and kept as .migrated)
    favorites/favorites.csv                     the same as a flat table (rewritten with every change; for sharing)
    favorites/<target>_<YYYYMMDDTHHMM>/          the event's own copies of its KML ground track and preview SVG
    favorites/lists/<name>/                     saved favorites lists (list.json + files/<key>/ copies; save_list)
    favorites/glance.html                       all favorites' paths on one map (write_glance)

An entry holds the full hits_log record, the site and the run context of the search it came from, when it was added,
a status (planned / observed / cancelled / clouded) and a note. Map and preview are copies, so later searches (which
overwrite or delete files in maps/) never change a favorite. Private (site names): favorites/ is in .gitignore.
Used by gui.py (report star buttons, Favorites tab). Standard library only.

    pysyzygos favorites list
"""
from pysyzygos.version import __version__
from pysyzygos import urls as U
from pysyzygos.sbdb import is_designation
import glob, json, math, os, re, shutil, sys, tempfile
from datetime import datetime, timezone

DIR = "favorites"
STATUSES = ("planned", "observed", "cancelled", "clouded")


def key_of(target_id, best_utc):
    """<target>_<YYYYMMDDTHHMM>, the same stem as the files in maps/."""
    from pysyzygos.report import file_id                          # P:Jupiter -> P-Jupiter (a folder name)
    return f"{file_id(target_id)}_{str(best_utc).strip()[:16].replace(':', '').replace('-', '')}"


def _path(folder):
    return os.path.join(folder, "favorites.json")


def _db(folder):
    """The results database next to the favorites folder (the data folder's pysyzygos.db); imports an older
    favorites.json once."""
    from pysyzygos import db
    con = db.connect(os.path.join(os.path.dirname(os.path.abspath(folder)), db.DEFAULT))
    db.favorites_import(con, _path(folder))
    return con


def load(folder=DIR):
    from pysyzygos import db
    con = _db(folder)
    try:
        return db.favorites_load(con)
    finally:
        con.close()


def _save(items, folder):
    from pysyzygos import db
    os.makedirs(folder, exist_ok=True)
    con = _db(folder)
    try:
        db.favorites_save(con, items)
    finally:
        con.close()
    write_csv(items, folder)


PHYS_KEYS = ("H", "G", "diameter", "diameter_sigma", "extent", "albedo", "rot_per", "pole", "spec_T", "spec_B", "orbit")


def phys_of(entry):
    """{name: (value, ref)} of the size-cache entry (sbdb) kept with a favorite, for H, G, diameter, ..."""
    out = {}
    for k in PHYS_KEYS:
        v = ((entry or {}).get("phys") or {}).get(k)
        if v and v.get("value") not in (None, ""):
            out[k] = (v["value"], v.get("ref") or "")
    return out


def write_csv(items=None, folder=DIR):
    """favorites/favorites.csv: one row per favorite (status, note, added, site, the search record, size data)."""
    import csv
    items = load(folder) if items is None else items
    rec_cols = []
    for e in items:
        rec_cols += [k for k in e["record"] if k not in rec_cols]
    cols = (["key", "status", "note", "added", "site", "site_lat", "site_lon", "site_ele"] + rec_cols
            + [f"sbdb_{k}" for k in PHYS_KEYS] + ["kml", "preview_svg", "globe_svg"])
    fd, tmp = tempfile.mkstemp(dir=folder, suffix=".tmp")
    with os.fdopen(fd, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for e in items:
            site, files, ph = e.get("site") or {}, e.get("files") or {}, e.get("phys") or {}
            row = dict(key=e["key"], status=e.get("status", ""), note=e.get("note", ""), added=e.get("added", ""),
                       site=site.get("name", ""), site_lat=site.get("lat", ""), site_lon=site.get("lon", ""),
                       site_ele=site.get("ele", ""), kml=files.get("kml", ""), preview_svg=files.get("svg", ""),
                       globe_svg=files.get("globe", ""))
            row.update({k: v for k, v in e["record"].items() if k in rec_cols})
            row.update({f"sbdb_{k}": (ph.get(k) or ["", ""])[0] for k in PHYS_KEYS})
            w.writerow(row)
    os.replace(tmp, os.path.join(folder, "favorites.csv"))


def keys(folder=DIR):
    return [e["key"] for e in load(folder)]


def pm_text(r):
    """'-4.00, -13.00 ± 1.70 mas/yr (UCAC5)' (pmRA·cosDec, pmDec) from the record; older records: the source alone
    (from star_kind), or "Gaia DR3"."""
    from pysyzygos.gaia_local import pm_source
    src = (r.get("star_pm_source") or "").strip() or pm_source(r.get("star_kind") or 0) or "Gaia DR3"
    def num(k):
        try:
            v = float(r.get(k))
            return v if v == v else None
        except (TypeError, ValueError):
            return None
    a, d, e = num("star_pmra"), num("star_pmdec"), num("star_pm_err")
    if src == "none":
        return "none (2-parameter star: its 2016.0 position is used)"
    if a is None or d is None:
        return src
    return f"{a:+.2f}, {d:+.2f}" + (f" \u00b1 {e:.2f}" if e is not None and e > 0 else "") + f" mas/yr ({src})"


def alts_text(r):
    """The star's other proper-motion estimates (search: pmcheck) and the spread they give at the event."""
    try:
        sk = float(r.get("star_pm_spread_km"))
        spread = f" \u2192 path spread \u00b1{sk:.0f} km (1 sigma)" if sk == sk else ""
    except (TypeError, ValueError):
        spread = ""
    return (r.get("star_pm_alts") or "").strip() + spread


def edited(folder=DIR):
    """Keys of the favorites changed from their defaults (a note, or a status other than "planned"): removing those
    from the results page asks first."""
    return [e["key"] for e in load(folder) if str(e.get("note") or "").strip() or
            (e.get("status") or STATUSES[0]) != STATUSES[0]]


def add(record, run=None, map_dir="maps", folder=DIR, sbdb=None, key_suffix="", status="planned", note=""):
    """Add an event (record: a hits_log row as a dict; run: the run summary of its search, or None; sbdb: the
    asteroid's size-cache entry from sbdb, kept with the favorite). Copies its KML and preview from map_dir.
    key_suffix: appended to the key (several sites of one event, e.g. the observers of an archive event: '_<name>').
    Returns (ok, message)."""
    try:
        base = key_of(record["target_id"], record["best_utc"])
    except KeyError as ex:
        return False, f"not an event record (no {ex})"
    key = base + key_suffix
    items = load(folder)
    if any(e["key"] == key for e in items):
        return False, f"{key} is already a favorite"
    own = os.path.join(folder, key)
    os.makedirs(own, exist_ok=True)
    files = {}
    for ext, pat in (("kml", "*.kml"), ("svg", "*.svg"), ("globe", "*_globe.svg")):
        found = sorted(glob.glob(os.path.join(glob.escape(map_dir), f"{glob.escape(base)}{pat}")))
        if ext == "svg":
            found = [f for f in found if not f.endswith("_globe.svg")]    # the preview, not the globe plot
        if found:
            dst = os.path.join(own, os.path.basename(found[0]))
            shutil.copyfile(found[0], dst)
            files[ext] = os.path.relpath(dst, folder).replace(os.sep, "/")
    run = run or {}
    entry = dict(key=key, added=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"), version=__version__,
                 status=status if status in STATUSES else STATUSES[0], note=note,
                 record=record, site=run.get("site"), files=files,
                 phys=phys_of(sbdb), phys_src=(sbdb or {}).get("source", ""),
                 run={k: run.get(k) for k in ("run_utc", "window_start", "window_days", "limits", "earth_pck",
                                               "targets_from") if k in run})
    items.insert(0, entry)
    _save(items, folder)
    name = (record.get("target_name") or record["target_id"]).strip()
    return True, f"added to favorites: {name}, {str(record['best_utc'])[:19]} UT" + (
        "" if files else " (no map or preview found to copy)")


def set_field(key, name, value, folder=DIR):
    """Store one extra field in a favorite (e.g. 'vizier': the double-star check). Returns True if found."""
    items = load(folder)
    for e in items:
        if e["key"] == key:
            e[name] = value
            _save(items, folder)
            return True
    return False


def update(key, folder=DIR, **fields):
    """Set status and/or note of a favorite. Returns (ok, message)."""
    items = load(folder)
    for e in items:
        if e["key"] == key:
            if "status" in fields and fields["status"] not in STATUSES:
                return False, f"status must be one of {', '.join(STATUSES)}"
            e.update({k: v for k, v in fields.items() if k in ("status", "note")})
            _save(items, folder)
            return True, f"{key} saved"
    return False, f"{key} is not a favorite"


def remove(key, folder=DIR):
    """Drop a favorite and its copied files. Returns (ok, message)."""
    items = load(folder)
    rest = [e for e in items if e["key"] != key]
    if len(rest) == len(items):
        return False, f"{key} is not a favorite"
    _save(rest, folder)
    shutil.rmtree(os.path.join(folder, key), ignore_errors=True)
    return True, f"{key} removed"


def update_many(keys_, folder=DIR, **fields):
    """Set status and/or note of several favorites. Returns (ok, message)."""
    if "status" in fields and fields["status"] not in STATUSES:
        return False, f"status must be one of {', '.join(STATUSES)}"
    items, want, n = load(folder), set(keys_), 0
    for e in items:
        if e["key"] in want:
            e.update({k: v for k, v in fields.items() if k in ("status", "note")})
            n += 1
    if n:
        _save(items, folder)
    return n > 0, f"{n} favorite{'s' if n != 1 else ''} updated" if n else "none of these is a favorite"


def remove_many(keys_, folder=DIR):
    """Drop several favorites and their copied files. Returns (ok, message)."""
    items, want = load(folder), set(keys_)
    rest = [e for e in items if e["key"] not in want]
    n = len(items) - len(rest)
    if n:
        _save(rest, folder)
        for k in want:
            shutil.rmtree(os.path.join(folder, k), ignore_errors=True)
    return n > 0, f"{n} favorite{'s' if n != 1 else ''} removed" if n else "none of these is a favorite"


def cleanup(before=None, folder=DIR):
    """Remove every favorite whose event is before `before` (ISO date, default: today UTC). Returns (ok, message)."""
    day = before or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    old = [e["key"] for e in load(folder) if str(e["record"].get("best_utc", ""))[:10] < day]
    if not old:
        return True, f"no favorites before {day}"
    ok, msg = remove_many(old, folder)
    return ok, f"{msg} (events before {day})"


def write_page(folder=DIR, tiles=None):
    """favorites/favorites.html: the favorites as a report table (as the Results page, plus select box, site, status,
    note, added) with the same tools, using each favorite's own map and preview copies. Returns the path."""
    from pysyzygos import report as R
    events, paths, sites = [], {}, set()
    for f in load(folder):
        r, site = f["record"], f.get("site") or {}
        own = os.path.join(folder, f["key"])
        try:
            e = R.build_event(r, site.get("lat"), site.get("lon"), own, folder)
        except (KeyError, ValueError):
            continue
        e.update(fav=dict(key=f["key"], status=f.get("status", ""), note=f.get("note", ""), added=f.get("added", "")),
                 site=site)
        if e["kml_abs"]:
            try:
                paths[f["key"]] = R.kml_to_data(e["kml_abs"])
                e["pkey"] = f["key"]
            except Exception:
                pass
        sites.add(site.get("name", "?"))
        events.append(e)
    events.sort(key=lambda e: e["when"])
    span = (f" from {min(e['when'] for e in events):%Y-%m-%d} to {max(e['when'] for e in events):%Y-%m-%d}"
            if events else "")
    meta = dict(title="PySyzygos favorites", span=span, sort="date", info=None,
                observer=f"{len(sites)} site{'s' if len(sites) != 1 else ''}: {', '.join(sorted(sites))}" if sites
                else "no favorites yet: add events with the star button in the Results report",
                generated=datetime.now().strftime("%Y-%m-%d %H:%M"), paths=paths, tiles=tiles or U.URL_OSM_TILES,
                obs=None, site=None,
                favorites=True, statuses=STATUSES)
    os.makedirs(folder, exist_ok=True)
    out = os.path.join(folder, "favorites.html")
    fd, tmp = tempfile.mkstemp(dir=folder, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(R.to_html(events, meta))
    os.replace(tmp, out)
    return out


# ------------------------------------------------------------------------------------------- saved lists
# A saved list is a snapshot of the favorites: list.json (name, saved, entries) and copies of each favorite's own
# folder (KML, preview, globe, path verification without its search run and orbit files). Loading one replaces the
# current favorites (or adds to them); the favorites before the last load are kept as the list PREVIOUS.
LISTS = "lists"
PREVIOUS = "before last load"
LIST_SKIP = ("run", "*.bsp", "*.tmp")                             # not copied into a list (re-made on demand)


def list_slug(name):
    """A list's folder name from its name ('favorites 2026-11-02' -> 'favorites_2026-11-02')."""
    return re.sub(r"[^A-Za-z0-9._-]+", "_", str(name).strip()).strip("._") or "list"


def default_list_name(items):
    """'favorites <date of the last added entry>' (today if none)."""
    day = max((str(e.get("added") or "")[:10] for e in items), default="") or \
        datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return f"favorites {day}"


def _events_span(items):
    days = sorted(str(e["record"].get("best_utc", ""))[:10] for e in items)
    return f"{days[0]} to {days[-1]}" if days else ""


def save_list(name=None, folder=DIR, overwrite=False):
    """Save the current favorites under a name (default: default_list_name). Returns (ok, message)."""
    items = load(folder)
    if not items:
        return False, "no favorites to save"
    name = (name or "").strip() or default_list_name(items)
    d = os.path.join(folder, LISTS, list_slug(name))
    if os.path.exists(d) and not overwrite:
        return False, f"a list named “{name}” exists"
    tmp = d + ".tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(os.path.join(tmp, "files"))
    for e in items:
        src = os.path.join(folder, e["key"])
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(tmp, "files", e["key"]), ignore=shutil.ignore_patterns(*LIST_SKIP))
    meta = dict(name=name, saved=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"), version=__version__,
                n=len(items), span=_events_span(items), entries=items)
    with open(os.path.join(tmp, "list.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f)
    shutil.rmtree(d, ignore_errors=True)
    os.replace(tmp, d)
    return True, f"saved {len(items)} favorite{'s' if len(items) != 1 else ''} as “{name}”"


def lists(folder=DIR):
    """The saved lists, newest first: [dict(name, slug, saved, n, span)]."""
    out = []
    for p in glob.glob(os.path.join(glob.escape(os.path.join(folder, LISTS)), "*", "list.json")):
        try:
            with open(p, encoding="utf-8") as f:
                m = json.load(f)
        except (OSError, ValueError):
            continue
        out.append(dict(name=m.get("name", ""), slug=os.path.basename(os.path.dirname(p)), saved=m.get("saved", ""),
                        n=m.get("n", len(m.get("entries", []))), span=m.get("span", "")))
    return sorted(out, key=lambda m: m["saved"], reverse=True)


def load_list(slug, folder=DIR, mode="replace"):
    """Make a saved list the current favorites (mode 'replace') or add its entries not yet there ('add'). The
    favorites before are saved as the list PREVIOUS first. Returns (ok, message)."""
    d = os.path.join(folder, LISTS, list_slug(slug))
    try:
        with open(os.path.join(d, "list.json"), encoding="utf-8") as f:
            m = json.load(f)
    except (OSError, ValueError):
        return False, f"no saved list “{slug}”"
    src = os.path.join(d, "files")
    if list_slug(slug) == list_slug(PREVIOUS):                    # saving PREVIOUS below would overwrite it
        keep = tempfile.mkdtemp(dir=folder)
        shutil.copytree(src, os.path.join(keep, "files"), dirs_exist_ok=True)
        src = os.path.join(keep, "files")
    else:
        keep = None
    try:
        items = load(folder)
        if items:
            save_list(PREVIOUS, folder, overwrite=True)
        new = list(m.get("entries", []))
        if mode == "add":
            have = {e["key"] for e in items}
            added = [e for e in new if e["key"] not in have]
            new = items + added
        else:
            gone = {e["key"] for e in items} - {e["key"] for e in new}
            for k in gone:
                shutil.rmtree(os.path.join(folder, k), ignore_errors=True)
            added = new
        for e in added:
            s = os.path.join(src, e["key"])
            if os.path.isdir(s):
                shutil.copytree(s, os.path.join(folder, e["key"]), dirs_exist_ok=True)
        _save(new, folder)
    finally:
        if keep:
            shutil.rmtree(keep, ignore_errors=True)
    name = m.get("name") or slug
    if mode == "add":
        return True, f"added {len(added)} favorite{'s' if len(added) != 1 else ''} from “{name}”"
    return True, (f"loaded “{name}” ({len(new)} favorites)"
                  + (f"; the {len(items)} before are saved as “{PREVIOUS}”" if items else ""))


OBSERVED_LIST = "observed"


def add_to_list(name, entries, folder=DIR):
    """Put favorites into a saved list (created if missing): an entry with the same key is replaced by the newer one,
    their folders copied. Returns the number of entries in the list after."""
    d = os.path.join(folder, LISTS, list_slug(name))
    try:
        with open(os.path.join(d, "list.json"), encoding="utf-8") as f:
            m = json.load(f)
    except (OSError, ValueError):
        m = dict(name=name, entries=[])
    new = {e["key"] for e in entries}
    items = list(entries) + [e for e in m.get("entries", []) if e["key"] not in new]
    items.sort(key=lambda e: str(e["record"].get("best_utc", "")), reverse=True)
    os.makedirs(os.path.join(d, "files"), exist_ok=True)
    for e in entries:
        src = os.path.join(folder, e["key"])
        if os.path.isdir(src):
            dst = os.path.join(d, "files", e["key"])
            shutil.rmtree(dst, ignore_errors=True)
            shutil.copytree(src, dst, ignore=shutil.ignore_patterns(*LIST_SKIP))
    m.update(name=m.get("name") or name, saved=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
             version=__version__, n=len(items), span=_events_span(items), entries=items)
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(m, f)
    os.replace(tmp, os.path.join(d, "list.json"))
    return len(items)


def past_observed(folder=DIR, now=None):
    """Keys of the favorites with status 'observed' (any outcome) whose event is over."""
    now = now or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    return [e["key"] for e in load(folder) if e.get("status") == "observed"
            and str(e["record"].get("best_utc", ""))[:19] < now]


def archive_observed(folder=DIR, move=True, name=OBSERVED_LIST, now=None):
    """Put the past observed favorites (past_observed) into the saved list `name` (default 'observed'; added to
    what it holds) and, with move, remove them from the current favorites. Returns (ok, message)."""
    keys = set(past_observed(folder, now))
    if not keys:
        return False, "no past events marked observed"
    picked = [e for e in load(folder) if e["key"] in keys]
    n = add_to_list(name, picked, folder)
    msg = (f"{len(picked)} observed event{'s' if len(picked) != 1 else ''} "
           f"{'moved' if move else 'added'} to the list “{name}” ({n} in it)")
    if move:
        remove_many(keys, folder)
    return True, msg


def _same(a, b):
    key = lambda items: json.dumps(sorted(items, key=lambda e: e["key"]), sort_keys=True, default=str)
    return key(a) == key(b)


def saved_as(folder=DIR):
    """The name of a saved list (not PREVIOUS) that holds exactly the current favorites, else None: the current
    ones are new or changed since (status, note, added or removed events)."""
    items = load(folder)
    for p in glob.glob(os.path.join(glob.escape(os.path.join(folder, LISTS)), "*", "list.json")):
        if os.path.basename(os.path.dirname(p)) == list_slug(PREVIOUS):
            continue
        try:
            with open(p, encoding="utf-8") as f:
                m = json.load(f)
        except (OSError, ValueError):
            continue
        if _same(m.get("entries", []), items):
            return m.get("name") or os.path.basename(os.path.dirname(p))
    return None


def delete_list(slug, folder=DIR):
    d = os.path.join(folder, LISTS, list_slug(slug))
    if not os.path.isfile(os.path.join(d, "list.json")):
        return False, f"no saved list “{slug}”"
    shutil.rmtree(d)
    return True, f"list “{slug}” deleted"


# ------------------------------------------------------------------------------------------- all paths on one map
GLANCE_LINES = ("Centre", "Shadow limit", "1-sigma")              # the lines drawn (KML names start so)
GLANCE_COLORS = ("#2563eb", "#dc2626", "#16a34a", "#9333ea", "#ea580c", "#0891b2", "#db2777", "#65a30d", "#7c3aed",
                 "#b45309", "#0f766e", "#be123c")                 # one per event, repeating


def glance_data(folder=DIR, keys=None):
    """Paths of the favorites (those with event keys `keys` in that order, report.event_key; None: all, by time)
    for the map: [dict(key, title, status, color, lines, sites)]."""
    from pysyzygos import report as R
    items = load(folder)
    if keys is not None:
        by = {R.event_key(e["record"].get("target_id", ""), e["record"].get("best_utc", "")): e for e in items}
        items = [by[k] for k in keys if k in by]
    else:
        items = sorted(items, key=lambda e: str(e["record"].get("best_utc", "")))
    out = []
    for e in items:
        kml = (e.get("files") or {}).get("kml")
        if not kml or not os.path.isfile(os.path.join(folder, kml)):
            continue
        try:
            d = R.kml_to_data(os.path.join(folder, kml))
        except Exception:
            continue
        r, color = e["record"], GLANCE_COLORS[len(out) % len(GLANCE_COLORS)]
        tid = str(r.get("target_id", "")).strip()
        name = (r.get("target_name") or tid).strip() if ":" in tid else R.target_label(tid, r.get("target_name"))
        lines = [dict(name=ln["name"], pts=ln["pts"], kind=next(k for k in GLANCE_LINES if ln["name"].startswith(k)))
                 for ln in d["lines"] if ln["name"].startswith(GLANCE_LINES) and len(ln["pts"]) > 1]
        sites = [[p["lat"], p["lon"]] for p in d["pins"] if p["name"] == "Observer"]
        out.append(dict(key=e["key"], title=f"{name} · {str(r.get('best_utc', ''))[:16].replace('T', ' ')} UT",
                        status=e.get("status", ""), site=(e.get("site") or {}).get("name", ""), color=color,
                        lines=lines, sites=sites))
    return out


GLANCE_HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Favorites at a glance</title>
<link rel="stylesheet" href="__CSS__">
<style>
:root{--bg:#fff;--ink:#1e293b;--muted:#64748b;--line:#e2e8f0;--card:#f8fafc}
@media (prefers-color-scheme: dark){:root{--bg:#0f172a;--ink:#e2e8f0;--muted:#94a3b8;--line:#334155;--card:#1e293b}}
html,body{margin:0;height:100%;background:var(--bg);color:var(--ink);font:14px system-ui,sans-serif}
#wrap{display:flex;height:100%}#side{width:300px;flex:none;overflow:auto;border-right:1px solid var(--line);padding:10px}
#map{flex:1}h1{font-size:1.05rem;margin:0 0 4px}.sub{color:var(--muted);font-size:.8rem;margin:0 0 8px}
.ev{display:flex;gap:6px;align-items:flex-start;padding:4px 0;border-bottom:1px solid var(--line)}
.ev i{width:14px;height:4px;margin-top:8px;flex:none;border-radius:2px}.ev a{color:inherit;cursor:pointer;text-decoration:none}
.ev a:hover{text-decoration:underline}.ev small{display:block;color:var(--muted)}
button{font:inherit;font-size:.85rem;padding:2px 10px;margin:0 4px 8px 0;border:1px solid var(--line);border-radius:6px;
 background:var(--card);color:var(--ink);cursor:pointer}
.lbl{font-weight:600;font-size:11px;padding:1px 4px;border-width:2px}
@media (max-width:700px){#wrap{flex-direction:column}#side{width:auto;max-height:35vh;border-right:0;
 border-bottom:1px solid var(--line)}}
</style></head><body><div id="wrap"><div id="side"><h1>Favorites at a glance</h1>
<p class="sub">__SUB__</p><button id="all" type="button">Show all</button><button id="lab" type="button">Labels on/off</button>
<div id="list"></div><p class="sub">Thick: center line; thin: shadow limits; dotted: 1-sigma limits. Labels sit where
the path passes its site; where they would overlap, only the first shows (zoom in for more). Click a name to zoom to
it; untick to hide it.</p></div><div id="map"></div></div>
<script src="__JS__"></script>
<script id="glancedata" type="application/json">__DATA__</script>
<script>
(function(){var D=JSON.parse(document.getElementById('glancedata').textContent),box=document.getElementById('map');
if(!window.L){box.innerHTML='<p style="margin:14px">The map library could not be loaded (offline?).</p>';return;}
var map=L.map(box,{worldCopyJump:true}),all=L.featureGroup().addTo(map),labels=[],showLab=true;
L.tileLayer(__TILES__,{maxZoom:18,attribution:'&copy; OpenStreetMap contributors'}).addTo(map);
var W={'Centre':3,'Shadow limit':1.5,'1-sigma':1.2},DASH={'1-sigma':'2 5'},seen={};
function anchor(c,sites){if(!c)return null;if(!sites.length)return c[Math.floor(c.length/2)];var s=sites[0],b=null,bd=1e9;
 c.forEach(function(p){var d=Math.pow(p[0]-s[0],2)+Math.pow((p[1]-s[1])*Math.cos(s[0]*Math.PI/180),2);if(d<bd){bd=d;b=p;}});return b;}
D.forEach(function(ev){var g=L.featureGroup(),c=null;
 ev.lines.forEach(function(l){L.polyline(l.pts,{color:ev.color,weight:W[l.kind]||1.5,dashArray:DASH[l.kind]||null,
  opacity:l.kind==='Centre'?0.95:0.7}).bindTooltip(ev.title+' \\u00b7 '+l.name,{sticky:true}).addTo(g);
  if(!c&&l.kind==='Centre')c=l.pts;});
 ev.sites.forEach(function(s){var k=s.join(',');if(seen[k])return;seen[k]=1;
  L.circleMarker(s,{radius:6,color:'#fff',weight:2,fillColor:'#e11d48',fillOpacity:1}).bindTooltip(ev.site||'Site').addTo(all);});
 var a=anchor(c,ev.sites);if(a){var t=L.tooltip({permanent:true,direction:'right',className:'lbl'}).setLatLng(a)
  .setContent(ev.title);labels.push({t:t,g:g});t.addTo(g);
  t.on('add',function(){var el=t.getElement();if(el)el.style.borderColor=ev.color;});}
 g.addTo(all);ev.g=g;
 var row=document.createElement('div');row.className='ev';
 row.innerHTML='<input type="checkbox" checked><i style="background:'+ev.color+'"></i><div><a></a><small></small></div>';
 row.querySelector('a').textContent=ev.title;row.querySelector('small').textContent=[ev.site,ev.status].filter(Boolean).join(' \\u00b7 ');
 row.querySelector('input').addEventListener('change',function(e){if(e.target.checked)g.addTo(all);else all.removeLayer(g);});
 row.querySelector('a').addEventListener('click',function(){if(!all.hasLayer(g)){g.addTo(all);row.querySelector('input').checked=true;}
  map.fitBounds(g.getBounds(),{padding:[30,30]});});
 document.getElementById('list').appendChild(row);});
function declutter(){var kept=[];labels.forEach(function(x){var el=x.t.getElement();if(!el)return;
 el.style.visibility='';var r=el.getBoundingClientRect(),hit=kept.some(function(k){return r.left<k.right&&r.right>k.left&&
 r.top<k.bottom&&r.bottom>k.top;});if(hit)el.style.visibility='hidden';else kept.push(r);});}
map.on('zoomend moveend layeradd layerremove',function(){setTimeout(declutter,0);});
function fit(){if(all.getLayers().length)map.fitBounds(all.getBounds(),{padding:[20,20]});else map.setView([20,0],2);}
document.getElementById('all').addEventListener('click',function(){D.forEach(function(ev){ev.g.addTo(all);});
 document.querySelectorAll('#list input').forEach(function(i){i.checked=true;});fit();});
document.getElementById('lab').addEventListener('click',function(){showLab=!showLab;labels.forEach(function(x){
 if(showLab)x.t.addTo(x.g);else x.g.removeLayer(x.t);});});
fit();})();
</script></body></html>"""


def write_glance(folder=DIR, keys=None, tiles=None):
    """favorites/glance.html: the favorites' paths (center line, shadow and 1-sigma limits, from each favorite's KML
    copy) on one map, each labeled with target and date, in its own color; the sites as pins. keys: the event keys
    the favorites page shows (its filter and order), None = all. Returns (path, number of events drawn)."""
    data = glance_data(folder, keys)
    n_all = len(load(folder))
    sub = (f"{len(data)} of {n_all} favorites" + (" (as the table shows them)" if keys is not None else "")
           + f" · {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    page = (GLANCE_HTML.replace("__CSS__", U.URL_LEAFLET_CSS).replace("__JS__", U.URL_LEAFLET_JS)
            .replace("__TILES__", json.dumps(tiles or U.URL_OSM_TILES)).replace("__SUB__", sub)
            .replace("__DATA__", json.dumps(data, separators=(",", ":")).replace("</", "<\\/")))
    os.makedirs(folder, exist_ok=True)
    out = os.path.join(folder, "glance.html")
    fd, tmp = tempfile.mkstemp(dir=folder, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(page)
    os.replace(tmp, out)
    return out, len(data)


def backfill_phys(lookup, folder=DIR):
    """Give favorites SBDB's full physical data (size, and shape and rotation where known): lookup(target_id) ->
    size-cache entry or None (sbdb.get_full). Done once per favorite: 'phys_src' notes that the entry came
    from the per-object SBDB API (bulk rows of the pick tool hold only the size; offline, it is tried again next
    time). Saves (and rewrites the CSV) only if something changed. Returns the number updated."""
    items, n = load(folder), 0
    for e in items:
        tid = str(e["record"].get("target_id", "")).strip()
        if not (tid.isdigit() or is_designation(tid)) or (e.get("phys_src") == "sbdb.api" and "orbit" in (e.get("phys") or {})):
            continue                                              # (the orbit solution: added 0.14.x)
        entry = lookup(str(e["record"].get("target_id", "")).strip())
        if not entry:
            continue
        e["phys"] = {**(e.get("phys") or {}), **phys_of(entry)}
        e["phys_src"], n = entry.get("source", ""), n + 1
    if n:
        _save(items, folder)
    return n


def backfill_class(lookup, folder=DIR):
    """Give favorites added before records carried the JPL orbit class (search.asteroid_class, 2026-10-26) its fields
    ast_class / ast_class_name, for the report's class filter: lookup(target_id) -> size-cache entry or None
    (sbdb.get_full; its phys '_class'). Entries without it are tried again next time. Returns the number updated."""
    items, n = load(folder), 0
    for e in items:
        r = e["record"]
        tid = str(r.get("target_id", "")).strip()
        if str(r.get("ast_class") or "").strip() not in ("", "nan") or not (tid.isdigit() or is_designation(tid)):
            continue
        c = ((lookup(tid) or {}).get("phys") or {}).get("_class") or {}
        if c.get("value"):
            r["ast_class"], r["ast_class_name"], n = c["value"], c.get("title") or "", n + 1
    if n:
        _save(items, folder)
    return n


def backfill_doubles(check, folder=DIR):
    """Give favorites added before the close/double-star check (doubles.py) its fields: check(record) -> dict of
    fields, or None when it cannot be done now (no catalog). Done once per favorite (the record then has
    double_check). Returns the number updated."""
    items, n = load(folder), 0
    for e in items:
        r = e["record"]
        if str(r.get("double_check") or "") not in ("", "none", "nan"):
            continue
        f = check(r)
        if f:
            r.update({k: (None if isinstance(v, float) and v != v else v) for k, v in f.items()})   # NaN -> null
            n += 1
    if n:
        _save(items, folder)
    return n


def double_text(entry):
    """'companion G 17.4 at 2.8″: drop 3.31 mag with its light (local catalog)', 'none known (local catalog and
    Gaia online)', or '' when the favorite has not been checked."""
    r = entry["record"]
    src = str(r.get("double_check") or "")
    if src in ("", "none", "nan"):
        return ""
    where = {"local": "local catalog", "gaia online": "local catalog and Gaia online"}.get(src, src)
    hint = str(r.get("double_hint") or "")
    return f"{hint} ({where})" if hint and hint != "nan" else f"none known ({where})"


def backfill_names(lookup, folder=DIR):
    """Give favorites saved without them the star's other names (star_ucac4, star_tyc, star_hip; catalog part xref):
    lookup(record) -> dict of those fields, or None when it cannot be done now (no catalog with that part). Done once
    per favorite (the record then has star_ucac4, empty for a star without one). Returns the number updated."""
    items, n = load(folder), 0
    for e in items:
        r = e["record"]
        if "star_ucac4" in r or not str(r.get("star") or "").strip():
            continue
        f = lookup(r)
        if f is None:
            continue
        r.update({k: f.get(k, "") for k in ("star_ucac4", "star_tyc", "star_hip")})
        n += 1
    if n:
        _save(items, folder)
    return n


def backfill_globes(map_dir="maps", folder=DIR):
    """Give favorites added before globe plots existed the plot of a later search (<key>*_globe.svg in map_dir),
    copied into their own folder. Returns the number added."""
    items, n = load(folder), 0
    for e in items:
        files = e.setdefault("files", {})
        if "globe" in files:
            continue
        found = sorted(glob.glob(os.path.join(glob.escape(map_dir), f"{glob.escape(e['key'])}*_globe.svg")))
        if found:
            own = os.path.join(folder, e["key"])
            os.makedirs(own, exist_ok=True)
            dst = os.path.join(own, os.path.basename(found[0]))
            shutil.copyfile(found[0], dst)
            files["globe"], n = os.path.relpath(dst, folder).replace(os.sep, "/"), n + 1
    if n:
        _save(items, folder)
    return n


def backfill_timezones(lookup, folder=DIR):
    """Give each favorite's site its IANA time zone (for showing site times): lookup(lat, lon) -> name or None,
    called once per distinct site position. Saves only if something changed. Returns the number filled in."""
    items, n, cache = load(folder), 0, {}
    for e in items:
        site = e.get("site") or {}
        if site.get("tz") or site.get("lat") is None or site.get("lon") is None:
            continue
        key = (round(float(site["lat"]), 3), round(float(site["lon"]), 3))
        if key not in cache:
            cache[key] = lookup(site["lat"], site["lon"])
        if cache[key]:
            site["tz"], n = cache[key], n + 1
    if n:
        _save(items, folder)
    return n


EVENT_KEYS = ("dist_au", "motion_ra_ash", "motion_dec_ash", "sun_elong_deg", "m_combined", "shadow_from_utc",
              "shadow_to_utc")


def horizons_event(target_id, utc, timeout=30):
    """OWC-style event data for favorites saved before the search logged it (search.event_context): distance,
    motion, solar elongation and the 1-sigma error ellipse from one JPL Horizons observer query (geocentric) at the
    event minute; None if Horizons cannot be reached. Planets and moons (P:/M: targets) by their NAIF id."""
    import csv as _csv, io, urllib.parse
    from pysyzygos import net, bodies
    b = bodies.parse(target_id)
    cmd = str(b["naif"]) if b else f"{str(target_id).strip()};"
    t0 = str(utc)[:16].replace("T", " ")
    q = {"format": "json", "COMMAND": f"'{cmd}'", "EPHEM_TYPE": "OBSERVER", "CENTER": "'500@399'",
         "START_TIME": f"'{t0}'", "STOP_TIME": f"'{t0[:-2]}{int(t0[-2:]) + 1:02d}'" if not t0.endswith("59") else f"'{t0}:59'",
         "STEP_SIZE": "'1m'", "QUANTITIES": "'3,20,23,37'", "CSV_FORMAT": "YES", "OBJ_DATA": "NO"}
    try:
        with net.urlopen(U.URL_JPL_HORIZONS_API + "?" + urllib.parse.urlencode(q), timeout=timeout) as r:
            text = json.load(r).get("result", "")
        head = text[:text.index("$$SOE")].strip().splitlines()[-2]
        row = text[text.index("$$SOE") + 5:text.index("$$EOE")].strip().splitlines()[0]
        cols = [c.strip() for c in next(_csv.reader(io.StringIO(head)))]
        vals = [c.strip() for c in next(_csv.reader(io.StringIO(row)))]
        d = dict(zip(cols, vals))
        out = dict(dist_au=float(d["delta"]), motion_ra_ash=float(d["dRA*cosD"]), motion_dec_ash=float(d["d(DEC)/dt"]),
                   sun_elong_deg=float(d["S-O-T"]))
        try:                                                      # the 1-sigma error ellipse (small bodies only)
            out.update(ast_err_smaa_mas=float(d["SMAA_3sig"]) / 3 * 1000, ast_err_smia_mas=float(d["SMIA_3sig"]) / 3 * 1000,
                       ast_err_pa_deg=(90.0 - float(d["Theta"])) % 180.0)
        except (KeyError, ValueError):
            pass
        return out
    except (OSError, ValueError, KeyError, IndexError, StopIteration):
        return None


def backfill_event(lookup=horizons_event, folder=DIR):
    """Event data (EVENT_KEYS) for favorites whose record lacks it (saved before 0.14.x): lookup(target_id, utc) ->
    dict or None (offline: tried again next time); the combined magnitude from the record, From/To from the KML's
    first and last minute mark (approximate, marked with '~'). Returns the number updated."""
    import re
    items, n = load(folder), 0
    for e in items:
        r = e["record"]
        if str(r.get("dist_au") or "").strip():
            continue
        got = lookup(r.get("target_id", ""), r.get("best_utc", ""))
        if not got:
            continue
        r.update({k: str(v) for k, v in got.items()})
        try:
            m, ma = float(r.get("mag")), float(r.get("m_ast"))
            r["m_combined"] = str(-2.5 * math.log10(10 ** (-0.4 * m) + 10 ** (-0.4 * ma)))
        except (TypeError, ValueError):
            pass
        kml = (e.get("files") or {}).get("kml")
        if kml and os.path.isfile(os.path.join(folder, kml)):
            marks = re.findall(r"<name>(\d\d:\d\d) UTC</name>", open(os.path.join(folder, kml), encoding="utf-8").read())
            if marks:
                day = str(r.get("best_utc", ""))[:10]
                r["shadow_from_utc"], r["shadow_to_utc"] = f"~{day}T{marks[0]}", f"~{day}T{marks[-1]}"
        n += 1
    if n:
        _save(items, folder)
    return n


def backfill_errors(ast_lookup=horizons_event, star_lookup=None, folder=DIR):
    """The error ellipses for favorites saved without them: the target's from JPL Horizons (ast_lookup(target_id,
    utc) -> dict with ast_err_*), the star's from the Gaia archive for all (star_lookup(source_ids) ->
    {id: row} or None; default doubles.fetch_star_errors), carried to each event date. Marked 'err_checked' when
    both answered, so it runs once per favorite (offline: next time). Returns the number updated."""
    from pysyzygos import ellipses, doubles
    items = load(folder)
    todo = [e for e in items if not e.get("err_checked")]
    if not todo:
        return 0
    stars = (star_lookup or doubles.fetch_star_errors)([e["record"].get("star") for e in todo
                                                         if str(e["record"].get("star") or "").strip()])
    n = 0
    for e in todo:
        r, done = e["record"], True
        tid = str(r.get("target_id", ""))
        if ":" not in tid and not str(r.get("ast_err_smaa_mas") or "").strip():
            got = ast_lookup(tid, r.get("best_utc", ""))
            if got is None:
                done = False
            else:
                r.update({k: str(v) for k, v in got.items() if k.startswith("ast_err_")})
        if stars is None:
            done = False
        elif not str(r.get("star_err_smaa_mas") or "").strip():
            g = stars.get(int(r.get("star") or 0))
            years = 2000.0 + float(r.get("best_et") or 0) / (365.25 * 86400) - 2016.0
            se = ellipses.star_ellipse(g, years) if g else None
            if se:
                r.update(star_err_smaa_mas=str(se[0]), star_err_smia_mas=str(se[1]), star_err_pa_deg=str(se[2]))
        if done:
            e["err_checked"] = True
        n += 1 if done or any(str(r.get(k) or "").strip() for k in ("ast_err_smaa_mas", "star_err_smaa_mas")) else 0
    if n:
        _save(items, folder)
    return n


def error_svg(entry, size=300):
    """The favorite's sky-plane 1-sigma error ellipses (target, star, combined) as one SVG (ellipses.svg), with the
    error across the track in mas and km; without Gaia's errors for the star a typical star of its G (marked '!');
    the star where it stands as seen from the site, unless that is more than 2 shadow widths outside. None when
    neither ellipse is known."""
    from pysyzygos import ellipses
    r = entry["record"]
    trip = lambda p: tuple(_f(r.get(f"{p}_{k}")) for k in ("smaa_mas", "smia_mas", "pa_deg"))
    ast, star = trip("ast_err"), trip("star_err")
    ast, star = (ast if None not in ast else None), (star if None not in star else None)
    missing, star_note = {}, ""
    if not star:                                                  # no Gaia errors: a typical star of this G, marked
        g, et = _f(r.get("mag")), _f(r.get("best_et"))
        if g is not None and et is not None:
            star = ellipses.typical_star(g, 2000.0 + et / (365.25 * 86400) - 2016.0)
            star_note = f"typical for G {g:.1f} ({'no Gaia errors' if entry.get('err_checked') else 'Gaia: none yet'})"
        else:
            missing["Star"] = "no Gaia errors"
    if not ast and not star:
        return None
    mra, mde, dist = _f(r.get("motion_ra_ash")), _f(r.get("motion_dec_ash")), _f(r.get("dist_au"))
    note = ""
    if mra is not None and mde is not None:
        c = ellipses.add(*[ellipses.cov(*e) for e in (ast, star) if e])
        x = ellipses.across_track(c, mra, mde)
        if x is not None:
            note = f"across track (dashed: motion): 1σ {x:.1f} mas" + (
                f" = {x / 206264806.2 * dist * 1.495978707e8:.1f} km" if dist else "")
    if not ast:
        missing["Target"] = ("planet or moon: no error ellipse (ephemeris error see Path 1σ)"
                             if ":" in str(r.get("target_id", "")) else
                             "no error ellipse from JPL Horizons" if entry.get("err_checked") else "not fetched yet")
    star_at, disk, at_note = None, None, ""
    ox, oy, rad = _f(r.get("offset_east_km")), _f(r.get("offset_north_km")), _f(r.get("r_km"))
    if dist and ox is not None and oy is not None:                # the star seen from the site: -(axis - observer)
        k = 206264806.2 / (dist * 1.495978707e8)                  # mas per km at the target
        star_at, disk = (-ox * k, -oy * k), (rad * k if rad else None)
        off = math.hypot(ox, oy)
        inside = rad is not None and off < rad
        at_note = (f"star at site (dashed): {math.hypot(*star_at):.1f} mas = {off:.1f} km"
                   + (", inside" if inside else ", outside"))
        if rad and off > 2 * (2 * rad):                           # far outside: no zoom out for it, not drawn
            at_note = f"star at site: {off:.1f} km off (> 2 widths, not drawn)"
            star_at, disk = None, None
    return ellipses.svg(ast, star, (mra, mde) if mra is not None and mde is not None else None, size, note=note,
                        missing=missing, star_note=star_note, star_at=star_at, disk_mas=disk, star_at_note=at_note)


def _f(v):
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def _hms(deg, hours=False, nd=3):
    v = abs(deg) / (15.0 if hours else 1.0)
    a, rest = int(v), (v - int(v)) * 60
    b, c = int(rest), (rest - int(rest)) * 60
    if round(c, nd) >= 60:
        b, c = b + 1, 0.0
    if b >= 60:
        a, b = a + 1, 0
    if hours:
        return f"{a:02d}h {b:02d}m {c:0{3 + nd}.{nd}f}s"
    return f"{'-' if deg < 0 else '+'}{a:02d}° {b:02d}′ {c:0{3 + nd - 1}.{nd - 1}f}″"


def event_info(entry):
    """The favorite as OWC's event page summarises it: [(group, [(label, value), ...])] for Prediction, Event,
    Star and Object. Values the record does not have are left out ('—' where OWC always shows one)."""
    from pysyzygos import binaries
    r, ph, run = entry["record"], entry.get("phys") or {}, entry.get("run") or {}
    f = lambda k: _f(r.get(k))
    rad, speed, s1 = f("r_km"), f("speed_kms"), f("path_sigma1_km")
    body = ":" in str(r.get("target_id", ""))
    t = lambda u: (str(u).replace("T", " ")[:19] + " UT") if u else "—"
    hm = lambda u: (("≈ " if str(u).startswith("~") else "") + str(u).lstrip("~")[11:19] + " UT") if u else "—"
    pred = [("Last updated", t(run.get("run_utc"))),
            ("Computed by", f"PySyzygos {entry.get('version', '?')}"),
            ("Data sources", "JPL Horizons / Gaia DR3 (local catalog)" + (", NAIF" if body else "")),
            ("Orbit", (ph.get("orbit") or ["—"])[0] if not body else "planetary ephemeris (Horizons)"),
            ("Error (path widths)", f"{s1 / (2 * rad):.2f}" if s1 and rad else "—"),
            ("Error in time", f"≈ {s1 / speed:.1f} s" if s1 and speed else "—"),
            ("Path 1σ", f"{s1:.1f} km ({r.get('sigma_source') or '?'}" + (": 3σ RSS / 3)" if r.get("sigma_source") == "Horizons" else ")")
             if s1 else "—"),
            ("Id", entry.get("key", ""))]
    m_ast, mag, drop = f("m_ast"), f("mag"), f("mag_drop")
    illum, msep, elong = f("moon_illum_pct"), f("moon_sep_deg"), f("sun_elong_deg")
    ev = [("From", hm(r.get("shadow_from_utc"))), ("To", hm(r.get("shadow_to_utc"))),
          ("At the site", t(r.get("best_utc"))),
          ("Combined mag (G)", f"{f('m_combined'):.2f}" if f("m_combined") is not None else "—"),
          ("Max duration", f"{f('max_duration_s'):.2f} s" if f("max_duration_s") is not None else "—"),
          ("Mag drop (G)", f"{drop:.2f}" if drop is not None else "—"),
          ("Shadow width", f"{2 * rad:.1f} km" if rad else "—")] + \
         ([("Site height shift", f"{abs(f('height_shift_km')):.2f} km to side "
                                 f"{'A' if f('height_shift_km') >= 0 else 'B'} (map lines at height 0)")]
          if f("height_shift_km") is not None else []) + \
         [("Moon phase", f"{illum:.0f}% sunlit" if illum is not None else "—"),
          ("Solar elong.", f"{elong:.0f}°" if elong is not None else "—"),
          ("Moon elong.", f"{msep:.0f}°" if msep is not None else "—")]
    ra, dec = f("star_ra"), f("star_dec")
    from pysyzygos.report import star_label
    name, others = star_label(r)
    star = [("Name", name or "—")] + ([("Also", others)] if others else []) + \
           [("G mag", f"{mag:.2f}" if mag is not None else "—")]
    if ra is not None and dec is not None:
        try:
            import warnings
            from astropy.coordinates import SkyCoord, TETE, get_constellation
            from astropy.time import Time
            import astropy.units as au
            c = SkyCoord(ra * au.deg, dec * au.deg, frame="icrs")
            star.insert(1, ("Constellation", get_constellation(c)))
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                app = c.transform_to(TETE(obstime=Time(str(r.get("best_utc"))[:23], scale="utc")))
            apparent = (_hms(app.ra.deg, True, 4), _hms(app.dec.deg))
        except Exception:
            apparent = None
        star += [("RA [ICRS]", _hms(ra, True, 4)), ("Dec [ICRS]", _hms(dec))]
        if apparent:
            star += [("RA [apparent]", apparent[0]), ("Dec [apparent]", apparent[1])]
    ruwe = f("gaia_ruwe")
    if ruwe is None:
        ruwe = f("star_ruwe")                                     # a supplement star: RUWE from the local supplement
    sflag = (r.get("star_flag") or "").strip()
    star += [("RUWE", f"{ruwe:.2f}" + (" \u2691 (supplement: position less certain)" if sflag.startswith("RUWE") else "")
              if ruwe is not None else ("2-parameter source \u2691 (see proper motion)" if sflag
                                        else "< 1.4 (local catalog)")),
             ("Proper motion", pm_text(r)),
             *([("Other estimates", alts_text(r))] if (r.get("star_pm_alts") or "").strip() else []),
             ("Close/double", double_text(entry) or "not checked yet")]
    dist = f("dist_au")
    mas = (2 * rad / (dist * 1.495978707e8) * 206264806.2) if rad and dist else None
    rng = (f" (range {2 * f('r_min_km'):.1f} to {2 * f('r_max_km'):.1f})" if f("r_min_km") is not None and f("r_max_km") is not None
           else "")
    obj = [("Name", (r.get("target_name") or r.get("target_id") or "").strip()),
           ("Class", r.get("kind") or "asteroid"),
           ("Diameter", f"{2 * rad:.2f} km{rng}, {str(r.get('size_source', '')).split(' (ref')[0]}"
            + (" (* estimate, uncertain by a factor ~1.7)" if str(r.get("size_source", "")).lower().startswith("h only")
               else "") if rad else "—"),
           ("Diameter (angular)", f"{mas:.2f} mas" if mas else "—"),
           ("Distance", f"{dist:.4f} au" if dist else "—"),
           ("Mag", f"{m_ast:.1f}" if m_ast is not None else "—"),
           ("Motion RA", f"{f('motion_ra_ash'):.2f} ″/h" if f("motion_ra_ash") is not None else "—"),
           ("Motion Dec", f"{f('motion_dec_ash'):.2f} ″/h" if f("motion_dec_ash") is not None else "—"),
           ]
    for k, label in (("H", "H"), ("albedo", "Albedo")):
        if k in ph:
            obj.append((label, str(ph[k][0])))
    if not body:
        obj += [("Shape, rotation", shape_text(entry) or "not known"),
                ("Satellites", binaries.text(r.get("target_id", "")) or "none known (Johnston 2019)")]
    return [("Prediction", pred), ("Event", ev), ("Star", star), ("Object", obj)]


def predicted_utc(entry):
    """When the favorite's prediction was computed: its search run (run summary run_utc, UTC), else when it was
    added; 'YYYY-MM-DDTHH:MM:SS' or ''."""
    return str((entry.get("run") or {}).get("run_utc") or entry.get("added") or "")[:19]


def prediction_text(entry):
    """'predicted 2026-10-30 01:47 UT (search run), orbit JPL#1029 of 2026-10-28; added 2026-10-30 01:48 UT'."""
    t = predicted_utc(entry)
    o = (entry.get("phys") or {}).get("orbit")
    orbit = o[0] if isinstance(o, (list, tuple)) and o else (o.get("value") if isinstance(o, dict) else o)
    out = f"predicted {t[:16].replace('T', ' ')} UT (search run)" if t else "prediction time not known"
    out += f", orbit {orbit}" if orbit else ""
    added = str(entry.get("added") or "")[:16].replace("T", " ")
    return out + (f"; added {added} UT" if added else "")


def title_text(entry):
    """'369152 (2008 SJ52) occults Gaia DR3 3160985089639151616 around 2026-10-12 04:58:57 UT at Site (40.0000,
    -73.0000, 30 m)'."""
    r, site = entry["record"], entry.get("site") or {}
    where = site.get("name", "?")
    if site.get("lat") is not None and site.get("lon") is not None:
        where += f" ({float(site['lat']):.4f}, {float(site['lon']):.4f}" + (
            f", {float(site['ele']):.0f} m)" if site.get("ele") is not None else ")")
    from pysyzygos.report import star_label
    star = f"{star_label(r)[0]} " if str(r.get("star") or "").strip() else ""
    return (f"{(r.get('target_name') or r.get('target_id') or '').strip()} occults {star}around "
            f"{str(r.get('best_utc'))[:19].replace('T', ' ')} UT at {where}")


def size_text(entry):
    """'D 3.04 km (2.81-3.27 km, SBDB diameter, NEOWISE) · H 14.03 · albedo 0.06': the size the search used (from
    its record: radius and range, source) and the cached SBDB data kept with the favorite."""
    r, ph = entry["record"], entry.get("phys") or {}
    parts = []
    try:
        d, lo, hi = (2 * float(r[k]) for k in ("r_km", "r_min_km", "r_max_km"))
        src = (r.get("size_source") or "").split(" (ref")[0].strip()
        if "neowise" in (r.get("size_source") or "").lower():
            src += ", NEOWISE"
        parts.append(f"D {d:.2f} km ({lo:.2f}-{hi:.2f} km" + (f", {src})" if src else ")"))
    except (KeyError, TypeError, ValueError):
        pass
    for k, label in (("H", "H"), ("albedo", "albedo")):
        if k in ph:
            parts.append(f"{label} {ph[k][0]}")
    if str(r.get("size_source") or "").lower().startswith("h only"):
        parts.append("* estimate, uncertain by a factor ~1.7")
    return " · ".join(parts)


def shape_text(entry):
    """'axes 18.2 x 10.5 x 8.9 km · rotation 5.27 h · pole (300, 25) · type S': shape and rotation data from SBDB kept
    with the favorite, where known (most small asteroids have none). Empty string if there is nothing."""
    ph, parts = entry.get("phys") or {}, []
    if "extent" in ph:
        parts.append(f"axes {str(ph['extent'][0]).replace('x', ' x ')} km")
    if "rot_per" in ph:
        parts.append(f"rotation {ph['rot_per'][0]} h")
    if "pole" in ph:
        parts.append(f"pole {ph['pole'][0]}")
    tax = ph.get("spec_T") or ph.get("spec_B")
    if tax:
        parts.append(f"type {tax[0]}")
    return " · ".join(parts)


def find_record(csv_path, target_id, best_utc):
    """The hits_log row (dict) of this event, matched by target and event minute, or None."""
    import csv
    want = key_of(target_id, best_utc)
    try:
        with open(csv_path, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if key_of(r.get("target_id", ""), r.get("best_utc", "")) == want:
                    return r
    except OSError:
        pass
    return None


def main():
    from pysyzygos.home import HOME
    os.chdir(HOME)
    if sys.argv[1:2] != ["list"]:
        sys.exit(__doc__)
    for e in load():
        r, s = e["record"], e.get("site") or {}
        print(f"{e['key']:24s} {e['status']:9s} {(r.get('target_name') or '')[:28]:28s} site {s.get('name', '?'):12s} "
              f"G {float(r.get('mag') or 0):5.2f}  {e['note'][:40]}")


if __name__ == "__main__":
    sys.exit(main())
