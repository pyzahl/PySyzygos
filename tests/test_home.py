"""The data folder (pysyzygos.home): order of the rules, the system settings folder, the saved setting."""
import _testtmp  # noqa: F401  (temporary files of this run in one folder, removed at exit)
import sys, os, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
from pysyzygos import home as H

tmp = tempfile.mkdtemp()
pointer = os.path.join(tmp, "cfg", "pysyzygos", "home")
checkout = os.path.join(tmp, "proj")
pkg = os.path.join(checkout, "src", "pysyzygos")
os.makedirs(pkg)
installed = os.path.join(tmp, "site-packages", "pysyzygos")
os.makedirs(installed)
default = os.path.join(tmp, "PySyzygos")

# installed copy, nothing set: the default
assert H.resolve({}, pointer, installed, default) == (default, "default")
# a checkout (pyproject.toml two levels up): its project folder
open(os.path.join(checkout, "pyproject.toml"), "w").close()
assert H.resolve({}, pointer, pkg, default) == (checkout, "checkout")
# a saved setting wins over the checkout; save() creates the folder and the settings file
chosen = H.save(os.path.join(tmp, "data"), pointer)
assert os.path.isdir(chosen) and open(pointer).read().strip() == chosen
assert H.resolve({}, pointer, pkg, default) == (chosen, "setting")
assert H.resolve({}, pointer, installed, default) == (chosen, "setting")
# the environment variable wins over everything (one run)
assert H.resolve({"PYSYZYGOS_HOME": os.path.join(tmp, "x")}, pointer, pkg, default) == (os.path.join(tmp, "x"), "env")
# an empty settings file counts as no setting
open(pointer, "w").close()
assert H.resolve({}, pointer, installed, default) == (default, "default")

# the system's settings folder
assert H.config_dir("linux", {}).endswith(os.path.join(".config", "pysyzygos"))
assert H.config_dir("linux", {"XDG_CONFIG_HOME": "/xdg"}) == os.path.join("/xdg", "pysyzygos")
assert H.config_dir("darwin", {}).endswith(os.path.join("Library", "Application Support", "PySyzygos"))
assert H.config_dir("win32", {"APPDATA": "C:\\Users\\u\\AppData\\Roaming"}).endswith("PySyzygos")
assert "setting in" in H.describe(chosen, "setting") and "checkout" in H.describe(checkout, "checkout")

# names before 1.0.0 (PyOccult): environment variables, the old settings file, the data folder's files
env = {"PYOCCULT_HOME": "/old", "PYOCCULT_SITE": "field", "PYSYZYGOS_SITE": "home", "OTHER": "1"}
H.legacy_env(env)
assert env["PYSYZYGOS_HOME"] == "/old" and env["PYSYZYGOS_SITE"] == "home" and "PYSYZYGOS_OTHER" not in env
assert H.config_dir("linux", {}, name="PyOccult").endswith(os.path.join(".config", "pyoccult"))
old_ptr, new_ptr = os.path.join(tmp, "old", "home"), os.path.join(tmp, "new", "home")
os.makedirs(os.path.dirname(old_ptr))
with open(old_ptr, "w") as f:
    f.write(os.path.join(tmp, "olddata") + "\n")
H.legacy_pointer(new_ptr, old_ptr)
assert open(new_ptr).read().strip() == os.path.join(tmp, "olddata") and os.path.isfile(old_ptr)
H.save(os.path.join(tmp, "newer"), new_ptr)
H.legacy_pointer(new_ptr, old_ptr)                                  # an existing new setting is never replaced
assert open(new_ptr).read().strip() == os.path.join(tmp, "newer")

d = os.path.join(tmp, "datafolder")
os.makedirs(d)
with open(os.path.join(d, "pyoccult_config.py"), "w") as f:
    f.write('site_name = _os.environ.get("PYOCCULT_SITE", default_site)\nresults_db = "pyoccult.db"   # PyOccult\n')
for n in ("pyoccult.db", "pyoccult.db-wal"):
    open(os.path.join(d, n), "w").close()
assert len(H.legacy_files(d)) == 2
new_cfg = open(os.path.join(d, "pysyzygos_config.py")).read()
assert "PYSYZYGOS_SITE" in new_cfg and '"pysyzygos.db"' in new_cfg and "PySyzygos" in new_cfg and "occult" not in new_cfg.lower()
assert sorted(os.listdir(d)) == ["pyoccult_config.py.pre-1.0", "pysyzygos.db", "pysyzygos.db-wal", "pysyzygos_config.py"]
assert H.legacy_files(d) == []                                       # once only
print("HOME TESTS PASSED")
