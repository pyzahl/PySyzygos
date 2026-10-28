"""db.py - PySyzygos's results database: one SQLite file in the data folder (config `results_db`, default
pysyzygos.db). Standard library only (sqlite3).

Tables
  runs       one row per search run: series, start time, mode, summary (the run summary as JSON, see search.py)
  events     one row per logged event: run, series, kind ('asteroid'; later 'planet', 'moon', 'eclipse', ...), target,
             event time, star, and the full record as JSON (the same fields as a hit-log row)
  contacts   contact times of an event (D/R for the Moon and planets, C1-C4 for eclipses; not used by asteroids yet)
  favorites  the favorites list (one row per favorite, the entry as JSON; map/preview copies stay files)
  meta       schema version, current series
Views
  hits       one row per event with the useful record fields as plain, typed columns (HITS: name, field, unit,
             meaning), for conditions such as "mag < 11 AND chance > 30" (where_keys; GUI Results "SQL filter")

Results *lists* keep different searches apart (config `results_list`): "main" (the asteroid search, exported as
hits_log.csv) and "bodies" (planets and moons, the Planets & Moons tab, exported as bodies_log.csv). Each list has
its own current series; series numbers are unique across lists.
A *series* is what the old hits_log.csv was: the events since the last fresh start ("Start a fresh results list" in
the GUI, config `results_new_series`). Older series stay in the database. After each run the current series is
written out as hits_log.csv and hits_log.runs.jsonl (exports with consistent columns, for the report, the CSV
download and other tools). An existing hits_log.csv / runs.jsonl / favorites.json is imported once.
"""
from pysyzygos.version import __version__
import csv, json, math, os, re, sqlite3, tempfile, time

SCHEMA = 1
DEFAULT = "pysyzygos.db"


def _json(obj):
    return json.dumps(obj, default=lambda o: o.item() if hasattr(o, "item") else str(o))


def connect(path=DEFAULT):
    """Open (and create) the database. Several processes may use it (GUI and a run): WAL mode, 30 s busy wait."""
    con = sqlite3.connect(path, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript("""
        CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS runs (id INTEGER PRIMARY KEY, series INTEGER, started TEXT, mode TEXT, summary TEXT);
        CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, run_id INTEGER, series INTEGER, kind TEXT,
            target_id TEXT, best_utc TEXT, best_et REAL, star TEXT, record TEXT);
        CREATE INDEX IF NOT EXISTS events_series ON events (series);
        CREATE INDEX IF NOT EXISTS events_key ON events (target_id, best_utc);
        CREATE TABLE IF NOT EXISTS contacts (event_id INTEGER, label TEXT, utc TEXT, et REAL, data TEXT);
        CREATE TABLE IF NOT EXISTS favorites (key TEXT PRIMARY KEY, pos INTEGER, entry TEXT);
    """)
    create_hits_view(con)
    con.execute("INSERT OR IGNORE INTO meta VALUES ('schema', ?)", (str(SCHEMA),))
    con.execute("INSERT OR IGNORE INTO meta VALUES ('series', '1')")
    if "list" not in [r[1] for r in con.execute("PRAGMA table_info(runs)")]:     # schema 1 without lists
        con.execute("ALTER TABLE runs ADD COLUMN list TEXT DEFAULT 'main'")
    con.commit()
    return con


# ------------------------------------------------------------------------------------------- the hits view
# (column, record field(s) (first non-empty wins) or SQL, kind 'num' | 'text', unit, meaning): the view's columns,
# the GUI's field list and its autocomplete (one source). Numbers that are text in older records (imported CSV) are
# converted; '', 'nan' and missing values are NULL, never 0.
HITS = [
    ("target", "target_id", "text", "", "asteroid number or body (P:Jupiter)"),
    ("name", "target_name", "text", "", "name, e.g. '(4089) Galbraith'"),
    ("utc", "best_utc", "text", "UTC", "closest approach at the site, ISO time, e.g. utc >= '2026-11-01'"),
    ("mag", "mag", "num", "G mag", "star magnitude (Gaia G)"),
    ("mag_drop", "mag_drop", "num", "mag", "magnitude drop"),
    ("mag_drop_blended", "mag_drop_blended", "num", "mag", "drop with close neighbours' light"),
    ("duration", "max_duration_s", "num", "s", "maximum duration (center line)"),
    ("star_alt", "star_alt", "num", "deg", "star altitude at the event"),
    ("star_az", "star_az", "num", "deg", "star azimuth (from north through east)"),
    ("sun_alt", "sun_alt", "num", "deg", "Sun altitude at the site"),
    ("moon_sep", "moon_sep_deg", "num", "deg", "Moon's distance from the star"),
    ("moon_illum", "moon_illum_pct", "num", "%", "Moon illuminated"),
    ("chance", "p_site", "pct", "%", "chance that the shadow covers the site, 0-100"),
    ("distance", "min_distance", "num", "km", "site's distance from the shadow center line in the fundamental plane"),
    ("ground_dist", "ground_dist_km", "num", "km", "site's distance from the shadow center line on the ground, across "
     "the track (from 1.4.1; up to 1 / sin(star altitude) x distance)"),
    ("radius", "r_km", "num", "km", "asteroid radius (shadow half-width)"),
    ("sigma", "path_sigma1_km", "num", "km", "path uncertainty, 1 sigma"),
    ("star_sigma", "star_sigma_km", "num", "km", "the star's own position uncertainty, 1 sigma"),
    ("ruwe", "star_ruwe|gaia_ruwe", "num", "", "Gaia RUWE (above 1.4: often a double star)"),
    ("star_flag", "star_flag", "text", "", "supplement star: 'RUWE 1.65' or '2p ...'; '' main catalog"),
    ("star_kind", "star_kind", "num", "", "0 main catalog, 1 high RUWE, 2+ 2-parameter star"),
    ("double_hint", "double_hint", "text", "", "close or double star note ('' none)"),
    ("horizon", "horizon_flag", "text", "", "your horizon: 'behind', 'near' or ''"),
    ("size_source", "size_source", "text", "", "where the size comes from, e.g. 'H only, albedo assumed'"),
    ("dist_au", "dist_au", "num", "au", "asteroid's distance from the Earth"),
    ("speed", "speed_kms", "num", "km/s", "shadow speed"),
    ("star", "star", "text", "", "Gaia DR3 source id"),
    ("hip", "star_hip", "text", "", "Hipparcos number ('' none)"),
    ("tyc", "star_tyc", "text", "", "Tycho-2 number ('' none)"),
    ("ucac4", "star_ucac4", "text", "", "UCAC4 number ('' none)"),
    # observed events (results list 'observed': the Occult archive, observed.py) and their check (obscheck.py)
    ("chords", "n_positive", "num", "", "observed: positive chords"),
    ("observers", "n_observers", "num", "", "observed: observers"),
    ("fit_quality", "fit_quality", "num", "", "observed: 0 none, 1 astrometry only, 2 size limits, 3 reliable size, 4 better than shape models"),
    ("cbet", "sat_cbet", "text", "", "observed: CBET number of a satellite found by this occultation ('' none)"),
    ("dx_across", "chk_across_km", "num", "km", "observed minus predicted, across the track"),
    ("dt_along", "chk_along_s", "num", "s", "observed minus predicted, along the track, in seconds (archive's fit)"),
    ("dt_site", "chk_site_dt_s", "num", "s", "observed minus predicted chord mid-time at the observers' sites (median)"),
    ("scope", "scope", "text", "", "'earth' for a search anywhere on Earth, '' at a site"),
    ("class", "ast_class", "text", "", "JPL orbit class: MBA, IMB, OMB, TJN, MCA, APO, AMO, ATE, IEO, TNO, CEN, ... "
     "e.g. class IN ('TJN', 'TNO')"),
]


def _num_sql(field):
    v = f"json_extract(record, '$.{field}')"
    t = f"json_type(record, '$.{field}')"
    return (f"(CASE WHEN {t} IN ('real', 'integer') THEN {v} WHEN {t} = 'text' AND trim({v}) <> '' AND "
            f"lower(trim({v})) NOT IN ('nan', 'inf', '-inf', 'none') AND trim({v}) NOT GLOB '*[^-+.0-9eE ]*' "
            f"THEN CAST(trim({v}) AS REAL) END)")


def create_hits_view(con):
    """Create the view hits from HITS, or replace it when this code defines it differently (once after an update).
    Safe with several connections opening at the same time."""
    cols = ["e.id AS id", "e.series AS series", "e.kind AS kind", "e.run_id AS run",
            "COALESCE(json_extract(r.summary, '$.site.name'), '') AS site"]
    for name, fields, kind, _, _ in HITS:
        parts = []
        for f in fields.split("|"):
            if kind in ("num", "pct"):
                parts.append(_num_sql(f) + (" * 100.0" if kind == "pct" else ""))
            else:
                parts.append(f"NULLIF(CAST(json_extract(record, '$.{f}') AS TEXT), '')")
        expr = parts[0] if len(parts) == 1 else f"COALESCE({', '.join(parts)})"
        if kind == "text" and len(parts) == 1:
            expr = f"COALESCE({expr}, '')"
        cols.append(f"{expr} AS {name}")
    sql = "CREATE VIEW hits AS SELECT " + ", ".join(cols) + " FROM events e LEFT JOIN runs r ON r.id = e.run_id"
    row = con.execute("SELECT sql FROM sqlite_master WHERE type='view' AND name='hits'").fetchone()
    if row and row[0] == sql:                                   # current already: nothing to do (the usual case)
        return
    # several connections may open at once (GUI start: a background task and the page): one changes the view under
    # a write lock; another that finds it changed meanwhile leaves it (it failed with "view hits already exists")
    try:
        con.execute("BEGIN IMMEDIATE")
        row = con.execute("SELECT sql FROM sqlite_master WHERE type='view' AND name='hits'").fetchone()
        if not (row and row[0] == sql):
            con.execute("DROP VIEW IF EXISTS hits")
            con.execute(sql)
        con.execute("COMMIT")
    except sqlite3.OperationalError:
        try:
            con.execute("ROLLBACK")
        except sqlite3.OperationalError:
            pass


# functions usable in conditions (registered by where_keys): name, unit, meaning (also the GUI's field list)
FUNCTIONS = [
    ("horizon_alt(star_az)", "deg", "your horizon's altitude at that azimuth, for the list's site (NULL: no horizon "
     "set for it); e.g. star_alt > horizon_alt(star_az) + 5"),
    ("horizon_alt(star_az, site)", "deg", "the same for each event's own site (column site) or a named one"),
]


def _horizons():
    """{site name: horizon points [(az, alt)]} of sites.py in the data folder (sites without a horizon left out)."""
    try:
        from pysyzygos.sitesfile import load_sites
        sites, _ = load_sites()
    except Exception:
        return {}
    return {n: [tuple(map(float, p)) for p in (v.get("horizon") or [])] for n, v in sites.items() if v.get("horizon")}


def _horizon_functions(con, list_site):
    """Register horizon_alt(az [, site]) on a connection: the site's horizon altitude (horizon.altitude, the search's
    own interpolation) at an azimuth; NULL for a site without a horizon or an unknown azimuth."""
    from pysyzygos import horizon as H
    hz = {}

    def alt(az, site):
        if not hz:
            hz.update(_horizons() or {"": []})
        pts = hz.get(site or "")
        if az is None or not pts:
            return None
        try:
            return H.altitude(pts, float(az))
        except (TypeError, ValueError):
            return None
    con.create_function("horizon_alt", 1, lambda az: alt(az, list_site), deterministic=True)
    con.create_function("horizon_alt", 2, alt, deterministic=True)


# the report's filter bar (report.filter_bar: limits and flags) as a condition on hits, to start a custom one from;
# fields often unknown keep the bar's rule "unknown values pass" (IS NULL OR ...)
FILTER_SQL = {"mag": "mag <= {v}", "dur": "duration >= {v}", "drop": "(mag_drop IS NULL OR mag_drop >= {v})",
              "alt": "star_alt >= {v}", "sun": "sun_alt <= {v}", "ruwe": "(ruwe IS NULL OR ruwe <= {v})",
              "chance": "(chance IS NULL OR chance >= {v})"}
FILTER_HIDE_SQL = {"sup": "star_flag = ''", "unc": "(star_sigma IS NULL OR star_sigma <= 0.5 * radius)",
                   "dbl": "double_hint = ''", "twi": "sun_alt <= -12", "hz": "horizon NOT IN ('behind', 'near')",
                   "est": "size_source NOT LIKE 'H only%'"}


def filter_to_sql(spec):
    """The filter bar's settings ({'mag': 12.5, ..., 'hide': [...], 'only': [...]}) as an SQL condition, every
    part joined with AND; '' for no filter. 'only +moon' has no column: kept as a comment."""
    parts = []
    for k, op, tail in (("from", ">=", ""), ("to", "<=", ":59.999")):    # time window: ISO text compares in order
        v = str((spec or {}).get(k) or "").strip()
        if re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d", v):
            parts.append(f"utc {op} '{v}{tail}'")
    for k, tpl in FILTER_SQL.items():
        v = (spec or {}).get(k)
        if isinstance(v, (int, float)):
            parts.append(tpl.format(v=f"{v:g}"))
    v = (spec or {}).get("hzc")                                   # clear of the site's horizon by at least v deg
    if isinstance(v, (int, float)):
        parts.append(f"(horizon_alt(star_az, site) IS NULL OR star_alt - horizon_alt(star_az, site) >= {v:g})")
    parts += [FILTER_HIDE_SQL[h] for h in (spec or {}).get("hide", []) if h in FILTER_HIDE_SQL]
    sql = " AND ".join(parts)
    if "moon" in (spec or {}).get("only", []):
        sql = (sql + " " if sql else "1 = 1 ") + "/* only +moon: no SQL column */"
    return sql


WHERE_MAX_S = 10.0          # a condition's query is stopped after this long (e.g. an endless recursive subquery)


def where_keys(path, where, lst="main", series=None, limit=100000, max_s=WHERE_MAX_S):
    """The events of a results list's series (default: its current one) that match an SQL condition on the hits
    view, as [(target, utc), ...]. Safe with any text: a read-only connection (mode=ro + query_only: nothing can be
    written), one statement only, at most max_s seconds; raises ValueError with SQLite's message for a bad condition."""
    if ";" in where:
        raise ValueError("one condition only (no ';')")
    con = connect(path)                                       # the view exists and is current
    ser = current_series(con, lst) if series is None else series
    row = con.execute("SELECT summary FROM runs WHERE series = ? ORDER BY id DESC LIMIT 1", (ser,)).fetchone()
    con.close()
    try:
        list_site = (json.loads(row[0] or "{}").get("site") or {}).get("name", "") if row else ""
    except ValueError:
        list_site = ""
    con = sqlite3.connect(f"file:{os.path.abspath(path)}?mode=ro", uri=True, timeout=30)
    try:
        con.execute("PRAGMA query_only = ON")
        _horizon_functions(con, list_site)
        end = time.monotonic() + max_s
        con.set_progress_handler(lambda: 1 if time.monotonic() > end else 0, 10000)   # nonzero: SQLite stops
        try:
            rows = con.execute(f"SELECT target, utc FROM hits WHERE series = ? AND ({where}) LIMIT ?",
                               (ser, limit)).fetchall()
        except sqlite3.Error as ex:
            if time.monotonic() > end:
                raise ValueError(f"the condition took too long (stopped after {max_s:g} s)") from None
            raise ValueError(str(ex)) from None
        return [(str(t), str(u)) for t, u in rows]
    finally:
        con.close()


def _key(lst):
    return "series" if lst in (None, "", "main") else f"series:{lst}"


def _next_series(con):
    used = con.execute("SELECT MAX(CAST(value AS INTEGER)) FROM meta WHERE key LIKE 'series%'").fetchone()[0]
    return max(int(used or 0), int(con.execute("SELECT COALESCE(MAX(series), 0) FROM runs").fetchone()[0])) + 1


def current_series(con, lst="main"):
    """The current series of a results list (a new list gets its own series number)."""
    r = con.execute("SELECT value FROM meta WHERE key=?", (_key(lst),)).fetchone()
    if r is None:
        con.execute("INSERT INTO meta VALUES (?, ?)", (_key(lst), str(_next_series(con))))
        con.commit()
        return current_series(con, lst)
    return int(r[0])


def start_run(con, mode, new_series=False, lst="main"):
    """A new run of a results list (in a new series if new_series). Returns (run_id, series)."""
    series = current_series(con, lst)
    if new_series and con.execute("SELECT 1 FROM runs WHERE series=?", (series,)).fetchone():
        series = _next_series(con)                                # (an unused current series is simply reused)
        con.execute("UPDATE meta SET value=? WHERE key=?", (str(series), _key(lst)))
    cur = con.execute("INSERT INTO runs (series, started, mode, summary, list) VALUES (?, ?, ?, NULL, ?)",
                      (series, time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()), mode, lst or "main"))
    con.commit()
    return cur.lastrowid, series


def finish_run(con, run_id, summary):
    con.execute("UPDATE runs SET summary=? WHERE id=?", (_json(summary), run_id))
    con.commit()


def add_event(con, run_id, record, kind="asteroid", contacts=(), commit=True):
    """Log one event (record: the hit-log fields). contacts: [(label, utc, et, data dict)]. Returns its id.
    commit=False: the caller commits (bulk imports)."""
    series = con.execute("SELECT series FROM runs WHERE id=?", (run_id,)).fetchone()[0]
    cur = con.execute("INSERT INTO events (run_id, series, kind, target_id, best_utc, best_et, star, record) "
                      "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                      (run_id, series, kind, str(record.get("target_id", "")), str(record.get("best_utc", "")),
                       float(record.get("best_et") or 0.0), str(record.get("star", "")), _json(record)))
    for label, utc, et, data in contacts:
        con.execute("INSERT INTO contacts VALUES (?, ?, ?, ?, ?)", (cur.lastrowid, label, utc, et, _json(data or {})))
    if commit:
        con.commit()
    return cur.lastrowid


def update_events(con, records, updates, lst="main"):
    """Merge updates (one dict per record) into this series' events of these records (same target and time).
    Returns the number of events updated."""
    series, n = current_series(con, lst), 0
    for r, u in zip(records, updates):
        for row in con.execute("SELECT id, record FROM events WHERE series=? AND target_id=? AND best_utc=?",
                               (series, str(r["target_id"]), str(r["best_utc"]))).fetchall():
            rec = json.loads(row["record"])
            rec.update(u)
            con.execute("UPDATE events SET record=? WHERE id=?", (_json(rec), row["id"]))
            n += 1
    con.commit()
    return n


def events(con, series=None, kind=None, lst="main"):
    """The records (dicts, logging order) of a series (default: the list's current one), optionally of one kind."""
    series = current_series(con, lst) if series is None else series
    q, args = "SELECT record FROM events WHERE series=?", [series]
    if kind:
        q, args = q + " AND kind=?", args + [kind]
    return [json.loads(r["record"]) for r in con.execute(q + " ORDER BY id", args)]


def runs(con, series=None, lst="main"):
    """The run summaries (dicts) of a series, oldest first (runs without a summary are left out)."""
    series = current_series(con, lst) if series is None else series
    return [json.loads(r["summary"]) for r in con.execute(
        "SELECT summary FROM runs WHERE series=? AND summary IS NOT NULL ORDER BY id", (series,))]


def last_run(con):
    r = con.execute("SELECT summary FROM runs WHERE summary IS NOT NULL ORDER BY id DESC LIMIT 1").fetchone()
    return json.loads(r["summary"]) if r else None


def find_event(con, target_id, best_utc_prefix):
    """The newest record of an asteroid whose event time starts with best_utc_prefix (e.g. to the minute), or None."""
    r = con.execute("SELECT record FROM events WHERE target_id=? AND best_utc LIKE ? ORDER BY id DESC LIMIT 1",
                    (str(target_id).strip(), str(best_utc_prefix).strip() + "%")).fetchone()
    return json.loads(r["record"]) if r else None


def find_event_run(con, target_id, best_utc_prefix):
    """(record, run summary) of the newest event of a target (any list) whose time starts with best_utc_prefix, or
    (None, None)."""
    r = con.execute("SELECT e.record, r.summary FROM events e JOIN runs r ON r.id = e.run_id WHERE e.target_id=? "
                    "AND e.best_utc LIKE ? ORDER BY e.id DESC LIMIT 1",
                    (str(target_id).strip(), str(best_utc_prefix).strip() + "%")).fetchone()
    if not r:
        return None, None
    return json.loads(r["record"]), (json.loads(r["summary"]) if r["summary"] else None)


def _cell(v):
    """A record value as the hit log writes it ('' for None/NaN)."""
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return ""
    if isinstance(v, (list, dict)):                          # e.g. the observers' sites of an archive event
        return _json(v)
    return str(v)


def _atomic(path, write):
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(path)), suffix=".tmp")
    with os.fdopen(fd, "w", newline="", encoding="utf-8") as f:
        write(f)
    os.replace(tmp, path)


def export(con, csv_path, series=None, lst="main"):
    """Write a series (default: current) as csv_path (all events, columns in first-seen order) and its run summaries
    as <stem>.runs.jsonl. No events: the CSV is removed (as an empty hit log was before), the summaries are written."""
    series = current_series(con, lst) if series is None else series
    recs = events(con, series)
    cols = []
    for r in recs:
        cols += [k for k in r if k not in cols]
    if recs:
        _atomic(csv_path, lambda f: (csv.writer(f).writerow(cols),
                                     csv.writer(f).writerows([[_cell(r.get(k)) for k in cols] for r in recs])))
    elif os.path.isfile(csv_path):
        os.remove(csv_path)
    _atomic(os.path.splitext(csv_path)[0] + ".runs.jsonl",
            lambda f: f.writelines(_json(s) + "\n" for s in runs(con, series)))
    return len(recs)


def import_log(con, csv_path):
    """Import an existing hit log (and its runs.jsonl) as the current series, once (only into an empty database).
    Returns the number of events imported."""
    if con.execute("SELECT 1 FROM events LIMIT 1").fetchone() or not os.path.isfile(csv_path):
        return 0
    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    summaries = []
    jl = os.path.splitext(csv_path)[0] + ".runs.jsonl"
    if os.path.isfile(jl):
        with open(jl, encoding="utf-8") as f:
            summaries = [json.loads(ln) for ln in f if ln.strip()]
    run_id, series = start_run(con, "imported")
    for s in summaries[:-1]:                                      # earlier runs: summaries only
        con.execute("INSERT INTO runs (series, started, mode, summary) VALUES (?, ?, ?, ?)",
                    (series, s.get("run_utc", ""), "imported", _json(s)))
    finish_run(con, run_id, summaries[-1] if summaries else {"note": f"imported from {os.path.basename(csv_path)}"})
    for r in rows:
        add_event(con, run_id, {k: v for k, v in r.items() if k is not None})
    return len(rows)


# ---------------------------------------------------------------- favorites
def favorites_load(con):
    return [json.loads(r["entry"]) for r in con.execute("SELECT entry FROM favorites ORDER BY pos")]


def favorites_save(con, items):
    con.execute("DELETE FROM favorites")
    con.executemany("INSERT INTO favorites VALUES (?, ?, ?)", [(e["key"], i, _json(e)) for i, e in enumerate(items)])
    con.commit()


def favorites_import(con, json_path):
    """Import favorites.json once (only into an empty favorites table); the file is kept as favorites.json.migrated.
    Returns the number imported."""
    if con.execute("SELECT 1 FROM favorites LIMIT 1").fetchone() or not os.path.isfile(json_path):
        return 0
    with open(json_path, encoding="utf-8") as f:
        items = json.load(f)
    favorites_save(con, items)
    os.replace(json_path, json_path + ".migrated")
    return len(items)
