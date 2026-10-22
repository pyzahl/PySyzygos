"""exports.py - the GUI's CSV downloads, with the columns of csv_exports.py (data folder; template
templates/csv_exports.py): Results, Planets & Moons, Favorites and the saved picks. The default columns are the
tables' columns with the values as shown; the file can add any raw column of the logs, or all ("*").

    write(kind, rows, path)   rows: [(shown, raw)] -> CSV (UTF-8 with BOM), columns from spec(kind)
    results_rows(db_path, lst)  the Results ("main") / Planets & Moons ("bodies") rows from the results database
                              (pysyzygos.db, the list's current series; same events and order as the report)
    favorite_rows(items)      the favorites (favorites.load()), by event time as on the page
    pick_rows(csv_path, targets)  a saved pick's events as the Pick tab shows them (pick_shown)
Standard library only.
"""
from pysyzygos.version import __version__
import csv, os, runpy, shutil, sys, tempfile

TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates", "csv_exports.py")
FILE = "csv_exports.py"


def spec(kind, home=None):
    """The column list of an export: the user's csv_exports.py (created from the template if missing) over the
    template's."""
    exports = dict(runpy.run_path(TEMPLATE)["EXPORTS"])
    if home is not None:
        user = os.path.join(home, FILE)
        if not os.path.isfile(user):
            shutil.copyfile(TEMPLATE, user)
            print(f"created {user} from the template (the CSV columns; edit it as you like)", file=sys.stderr)
        exports.update(runpy.run_path(user).get("EXPORTS") or {})
    if kind not in exports:
        raise KeyError(f"no export '{kind}' in {FILE}")
    return list(exports[kind])


def _value(v):
    return "" if v is None else v


def write(kind, rows, path, home=None, columns=None):
    """Write rows [(shown, raw)] as CSV with the columns of `kind` (or `columns`). Returns the number of rows."""
    cols = columns if columns is not None else spec(kind, home)
    heads, getters = [], []
    for c in cols:
        if c == "*" or (isinstance(c, (tuple, list)) and c[-1] == "*"):
            named = {s[4:] for h, s in (x for x in cols if isinstance(x, (tuple, list))) if isinstance(s, str)
                     and s.startswith("raw:")}
            for raw_key in [k for _, raw in rows for k in raw]:
                if raw_key not in named and raw_key not in heads:
                    heads.append(raw_key)
                    getters.append(lambda sh, raw, k=raw_key: raw.get(k))
            continue
        head, src = c
        if callable(src):
            getters.append(lambda sh, raw, f=src: f(sh, raw))
        elif src.startswith("raw:"):
            getters.append(lambda sh, raw, k=src[4:]: raw.get(k))
        else:
            getters.append(lambda sh, raw, k=src: sh.get(k))
        heads.append(head)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(path)), suffix=".tmp")
    with os.fdopen(fd, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(heads)
        for shown, raw in rows:
            w.writerow([_value(g(shown, raw)) for g in getters])
    os.replace(tmp, path)
    return len(rows)


# ---------------------------------------------------------------- shown values (as the tables show them)
def shadow_text(e):
    """'12.3 km, inside' / '12.3 km, 5.1 km out' (Shadow dist column)."""
    if e["miss"] is None:
        return "—"
    m = e["margin"]
    return f"{e['miss']:.1f} km" + ("" if m is None else ", inside" if m <= 0 else f", {m:.1f} km out")


def event_shown(e):
    """The values of a Results / Planets & Moons / Favorites row (report.build_event output) by name."""
    from pysyzygos import report as R, binaries
    tag = binaries.short(e["tid"]) if not e.get("body") else ""
    drop = R.fmt(e["drop"]) + ((" ⚠" + (f" {e['drop_blend']:.2f}" if e.get("drop_blend") is not None else ""))
                               if e.get("dhint") else "")
    dur = e.get("contact_dur")
    out = dict(
        asteroid=(f"{e['label']} ({e['kind'] or 'body'})" if e.get("body") else e["label"])
        + (f" {tag}" if tag else "") + (" *" if R.size_estimated(e) else ""),
        event_time=R.fmt_time(e["when"]), event_utc=e["utc"], gaia_id=e["star"],
        star_name=e.get("star_name") or "", star_other_names=e.get("star_tip") or "", kind=e["kind"],
        star_mag=R.fmt(e["mag"]) + (f" \u26a0 star \u00b1{R.star_uncertain(e):.0f} km" if R.star_uncertain(e)
                                    else f" \u2691 {e['sflag']}" if e.get("sflag") else "")
        + (f" {R.twilight_text(e.get('sun'))}" if R.twilight_text(e.get("sun")) else ""),
        sun_alt=None if e.get("sun") is None else round(e["sun"], 1),
        star_flag=e.get("sflag") or "", star_sigma_km=None if e.get("star_sigma") is None else round(e["star_sigma"], 1),
        mag_drop=drop, max_dur=R.fmt(e["dur"]), altitude=R.alt_text(e) + (f" ({R.horizon_text(e)})" if R.horizon_text(e) else ""),
        moon_dist=R.moon_text(e), shadow_dist=shadow_text(e), chance=R.chance_text(e),
        chance_pct=None if e.get("p_site") is None else round(100 * e["p_site"], 1),
        shadow_km=None if e["miss"] is None else round(e["miss"], 1),
        diameter_km=None if e["rad"] is None else round(2 * e["rad"], 1), size_source=e["size_src"],
        body=f"{e['label']} ({e['kind'] or 'body'})",
        d_time=f"{e['when']:%Y-%b-%d} {R.contact_text(e.get('d_utc'))}", closest=R.contact_text(e["utc"]),
        r_time=R.contact_text(e.get("r_utc")),
        duration="—" if not dur else (f"{dur / 60:.1f} min" if dur >= 120 else f"{dur:.1f} s"))
    f = e.get("fav")
    if f:
        out.update(site=(e.get("site") or {}).get("name", "?"), status=f["status"], note=f["note"],
                   added=f["added"][5:16].replace("T", " "), added_utc=f["added"])
    return out


def results_rows(db_path, lst="main", lat=None, lon=None, sort="mag"):
    """[(shown, raw)] of a results list's current series in the database, as the report lists them (deduplicated;
    brightest star first, or by date). raw: the event record with values as the log CSV writes them."""
    from pysyzygos import report as R, db
    con = db.connect(db_path)
    try:
        rows = [{k: db._cell(v) for k, v in rec.items()} for rec in db.events(con, lst=lst)]
        runs = db.runs(con, lst=lst)
    finally:
        con.close()
    site = (runs[-1] if runs else {}).get("site") or {}
    lat, lon = site.get("lat", lat), site.get("lon", lon)
    out_dir = os.path.dirname(os.path.abspath(db_path))
    pairs = []
    for r in rows:
        try:
            pairs.append((R.build_event(r, lat, lon, os.devnull, out_dir), r))
        except (KeyError, ValueError):
            continue
    kept = {id(e) for e in R.dedupe([e for e, _ in pairs])}
    pairs = [(e, r) for e, r in pairs if id(e) in kept]
    if sort == "mag":
        pairs.sort(key=lambda p: (p[0]["mag"] is None, p[0]["mag"] if p[0]["mag"] is not None else 0.0, p[0]["when"]))
    else:
        pairs.sort(key=lambda p: p[0]["when"])
    return [(event_shown(e), r) for e, r in pairs]


def only_shown(pairs, keys):
    """The rows [(shown, raw)] that the page shows, in its order: keys = the visible rows' report.event_key, top to
    bottom (filter bar, SQL filter and sorting applied). keys None (page not readable): all rows, unchanged."""
    if keys is None:
        return pairs
    from pysyzygos import report as R
    order = {k: i for i, k in enumerate(keys)}
    kept = [(order[k], p) for p in pairs
            if (k := R.event_key(p[1].get("target_id", ""), p[1].get("best_utc", ""))) in order]
    return [p for _, p in sorted(kept, key=lambda x: x[0])]


def favorite_rows(items):
    """[(shown, raw)] of the favorites (favorites.load()), by event time as on the Favorites page."""
    from pysyzygos import report as R
    pairs = []
    for f in items:
        r, site = f["record"], f.get("site") or {}
        try:
            e = R.build_event(r, site.get("lat"), site.get("lon"), os.devnull, ".")
        except (KeyError, ValueError):
            continue
        e.update(fav=dict(key=f["key"], status=f.get("status", ""), note=f.get("note", ""), added=f.get("added", "")),
                 site=site)
        pairs.append((e, r))
    pairs.sort(key=lambda p: p[0]["when"])
    return [(event_shown(e), r) for e, r in pairs]


def pick_shown(r, targets):
    """A pick_events.csv row as the Pick tab shows it (2 decimals, * for a size from H, ✓ for a search target)."""
    s = dict(r)
    for k in ("H", "star_mag", "drop", "dur_s", "mag_margin", "miss_km", "star_alt"):
        try:
            s[k] = f"{float(r[k]):.2f}" if r.get(k) not in (None, "") else ""
        except ValueError:
            s[k] = r.get(k) or ""
    if str(r.get("D_est")).lower() == "true":                        # size from H only (see the report note)
        s["name"] = f"{r.get('name', '')} *"
    s["target"] = "✓" if str(r.get("number")) in targets else ""
    from pysyzygos.gaia_local import star_flag                       # supplement star (RUWE >= 1.4, 2-parameter)
    flag = star_flag(r.get("star_kind") or 0, r.get("star_ruwe"))
    s["star_flag"] = flag
    if flag:                                                     # no proper motion at all: the strong warning sign
        s["star_mag"] = f"{s['star_mag']} {'\u26a0' if 'NO proper motion' in flag else '\u2691'} {flag}"
    from pysyzygos.report import twilight_text                       # Sun above -12 deg at the site: twilight
    try:
        twi = twilight_text(float(r["sun_alt"])) if r.get("sun_alt") not in (None, "") else ""
    except ValueError:
        twi = ""
    if twi:
        s["star_mag"] = f"{s['star_mag']} {twi}"
    return s


def pick_rows(csv_path, targets):
    with open(csv_path, newline="", encoding="utf-8") as f:
        raw = list(csv.DictReader(f))
    return [(pick_shown(r, targets), r) for r in raw]
