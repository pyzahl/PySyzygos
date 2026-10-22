"""gui_favorites.py - Favorites tab: the starred events (favorites.py) with their detail panel, map, horizon view,
VizieR and OWC checks, and the path verification (pathcheck.py) with its own log.

Part of the GUI (gui.py builds the page): panel(pg) adds the tab's controls, handlers(pg) its functions, connect(pg)
wires them up; pg holds the page's elements and functions shared between the tabs.
"""
import json, math, os, time

from pysyzygos import exports, favorites, occultations
from pysyzygos.home import HOME as ROOT
from nicegui import run, ui
from pysyzygos.gui_common import (
    PYSYZYGOS, load_ui_state, resizable_box, run_process, save_ui_state, stop_process, today_utc)


def panel(pg):
    """The favorites tab's controls (inside its ui.tab_panel)."""
    with ui.tab_panel(pg.t_fav):
        with ui.row().classes("w-full items-center gap-4"):
            pg.fav_info = ui.label().classes("text-sm text-slate-600")
            ui.button("Reload", on_click=lambda: pg.load_favs()).props("flat dense")
            ui.link("Open in a new tab", "/fav/favorites.html", new_tab=True)
            pc_chk = ui.checkbox("Path verification", value=bool(load_ui_state().get("path_check", False))).tooltip(
                "Show the tools to compare a favorite's geodetic path with Occult's path listing (pathcheck.py; "
                "method: VERIFICATION.md section 3)")
            ui.button("CSV", on_click=lambda: pg.fav_csv()).props("outline dense").tooltip(
                "Download the favorites the table shows (its filter and sort order), named favorites_<today>.csv."
                " Columns: csv_exports.py in the data folder (default: as the table shows them; any log column can be added). "
                "The full table with all columns stays in favorites/favorites.csv")
            if getattr(pg.config, "owc_feeds", True):                    # config owc_feeds (on by default)
                ui.button("Check OWC Feeds", on_click=lambda: pg.owc_check("favorites")).props("outline dense").tooltip(
                    "Look the favorites up in OccultWatcher Cloud: prediction feeds (tags) and signed-up stations "
                    "(one request per second)")
        ui.label("Add events with the ☆ button in the Results report (opened from this GUI). Each favorite keeps "
                 "its own copy of map and preview, so later searches do not change it. Click a row for its preview, "
                 "map and note below; check rows for the actions above the table. Drag the table's bottom-right corner to make "
                 "it taller or shorter (remembered).").classes("text-xs text-slate-500")
        with resizable_box("favorites", 60):                          # drag the corner to resize (remembered)
            pg.f_frame = ui.element("iframe").style("width: 100%; height: 100%; border: 0; display: block")
        with ui.column().classes("w-full gap-3") as pg.f_detail:
            with ui.row().classes("w-full no-wrap gap-4 items-stretch"):
                pg.f_img = ui.element("img").style("width: 420px; max-width: 45vw; border: 1px solid #ddd")
                pg.f_map = ui.leaflet(center=(40.7, -74.0), zoom=9).classes("grow").style(   # as tall as the
                    "height: calc(min(420px, 45vw) * 634 / 560); border: 1px solid #ddd")    # preview (560x634)
                pg.f_nomap = ui.label("No map copied for this event.").classes("text-sm text-slate-500")
            with ui.row().classes("gap-3 items-center text-xs text-slate-600") as pg.f_legend:   # no ui.html:
                for sym, col, txt in (("━", "#15803d", "centre line"), ("━", "#dc2626", "shadow limits"),  # its
                                      ("┄", "#7c3aed", "1σ"), ("╌", "#d97706", "3σ")):         # signature differs
                    with ui.row().classes("gap-1 items-center"):                              # across versions
                        ui.label(sym).style(f"color: {col}; font-weight: 700")
                        ui.label(txt)
                ui.label("marker: site")
            with ui.column().classes("w-full"):
                pg.f_title = ui.label().classes("text-lg font-semibold")
                pg.f_bar = ui.html("").tooltip(
                    "Across the path at your site: green the shadow, orange out to 1 sigma beyond its edges "
                    "(the path's uncertainty: orbit and star), black the 3-sigma limits; the blue mark is your "
                    "site, with its distance from the centre line and the chance that the shadow covers it")
                pg.f_pano = ui.html("").classes("w-full").tooltip(
                    "Your site's 360° photo (Site tab, Horizon): the star at the event time (red ring), the "
                    "horizon line (white) and the margin (dashed)")
                pg.f_info = ui.grid(columns=4).classes("w-full gap-x-6 gap-y-1")   # OWC-style event summary
                with ui.row().classes("w-full no-wrap gap-6 items-start"):
                    pg.f_err = ui.element("img").style("width: 300px; flex: none").tooltip(
                        "Uncertainty ellipses (sky plane, 1 sigma) at one scale: the target's (JPL Horizons), the star's "
                        "(Gaia DR3, carried to the event date; '!' = a typical star of that G when Gaia's errors "
                        "are not at hand) and the combined one, which moves the path. Only the part across the "
                        "target's motion (dashed) shifts the path on the ground")
                    with ui.column().classes("grow"):
                        pg.f_occ = ui.label().classes("text-sm text-slate-600").tooltip(
                            "Earlier occultations of this asteroid in NASA's archive of observed occultations (PDS "
                            "Small Bodies Node; Herald, Dunham et al.; doi:10.26033/ehqs-jp27). Reference only: the "
                            "prediction uses the size above. Event quality: astrometry only < limits on size < "
                            "reliable size < better than shape models. With the Occult data add-on (System tab): "
                            "IOTA's current archive instead")
                        pg.f_ocd = ui.label().classes("text-sm text-slate-600 whitespace-pre-line").tooltip(
                            "From the optional Occult data add-on (System tab; data by D. Herald, published by "
                            "IOTA): infrared diameters, H in g and r, known satellites, Gaia non-single-star "
                            "solutions at the star (within 3\"). Reference only: the prediction uses the size "
                            "above")
                        with ui.row().classes("items-center gap-2"):
                            ui.button("Double-star check (VizieR)", on_click=lambda: pg.fav_vizier()).props(
                                "outline dense").tooltip(
                                "Ask VizieR (needs the network, a few seconds) for known pairs at this star (the "
                                "Washington Double Star Catalog, WDS: discoverer, separation, position angle, "
                                "magnitudes, last observed; 'O' = orbit in ORB6) and Gaia DR3's signs of a "
                                "companion the local catalog does not keep (elongated image, position wobble, "
                                "colour-window excess). Kept with the favorite")
                        pg.f_viz = ui.label().classes("text-sm text-slate-700 whitespace-pre-line")
                        pg.f_added = ui.label().classes("text-xs text-slate-500")
                        with ui.row().classes("items-end gap-4"):
                            pg.f_status = ui.select(list(favorites.STATUSES), label="Status").classes("w-40")
                            pg.f_kml = ui.link("KML (ground track)", "#")
                            pg.f_globe = ui.link("Globe (whole-Earth view)", "#", new_tab=True)
                        pg.f_note = ui.textarea("Note").classes("w-full")
                        with ui.row():
                            ui.button("Save", on_click=lambda: pg.save_fav()).props("color=primary")
                            ui.button("Remove from favorites", on_click=lambda: pg.remove_fav()).props(
                                "outline color=negative")
            with ui.column().classes("w-full gap-2 border-t pt-2") as f_pc:
                ui.label("Path verification: our geodetic path against Occult's listing").classes("font-semibold")
                pg.f_pc_info = ui.label().classes("text-sm text-slate-600")
                with ui.row().classes("gap-2 items-center"):
                    ui.button("Compute our path (fresh)", on_click=lambda: pg.pc_run()).props("outline dense").tooltip(
                        "Runs the search for this event only, with today's orbit from JPL and this version of "
                        "PySyzygos (relaxed limits; about 10-30 s), and keeps its path and orbit files with the "
                        "favorite. Compute it on the same day as the Occult listing: orbits change")
                    ui.button("Export our path (Occult layout)", on_click=lambda: pg.pc_export()).props(
                        "outline dense").tooltip("Our centre line, shadow and 1-sigma limits every 1.45 s as a text "
                                                 "table in Occult's layout, to send for a comparison the other way")
                    ui.button("Last report", on_click=lambda: pg.pc_show()).props("flat dense")
                    ui.button("Keep in owc_refs", on_click=lambda: pg.pc_keep()).props("flat dense").tooltip(
                        "Copy the last comparison (report, points, Occult's listing) to owc_refs/occult_paths/ "
                        "(private) and add a line to its index.md")
                pg.f_pc_list = ui.textarea("Occult's path listing: paste the text (or load the .txt below)").classes(
                    "w-full font-mono text-xs").props("rows=4")
                pg.f_pc_head = ui.textarea("Occult's plot header (optional: JPL#..., RA, Dec, Dia = ...)").classes(
                    "w-full font-mono text-xs").props("rows=2")
                with ui.row().classes("gap-2 items-center"):
                    ui.upload(label="Load listing .txt", auto_upload=True, on_upload=lambda e: pg.pc_upload(e)).props(
                        "accept=.txt dense flat").classes("w-64")
                    ui.button("Compare", on_click=lambda: pg.pc_compare()).props("color=primary")
                    ui.button("Step by step", on_click=lambda: pg.pc_steps()).props("outline").tooltip(
                        "The event step by step from our path: the star from the Gaia catalog through every "
                        "correction (with its amount), the asteroid, the resulting vectors and the Besselian "
                        "elements at the shadow's touch-down, centre and leaving, and the geodetic points then")
                with ui.expansion("Step-by-step data (catalog, corrections, vectors, Besselian elements)").classes(
                        "w-full") as pg.f_pc_steps:
                    pg.f_pc_steps_md = ui.markdown().classes("w-full text-sm")
            f_pc.set_visibility(bool(pc_chk.value))
            pc_chk.on_value_change(lambda e: (f_pc.set_visibility(bool(e.value)), save_ui_state(path_check=bool(e.value))))
        pg.f_detail.set_visibility(False)
        with ui.card().classes("w-full"):                         # this tab's own tasks (path verification) only
            with ui.row().classes("w-full items-center"):
                ui.label("Favorites log").classes("font-semibold").tooltip(
                    "The favorites' own tasks (path verification). They run independently of a search, pick or "
                    "pre-screen, whose output stays in the log of the other tabs")
                ui.button("Clear", on_click=lambda: pg.fav_log.clear()).props("flat dense")
                ui.button("Stop", on_click=lambda: stop_process(pg.fav_log, "fav")).props("flat dense color=negative")
            pg.fav_log = ui.log(max_lines=2000).classes("w-full h-48 text-xs")


def handlers(pg):
    """The favorites tab's functions and state, as attributes of pg."""
    async def fav_csv():
        items = favorites.load(os.path.join(ROOT, favorites.DIR))
        if not items:
            ui.notify("No favorites yet", type="warning")
            return
        keys = await pg.shown_keys(pg.f_frame)
        shown = exports.only_shown(exports.favorite_rows(items), keys)
        if keys is not None and not shown:
            ui.notify("No favorites shown (the filter hides them all): nothing to export", type="warning")
            return
        pg.download_csv("favorites", shown, f"favorites_{today_utc()}.csv")
        ui.notify(f"CSV: {len(shown)} favorite(s)" + (" as shown (filter and sort order)" if keys is not None else
                                                      " (all: the page could not be read)"))
    pg.fav_csv = fav_csv

    pg.fav_cur = {"key": None}

    async def fav_vizier():
        from pysyzygos import doubles as D_
        e = next((x for x in favorites.load() if x["key"] == pg.fav_cur["key"]), None)
        if not e:
            ui.notify("Click a favorite first", type="warning")
            return
        r = e["record"]
        try:
            sid = int(str(r.get("star")).split(".")[0])
            ra, dec = float(r["star_ra"]), float(r["star_dec"])
        except (KeyError, TypeError, ValueError):
            ui.notify("This favorite has no star position", type="warning")
            return
        pg.f_viz.text = "asking VizieR ..."
        try:
            v = await run.io_bound(D_.vizier_check, sid, ra, dec)
        except OSError as ex:
            pg.f_viz.text = ""
            ui.notify(f"VizieR not reachable: {str(ex)[:120]}", type="warning")
            return
        favorites.set_field(e["key"], "vizier", v)
        pg.f_viz.text = "\n".join(D_.vizier_text(v))
        ui.notify(f"{len(v['wds'])} WDS pair(s), {len(v['hints'])} sign(s)", type="positive")
    pg.fav_vizier = fav_vizier

    def load_favs(select=None):
        """Rebuild the favorites page (report table) and show it; keep or set the selected favorite."""
        favorites.write_page()
        items = favorites.load()
        pg.fav_info.text = f"{len(items)} favorite event{'s' if len(items) != 1 else ''}"
        pg.f_frame.props(f"src=/fav/favorites.html?t={time.time():.0f}")
        if select:
            pg.fav_cur["key"] = select
        if pg.fav_cur["key"] not in {e["key"] for e in items}:
            pg.fav_cur["key"] = None
        pg.show_fav()
    pg.load_favs = load_favs

    def current_fav():
        return next((e for e in favorites.load() if e["key"] == pg.fav_cur["key"]), None)
    pg.current_fav = current_fav

    def fav_pano(e):
        """The site's photo with the star at the event, or None (the favorite's site found in sites.py by position)."""
        from pysyzygos import panorama, report as R_
        site, r = e.get("site") or {}, e["record"]
        try:
            lat, lon = float(site["lat"]), float(site["lon"])
        except (KeyError, TypeError, ValueError):
            return None
        s = next((v for v in pg.sites.values() if abs(float(v.get("lat", 99)) - lat) < 2e-4
                  and abs(float(v.get("lon", 999)) - lon) < 2e-4 and v.get("horizon_image")), None)
        if not s or not os.path.isfile(s["horizon_image"]):
            return None
        f = lambda k: (lambda v: v if v == v else None)(float(r[k])) if str(r.get(k) or "").strip() not in (
            "", "nan") else None
        alt, az = f("star_alt"), f("star_az")
        if az is None and alt is not None and f("star_ra") is not None:
            try:
                alt, az = R_.alt_az(f("star_ra"), f("star_dec"), r.get("best_utc"), lat, lon)
            except Exception:
                az = None
        hi = 70 if alt is None else min(90, max(70, int(alt // 10 + 2) * 10))
        return panorama.svg(s["horizon_image"], float(s.get("horizon_image_az", 0)), s.get("horizon"),
                            s.get("horizon_margin", 15), star=(az, alt), alt_range=(-10, hi), width=1100,
                            label=None if alt is None else f"star {alt:.0f}°")
    pg.fav_pano = fav_pano

    def show_fav(*_):
        e = pg.current_fav()
        pg.f_detail.set_visibility(e is not None)
        if e is None:
            return
        r, site, files = e["record"], e.get("site") or {}, e.get("files") or {}
        pg.f_title.text = favorites.title_text(e)
        pg.pc_refresh()
        pg.f_info.clear()
        with pg.f_info:
            for group, rows in favorites.event_info(e):
                with ui.column().classes("gap-0"):
                    ui.label(group).classes("text-lg font-semibold")
                    for k, v in rows:
                        with ui.row().classes("gap-1 no-wrap text-base"):
                            ui.label(f"{k}:").classes("text-slate-500 whitespace-nowrap")
                            ui.label(str(v)).classes("text-slate-800 min-w-0 break-words")
        rr = e["record"]
        num_ = lambda k: (lambda v: v if v == v else None)(float(rr[k])) if str(rr.get(k) or "").strip() not in (
            "", "nan") else None
        from pysyzygos import report as R_
        bar = R_.chance_bar_svg(num_("min_distance"), num_("r_km"), num_("path_sigma1_km"), num_("p_site"))
        pg.f_bar.content = bar or ""
        pg.f_bar.set_visibility(bar is not None)
        pano = pg.fav_pano(e)
        pg.f_pano.content = pano or ""
        pg.f_pano.set_visibility(pano is not None)
        err = favorites.error_svg(e)
        pg.f_err.set_visibility(err is not None)
        if err:
            import base64
            pg.f_err.props(f'src="data:image/svg+xml;base64,{base64.b64encode(err.encode()).decode()}" alt="Error ellipses"')
        pg.f_occ.text = occultations.text(e["record"].get("target_id", ""))
        from pysyzygos import occultdata
        ocd = occultdata.summary(e["record"].get("target_id", ""))
        try:
            ocd += occultdata.star_text(float(e["record"]["star_ra"]), float(e["record"]["star_dec"]))
        except (KeyError, TypeError, ValueError):
            pass
        pg.f_ocd.text = "\n".join(ocd)
        pg.f_ocd.set_visibility(bool(ocd))
        from pysyzygos import doubles as D_
        pg.f_viz.text = "\n".join(D_.vizier_text(e.get("vizier")))
        pg.f_added.text = f"added {e.get('added', '')[:16].replace('T', ' ')} UT"
        pg.f_status.value, pg.f_note.value = e.get("status", "planned"), e.get("note", "")
        pg.f_img.set_visibility("svg" in files)
        if "svg" in files:
            pg.f_img.props(f'src=/fav/{files["svg"]}?t={int(time.time())} alt="Event preview"')
        pg.f_globe.set_visibility("globe" in files)
        if "globe" in files:
            pg.f_globe.props(f'href=/fav/{files["globe"]}')
        pg.f_kml.set_visibility("kml" in files)
        if "kml" in files:
            pg.f_kml.props(f'href=/fav/{files["kml"]} download')
        pg.draw_fav_map(e)
    pg.show_fav = show_fav

    pg.fav_layers = []

    def draw_fav_map(e):
        """The favorite's own KML copy on the map: shadow path lines and the site, zoomed to the nearest path part."""
        from pysyzygos import report
        for layer in pg.fav_layers:
            pg.f_map.remove_layer(layer)
        pg.fav_layers.clear()
        kml = (e.get("files") or {}).get("kml")
        try:
            data = report.kml_to_data(os.path.join(favorites.DIR, kml)) if kml else None
        except Exception:
            data = None
        for el in (pg.f_map, pg.f_legend):
            el.set_visibility(data is not None)
        pg.f_nomap.set_visibility(data is None)
        if data is None:
            return
        for ln in data["lines"]:
            if len(ln["pts"]) > 1:
                opts = {"color": ln["color"], "weight": ln["width"]}
                if ln.get("dash"):
                    opts["dashArray"] = ln["dash"]
                pg.fav_layers.append(pg.f_map.generic_layer(name="polyline", args=[ln["pts"], opts]))
        site = e.get("site") or {}
        centre = next((ln["pts"] for ln in data["lines"] if ln["name"].startswith("Centre")), [])
        if site.get("lat") is not None and site.get("lon") is not None:
            obs = [site["lat"], site["lon"]]
            pg.fav_layers.append(pg.f_map.marker(latlng=tuple(obs)))
            near = min(centre, key=lambda p: (p[0] - obs[0]) ** 2 + ((p[1] - obs[1]) * math.cos(math.radians(obs[0]))) ** 2,
                       default=obs)
            bounds = [obs, near]
        else:
            bounds = centre or [[0, 0]]

        def fit():
            pg.f_map.run_map_method("invalidateSize")
            pg.f_map.run_map_method("fitBounds", bounds, {"padding": [50, 50], "maxZoom": 11})
        ui.timer(0.3, fit, once=True)
    pg.draw_fav_map = draw_fav_map

    def save_fav():
        e = pg.current_fav()
        if e:
            ok, msg = favorites.update(e["key"], status=pg.f_status.value, note=pg.f_note.value or "")
            ui.notify(msg, type="positive" if ok else "warning")
            pg.load_favs(select=e["key"])
    pg.save_fav = save_fav

    async def remove_fav():
        e = pg.current_fav()
        if not e:
            return
        with ui.dialog() as dlg, ui.card():
            ui.label(f"Remove {pg.f_title.text} and its copied map and preview?")
            with ui.row():
                ui.button("Remove", on_click=lambda: dlg.submit(True)).props("color=negative")
                ui.button("Cancel", on_click=lambda: dlg.submit(False)).props("flat")
        if await dlg:
            ok, msg = favorites.remove(e["key"])
            ui.notify(msg, type="positive" if ok else "warning")
            pg.fav_cur["key"] = None
            pg.load_favs()
    pg.remove_fav = remove_fav

    def pc_dir():
        from pysyzygos import pathcheck
        return pathcheck.fav_dir(pg.fav_cur["key"], os.path.join(ROOT, favorites.DIR)) if pg.fav_cur["key"] else None
    pg.pc_dir = pc_dir

    def pc_newest(pattern):
        import glob as _glob
        d = pg.pc_dir()
        files = sorted(_glob.glob(os.path.join(d, pattern))) if d else []
        return files[-1] if files else None
    pg.pc_newest = pc_newest

    def pc_refresh():
        d = pg.pc_dir()
        try:
            m = json.load(open(os.path.join(d, "meta.json")))
            pg.f_pc_info.text = (f"Our path: computed {m['run_utc']} UTC with PySyzygos {m['version']}, orbit "
                                 f"{m.get('orbit') or '?'}." + ("  Last comparison: " + os.path.basename(pg.pc_newest('compare_*.md'))
                                                         if pg.pc_newest('compare_*.md') else ""))
        except (OSError, ValueError, TypeError):
            pg.f_pc_info.text = "Our path: not computed yet (Compute our path first)."
        st = pg.pc_newest("steps_*.md")
        pg.f_pc_steps_md.content = open(st, encoding="utf-8").read() if st else "*Not computed yet: Step by step.*"
    pg.pc_refresh = pc_refresh

    async def pc_run():
        if not pg.fav_cur["key"]:
            return
        async def done(rc):
            pg.pc_refresh()
            ui.notify("Our path is computed" if rc == 0 else "Computing our path failed: see the log",
                      type="positive" if rc == 0 else "negative")
        await run_process(PYSYZYGOS + ["path-check", "run", pg.fav_cur["key"]], pg.fav_log, on_done=done,
                          env_catalog=pg.cat_sel.value, slot="fav")
    pg.pc_run = pc_run

    async def pc_export():
        if not pg.fav_cur["key"]:
            return
        async def done(rc):
            f = pg.pc_newest("pysyzygos_path_*.txt")
            if rc == 0 and f:
                ui.download(f, os.path.basename(f))
            else:
                ui.notify("Export failed: compute our path first (see the log)", type="negative")
        await run_process(PYSYZYGOS + ["path-check", "export", pg.fav_cur["key"]], pg.fav_log, on_done=done,
                          env_catalog=pg.cat_sel.value, slot="fav")
    pg.pc_export = pc_export

    async def pc_upload(e):
        data = await e.file.read()
        pg.f_pc_list.value = data.decode("utf-8", errors="replace") if b"\x00" not in data[:200] else ""
        ui.notify(f"Loaded {getattr(e.file, 'name', 'the file')}: {len(pg.f_pc_list.value.splitlines())} lines")
    pg.pc_upload = pc_upload

    def pc_show(path=None):
        path = path or pg.pc_newest("compare_*.md")
        if not path:
            ui.notify("No comparison yet", type="warning")
            return
        pg.pc_md.content = open(path, encoding="utf-8").read()
        pg.pc_state["md"] = path
        pg.pc_dialog.open()
    pg.pc_show = pc_show

    async def pc_compare():
        if not pg.fav_cur["key"]:
            return
        if not (pg.f_pc_list.value or "").strip():
            ui.notify("Paste Occult's path listing first (or load its .txt)", type="warning")
            return
        d = pg.pc_dir()
        if not os.path.isfile(os.path.join(d, "path.npz")):
            ui.notify("Compute our path first", type="warning")
            return
        lp, hp = os.path.join(d, "occult_input.txt"), os.path.join(d, "occult_header_input.txt")
        open(lp, "w", encoding="utf-8").write(pg.f_pc_list.value)
        open(hp, "w", encoding="utf-8").write(pg.f_pc_head.value or "")
        async def done(rc):
            pg.pc_refresh()
            if rc == 0:
                pg.pc_show()
            else:
                ui.notify("The comparison failed: see the log", type="negative")
        await run_process(PYSYZYGOS + ["path-check", "compare", pg.fav_cur["key"], lp, "--header", hp], pg.fav_log,
                          on_done=done, env_catalog=pg.cat_sel.value, slot="fav")
    pg.pc_compare = pc_compare

    async def pc_steps():
        if not pg.fav_cur["key"]:
            return
        if not os.path.isfile(os.path.join(pg.pc_dir(), "path.npz")):
            ui.notify("Compute our path first", type="warning")
            return
        async def done(rc):
            pg.pc_refresh()
            if rc == 0:
                pg.f_pc_steps.open()
            else:
                ui.notify("Step by step failed: see the log", type="negative")
        await run_process(PYSYZYGOS + ["path-check", "steps", pg.fav_cur["key"]], pg.fav_log, on_done=done,
                          env_catalog=pg.cat_sel.value, slot="fav")
    pg.pc_steps = pc_steps

    async def pc_keep():
        if pg.fav_cur["key"]:
            await run_process(PYSYZYGOS + ["path-check", "keep", pg.fav_cur["key"]], pg.fav_log, slot="fav")
    pg.pc_keep = pc_keep

    def on_fav_select(e):
        pg.fav_cur["key"] = e.args if isinstance(e.args, str) else (e.args or [None])[0]
        pg.show_fav()
    pg.on_fav_select = on_fav_select

    def on_fav_changed(_):                        # the page changed favorites (mass actions): refresh the panel
        if pg.fav_cur["key"] not in set(favorites.keys()):
            pg.fav_cur["key"] = None
        pg.show_fav()
    pg.on_fav_changed = on_fav_changed


def connect(pg):
    """Wire the tab up and fill it (run after all tabs' handlers)."""
    with ui.dialog() as pg.pc_dialog, ui.card().classes("w-full max-w-5xl"):
        pg.pc_md = ui.markdown().classes("w-full text-sm")
        pg.pc_state = {"md": None}
        with ui.row():
            ui.button("Download .md", on_click=lambda: ui.download(pg.pc_state["md"], os.path.basename(pg.pc_state["md"]))
                      if pg.pc_state["md"] else None).props("outline dense")
            ui.button("Close", on_click=pg.pc_dialog.close).props("flat dense")

    ui.on("fav_select", pg.on_fav_select)
    ui.on("fav_changed", pg.on_fav_changed)
    pg.tabs.on_value_change(lambda e: pg.load_favs() if e.value == pg.t_fav or e.value == "Favorites" else None)
    pg.load_favs()
