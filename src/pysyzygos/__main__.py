"""pysyzygos - start the web interface or one of the tools.

    pysyzygos                         web interface (GUI); same as `pysyzygos gui`, options e.g. --port 8081 --no-browser
    pysyzygos setup                   one-time setup: your site, SPICE kernels, local Gaia catalog (resumable)
    pysyzygos pick ...                event finder over all asteroids (targets for the search)
    pysyzygos search                  the prediction for the targets (settings: pysyzygos_config.py)
    pysyzygos report hits_log.csv     results as an HTML or Markdown page
    pysyzygos owc-check               compare with an OWC search result (owc_reference.txt)
    pysyzygos gaia build|status|...   the local Gaia catalog
    pysyzygos picks list|import       saved picks
    pysyzygos prescreen build|list    pre-screened target lists per region and window (pick --prescreen)
    pysyzygos favorites ...           favorites list (page, CSV)
    pysyzygos path-check ...          a favorite's path, fresh, and its comparison with an Occult listing
    pysyzygos offline on|off|copy|status   keep copies of orbit downloads for use without network
    pysyzygos info [--json]           what data is installed and in use (time, Earth, catalogs, asteroids)
    pysyzygos kstars ...              point KStars (Linux)
    pysyzygos stellarium ...          point Stellarium (Remote Control plugin)
    pysyzygos run <command> '<json>'  a search or pick with settings overridden for this run (used by the GUI)
    pysyzygos cleanup [--yes]         remove downloads and generated files (keeps the Gaia catalogs; lists first)

`pysyzygos <command> --help` shows a command's options. Also: python -m pysyzygos <command> ...
Every command runs in the data folder: a checkout's project folder, else the folder chosen at the first
`pysyzygos setup` (default ~/PySyzygos; change it with `pysyzygos setup --home <folder>`), or PYSYZYGOS_HOME for one run.
`pysyzygos setup --status` shows which one is used.
"""
import importlib, os, runpy, sys, time
os.environ.setdefault("PYSYZYGOS_T0", repr(time.time()))   # when the command started (run timings, e.g. the pick's)

COMMANDS = {"gui": "gui", "setup": "setup", "pick": "pick", "search": "search", "report": "report",
            "owc-check": "owc_check", "gaia": "gaia_local", "catalog": "starcat", "planets": "bodies", "picks": "picks", "prescreen": "prescreen", "favorites": "favorites",
            "kstars": "kstars", "stellarium": "stellarium", "run": "runner", "cleanup": "cleanup",
            "path-check": "pathcheck", "offline": "offline", "info": "sysinfo"}
SCRIPTS = {"search"}            # not import-safe (sets up SPICE at import): executed as a script


def run(command, args):
    """Run one command with its arguments, in the data folder."""
    from pysyzygos import home
    if command != "setup":                                    # setup chooses the data folder itself (first run, --home)
        os.makedirs(home.HOME, exist_ok=True)
        os.chdir(home.HOME)
    module = f"pysyzygos.{COMMANDS[command]}"
    sys.argv = [f"pysyzygos {command}"] + list(args)
    if command in SCRIPTS:
        runpy.run_module(module, run_name="__main__", alter_sys=True)
        return 0
    # imported, then main(): functions handed to worker processes (pick, gaia build) keep their module name
    return importlib.import_module(module).main()


def safe_console():
    """Never crash on a character the console cannot show (Windows consoles with a legacy code page such as cp1252
    cannot encode e.g. the check mark of the kernel download): replace it with '?' instead. Runs started by the GUI use
    Python's UTF-8 mode (PYTHONUTF8), so their log shows every character."""
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass


def main(argv=None):
    safe_console()
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv and argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    if argv and argv[0] == "--version":
        from pysyzygos.version import __version__, __codename__
        print(f"PySyzygos {__version__} “{__codename__}”")
        return 0
    if not argv or argv[0].startswith("-"):                  # no command (or GUI options only): the GUI
        argv = ["gui"] + argv
    if argv[0] not in COMMANDS:
        sys.exit(f"pysyzygos: unknown command {argv[0]!r}; commands: {', '.join(COMMANDS)} (pysyzygos --help)")
    rc = run(argv[0], argv[1:])
    return rc if isinstance(rc, int) else 0


if __name__ == "__main__":
    sys.exit(main())
