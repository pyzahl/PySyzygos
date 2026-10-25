"""gui_pick.py - Pick tab: the event finder over all asteroids for the selected site and window, the saved picks and the
pre-screens (build, download shared ones, delete).

Part of the GUI (gui.py builds the page): panel(pg) adds the tab's controls, handlers(pg) its functions, connect(pg)
wires them up; pg holds the page's elements and functions shared between the tabs.
"""
import csv, os

from pysyzygos import exports
from pysyzygos.home import HOME as ROOT
from nicegui import background_tasks, run, ui
from pysyzygos.gui_common import (
    PRE_FIXED, PYSYZYGOS, SUPPLEMENT, _day_et, load_ui_state, prescreen_regions, resizable_box, run_process, save_ui_state,
    stop_process, today_utc)


def panel(pg):
    """The pick tab's controls (inside its ui.tab_panel)."""
    with ui.tab_panel(pg.t_pick):
        pg.site_note_p = ui.label().classes("text-sm text-slate-600")
        with ui.row().classes("items-end gap-4"):
            pg.p_start = ui.input("Start (UTC date)", value=today_utc()).props("type=date").classes("w-36")
            pg.p_days = ui.number("Days", value=pg.config.days, min=1, step=1).classes("w-28")
            pg.p_mag = ui.number("Star G limit", step=0.1, min=6, max=21).classes("w-28").tooltip(
                "Faintest star (Gaia G) searched. Default: from the site's telescope (aperture, detection "
                "frames, longest exposure, MagAdjust; Site tab), capped at the catalog's limit; change it for one "
                "pick run. Above G 15 the first pick builds a deeper star index once (a few minutes)")
            ui.button("↺", on_click=lambda: pg.mag_reset("pick")).props("flat dense").tooltip(
                "Back to the site's default star limit")
            pg.p_hmax = ui.number("H below", value=getattr(pg.config, "pick_hmax", 17.0), step=0.5).classes(
                "w-28").tooltip(
                "Only asteroids with H below this are screened (fainter H = smaller asteroids; more asteroids "
                "take longer). An asteroid with a larger H is never found by the pick, but the search finds it if "
                "you enter its number")
            pg.p_all = ui.checkbox("All numbered (slow)")
            pg.p_top = ui.number("Targets (top)", value=40, min=1, step=5).classes("w-28")
            pg.p_workers = ui.number("Workers", value=max(1, (os.cpu_count() or 2) // 2), min=1, step=1).classes(
                "w-28")
            pg.p_sort = ui.select(["mag", "date", "margin", "drop"], value="mag", label="Rank by").classes("w-28")
            pg.p_pre = ui.select(dict(PRE_FIXED), value="auto", label="Asteroids").classes("w-80").tooltip(
                "auto: if a pre-screen fits (its region holds the site, its window this pick's window, its limits "
                "are as loose), only its asteroids are screened: the same events, much faster; else all. "
                "all: every asteroid, for any place and time (slower, no pre-screen needed). "
                "Or one pre-screen by name (listed if it fits)")
        pg.p_mag_note = ui.label().classes("text-xs text-slate-500")
        # asteroid groups by JPL's orbit class: ticked = screened (picks.GROUPS); remembered (gui_state pick_groups);
        # a semi-major-axis range, inside or (exclude) outside; the bands table fills the range
        from pysyzygos.picks import GROUP_NAMES
        st = load_ui_state()
        saved = set(st.get("pick_groups") or GROUP_NAMES)
        with ui.column().classes("w-full gap-1 border rounded p-3"):
            ui.label("Which asteroids to screen").classes("font-semibold text-sm")
            ui.label("By JPL's orbit class (ticked = screened): Main belt = MBA, IMB (with the Hungarias) and OMB (with "
                     "the Hildas); NEO = Apollo, Amor, Aten, Atira; Everything else = Centaurs and the rest. Unticking "
                     "the main belt leaves ~25,000 of ~900,000 numbered asteroids (~15,000 below H 17): the high-value "
                     "targets in seconds, also with faint stars (raise the Star G limit up to the catalog's). Most NEOs "
                     "are smaller than H 17: raise 'H below' for them. The semi-major axis a narrows the choice "
                     "further, inside the range or (exclude) outside it; empty fields: no limit. Click a band below to "
                     "use its range.").classes("text-xs text-slate-600")
            au = lambda x: f"{x:.2f}".rstrip("0").rstrip(".") + (".0" if x == int(x) else "")    # 2.0, 1.78
            bands = [("Hungarias", 1.78, 2.0), ("Inner main belt", 2.0, 2.5), ("Middle main belt", 2.5, 2.82),
                     ("Outer main belt", 2.82, 3.3), ("Cybeles", 3.3, 3.7), ("Hildas", 3.7, 4.2),
                     ("Jupiter Trojans", 5.0, 5.4)]
            pg.p_bands = ui.table(columns=[dict(name="band", label="Band", field="band", align="left"),
                                           dict(name="a", label="a (AU)", field="a", align="left")],
                                  rows=[dict(band=b, a=f"{au(lo)} - {au(hi)}", lo=lo, hi=hi) for b, lo, hi in bands],
                                  row_key="band").props("dense flat").classes("text-xs w-96")
            pg.p_bands.on("rowClick", lambda e: pg.band_pick(e.args[1]))
            ui.label("A guide: families are better defined with e and i too.").classes("text-xs text-slate-500")
            with ui.row().classes("items-center gap-3"):
                ui.label("Asteroid groups:").classes("text-sm text-slate-600")
                pg.p_groups = {k: ui.checkbox(n, value=k in saved, on_change=lambda e: pg.groups_changed()).props("dense")
                               for k, n in GROUP_NAMES.items()}
            with ui.row().classes("items-center gap-3"):
                ui.label("Semi-major axis:").classes("text-sm text-slate-600")
                pg.p_aexcl = ui.checkbox("exclude this range", value=bool(st.get("pick_a_exclude")),
                                         on_change=lambda e: pg.groups_changed()).props("dense")
                pg.p_amin = ui.number("a from (AU)", value=st.get("pick_a_min"), step=0.1, min=0).classes("w-28").props(
                    "dense clearable")
                pg.p_amax = ui.number("a to (AU)", value=st.get("pick_a_max"), step=0.1, min=0).classes("w-28").props(
                    "dense clearable")
                for el in (pg.p_amin, pg.p_amax):
                    el.on_value_change(lambda e: pg.groups_changed())
            pg.p_count = ui.label("").classes("text-sm font-semibold text-slate-700")
        with ui.row().classes("items-center"):
            ui.button("Run pick", on_click=lambda: pg.run_pick()).props("color=primary")
            ui.button("Stop", on_click=lambda: stop_process(pg.log)).props("outline color=negative")
            pg.pre_info = ui.label().classes("text-sm text-slate-600")
        with ui.expansion("Pre-screens: build once for a region and window, then picks there are fast",
                          icon="speed").classes("w-full border rounded"):
            ui.label("A pick screens every asteroid (~465k) against the stars for your site, which takes many "
                     "minutes for a few weeks. A pre-screen does the site-independent part once for a region and a "
                     "window (about 1-2 hours for 20 days, 4 workers) and keeps only the asteroids with possible "
                     "events there; every later pick of a site inside that region and window ('Asteroids: auto') "
                     "then screens only those (a pick then takes seconds). Build it for the next weeks, around all your "
                     "sites, or for the whole Earth (same build time, bigger file: any site, also later ones); "
                     "rebuild after a few weeks (orbits are those of the build day). Uses the H limit and workers above; star limit "
                     "at least G 16; loose limits (reach 200 km, Sun below 0, star above 0). Stop saves; the same "
                     "build again resumes.").classes("text-sm text-slate-600")
            with ui.row().classes("items-end gap-4"):
                pg.ps_start = ui.input("Start (UTC date)", value=today_utc()).props("type=date").classes("w-36")
                pg.ps_days = ui.number("Days", value=30, min=1, step=1).classes("w-24")
                pg.ps_where = ui.select(prescreen_regions(), value="sites", label="Region").classes(
                    "w-60").tooltip(
                    "Around this site / all my sites: a box this many km around them (Box). A named region: its "
                    "lat/lon box (Box not used). Whole Earth stores the shadow's path of every event (~1 GB per "
                    "month at G 16, less with a brighter star limit), so a pick at any site tests it in seconds; "
                    "command line: 'pysyzygos prescreen extract' cuts a region file from it")
                pg.ps_km = ui.number("Box (km)", value=300, min=50, step=50).classes("w-28").tooltip(
                    "The region is a latitude/longitude box (a rectangle on the map, not a circle): this many km "
                    "north, south, east and west of the site (around all sites: of every site, at least this "
                    "far everywhere). Around one site the poleward edge is a little narrower in km (about 465 of "
                    "500 km at 41 N). Events count if the shadow path comes within the asteroid's radius + 200 km "
                    "(reach) of the box, so the effective region is the box widened by 200 km or more")
                pg.ps_where.on_value_change(lambda e: pg.ps_km.set_visibility(e.value in ("site", "sites")))
                pg.ps_fresh = ui.checkbox("Start over").tooltip(
                    "Discard a stopped build of the same name and window instead of resuming it (needed when "
                    "the build format changed after an update)")
                ui.button("Build pre-screen", on_click=lambda: pg.run_prescreen()).props("outline")
                ui.button("Delete selected", on_click=lambda: pg.delete_prescreens()).props(
                    "flat dense color=negative")
                ui.button("Download shared", on_click=lambda: pg.prescreen_shared()).props("outline dense").tooltip(
                    "Whole-Earth pre-screens shared on the mirror (built by other users of PySyzygos): list them "
                    "and download one instead of building it (about 1.5 GB for 40 days at G 16; any site)")
            ps_cols = [dict(name=k, label=lbl, field=k, sortable=True, align="left") for k, lbl in
                       (("name", "Name"), ("window", "Window"), ("region", "Region"), ("sites", "Sites inside"),
                        ("limits", "For picks up to"), ("found", "Asteroids / events"), ("age", "Built"), ("fits", "This pick"))]
            pg.ps_table = ui.table(columns=ps_cols, rows=[], row_key="path", selection="multiple").classes(
                "w-full").props("flat dense")
            ui.label("'For picks up to': a pre-screen keeps every event a pick with these or stricter limits can "
                     "find (fainter stars, a larger reach or H would need events it left out). Reach is the "
                     "observer's travel distance across the shadow path; a whole-Earth pre-screen has no region, "
                     "only these limits. 'This pick' says why one does not fit.").classes("text-xs text-slate-500")
        with ui.row().classes("w-full items-center gap-4"):
            pg.p_saved = ui.select({}, label="Saved picks of this site").classes("w-96")
            ui.button("Use for search", on_click=lambda: pg.use_saved()).props("outline").tooltip(
                "Set the search window to this pick's window and go to the Search tab")
            ui.button("Reload", on_click=lambda: pg.load_pick()).props("flat dense")
            ui.button("CSV", on_click=lambda: pg.pick_csv()).props("outline dense").tooltip(
                "Download the selected pick's events as a CSV table."
                " Columns: csv_exports.py in the data folder (default: as the table shows them; any log column can be added)")
        pg.pick_info = ui.label().classes("text-sm text-slate-600 w-full")
        pg.targets_info = ui.label().classes("text-sm text-slate-600 w-full")
        cols = [dict(name=k, label=lbl, field=k, sortable=True, align="left") for k, lbl in
                (("target", "Target"), ("number", "#"), ("name", "Asteroid"), ("H", "H"), ("utc", "UT"),
                 ("star_mag", "G"), ("drop", "Drop"), ("dur_s", "Dur (s)"), ("mag_margin", "Margin"),
                 ("miss_km", "Miss (km)"), ("star_alt", "Alt"))]
        with resizable_box("pick", 55, scroll=True):                # drag the corner to resize (remembered)
            pg.p_table = ui.table(columns=cols, rows=[], row_key="key", pagination=0).classes("w-full").props(
                "flat dense")


def handlers(pg):
    """The pick tab's functions and state, as attributes of pg."""
    def show_saved(*_):
        """Pick tab: show the events of the selected saved pick."""
        p = next((p for p in pg.saved_list if p["py"] == pg.p_saved.value), None)
        rows = []
        if p is None:
            pg.pick_info.text = f"No saved pick for site {pg.state['name']} yet: run a pick."
            pg.targets_info.text = ""
        else:
            if os.path.isfile(p["csv"]):
                with open(p["csv"]) as f:
                    rows = list(csv.DictReader(f))
            rows = [dict(exports.pick_shown(r, p["targets"]), key=f"{r.get('number')}_{r.get('utc')}") for r in rows]
            pg.pick_info.text = f"{pg.picks.describe(p)}: {len(rows)} events ({p['csv']})"
            pg.targets_info.text = ("Targets: " + ", ".join(p["targets"][:60]) + (" ..." if len(p["targets"]) > 60 else ""))
        pg.p_table.rows = rows
        return len(rows)
    pg.show_saved = show_saved

    def load_pick(select=None):
        """Fill the list of saved picks of the selected site (newest window first) and show one. Returns #events."""
        pg.saved_list[:] = pg.picks.list_for(pg.state["name"], pg.picks_dir)
        pg.p_saved.options = {p["py"]: f"{p['start']} + {p['days']:g} d · {len(p['targets'])} targets · picked "
                                       f"{p['picked'][:16].replace('T', ' ') or '?'}" for p in pg.saved_list}
        pg.p_saved.update()
        keep = select or pg.p_saved.value
        pg.p_saved.value = keep if keep in pg.p_saved.options else (pg.saved_list[0]["py"] if pg.saved_list else None)
        n = pg.show_saved()
        pg.saved_info()
        return n
    pg.load_pick = load_pick

    def prescreen_options(*_):
        """Pick tab: the Asteroids choices (auto, all, the pre-screens that fit this site and window), the line saying
        what the pick will screen, and the pre-screens table."""
        from pysyzygos import prescreen as PS
        opts, rows, fit = dict(PRE_FIXED), [], []
        s = pg.sites.get(pg.state["name"], {})
        try:
            t0 = _day_et(pg.p_start.value)
            t1 = t0 + float(pg.p_days.value or 1) * 86400
            want = dict(cam_limit=float(pg.p_mag.value or 0), hmax=None if pg.p_all.value else float(pg.p_hmax.value or 17),
                        hmax_all=bool(pg.p_all.value),
                        supplement=bool(SUPPLEMENT["on"] and pg.cat_sel.value
                                        and pg.gaia_local.has_supplement(os.path.join(ROOT, pg.cat_sel.value))))
            files = PS.list_files(os.path.join(ROOT, PS.DIR))
        except Exception:
            files, t0, t1, want = [], 0, 0, {}
        for path, m in files:
            m = dict(m, et0=_day_et(m["start"]), et1=_day_et(m["start"]) + m["days"] * 86400)
            bad = PS.check(m, t0, t1, s.get("lat", 0), s.get("lon", 0), want) if s.get("lat") is not None else ["no site"]
            if not bad:
                opts[path] = "pre-screen " + PS.describe(path, m)
                fit.append((m.get("built", ""), path, m))
            reg = m.get("region")
            inside = ["all (site test)"] if not reg else \
                [n for n, v in pg.sites.items() if "lat" in v and PS.contains(m, v["lat"], v["lon"])]
            try:
                n_ev, n_ast = PS.counts(path)
            except Exception:
                n_ev = n_ast = "?"
            age = PS.age_days(m)
            rows.append(dict(path=path, name=m.get("name", "?"),
                             window=f"{m['start']} + {m['days']:g} d",
                             region="whole Earth" if not reg else f"lat {reg['lat_min']:.0f}..{reg['lat_max']:.0f}, "
                                                                  f"lon {reg['lon_min']:.0f}..{reg['lon_max']:.0f}",
                             sites=", ".join(inside) or "-",
                             limits=f"G \u2264 {m['cam_limit']:g}, H < {m.get('hmax')}"
                                    + (f", reach \u2264 {m['reach_km']:g} km" if reg else ""),
                             found=f"{n_ast} / {n_ev}",
                             age="?" if age is None else (f"{age:.0f} d ago" + (" (old: rebuild)" if age > 30 else "")),
                             fits="fits" if not bad else "; ".join(bad)))
        pg.p_pre.options = opts
        if pg.p_pre.value not in opts:
            pg.p_pre.value = "auto"
        pg.p_pre.update()
        pg.ps_table.rows = rows
        pg.ps_table.update()
        if pg.p_pre.value == "all":
            pg.pre_info.text = "Screens all asteroids (any place and time; slower)."
        elif fit:
            _, path, m = max(fit, key=lambda x: x[0]) if pg.p_pre.value == "auto" else \
                next(x for x in fit if x[1] == pg.p_pre.value)
            pg.pre_info.text = f"Screens only the asteroids of pre-screen {os.path.basename(path)} (fast)."
        else:
            pg.pre_info.text = ("No pre-screen fits this site and window: screens all asteroids (slower). "
                                "Build one below for fast picks.")
    pg.prescreen_options = prescreen_options

    async def prescreen_shared():
        from pysyzygos import prescreen as PS
        ui.notify("Asking the mirror for its shared pre-screens ...")
        m, man = await run.io_bound(PS.remote_list, None, lambda *a: None)
        if not man or not man.get("prescreens"):
            ui.notify("No shared pre-screens (mirror not reachable, or none published yet)", type="warning")
            return
        here = {os.path.basename(p) for p, _ in PS.list_files()}
        with ui.dialog() as dlg, ui.card().classes("max-w-3xl"):
            ui.label("Shared whole-Earth pre-screens").classes("font-semibold")
            ui.label("Built with the limits shown (loose on purpose: a pick with stricter limits finds the same "
                     "events). Orbits are those of the build day: prefer a recent one.").classes("text-xs text-slate-500")
            for e in reversed(man["prescreens"]):
                mb = e["archive_bytes"] / 1e6
                with ui.row().classes("items-center gap-3"):
                    ui.label(f"{e['start']} + {e['days']:g} d, for picks up to G {e['cam_limit']:g} (any reach), "
                             f"{e['n_asteroids']} asteroids / {e['n_events']} events, built "
                             f"{str(e.get('built'))[:10]}, {mb:.0f} MB").classes("text-sm")
                    if e["name"] + ".global.npy" in here:
                        ui.label("installed").classes("text-sm text-green-700")
                    else:
                        async def get(name=e["name"]):
                            dlg.close()
                            ui.notify(f"Downloading {name} (see the log)")
                            await run_process(PYSYZYGOS + ["prescreen", "fetch", name], pg.log)
                            pg.prescreen_options()
                        ui.button("Download", on_click=get).props("dense outline")
            ui.button("Close", on_click=dlg.close).props("flat")
        dlg.open()
    pg.prescreen_shared = prescreen_shared

    async def delete_prescreens():
        sel = [r["path"] for r in pg.ps_table.selected]
        if not sel:
            ui.notify("Select pre-screens in the table first", type="warning")
            return
        from pysyzygos import prescreen as PS
        for p in sel:
            try:
                PS.remove(p)
            except OSError as e:
                ui.notify(f"{os.path.basename(p)}: {e}", type="negative")
        pg.ps_table.selected = []
        pg.prescreen_options()
        ui.notify(f"{len(sel)} pre-screen(s) deleted", type="positive")
    pg.delete_prescreens = delete_prescreens

    def pick_csv():
        p = next((p for p in pg.saved_list if p["py"] == pg.p_saved.value), None)
        if p is None or not os.path.isfile(p["csv"]):
            ui.notify("No saved pick with a CSV selected", type="warning")
            return
        pg.download_csv("pick", exports.pick_rows(p["csv"], p["targets"]), os.path.basename(p["csv"]))
    pg.pick_csv = pick_csv

    def use_saved():
        p = next((p for p in pg.saved_list if p["py"] == pg.p_saved.value), None)
        if p is None:
            ui.notify("No saved pick selected", type="warning")
            return
        pg.s_start.value, pg.s_days.value, pg.s_use_file.value = p["start"], p["days"], True
        pg.tabs.value = pg.t_search
    pg.use_saved = use_saved

    from pysyzygos import picks
    pg.picks = picks
    pg.picks_dir = getattr(pg.config, "picks_dir", "picks")
    pg.saved_list = []

    async def run_pick():
        if not pg.catalog_ok():
            return
        pg.ensure_saved()
        args = PYSYZYGOS + ["pick", "--start", pg.p_start.value, "--days", str(int(pg.p_days.value)),
                "--top", str(int(pg.p_top.value)), "--workers", str(int(pg.p_workers.value)), "--sort", pg.p_sort.value]
        args += ["--all"] if pg.p_all.value else ["--hmax", str(pg.p_hmax.value)]
        if pg.p_mag.value:
            args += ["--cam-limit", f"{float(pg.p_mag.value):g}"]
        if pg.p_pre.value != "all":
            args += ["--prescreen", pg.p_pre.value]                # "auto" or a file
        groups = [k for k, cb in pg.p_groups.items() if cb.value]
        if not groups:
            ui.notify("Tick at least one asteroid group", type="warning")
            return
        if len(groups) < len(pg.p_groups):
            args += ["--groups", ",".join(groups)]
        if pg.p_amin.value not in (None, ""):
            args += ["--a-min", f"{float(pg.p_amin.value):g}"]
        if pg.p_amax.value not in (None, ""):
            args += ["--a-max", f"{float(pg.p_amax.value):g}"]
        if pg.p_aexcl.value and (pg.p_amin.value not in (None, "") or pg.p_amax.value not in (None, "")):
            args += ["--a-exclude"]

        async def done(rc):
            if rc == 0:
                n = pg.load_pick(select=pg.picks.paths(pg.state["name"], pg.p_start.value, int(pg.p_days.value), pg.picks_dir)[0])
                pg.s_use_file.value = True
                ui.notify(f"{n} events; saved for site {pg.state['name']}", type="positive")
        await run_process(args, pg.log, env_site=pg.state["name"], on_done=done, env_catalog=pg.cat_sel.value)
    pg.run_pick = run_pick

    async def count_update(*_):
        """'These settings screen N of M asteroids' from the pick's cached asteroid list (picks.count), read once in
        the background; before a pre-screen and the site and star test."""
        from pysyzygos import picks as PK
        cache = os.path.join(getattr(pg.config, "cache_path", "") or "", "PySyzygos_sbdb_cache.json")
        if not os.path.isfile(cache):
            pg.p_count.text = "Asteroid count: after the first pick (it downloads JPL's asteroid list)"
            return
        if pg.p_count.text == "" or "counting" in pg.p_count.text:
            pg.p_count.text = "counting ..."
        idx = await run.io_bound(PK.count_index, cache)
        if idx is None:
            return
        f = lambda v: None if v in (None, "") else float(v)
        hmax = None if pg.p_all.value else float(pg.p_hmax.value or 17)
        if hmax is not None and idx["hmax"] is not None and hmax > idx["hmax"] or hmax is None and idx["hmax"] is not None:
            pg.p_count.text = (f"Asteroid count: the stored list holds H < {idx['hmax']:g} only; the next pick downloads "
                               f"the longer one")
            return
        groups = [k for k, cb in pg.p_groups.items() if cb.value]
        n, n_h = PK.count(idx, hmax, groups, f(pg.p_amin.value), f(pg.p_amax.value), bool(pg.p_aexcl.value))
        pg.p_count.text = (f"These settings screen {n:,} of {n_h:,} asteroids"
                           + (f" with H < {hmax:g}" if hmax is not None else " (all numbered)")
                           + " (before a pre-screen and the site and star test)")
    pg.count_update = count_update

    def groups_changed():
        background_tasks.create(count_update())
        save_ui_state(pick_groups=[k for k, cb in pg.p_groups.items() if cb.value],
                      pick_a_min=pg.p_amin.value if pg.p_amin.value not in ("",) else None,
                      pick_a_max=pg.p_amax.value if pg.p_amax.value not in ("",) else None,
                      pick_a_exclude=bool(pg.p_aexcl.value))
    pg.groups_changed = groups_changed

    def band_pick(row):
        """A band of the table: its a range into 'a from / to' (inside it)."""
        pg.p_amin.value, pg.p_amax.value = row["lo"], row["hi"]
        pg.p_aexcl.value = False
        ui.notify(f"a {row['lo']:g} - {row['hi']:g} AU ({row['band']}); clear the fields for no limit", type="info")
    pg.band_pick = band_pick

    async def run_prescreen():
        if not pg.catalog_ok():
            return
        pg.ensure_saved()
        v = pg.ps_where.value
        where = (["--region", v.split(":", 1)[1]] if v.startswith("region:") else
                 {"site": ["--around-site", f"{float(pg.ps_km.value or 300):g}"],
                  "sites": ["--around-sites", f"{float(pg.ps_km.value or 300):g}"], "global": ["--global"]}[v])
        args = PYSYZYGOS + ["prescreen", "build", "--start", pg.ps_start.value, "--days", str(int(pg.ps_days.value)),
                           *where, "--workers", str(int(pg.p_workers.value))]
        args += ["--all"] if pg.p_all.value else ["--hmax", str(pg.p_hmax.value)]
        args += ["--cam-limit", f"{max(16.0, float(pg.p_mag.value or 0)):g}"]
        if pg.ps_fresh.value:
            args += ["--fresh"]
            pg.ps_fresh.value = False

        async def done(rc):
            pg.prescreen_options()
            if rc == 0:
                ui.notify("Pre-screen built; picks inside its region and window use it ('Asteroids: auto')",
                          type="positive")
            else:
                ui.notify("Pre-screen not finished; the same build again resumes it", type="warning")
        await run_process(args, pg.log, env_site=pg.state["name"], on_done=done, env_catalog=pg.cat_sel.value)
    pg.run_prescreen = run_prescreen


def connect(pg):
    """Wire the tab up and fill it (run after all tabs' handlers)."""
    pg.p_saved.on_value_change(pg.show_saved)

    pg.load_pick()
    for el in (pg.p_start, pg.p_days, pg.p_mag, pg.p_hmax, pg.p_all, pg.p_pre):
        el.on_value_change(pg.prescreen_options)
    pg.prescreen_options()
    for el in (pg.p_hmax, pg.p_all):                                    # the asteroid count follows H and 'all' too
        el.on_value_change(lambda e: background_tasks.create(pg.count_update()))
    background_tasks.create(pg.count_update())
