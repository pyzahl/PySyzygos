"""gui_common.py - what the GUI's modules share (gui.py and the tab modules gui_<tab>.py): the remembered GUI
choices (gui_state.json), site helpers, the catalog selector's choices, running PySyzygos commands as processes with
their output in a log (and a log file per run in logs/), the resizable list boxes, small date helpers.
"""
from pysyzygos.version import __version__
import asyncio, json, math, os, re, sys, time

from pysyzygos import starcat
from pysyzygos.home import HOME as ROOT, PKG                      # ROOT: the data folder (sites.py, maps/, ...)
from nicegui import ui

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


# ---------------------------------------------------------------- GUI state, site helpers
UI_STATE = os.path.join(ROOT, "gui_state.json")                  # last selected site and catalog (data folder)


def load_ui_state():
    try:
        with open(UI_STATE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def dist_args():
    """The report's --distance (System tab: shadow distance on the ground, default, or in the fundamental plane)."""
    return ["--distance", load_ui_state().get("shadow_distance") or "ground"]


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


LOG_DIR, LOG_KEEP_DAYS = "logs", 30          # every GUI run's output, one file per run (<data folder>/logs)


HOOKS = {}                                   # set by the page: "steps" (show a run's step summary)


def open_run_log(args):
    """A new log file for a run: logs/<YYYYmmdd-HHMMSS>_<command>.log (files older than LOG_KEEP_DAYS deleted).
    Returns (file or None, its path relative to the data folder)."""
    d = os.path.join(ROOT, LOG_DIR)
    try:
        os.makedirs(d, exist_ok=True)
        cut = time.time() - LOG_KEEP_DAYS * 86400
        for f in os.listdir(d):
            p = os.path.join(d, f)
            if f.endswith(".log") and os.path.getmtime(p) < cut:
                os.remove(p)
        words = [x for x in args[args.index("pysyzygos") + 1:] if not x.startswith(("-", "{"))] \
            if "pysyzygos" in args else [os.path.basename(args[0])]
        cmd = "_".join(words[:2]) if words[:1] in (["run"], ["prescreen"], ["catalog"]) else (words or ["run"])[0]
        rel = os.path.join(LOG_DIR, time.strftime("%Y%m%d-%H%M%S") + f"_{re.sub(r'[^A-Za-z0-9_.-]', '_', cmd)}.log")
        return open(os.path.join(ROOT, rel), "w", encoding="utf-8"), rel
    except OSError:
        return None, ""


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
    env["PYSYZYGOS_T0"] = repr(time.time())               # this run's start (not the GUI's: start-up times)
    def push(text):
        # the page can be gone (browser closed, reloaded or stalled past the reconnect timeout): keep going without it,
        # and keep reading the output, or the process blocks on a full pipe and stays "in progress" forever
        try:
            log.push(text)
        except RuntimeError:
            pass

    flog, rel = open_run_log(args)

    def keep(text):                                          # the run's log file (logs/)
        if flog:
            try:
                flog.write(text + "\n")
                flog.flush()
            except OSError:
                pass

    head = (f"$ {' '.join(args)}" + (f"   (site {env_site})" if env_site else "")
            + (f"   (catalog {env_catalog})" if env_catalog else ""))
    push(head)
    keep(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  PySyzygos {__version__}\n{head}")
    t0 = time.time()
    proc = await asyncio.create_subprocess_exec(*args, cwd=ROOT, env=env, stdout=asyncio.subprocess.PIPE,
                                                stderr=asyncio.subprocess.STDOUT,
                                                stdin=asyncio.subprocess.DEVNULL)   # never waits for an answer:
    # without it the run inherits the terminal the GUI was started from, and setup's questions (no line end, so
    # not shown in the log) wait forever (found 2026-10-17 with "Install the new catalog")
    setattr(Job, slot, proc)
    from pysyzygos import steps as STP
    async for line in proc.stdout:
        text = line.decode(errors="replace").rstrip()
        keep(text)
        summary = STP.parse(text)
        if summary is not None:                              # the step summary: shown as a table, not as JSON
            summary["log"] = rel
            if HOOKS.get("steps") and slot == "proc":
                try:
                    HOOKS["steps"](summary)
                except RuntimeError:
                    pass
            continue
        push(text)
    rc = await proc.wait()
    push(f"--- finished with exit code {rc} in {time.time() - t0:.0f} s" + (f"; log saved: {rel}" if rel else ""))
    keep(f"--- finished with exit code {rc} in {time.time() - t0:.0f} s")
    if flog:
        flog.close()
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
