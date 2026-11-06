"""gui_system.py - System tab: data in use, star catalog parts and updates, planet kernels, Occult data add-on, offline
copies, cache.

Part of the GUI (gui.py builds the page): panel(pg) adds the tab's controls, handlers(pg) its functions, connect(pg)
wires them up; pg holds the page's elements and functions shared between the tabs.
"""
import html, json, os, shutil, signal, subprocess, sys, time

from pysyzygos import home, starcat
from pysyzygos.home import HOME as ROOT, PKG
from nicegui import run, ui
from pysyzygos.gui_common import PYSYZYGOS, catalog_options, run_process, save_ui_state, load_ui_state

# A catalog build of another G limit from ESA's files (hours): a process of its own, detached from the GUI (it goes on
# when the GUI restarts, and a search or pick can run meanwhile); its state in the data folder, its output in logs/.
BUILD_STATE = "catalog_build.json"


def build_state():
    """The background catalog build (dict: pid, dir, gmax, workers, xref, log, started), or None."""
    try:
        with open(os.path.join(ROOT, BUILD_STATE), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def build_folder(g):
    """A free folder name for a catalog of limit g: gaia_dr3_g18, else gaia_dr3_g18_v2, _v3, ... (an old-format or
    other catalog keeps its folder; an unfinished build of the same name is offered again: it resumes, also one with
    all stars but without the CDS steps (proper motions of the 2-parameter stars, star names))."""
    base = f"gaia_dr3_g{float(g):g}".replace(".", "_")
    for name in [base] + [f"{base}_v{k}" for k in range(2, 10)]:
        d = os.path.join(ROOT, name)
        if not os.path.exists(d) or (os.path.isfile(os.path.join(d, "build.json")) and not starcat.is_format2(d)) \
                or cds_missing(d, g):
            return name
    return base + "_new"


def cds_missing(d, g):
    """A finished catalog of limit g whose CDS steps did not run (CDS down at the end of a build)."""
    try:
        m = starcat._manifest(d)
        return (starcat.is_format2(d) and abs(float(m["gmax"]) - float(g)) < 1e-9
                and (not m.get("pm_xmatch") or "xref" not in starcat.groups_present(d)))
    except (OSError, ValueError, KeyError):
        return False


def pid_alive(pid):
    if os.name == "nt":
        r = subprocess.run(["tasklist", "/FI", f"PID eq {int(pid)}", "/NH"], capture_output=True, text=True)
        return str(int(pid)) in r.stdout
    try:
        os.kill(int(pid), 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def start_build(folder, gmax, workers=6, xref=True, fetch=None, groups=None):
    """Start `pysyzygos catalog build --dir folder --gmax G [--xref]` detached; returns its state. A limit that is
    ready-made (fetch True; None: starcat.ZENODO_STEM, 16 and 18.7) is downloaded instead (`catalog fetch`, the parts
    groups, default all) into a new folder."""
    os.makedirs(os.path.join(ROOT, "logs"), exist_ok=True)
    log = os.path.join("logs", f"catalog_build_{folder}.log")
    if fetch is None:                               # explicit True: also into a folder a stopped download left
        fetch = float(gmax) in starcat.ZENODO_STEM and not os.path.exists(os.path.join(ROOT, folder))
    if fetch:
        groups = groups or ("quality,extras" + (",xref" if xref else ""))
        args = [sys.executable, "-u", "-m", "pysyzygos", "catalog", "fetch", "--dir", folder, "--gmax", f"{gmax:g}",
                "--groups", groups]
    else:
        args = [sys.executable, "-u", "-m", "pysyzygos", "catalog", "build", "--dir", folder, "--gmax", f"{gmax:g}",
                "--workers", str(int(workers))] + (["--xref"] if xref else [])
    env = {k: v for k, v in os.environ.items() if not k.startswith("NICEGUI_")}
    env.update(PYSYZYGOS_HOME=ROOT, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    kw = (dict(creationflags=0x00000008 | 0x00000200) if os.name == "nt"          # DETACHED_PROCESS, NEW_PROCESS_GROUP
          else dict(start_new_session=True))
    with open(os.path.join(ROOT, log), "a", encoding="utf-8") as fh:
        fh.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')}: {' '.join(args[3:])}\n")
        fh.flush()
        p = subprocess.Popen(args, cwd=ROOT, env=env, stdout=fh, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, **kw)
    st = dict(pid=p.pid, dir=folder, gmax=gmax, workers=int(workers), xref=bool(xref), log=log,
              fetch=bool(fetch), groups=args[-1] if fetch else None,
              started=time.strftime("%Y-%m-%d %H:%M:%S"), t0=time.time())
    tmp = os.path.join(ROOT, BUILD_STATE + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(st, fh)
    os.replace(tmp, os.path.join(ROOT, BUILD_STATE))
    return st


def stop_build(st):
    """Stop the build (and its download workers); a later build of the same folder resumes."""
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(int(st["pid"]))], capture_output=True)
    else:
        try:
            os.killpg(int(st["pid"]), signal.SIGTERM)                 # its own session: the workers too
        except (ProcessLookupError, PermissionError):
            pass


def log_tail(path, n=40):
    """The last n lines of a log (a progress line rewritten with \\r counts once, as last shown)."""
    try:
        with open(os.path.join(ROOT, path), "rb") as fh:
            fh.seek(0, 2)
            fh.seek(max(0, fh.tell() - 64000))
            text = fh.read().decode("utf-8", "replace")
    except OSError:
        return []
    lines = [ln.split("\r")[-1].rstrip() for ln in text.split("\n")]
    return [ln for ln in lines if ln.strip()][-n:]


def steps_of(st):
    """starcat.build_steps of the build in st (what it was started with)."""
    return starcat.build_steps(os.path.join(ROOT, st["dir"]), xref=bool(st.get("xref", True)))


def pending(st):
    if st.get("fetch") and not starcat.is_format2(os.path.join(ROOT, st["dir"])):
        return ["download"]                         # a stopped download: Retry resumes it
    return [step for step, state, _ in steps_of(st) if state == "pending"]


def build_progress(st):
    """(running, text) of the background build."""
    running = pid_alive(st["pid"])
    d = os.path.join(ROOT, st["dir"])
    done = starcat.is_format2(d)
    s = starcat.status(d)
    if done:
        stage = (f"stars complete: {s.get('n_stars', 0) / 1e6:.1f} M, {s['gb']:.1f} GB"
                 + (", the later steps are running" if running and pending(st) else ""))
    elif st.get("fetch"):
        stage = "downloading the ready-made catalog (Zenodo / mirror)"
    elif s["total"]:
        stage = (f"{s['done']} of {s['total']} ESA files ({100.0 * s['done'] / s['total']:.0f} %)"
                 + (": merging" if s["done"] == s["total"] else ""))
    else:
        stage = "starting (listing ESA's files)"
    el = time.time() - float(st.get("t0") or time.time())
    tail = log_tail(st["log"], 1)
    return running, (f"{st['dir']} (G \u2264 {st['gmax']:g}): {stage} \u00b7 "
                     + (f"running for {el / 3600:.1f} h" if running else
                        "stopped: steps pending (below), Retry when the service is back" if done and pending(st) else
                        "finished" if done else "stopped: Retry to resume" if st.get("fetch") else
                        "stopped: Build again to resume")
                     + (f" \u00b7 {tail[0][:140]}" if tail else ""))


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
            from pysyzygos import urls as U_
            pg.upd_git = ui.link("Get git (installer)", U_.URL_GIT_DOWNLOAD, new_tab=True).classes("text-sm").tooltip(
                "Git for Windows, macOS or Linux. Then switch this ZIP folder to git (README: 'Installed from the "
                "ZIP? Switch to git'): updates become one click here")
            pg.upd_git.set_visibility(False)
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
            # the ready-made catalogs (Zenodo / mirrors): sizes, installed or not, download (ready_made / start_build)
            with ui.row().classes("items-center gap-3 mt-2"):
                ui.label("Ready-made catalogs (Zenodo, mirror)").classes("text-sm font-medium")
                ui.button("Check online", on_click=lambda: pg.cat_ready_check()).props("flat dense")
            pg.cat_ready = ui.column().classes("w-full gap-1")
            pg.cat_ready_draw(READY["info"] or starcat.ready_made(online=False), READY["online"])
            # another limit (G 18, ...): built from ESA's files in the background (build_state / start_build)
            ui.label("Build a catalog with another limit (from ESA's files, in the background; G \u2264 16 and "
                     "18.7 are ready-made: downloaded from Zenodo instead, all parts)").classes(
                "text-sm font-medium mt-2")
            ui.label("Reads all of ESA's Gaia DR3 files whatever the limit (753 GB of downloads): hours (G \u2264 16 "
                     "took 1 h 49 min, G \u2264 18 holds ~4\u00d7 the stars). It runs on its own: searches and picks "
                     "can run meanwhile, and it goes on when the GUI restarts; a stopped build resumes where it stopped. "
                     "Then choose it in the header's catalog selector.").classes("text-xs text-slate-500")
            with ui.row().classes("items-end gap-3"):
                b_g = ui.number("G limit", value=18.0, min=12.0, max=21.0, step=0.1, format="%.1f").classes("w-24")
                b_dir = ui.input("Folder", value=build_folder(18.0)).classes("w-48")
                b_w = ui.number("Downloads at once", value=6, min=1, max=16, step=1, format="%d").classes("w-36")
                b_x = ui.checkbox("star names (UCAC4 / Tycho / HIP)", value=True).props("dense")
                b_g.on_value_change(lambda e: b_dir.set_value(build_folder(e.value or 18.0)))
                ui.button("Build in the background", on_click=lambda: pg.cat_build_start(
                    b_dir.value, b_g.value, b_w.value, b_x.value)).props("outline dense")
            with ui.row().classes("items-center gap-2 w-full") as pg.cat_build_row:
                pg.cat_build_lbl = ui.label("").classes("text-sm text-slate-700 grow")
                ui.button("Log", on_click=lambda: pg.cat_build_log()).props("flat dense")
                pg.cat_build_stop = ui.button("Stop", on_click=lambda: pg.cat_build_stop_ask()).props(
                    "flat dense color=negative")
                pg.cat_build_retry = ui.button("Retry the missing steps", on_click=lambda: pg.cat_build_retry_go()
                                               ).props("outline dense color=primary")
                pg.cat_build_clear = ui.button("Clear", on_click=lambda: pg.cat_build_dismiss()).props("flat dense")
            pg.cat_build_steps = ui.html("").classes("text-xs")
            pg.cat_build_tick()
    pg.cat_refresh = cat_refresh

    READY = {"info": None, "online": False}         # the last check of the ready-made catalogs (for redraws)
    PARTS = {"quality,xref": "core + quality + star names (recommended)", "quality": "core + quality",
             "none": "core only", "quality,extras,xref": "all parts"}

    def installed(g):
        """Folders in the data folder holding a format-2 catalog of limit g."""
        return [f for f in sorted(os.listdir(ROOT)) if f.startswith("gaia_dr3_") and not f.endswith((".old", ".new"))
                and starcat.is_format2(os.path.join(ROOT, f))
                and abs(float(starcat._manifest(os.path.join(ROOT, f)).get("gmax", -1)) - g) < 1e-9]

    def cat_ready_draw(info, online):
        """One line per ready-made limit: part sizes, where it is (after Check online), installed folder or
        Download with a choice of parts."""
        pg.cat_ready.clear()
        with pg.cat_ready:
            for g, parts in info.items():
                have = installed(g)
                sizes = " \u00b7 ".join(f"{p} {e['size'] / 1e9:.1f} GB" if e["size"] else f"{p} ?"
                                         for p, e in parts.items())
                if online:
                    core = parts["core"]
                    where = ", ".join((["Zenodo"] if core["zenodo"] else []) + core["mirrors"]) or "not available"
                else:
                    where = "Check online for availability"
                known = g in starcat.ZENODO_STEM
                with ui.row().classes("items-center gap-3"):
                    ui.label(f"G \u2264 {g:g}").classes("text-sm font-medium w-16")
                    ui.label(f"{sizes} \u2014 {where}" + ("" if known else " (new: not known to this version)")
                             ).classes("text-sm " + ("text-slate-700" if not online or where != "not available"
                                                     else "text-slate-400"))
                    if have:
                        ui.label(f"installed: {', '.join(have)}").classes("text-sm text-green-800")
                    elif not online or where != "not available":
                        sel = ui.select(PARTS, value="quality,xref").props("dense outlined").classes("w-72")
                        ui.button("Download", on_click=lambda g=g, sel=sel: pg.cat_ready_get(g, sel.value, info)
                                  ).props("outline dense color=primary")
    pg.cat_ready_draw = cat_ready_draw

    async def cat_ready_check():
        """Ask Zenodo (newest version) and the mirrors what is ready-made."""
        n = ui.notification("Asking Zenodo and the mirror \u2026", spinner=True, timeout=None)
        try:
            READY["info"] = await run.io_bound(starcat.ready_made, True)
            READY["online"] = True
        except Exception as e:                       # Zenodo down: the mirrors were not asked either
            n.dismiss()
            ui.notify(f"Zenodo did not answer ({str(e)[:100]}); sizes as known to this version", type="warning")
            return
        n.dismiss()
        pg.cat_ready_draw(READY["info"], True)
    pg.cat_ready_check = cat_ready_check

    def cat_ready_get(g, parts, info):
        """Download a ready-made catalog into a new folder in the background (as a build: progress, Stop, Log)."""
        gb = sum((info[g][p]["size"] or 0) for p in ["core"] + [p for p in parts.split(",") if p != "none"]) / 1e9
        free = shutil.disk_usage(ROOT).free / 1e9
        if gb and free < 2.4 * gb:
            ui.notify(f"Not enough disk space: about {2.4 * gb:.0f} GB needed while unpacking, {free:.0f} GB free",
                      type="warning")
            return
        st = build_state()
        if st and pid_alive(st["pid"]):
            ui.notify(f"A build or download is running ({st['dir']}): one at a time", type="warning")
            return
        folder = build_folder(g)
        st = start_build(folder, g, xref="xref" in parts, fetch=True, groups=parts)
        ui.notify(f"Downloading G \u2264 {g:g} ({gb:.1f} GB) into {folder} in the background; progress below",
                  type="positive", multi_line=True)
        BUILD["running"] = True
        pg.cat_build_tick()
    pg.cat_ready_get = cat_ready_get

    BUILD = {"running": None}                       # the last seen state: a finished build refreshes the header once

    def cat_build_tick():
        """The background build's progress line (every 10 s, and when the section is drawn)."""
        st = build_state()
        row = getattr(pg, "cat_build_row", None)
        if row is None:
            return
        row.set_visibility(st is not None)
        if st is None:
            return
        running, text = build_progress(st)
        pg.cat_build_lbl.text = text
        pg.cat_build_lbl.classes(replace="text-sm grow " + ("text-slate-700" if running else
                                 "text-green-800" if starcat.is_format2(os.path.join(ROOT, st["dir"])) else "text-amber-800"))
        pg.cat_build_stop.set_visibility(running)
        pg.cat_build_clear.set_visibility(not running)
        todo = (starcat.is_format2(os.path.join(ROOT, st["dir"])) or st.get("fetch")) and pending(st)
        pg.cat_build_retry.set_visibility(not running and bool(todo))
        mark = {"done": ("\u2713", "text-green-800"), "pending": ("\u2026" if running else "\u2717", "text-amber-800"),
                "skipped": ("\u2013", "text-slate-500")}
        pg.cat_build_steps.set_content("<br>".join(
            f'<span class="{mark[state][1]}">{mark[state][0]} {html.escape(step)}: {state}'
            f'{" (" + html.escape(detail) + ")" if detail else ""}</span>' for step, state, detail in steps_of(st))
            if not (st.get("fetch") and not starcat.is_format2(os.path.join(ROOT, st["dir"]))) else "")
        if BUILD["running"] and not running:          # just finished or stopped: the header lists it
            opts = catalog_options()
            pg.cat_sel.set_options(opts, value=pg.cat_sel.value if pg.cat_sel.value in opts else None)
            ok = starcat.is_format2(os.path.join(ROOT, st["dir"]))
            ui.notify(f"Catalog {st['dir']} is ready: choose it in the header" if ok else
                      f"The build of {st['dir']} stopped (see Log); Build again to resume",
                      type="positive" if ok else "warning", timeout=0, close_button=True)
        BUILD["running"] = running
    pg.cat_build_tick = cat_build_tick

    def cat_build_start(folder, g, workers, xref):
        folder = str(folder or "").strip()
        st = build_state()
        if st and pid_alive(st["pid"]):
            ui.notify(f"A build is running ({st['dir']}): one at a time", type="warning")
            return
        if not folder.startswith("gaia_dr3_") or os.sep in folder or "/" in folder:
            ui.notify("The folder's name starts with gaia_dr3_ (e.g. gaia_dr3_g18), in the data folder", type="warning")
            return
        d = os.path.join(ROOT, folder)
        if starcat.is_format2(d) and not any(state == "pending" for _, state, _ in starcat.build_steps(d, xref=bool(xref))):
            ui.notify(f"{folder} is a complete catalog already", type="warning")
            return
        if not starcat.is_format2(d) and os.path.isfile(os.path.join(d, "catalog.json")):
            ui.notify(f"{folder} holds a catalog of the old format: choose another folder", type="warning")
            return
        st = start_build(folder, float(g or 18.0), int(workers or 6), bool(xref))
        ui.notify(f"Building {folder} (G \u2264 {st['gmax']:g}) in the background; progress below, output in {st['log']}",
                  type="positive", multi_line=True)
        BUILD["running"] = True
        pg.cat_build_tick()
    pg.cat_build_start = cat_build_start

    def cat_build_retry_go():
        """The same build again: the finished steps are skipped, the pending ones tried once more."""
        st = build_state()
        if st and st.get("fetch"):                    # a stopped download: resumed (the .part file is kept)
            start_build(st["dir"], st["gmax"], xref=st.get("xref", True), fetch=True, groups=st.get("groups"))
            BUILD["running"] = True
            pg.cat_build_tick()
        elif st:
            pg.cat_build_start(st["dir"], st["gmax"], st.get("workers", 6), st.get("xref", True))
    pg.cat_build_retry_go = cat_build_retry_go

    def cat_build_stop_ask():
        st = build_state()
        if not st:
            return

        def go():
            d.close()
            stop_build(st)
            ui.notify(f"Stopping the build of {st['dir']}; Build again to resume", type="warning")
            ui.timer(2.0, pg.cat_build_tick, once=True)
        with ui.dialog() as d, ui.card():
            ui.label(f"Stop the build of {st['dir']}? The files done so far are kept: building the same folder "
                     f"again resumes.")
            with ui.row():
                ui.button("Stop the build", on_click=go).props("color=negative")
                ui.button("Cancel", on_click=d.close).props("flat")
        d.open()
    pg.cat_build_stop_ask = cat_build_stop_ask

    def cat_build_dismiss():
        try:
            os.remove(os.path.join(ROOT, BUILD_STATE))
        except OSError:
            pass
        BUILD["running"] = None
        pg.cat_build_tick()
    pg.cat_build_dismiss = cat_build_dismiss

    def cat_build_log():
        st = build_state()
        if not st:
            return
        with ui.dialog() as d, ui.card().classes("w-[90vw] max-w-[1100px]"):
            ui.label(f"{st['log']} (last lines)").classes("font-semibold")
            ui.code("\n".join(log_tail(st["log"], 60)) or "(empty)").classes("w-full text-xs")
            ui.button("Close", on_click=d.close).props("flat")
        d.open()
    pg.cat_build_log = cat_build_log

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
        pg.upd_git.set_visibility(s.get("kind") == "zip")
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
            pg.upd_info.text = ((f"release {rel.get('tag')} available: download it" if s.get("release_newer") else
                                 "up to date with the releases" if rel else "no update information (offline?)")
                                + " \u00b7 installed from a ZIP: switch it to git for one-click updates and the patch "
                                  "versions between releases (README: 'Installed from the ZIP? Switch to git')")
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
            gb = sum((starcat.ARCHIVE_SHA256.get(starcat.archive_name(gmax, g)) or (0,))[0] or 0
                     for g in ("core", "quality")) / 1e9 or 3.0
            how = (f"The ready-made G \u2264 {gmax:g} catalog is downloaded (about {gb:.0f} GB for core + quality, from "
                   f"the fastest of Zenodo and the mirrors), checked and unpacked: minutes to an hour or more.")
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
    ui.timer(10.0, pg.cat_build_tick)                           # the background catalog build's progress
    pg.tabs.on_value_change(lambda e: pg.sys_info_refresh() if e.value in (pg.t_sys, "System") else None)
