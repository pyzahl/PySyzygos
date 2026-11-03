"""home.py - where PySyzygos's code and your data live.

PKG: the package folder (code, templates, the logo, data/ne_110m_earth.json).
HOME: the data folder: sites.py, pysyzygos_config.py, SPICE kernels, Gaia catalogs, picks/, favorites/, maps/,
hits_log.csv, ... Every tool runs with HOME as its working folder, so relative paths in the configuration (map_dir,
gaia_local_dir, picks_dir) are relative to it. HOME is, first match:
  1. "env":      the environment variable PYSYZYGOS_HOME (one run, tests, several setups side by side);
  2. "setting":  the folder saved in the settings file POINTER (`pysyzygos setup --home <folder>`, or setup's question
                 on the first run of an installed copy):
                   Linux    ~/.config/pysyzygos/home  (or $XDG_CONFIG_HOME/pysyzygos/home)
                   macOS    ~/Library/Application Support/PySyzygos/home
                   Windows  %APPDATA%\\PySyzygos\\home
  3. "checkout": the project folder (the one with pyproject.toml) when PySyzygos runs from a source checkout (git clone
                 + `pip install -e .`, `uv run`), so a clone keeps its data in its own folder;
  4. "default":  DEFAULT, ~/PySyzygos (an installed copy without a setting yet).
SOURCE tells which one applied.
Renamed from PyOccult in 1.0.0; the old names still work for a transition period: PYOCCULT_* environment variables
(copied to PYSYZYGOS_*), the old settings file (LEGACY_POINTER, copied to POINTER once) and an existing ~/PyOccult.
"""
import os, sys

PKG = os.path.dirname(os.path.abspath(__file__))
LEGACY_DEFAULT = os.path.join(os.path.expanduser("~"), "PyOccult")             # name before 1.0.0
DEFAULT = os.path.join(os.path.expanduser("~"), "PySyzygos")
if not os.path.isdir(DEFAULT) and os.path.isdir(LEGACY_DEFAULT):
    DEFAULT = LEGACY_DEFAULT                                                     # keep using an existing data folder


def config_dir(platform=sys.platform, environ=os.environ, name="PySyzygos"):
    """The system's folder for PySyzygos's own settings: the data-folder setting (POINTER) and the observation
    GUI's connection file for PyStarLight (obsreport.API_FILE)."""
    if platform.startswith("win"):
        return os.path.join(environ.get("APPDATA") or os.path.expanduser("~\\AppData\\Roaming"), name)
    if platform == "darwin":
        return os.path.join(os.path.expanduser("~"), "Library", "Application Support", name)
    return os.path.join(environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config"), name.lower())


POINTER = os.path.join(config_dir(), "home")
LEGACY_POINTER = os.path.join(config_dir(name="PyOccult"), "home")


def legacy_env(environ=os.environ):
    """PYOCCULT_<X> -> PYSYZYGOS_<X> where the new name is not set (names before 1.0.0)."""
    for k, v in list(environ.items()):
        if k.startswith("PYOCCULT_"):
            environ.setdefault("PYSYZYGOS_" + k[len("PYOCCULT_"):], v)


def legacy_pointer(pointer=POINTER, legacy=LEGACY_POINTER):
    """Copy the data-folder setting of a version before 1.0.0 to the new settings file (once; the old one stays)."""
    if os.path.isfile(pointer) or not os.path.isfile(legacy):
        return
    try:
        with open(legacy, encoding="utf-8") as f:
            saved = f.read().strip()
        if saved:
            save(saved, pointer)
            print(f"data-folder setting copied from {legacy} to {pointer} (PyOccult is now PySyzygos)", file=sys.stderr)
    except OSError:
        pass


def resolve(environ=os.environ, pointer=POINTER, pkg=PKG, default=DEFAULT):
    """(data folder, source) by the rules above."""
    env = environ.get("PYSYZYGOS_HOME")
    if env:
        return os.path.abspath(os.path.expanduser(env)), "env"
    try:
        with open(pointer, encoding="utf-8") as f:
            saved = f.read().strip()
        if saved:
            return os.path.abspath(os.path.expanduser(saved)), "setting"
    except OSError:
        pass
    checkout = os.path.dirname(os.path.dirname(pkg))                   # <project>/src/pysyzygos -> <project>
    if os.path.isfile(os.path.join(checkout, "pyproject.toml")):
        return checkout, "checkout"
    return default, "default"


def legacy_files(home):
    """Rename the data folder's files of a version before 1.0.0 (PyOccult): pyoccult_config.py -> pysyzygos_config.py
    with the old names inside replaced (environment variables, pyoccult.db; the original kept as
    pyoccult_config.py.pre-1.0), pyoccult.db (+ -wal, -shm) -> pysyzygos.db. Only where the new file does not exist yet.
    Returns the messages."""
    out = []
    old, new = os.path.join(home, "pyoccult_config.py"), os.path.join(home, "pysyzygos_config.py")
    if os.path.isfile(old) and not os.path.exists(new):
        with open(old, encoding="utf-8") as f:
            text = f.read()
        for a, b in (("PyOccult", "PySyzygos"), ("pyoccult", "pysyzygos"), ("PYOCCULT", "PYSYZYGOS")):
            text = text.replace(a, b)
        with open(new + ".tmp", "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(new + ".tmp", new)
        os.replace(old, old + ".pre-1.0")
        out.append(f"{old} -> {new} (the original kept as {old}.pre-1.0)")
    old, new = os.path.join(home, "pyoccult.db"), os.path.join(home, "pysyzygos.db")
    if os.path.isfile(old) and not os.path.exists(new):
        for ext in ("-wal", "-shm", ""):                                 # the main file last
            if os.path.isfile(old + ext):
                os.replace(old + ext, new + ext)
        out.append(f"{old} -> {new}")
    return out


def save(folder, pointer=POINTER):
    """Remember folder as the data folder (writes the settings file, creates the folder). Returns its full path."""
    folder = os.path.abspath(os.path.expanduser(folder))
    os.makedirs(folder, exist_ok=True)
    os.makedirs(os.path.dirname(pointer), exist_ok=True)
    tmp = pointer + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(folder + "\n")
    os.replace(tmp, pointer)
    return folder


def describe(home=None, source=None):
    """'~/PySyzygos (setting in ~/.config/pysyzygos/home)': the data folder and why, for status lines."""
    home, source = (home, source) if home else (HOME, SOURCE)
    why = {"env": "environment variable PYSYZYGOS_HOME", "setting": f"setting in {POINTER}",
           "checkout": "project folder of this checkout", "default": "default for an installed copy"}[source]
    return f"{home} ({why})"


legacy_env()
legacy_pointer()
HOME, SOURCE = resolve()
