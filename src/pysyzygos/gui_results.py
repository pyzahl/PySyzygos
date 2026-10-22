"""gui_results.py - Results tab: the report of the current results list, CSV download, OccultWatcher Cloud check.

Part of the GUI (gui.py builds the page): panel(pg) adds the tab's controls, handlers(pg) its functions; pg holds the
page's elements and functions shared between the tabs.
"""
import csv, os, time

from pysyzygos import exports, favorites
from pysyzygos.home import HOME as ROOT
from nicegui import run, ui
from pysyzygos.gui_common import KSTARS_OPT, PYSYZYGOS, resizable_box, run_process


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
                "Download the search results as a CSV table."
                " Columns: csv_exports.py in the data folder (default: as the table shows them; any log column can be added)")
            ui.checkbox("KStars/Stellarium: set its location to the event site", value=KSTARS_OPT["set_location"],
                        on_change=lambda e: KSTARS_OPT.update(set_location=bool(e.value))).tooltip(
                "The report's KStars buttons (Linux, KStars running) and Stellarium buttons (Remote Control "
                "plugin). Off: they keep their location (KStars tells you if that is far from the site).")
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
        await run_process(PYSYZYGOS + ["report", pg.config.hits_output_cvs_file], pg.log)
        pg.frame.props(f"src=/out/hits_report.html?t={int(time.time())}")
    pg.build_report = build_report

    def hits_csv():
        path = os.path.join(ROOT, pg.config.hits_output_cvs_file)
        if not os.path.isfile(path):
            ui.notify("No search results yet (run a search)", type="warning")
            return
        from pysyzygos import report
        run = report.read_last_run(path) or {}             # name it like the picks: site, window
        site, start = (run.get("site") or {}).get("name"), str(run.get("window_start") or "")[:10]
        name = (f"hits_{pg.picks._safe(site)}__{start}_{float(run['window_days']):g}d.csv"
                if site and start and run.get("window_days") else os.path.basename(path))
        pg.download_csv("results", exports.results_rows(pg.results_db(), "main"), name)
    pg.hits_csv = hits_csv
