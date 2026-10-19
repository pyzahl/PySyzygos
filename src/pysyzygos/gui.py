"""gui.py - local web interface for PySyzygos (NiceGUI): set up observing sites on a map, run the search or the
pick tool, follow the log, look at the results.

    pysyzygos                            # opens http://127.0.0.1:8080 in the browser (same as: pysyzygos gui)
    pysyzygos --port 8090 --no-browser

It listens on this computer only (127.0.0.1), because it can start programs. Every run is its own process
(`python -m pysyzygos run ...`, pysyzygos/runner.py), so SPICE stays out of the GUI; settings chosen here apply to that run only, pysyzygos_config.py is
not changed. Saving a site rewrites sites.py (comments in it are not kept).
"""
from pysyzygos.version import __version__, __codename__, __author__, __copyright__, __license__, __url__
import argparse, asyncio, csv, json, math, os, re, shutil, sys, time

from pysyzygos import home
from pysyzygos.home import HOME as ROOT, PKG                      # ROOT: the data folder (sites.py, maps/, ...)
os.chdir(ROOT)
from nicegui import app, run, ui
from pysyzygos import geo
from pysyzygos import favorites
from pysyzygos import cameras
from pysyzygos import occultations
from pysyzygos import binaries
from pysyzygos import exports
from pysyzygos import starcat

PY = sys.executable
PYSYZYGOS = [PY, "-u", "-m", "pysyzygos"]                             # how runs are started: PYSYZYGOS + [command, ...]
SITE_KEYS = [  # key, label, default, step  (optional site keys, see sites_example.py)
    ("aperture_cm", "Aperture (cm)", 25.0, 1), ("focal_mm", "Focal length (mm)", None, 10),
    ("mag_adjust", "MagAdjust (mag)", 0.0, 0.1),
    ("sensor_w_mm", "Sensor width (mm)", 5.6, 0.1), ("sensor_h_mm", "Sensor height (mm)", 3.2, 0.1),
    ("frames", "Detection frames", 4, 1),
    ("extinction", "Extinction (mag/airmass)", 0.0, 0.05), ("min_alt", "Min. star altitude (°)", 10.0, 1),
    ("max_sun_alt", "Max. Sun altitude (°)", 0.0, 1), ("reach_km", "Reach (km)", None, 5),
    ("min_dur_s", "Min. duration (s)", 0.4, 0.05), ("max_exp_s", "Longest exposure (s)", 0.64, 0.01),
]


# ---------------------------------------------------------------- sites.py
UI_STATE = os.path.join(ROOT, "gui_state.json")                  # last selected site and catalog (data folder)


def load_ui_state():
    try:
        with open(UI_STATE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_ui_state(**kw):
    """Remember GUI choices across restarts (gui_state.json in the data folder, written atomically)."""
    import tempfile
    st = dict(load_ui_state(), **kw)
    try:
        fd, tmp = tempfile.mkstemp(dir=ROOT, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(st, f)
        os.replace(tmp, UI_STATE)
    except OSError:
        pass


from pysyzygos.sitesfile import load_sites, save_sites       # sites.py (saving fills each site's geoid height)


def mag_limit(s):
    """Faintest star searched, as in pysyzygos_config.py (OWC criterion at the longest usable exposure)."""
    if s.get("mag_limit"):
        return float(s["mag_limit"])
    return round(5 * math.log10(s.get("aperture_cm", 25.0)) + 2.5 * math.log10(s.get("max_exp_s", 0.64)) + 8.5
                 + s.get("mag_adjust", 0.0), 1)


def fov(s):
    focal = s.get("focal_mm") or 100.0 * s.get("aperture_cm", 25.0)
    sw, sh = s.get("sensor_mm", (5.6, 3.2))
    return tuple(2 * math.degrees(math.atan(x / 2 / focal)) * 60 for x in (sw, sh))


# ---------------------------------------------------------------- processes
class Job:
    proc = None                    # the main job: search, pick, pre-screen, setup, report, catalog (one at a time)
    fav = None                     # the Favorites tab's own tasks (path verification): independent of the main job


SUPPLEMENT = dict(on=True)          # header "+ high-RUWE stars": every run gets PYSYZYGOS_SUPPLEMENT (gaia_local)


def catalog_options(found=None):
    """{folder: label} of the catalogs in the data folder for the header's selector (old format and incomplete
    ones marked)."""
    from pysyzygos import gaia_local
    found = gaia_local.find_catalogs(ROOT) if found is None else found
    return {d: f"{d} (G \u2264 {g:g}, " + (f"v{starcat.data_version(os.path.join(ROOT, d))}"
                                          if starcat.is_format2(os.path.join(ROOT, d)) else "old format") + ")"
            + ("" if ok else f", incomplete {gaia_local.status(os.path.join(ROOT, d))['done']}"
                             f"/{gaia_local.status(os.path.join(ROOT, d))['total']}")
            for d, g, ok, _ in found}


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


async def run_process(args, log, env_site=None, on_done=None, env_catalog=None, slot="proc"):
    """Run a PySyzygos command as a subprocess, its output into log. slot: "proc" (the main job: one at a time) or
    "fav" (the Favorites tab's tasks: one at a time among themselves, independent of the main job)."""
    cur = getattr(Job, slot)
    if cur and cur.returncode is None:
        ui.notify("A run is already in progress" if slot == "proc" else
                  "A favorites task is already running (see the log on this tab)", type="warning")
        return None
    env = dict(os.environ, PYTHONUNBUFFERED="1", PYSYZYGOS_HOME=ROOT,
               PYTHONUTF8="1", PYTHONIOENCODING="utf-8")       # UTF-8 output on every system (log: decoded as UTF-8)
    env["PYTHONPATH"] = os.pathsep.join(x for x in (os.path.dirname(PKG), env.get("PYTHONPATH")) if x)   # not installed
    if env_site:
        env["PYSYZYGOS_SITE"] = env_site
    if env_catalog:
        env["PYSYZYGOS_CATALOG"] = env_catalog
    env["PYSYZYGOS_SUPPLEMENT"] = "1" if SUPPLEMENT["on"] else "0"
    def push(text):
        # the page can be gone (browser closed, reloaded or stalled past the reconnect timeout): keep going without it,
        # and keep reading the output, or the process blocks on a full pipe and stays "in progress" forever
        try:
            log.push(text)
        except RuntimeError:
            pass

    push(f"$ {' '.join(args)}" + (f"   (site {env_site})" if env_site else "")
         + (f"   (catalog {env_catalog})" if env_catalog else ""))
    t0 = time.time()
    proc = await asyncio.create_subprocess_exec(*args, cwd=ROOT, env=env, stdout=asyncio.subprocess.PIPE,
                                                stderr=asyncio.subprocess.STDOUT,
                                                stdin=asyncio.subprocess.DEVNULL)   # never waits for an answer:
    # without it the run inherits the terminal the GUI was started from, and setup's questions (no line end, so
    # not shown in the log) wait forever (found 2026-10-17 with "Install the new catalog")
    setattr(Job, slot, proc)
    async for line in proc.stdout:
        push(line.decode(errors="replace").rstrip())
    rc = await proc.wait()
    push(f"--- finished with exit code {rc} in {time.time() - t0:.0f} s")
    if on_done:
        try:
            await on_done(rc)
        except RuntimeError:                                     # page gone: results stay in their files (picks/, ...)
            pass
    return rc


def stop_process(log, slot="proc"):
    p = getattr(Job, slot)
    if p and p.returncode is None:
        p.terminate()
        log.push("--- stopped")


# ---------------------------------------------------------------- resizable list boxes
RESIZE_JS = """<script>
// list boxes the user can make taller or shorter (drag the bottom-right corner): .pyo-resize[data-key][data-vh].
// The height is saved only after a drag, as a share of the window height, and restored only when plausible
// (25-92 % of the window); otherwise the box keeps its default. (Saving on every size change stored the box's
// minimum height while the tab was being laid out, so after a restart only a sliver of the list was left.)
(function(){
 var LO=25,HI=92;
 function vh(px){return 100*px/window.innerHeight;}
 function setup(b){if(b.dataset.ready)return;b.dataset.ready='1';var k='pysyzygos_box_'+b.dataset.key;
  try{var v=parseFloat(localStorage.getItem(k));if(v>=LO&&v<=HI)b.style.height=v+'vh';}catch(e){}
  var h0=null;
  b.addEventListener('pointerdown',function(){h0=b.offsetHeight;});
  document.addEventListener('pointerup',function(){if(h0===null)return;var h=b.offsetHeight;
   if(Math.abs(h-h0)>4&&h>0){var v=Math.min(HI,Math.max(LO,vh(h)));b.style.height=v+'vh';
    try{localStorage.setItem(k,v.toFixed(1));}catch(e){}}h0=null;});}
 function scan(){document.querySelectorAll('.pyo-resize[data-key]').forEach(setup);}
 scan();setInterval(scan,1000);
})();
</script>"""


def resizable_box(key, default_vh, scroll=False):
    """A box for a list (iframe or table) whose height the user drags at its bottom-right corner, remembered per box
    in the browser (RESIZE_JS). scroll=True: the content scrolls inside (tables); else it fills the box (iframes)."""
    return ui.element("div").classes("w-full pyo-resize").props(f'data-key="{key}"').style(
        f"height: {default_vh}vh; min-height: 160px; resize: vertical; padding-bottom: 14px; "
        f"overflow: {'auto' if scroll else 'hidden'}; border: 1px solid #ddd; background: #f1f5f9")


# ---------------------------------------------------------------- page
@ui.page("/")
def index():
    from pysyzygos import config
    sites, default_site = load_sites()
    last = load_ui_state()                                       # the site and catalog chosen last time
    state = dict(name=last["site"] if last.get("site") in sites else default_site)
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
        sel = ui.select(list(sites), value=state["name"]).props("dark dense options-dense standout").classes("w-48")
        from pysyzygos import gaia_local
        found = gaia_local.find_catalogs(ROOT)
        complete = {d for d, g, ok, _ in found if ok}
        cat_gmax = {d: float(g) for d, g, ok, _ in found if g is not None}
        cats = catalog_options(found)
        ui.label("Catalog:").classes("text-slate-300")
        cat_sel = ui.select(cats, value=last["catalog"] if last.get("catalog") in complete else
                            config.gaia_local_dir if config.gaia_local_dir in complete else
                            (min(complete) if complete else (next(iter(cats)) if cats else None))
                            ).props("dark dense options-dense standout").classes("w-64").tooltip(
            "Local Gaia catalogs in the project folder. Install or add one with: pysyzygos setup [--gmax 16]")
        SUPPLEMENT["on"] = bool(last.get("supplement", True))
        sup_chk = ui.checkbox("+ high-RUWE stars", value=SUPPLEMENT["on"]).props("dark dense").classes(
            "text-slate-300")
        ui.button("About", on_click=lambda: about.open()).props("flat dense color=white no-caps")
        ui.button(icon="power_settings_new", on_click=lambda: quit_dialog()).props(
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

    with ui.dialog() as about, ui.card().classes("max-w-xl"):
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
            ui.button("Close", on_click=lambda: about.close()).props("flat")
    with ui.tabs().classes("w-full") as tabs:
        t_site, t_pick = ui.tab("Site"), ui.tab("Pick")
        t_bod = ui.tab("Planets & Moons")
        t_search, t_res = ui.tab("Search"), ui.tab("Results")
        t_fav = ui.tab("Favorites")
        t_sys = ui.tab("System")
    log_card = None

    with ui.tab_panels(tabs, value=t_site).classes("w-full"):
        # ------------------------------------------------ site
        with ui.tab_panel(t_site):
            with ui.row().classes("w-full items-end gap-4"):
                site_title = ui.label().classes("text-lg font-semibold")
                new_name = ui.input("New site name").classes("w-48")
                ui.button("Add site", on_click=lambda: add_site()).props("outline")
                is_default = ui.checkbox("Default for command-line runs").tooltip(
                    "default_site in sites.py: used by `pysyzygos search` / `pysyzygos pick` run without the GUI")
                ui.button("Save sites.py", on_click=lambda: save()).props("color=primary")
                ui.button("Remove site", on_click=lambda: remove_site()).props("outline color=negative").tooltip(
                    "Remove the site selected at the top right from sites.py (asks first; saved at once)")
                unsaved = ui.label().classes("text-sm text-amber-700")
            with ui.row().classes("w-full no-wrap gap-4"):
                with ui.column().classes("w-1/2"):
                    m = ui.leaflet(center=(40.7, -74.0), zoom=9).classes("w-full").style("height: 430px")
                    marker = m.marker(latlng=(40.7, -74.0))
                    with ui.row().classes("w-full items-end"):
                        q = ui.input("Find a place").classes("grow")
                        ui.button("Search", on_click=lambda: find_place()).props("outline")
                        ui.button("My IP location", on_click=lambda: ip_loc()).props("outline")
                    hits = ui.column().classes("w-full gap-1")
                    occ = geo.mpc_observatories()               # MPC observatory codes (downloaded once into data/)
                    with ui.row().classes("w-full no-wrap gap-4"):
                        occ_sel = ui.select({i: f"{x['code']} {x['name']}" for i, x in enumerate(occ)},  # searchable:
                                                                                      # code and name only
                                            with_input=True, clearable=True,
                                            label="MPC observatory (type code or name)" if occ else
                                            "MPC observatory list: not available (offline?)").classes("w-1/2").props(
                            "dense options-dense" + ("" if occ else " disable")).tooltip(
                            f"{len(occ)} observatories with their official MPC codes (Minor Planet Center): sets position, "
                            "elevation, description and MPC code; the equipment stays as it is")
                        cam_sel = ui.select({i: cameras.label(c) for i, c in enumerate(cameras.SENSORS)},
                                            with_input=True, clearable=True,
                                            label="Sensor (cameras; type a name)").classes(
                            "grow").props("dense options-dense").tooltip(
                            "Sensors common in occultation work, each with the cameras built with it (MM / MC, M / C: "
                            "the mono and color versions of a camera, same sensor size). Picking one fills sensor "
                            "width and height, computed from pixel count and pixel size. Not listed, or a cropped "
                            "readout: enter width and height yourself")
                    ui.button("Add as new site", on_click=lambda: add_site()).props("outline").tooltip(
                        "Add the current map site (position, description, MPC code and the equipment in the form) as a "
                        "new site to the site selector at the top right, named as in 'New site name'; saved at once")
                    ui.label("Click the map to set the position; the elevation is looked up. "
                             "Use an exact position (GPS, map) for observing.").classes("text-xs text-slate-500")
                with ui.column().classes("w-1/2"):
                    with ui.row().classes("w-full no-wrap gap-4"):
                        desc = ui.input("Description").classes("grow")
                        mpc = ui.input("MPC code").classes("w-28").tooltip(
                            "The site's official Minor Planet Center observatory code, if it has one (kept in sites.py "
                            "as mpc_code; filled in when you pick an observatory below)")
                    with ui.row():
                        paste_tip = ("Paste coordinates in any usual format into Latitude, Longitude or Elevation, "
                                     "e.g. Lng: -121° 57' 19\", Lat: +37° 01' 27\", Alt: 132 m  or  37.02417, "
                                     "-121.95528  or  37°01'27\"N 121°57'19\"W: all three fields are filled (the "
                                     "elevation is looked up if not given)")
                        lat = ui.number("Latitude (°)", format="%.5f", step=0.0001).tooltip(paste_tip)
                        lon = ui.number("Longitude (°, east +)", format="%.5f", step=0.0001).tooltip(paste_tip)
                        ele = ui.number("Elevation (m)", format="%.0f", step=1).tooltip(paste_tip)
                        ele_ref = ui.select({"msl": "above sea level", "ellipsoid": "above WGS84 ellipsoid"},
                                            value="msl", label="Elevation is").tooltip(
                            "Maps, Open-Meteo and most GPS displays give the height above mean sea level; PySyzygos "
                            "adds the geoid's height there (EGM96, saved in sites.py as geoid_m). MPC observatory "
                            "codes (and GPS set to ellipsoid height) give it above the WGS84 ellipsoid already.")
                    fields = {}
                    with ui.grid(columns=3).classes("w-full"):
                        for key, label, default, step in SITE_KEYS:
                            fields[key] = ui.number(label, value=default, step=step)
                    derived = ui.label().classes("text-sm text-slate-600")
                    with ui.expansion("Horizon (optional): trees, buildings, hills").classes("w-full") as hz_exp:
                        ui.label("Load OccultWatcher's UserHorizon.txt (the same file works in both programs) for "
                                 "the site in this form, then save the site: events whose star is behind your horizon "
                                 "are marked \u26f0 yellow, those closer to it than the margin red, in the results and "
                                 "favorites. A file with several stations: the one named like the site, else the "
                                 "first.").classes(
                            "text-xs text-slate-500")
                        with ui.row().classes("items-center gap-3"):
                            ui.upload(label="Load UserHorizon.txt", auto_upload=True,
                                      on_upload=lambda e: hz_upload(e)).props("accept=.txt flat dense").classes("w-56")
                            hz_margin = ui.number("Margin (°)", value=15, min=0, max=45, step=1).classes("w-28").tooltip(
                                "A star closer than this to the horizon line, in any direction, is marked (red); "
                                "OccultWatcher's default warning threshold is 15°")
                            hz_filter = ui.checkbox("leave out events behind it").tooltip(
                                "Otherwise they are kept and marked yellow (as OccultWatcher does)")
                            ui.button("Remove", on_click=lambda: hz_set(None)).props("flat dense color=negative")
                        with ui.row().classes("items-center gap-3"):
                            ui.upload(label="Load a 360° photo", auto_upload=True,
                                      on_upload=lambda e: pano_upload(e)).props(
                                "accept=.jpg,.jpeg,.png flat dense").classes("w-56").tooltip(
                                "Equirectangular (2:1), as a 360° camera or a phone's photo sphere saves it, taken "
                                "level at the telescope. With the sky made transparent (PNG), the horizon line can be "
                                "read from it")
                            hz_az = ui.number("Azimuth at the photo's left edge (°)", value=0, min=0, max=360,
                                              step=0.5).classes("w-56").on_value_change(lambda e: hz_draw())
                            hz_fit = ui.button("Fit to the horizon line", on_click=lambda: pano_fit()).props(
                                "flat dense").tooltip("Turn the photo so that its horizon lies best on the horizon "
                                                      "points above (needs a photo with transparent sky)")
                            hz_from = ui.button("Horizon from the photo", on_click=lambda: pano_points()).props(
                                "flat dense").tooltip("The horizon points from the photo's transparent sky (whole "
                                                      "degrees, as UserHorizon.txt); replaces the points above")
                            hz_dl = ui.button("UserHorizon.txt", on_click=lambda: hz_download()).props(
                                "flat dense").tooltip("Download the horizon as OccultWatcher's UserHorizon.txt")
                            ui.button("Remove photo", on_click=lambda: pano_set(None)).props(
                                "flat dense color=negative")
                        hz_info = ui.label().classes("text-sm text-slate-600")
                        hz_pic = ui.html("")

        # ------------------------------------------------ search
        with ui.tab_panel(t_search):
            site_note_s = ui.label().classes("text-sm text-slate-600")
            with ui.row().classes("items-end gap-4"):
                s_start = ui.input("Start (UTC date)", value=today_utc()).props("type=date")
                s_days = ui.number("Days", value=config.days, min=1, step=1)
                s_mag = ui.number("Star G limit", step=0.1, min=6, max=21).classes("w-28").tooltip(
                    "Faintest star (Gaia G) searched. Default: from the site's telescope (aperture, detection frames, longest "
                    "exposure, MagAdjust; Site tab), capped at the catalog's limit; change it for one run")
                ui.button("↺", on_click=lambda: mag_reset("search")).props("flat dense").tooltip(
                    "Back to the site's default star limit")
                s_drop = ui.number("Min. drop (mag)", value=getattr(config, "min_mag_drop", 0.1), step=0.05)
            s_mag_note = ui.label().classes("text-xs text-slate-500")
            s_use_file = ui.switch("Targets from the saved pick of this site (Pick tab)", value=True).tooltip(
                "Uses the newest saved pick of the selected site whose window covers the search window; "
                "without one, targets.py or the list in pysyzygos_config.py")
            targets_warn_s = ui.label().classes("text-sm w-full")
            s_targets = ui.textarea("Targets (asteroid numbers, comma or space separated)",
                                    value=", ".join(config.targets)).classes("w-full")
            with ui.row():
                s_fresh = ui.checkbox("Start a fresh results list", value=True).tooltip(
                    "On: the Results tab shows only this search (a new series in the results database; older "
                    "results stay in pysyzygos.db). Off: add this search's events to the current list")
                s_maps = ui.checkbox("KML maps", value=bool(config.write_maps))
                s_prev = ui.checkbox("Previews", value=bool(getattr(config, "write_previews", True)))
            with ui.row().classes("items-center"):
                ui.label("Astrometric corrections of the star:").classes("text-sm text-slate-600")
                s_plx = ui.checkbox("Stellar parallax", value=bool(getattr(config, "star_parallax", True))).tooltip(
                    "The star as seen from the Earth, not the Sun (Gaia parallax); up to several km on the path")
                s_defl = ui.checkbox("Light deflection (Sun, Jupiter, Saturn)",
                                     value=bool(getattr(config, "light_deflection", True))).tooltip(
                    "Gravitational light bending, star minus asteroid; up to ~6 km away from opposition. "
                    "Both off reproduce results before version 0.10.0")
                s_dbl = ui.checkbox("Online Gaia check of the event stars",
                                    value=bool(getattr(config, "gaia_online_check", True))).tooltip(
                    "After the search, one query to the Gaia archive: Gaia's double-star hints for each event star, "
                    "and close neighbours the local catalog leaves out. Close neighbours from the local catalog "
                    "are always checked. Skipped when offline")
            with ui.row():
                ui.button("Run search", on_click=lambda: run_search()).props("color=primary")
                ui.button("Stop", on_click=lambda: stop_process(log)).props("outline color=negative")

        # ------------------------------------------------ pick
        with ui.tab_panel(t_pick):
            site_note_p = ui.label().classes("text-sm text-slate-600")
            with ui.row().classes("items-end gap-4"):
                p_start = ui.input("Start (UTC date)", value=today_utc()).props("type=date").classes("w-36")
                p_days = ui.number("Days", value=config.days, min=1, step=1).classes("w-28")
                p_mag = ui.number("Star G limit", step=0.1, min=6, max=21).classes("w-28").tooltip(
                    "Faintest star (Gaia G) searched. Default: from the site's telescope (aperture, detection "
                    "frames, longest exposure, MagAdjust; Site tab), capped at the catalog's limit; change it for one "
                    "pick run. Above G 15 the first pick builds a deeper star index once (a few minutes)")
                ui.button("↺", on_click=lambda: mag_reset("pick")).props("flat dense").tooltip(
                    "Back to the site's default star limit")
                p_hmax = ui.number("H below", value=getattr(config, "pick_hmax", 17.0), step=0.5).classes(
                    "w-28").tooltip(
                    "Only asteroids with H below this are screened (fainter H = smaller asteroids; more asteroids "
                    "take longer). An asteroid with a larger H is never found by the pick, but the search finds it if "
                    "you enter its number")
                p_all = ui.checkbox("All numbered (slow)")
                p_top = ui.number("Targets (top)", value=40, min=1, step=5).classes("w-28")
                p_workers = ui.number("Workers", value=max(1, (os.cpu_count() or 2) // 2), min=1, step=1).classes(
                    "w-28")
                p_sort = ui.select(["mag", "date", "margin", "drop"], value="mag", label="Rank by").classes("w-28")
                p_pre = ui.select(dict(PRE_FIXED), value="auto", label="Asteroids").classes("w-80").tooltip(
                    "auto: if a pre-screen fits (its region holds the site, its window this pick's window, its limits "
                    "are as loose), only its asteroids are screened: the same events, much faster; else all. "
                    "all: every asteroid, for any place and time (slower, no pre-screen needed). "
                    "Or one pre-screen by name (listed if it fits)")
            p_mag_note = ui.label().classes("text-xs text-slate-500")
            with ui.row().classes("items-center"):
                ui.button("Run pick", on_click=lambda: run_pick()).props("color=primary")
                ui.button("Stop", on_click=lambda: stop_process(log)).props("outline color=negative")
                pre_info = ui.label().classes("text-sm text-slate-600")
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
                    ps_start = ui.input("Start (UTC date)", value=today_utc()).props("type=date").classes("w-36")
                    ps_days = ui.number("Days", value=30, min=1, step=1).classes("w-24")
                    ps_where = ui.select(prescreen_regions(), value="sites", label="Region").classes(
                        "w-60").tooltip(
                        "Around this site / all my sites: a box this many km around them (Box). A named region: its "
                        "lat/lon box (Box not used). Whole Earth stores the shadow's path of every event (~1 GB per "
                        "month at G 16, less with a brighter star limit), so a pick at any site tests it in seconds; "
                        "command line: 'pysyzygos prescreen extract' cuts a region file from it")
                    ps_km = ui.number("Box (km)", value=300, min=50, step=50).classes("w-28").tooltip(
                        "The region is a latitude/longitude box (a rectangle on the map, not a circle): this many km "
                        "north, south, east and west of the site (around all sites: of every site, at least this "
                        "far everywhere). Around one site the poleward edge is a little narrower in km (about 465 of "
                        "500 km at 41 N). Events count if the shadow path comes within the asteroid's radius + 200 km "
                        "(reach) of the box, so the effective region is the box widened by 200 km or more")
                    ps_where.on_value_change(lambda e: ps_km.set_visibility(e.value in ("site", "sites")))
                    ps_fresh = ui.checkbox("Start over").tooltip(
                        "Discard a stopped build of the same name and window instead of resuming it (needed when "
                        "the build format changed after an update)")
                    ui.button("Build pre-screen", on_click=lambda: run_prescreen()).props("outline")
                    ui.button("Delete selected", on_click=lambda: delete_prescreens()).props(
                        "flat dense color=negative")
                ps_cols = [dict(name=k, label=lbl, field=k, sortable=True, align="left") for k, lbl in
                           (("name", "Name"), ("window", "Window"), ("region", "Region"), ("sites", "Sites inside"),
                            ("limits", "Limits"), ("found", "Asteroids / events"), ("age", "Built"), ("fits", "This pick"))]
                ps_table = ui.table(columns=ps_cols, rows=[], row_key="path", selection="multiple").classes(
                    "w-full").props("flat dense")
            with ui.row().classes("w-full items-center gap-4"):
                p_saved = ui.select({}, label="Saved picks of this site").classes("w-96")
                ui.button("Use for search", on_click=lambda: use_saved()).props("outline").tooltip(
                    "Set the search window to this pick's window and go to the Search tab")
                ui.button("Reload", on_click=lambda: load_pick()).props("flat dense")
                ui.button("CSV", on_click=lambda: pick_csv()).props("outline dense").tooltip(
                    "Download the selected pick's events as a CSV table."
                    " Columns: csv_exports.py in the data folder (default: as the table shows them; any log column can be added)")
            pick_info = ui.label().classes("text-sm text-slate-600 w-full")
            targets_info = ui.label().classes("text-sm text-slate-600 w-full")
            cols = [dict(name=k, label=lbl, field=k, sortable=True, align="left") for k, lbl in
                    (("target", "Target"), ("number", "#"), ("name", "Asteroid"), ("H", "H"), ("utc", "UT"),
                     ("star_mag", "G"), ("drop", "Drop"), ("dur_s", "Dur (s)"), ("mag_margin", "Margin"),
                     ("miss_km", "Miss (km)"), ("star_alt", "Alt"))]
            with resizable_box("pick", 55, scroll=True):                # drag the corner to resize (remembered)
                p_table = ui.table(columns=cols, rows=[], row_key="key", pagination=0).classes("w-full").props(
                    "flat dense")

        # ------------------------------------------------ planets & moons (bodies.py)
        with ui.tab_panel(t_bod):
            site_note_b = ui.label().classes("text-sm text-slate-600")
            from pysyzygos import bodies as bodies_mod
            b_checks, b_small = {}, {}
            with ui.row().classes("items-start gap-6"):
                for grp in bodies_mod.GROUPS:
                    major, small = bodies_mod.featured(grp)
                    with ui.column().classes("gap-0"):
                        ui.label(f"{grp.capitalize()} system").classes("font-semibold")
                        for t in major:
                            kind = bodies_mod.kind(t)
                            b_checks[t] = ui.checkbox(f"{bodies_mod.name(t)}" + (f" ({kind})" if kind != "moon" else ""),
                                                      value=(grp == "jupiter")).props("dense")
                        if small:
                            b_small[grp] = ui.checkbox(f"smaller moons ({len(small)})", value=False).props(
                                "dense").tooltip(", ".join(bodies_mod.name(t) for t in small[:40])
                                                 + (" ..." if len(small) > 40 else "")
                                                 + ": like small asteroids (faint, narrow paths, less certain orbits)")
                with ui.column().classes("gap-0"):
                    ui.label("Coming").classes("font-semibold text-slate-400")
                    ui.label("Earth's Moon").classes("text-sm text-slate-400")
            with ui.row().classes("items-end gap-4"):
                b_start = ui.input("Start (UTC date)", value=today_utc()).props("type=date").classes("w-36")
                b_days = ui.number("Days", value=30, min=1, step=1).classes("w-28")
                b_mag = ui.number("Star G limit", step=0.1, min=6, max=21).classes("w-28").tooltip(
                    "Faintest star (Gaia G) searched. Default: from the site's telescope (aperture, detection frames, longest "
                    "exposure, MagAdjust; Site tab), capped at the catalog's limit; change it for one run. "
                    "Planets have no drop limit (any star they cover disappears); moons also need the min. drop")
                ui.button("↺", on_click=lambda: mag_reset("bodies")).props("flat dense").tooltip(
                    "Back to the site's default star limit")
                b_drop = ui.number("Moons: min. drop (mag)", value=getattr(config, "min_mag_drop", 0.1),
                                   step=0.05).classes("w-36").tooltip(
                    "Moons are bright (about mag 5 for Jupiter's): only bright stars give a measurable drop")
                b_fresh = ui.checkbox("Start a fresh list", value=True)
            b_mag_note = ui.label().classes("text-xs text-slate-500")
            with ui.row():
                ui.button("Run", on_click=lambda: run_bodies()).props("color=primary")
                ui.button("Stop", on_click=lambda: stop_process(log)).props("outline color=negative")
                ui.button("Rebuild report", on_click=lambda: build_bodies_report()).props("outline")
                ui.link("Open in a new tab", "/out/bodies_report.html", new_tab=True).classes("self-center")
                ui.button("CSV", on_click=lambda: bodies_csv()).props("outline dense").tooltip(
                    "Download these events with disappearance and reappearance times."
                    " Columns: csv_exports.py in the data folder (default: as the table shows them; any log column can be added)")
            ui.label("Disappearance (D) and reappearance (R) at your site, from JPL Horizons positions (a small "
                     "kernel per window). The results are their own list (bodies_log.csv), apart from the asteroid "
                     "search.").classes("text-xs text-slate-500")
            with resizable_box("bodies", 60):
                b_frame = ui.element("iframe").style("width: 100%; height: 100%; border: 0; display: block")

        # ------------------------------------------------ results
        with ui.tab_panel(t_res):
            with ui.row().classes("items-center"):
                ui.button("Rebuild report", on_click=lambda: build_report()).props("outline")
                if getattr(config, "owc_lookup", False):                  # experimental, set in pysyzygos_config.py
                    ui.button("Check OWC", on_click=lambda: owc_check("results")).props("outline dense").tooltip(
                        "Look these events up in OccultWatcher Cloud: prediction feeds (tags) and signed-up stations, "
                        "shown under the asteroid with a link to the OWC event page (one request per second)")
                ui.link("Open in a new tab", "/out/hits_report.html", new_tab=True)
                ui.button("CSV", on_click=lambda: hits_csv()).props("outline dense").tooltip(
                    "Download the search results as a CSV table."
                    " Columns: csv_exports.py in the data folder (default: as the table shows them; any log column can be added)")
                ui.checkbox("KStars/Stellarium: set its location to the event site", value=KSTARS_OPT["set_location"],
                            on_change=lambda e: KSTARS_OPT.update(set_location=bool(e.value))).tooltip(
                    "The report's KStars buttons (Linux, KStars running) and Stellarium buttons (Remote Control "
                    "plugin). Off: they keep their location (KStars tells you if that is far from the site).")
            with resizable_box("results", 75):                            # drag the corner to resize (remembered)
                frame = ui.element("iframe").style("width: 100%; height: 100%; border: 0; display: block")

        # ------------------------------------------------ favorites
        with ui.tab_panel(t_fav):
            with ui.row().classes("w-full items-center gap-4"):
                fav_info = ui.label().classes("text-sm text-slate-600")
                ui.button("Reload", on_click=lambda: load_favs()).props("flat dense")
                ui.link("Open in a new tab", "/fav/favorites.html", new_tab=True)
                pc_chk = ui.checkbox("Path verification", value=bool(load_ui_state().get("path_check", False))).tooltip(
                    "Show the tools to compare a favorite's geodetic path with Occult's path listing (pathcheck.py; "
                    "method: VERIFICATION.md section 3)")
                ui.button("CSV", on_click=lambda: fav_csv()).props("outline dense").tooltip(
                    "Download all favorites as a table, named favorites_<today>.csv."
                    " Columns: csv_exports.py in the data folder (default: as the table shows them; any log column can be added). "
                    "The full table with all columns stays in favorites/favorites.csv")
                if getattr(config, "owc_lookup", False):                  # experimental, set in pysyzygos_config.py
                    ui.button("Check OWC", on_click=lambda: owc_check("favorites")).props("outline dense").tooltip(
                        "Look the favorites up in OccultWatcher Cloud: prediction feeds (tags) and signed-up stations "
                        "(one request per second)")
            ui.label("Add events with the ☆ button in the Results report (opened from this GUI). Each favorite keeps "
                     "its own copy of map and preview, so later searches do not change it. Click a row for its preview, "
                     "map and note below; check rows for the actions above the table. Drag the table's bottom-right corner to make "
                     "it taller or shorter (remembered).").classes("text-xs text-slate-500")
            with resizable_box("favorites", 60):                          # drag the corner to resize (remembered)
                f_frame = ui.element("iframe").style("width: 100%; height: 100%; border: 0; display: block")
            with ui.column().classes("w-full gap-3") as f_detail:
                with ui.row().classes("w-full no-wrap gap-4 items-stretch"):
                    f_img = ui.element("img").style("width: 420px; max-width: 45vw; border: 1px solid #ddd")
                    f_map = ui.leaflet(center=(40.7, -74.0), zoom=9).classes("grow").style(   # as tall as the
                        "height: calc(min(420px, 45vw) * 634 / 560); border: 1px solid #ddd")    # preview (560x634)
                    f_nomap = ui.label("No map copied for this event.").classes("text-sm text-slate-500")
                with ui.row().classes("gap-3 items-center text-xs text-slate-600") as f_legend:   # no ui.html:
                    for sym, col, txt in (("━", "#15803d", "centre line"), ("━", "#dc2626", "shadow limits"),  # its
                                          ("┄", "#7c3aed", "1σ"), ("╌", "#d97706", "3σ")):         # signature differs
                        with ui.row().classes("gap-1 items-center"):                              # across versions
                            ui.label(sym).style(f"color: {col}; font-weight: 700")
                            ui.label(txt)
                    ui.label("marker: site")
                with ui.column().classes("w-full"):
                    f_title = ui.label().classes("text-lg font-semibold")
                    f_bar = ui.html("").tooltip(
                        "Across the path at your site: green the shadow, orange out to 1 sigma beyond its edges "
                        "(the path's uncertainty: orbit and star), black the 3-sigma limits; the blue mark is your "
                        "site, with its distance from the centre line and the chance that the shadow covers it")
                    f_pano = ui.html("").classes("w-full").tooltip(
                        "Your site's 360° photo (Site tab, Horizon): the star at the event time (red ring), the "
                        "horizon line (white) and the margin (dashed)")
                    f_info = ui.grid(columns=4).classes("w-full gap-x-6 gap-y-1")   # OWC-style event summary
                    with ui.row().classes("w-full no-wrap gap-6 items-start"):
                        f_err = ui.element("img").style("width: 300px; flex: none").tooltip(
                            "Uncertainty ellipses (sky plane, 1 sigma) at one scale: the target's (JPL Horizons), the star's "
                            "(Gaia DR3, carried to the event date; '!' = a typical star of that G when Gaia's errors "
                            "are not at hand) and the combined one, which moves the path. Only the part across the "
                            "target's motion (dashed) shifts the path on the ground")
                        with ui.column().classes("grow"):
                            f_occ = ui.label().classes("text-sm text-slate-600").tooltip(
                                "Earlier occultations of this asteroid in NASA's archive of observed occultations (PDS "
                                "Small Bodies Node; Herald, Dunham et al.; doi:10.26033/ehqs-jp27). Reference only: the "
                                "prediction uses the size above. Event quality: astrometry only < limits on size < "
                                "reliable size < better than shape models")
                            with ui.row().classes("items-center gap-2"):
                                ui.button("Double-star check (VizieR)", on_click=lambda: fav_vizier()).props(
                                    "outline dense").tooltip(
                                    "Ask VizieR (needs the network, a few seconds) for known pairs at this star (the "
                                    "Washington Double Star Catalog, WDS: discoverer, separation, position angle, "
                                    "magnitudes, last observed; 'O' = orbit in ORB6) and Gaia DR3's signs of a "
                                    "companion the local catalog does not keep (elongated image, position wobble, "
                                    "colour-window excess). Kept with the favorite")
                            f_viz = ui.label().classes("text-sm text-slate-700 whitespace-pre-line")
                            f_added = ui.label().classes("text-xs text-slate-500")
                            with ui.row().classes("items-end gap-4"):
                                f_status = ui.select(list(favorites.STATUSES), label="Status").classes("w-40")
                                f_kml = ui.link("KML (ground track)", "#")
                                f_globe = ui.link("Globe (whole-Earth view)", "#", new_tab=True)
                            f_note = ui.textarea("Note").classes("w-full")
                            with ui.row():
                                ui.button("Save", on_click=lambda: save_fav()).props("color=primary")
                                ui.button("Remove from favorites", on_click=lambda: remove_fav()).props(
                                    "outline color=negative")
                with ui.column().classes("w-full gap-2 border-t pt-2") as f_pc:
                    ui.label("Path verification: our geodetic path against Occult's listing").classes("font-semibold")
                    f_pc_info = ui.label().classes("text-sm text-slate-600")
                    with ui.row().classes("gap-2 items-center"):
                        ui.button("Compute our path (fresh)", on_click=lambda: pc_run()).props("outline dense").tooltip(
                            "Runs the search for this event only, with today's orbit from JPL and this version of "
                            "PySyzygos (relaxed limits; about 10-30 s), and keeps its path and orbit files with the "
                            "favorite. Compute it on the same day as the Occult listing: orbits change")
                        ui.button("Export our path (Occult layout)", on_click=lambda: pc_export()).props(
                            "outline dense").tooltip("Our centre line, shadow and 1-sigma limits every 1.45 s as a text "
                                                     "table in Occult's layout, to send for a comparison the other way")
                        ui.button("Last report", on_click=lambda: pc_show()).props("flat dense")
                        ui.button("Keep in owc_refs", on_click=lambda: pc_keep()).props("flat dense").tooltip(
                            "Copy the last comparison (report, points, Occult's listing) to owc_refs/occult_paths/ "
                            "(private) and add a line to its index.md")
                    f_pc_list = ui.textarea("Occult's path listing: paste the text (or load the .txt below)").classes(
                        "w-full font-mono text-xs").props("rows=4")
                    f_pc_head = ui.textarea("Occult's plot header (optional: JPL#..., RA, Dec, Dia = ...)").classes(
                        "w-full font-mono text-xs").props("rows=2")
                    with ui.row().classes("gap-2 items-center"):
                        ui.upload(label="Load listing .txt", auto_upload=True, on_upload=lambda e: pc_upload(e)).props(
                            "accept=.txt dense flat").classes("w-64")
                        ui.button("Compare", on_click=lambda: pc_compare()).props("color=primary")
                        ui.button("Step by step", on_click=lambda: pc_steps()).props("outline").tooltip(
                            "The event step by step from our path: the star from the Gaia catalog through every "
                            "correction (with its amount), the asteroid, the resulting vectors and the Besselian "
                            "elements at the shadow's touch-down, centre and leaving, and the geodetic points then")
                    with ui.expansion("Step-by-step data (catalog, corrections, vectors, Besselian elements)").classes(
                            "w-full") as f_pc_steps:
                        f_pc_steps_md = ui.markdown().classes("w-full text-sm")
                f_pc.set_visibility(bool(pc_chk.value))
                pc_chk.on_value_change(lambda e: (f_pc.set_visibility(bool(e.value)), save_ui_state(path_check=bool(e.value))))
            f_detail.set_visibility(False)
            with ui.card().classes("w-full"):                         # this tab's own tasks (path verification) only
                with ui.row().classes("w-full items-center"):
                    ui.label("Favorites log").classes("font-semibold").tooltip(
                        "The favorites' own tasks (path verification). They run independently of a search, pick or "
                        "pre-screen, whose output stays in the log of the other tabs")
                    ui.button("Clear", on_click=lambda: fav_log.clear()).props("flat dense")
                    ui.button("Stop", on_click=lambda: stop_process(fav_log, "fav")).props("flat dense color=negative")
                fav_log = ui.log(max_lines=2000).classes("w-full h-48 text-xs")

        with ui.tab_panel(t_sys):
            from pysyzygos import offline
            ui.label(f"Data folder: {home.describe()}").classes("text-sm text-slate-600")
            with ui.row().classes("gap-2 items-center"):
                ui.button("Setup status", on_click=lambda: sys_status()).props("outline dense").tooltip(
                    "pysyzygos setup --status (in the log below): kernels, Earth orientation, catalogs, supplement, "
                    "the site's height")
            ui.separator()
            with ui.row().classes("items-center gap-2"):
                ui.label("Data in use").classes("font-semibold")
                ui.button("Refresh", on_click=lambda: sys_info_refresh()).props("flat dense").tooltip(
                    "pysyzygos info: time and Earth orientation (valid ranges), the star catalogs (the one in use "
                    "marked), the asteroid data in the cache and the offline copies, results")
            sys_info = ui.column().classes("w-full gap-1")
            with ui.row().classes("gap-2 items-center"):
                ui.button("Download orbits again", on_click=lambda: sys_cache(True)).props("outline dense").tooltip(
                    "Delete the cached orbit files (JPL Horizons): the next search downloads the current orbits. "
                    "Searches do this by themselves for files older than orbit_max_age_days (config, default 1)")
                ui.button("Empty cache", on_click=lambda: sys_cache_ask()).props("flat dense color=negative").tooltip(
                    f"Delete PySyzygos's files in {config.cache_path}: orbit files, the pick's asteroid list (the next "
                    "pick downloads it again, ~100 MB), size data, CSV exports. The offline copies stay")
            ui.separator()
            with ui.row().classes("items-center gap-2"):
                ui.label("Star catalog").classes("font-semibold")
                ui.label("(the one selected in the header)").classes("text-xs text-slate-500")
            cat_box = ui.column().classes("w-full gap-1")
            ui.separator()
            ui.label("Planets and moons offline").classes("font-semibold")
            ui.label("NAIF's kernels of the planet systems: with one, the positions of that planet and its moons come "
                     "from your computer; without, from JPL Horizons per search (needs the network). Uranus: Horizons "
                     "only (NAIF splits it into very large files).").classes("text-xs text-slate-500")
            planets_box = ui.column().classes("w-full gap-0")
            ui.separator()
            ui.label("Offline use").classes("font-semibold")
            ui.label("The pick's asteroid list (JPL SBDB) and the searches' orbit files (JPL Horizons) are cached in "
                     f"{config.cache_path}, which is lost when the computer restarts where it is /dev/shm. With copies "
                     "kept here (the data folder's offline/), a pick or search without network uses them and says how "
                     "old they are: plan online, observe offline. The list is ~34 MB compressed (asteroids with "
                     "H < 17).").classes("text-xs text-slate-500")
            off_chk = ui.checkbox("Keep copies of orbit downloads for use without network", value=offline.enabled())
            off_info = ui.label().classes("text-sm text-slate-600 whitespace-pre-line")
            with ui.row().classes("gap-2"):
                ui.button("Copy now", on_click=lambda: sys_copy()).props("outline dense").tooltip(
                    "Copy what is in the cache now (the asteroid list of the last pick, the orbit files of past "
                    "searches) and switch the copies on")
                ui.button("Remove copies", on_click=lambda: sys_remove_ask()).props("flat dense color=negative")

    with ui.card().classes("w-full") as log_card:
        with ui.row().classes("w-full items-center"):
            ui.label("Log").classes("font-semibold")
            ui.button("Clear", on_click=lambda: log.clear()).props("flat dense")
        log = ui.log(max_lines=3000).classes("w-full h-64 text-xs")
    # the Favorites tab has its own log (its tasks only): the main one is not shown there
    tabs.on_value_change(lambda e: log_card.set_visibility(e.value not in (t_fav, "Favorites")))
    log_card.set_visibility(tabs.value not in (t_fav, "Favorites"))

    # ------------------------------------------------ site logic
    def show_site(name):
        s = sites[name]
        state["name"] = name
        lat.value, lon.value, ele.value, desc.value = s["lat"], s["lon"], s["ele"], s.get("name", name)
        ele_ref.value = s.get("ele_ref", "msl")
        mpc.value = str(s.get("mpc_code", "") or "")
        for key, _, default, _ in SITE_KEYS:
            if key == "sensor_w_mm":
                fields[key].value = s.get("sensor_mm", (5.6, 3.2))[0]
            elif key == "sensor_h_mm":
                fields[key].value = s.get("sensor_mm", (5.6, 3.2))[1]
            else:
                fields[key].value = s.get(key, default)
        is_default.value = name == state.get("default", default_site)
        hz_margin.value = s.get("horizon_margin", 15)
        hz_filter.value = bool(s.get("horizon_filter", False))
        HZ["image"] = s.get("horizon_image") if s.get("horizon_image") and os.path.isfile(s["horizon_image"]) else None
        hz_az.value = float(s.get("horizon_image_az", 0.0))
        hz_set([tuple(p) for p in s.get("horizon") or []] or None, s.get("horizon_name", ""))
        site_title.text = f"Site: {name}"
        try:
            load_pick()
            prescreen_options()
        except NameError:                         # first call, while the page is built: load_pick() runs later
            pass
        for note in (site_note_s, site_note_p, site_note_b):
            note.text = (f"Runs use site {name} ({s['lat']:.4f}, {s['lon']:.4f}, {s.get('aperture_cm', 25):g} cm); "
                         f"change it at the top right.")
        marker.move(s["lat"], s["lon"])
        m.set_center((s["lat"], s["lon"]))
        update_derived()

    HZ = dict(pts=None, name="", image=None)                     # the horizon in the form (horizon.py, panorama.py)

    def hz_draw():
        from pysyzygos import horizon, panorama
        pts, img = HZ["pts"], HZ["image"]
        prof = panorama.load_meta(img).get("profile") if img else None
        hz_fit.set_visibility(bool(img and prof and pts))
        hz_from.set_visibility(bool(img and prof))
        hz_dl.set_visibility(bool(pts))
        if img:
            hz_pic.content = panorama.svg(img, float(hz_az.value or 0), pts, float(hz_margin.value or 15), width=900)
        else:
            hz_pic.content = horizon.svg(pts, width=540, height=110) if pts else ""
        txt = (f"{HZ['name'] or 'horizon'}: {len(pts)} points, highest {max(h for _, h in pts)}°" if pts
               else "no horizon: a flat horizon is assumed")
        hz_info.text = txt + (f" · photo {os.path.basename(img)}" if img else "") + " (saved with the site)"
        try:
            update_derived()                                         # marks "unsaved changes"
        except NameError:                                            # while the page is built
            pass

    def hz_set(pts, name=""):
        HZ["pts"], HZ["name"] = (pts, name) if pts else (None, "")
        hz_draw()

    def pano_set(img):
        HZ["image"] = img
        hz_draw()

    async def pano_upload(e):
        from pysyzygos import panorama
        data = await e.file.read()
        e.sender.reset()
        try:
            img, meta = await run.io_bound(panorama.save, data, state["name"], source=e.file.name)
        except Exception as ex:
            ui.notify(f"Not loaded: {ex}", type="warning", timeout=8000)
            return
        HZ["image"] = img
        if meta.get("profile") and HZ["pts"]:
            pano_fit()
        hz_draw()
        ui.notify(f"Photo set for site {state['name']}" + ("" if meta.get("profile") else
                  " (no transparent sky: set the azimuth at its left edge by hand)") + ": save the site to keep it",
                  type="positive", timeout=8000)

    def pano_fit():
        from pysyzygos import panorama
        prof = panorama.load_meta(HZ["image"]).get("profile") if HZ["image"] else None
        if not (prof and HZ["pts"]):
            return
        az0, d = panorama.fit_az_left(prof, HZ["pts"])
        hz_az.value = az0
        ui.notify(f"Azimuth at the left edge {az0:g}° (photo and horizon points differ by {d:.1f}° in the median)",
                  type="info", timeout=8000)

    def pano_points():
        from pysyzygos import panorama
        prof = panorama.load_meta(HZ["image"]).get("profile") if HZ["image"] else None
        if prof:
            hz_set(panorama.points(prof, float(hz_az.value or 0)), f"{state['name']} (from the photo)")

    def hz_download():
        from pysyzygos import horizon
        if HZ["pts"]:
            ui.download(horizon.to_text(HZ["name"] or state["name"], HZ["pts"]).encode(), "UserHorizon.txt")

    async def hz_upload(e):
        from pysyzygos import horizon
        text = (await e.file.read()).decode("utf-8-sig", errors="replace")
        e.sender.reset()                                             # the same file can be loaded again
        try:
            stations = horizon.parse(text)
        except horizon.HorizonError as ex:
            ui.notify(f"Not loaded: {ex}", type="warning", timeout=8000)
            return
        site = state["name"]
        names = list(stations)
        key = lambda x: "".join(ch for ch in x.lower() if ch.isalnum())
        pick = next((n for n in names if key(n) == key(site)), None) or \
            next((n for n in names if key(site) and key(site) in key(n)), None) or names[0]
        hz_set(stations[pick], pick)
        more = f" (of {len(names)} stations in the file: {', '.join(names)})" if len(names) > 1 else ""
        ui.notify(f"Horizon '{pick}' set for site {site}{more}: save the site to keep it", type="positive",
                  timeout=8000)

    def collect():
        s = dict(lat=float(lat.value or 0), lon=float(lon.value or 0), ele=float(ele.value or 0),
                 name=desc.value or state["name"])
        if HZ["pts"]:
            s.update(horizon=[list(p) for p in HZ["pts"]], horizon_name=HZ["name"],
                     horizon_margin=float(hz_margin.value or 15), horizon_filter=bool(hz_filter.value))
        if HZ["image"]:
            s.update(horizon_image=HZ["image"].replace(os.sep, "/"), horizon_image_az=float(hz_az.value or 0))
        if ele_ref.value == "ellipsoid":
            s["ele_ref"] = "ellipsoid"                            # else above sea level: geoid_m added when saved
        if (mpc.value or "").strip():
            s["mpc_code"] = mpc.value.strip()
        for key, _, default, _ in SITE_KEYS:
            v = fields[key].value
            if key in ("sensor_w_mm", "sensor_h_mm") or v is None or v == "":
                continue
            s[key] = int(v) if key == "frames" else float(v)
        s["sensor_mm"] = (float(fields["sensor_w_mm"].value or 5.6), float(fields["sensor_h_mm"].value or 3.2))
        from pysyzygos import geoid
        return geoid.fill(s)                              # geoid_m as saving would set it (an older file differs)

    def pick_mag_default(s):
        """Faintest star for the pick: the site's telescope limit, capped at the selected catalog's G limit."""
        return round(min(mag_limit(s), cat_gmax.get(cat_sel.value, 18.0)), 1)

    # the star G limits of Pick, Search and Planets & Moons: the site's default unless overridden (kept until reset with
    # the ↺ button, also across restarts: gui_state mag_override); a note says where the value comes from
    MAG = dict(setting=False, override={k: float(v) for k, v in (load_ui_state().get("mag_override") or {}).items()})
    INDEX_GB = {15: 1.2, 16: 2.6, 17: 5.0, 18: 10.0}             # bright-star index sizes on disk (measured: 15, 16, 18)

    def mag_fields():
        return {"pick": (p_mag, p_mag_note), "search": (s_mag, s_mag_note), "bodies": (b_mag, b_mag_note)}

    def mag_source(s):
        lim, cap = mag_limit(s), cat_gmax.get(cat_sel.value, 18.0)
        how = (f"mag_limit {float(s['mag_limit']):g} in sites.py" if s.get("mag_limit") else
               f"{s.get('aperture_cm', 25.0):g} cm, {int(s.get('frames', 4))} frames, longest exposure "
               f"{s.get('max_exp_s', 0.64):g} s, MagAdjust {s.get('mag_adjust', 0.0):+g}")
        return (f"Star limit from site {state['name']}: {how} → G {lim:.1f}"
                + (f", capped at the catalog's {cap:g}" if lim > cap else ""))

    def mag_apply(s=None):
        s = s or collect()
        d = pick_mag_default(s)
        MAG["setting"] = True
        try:
            for kind, (f, note) in mag_fields().items():
                ov = MAG["override"].get(kind)
                f.value = d if ov is None else ov
                v = float(f.value or d)
                text = (f"Star limit G {v:g}: your override (site default {d:g}; ↺ resets)" if ov is not None
                        else mag_source(s))
                if kind == "pick":
                    n = max(15, math.ceil(v - 1e-9))
                    cd = os.path.join(ROOT, cat_sel.value or "")
                    if not starcat.is_format2(cd) and not os.path.isfile(os.path.join(cd, f"bright_G{float(n):.1f}.v2.npy")):
                        text += (f" · the G ≤ {n} star index is not built yet: the next pick builds it once "
                                 f"(several minutes, ~{INDEX_GB.get(n, 10):g} GB on disk)")
                note.text = text
        finally:
            MAG["setting"] = False

    def mag_changed(kind, e):
        if MAG["setting"]:
            return
        d = pick_mag_default(collect())
        v = e.value
        MAG["override"][kind] = None if v in (None, "") or abs(float(v) - d) < 1e-9 else float(v)
        save_ui_state(mag_override={k: x for k, x in MAG["override"].items() if x is not None})
        mag_apply()

    def mag_reset(kind):
        MAG["override"][kind] = None
        save_ui_state(mag_override={k: x for k, x in MAG["override"].items() if x is not None})
        mag_apply()

    for _kind, (_f, _n) in mag_fields().items():
        _f.on_value_change(lambda e, k=_kind: mag_changed(k, e))

    def update_derived(*_):
        s = collect()
        unsaved.text = "" if saved_site(state["name"]) == effective(s, state["name"]) else "unsaved changes"
        w, h = fov(s)
        mag_apply(s)
        derived.text = (f"Stars searched to G {mag_limit(s):.1f} · camera field {w:.1f}′ × {h:.1f}′ "
                        f"(focal {s.get('focal_mm') or 100 * s.get('aperture_cm', 25):.0f} mm)")

    for el in [lat, lon, ele, mpc, *fields.values()]:
        el.on_value_change(update_derived)

    def set_position(la, lo, el=None):
        lat.value, lon.value = round(la, 5), round(lo, 5)
        if el is not None:
            ele.value = round(el)
        marker.move(la, lo)

    async def on_click(e):
        ll = e.args.get("latlng", {})
        set_position(ll["lat"], ll["lng"])
        el = await run.io_bound(geo.elevation, ll["lat"], ll["lng"])
        if el is not None:
            ele.value = round(el)
            ele_ref.value = "msl"                                 # Open-Meteo: above sea level

    m.on("map-click", on_click)

    # pasted coordinates: a number field drops text, so text that is not a plain number is taken from the paste
    # event in the browser and parsed here (geo.parse_coords: DMS, decimal, N/S/E/W, labels, heights)
    PASTE_JS = ("(e) => { const t = (e.clipboardData || window.clipboardData).getData('text'); "
                "if (!/^\\s*[+-]?\\d*\\.?\\d+\\s*$/.test(t)) { e.preventDefault(); emit(t); } }")

    async def on_paste(field, e):
        text = e.args if isinstance(e.args, str) else (e.args[0] if e.args else "")
        if re.fullmatch(r"\s*[+-]?\d+,\d+\s*", text):           # one number with a decimal comma (German, Swiss)
            text = text.replace(",", ".")                      # the fields always use the decimal point
        try:
            c = geo.parse_coords(text, field)
        except ValueError as ex:
            ui.notify(f"Coordinates not understood: {ex}", type="warning")
            return
        la = c["lat"] if c["lat"] is not None else lat.value
        lo = c["lon"] if c["lon"] is not None else lon.value
        if c["ele"] is not None:
            ele.value = round(c["ele"])
        if la is None or lo is None:
            if c["lat"] is not None:
                lat.value = round(c["lat"], 5)
            if c["lon"] is not None:
                lon.value = round(c["lon"], 5)
            return
        set_position(float(la), float(lo))
        m.set_center((float(la), float(lo)))
        got = ", ".join(k for k in ("lat", "lon", "ele") if c[k] is not None)
        if c["ele"] is None and c["lat"] is not None and c["lon"] is not None:
            el = await run.io_bound(geo.elevation, float(la), float(lo))
            if el is not None:
                ele.value = round(el)
                got += " (elevation looked up)"
        ui.notify(f"Pasted coordinates: {got}: {float(la):.5f}, {float(lo):.5f}"
                  + (f", {ele.value:.0f} m" if ele.value is not None else ""), type="positive")

    for f_, el_ in (("lat", lat), ("lon", lon), ("ele", ele)):
        el_.on("paste", lambda e, f_=f_: on_paste(f_, e), js_handler=PASTE_JS)

    async def pick_occult(e):
        if e.value is None:
            return
        x = occ[e.value]
        set_position(x["lat"], x["lon"], x["ele"] if x["ele_ok"] else None)
        ele_ref.value = "ellipsoid" if x["ele_ok"] else "msl"     # MPC parallax constants: height above WGS84
        m.set_center((x["lat"], x["lon"]))
        desc.value, mpc.value = x["name"], x["code"]
        auto = f"{x['code']} {x['name'].split(',')[0].strip()}"
        if not (new_name.value or "").strip() or new_name.value == state.get("auto_name"):   # keep a name you typed
            new_name.value = auto
        state["auto_name"] = auto
        if not x["ele_ok"]:                                       # old low-precision entry: look the height up
            el = await run.io_bound(geo.elevation, x["lat"], x["lon"])
            if el is not None:
                ele.value = round(el)
        ui.notify(f"MPC {x['code']} {x['name']}: shown on the map and in the form. 'Add as new site' adds it to the "
                  f"site selector; 'Save sites.py' would instead move {state['name']} there.",
                  multi_line=True, timeout=9000)

    occ_sel.on_value_change(pick_occult)

    def pick_camera(e):
        if e.value is None:
            return
        c = cameras.SENSORS[e.value]
        w, h = cameras.sensor_mm(c)
        fields["sensor_w_mm"].value, fields["sensor_h_mm"].value = w, h       # updates the camera field line too
        ui.notify(f"{c[0]} ({c[4]}): sensor {w:.2f} × {h:.2f} mm; 'Save sites.py' keeps it for this site",
                  timeout=6000)

    cam_sel.on_value_change(pick_camera)

    async def find_place():
        hits.clear()
        res = await run.io_bound(geo.places, q.value or "")
        with hits:
            if not res:
                ui.label("No place found (or offline)").classes("text-sm text-slate-500")
            for la, lo, el, label in res:
                ui.button(f"{label}: {la:.4f}, {lo:.4f}, {el or 0:.0f} m",
                          on_click=lambda la=la, lo=lo, el=el: (set_position(la, lo, el), m.set_center((la, lo)),
                                                                hits.clear())).props("flat dense no-caps align=left")

    async def ip_loc():
        r = await run.io_bound(geo.ip_location)
        if r is None:
            ui.notify("IP lookup failed", type="warning")
            return
        set_position(r[0], r[1], r[2])
        m.set_center((r[0], r[1]))
        ui.notify(f"Approximate (from your IP address): {r[3]}")

    def add_site():
        """The position and settings in the form as a new site (name from 'New site name'), selected and saved."""
        name = (new_name.value or "").strip()
        if not name or name in sites:
            ui.notify("Enter a new, unused site name (field 'New site name' at the top)", type="warning")
            return
        sites[name] = collect()                                   # keeps the description from the form
        sel.options = list(sites)
        sel.update()
        sel.value = name                                          # shows it (show_site) and makes it the run site
        new_name.value, state["auto_name"] = "", None
        save_sites(sites, state.get("default", default_site))
        unsaved.text = ""
        ui.notify(f"Site {name} added and saved in sites.py; it is now selected for all runs (top right)",
                  type="positive")

    def effective(s, name):
        """A site with every optional key filled in with its default, for comparing form and file."""
        e = {k: (tuple(v) if isinstance(v, list) else v) for k, v in s.items()}
        e.setdefault("name", name)
        e.setdefault("sensor_mm", (5.6, 3.2))
        for key, _, default, _ in SITE_KEYS:
            if key not in ("sensor_w_mm", "sensor_h_mm") and default is not None:
                e.setdefault(key, default)
        return e

    def saved_site(name):
        """The site as it is in sites.py now (what a run will use), with defaults filled in; None if not there."""
        try:
            s = load_sites()[0].get(name)
        except Exception:
            return None
        return effective(s, name) if s else None

    def ensure_saved():
        """Runs read sites.py: save the selected site first if it was edited or is new."""
        s = collect()
        if not os.path.isfile("sites.py") or saved_site(state["name"]) != effective(s, state["name"]):
            save()
            ui.notify(f"Saved the changes to site {state['name']} for this run", type="info")

    async def remove_site():
        name = state["name"]
        if len(sites) < 2:
            ui.notify("This is the only site: add another one before removing it", type="warning")
            return
        with ui.dialog() as dlg, ui.card():
            ui.label(f"Remove site {name} ({sites[name].get('name', name)}) from sites.py?")
            with ui.row():
                ui.button("Remove", on_click=lambda: dlg.submit(True)).props("color=negative")
                ui.button("Cancel", on_click=lambda: dlg.submit(False)).props("flat")
        if not await dlg:
            return
        del sites[name]
        default = state.get("default", default_site)
        note = ""
        if default == name or default not in sites:
            default = state["default"] = next(iter(sites))
            note = f"; {default} is now the default for command-line runs"
        save_sites(sites, default)
        sel.options = list(sites)
        sel.update()
        sel.value = default                                       # shows it (show_site)
        unsaved.text = ""
        ui.notify(f"Site {name} removed from sites.py{note}", type="positive")

    def save():
        sites[state["name"]] = collect()
        if is_default.value:
            state["default"] = state["name"]
        save_sites(sites, state.get("default", default_site))
        ui.notify(f"sites.py saved (default site: {state.get('default', default_site)})", type="positive")
        unsaved.text = ""

    hz_margin.on_value_change(lambda e: hz_draw())
    sel.on_value_change(lambda e: (show_site(e.value), save_ui_state(site=e.value, catalog=cat_sel.value))
                        if e.value in sites else None)
    def catalog_limit(*_):                                        # the catalog's limit caps the star limits
        mag_apply()
    cat_sel.on_value_change(catalog_limit)
    cat_sel.on_value_change(lambda e: save_ui_state(catalog=e.value, site=state["name"]) if e.value else None)

    def supplement_state(*_):
        """The header switch: enabled when the selected catalog has a complete supplement (gaia_local)."""
        d = os.path.join(ROOT, cat_sel.value) if cat_sel.value else None
        have = bool(d and gaia_local.has_supplement(d))
        sup_chk.set_enabled(have)
        if d and starcat.is_format2(d):
            sup_chk.tooltip("Also search the stars with Gaia RUWE >= 1.4 (often unresolved doubles) and the "
                            "2-parameter sources (no or a cross-matched proper motion). This catalog includes them; "
                            "they are flagged \u2691 in the results (position, and so the path, less certain).")
            return
        sup_chk.tooltip("Also search the stars the main catalog leaves out: Gaia RUWE >= 1.4 (often unresolved "
                        "doubles) and 2-parameter sources (no proper motion). OWC predicts events on them; here they "
                        "are flagged \u2691 in the results (position, and so the path, less certain). "
                        + ("" if have else f"Not built for this catalog yet: pysyzygos gaia supplement --dir "
                                           f"{cat_sel.value} --gmax 16 (about 2 h, ~0.3 GB)"))

    def supplement_change(e):
        SUPPLEMENT["on"] = bool(e.value)
        save_ui_state(supplement=bool(e.value), catalog=cat_sel.value, site=state["name"])
        prescreen_options()

    sup_chk.on_value_change(supplement_change)
    cat_sel.on_value_change(supplement_state)
    supplement_state()
    show_site(state["name"])

    # ------------------------------------------------ runs
    async def owc_check(which):
        """Look the Results or Favorites events up in OccultWatcher Cloud (owc.py), then show the tables again."""
        from pysyzygos import owc
        if which == "results":
            path = os.path.join(ROOT, config.hits_output_cvs_file)
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
            log.push(f"OWC check failed: {err}")
            print(f"OWC check failed: {err}")
        ui.notify(f"OccultWatcher Cloud: {found} of {n} event(s) found"
                  + (f"; {len(errors)} failed: details in the Log at the bottom of the page" if errors else ""),
                  type="warning" if errors else "positive", multi_line=True)
        if which == "results":
            await build_report()
        else:
            load_favs(fav_cur["key"])

    async def run_bodies():
        """Planets & Moons tab: search the ticked bodies (their own results list), then show their report."""
        if not catalog_ok():
            return
        targets = [t for t, c in b_checks.items() if c.value]
        for grp, c in b_small.items():                  # a system's smaller moons, all at once
            if c.value:
                targets += bodies_mod.featured(grp)[1]
        if not targets:
            ui.notify("Tick at least one body", type="warning")
            return
        ensure_saved()
        over = dict(ct=f"{b_start.value}T00:00:00", days=int(b_days.value), targets=targets, targets_source="list",
                    results_list="bodies", hits_output_cvs_file="bodies_log.csv",
                    results_new_series=bool(b_fresh.value),
                    min_mag_drop=float(b_drop.value), gaia_online_check=False,
                    **({"MAG_MIN": float(b_mag.value)} if b_mag.value else {}))

        async def done(rc):
            if rc == 0:
                await build_bodies_report()
        await run_process(PYSYZYGOS + ["run", "search", json.dumps(over)], log,
                          env_site=state["name"], on_done=done, env_catalog=cat_sel.value)

    async def build_bodies_report(rc=0):
        if not os.path.isfile(os.path.join(ROOT, "bodies_log.csv")) and not os.path.isfile(
                os.path.join(ROOT, "bodies_log.runs.jsonl")):
            ui.notify("No planet or moon search yet", type="warning")
            return
        await run_process(PYSYZYGOS + ["report", "bodies_log.csv", "-o", "bodies_report.html", "--layout", "bodies"],
                          log)
        b_frame.props(f"src=/out/bodies_report.html?t={int(time.time())}")

    def bodies_csv():
        path = os.path.join(ROOT, "bodies_log.csv")
        if not os.path.isfile(path):
            ui.notify("No planet or moon events yet", type="warning")
            return
        download_csv("bodies", exports.results_rows(results_db(), "bodies"), f"bodies_{today_utc()}.csv")

    async def build_report(rc=0):
        await run_process(PYSYZYGOS + ["report", config.hits_output_cvs_file], log)
        frame.props(f"src=/out/hits_report.html?t={int(time.time())}")

    def catalog_ok():
        """Runs need a complete catalog: tell the user how to get one otherwise."""
        if cat_sel.value in complete:
            return True
        ui.notify(("No complete Gaia catalog yet" if not cat_sel.value else f"Catalog {cat_sel.value} is incomplete")
                  + ": run  pysyzygos setup  (it resumes), then restart the GUI", type="warning", timeout=10000)
        return False

    async def run_search():
        if not catalog_ok():
            return
        ensure_saved()
        over = dict(ct=f"{s_start.value}T00:00:00", days=int(s_days.value), min_mag_drop=float(s_drop.value),
                    **({"MAG_MIN": float(s_mag.value)} if s_mag.value else {}),
                    write_maps=bool(s_maps.value), write_previews=bool(s_prev.value),
                    star_parallax=bool(s_plx.value), light_deflection=bool(s_defl.value),
                    gaia_online_check=bool(s_dbl.value))
        if not s_use_file.value:
            over["targets"] = [t for t in s_targets.value.replace(",", " ").split() if t]
        over["results_new_series"] = bool(s_fresh.value)          # db.py: a fresh results list = a new series

        async def done(rc):
            if rc == 0:
                await build_report()
                tabs.value = t_res
        await run_process(PYSYZYGOS + ["run", "search", json.dumps(over)], log,
                          env_site=state["name"], on_done=done, env_catalog=cat_sel.value)

    def saved_info(*_):
        """Search tab: which saved pick the search will use for the selected site and window."""
        if not s_use_file.value:
            targets_warn_s.text = "The search uses the list below."
            targets_warn_s.classes(replace="text-sm w-full text-slate-600")
            return
        try:
            s = sites.get(state["name"], {})
            p = picks.best_for(state["name"], s_start.value, float(s_days.value or 1), picks_dir, s.get("lat"), s.get("lon"))
        except ValueError:
            p = None
        if p:
            targets_warn_s.text = f"The search uses the {picks.describe(p)}."
            targets_warn_s.classes(replace="text-sm w-full text-slate-600")
        else:
            targets_warn_s.text = (f"No saved pick of site {state['name']} covers this window: the search uses "
                                   f"targets.py or the config list. Run a pick for it (Pick tab) for better targets.")
            targets_warn_s.classes(replace="text-sm w-full text-amber-700")

    def show_saved(*_):
        """Pick tab: show the events of the selected saved pick."""
        p = next((p for p in saved_list if p["py"] == p_saved.value), None)
        rows = []
        if p is None:
            pick_info.text = f"No saved pick for site {state['name']} yet: run a pick."
            targets_info.text = ""
        else:
            if os.path.isfile(p["csv"]):
                with open(p["csv"]) as f:
                    rows = list(csv.DictReader(f))
            rows = [dict(exports.pick_shown(r, p["targets"]), key=f"{r.get('number')}_{r.get('utc')}") for r in rows]
            pick_info.text = f"{picks.describe(p)}: {len(rows)} events ({p['csv']})"
            targets_info.text = ("Targets: " + ", ".join(p["targets"][:60]) + (" ..." if len(p["targets"]) > 60 else ""))
        p_table.rows = rows
        return len(rows)

    def load_pick(select=None):
        """Fill the list of saved picks of the selected site (newest window first) and show one. Returns #events."""
        saved_list[:] = picks.list_for(state["name"], picks_dir)
        p_saved.options = {p["py"]: f"{p['start']} + {p['days']:g} d · {len(p['targets'])} targets · picked "
                                    f"{p['picked'][:16].replace('T', ' ') or '?'}" for p in saved_list}
        p_saved.update()
        keep = select or p_saved.value
        p_saved.value = keep if keep in p_saved.options else (saved_list[0]["py"] if saved_list else None)
        n = show_saved()
        saved_info()
        return n

    def prescreen_options(*_):
        """Pick tab: the Asteroids choices (auto, all, the pre-screens that fit this site and window), the line saying
        what the pick will screen, and the pre-screens table."""
        from pysyzygos import prescreen as PS
        opts, rows, fit = dict(PRE_FIXED), [], []
        s = sites.get(state["name"], {})
        try:
            t0 = _day_et(p_start.value)
            t1 = t0 + float(p_days.value or 1) * 86400
            want = dict(cam_limit=float(p_mag.value or 0), hmax=None if p_all.value else float(p_hmax.value or 17),
                        hmax_all=bool(p_all.value),
                        supplement=bool(SUPPLEMENT["on"] and cat_sel.value
                                        and gaia_local.has_supplement(os.path.join(ROOT, cat_sel.value))))
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
                [n for n, v in sites.items() if "lat" in v and PS.contains(m, v["lat"], v["lon"])]
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
                             limits=f"G <= {m['cam_limit']:g}, H < {m.get('hmax')}, reach {m['reach_km']:g} km",
                             found=f"{n_ast} / {n_ev}",
                             age="?" if age is None else (f"{age:.0f} d ago" + (" (old: rebuild)" if age > 30 else "")),
                             fits="fits" if not bad else "; ".join(bad)))
        p_pre.options = opts
        if p_pre.value not in opts:
            p_pre.value = "auto"
        p_pre.update()
        ps_table.rows = rows
        ps_table.update()
        if p_pre.value == "all":
            pre_info.text = "Screens all asteroids (any place and time; slower)."
        elif fit:
            _, path, m = max(fit, key=lambda x: x[0]) if p_pre.value == "auto" else \
                next(x for x in fit if x[1] == p_pre.value)
            pre_info.text = f"Screens only the asteroids of pre-screen {os.path.basename(path)} (fast)."
        else:
            pre_info.text = ("No pre-screen fits this site and window: screens all asteroids (slower). "
                             "Build one below for fast picks.")

    async def delete_prescreens():
        sel = [r["path"] for r in ps_table.selected]
        if not sel:
            ui.notify("Select pre-screens in the table first", type="warning")
            return
        from pysyzygos import prescreen as PS
        for p in sel:
            try:
                PS.remove(p)
            except OSError as e:
                ui.notify(f"{os.path.basename(p)}: {e}", type="negative")
        ps_table.selected = []
        prescreen_options()
        ui.notify(f"{len(sel)} pre-screen(s) deleted", type="positive")

    def pick_csv():
        p = next((p for p in saved_list if p["py"] == p_saved.value), None)
        if p is None or not os.path.isfile(p["csv"]):
            ui.notify("No saved pick with a CSV selected", type="warning")
            return
        download_csv("pick", exports.pick_rows(p["csv"], p["targets"]), os.path.basename(p["csv"]))

    def fav_csv():
        items = favorites.load(os.path.join(ROOT, favorites.DIR))
        if not items:
            ui.notify("No favorites yet", type="warning")
            return
        download_csv("favorites", exports.favorite_rows(items), f"favorites_{today_utc()}.csv")

    def hits_csv():
        path = os.path.join(ROOT, config.hits_output_cvs_file)
        if not os.path.isfile(path):
            ui.notify("No search results yet (run a search)", type="warning")
            return
        from pysyzygos import report
        run = report.read_last_run(path) or {}             # name it like the picks: site, window
        site, start = (run.get("site") or {}).get("name"), str(run.get("window_start") or "")[:10]
        name = (f"hits_{picks._safe(site)}__{start}_{float(run['window_days']):g}d.csv"
                if site and start and run.get("window_days") else os.path.basename(path))
        download_csv("results", exports.results_rows(results_db(), "main"), name)

    def results_db():
        return os.path.join(ROOT, getattr(config, "results_db", "pysyzygos.db"))

    def download_csv(kind, rows, name):
        """A CSV download with the columns of csv_exports.py (data folder) for this table."""
        folder = os.path.join(config.cache_path, "pysyzygos_exports")
        os.makedirs(folder, exist_ok=True)
        try:
            exports.write(kind, rows, os.path.join(folder, name), home=ROOT)
        except Exception as ex:                                  # a broken csv_exports.py: say so
            ui.notify(f"CSV export failed ({type(ex).__name__}: {ex}); check csv_exports.py in the data folder",
                      type="negative", timeout=10000)
            return
        ui.download(os.path.join(folder, name), name)

    def use_saved():
        p = next((p for p in saved_list if p["py"] == p_saved.value), None)
        if p is None:
            ui.notify("No saved pick selected", type="warning")
            return
        s_start.value, s_days.value, s_use_file.value = p["start"], p["days"], True
        tabs.value = t_search

    from pysyzygos import picks
    picks_dir = getattr(config, "picks_dir", "picks")
    saved_list = []
    p_saved.on_value_change(show_saved)
    for el in (s_start, s_days, s_use_file):
        el.on_value_change(saved_info)
    load_pick()
    for el in (p_start, p_days, p_mag, p_hmax, p_all, p_pre):
        el.on_value_change(prescreen_options)
    prescreen_options()

    fav_cur = {"key": None}

    async def fav_vizier():
        from pysyzygos import doubles as D_
        e = next((x for x in favorites.load() if x["key"] == fav_cur["key"]), None)
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
        f_viz.text = "asking VizieR ..."
        try:
            v = await run.io_bound(D_.vizier_check, sid, ra, dec)
        except OSError as ex:
            f_viz.text = ""
            ui.notify(f"VizieR not reachable: {str(ex)[:120]}", type="warning")
            return
        favorites.set_field(e["key"], "vizier", v)
        f_viz.text = "\n".join(D_.vizier_text(v))
        ui.notify(f"{len(v['wds'])} WDS pair(s), {len(v['hints'])} sign(s)", type="positive")

    def load_favs(select=None):
        """Rebuild the favorites page (report table) and show it; keep or set the selected favorite."""
        favorites.write_page()
        items = favorites.load()
        fav_info.text = f"{len(items)} favorite event{'s' if len(items) != 1 else ''}"
        f_frame.props(f"src=/fav/favorites.html?t={time.time():.0f}")
        if select:
            fav_cur["key"] = select
        if fav_cur["key"] not in {e["key"] for e in items}:
            fav_cur["key"] = None
        show_fav()

    def current_fav():
        return next((e for e in favorites.load() if e["key"] == fav_cur["key"]), None)

    def fav_pano(e):
        """The site's photo with the star at the event, or None (the favorite's site found in sites.py by position)."""
        from pysyzygos import panorama, report as R_
        site, r = e.get("site") or {}, e["record"]
        try:
            lat, lon = float(site["lat"]), float(site["lon"])
        except (KeyError, TypeError, ValueError):
            return None
        s = next((v for v in sites.values() if abs(float(v.get("lat", 99)) - lat) < 2e-4
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

    def show_fav(*_):
        e = current_fav()
        f_detail.set_visibility(e is not None)
        if e is None:
            return
        r, site, files = e["record"], e.get("site") or {}, e.get("files") or {}
        f_title.text = favorites.title_text(e)
        pc_refresh()
        f_info.clear()
        with f_info:
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
        f_bar.content = bar or ""
        f_bar.set_visibility(bar is not None)
        pano = fav_pano(e)
        f_pano.content = pano or ""
        f_pano.set_visibility(pano is not None)
        err = favorites.error_svg(e)
        f_err.set_visibility(err is not None)
        if err:
            import base64
            f_err.props(f'src="data:image/svg+xml;base64,{base64.b64encode(err.encode()).decode()}" alt="Error ellipses"')
        f_occ.text = occultations.text(e["record"].get("target_id", ""))
        from pysyzygos import doubles as D_
        f_viz.text = "\n".join(D_.vizier_text(e.get("vizier")))
        f_added.text = f"added {e.get('added', '')[:16].replace('T', ' ')} UT"
        f_status.value, f_note.value = e.get("status", "planned"), e.get("note", "")
        f_img.set_visibility("svg" in files)
        if "svg" in files:
            f_img.props(f'src=/fav/{files["svg"]}?t={int(time.time())} alt="Event preview"')
        f_globe.set_visibility("globe" in files)
        if "globe" in files:
            f_globe.props(f'href=/fav/{files["globe"]}')
        f_kml.set_visibility("kml" in files)
        if "kml" in files:
            f_kml.props(f'href=/fav/{files["kml"]} download')
        draw_fav_map(e)

    fav_layers = []

    def draw_fav_map(e):
        """The favorite's own KML copy on the map: shadow path lines and the site, zoomed to the nearest path part."""
        from pysyzygos import report
        for layer in fav_layers:
            f_map.remove_layer(layer)
        fav_layers.clear()
        kml = (e.get("files") or {}).get("kml")
        try:
            data = report.kml_to_data(os.path.join(favorites.DIR, kml)) if kml else None
        except Exception:
            data = None
        for el in (f_map, f_legend):
            el.set_visibility(data is not None)
        f_nomap.set_visibility(data is None)
        if data is None:
            return
        for ln in data["lines"]:
            if len(ln["pts"]) > 1:
                opts = {"color": ln["color"], "weight": ln["width"]}
                if ln.get("dash"):
                    opts["dashArray"] = ln["dash"]
                fav_layers.append(f_map.generic_layer(name="polyline", args=[ln["pts"], opts]))
        site = e.get("site") or {}
        centre = next((ln["pts"] for ln in data["lines"] if ln["name"].startswith("Centre")), [])
        if site.get("lat") is not None and site.get("lon") is not None:
            obs = [site["lat"], site["lon"]]
            fav_layers.append(f_map.marker(latlng=tuple(obs)))
            near = min(centre, key=lambda p: (p[0] - obs[0]) ** 2 + ((p[1] - obs[1]) * math.cos(math.radians(obs[0]))) ** 2,
                       default=obs)
            bounds = [obs, near]
        else:
            bounds = centre or [[0, 0]]

        def fit():
            f_map.run_map_method("invalidateSize")
            f_map.run_map_method("fitBounds", bounds, {"padding": [50, 50], "maxZoom": 11})
        ui.timer(0.3, fit, once=True)

    def save_fav():
        e = current_fav()
        if e:
            ok, msg = favorites.update(e["key"], status=f_status.value, note=f_note.value or "")
            ui.notify(msg, type="positive" if ok else "warning")
            load_favs(select=e["key"])

    async def remove_fav():
        e = current_fav()
        if not e:
            return
        with ui.dialog() as dlg, ui.card():
            ui.label(f"Remove {f_title.text} and its copied map and preview?")
            with ui.row():
                ui.button("Remove", on_click=lambda: dlg.submit(True)).props("color=negative")
                ui.button("Cancel", on_click=lambda: dlg.submit(False)).props("flat")
        if await dlg:
            ok, msg = favorites.remove(e["key"])
            ui.notify(msg, type="positive" if ok else "warning")
            fav_cur["key"] = None
            load_favs()

    # ------------------------------------------------ System tab
    def sys_refresh():
        from pysyzygos import offline
        off_info.text = offline.status_text()

    def sys_toggle(e):
        from pysyzygos import offline
        offline.set_enabled(bool(e.value))
        sys_refresh()

    async def sys_status():
        await run_process(PYSYZYGOS + ["setup", "--status"], log)

    async def sys_copy():
        from pysyzygos import offline
        ok, n = await run.io_bound(offline.copy_now, config.cache_path)
        off_chk.value = offline.enabled()
        sys_refresh()
        ui.notify(f"Copied: asteroid list {'yes' if ok else 'no (none in the cache: run a pick first)'}, {n} orbit files",
                  type="positive" if ok or n else "warning")

    def sys_remove_ask():
        with ui.dialog() as d, ui.card():
            ui.label("Remove all offline copies (asteroid list, orbit files)?")
            with ui.row():
                ui.button("Remove", on_click=lambda: (sys_remove(), d.close())).props("color=negative")
                ui.button("Cancel", on_click=d.close).props("flat")
        d.open()

    def sys_remove():
        from pysyzygos import offline
        offline.remove()
        off_chk.value = False
        sys_refresh()

    async def sys_cache(orbits_only):
        from pysyzygos import cleanup
        n, size = await run.io_bound(cleanup.empty_cache, config.cache_path, orbits_only)
        ui.notify(f"Deleted {n} {'orbit files' if orbits_only else 'cache files'} ({size / 1e6:.0f} MB)",
                  type="positive")
        await sys_info_refresh()

    def sys_cache_ask():
        async def go():
            d.close()
            await sys_cache(False)

        with ui.dialog() as d, ui.card():
            ui.label(f"Delete PySyzygos's cached downloads in {config.cache_path} (orbit files, asteroid list, size "
                     "data)? They are downloaded again when needed; the offline copies stay.")
            with ui.row():
                ui.button("Empty cache", on_click=go).props("color=negative")
                ui.button("Cancel", on_click=d.close).props("flat")
        d.open()

    def cat_refresh(*_):
        """The System tab's catalog section: parts of a format-2 catalog (checkboxes), or the upgrade of an old one."""
        cat_box.clear()
        d = os.path.join(ROOT, cat_sel.value) if cat_sel.value else None
        with cat_box:
            if not d:
                ui.label("No catalog: pysyzygos setup").classes("text-sm text-red-700")
                return
            if starcat.is_format2(d):
                st = starcat.status(d)
                v, newer = starcat.data_version(d), starcat.update_available(d)
                ui.label(f"{cat_sel.value}: data version {v} ({starcat.DATA_TEXT.get(v, '')}), G \u2264 "
                         f"{st['gmax']:g}, {st['n_stars'] / 1e6:.1f} M stars, {st['gb']:.1f} GB"
                         + ("" if newer else " \u2014 the latest")).classes("text-sm text-slate-700")
                if newer:
                    with ui.row().classes("items-center gap-3"):
                        ui.label(f"Data version {newer} is published: {starcat.DATA_TEXT.get(newer, '')}, and the "
                                 f"star names (xref). The parts that changed are downloaded next to this one and "
                                 f"swapped in.").classes("text-sm text-amber-800")
                        upd_del = ui.checkbox("delete the previous version afterwards", value=True).props("dense")
                        ui.button(f"Update to {newer}", on_click=lambda: cat_update(cat_sel.value, upd_del.value)
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
                    cb.on_value_change(lambda e, g=g: cat_part(d, g, e.value))
            else:
                st = gaia_local.status(d)
                ui.label(f"{cat_sel.value}: G \u2264 {st.get('gmax', 0):g}, {st['gb']:.1f} GB, the old format (before "
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
                    ui.button("Upgrade the catalog", on_click=lambda: cat_upgrade_ask(
                        cat_sel.value, up_parts.value, up_del.value)).props("outline dense")
            for old in sorted(f for f in os.listdir(ROOT) if f.startswith("gaia_dr3_") and f.endswith(".old")):
                with ui.row().classes("items-center gap-2"):
                    ui.label(f"{old}: the catalog before the upgrade").classes("text-sm text-slate-600")
                    ui.button("Delete", on_click=lambda o=old: cat_delete_old(o)).props("flat dense color=negative")

    def planets_refresh(*_):
        from pysyzygos import bodies
        planets_box.clear()
        with planets_box:
            for g, fname, size, have, n in bodies.kernels_status(ROOT):
                label = f"{g.capitalize()} system ({fname}, " + (f"{n / 1e9:.2f} GB)" if have else f"{size})")
                cb = ui.checkbox(label, value=have).props("dense")
                cb.on_value_change(lambda e, g=g, fname=fname: planet_kernel(g, fname, e.value))

    async def planet_kernel(g, fname, on):
        from pysyzygos import bodies
        if on:
            ui.notify(f"Downloading {fname} from NAIF (see the log; large files take a while)")
            await run_process(PYSYZYGOS + ["planets", "add", g], log)
            planets_refresh()
            await sys_info_refresh()
            return

        async def go(delete):
            dlg.close()
            if delete:
                await run.io_bound(bodies.remove_naif, g, ROOT)
                ui.notify(f"{fname} deleted: {g.capitalize()} positions now from JPL Horizons", type="positive")
            planets_refresh()
            await sys_info_refresh()

        with ui.dialog().props("persistent") as dlg, ui.card().classes("max-w-lg"):
            ui.label(f"Delete {fname}?").classes("font-semibold")
            ui.label(f"Searches of the {g.capitalize()} system then take the positions from JPL Horizons (needs the "
                     f"network). Ticking it again downloads the file anew from NAIF.").classes("text-sm")
            with ui.row():
                ui.button("Delete", on_click=lambda: go(True)).props("color=negative")
                ui.button("Cancel", on_click=lambda: go(False)).props("flat")
        dlg.open()

    async def cat_part(d, g, on):
        if on:
            if g in starcat.disabled_groups(d):                     # switched off earlier: back at once
                ok = await run.io_bound(starcat.enable_group, d, g)
                ui.notify(f"The catalog part '{g}' is switched on again" if ok else
                          f"The kept files of '{g}' do not fit this catalog: download it again", type="positive"
                          if ok else "warning")
            else:
                ui.notify(f"Downloading the catalog part '{g}' (see the log)")
                await run_process(PYSYZYGOS + ["catalog", "add", g, "--dir", d], log)
            cat_refresh()
            await sys_info_refresh()
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
            cat_refresh()                                       # cancel: the checkbox shows the part again
            await sys_info_refresh()

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

    async def cat_update(name, delete_old=True):
        """Bring a format-2 catalog to the newest published data version (setup --update-catalog)."""
        ui.notify("Updating the catalog: see the log for its progress")
        await run_process(PYSYZYGOS + ["setup", "--update-catalog", "--no-geoip", "--dir", name]
                          + (["--delete-old"] if delete_old else []), log)
        d = os.path.join(ROOT, name)
        if starcat.is_format2(d) and not starcat.update_available(d):
            ui.notify(f"{name} is now data version {starcat.data_version(d)}. The page reloads in 5 s.",
                      type="positive", timeout=5000)
            save_ui_state(catalog=name, site=state["name"])
            ui.timer(5.0, ui.navigate.reload, once=True)
        else:
            ui.notify("The update is not finished (see the log); run it again to resume", type="warning")
        opts = catalog_options()
        cat_sel.set_options(opts, value=cat_sel.value if cat_sel.value in opts else None)
        cat_refresh()
        await sys_info_refresh()

    def cat_upgrade_ask(name, parts, delete_old):
        """What the upgrade will do (source, time, disk), then run it."""
        d = os.path.join(ROOT, name)
        st = gaia_local.status(d)
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
                    await cat_upgrade(name, parts, delete_old)
                ui.button("Upgrade", on_click=go).props("color=primary")
                ui.button("Cancel", on_click=dlg.close).props("flat")
        dlg.open()

    async def cat_upgrade(name, parts="quality", delete_old=True):
        ui.notify("Upgrading the catalog: see the log for its progress")
        args = PYSYZYGOS + ["setup", "--upgrade-catalog", "--no-geoip", "--groups", parts, "--dir", name]
        await run_process(args + (["--delete-old"] if delete_old else []), log)
        d = os.path.join(ROOT, name)
        if starcat.is_format2(d):
            ui.notify(f"{name} is now in the new format" + ("; the old catalog is deleted" if delete_old and
                      not os.path.exists(d + ".old") else "") + ". The page reloads in 5 s.", type="positive",
                      timeout=5000)
            save_ui_state(catalog=name, site=state["name"])            # the reloaded page selects it
            ui.timer(5.0, ui.navigate.reload, once=True)              # header list and tabs from the new state
        else:
            ui.notify("The upgrade is not finished (see the log); run it again to resume", type="warning")
        opts = catalog_options()
        cat_sel.set_options(opts, value=cat_sel.value if cat_sel.value in opts else None)
        cat_refresh()
        await sys_info_refresh()

    def cat_delete_old(name):
        async def go():
            d.close()
            await run.io_bound(shutil.rmtree, os.path.join(ROOT, name), True)
            ui.notify(f"Deleted {name}", type="positive")
            cat_refresh()

        with ui.dialog() as d, ui.card():
            ui.label(f"Delete {name} (the catalog before the upgrade, with its star indexes and supplement)?")
            with ui.row():
                ui.button("Delete", on_click=go).props("color=negative")
                ui.button("Cancel", on_click=d.close).props("flat")
        d.open()

    async def sys_info_refresh():
        import subprocess
        env = dict(os.environ, PYSYZYGOS_HOME=ROOT, PYTHONUTF8="1",
                   PYTHONPATH=os.pathsep.join(x for x in (os.path.dirname(PKG), os.environ.get("PYTHONPATH")) if x))
        if cat_sel.value:
            env["PYSYZYGOS_CATALOG"] = cat_sel.value
        r = await run.io_bound(subprocess.run, PYSYZYGOS + ["info", "--json"], capture_output=True, text=True,
                               stdin=subprocess.DEVNULL,
                               cwd=ROOT, env=env, timeout=120)
        sys_info.clear()
        with sys_info:
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
        sys_refresh()

    off_chk.on_value_change(sys_toggle)
    sys_refresh()
    cat_refresh()
    planets_refresh()
    cat_sel.on_value_change(cat_refresh)
    tabs.on_value_change(lambda e: sys_info_refresh() if e.value in (t_sys, "System") else None)

    # ------------------------------------------------ path verification (pathcheck.py)
    with ui.dialog() as pc_dialog, ui.card().classes("w-full max-w-5xl"):
        pc_md = ui.markdown().classes("w-full text-sm")
        pc_state = {"md": None}
        with ui.row():
            ui.button("Download .md", on_click=lambda: ui.download(pc_state["md"], os.path.basename(pc_state["md"]))
                      if pc_state["md"] else None).props("outline dense")
            ui.button("Close", on_click=pc_dialog.close).props("flat dense")

    def pc_dir():
        from pysyzygos import pathcheck
        return pathcheck.fav_dir(fav_cur["key"], os.path.join(ROOT, favorites.DIR)) if fav_cur["key"] else None

    def pc_newest(pattern):
        import glob as _glob
        d = pc_dir()
        files = sorted(_glob.glob(os.path.join(d, pattern))) if d else []
        return files[-1] if files else None

    def pc_refresh():
        d = pc_dir()
        try:
            m = json.load(open(os.path.join(d, "meta.json")))
            f_pc_info.text = (f"Our path: computed {m['run_utc']} UTC with PySyzygos {m['version']}, orbit "
                              f"{m.get('orbit') or '?'}." + ("  Last comparison: " + os.path.basename(pc_newest('compare_*.md'))
                                                         if pc_newest('compare_*.md') else ""))
        except (OSError, ValueError, TypeError):
            f_pc_info.text = "Our path: not computed yet (Compute our path first)."
        st = pc_newest("steps_*.md")
        f_pc_steps_md.content = open(st, encoding="utf-8").read() if st else "*Not computed yet: Step by step.*"

    async def pc_run():
        if not fav_cur["key"]:
            return
        async def done(rc):
            pc_refresh()
            ui.notify("Our path is computed" if rc == 0 else "Computing our path failed: see the log",
                      type="positive" if rc == 0 else "negative")
        await run_process(PYSYZYGOS + ["path-check", "run", fav_cur["key"]], fav_log, on_done=done,
                          env_catalog=cat_sel.value, slot="fav")

    async def pc_export():
        if not fav_cur["key"]:
            return
        async def done(rc):
            f = pc_newest("pysyzygos_path_*.txt")
            if rc == 0 and f:
                ui.download(f, os.path.basename(f))
            else:
                ui.notify("Export failed: compute our path first (see the log)", type="negative")
        await run_process(PYSYZYGOS + ["path-check", "export", fav_cur["key"]], fav_log, on_done=done,
                          env_catalog=cat_sel.value, slot="fav")

    async def pc_upload(e):
        data = await e.file.read()
        f_pc_list.value = data.decode("utf-8", errors="replace") if b"\x00" not in data[:200] else ""
        ui.notify(f"Loaded {getattr(e.file, 'name', 'the file')}: {len(f_pc_list.value.splitlines())} lines")

    def pc_show(path=None):
        path = path or pc_newest("compare_*.md")
        if not path:
            ui.notify("No comparison yet", type="warning")
            return
        pc_md.content = open(path, encoding="utf-8").read()
        pc_state["md"] = path
        pc_dialog.open()

    async def pc_compare():
        if not fav_cur["key"]:
            return
        if not (f_pc_list.value or "").strip():
            ui.notify("Paste Occult's path listing first (or load its .txt)", type="warning")
            return
        d = pc_dir()
        if not os.path.isfile(os.path.join(d, "path.npz")):
            ui.notify("Compute our path first", type="warning")
            return
        lp, hp = os.path.join(d, "occult_input.txt"), os.path.join(d, "occult_header_input.txt")
        open(lp, "w", encoding="utf-8").write(f_pc_list.value)
        open(hp, "w", encoding="utf-8").write(f_pc_head.value or "")
        async def done(rc):
            pc_refresh()
            if rc == 0:
                pc_show()
            else:
                ui.notify("The comparison failed: see the log", type="negative")
        await run_process(PYSYZYGOS + ["path-check", "compare", fav_cur["key"], lp, "--header", hp], fav_log,
                          on_done=done, env_catalog=cat_sel.value, slot="fav")

    async def pc_steps():
        if not fav_cur["key"]:
            return
        if not os.path.isfile(os.path.join(pc_dir(), "path.npz")):
            ui.notify("Compute our path first", type="warning")
            return
        async def done(rc):
            pc_refresh()
            if rc == 0:
                f_pc_steps.open()
            else:
                ui.notify("Step by step failed: see the log", type="negative")
        await run_process(PYSYZYGOS + ["path-check", "steps", fav_cur["key"]], fav_log, on_done=done,
                          env_catalog=cat_sel.value, slot="fav")

    async def pc_keep():
        if fav_cur["key"]:
            await run_process(PYSYZYGOS + ["path-check", "keep", fav_cur["key"]], fav_log, slot="fav")

    def on_fav_select(e):
        fav_cur["key"] = e.args if isinstance(e.args, str) else (e.args or [None])[0]
        show_fav()

    def on_fav_changed(_):                        # the page changed favorites (mass actions): refresh the panel
        if fav_cur["key"] not in set(favorites.keys()):
            fav_cur["key"] = None
        show_fav()

    ui.on("fav_select", on_fav_select)
    ui.on("fav_changed", on_fav_changed)
    tabs.on_value_change(lambda e: load_favs() if e.value == t_fav or e.value == "Favorites" else None)
    load_favs()

    async def run_pick():
        if not catalog_ok():
            return
        ensure_saved()
        args = PYSYZYGOS + ["pick", "--start", p_start.value, "--days", str(int(p_days.value)),
                "--top", str(int(p_top.value)), "--workers", str(int(p_workers.value)), "--sort", p_sort.value]
        args += ["--all"] if p_all.value else ["--hmax", str(p_hmax.value)]
        if p_mag.value:
            args += ["--cam-limit", f"{float(p_mag.value):g}"]
        if p_pre.value != "all":
            args += ["--prescreen", p_pre.value]                # "auto" or a file

        async def done(rc):
            if rc == 0:
                n = load_pick(select=picks.paths(state["name"], p_start.value, int(p_days.value), picks_dir)[0])
                s_use_file.value = True
                ui.notify(f"{n} events; saved for site {state['name']}", type="positive")
        await run_process(args, log, env_site=state["name"], on_done=done, env_catalog=cat_sel.value)


    async def run_prescreen():
        if not catalog_ok():
            return
        ensure_saved()
        v = ps_where.value
        where = (["--region", v.split(":", 1)[1]] if v.startswith("region:") else
                 {"site": ["--around-site", f"{float(ps_km.value or 300):g}"],
                  "sites": ["--around-sites", f"{float(ps_km.value or 300):g}"], "global": ["--global"]}[v])
        args = PYSYZYGOS + ["prescreen", "build", "--start", ps_start.value, "--days", str(int(ps_days.value)),
                           *where, "--workers", str(int(p_workers.value))]
        args += ["--all"] if p_all.value else ["--hmax", str(p_hmax.value)]
        args += ["--cam-limit", f"{max(16.0, float(p_mag.value or 0)):g}"]
        if ps_fresh.value:
            args += ["--fresh"]
            ps_fresh.value = False

        async def done(rc):
            prescreen_options()
            if rc == 0:
                ui.notify("Pre-screen built; picks inside its region and window use it ('Asteroids: auto')",
                          type="positive")
            else:
                ui.notify("Pre-screen not finished; the same build again resumes it", type="warning")
        await run_process(args, log, env_site=state["name"], on_done=done, env_catalog=cat_sel.value)


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


PRE_FIXED = {"auto": "auto: a fitting pre-screen, else all", "all": "all asteroids (any place and time; slower)"}


def prescreen_regions():
    """Region choices of the Pre-screens panel: around the site(s), the named regions of prescreen.REGIONS (with
    their lat/lon box), the whole Earth."""
    from pysyzygos import prescreen as PS
    hemi = lambda x, p, n: f"{abs(x):g}{p if x >= 0 else n}"
    out = {"site": "around this site", "sites": "around all my sites"}
    for k, (la0, la1, lo0, lo1) in PS.REGIONS.items():
        out["region:" + k] = (f"{k.replace('-', ' ').title().replace('Usa', 'USA')} ({hemi(la0, 'N', 'S')}..{hemi(la1, 'N', 'S')}, "
                              f"{hemi(lo0, 'E', 'W')}..{hemi(lo1, 'E', 'W')})")
    out["global"] = "whole Earth (any site)"
    return out


def _day_et(date):
    """Seconds of 00:00 UTC of a YYYY-MM-DD date on one scale (for comparing pick and pre-screen windows in the GUI,
    which has no SPICE; both start at 00:00 UTC, so the offset to ET cancels)."""
    import calendar
    return float(calendar.timegm(time.strptime(str(date)[:10], "%Y-%m-%d")))


KSTARS_OPT = dict(set_location=True)                   # Results tab option, read by /api/kstars/show


def today_utc():
    """Today's date (UTC), the default start of the Pick and Search windows in the GUI (pysyzygos_config.ct is only the
    command-line default)."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


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

    @app.get("/api/kstars/status")
    def kstars_status():
        ok, msg = kstars.available()
        return {"ok": ok, "msg": msg}

    @app.get("/api/kstars/show")
    def kstars_show(ra: float, dec: float, utc: str, fov: float = 2.0, lat: float = None, lon: float = None,
                    ele: float = 0.0):
        ok, msg = kstars.show(ra, dec, utc, fov, lat, lon, ele, set_location=KSTARS_OPT["set_location"])
        return {"ok": ok, "msg": msg}

    @app.get("/api/stellarium/show")
    def stellarium_show(ra: float, dec: float, utc: str, fov: float = 2.0, lat: float = None, lon: float = None,
                        ele: float = 0.0):
        tz = site_timezone(lat, lon) if KSTARS_OPT["set_location"] and lat is not None and lon is not None else None
        ok, msg = stellarium.show(ra, dec, utc, fov, lat, lon, ele, set_location=KSTARS_OPT["set_location"], tz=tz)
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
    # always the decimal point: Firefox formats number fields by the page's language (German: "45,12345"), while the
    # values, logs and reports are Python's "45.12345". The page declares English before it is drawn, and every number
    # field carries lang="en" itself (so a browser translation or add-on cannot change it either)
    ui.add_head_html("<script>document.documentElement.lang = 'en';</script>", shared=True)
    ui.number.default_props("lang=en")
    ui.run(host="127.0.0.1", port=a.port, title="PySyzygos", favicon=os.path.join(PKG, "pysyzygos_logo.svg"),
           show=not a.no_browser, reload=False, reconnect_timeout=60, language="en-US")   # a busy browser keeps its page


if __name__ in {"__main__", "__mp_main__"}:
    main()
