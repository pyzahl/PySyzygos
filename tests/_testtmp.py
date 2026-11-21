"""_testtmp.py - every temporary file of one test run in one folder, deleted when the test ends.

Imported first by each test (`import _testtmp`): tempfile.mkdtemp() / mkstemp() / TemporaryDirectory then land in
/tmp/pysyzygos-test-XXXX (TMPDIR too, so child processes follow), removed at exit. Before, every run left its
folders in /tmp, which is a RAM disk on many Linux systems (2026-11-19: ~790 folders, 1.9 GB).
"""
import atexit, os, shutil, tempfile

ROOT = tempfile.mkdtemp(prefix="pysyzygos-test-")
tempfile.tempdir = ROOT
os.environ["TMPDIR"] = ROOT
atexit.register(shutil.rmtree, ROOT, True)
