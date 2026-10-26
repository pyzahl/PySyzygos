"""gui_search.py - Search tab: the exact search of the picked targets (or a list) for the selected site and window.

Part of the GUI (gui.py builds the page): panel(pg) adds the tab's controls, handlers(pg) its functions, connect(pg)
wires them up; pg holds the page's elements and functions shared between the tabs.
"""
import json

from nicegui import ui
from pysyzygos.gui_common import PYSYZYGOS, run_process, stop_process, today_utc


def panel(pg):
    """The search tab's controls (inside its ui.tab_panel)."""
    with ui.tab_panel(pg.t_search):
        pg.site_note_s = ui.label().classes("text-sm text-slate-600")
        with ui.row().classes("items-end gap-4"):
            pg.s_start = ui.input("Start (UTC date)", value=today_utc()).props("type=date")
            pg.s_days = ui.number("Days", value=pg.config.days, min=1, step=1)
            pg.s_mag = ui.number("Star G limit", step=0.1, min=6, max=21).classes("w-28").tooltip(
                "Faintest star (Gaia G) searched. Default: from the site's telescope (aperture, detection frames, longest "
                "exposure, MagAdjust; Site tab), capped at the catalog's limit; change it for one run")
            ui.button("↺", on_click=lambda: pg.mag_reset("search")).props("flat dense").tooltip(
                "Back to the site's default star limit")
            pg.s_drop = ui.number("Min. drop (mag)", value=getattr(pg.config, "min_mag_drop", 0.1), step=0.05)
        pg.s_mag_note = ui.label().classes("text-xs text-slate-500")
        with ui.row().classes("items-center gap-2"):
            pg.s_scope = ui.toggle({"site": "At the site", "earth": "Anywhere on Earth"}, value="site",
                                   on_change=lambda e: pg.scope_changed()).props("dense no-caps")
            pg.s_scope_note = ui.label().classes("text-xs text-slate-500")
        pg.s_use_file = ui.switch("Targets from the saved pick of this site (Pick tab)", value=True).tooltip(
            "Uses the newest saved pick of the selected site whose window covers the search window; "
            "without one, targets.py or the list in pysyzygos_config.py")
        pg.targets_warn_s = ui.label().classes("text-sm w-full")
        pg.s_targets = ui.textarea("Targets (asteroid numbers, comma or space separated)",
                                   value=", ".join(pg.config.targets)).classes("w-full")
        with ui.row():
            pg.s_fresh = ui.checkbox("Start a fresh results list", value=True).tooltip(
                "On: the Results tab shows only this search (a new series in the results database; older "
                "results stay in pysyzygos.db). Off: add this search's events to the current list")
            pg.s_maps = ui.checkbox("KML maps", value=bool(pg.config.write_maps))
            pg.s_prev = ui.checkbox("Previews", value=bool(getattr(pg.config, "write_previews", True)))
        with ui.row().classes("items-center"):
            ui.label("Astrometric corrections of the star:").classes("text-sm text-slate-600")
            pg.s_plx = ui.checkbox("Stellar parallax", value=bool(getattr(pg.config, "star_parallax", True))).tooltip(
                "The star as seen from the Earth, not the Sun (Gaia parallax); up to several km on the path")
            pg.s_defl = ui.checkbox("Light deflection (Sun, Jupiter, Saturn)",
                                    value=bool(getattr(pg.config, "light_deflection", True))).tooltip(
                "Gravitational light bending, star minus asteroid; up to ~6 km away from opposition. "
                "Both off reproduce results before version 0.10.0")
            pg.s_dbl = ui.checkbox("Online Gaia check of the event stars",
                                   value=bool(getattr(pg.config, "gaia_online_check", True))).tooltip(
                "After the search, one query to the Gaia archive: Gaia's double-star hints for each event star, "
                "and close neighbours the local catalog leaves out. Close neighbours from the local catalog "
                "are always checked. Skipped when offline")
        with ui.row():
            ui.button("Run search", on_click=lambda: pg.run_search()).props("color=primary")
            ui.button("Stop", on_click=lambda: stop_process(pg.log)).props("outline color=negative")


def handlers(pg):
    """The search tab's functions and state, as attributes of pg."""
    async def run_search():
        if not pg.catalog_ok():
            return
        pg.ensure_saved()
        over = dict(ct=f"{pg.s_start.value}T00:00:00", days=int(pg.s_days.value), min_mag_drop=float(pg.s_drop.value),
                    **({"MAG_MIN": float(pg.s_mag.value)} if pg.s_mag.value else {}),
                    write_maps=bool(pg.s_maps.value), write_previews=bool(pg.s_prev.value),
                    star_parallax=bool(pg.s_plx.value), light_deflection=bool(pg.s_defl.value),
                    gaia_online_check=bool(pg.s_dbl.value))
        earth = pg.s_scope.value == "earth"
        if not pg.s_use_file.value or earth:
            over["targets"] = [t for t in pg.s_targets.value.replace(",", " ").split() if t]
            if earth and not over["targets"]:
                ui.notify("Anywhere on Earth: list the asteroids below", type="warning")
                return
        over["results_new_series"] = bool(pg.s_fresh.value)          # db.py: a fresh results list = a new series
        if earth:                                                    # every event whose shadow touches the Earth
            over.update(search_scope="earth", results_list="earth", hits_output_cvs_file="earth_log.csv",
                        max_shadow_dist=0.0)

        async def done(rc):
            if rc == 0:
                src = "earth" if earth else "site"
                if pg.res_src.value != src:
                    pg.res_src.value = src                           # (shows that list's last report)
                await pg.build_report()
                pg.tabs.value = pg.t_res
        await run_process(PYSYZYGOS + ["run", "search", json.dumps(over)], pg.log,
                          env_site=pg.state["name"], on_done=done, env_catalog=pg.cat_sel.value)
    pg.run_search = run_search

    def saved_info(*_):
        """Search tab: which saved pick the search will use for the selected site and window."""
        if pg.s_scope.value == "earth":
            pg.targets_warn_s.text = "Anywhere on Earth: the search uses the list below (a pick is per site)."
            pg.targets_warn_s.classes(replace="text-sm w-full text-slate-600")
            return
        if not pg.s_use_file.value:
            pg.targets_warn_s.text = "The search uses the list below."
            pg.targets_warn_s.classes(replace="text-sm w-full text-slate-600")
            return
        try:
            s = pg.sites.get(pg.state["name"], {})
            p = pg.picks.best_for(pg.state["name"], pg.s_start.value, float(pg.s_days.value or 1), pg.picks_dir, s.get("lat"), s.get("lon"))
        except ValueError:
            p = None
        if p:
            pg.targets_warn_s.text = f"The search uses the {pg.picks.describe(p)}." + (
                f" {pg.picks.warnings_text(p)}" if p.get("warnings") else "")
            pg.targets_warn_s.classes(replace="text-sm w-full " + ("text-orange-600 font-semibold" if p.get("warnings")
                                                                   else "text-slate-600"))
        else:
            pg.targets_warn_s.text = (f"No saved pick of site {pg.state['name']} covers this window: the search uses "
                                      f"targets.py or the config list. Run a pick for it (Pick tab) for better targets.")
            pg.targets_warn_s.classes(replace="text-sm w-full text-amber-700")
    pg.saved_info = saved_info

    def scope_changed():
        earth = pg.s_scope.value == "earth"
        pg.s_use_file.set_enabled(not earth)
        pg.s_scope_note.text = ("every event whose shadow touches the Earth, for the asteroids listed below, by day "
                                "or night: no site, Sun, altitude or reach limits; each event is described at its "
                                "center-line point (results list 'anywhere on Earth')" if earth else
                                "events the selected site can observe (its limits and reach)")
        pg.saved_info()
    pg.scope_changed = scope_changed


def connect(pg):
    """Wire the tab up and fill it (run after all tabs' handlers)."""
    for el in (pg.s_start, pg.s_days, pg.s_use_file):
        el.on_value_change(pg.saved_info)
    pg.scope_changed()
