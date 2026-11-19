"""pysyzygos cleanup: a dry run deletes nothing; --yes deletes downloads, PySyzygos's own cache files, catalog extras
and run outputs, but never the catalogs' star files, owc_refs/, private-docs/, release/, other files in the cache
folder, or (without --all) your settings; --keep-results keeps the run outputs. In a temporary folder."""
import _testtmp  # noqa: F401  (temporary files of this run in one folder, removed at exit)
import sys, os, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
from pysyzygos import cleanup as CL, home as H

root = tempfile.mkdtemp()
cache = tempfile.mkdtemp()
os.chdir(root)


def touch(p, n=10):
    os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    with open(p, "wb") as f:
        f.write(b"x" * n)


def make():
    for p in ("de440.bsp", "naif0012.tls", "jup365.bsp", "data/ObsCodes.html", "sbdb_cache.json",
              "gaia_dr3_g16/catalog.json", "gaia_dr3_g16/GaiaSource_000000-003111.npy",
              "gaia_dr3_g16/bright_G15.0.v2.npy", "gaia_dr3_g16/supplement/catalog.json",
              "pysyzygos.db", "hits_log.csv", "maps/a.kml", "picks/x.py", "prescreen/p.db", "gaia_build.log",
              "targets.py", "sites.py~", "pyoccult.db", "pyoccult_config.py",      # names before 1.0.0
              "sites.py", "pysyzygos_config.py", "favorites/favorites.json", "gui_state.json",
              "owc_refs/set.txt", "owc_reference.txt", "private-docs/n.md", "release/gaia_dr3_g16.tar.xz", "run.sh"):
        touch(os.path.join(root, p))
    for p in ("PySyzygos_asteroid_1_a_b.bsp", "PySyzygos_sbdb_cache.json", "pysyzygos_exports/x.csv",
              "PyOccult_asteroid_1_a_b.bsp", "PyOccult_sbdb_phys.json",
              "someone_elses_file.dat"):
        touch(os.path.join(cache, p))


CL.cache_path = lambda: cache
H.POINTER = os.path.join(root, "pointer_home")
H.LEGACY_POINTER = os.path.join(root, "pointer_home_old")       # never the real ~/.config/pyoccult/home
make()
touch(H.POINTER)
touch(H.LEGACY_POINTER)

ex = lambda p: os.path.exists(os.path.join(root, p))
KEEP_ALWAYS = ("gaia_dr3_g16/catalog.json", "gaia_dr3_g16/GaiaSource_000000-003111.npy", "owc_refs/set.txt",
               "owc_reference.txt", "private-docs/n.md", "release/gaia_dr3_g16.tar.xz", "run.sh")
SETTINGS = ("sites.py", "pysyzygos_config.py", "favorites/favorites.json", "gui_state.json", "pyoccult_config.py")
GONE = ("de440.bsp", "naif0012.tls", "jup365.bsp", "data/ObsCodes.html", "sbdb_cache.json",
        "gaia_dr3_g16/bright_G15.0.v2.npy", "gaia_dr3_g16/supplement")
OUTPUTS = ("pysyzygos.db", "pyoccult.db", "hits_log.csv", "maps", "picks", "prescreen", "gaia_build.log", "targets.py", "sites.py~")

# --orbits: only the orbit files in the cache; --cache: all PySyzygos's cache files; nothing else, no --yes needed
assert CL.main(["--orbits"]) == 0
assert sorted(os.listdir(cache)) == ["PyOccult_sbdb_phys.json", "PySyzygos_sbdb_cache.json", "pysyzygos_exports",
                                     "someone_elses_file.dat"], os.listdir(cache)
assert CL.main(["--cache"]) == 0 and sorted(os.listdir(cache)) == ["someone_elses_file.dat"]
assert all(ex(p) for p in KEEP_ALWAYS + SETTINGS + GONE + OUTPUTS)
make()

# a dry run deletes nothing
assert CL.main([]) == 0
assert all(ex(p) for p in KEEP_ALWAYS + SETTINGS + GONE + OUTPUTS)

# --keep-results: downloads, caches, catalog extras go; run outputs, settings and the protected stay
assert CL.main(["--yes", "--keep-results"]) == 0
assert not any(ex(p) for p in GONE), [p for p in GONE if ex(p)]
assert all(ex(p) for p in KEEP_ALWAYS + SETTINGS + OUTPUTS)
assert sorted(os.listdir(cache)) == ["someone_elses_file.dat"], os.listdir(cache)

# --yes: the run outputs too; settings kept
assert CL.main(["--yes"]) == 0
assert not any(ex(p) for p in OUTPUTS) and all(ex(p) for p in KEEP_ALWAYS + SETTINGS)
assert os.path.isfile(H.POINTER)

# --all --yes: settings and the data-folder setting as well; the protected and the star files still there
assert CL.main(["--all", "--yes"]) == 0
assert not any(ex(p) for p in SETTINGS) and not os.path.exists(H.POINTER) and not os.path.exists(H.LEGACY_POINTER)
assert all(ex(p) for p in KEEP_ALWAYS)
assert CL.main([]) == 0                                     # nothing left to clean
print("CLEANUP TESTS PASSED")
