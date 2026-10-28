"""gui_system.py - System tab: data in use, star catalog parts and updates, planet kernels, Occult data add-on, offline
copies, cache.

Part of the GUI (gui.py builds the page): panel(pg) adds the tab's controls, handlers(pg) its functions, connect(pg)
wires them up; pg holds the page's elements and functions shared between the tabs.
"""
import json, os, shutil

from pysyzygos import home, starcat
from pysyzygos.home import HOME as ROOT, PKG
from nicegui import run, ui
from pysyzygos.gui_common import PYSYZYGOS, catalog_options, run_process, save_ui_state, load_ui_state


def panel(pg):
    """The system tab's controls (inside its ui.tab_panel)."""
    with ui.tab_panel(pg.t_sys):
        from pysyzygos import offline
        ui.label(f"Data folder: {home.describe()}").classes("text-sm text-slate-600")
        # updates: looked up when this tab is first opened (no messages elsewhere); a git checkout can be updated here
        from pysyzygos import urls as U
        from pysyzygos.version import __version__
        with ui.row().classes("items-center gap-3"):
            ui.label(f"PySyzygos {__version__}").classes("font-semibold")
            pg.upd_info = ui.label("").classes("text-sm")
            ui.link("Changelog", U.URL_CHANGELOG, new_tab=True).classes("text-sm")
            pg.upd_rel = ui.link("Release", "", new_tab=True).classes("text-sm")
            pg.upd_rel.set_visibility(False)
            pg.upd_btn = ui.button("Update", on_click=lambda: pg.upd_run()).props("outline dense color=primary").tooltip(
                "git pull (fast-forward only: never merges, never touches your changes), the dependencies if they "
                "changed, then a restart. Your data folder (sites, results, catalogs) is not touched")
            pg.upd_btn.set_visibility(False)
            ui.button("Check", on_click=lambda: pg.upd_check()).props("flat dense").tooltip(
                "Look for a newer version (git fetch, or the newest GitHub release for a ZIP install)")
        pg.upd_new = ui.expansion("What is new").classes("w-full text-sm")
        pg.upd_new.set_visibility(False)
        with pg.upd_new:
            pg.upd_md = ui.markdown("").classes("text-sm")
        with ui.row().classes("gap-2 items-center"):
            ui.button("Setup status", on_click=lambda: pg.sys_status()).props("outline dense").tooltip(
                "pysyzygos setup --status (in the log below): kernels, Earth orientation, catalogs, supplement, "
                "the site's height")
            ui.button("Refresh Earth orientation", on_click=lambda: pg.sys_earth()).props("outline dense").tooltip(
                "Download earth_latest_high_prec.bpc again now (pysyzygos setup --refresh-earth): it predicts the "
                "Earth's rotation ~3 months ahead and is otherwise refreshed after earth_pck_max_age days. Searches "
                "past its end use NAIF's long-term prediction (up to a year after its last measurement) and say so "
                "in the Warnings line")
        with ui.row().classes("gap-2 items-center"):
            ui.label("Shadow distance in Results and Favorites:").classes("text-sm")
            pg.sys_dist = ui.select({"ground": "on the ground (default)", "plane": "in the fundamental plane"},
                                    value=load_ui_state().get("shadow_distance") or "ground").props("dense").classes(
                "w-60").tooltip(
                "On the ground: the site's distance from the center line across the track on the ground (the shadow "
                "cylinder's footprint is stretched where the star is low, up to 1 / sin of its altitude). In the "
                "fundamental plane: perpendicular to the star, as the solver and the chance use it. The hover of each "
                "distance shows both.")
            pg.sys_dist.on_value_change(lambda e: pg.set_distance(e.value))
        ui.separator()
        with ui.row().classes("items-center gap-2"):
            ui.label("Data in use").classes("font-semibold")
            ui.button("Refresh", on_click=lambda: pg.sys_info_refresh()).props("flat dense").tooltip(
                "pysyzygos info: time and Earth orientation (valid ranges), the star catalogs (the one in use "
                "marked), the asteroid data in the cache and the offline copies, results")
        pg.sys_info = ui.column().classes("w-full gap-1")
        with ui.row().classes("gap-2 items-center"):
            ui.button("Download orbits again", on_click=lambda: pg.sys_cache(True)).props("outline dense").tooltip(
                "Delete the cached orbit files (JPL Horizons): the next search downloads the current orbits. "
                "Searches do this by themselves for files older than orbit_max_age_days (config, default 7)")
            ui.button("Empty cache", on_click=lambda: pg.sys_cache_ask()).props("flat dense color=negative").tooltip(
                f"Delete PySyzygos's files in {pg.config.cache_path}: orbit files, the pick's asteroid list (the next "
                "pick downloads it again, ~100 MB), size data, CSV exports. The offline copies stay")
        ui.separator()
        with ui.row().classes("items-center gap-2"):
            ui.label("Star catalog").classes("font-semibold")
            ui.label("(the one selected in the header)").classes("text-xs text-slate-500")
        pg.cat_box = ui.column().classes("w-full gap-1")
        ui.separator()
        ui.label("Planets and moons offline").classes("font-semibold")
        ui.label("NAIF's kernels of the planet systems: with one, the positions of that planet and its moons come "
                 "from your computer; without, from JPL Horizons per search (needs the network). Uranus: Horizons "
                 "only (NAIF splits it into very large files).").classes("text-xs text-slate-500")
        pg.planets_box = ui.column().classes("w-full gap-0")
        ui.separator()
        ui.label("Occult data (optional add-on)").classes("font-semibold")
        ui.label("Asteroid data that D. Herald maintains for the Occult program, published by IOTA: infrared "
                 "diameters, H and G in two colours, asteroid satellites, the occultation results archive "
                 "(updated continuously; replaces the yearly NASA PDS extract in the favorites panel), Gaia "
                 "non-single stars. Shown with the favorites as reference; the predictions do not use them yet. "
                 "Stored in the data folder's occult_data/.").classes("text-xs text-slate-500")
        pg.occ_box = ui.column().classes("w-full gap-0")
        with ui.row().classes("items-center gap-2"):
            pg.obs_info = ui.label().classes("text-sm")
            ui.button("Check our predictions", on_click=lambda: pg.obs_check_run()).props("outline dense").tooltip(
                "Every observed event of the archive against PySyzygos's prediction for it (today's JPL orbit, the "
                "search's star corrections): observed minus predicted across and along the track. One JPL Horizons "
                "request per asteroid, two at a time: a few hours for all; Stop and run again to continue")
            ui.button("Summary", on_click=lambda: pg.obs_check_show()).props("flat dense")
        with ui.row().classes("items-center gap-2"):
            ui.button("Check for updates", on_click=lambda: pg.occ_check()).props("outline dense").tooltip(
                "Compare the installed datasets with the server's (a few small requests); changed ones can then "
                "be downloaded again")
            pg.occ_src = ui.input("Occult 'Resource Files' folder").props("dense outlined").classes("w-96")
            ui.button("Import", on_click=lambda: pg.occ_import()).props("flat dense").tooltip(
                "Copy the datasets from an Occult installation instead of downloading them (their server date is "
                "then unknown: 'Check for updates' lists them)")
        ui.separator()
        ui.label("Offline use").classes("font-semibold")
        ui.label("The pick's asteroid list (JPL SBDB) and the searches' orbit files (JPL Horizons) are cached in "
                 f"{pg.config.cache_path}, which is lost when the computer restarts where it is /dev/shm. With copies "
                 "kept here (the data folder's offline/), a pick or search without network uses them and says how "
                 "old they are: plan online, observe offline. The list is ~34 MB compressed (asteroids with "
                 "H < 17).").classes("text-xs text-slate-500")
        pg.off_chk = ui.checkbox("Keep copies of orbit downloads for use without network", value=offline.enabled())
        pg.off_info = ui.label().classes("text-sm text-slate-600 whitespace-pre-line")
        with ui.row().classes("gap-2"):
            ui.button("Copy now", on_click=lambda: pg.sys_copy()).props("outline dense").tooltip(
                "Copy what is in the cache now (the asteroid list of the last pick, the orbit files of past "
                "searches) and switch the copies on")
            ui.button("Remove copies", on_click=lambda: pg.sys_remove_ask()).props("flat dense color=negative")


def handlers(pg):
    """The system tab's functions and state, as attributes of pg."""
    async def set_distance(mode):
        """System tab: the shadow distance shown (ground / plane): saved, used by this process (favorites page, CSV
        exports) and the report runs (dist_args); both pages rebuilt."""
        from pysyzygos import report
        save_ui_state(shadow_distance=mode)
        report.DISTANCE = mode
        pg.load_favs()
        ui.notify("Shadow distance " + ("on the ground" if mode == "ground" else "in the fundamental plane")
                  + ": rebuilding the results page", type="info")
        await pg.build_report()
    pg.set_distance = set_distance

    def sys_refresh():
        from pysyzygos import offline
        pg.off_info.text = offline.status_text()
    pg.sys_refresh = sys_refresh

    def sys_toggle(e):
        from pysyzygos import offline
        offline.set_enabled(bool(e.value))
        pg.sys_refresh()
    pg.sys_toggle = sys_toggle

    async def sys_status():
        await run_process(PYSYZYGOS + ["setup", "--status"], pg.log)
    pg.sys_status = sys_status

    async def sys_earth():
        await run_process(PYSYZYGOS + ["setup", "--refresh-earth"], pg.log)
        await pg.sys_info_refresh()
    pg.sys_earth = sys_earth

    async def sys_copy():
        from pysyzygos import offline
        ok, n = await run.io_bound(offline.copy_now, pg.config.cache_path)
        pg.off_chk.value = offline.enabled()
        pg.sys_refresh()
        ui.notify(f"Copied: asteroid list {'yes' if ok else 'no (none in the cache: run a pick first)'}, {n} orbit files",
                  type="positive" if ok or n else "warning")
    pg.sys_copy = sys_copy

    def sys_remove_ask():
        with ui.dialog() as d, ui.card():
            ui.label("Remove all offline copies (asteroid list, orbit files)?")
            with ui.row():
                ui.button("Remove", on_click=lambda: (pg.sys_remove(), d.close())).props("color=negative")
                ui.button("Cancel", on_click=d.close).props("flat")
        d.open()
    pg.sys_remove_ask = sys_remove_ask

    def sys_remove():
        from pysyzygos import offline
        offline.remove()
        pg.off_chk.value = False
        pg.sys_refresh()
    pg.sys_remove = sys_remove

    async def sys_cache(orbits_only):
        from pysyzygos import cleanup
        n, size = await run.io_bound(cleanup.empty_cache, pg.config.cache_path, orbits_only)
        ui.notify(f"Deleted {n} {'orbit files' if orbits_only else 'cache files'} ({size / 1e6:.0f} MB)",
                  type="positive")
        await pg.sys_info_refresh()
    pg.sys_cache = sys_cache

    def sys_cache_ask():
        async def go():
            d.close()
            await pg.sys_cache(False)

        with ui.dialog() as d, ui.card():
            ui.label(f"Delete PySyzygos's cached downloads in {pg.config.cache_path} (orbit files, asteroid list, size "
                     "data)? They are downloaded again when needed; the offline copies stay.")
            with ui.row():
                ui.button("Empty cache", on_click=go).props("color=negative")
                ui.button("Cancel", on_click=d.close).props("flat")
        d.open()
    pg.sys_cache_ask = sys_cache_ask

    def cat_refresh(*_):
        """The System tab's catalog section: parts of a format-2 catalog (checkboxes), or the upgrade of an old one."""
        pg.cat_box.clear()
        d = os.path.join(ROOT, pg.cat_sel.value) if pg.cat_sel.value else None
        with pg.cat_box:
            if not d:
                ui.label("No catalog: pysyzygos setup").classes("text-sm text-red-700")
                return
            if starcat.is_format2(d):
                st = starcat.status(d)
                v, newer = starcat.data_version(d), starcat.update_available(d)
                ui.label(f"{pg.cat_sel.value}: data version {v} ({starcat.DATA_TEXT.get(v, '')}), G \u2264 "
                         f"{st['gmax']:g}, {st['n_stars'] / 1e6:.1f} M stars, {st['gb']:.1f} GB"
                         + ("" if newer else " \u2014 the latest")).classes("text-sm text-slate-700")
                if newer:
                    with ui.row().classes("items-center gap-3"):
                        ui.label(f"Data version {newer} is published: {starcat.DATA_TEXT.get(newer, '')}, and the "
                                 f"star names (xref). The parts that changed are downloaded next to this one and "
                                 f"swapped in.").classes("text-sm text-amber-800")
                        upd_del = ui.checkbox("delete the previous version afterwards", value=True).props("dense")
                        ui.button(f"Update to {newer}", on_click=lambda: pg.cat_update(pg.cat_sel.value, upd_del.value)
                                  ).props("color=primary dense")
                ready = float(st["gmax"]) in starcat.ZENODO_STEM
                ui.checkbox(f"core ({starcat.group_bytes(d, 'core') / 1e9:.1f} GB): {starcat.GROUP_TEXT['core']}",
                            value=True).props("dense disable")
                off = starcat.disabled_groups(d)
                for g in starcat.GROUPS:
                    have = g in st["groups"]
                    size = starcat.group_bytes(d, g) / 1e9 if have else None
                    off_gb = (os.path.getsize(os.path.join(d, f"{g}.npy{starcat.OFF}")) / 1e9 if g in off else None)
                    label = (f"{g}" + (f" ({size:.1f} GB)" if have else
                                       f" (switched off, files kept: {off_gb:.1f} GB)" if g in off else "")
                             + f": {starcat.GROUP_TEXT[g]}")
                    cb = ui.checkbox(label, value=have).props("dense")
                    if not have and not ready and g not in off and g != "xref":   # xref: built here if needed
                        cb.set_enabled(False)
                        cb.tooltip("This catalog was built from ESA's files: a part comes only with a new build "
                                   "(pysyzygos catalog build writes all parts)")
                    cb.on_value_change(lambda e, g=g: pg.cat_part(d, g, e.value))
            else:
                st = pg.gaia_local.status(d)
                ui.label(f"{pg.cat_sel.value}: G \u2264 {st.get('gmax', 0):g}, {st['gb']:.1f} GB, the old format (before "
                         f"1.3.0)").classes("text-sm text-slate-700")
                ui.label("The new format: one sort order for every lookup (no separate pick index), the high-RUWE and "
                         "2-parameter stars included, and optional parts: Gaia's errors and flags (quality), colours "
                         "and radial velocities (extras), UCAC4 / Tycho-2 / Hipparcos names (xref). G \u2264 16 is "
                         "ready-made on Zenodo and the mirror; other limits are built "
                         "from ESA's files (about 2 h). It is installed next to the old one and swapped in; the old "
                         "one is kept as <folder>.old until you delete it.").classes("text-xs text-slate-500")
                with ui.row().classes("items-center gap-3"):
                    up_parts = ui.select({"quality,xref": "core + quality + star names (recommended)",
                                          "quality": "core + quality", "none": "core only",
                                          "all": "all parts (+ extras, star names)"},
                                         value="quality,xref").props("dense outlined")
                    up_del = ui.checkbox("delete the old catalog when the new one is in place", value=True).props(
                        "dense")
                    ui.button("Upgrade the catalog", on_click=lambda: pg.cat_upgrade_ask(
                        pg.cat_sel.value, up_parts.value, up_del.value)).props("outline dense")
            for old in sorted(f for f in os.listdir(ROOT) if f.startswith("gaia_dr3_") and f.endswith(".old")):
                with ui.row().classes("items-center gap-2"):
                    ui.label(f"{old}: the catalog before the upgrade").classes("text-sm text-slate-600")
                    ui.button("Delete", on_click=lambda o=old: pg.cat_delete_old(o)).props("flat dense color=negative")
    pg.cat_refresh = cat_refresh

    def planets_refresh(*_):
        from pysyzygos import bodies
        pg.planets_box.clear()
        with pg.planets_box:
            for g, fname, size, have, n in bodies.kernels_status(ROOT):
                label = f"{g.capitalize()} system ({fname}, " + (f"{n / 1e9:.2f} GB)" if have else f"{size})")
                cb = ui.checkbox(label, value=have).props("dense")
                cb.on_value_change(lambda e, g=g, fname=fname: pg.planet_kernel(g, fname, e.value))
    pg.planets_refresh = planets_refresh

    async def planet_kernel(g, fname, on):
        from pysyzygos import bodies
        if on:
            ui.notify(f"Downloading {fname} from NAIF (see the log; large files take a while)")
            await run_process(PYSYZYGOS + ["planets", "add", g], pg.log)
            pg.planets_refresh()
            await pg.sys_info_refresh()
            return

        async def go(delete):
            dlg.close()
            if delete:
                await run.io_bound(bodies.remove_naif, g, ROOT)
                ui.notify(f"{fname} deleted: {g.capitalize()} positions now from JPL Horizons", type="positive")
            pg.planets_refresh()
            await pg.sys_info_refresh()

        with ui.dialog().props("persistent") as dlg, ui.card().classes("max-w-lg"):
            ui.label(f"Delete {fname}?").classes("font-semibold")
            ui.label(f"Searches of the {g.capitalize()} system then take the positions from JPL Horizons (needs the "
                     f"network). Ticking it again downloads the file anew from NAIF.").classes("text-sm")
            with ui.row():
                ui.button("Delete", on_click=lambda: go(True)).props("color=negative")
                ui.button("Cancel", on_click=lambda: go(False)).props("flat")
        dlg.open()
    pg.planet_kernel = planet_kernel

    def occ_refresh(*_):
        from pysyzygos import occultdata
        pg.occ_box.clear()
        with pg.occ_box:
            for s in occultdata.status():
                when = (s["server_date"][5:16] if s["server_date"] else "imported" if s["source"] else "")
                label = (f"{s['key']}: {s['text']} (" + (f"{s['bytes'] / 1e6:.1f} MB, {when})" if s["installed"]
                                                          else f"{s['zip']})"))
                cb = ui.checkbox(label, value=s["installed"]).props("dense")
                cb.on_value_change(lambda e, k=s["key"]: pg.occ_toggle(k, e.value))
        from pysyzygos import observed
        st = observed.status()
        pg.obs_info.text = ("Observed events: download 'observations' above" if st is None else
                            f"Observed events: {st['events']} until {st['events_until']} (Results tab, Show: Observed "
                            f"events)" + (f"; predictions checked {st['checked']}" if st.get("checked") else ""))
    pg.occ_refresh = occ_refresh

    async def upd_check():
        """Look for a newer version (selfupdate.status): a note, the changelog of the new version, Update if possible."""
        from pysyzygos import selfupdate
        pg.upd_checked = True
        pg.upd_info.text = "checking for updates ..."
        s = await run.io_bound(selfupdate.status)
        rel = s.get("release") or {}
        pg.upd_rel.set_visibility(bool(rel.get("url")) and (s.get("kind") == "zip" or s.get("release_newer")))
        if rel.get("url"):
            pg.upd_rel.props(f"href={rel['url']}")
            pg.upd_rel.text = f"Release {rel.get('tag', '')}"
        behind = s.get("behind") or 0
        if s.get("kind") == "git" and behind:
            v = s.get("remote_version") or "?"
            pg.upd_info.text = (f"new version {v} available ({behind} change(s))" if s.get("possible") else
                                f"new version {v} available ({behind} change(s)); update by hand: {s.get('reason')}")
            pg.upd_info.classes(replace="text-sm text-amber-700")
        elif s.get("kind") == "zip":
            pg.upd_info.text = (f"release {rel.get('tag')} available: download it" if s.get("release_newer") else
                                "up to date" if rel else "no update information (offline?)")
            pg.upd_info.classes(replace="text-sm" + (" text-amber-700" if s.get("release_newer") else ""))
        else:
            pg.upd_info.text = s.get("reason") or "up to date"
            pg.upd_info.classes(replace="text-sm text-slate-600")
        pg.upd_btn.set_visibility(bool(s.get("possible")))
        text = s.get("changelog") or ""
        commits = s.get("commits") or []
        pg.upd_md.content = (text + ("\n\n**Changes:**\n" + "\n".join(f"- {c[1] if len(c) > 1 else c[0]}" for c in commits)
                                     if commits else ""))
        pg.upd_new.set_visibility(bool(text or commits))
    pg.upd_check = upd_check
    pg.upd_checked = False

    async def upd_run():
        async def done(rc):
            if rc != 0:
                ui.notify("Update not done: see the log", type="warning")
                await upd_check()
                return
            with ui.dialog() as dlg, ui.card().classes("max-w-md"):
                ui.label("PySyzygos is updated").classes("font-semibold")
                ui.label("Restart now to use the new version (this page reconnects by itself)?").classes("text-sm")
                with ui.row():
                    ui.button("Restart", on_click=lambda: (dlg.close(), pg.restart_app())).props("color=primary")
                    ui.button("Later", on_click=dlg.close).props("flat")
            dlg.open()
        await run_process(PYSYZYGOS + ["update"], pg.log, on_done=done)
    pg.upd_run = upd_run

    async def obs_check_run():
        from pysyzygos import observed
        if observed.status() is None:
            ui.notify("Download the 'observations' dataset first", type="warning")
            return
        await run_process(PYSYZYGOS + ["obs-check", "run"], pg.log)
        pg.occ_refresh()
    pg.obs_check_run = obs_check_run

    def obs_check_show():
        from pysyzygos import obscheck
        md = obscheck.files()[1]
        if not os.path.isfile(md):
            ui.notify("No check yet: 'Check our predictions'", type="warning")
            return
        with ui.dialog() as dlg, ui.card().classes("w-[90vw] max-w-6xl"):
            with ui.scroll_area().classes("h-[75vh] w-full"):
                ui.markdown(open(md, encoding="utf-8").read()).classes("text-sm")
            ui.button("Close", on_click=dlg.close).props("flat")
        dlg.open()
    pg.obs_check_show = obs_check_show

    async def occ_toggle(key, on):
        from pysyzygos import occultdata
        if on:
            ui.notify(f"Downloading {key} (see the log)")
            await run_process(PYSYZYGOS + ["occult-data", "add", key], pg.log)
            pg.occ_refresh()
            return

        async def go(delete):
            dlg.close()
            if delete:
                await run.io_bound(occultdata.remove, key)
                ui.notify(f"{key} deleted", type="positive")
            pg.occ_refresh()

        with ui.dialog().props("persistent") as dlg, ui.card().classes("max-w-lg"):
            ui.label(f"Delete the dataset '{key}'?").classes("font-semibold")
            ui.label("Ticking it again downloads it anew.").classes("text-sm")
            with ui.row():
                ui.button("Delete", on_click=lambda: go(True)).props("color=negative")
                ui.button("Cancel", on_click=lambda: go(False)).props("flat")
        dlg.open()
    pg.occ_toggle = occ_toggle

    async def occ_check():
        from pysyzygos import occultdata
        new = await run.io_bound(occultdata.check_updates)
        if not new:
            ui.notify("The installed Occult datasets are up to date", type="positive")
            return
        with ui.dialog() as dlg, ui.card().classes("max-w-lg"):
            ui.label("Newer on the server:").classes("font-semibold")
            for k, d in new.items():
                ui.label(f"{k}: {d}").classes("text-sm")

            async def go():
                dlg.close()
                await run_process(PYSYZYGOS + ["occult-data", "update"], pg.log)
                pg.occ_refresh()
            with ui.row():
                ui.button("Download", on_click=go).props("color=primary")
                ui.button("Later", on_click=dlg.close).props("flat")
        dlg.open()
    pg.occ_check = occ_check

    async def occ_import():
        src = (pg.occ_src.value or "").strip()
        if not src or not os.path.isdir(src):
            ui.notify("Enter the path of an Occult 'Resource Files' folder", type="warning")
            return
        await run_process(PYSYZYGOS + ["occult-data", "import", src], pg.log)
        pg.occ_refresh()
    pg.occ_import = occ_import

    async def cat_part(d, g, on):
        if on:
            if g in starcat.disabled_groups(d):                     # switched off earlier: back at once
                ok = await run.io_bound(starcat.enable_group, d, g)
                ui.notify(f"The catalog part '{g}' is switched on again" if ok else
                          f"The kept files of '{g}' do not fit this catalog: download it again", type="positive"
                          if ok else "warning")
            else:
                ui.notify(f"Downloading the catalog part '{g}' (see the log)")
                await run_process(PYSYZYGOS + ["catalog", "add", g, "--dir", d], pg.log)
            pg.cat_refresh()
            await pg.sys_info_refresh()
            return
        size = starcat.group_bytes(d, g) / 1e9
        built = float(starcat.status(d)["gmax"]) not in starcat.ZENODO_STEM
        back = ("It can come back only with a new build of this catalog from ESA's files (about 2 h)." if built else
                "It can come back with a download (from Zenodo or a mirror).")

        async def done(how):
            dlg.close()
            try:
                if how == "off":
                    await run.io_bound(starcat.disable_group, d, g)
                    ui.notify(f"The catalog part '{g}' is switched off; its files are kept", type="positive")
                elif how == "delete":
                    await run.io_bound(starcat.remove_group, d, g)
                    ui.notify(f"The catalog part '{g}' is deleted ({size:.1f} GB freed)", type="positive")
            except OSError as e:                                # Windows: the file is in use (a run, the GUI)
                ui.notify(f"Not possible now: {str(e)[:160]}. Restart the GUI with no run going, then try again.",
                          type="warning", timeout=10000)
            pg.cat_refresh()                                       # cancel: the checkbox shows the part again
            await pg.sys_info_refresh()

        with ui.dialog().props("persistent") as dlg, ui.card().classes("max-w-xl"):
            ui.label(f"Stop using the catalog part '{g}' ({size:.1f} GB)?").classes("font-semibold")
            ui.label(f"{starcat.GROUP_TEXT[g]}.").classes("text-sm")
            ui.label("Switch off: it is no longer used, its files stay (ticking it again switches it back on at "
                     f"once). Delete: frees {size:.1f} GB. {back}").classes("text-sm text-slate-600")
            with ui.row():
                ui.button("Switch off, keep the files", on_click=lambda: done("off")).props("color=primary")
                ui.button("Delete", on_click=lambda: done("delete")).props("flat color=negative")
                ui.button("Cancel", on_click=lambda: done("cancel")).props("flat")
        dlg.open()
    pg.cat_part = cat_part

    async def cat_update(name, delete_old=True):
        """Bring a format-2 catalog to the newest published data version (setup --update-catalog)."""
        ui.notify("Updating the catalog: see the log for its progress")
        await run_process(PYSYZYGOS + ["setup", "--update-catalog", "--no-geoip", "--dir", name]
                          + (["--delete-old"] if delete_old else []), pg.log)
        d = os.path.join(ROOT, name)
        if starcat.is_format2(d) and not starcat.update_available(d):
            ui.notify(f"{name} is now data version {starcat.data_version(d)}. The page reloads in 5 s.",
                      type="positive", timeout=5000)
            save_ui_state(catalog=name, site=pg.state["name"])
            ui.timer(5.0, ui.navigate.reload, once=True)
        else:
            ui.notify("The update is not finished (see the log); run it again to resume", type="warning")
        opts = catalog_options()
        pg.cat_sel.set_options(opts, value=pg.cat_sel.value if pg.cat_sel.value in opts else None)
        pg.cat_refresh()
        await pg.sys_info_refresh()
    pg.cat_update = cat_update

    def cat_upgrade_ask(name, parts, delete_old):
        """What the upgrade will do (source, time, disk), then run it."""
        d = os.path.join(ROOT, name)
        st = pg.gaia_local.status(d)
        gmax = float(st.get("gmax") or 16)
        new = starcat.staging_dir(d)
        free = shutil.disk_usage(ROOT).free / 1e9
        old_gb = sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(d) for f in fs) / 1e9
        if starcat.is_format2(new):
            how = (f"A finished new catalog is already there ({os.path.basename(new)}, parts: "
                   f"{', '.join(starcat.groups_present(new))}): it is only swapped in, with all its parts.")
        elif gmax in starcat.ZENODO_STEM:
            how = (f"The ready-made G \u2264 {gmax:g} catalog is downloaded (about 3 GB for core + quality, from the "
                   f"fastest of Zenodo and the mirrors), checked and unpacked: a few minutes to half an hour.")
        else:
            how = (f"G \u2264 {gmax:g} is built from ESA's Gaia files: 753 GB streamed, about 2 hours, all parts "
                   f"(a build cannot add parts later). Your computer must stay on and online.")
        with ui.dialog() as dlg, ui.card().classes("max-w-xl"):
            ui.label(f"Upgrade {name} to the new catalog format").classes("font-semibold")
            ui.label(how).classes("text-sm")
            ui.label(f"It is installed next to the old one ({os.path.basename(new)}) and swapped in when complete; "
                     f"searches can go on meanwhile with the old one. Free disk: {free:.0f} GB; the old catalog "
                     f"takes {old_gb:.1f} GB" + (" and is deleted afterwards." if delete_old else
                                                 f" and is kept as {name}.old.")).classes("text-sm text-slate-600")
            with ui.row():
                async def go():
                    dlg.close()
                    await pg.cat_upgrade(name, parts, delete_old)
                ui.button("Upgrade", on_click=go).props("color=primary")
                ui.button("Cancel", on_click=dlg.close).props("flat")
        dlg.open()
    pg.cat_upgrade_ask = cat_upgrade_ask

    async def cat_upgrade(name, parts="quality", delete_old=True):
        ui.notify("Upgrading the catalog: see the log for its progress")
        args = PYSYZYGOS + ["setup", "--upgrade-catalog", "--no-geoip", "--groups", parts, "--dir", name]
        await run_process(args + (["--delete-old"] if delete_old else []), pg.log)
        d = os.path.join(ROOT, name)
        if starcat.is_format2(d):
            ui.notify(f"{name} is now in the new format" + ("; the old catalog is deleted" if delete_old and
                      not os.path.exists(d + ".old") else "") + ". The page reloads in 5 s.", type="positive",
                      timeout=5000)
            save_ui_state(catalog=name, site=pg.state["name"])            # the reloaded page selects it
            ui.timer(5.0, ui.navigate.reload, once=True)              # header list and tabs from the new state
        else:
            ui.notify("The upgrade is not finished (see the log); run it again to resume", type="warning")
        opts = catalog_options()
        pg.cat_sel.set_options(opts, value=pg.cat_sel.value if pg.cat_sel.value in opts else None)
        pg.cat_refresh()
        await pg.sys_info_refresh()
    pg.cat_upgrade = cat_upgrade

    def cat_delete_old(name):
        async def go():
            d.close()
            await run.io_bound(shutil.rmtree, os.path.join(ROOT, name), True)
            ui.notify(f"Deleted {name}", type="positive")
            pg.cat_refresh()

        with ui.dialog() as d, ui.card():
            ui.label(f"Delete {name} (the catalog before the upgrade, with its star indexes and supplement)?")
            with ui.row():
                ui.button("Delete", on_click=go).props("color=negative")
                ui.button("Cancel", on_click=d.close).props("flat")
        d.open()
    pg.cat_delete_old = cat_delete_old

    async def sys_info_refresh():
        import subprocess
        env = dict(os.environ, PYSYZYGOS_HOME=ROOT, PYTHONUTF8="1",
                   PYTHONPATH=os.pathsep.join(x for x in (os.path.dirname(PKG), os.environ.get("PYTHONPATH")) if x))
        if pg.cat_sel.value:
            env["PYSYZYGOS_CATALOG"] = pg.cat_sel.value
        r = await run.io_bound(subprocess.run, PYSYZYGOS + ["info", "--json"], capture_output=True, text=True,
                               stdin=subprocess.DEVNULL,
                               cwd=ROOT, env=env, timeout=120)
        pg.sys_info.clear()
        with pg.sys_info:
            try:
                data = json.loads(r.stdout.strip().splitlines()[-1])
            except (ValueError, IndexError):
                ui.label(f"pysyzygos info failed: {(r.stderr or r.stdout)[-300:]}").classes("text-sm text-red-700")
                return
            for group, rows in data:
                ui.label(group).classes("text-base font-semibold mt-1")
                with ui.grid(columns=2).classes("w-full gap-x-4 gap-y-0").style("grid-template-columns: 16rem 1fr"):
                    for k, v in rows:
                        ui.label(k).classes("text-sm text-slate-500")
                        ui.label(v).classes("text-sm text-slate-800 break-words")
        pg.sys_refresh()
    pg.sys_info_refresh = sys_info_refresh


def connect(pg):
    """Wire the tab up and fill it (run after all tabs' handlers)."""
    pg.off_chk.on_value_change(pg.sys_toggle)

    async def first_open(e):                                    # the update check: once, when the tab is opened
        if e.value in (pg.t_sys, "System") and not pg.upd_checked:
            await pg.upd_check()
    pg.tabs.on_value_change(first_open)
    pg.sys_refresh()
    pg.cat_refresh()
    pg.planets_refresh()
    pg.occ_refresh()
    pg.cat_sel.on_value_change(pg.cat_refresh)
    pg.tabs.on_value_change(lambda e: pg.sys_info_refresh() if e.value in (pg.t_sys, "System") else None)
