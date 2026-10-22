"""gui_bodies.py - Planets & Moons tab: planets and their moons as targets (bodies.py), their own results list and
report.

Part of the GUI (gui.py builds the page): panel(pg) adds the tab's controls, handlers(pg) its functions; pg holds the
page's elements and functions shared between the tabs.
"""
import json, os, time

from pysyzygos import exports
from pysyzygos.home import HOME as ROOT
from nicegui import ui
from pysyzygos.gui_common import PYSYZYGOS, resizable_box, run_process, stop_process, today_utc


def panel(pg):
    """The bodies tab's controls (inside its ui.tab_panel)."""
    with ui.tab_panel(pg.t_bod):
        pg.site_note_b = ui.label().classes("text-sm text-slate-600")
        from pysyzygos import bodies as bodies_mod
        pg.bodies_mod = bodies_mod
        pg.b_checks, pg.b_small = {}, {}
        with ui.row().classes("items-start gap-6"):
            for grp in pg.bodies_mod.GROUPS:
                major, small = pg.bodies_mod.featured(grp)
                with ui.column().classes("gap-0"):
                    ui.label(f"{grp.capitalize()} system").classes("font-semibold")
                    for t in major:
                        kind = pg.bodies_mod.kind(t)
                        pg.b_checks[t] = ui.checkbox(f"{pg.bodies_mod.name(t)}" + (f" ({kind})" if kind != "moon" else ""),
                                                     value=(grp == "jupiter")).props("dense")
                    if small:
                        pg.b_small[grp] = ui.checkbox(f"smaller moons ({len(small)})", value=False).props(
                            "dense").tooltip(", ".join(pg.bodies_mod.name(t) for t in small[:40])
                                             + (" ..." if len(small) > 40 else "")
                                             + ": like small asteroids (faint, narrow paths, less certain orbits)")
            with ui.column().classes("gap-0"):
                ui.label("Coming").classes("font-semibold text-slate-400")
                ui.label("Earth's Moon").classes("text-sm text-slate-400")
        with ui.row().classes("items-end gap-4"):
            pg.b_start = ui.input("Start (UTC date)", value=today_utc()).props("type=date").classes("w-36")
            pg.b_days = ui.number("Days", value=30, min=1, step=1).classes("w-28")
            pg.b_mag = ui.number("Star G limit", step=0.1, min=6, max=21).classes("w-28").tooltip(
                "Faintest star (Gaia G) searched. Default: from the site's telescope (aperture, detection frames, longest "
                "exposure, MagAdjust; Site tab), capped at the catalog's limit; change it for one run. "
                "Planets have no drop limit (any star they cover disappears); moons also need the min. drop")
            ui.button("↺", on_click=lambda: pg.mag_reset("bodies")).props("flat dense").tooltip(
                "Back to the site's default star limit")
            pg.b_drop = ui.number("Moons: min. drop (mag)", value=getattr(pg.config, "min_mag_drop", 0.1),
                                  step=0.05).classes("w-36").tooltip(
                "Moons are bright (about mag 5 for Jupiter's): only bright stars give a measurable drop")
            pg.b_fresh = ui.checkbox("Start a fresh list", value=True)
        pg.b_mag_note = ui.label().classes("text-xs text-slate-500")
        with ui.row():
            ui.button("Run", on_click=lambda: pg.run_bodies()).props("color=primary")
            ui.button("Stop", on_click=lambda: stop_process(pg.log)).props("outline color=negative")
            ui.button("Rebuild report", on_click=lambda: pg.build_bodies_report()).props("outline")
            ui.link("Open in a new tab", "/out/bodies_report.html", new_tab=True).classes("self-center")
            ui.button("CSV", on_click=lambda: pg.bodies_csv()).props("outline dense").tooltip(
                "Download the events the table shows (its filter and sort order), with disappearance and reappearance times."
                " Columns: csv_exports.py in the data folder (default: as the table shows them; any log column can be added)")
        ui.label("Disappearance (D) and reappearance (R) at your site, from JPL Horizons positions (a small "
                 "kernel per window). The results are their own list (bodies_log.csv), apart from the asteroid "
                 "search.").classes("text-xs text-slate-500")
        with resizable_box("bodies", 60):
            pg.b_frame = ui.element("iframe").style("width: 100%; height: 100%; border: 0; display: block")


def handlers(pg):
    """The bodies tab's functions and state, as attributes of pg."""
    async def run_bodies():
        """Planets & Moons tab: search the ticked bodies (their own results list), then show their report."""
        if not pg.catalog_ok():
            return
        targets = [t for t, c in pg.b_checks.items() if c.value]
        for grp, c in pg.b_small.items():                  # a system's smaller moons, all at once
            if c.value:
                targets += pg.bodies_mod.featured(grp)[1]
        if not targets:
            ui.notify("Tick at least one body", type="warning")
            return
        pg.ensure_saved()
        over = dict(ct=f"{pg.b_start.value}T00:00:00", days=int(pg.b_days.value), targets=targets, targets_source="list",
                    results_list="bodies", hits_output_cvs_file="bodies_log.csv",
                    results_new_series=bool(pg.b_fresh.value),
                    min_mag_drop=float(pg.b_drop.value), gaia_online_check=False,
                    **({"MAG_MIN": float(pg.b_mag.value)} if pg.b_mag.value else {}))

        async def done(rc):
            if rc == 0:
                await pg.build_bodies_report()
        await run_process(PYSYZYGOS + ["run", "search", json.dumps(over)], pg.log,
                          env_site=pg.state["name"], on_done=done, env_catalog=pg.cat_sel.value)
    pg.run_bodies = run_bodies

    async def build_bodies_report(rc=0):
        if not os.path.isfile(os.path.join(ROOT, "bodies_log.csv")) and not os.path.isfile(
                os.path.join(ROOT, "bodies_log.runs.jsonl")):
            ui.notify("No planet or moon search yet", type="warning")
            return
        await run_process(PYSYZYGOS + ["report", "bodies_log.csv", "-o", "bodies_report.html", "--layout", "bodies"],
                          pg.log)
        pg.b_frame.props(f"src=/out/bodies_report.html?t={int(time.time())}")
    pg.build_bodies_report = build_bodies_report

    async def bodies_csv():
        path = os.path.join(ROOT, "bodies_log.csv")
        if not os.path.isfile(path):
            ui.notify("No planet or moon events yet", type="warning")
            return
        keys = await pg.shown_keys(pg.b_frame)
        shown = exports.only_shown(exports.results_rows(pg.results_db(), "bodies"), keys)
        if keys is not None and not shown:
            ui.notify("No events shown (the filter hides them all): nothing to export", type="warning")
            return
        pg.download_csv("bodies", shown, f"bodies_{today_utc()}.csv")
    pg.bodies_csv = bodies_csv
