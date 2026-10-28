"""gui.py - local web interface for PySyzygos (NiceGUI): set up observing sites on a map, run the search or the
pick tool, follow the log, look at the results.

    pysyzygos                            # opens http://127.0.0.1:8080 in the browser (same as: pysyzygos gui)
    pysyzygos --port 8090 --no-browser

It listens on this computer only (127.0.0.1), because it can start programs. Every run is its own process
(`python -m pysyzygos run ...`, pysyzygos/runner.py), so SPICE stays out of the GUI; settings chosen here apply to that run only, pysyzygos_config.py is
not changed. Saving a site rewrites sites.py (comments in it are not kept).

The page is built by index() here (header, dialogs, tabs, log) and the tab modules gui_site, gui_pick, gui_bodies,
gui_search, gui_results, gui_favorites and gui_system; gui_common holds what they share (runs, log files, GUI state).
"""
from pysyzygos.version import __version__, __codename__, __author__, __copyright__, __license__, __url__
import argparse, asyncio, json, os, sys
from types import SimpleNamespace

from pysyzygos import home
from pysyzygos.home import HOME as ROOT, PKG                      # ROOT: the data folder (sites.py, maps/, ...)
os.chdir(ROOT)
from nicegui import app, ui
from pysyzygos import geo
from pysyzygos import favorites
from pysyzygos import exports
from pysyzygos import starcat
from pysyzygos.sitesfile import load_sites
from pysyzygos import (gui_bodies, gui_favorites, gui_pick, gui_results, gui_search, gui_site,  # the tabs
                       gui_system)
from pysyzygos.gui_common import (HOOKS, Job, KSTARS_OPT, RESIZE_JS, SUPPLEMENT, catalog_options, load_ui_state,
                                  save_ui_state)


GUI_ARGS = {}                                                    # the options this GUI was started with (restart)


def _stop_job():
    for p in (Job.proc, Job.fav):
        if p is not None and p.returncode is None:
            try:
                p.terminate()
            except ProcessLookupError:
                pass


def quit_app():
    """End the program (GUI 'Quit'): stop a running job, then shut the server down."""
    ui.notify("PySyzygos is quitting: you can close this tab", type="warning", timeout=4000)
    _stop_job()
    asyncio.get_event_loop().call_later(1.0, app.shutdown)


def restart_app():
    """Start the same program again in this process (GUI 'Restart'): exec replaces it, with the same command line;
    the listening socket is closed on exec (Python sockets are not inherited), so the new server takes the port and
    the open page reconnects by itself."""
    ui.notify("PySyzygos restarts: this page reconnects in a few seconds", type="info", timeout=6000)
    _stop_job()

    def again():                                                # same port; no new browser tab: this one reconnects
        os.environ["PYSYZYGOS_HOME"] = ROOT
        os.execv(sys.executable, [sys.executable, "-m", "pysyzygos", "gui", "--port", str(GUI_ARGS.get("port", 8080)),
                                  "--no-browser"])
    asyncio.get_event_loop().call_later(1.0, again)


# ---------------------------------------------------------------- page
@ui.page("/")
def index():
    pg = SimpleNamespace()          # the page: its elements and functions, shared with the tab modules (gui_<tab>.py)
    from pysyzygos import config
    pg.config = config
    pg.sites, pg.default_site = load_sites()
    pg.last = load_ui_state()                                       # the site and catalog chosen last time
    pg.state = dict(name=pg.last["site"] if pg.last.get("site") in pg.sites else pg.default_site)
    ui.page_title("PySyzygos")
    ui.add_body_html(RESIZE_JS)                                  # resizable list boxes (resizable_box)
    with ui.header().classes("items-center bg-slate-800"):
        ui.element("img").props('src=/pysyzygos_logo.svg alt=""').classes("w-9 h-9")
        ui.label("PySyzygos").classes("text-xl font-semibold")
        ui.label(f"v{__version__}").classes("text-xs text-slate-400 self-end mb-1").tooltip(
            f"PySyzygos {__version__} \u201c{__codename__}\u201d")
        ui.label("asteroid occultation search").classes("text-slate-300")
        ui.space()
        ui.label("Site for all runs:").classes("text-slate-300")
        pg.sel = ui.select(list(pg.sites), value=pg.state["name"]).props("dark dense options-dense standout").classes("w-48")
        from pysyzygos import gaia_local
        pg.gaia_local = gaia_local
        found = pg.gaia_local.find_catalogs(ROOT)
        pg.complete = {d for d, g, ok, _ in found if ok}
        pg.cat_gmax = {d: float(g) for d, g, ok, _ in found if g is not None}
        cats = catalog_options(found)
        ui.label("Catalog:").classes("text-slate-300")
        pg.cat_sel = ui.select(cats, value=pg.last["catalog"] if pg.last.get("catalog") in pg.complete else
                               pg.config.gaia_local_dir if pg.config.gaia_local_dir in pg.complete else
                               (min(pg.complete) if pg.complete else (next(iter(cats)) if cats else None))
                               ).props("dark dense options-dense standout").classes("w-64").tooltip(
            "Local Gaia catalogs in the project folder. Install or add one with: pysyzygos setup [--gmax 16]")
        SUPPLEMENT["on"] = bool(pg.last.get("supplement", True))
        pg.sup_chk = ui.checkbox("+ high-RUWE stars", value=SUPPLEMENT["on"]).props("dark dense").classes(
            "text-slate-300")
        ui.button("About", on_click=lambda: pg.about.open()).props("flat dense color=white no-caps")
        ui.button(icon="power_settings_new", on_click=lambda: pg.quit_dialog()).props(
            "flat dense round color=white").tooltip("Restart or quit PySyzygos (the program, not only this page)")
    def quit_dialog():
        """Restart (the same program again: picks up an update, e.g. after git pull) or quit; for a GUI started from
        a launcher, where the process is not at hand."""
        busy = any(p is not None and p.returncode is None for p in (Job.proc, Job.fav))
        with ui.dialog() as qd, ui.card().classes("max-w-md"):
            ui.label("Restart or quit PySyzygos?").classes("font-semibold")
            ui.label("Restart: the program starts again (with any update you installed) and this page reconnects "
                     "by itself. Quit: the program ends; close this browser tab afterwards."
                     + (" A run is still going: it is stopped." if busy else "")).classes("text-sm")
            with ui.row():
                ui.button("Restart", on_click=lambda: (qd.close(), restart_app())).props("color=primary")
                ui.button("Quit", on_click=lambda: (qd.close(), quit_app())).props("color=negative")
                ui.button("Cancel", on_click=qd.close).props("flat")
        qd.open()
    pg.quit_dialog = quit_dialog
    pg.restart_app = restart_app

    with ui.dialog() as pg.about, ui.card().classes("max-w-xl"):
        with ui.row().classes("items-center gap-4 no-wrap"):
            ui.element("img").props('src=/pysyzygos_logo.svg alt=""').classes("w-20 h-20")
            with ui.column().classes("gap-0"):
                ui.label("PySyzygos").classes("text-2xl font-semibold")
                ui.label(f"Version {__version__} \u201c{__codename__}\u201d").classes("text-slate-600")
                ui.label(f"by {__author__}").classes("text-sm text-slate-600")
        ui.label("Asteroid occultation prediction for your observing sites: picks the events at your site from all "
                 "numbered asteroids, computes them exactly (JPL Horizons orbits, NAIF SPICE, a local Gaia DR3 "
                 "catalog), and shows shadow paths, star-field previews and whole-Earth plots. Every observed "
                 "event, positive or negative, adds to what we know about the sizes, shapes and orbits of the small "
                 "bodies of the Solar System.").classes("text-sm")
        ui.label("The name: Greek s\u00fdzygos (\u03c3\u03cd\u03b6\u03c5\u03b3\u03bf\u03c2), \u201cyoked together\u201d (syn "
                 "\u201ctogether\u201d, zyg\u00f3n \u201cyoke\u201d), the root of syzygy: three celestial bodies in a "
                 "straight line, as the observer, the asteroid and the star are during an occultation. Called PyOccult "
                 "up to version 0.18.").classes("text-sm mt-2")
        ui.label("Credits").classes("font-semibold mt-2")
        ui.label("Stars: ESA Gaia DR3 (Gaia/DPAC) \u00b7 orbits and sizes: JPL Horizons and Small-Body Database \u00b7 "
                 "planets and Earth orientation: NAIF SPICE (SpiceyPy), DE440 \u00b7 coastlines: Natural Earth \u00b7 "
                 "maps: OpenStreetMap contributors, Leaflet \u00b7 interface: NiceGUI \u00b7 also Astropy, astroquery, "
                 "NumPy, SciPy, pandas \u00b7 reference predictions: Occult (D. Herald) and Occult Watcher Cloud "
                 "(H. Pavlov) \u00b7 the IOTA community \u00b7 developed with the help of Claude (Anthropic) via "
                 "Claude Code. Full references: README.md.").classes("text-xs text-slate-600")
        ui.label(f"Data folder: {home.describe()}. Change it with: pysyzygos setup --home <folder>").classes(
            "text-xs text-slate-600 mt-2")
        ui.label(f"{__copyright__}. Free software under the GNU GPL v3 or later ({__license__}); no warranty. "
                 "Gaia data: CC BY-NC 3.0 IGO.").classes("text-xs text-slate-600 mt-2")
        with ui.row().classes("w-full items-center justify-between mt-2"):
            ui.link(__url__, __url__, new_tab=True).classes("text-sm")
            ui.button("Close", on_click=lambda: pg.about.close()).props("flat")
    with ui.tabs().classes("w-full") as pg.tabs:
        pg.t_site, pg.t_pick = ui.tab("Site"), ui.tab("Pick")
        pg.t_bod = ui.tab("Planets & Moons")
        pg.t_search, pg.t_res = ui.tab("Search"), ui.tab("Results")
        pg.t_fav = ui.tab("Favorites")
        pg.t_sys = ui.tab("System")
    pg.log_card = None

    with ui.tab_panels(pg.tabs, value=pg.t_site).classes("w-full"):
        gui_site.panel(pg)
        gui_search.panel(pg)
        gui_pick.panel(pg)
        gui_bodies.panel(pg)
        gui_results.panel(pg)
        gui_favorites.panel(pg)
        gui_system.panel(pg)

    with ui.card().classes("w-full") as pg.log_card:
        with ui.row().classes("w-full items-center"):
            ui.label("Log").classes("font-semibold")
            ui.button("Clear", on_click=lambda: pg.log.clear()).props("flat dense")
        pg.log = ui.log(max_lines=3000).classes("w-full h-64 text-xs")
        pg.steps_box = ui.column().classes("w-full gap-1")

    def show_steps(sm):
        """The run summary under the log: the steps of the last pick, search or pre-screen build."""
        pg.steps_box.clear()
        total = sm.get("total_s") or 0.0
        with pg.steps_box:
            with ui.row().classes("items-center gap-3"):
                ui.label(f"Run summary: {sm.get('tool', '')}, {total:.1f} s").classes("font-semibold")
                if sm.get("log"):
                    ui.label(f"full log: {sm['log']}").classes("text-xs text-slate-500")
                ui.button("Hide", on_click=pg.steps_box.clear).props("flat dense")
            rows = []
            for r in sm.get("steps", []):
                pct = 100.0 * r["s"] / total if total else 0.0
                rows.append(dict(step=("\u2003" if r.get("group") else "") + r["name"], s=f"{r['s']:.1f}",
                                 pct=f"{pct:.0f} %", bar="\u2588" * int(round(pct / 4)),
                                 n=(f"{r['n']} {r['unit']}".strip() if r.get("n") is not None else "")))
            cols = [dict(name="step", label="Step", field="step", align="left"),
                    dict(name="s", label="Time (s)", field="s", align="right"),
                    dict(name="pct", label="Share", field="pct", align="right"),
                    dict(name="bar", label="", field="bar", align="left", classes="text-amber-600"),
                    dict(name="n", label="Count", field="n", align="left")]
            ui.table(columns=cols, rows=rows, row_key="step").props("flat dense").classes("w-full text-xs")
    pg.show_steps = show_steps

    HOOKS["steps"] = pg.show_steps
    # the Favorites tab has its own log (its tasks only): the main one is not shown there
    pg.tabs.on_value_change(lambda e: pg.log_card.set_visibility(e.value not in (pg.t_fav, "Favorites")))
    pg.log_card.set_visibility(pg.tabs.value not in (pg.t_fav, "Favorites"))

    # every tab's functions and state (attributes of pg), then the wiring, in the order the tabs need it
    gui_site.handlers(pg)
    gui_search.handlers(pg)
    gui_pick.handlers(pg)
    gui_bodies.handlers(pg)
    gui_results.handlers(pg)
    gui_favorites.handlers(pg)
    gui_system.handlers(pg)

    def catalog_limit(*_):                                        # the catalog's limit caps the star limits
        pg.mag_apply()
    pg.catalog_limit = catalog_limit

    def supplement_state(*_):
        """The header switch: enabled when the selected catalog has a complete supplement (gaia_local)."""
        d = os.path.join(ROOT, pg.cat_sel.value) if pg.cat_sel.value else None
        have = bool(d and pg.gaia_local.has_supplement(d))
        pg.sup_chk.set_enabled(have)
        if d and starcat.is_format2(d):
            pg.sup_chk.tooltip("Also search the stars with Gaia RUWE >= 1.4 (often unresolved doubles) and the "
                               "2-parameter sources (no or a cross-matched proper motion). This catalog includes them; "
                               "they are flagged \u2691 in the results (position, and so the path, less certain).")
            return
        pg.sup_chk.tooltip("Also search the stars the main catalog leaves out: Gaia RUWE >= 1.4 (often unresolved "
                           "doubles) and 2-parameter sources (no proper motion). OWC predicts events on them; here they "
                           "are flagged \u2691 in the results (position, and so the path, less certain). "
                           + ("" if have else f"Not built for this catalog yet: pysyzygos gaia supplement --dir "
                                              f"{pg.cat_sel.value} --gmax 16 (about 2 h, ~0.3 GB)"))
    pg.supplement_state = supplement_state

    def supplement_change(e):
        SUPPLEMENT["on"] = bool(e.value)
        save_ui_state(supplement=bool(e.value), catalog=pg.cat_sel.value, site=pg.state["name"])
        pg.prescreen_options()
    pg.supplement_change = supplement_change

    def catalog_ok():
        """Runs need a complete catalog: tell the user how to get one otherwise."""
        if pg.cat_sel.value in pg.complete:
            return True
        ui.notify(("No complete Gaia catalog yet" if not pg.cat_sel.value else f"Catalog {pg.cat_sel.value} is incomplete")
                  + ": run  pysyzygos setup  (it resumes), then restart the GUI", type="warning", timeout=10000)
        return False
    pg.catalog_ok = catalog_ok

    def results_db():
        return os.path.join(ROOT, getattr(pg.config, "results_db", "pysyzygos.db"))
    pg.results_db = results_db

    async def shown_keys(frame):
        """The event keys of the rows the report page in this iframe shows, top to bottom (report.event_key), or
        None if the page cannot be read (not loaded yet): the CSV downloads export what is shown."""
        try:
            return await ui.run_javascript(
                f"const f=getHtmlElement({frame.id});const d=f&&f.contentDocument;if(!d)return null;"
                "const r=[...d.querySelectorAll('table tbody tr[data-ev]')];if(!r.length&&!d.querySelector('table'))"
                "return null;return r.filter(x=>x.style.display!=='none').map(x=>x.dataset.ev);", timeout=5.0)
        except Exception:
            return None
    pg.shown_keys = shown_keys

    def download_csv(kind, rows, name):
        """A CSV download with the columns of csv_exports.py (data folder) for this table."""
        folder = os.path.join(pg.config.cache_path, "pysyzygos_exports")
        os.makedirs(folder, exist_ok=True)
        try:
            exports.write(kind, rows, os.path.join(folder, name), home=ROOT)
        except Exception as ex:                                  # a broken csv_exports.py: say so
            ui.notify(f"CSV export failed ({type(ex).__name__}: {ex}); check csv_exports.py in the data folder",
                      type="negative", timeout=10000)
            return
        ui.download(os.path.join(folder, name), name)
    pg.download_csv = download_csv

    gui_site.connect(pg)

    pg.sel.on_value_change(lambda e: pg.switch_site(e.value) if e.value in pg.sites else None)   # asks first if unsaved

    pg.cat_sel.on_value_change(pg.catalog_limit)
    pg.cat_sel.on_value_change(lambda e: save_ui_state(catalog=e.value, site=pg.state["name"]) if e.value else None)

    pg.sup_chk.on_value_change(pg.supplement_change)
    pg.cat_sel.on_value_change(pg.supplement_state)
    pg.supplement_state()
    pg.show_site(pg.state["name"])

    gui_search.connect(pg)
    gui_pick.connect(pg)
    gui_system.connect(pg)
    gui_results.connect(pg)
    gui_favorites.connect(pg)


def local_star_names(config):
    """lookup(record) for favorites.backfill_names: the star's UCAC4 / TYC / HIP names from a local catalog with the
    xref part: the one selected in the GUI header, else the config's, else any other; None for every record when no
    catalog has it."""
    from pysyzygos import gaia_local, starcat
    state = {}

    def with_xref():
        names = [load_ui_state().get("catalog"), config.gaia_local_dir] + sorted(
            f for f in os.listdir(ROOT) if f.startswith("gaia_dr3_") and not f.endswith((".old", ".new")))
        for n in names:
            d = os.path.join(ROOT, n) if n else None
            try:
                if d and starcat.is_format2(d) and starcat.group_ok(d, "xref"):
                    return gaia_local.LocalGaia(d)
            except Exception:
                continue
        return None

    def lookup(r):
        if "cat" not in state:
            try:
                c = with_xref()
                state["cat"] = c if getattr(c, "xref", None) is not None else None
            except Exception:
                state["cat"] = None
        c = state["cat"]
        if c is None:
            return None
        try:
            return c.names(int(str(r.get("star")).split(".")[0]), float(r["star_ra"]), float(r["star_dec"])) or \
                dict(star_ucac4="", star_tyc="", star_hip="")
        except (KeyError, TypeError, ValueError):
            return None
    return lookup


def local_double_check(config):
    """check(record) for favorites.backfill_doubles: the close/double-star check (doubles.py) from the local catalog,
    without SPICE; None for every record when no complete catalog is there."""
    from pysyzygos import doubles, gaia_local
    state = {}

    def check(r):
        if "local" not in state:
            try:
                state["local"] = gaia_local.LocalGaia(config.gaia_local_dir)
            except Exception:                                    # no or incomplete catalog: try again next start
                state["local"] = None
        local = state["local"]
        try:
            ra, dec, g, et = (float(r[k]) for k in ("star_ra", "star_dec", "mag", "best_et"))
            m_ast = float(r.get("m_ast")) if str(r.get("m_ast", "")) not in ("", "nan", "None") else None
        except (KeyError, TypeError, ValueError):
            return None
        if local is None:
            return None
        rad = float(getattr(config, "companion_radius_arcsec", 4.0))
        years = 2000.0 + et / (365.25 * 86400) - doubles.GAIA_EPOCH
        comps = doubles.companions(local.cone(ra, dec, (rad + 3.0) / 3600.0), int(str(r["star"]).split(".")[0]), ra, dec, g,
                                   years, rad)
        return doubles.fields(comps, g, m_ast, "local")
    return check


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=f"PySyzygos {__version__}")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()
    GUI_ARGS.update(port=a.port)
    print(f"PySyzygos {__version__}, data folder: {home.describe()}")
    from pysyzygos import config
    os.makedirs(config.map_dir, exist_ok=True)
    app.add_static_files("/out/maps", os.path.join(ROOT, config.map_dir), max_cache_age=0)
    app.add_static_file(local_file=os.path.join(PKG, "pysyzygos_logo.svg"), url_path="/pysyzygos_logo.svg")
    from pysyzygos import kstars                                      # report's KStars buttons (Linux; hidden elsewhere)
    from pysyzygos import stellarium                                  # report's Stellarium buttons (any system)
    os.makedirs(os.path.join(ROOT, favorites.DIR), exist_ok=True)
    from pysyzygos import sbdb                                        # full SBDB data (shape, rotation) for older favorites
    favorites.backfill_phys(lambda t: sbdb.get_full(t, config.cache_path))
    favorites.backfill_globes(config.map_dir)                   # globe plots of later searches for older favorites
    favorites.backfill_doubles(local_double_check(config))      # close/double stars for favorites added before
    favorites.backfill_names(local_star_names(config))          # UCAC4 / TYC / HIP names (catalog part xref)
    favorites.backfill_timezones(geo.timezone)                  # site time zones (online, once per site)
    favorites.backfill_event()                                  # OWC-style event data for older favorites (Horizons)
    import threading                                            # error ellipses (Horizons, one Gaia job): may be slow
    threading.Thread(target=favorites.backfill_errors, daemon=True).start()
    favorites.write_csv()
    from pysyzygos import report as _report                     # the shadow distance shown (System tab)
    _report.DISTANCE = load_ui_state().get("shadow_distance") or "ground"
    favorites.write_page()                                      # with this version's page code (filter bar, sorting)
    app.add_static_files("/fav", os.path.join(ROOT, favorites.DIR), max_cache_age=0)

    @app.get("/api/favorites/keys")
    def favorites_keys():
        return {"keys": favorites.keys(), "edited": favorites.edited()}

    @app.get("/api/favorites/update")
    def favorites_update(keys: str, status: str):
        ok, msg = favorites.update_many([k for k in keys.split(",") if k], status=status)
        favorites.write_page()
        return {"ok": ok, "msg": msg}

    @app.get("/api/favorites/remove")
    def favorites_remove(keys: str):
        ok, msg = favorites.remove_many([k for k in keys.split(",") if k])
        favorites.write_page()
        return {"ok": ok, "msg": msg}

    @app.get("/api/favorites/cleanup")
    def favorites_cleanup():
        ok, msg = favorites.cleanup()
        favorites.write_page()
        return {"ok": ok, "msg": msg}

    @app.get("/api/favorites/add")
    def favorites_add(tid: str, utc: str):
        from pysyzygos import config as cfg, report, db
        con = db.connect(os.path.join(ROOT, getattr(cfg, "results_db", db.DEFAULT)))
        try:                                                # any results list (asteroids, planets & moons)
            rec, run = db.find_event_run(con, tid, utc[:16])
        finally:
            con.close()
        if rec is None:                                     # an older log without the database
            rec, run = favorites.find_record(cfg.hits_output_cvs_file, tid, utc), report.read_last_run(cfg.hits_output_cvs_file)
        if rec is None:
            return {"ok": False, "msg": f"event {tid} {utc[:19]} not found in the results"}
        from pysyzygos import sbdb
        rec = {k: db._cell(v) for k, v in rec.items()}       # as a hit-log row ('' for none/NaN, as the export)
        ok, msg = favorites.add(rec, run, cfg.map_dir, sbdb=sbdb.get_full(tid, cfg.cache_path))
        if ok:
            favorites.backfill_timezones(geo.timezone)          # the new favorite's site time zone (once per site)
        favorites.write_page()
        return {"ok": ok, "msg": msg}

    # named filter sets of the report pages (report.filter_bar), shared by Results, Favorites, Planets & Moons
    @app.get("/api/filters")
    def filters_list():
        return {"ok": True, "sets": load_ui_state().get("filters") or {}}

    @app.get("/api/filters/save")
    def filters_save(name: str, spec: str):
        try:
            data = json.loads(spec)
            assert isinstance(data, dict)
        except (ValueError, AssertionError):
            return {"ok": False, "msg": "filter set not saved: not a filter"}
        name = name.strip()[:60]
        if not name:
            return {"ok": False, "msg": "filter set not saved: no name"}
        sets = dict(load_ui_state().get("filters") or {}, **{name: data})
        save_ui_state(filters=sets)
        return {"ok": True, "msg": f"filter set {name} saved"}

    @app.get("/api/filters/delete")
    def filters_delete(name: str):
        sets = dict(load_ui_state().get("filters") or {})
        sets.pop(name, None)
        save_ui_state(filters=sets)
        return {"ok": True, "msg": f"filter set {name} deleted"}

    @app.get("/api/kstars/status")
    def kstars_status():
        ok, msg = kstars.available()
        return {"ok": ok, "msg": msg}

    @app.get("/api/kstars/show")
    def kstars_show(ra: float, dec: float, utc: str, fov: float = 2.0, lat: float = None, lon: float = None,
                    ele: float = 0.0, names: str = ""):
        ok, msg = kstars.show(ra, dec, utc, fov, lat, lon, ele, set_location=KSTARS_OPT["set_location"],
                              names=[n for n in names.split("|") if n])
        return {"ok": ok, "msg": msg}

    @app.get("/api/stellarium/show")
    def stellarium_show(ra: float, dec: float, utc: str, fov: float = 2.0, lat: float = None, lon: float = None,
                        ele: float = 0.0, names: str = ""):
        tz = site_timezone(lat, lon) if KSTARS_OPT["set_location"] and lat is not None and lon is not None else None
        ok, msg = stellarium.show(ra, dec, utc, fov, lat, lon, ele, set_location=KSTARS_OPT["set_location"], tz=tz,
                                  names=[n for n in names.split("|") if n])
        return {"ok": ok, "msg": msg}

    TZ_CACHE = {}

    def site_timezone(lat, lon):
        """IANA time zone at a site: from a favorite at the same place (looked up before), else Open-Meteo once."""
        key = (round(float(lat), 3), round(float(lon), 3))
        if key not in TZ_CACHE:
            tz = next((e["site"]["tz"] for e in favorites.load() if (e.get("site") or {}).get("tz")
                       and abs(float(e["site"].get("lat", 99)) - lat) < 1e-3
                       and abs(float(e["site"].get("lon", 999)) - lon) < 1e-3), None)
            tz = tz or geo.timezone(lat, lon)
            if not tz:
                return None                                  # offline: try again next time
            TZ_CACHE[key] = tz
        return TZ_CACHE[key]
    app.add_static_file(local_file=os.path.join(ROOT, "hits_report.html"), url_path="/out/hits_report.html",
                        strict=False, max_cache_age=0)
    app.add_static_file(local_file=os.path.join(ROOT, "bodies_report.html"), url_path="/out/bodies_report.html",
                        strict=False, max_cache_age=0)
    for name in ("earth_report.html", "observed_report.html"):        # the Results tab's other sources
        app.add_static_file(local_file=os.path.join(ROOT, name), url_path=f"/out/{name}", strict=False, max_cache_age=0)
    # always the decimal point: Firefox formats number fields by the page's language (German: "45,12345"), while the
    # values, logs and reports are Python's "45.12345". The page declares English before it is drawn, and every number
    # field carries lang="en" itself (so a browser translation or add-on cannot change it either)
    ui.add_head_html("<script>document.documentElement.lang = 'en';</script>", shared=True)
    ui.number.default_props("lang=en")
    ui.run(host="127.0.0.1", port=a.port, title="PySyzygos", favicon=os.path.join(PKG, "pysyzygos_logo.svg"),
           show=not a.no_browser, reload=False, reconnect_timeout=60, language="en-US")   # a busy browser keeps its page


if __name__ in {"__main__", "__mp_main__"}:
    main()
