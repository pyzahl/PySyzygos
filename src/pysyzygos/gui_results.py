"""gui_results.py - Results tab: the report of the current results list, CSV download, OccultWatcher Cloud check.

Part of the GUI (gui.py builds the page): panel(pg) adds the tab's controls, handlers(pg) its functions, connect(pg)
wires them up; pg holds the page's elements and functions shared between the tabs. The SQL filter (a condition on the
results database's view hits, db.HITS) rebuilds the report with the matching events (report --where).
"""
import csv, os, re, time

from pysyzygos import db, exports, favorites
from pysyzygos.home import HOME as ROOT
from nicegui import run, ui
from pysyzygos.gui_common import KSTARS_OPT, PYSYZYGOS, load_ui_state, resizable_box, run_process, save_ui_state

# the SQL filter's help: columns of the view hits, the run's site, and the functions (db.HITS, db.FUNCTIONS)
SQL_NAMES = ([(n, "%" if k == "pct" else u, m) for n, _, k, u, m in db.HITS]
             + [("site", "", "the site the search was for (its name in sites.py)")] + list(db.FUNCTIONS))
SQL_EXAMPLES = ["mag < 11 AND chance > 30", "duration >= 1 AND sun_alt < -12", "ruwe < 1.4 AND star_flag = ''",
                "utc < '2026-11-15' AND star_alt > 20", "horizon = '' AND mag_drop > 0.5", "name LIKE '%Phaethon%'",
                "star_alt > horizon_alt(star_az) + 5"]


def panel(pg):
    """The results tab's controls (inside its ui.tab_panel)."""
    with ui.tab_panel(pg.t_res):
        with ui.row().classes("items-center"):
            ui.button("Rebuild report", on_click=lambda: pg.build_report()).props("outline")
            if getattr(pg.config, "owc_feeds", True):                    # config owc_feeds (on by default)
                ui.button("Check OWC Feeds", on_click=lambda: pg.owc_check("results")).props("outline dense").tooltip(
                    "Look these events up in OccultWatcher Cloud: prediction feeds (tags) and signed-up stations, "
                    "shown under the asteroid with a link to the OWC event page (one request per second)")
            ui.link("Open in a new tab", "/out/hits_report.html", new_tab=True)
            ui.button("CSV", on_click=lambda: pg.hits_csv()).props("outline dense").tooltip(
                "Download the events the table shows (its filter and sort order) as a CSV table."
                " Columns: csv_exports.py in the data folder (default: as the table shows them; any log column can be added)")
            ui.checkbox("KStars/Stellarium: set its location to the event site", value=KSTARS_OPT["set_location"],
                        on_change=lambda e: KSTARS_OPT.update(set_location=bool(e.value))).tooltip(
                "The report's KStars buttons (Linux, KStars running) and Stellarium buttons (Remote Control "
                "plugin). Off: they keep their location (KStars tells you if that is far from the site).")
        # SQL filter (advanced): a condition on the results database's view hits (db.HITS); the report is rebuilt
        # with only the matching events (report --where). The simple filter bar is in the report page itself.
        pg.sql_note = ui.label().classes("text-sm text-blue-800")
        with ui.expansion("SQL filter (advanced): a condition such as  mag < 11 AND chance > 30",
                          on_value_change=lambda e: pg.sql_from_bar(only_if_empty=True) if e.value else None
                          ).classes("w-full"):
            with ui.row().classes("w-full items-end gap-2 no-wrap"):
                pg.sql_in = ui.input("Condition", value=load_ui_state().get("sql_where") or "").classes("grow").props(
                    "dense clearable").tooltip("SQL condition on the columns listed below (AND, OR, NOT, <, <=, =, <>, "
                                               ">=, >, LIKE '%text%', IN (...), IS NULL); strings in single quotes")
                ui.button("From filter bar", on_click=lambda: pg.sql_from_bar()).props("dense flat no-caps").tooltip(
                    "Write the report's filter bar settings as an SQL condition, to edit (AND to OR, ...)")
                ui.button("Apply", on_click=lambda: pg.sql_apply()).props("dense color=primary")
                ui.button("Clear", on_click=lambda: pg.sql_clear()).props("dense outline")
            pg.sql_sugg = ui.row().classes("gap-1 min-h-[1.5rem]")       # field names matching the word being typed
            with ui.row().classes("items-center gap-1"):
                ui.label("Examples:").classes("text-xs text-slate-500")
                for x in SQL_EXAMPLES:
                    ui.button(x, on_click=lambda x=x: pg.sql_in.set_value(x)).props("dense flat no-caps size=sm")
            with ui.row().classes("items-end gap-2"):
                pg.sql_saved = ui.select({}, label="Saved conditions", on_change=lambda e: pg.sql_pick(e.value)).classes(
                    "w-64").props("dense")
                ui.button("Save as ...", on_click=lambda: pg.sql_save()).props("dense outline")
                ui.button("Delete", on_click=lambda: pg.sql_delete()).props("dense flat color=negative")
            with ui.expansion("Fields (click one to insert it)").classes("w-full"):
                pg.sql_fields = ui.table(
                    columns=[dict(name="name", label="Column", field="name", align="left"),
                             dict(name="unit", label="Unit", field="unit", align="left"),
                             dict(name="meaning", label="Meaning", field="meaning", align="left")],
                    rows=[dict(name=n, unit=u, meaning=m) for n, u, m in SQL_NAMES],
                    row_key="name").props("dense flat").classes("w-full text-xs")
        with resizable_box("results", 75):                            # drag the corner to resize (remembered)
            pg.frame = ui.element("iframe").style("width: 100%; height: 100%; border: 0; display: block")


def handlers(pg):
    """The results tab's functions and state, as attributes of pg."""
    async def owc_check(which):
        """Look the Results or Favorites events up in OccultWatcher Cloud (owc.py), then show the tables again."""
        from pysyzygos import owc
        if which == "results":
            path = os.path.join(ROOT, pg.config.hits_output_cvs_file)
            with open(path, newline="") if os.path.isfile(path) else open(os.devnull) as f:
                recs = list(csv.DictReader(f))
        else:
            recs = [f["record"] for f in favorites.load()]
        uniq = {owc.key(r): r for r in recs if str(r.get("target_id", "")).strip().isdigit() and r.get("best_utc")}
        if not uniq:
            ui.notify("No events to check", type="warning")
            return
        ui.notify(f"Checking {len(uniq)} event(s) in OccultWatcher Cloud (about {2 * len(uniq)} s) ...")
        found, n, errors = await run.io_bound(owc.check, list(uniq.values()), ROOT)
        for err in errors:                                      # which request failed and how (log and terminal)
            pg.log.push(f"OWC check failed: {err}")
            print(f"OWC check failed: {err}")
        ui.notify(f"OccultWatcher Cloud: {found} of {n} event(s) found"
                  + (f"; {len(errors)} failed: details in the Log at the bottom of the page" if errors else ""),
                  type="warning" if errors else "positive", multi_line=True)
        if which == "results":
            await pg.build_report()
        else:
            pg.load_favs(pg.fav_cur["key"])
    pg.owc_check = owc_check

    async def build_report(rc=0):
        where = (load_ui_state().get("sql_where") or "").strip()
        await run_process(PYSYZYGOS + ["report", pg.config.hits_output_cvs_file] + (["--where", where] if where else []),
                          pg.log)
        pg.frame.props(f"src=/out/hits_report.html?t={int(time.time())}")
        sql_show()
    pg.build_report = build_report

    # ------------------------------------------------ SQL filter
    def sql_show():
        where = (load_ui_state().get("sql_where") or "").strip()
        pg.sql_note.text = f"SQL filter active: {where}   (Clear in 'SQL filter' to show all events)" if where else ""

    async def sql_apply():
        where = (pg.sql_in.value or "").strip()
        if not where:
            return await sql_clear()
        try:
            n = len(await run.io_bound(db.where_keys, pg.results_db(), where))
        except ValueError as ex:
            ui.notify(f"SQL filter not usable: {ex}", type="negative", multi_line=True)
            return
        save_ui_state(sql_where=where)
        ui.notify(f"SQL filter: {n} event(s) of the current results list match", type="positive" if n else "warning")
        await pg.build_report()
    pg.sql_apply = sql_apply

    async def sql_from_bar(only_if_empty=False):
        """Fill the condition with the filter bar's settings in the report frame (db.filter_to_sql): a start for a
        custom condition. only_if_empty: leave a condition already written alone."""
        if only_if_empty and (pg.sql_in.value or "").strip():
            return
        try:
            spec = await ui.run_javascript(
                f"const f=getHtmlElement({pg.frame.id});const d=f&&f.contentDocument;const b=d&&d.getElementById('fbar');"
                "if(!b)return null;const s={},h=[],o=[];"
                "b.querySelectorAll('input[data-t]').forEach(i=>{if(i.value)s[i.dataset.t]=i.value;});"
                "b.querySelectorAll('input[data-f]').forEach(i=>{if(i.value!==''&&!isNaN(parseFloat(i.value)))s[i.dataset.f]=parseFloat(i.value);});"
                "b.querySelectorAll('input[data-h]').forEach(i=>{if(i.checked)h.push(i.dataset.h);});"
                "b.querySelectorAll('input[data-o]').forEach(i=>{if(i.checked)o.push(i.dataset.o);});"
                "s.hide=h;s.only=o;return s;", timeout=5.0)
        except Exception:
            spec = None
        sql = db.filter_to_sql(spec) if spec else ""
        if sql:
            pg.sql_in.value = sql
        elif not only_if_empty:
            ui.notify("The filter bar above the report has no settings (or the report is not shown yet)",
                      type="warning")
    pg.sql_from_bar = sql_from_bar

    async def sql_clear():
        pg.sql_in.value = ""
        save_ui_state(sql_where="")
        await pg.build_report()
    pg.sql_clear = sql_clear

    def sql_suggest(*_):
        """Field names starting with the word being typed, as buttons that complete it."""
        m = re.search(r"([A-Za-z_]+)$", pg.sql_in.value or "")
        word = m.group(1).lower() if m else ""
        pg.sql_sugg.clear()
        hits = [h for h in SQL_NAMES if word and h[0].startswith(word) and h[0] != word][:10]
        with pg.sql_sugg:
            for name, unit, meaning in hits:
                ui.button(name, on_click=lambda n=name: sql_complete(n)).props("dense flat no-caps size=sm").tooltip(
                    meaning + (f" ({unit})" if unit else ""))

    def sql_complete(name):
        txt = pg.sql_in.value or ""
        m = re.search(r"[A-Za-z_]*$", txt)                      # the word being typed (may be empty)
        pg.sql_in.value = txt[:m.start()] + name + " "

    def sql_insert(name):
        txt = (pg.sql_in.value or "").rstrip()
        pg.sql_in.value = (txt + " " + name + " ").lstrip()

    def sql_saved_refresh(select=None):
        q = load_ui_state().get("sql_queries") or {}
        pg.sql_saved.options = {k: k for k in sorted(q)}
        pg.sql_saved.value = select if select in q else None
        pg.sql_saved.update()

    def sql_pick(name):
        q = load_ui_state().get("sql_queries") or {}
        if name in q:
            pg.sql_in.value = q[name]
    pg.sql_pick = sql_pick

    def sql_save():
        where = (pg.sql_in.value or "").strip()
        if not where:
            ui.notify("Write a condition first", type="warning")
            return
        with ui.dialog() as dlg, ui.card():
            name = ui.input("Name of this condition", value=pg.sql_saved.value or "").classes("w-80")
            with ui.row():
                def ok():
                    n = (name.value or "").strip()
                    if not n:
                        return
                    q = dict(load_ui_state().get("sql_queries") or {}, **{n: where})
                    save_ui_state(sql_queries=q)
                    sql_saved_refresh(n)
                    dlg.close()
                    ui.notify(f"Condition '{n}' saved", type="positive")
                ui.button("Save", on_click=ok).props("color=primary")
                ui.button("Cancel", on_click=dlg.close).props("flat")
        dlg.open()
    pg.sql_save = sql_save

    def sql_delete():
        n = pg.sql_saved.value
        if not n:
            ui.notify("Choose a saved condition first", type="warning")
            return
        q = dict(load_ui_state().get("sql_queries") or {})
        q.pop(n, None)
        save_ui_state(sql_queries=q)
        sql_saved_refresh()
        ui.notify(f"Condition '{n}' deleted")
    pg.sql_delete = sql_delete
    pg.sql_suggest, pg.sql_insert, pg.sql_saved_refresh, pg.sql_show = sql_suggest, sql_insert, sql_saved_refresh, sql_show


def connect(pg):
    """Wire the tab up and fill it (run after all tabs' handlers)."""
    pg.sql_in.on_value_change(pg.sql_suggest)
    pg.sql_fields.on("rowClick", lambda e: pg.sql_insert(e.args[1]["name"]))
    pg.sql_saved_refresh()
    pg.sql_show()
    if os.path.isfile(os.path.join(ROOT, "hits_report.html")):        # the last report, at once (Rebuild: a new one)
        pg.frame.props(f"src=/out/hits_report.html?t={int(time.time())}")

    async def hits_csv():
        path = os.path.join(ROOT, pg.config.hits_output_cvs_file)
        if not os.path.isfile(path):
            ui.notify("No search results yet (run a search)", type="warning")
            return
        from pysyzygos import report
        run = report.read_last_run(path) or {}             # name it like the picks: site, window
        site, start = (run.get("site") or {}).get("name"), str(run.get("window_start") or "")[:10]
        name = (f"hits_{pg.picks._safe(site)}__{start}_{float(run['window_days']):g}d.csv"
                if site and start and run.get("window_days") else os.path.basename(path))
        rows, keys = exports.results_rows(pg.results_db(), "main"), await pg.shown_keys(pg.frame)
        shown = exports.only_shown(rows, keys)
        if keys is not None and not shown:
            ui.notify("No events shown (the filter hides them all): nothing to export", type="warning")
            return
        pg.download_csv("results", shown, name)
        ui.notify(f"CSV: {len(shown)} event(s)" + (" as shown (filter and sort order)" if keys is not None else
                                                   " (all: the report page could not be read)"))
    pg.hits_csv = hits_csv
