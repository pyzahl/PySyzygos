"""gui_system.log_tail: the last lines of a background job's log (System tab: catalog download / build), with Unix
and Windows line ends; a progress line rewritten with \\r counts once, as last shown. A Windows log (\\r\\n) once
showed as "(empty)": the text after the line end's \\r was all that was kept."""
import _testtmp  # noqa: F401  (temporary files of this run in one folder, removed at exit)
import os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
os.environ["PYSYZYGOS_HOME"] = tempfile.mkdtemp()
from pysyzygos import gui_system as GS

root = GS.ROOT
text = "start\n   download: 10 %\r   download: 50 %\r   download: 100 %\nunpacking ...\n"
for name, data in (("unix.log", text.encode()), ("win.log", text.replace("\n", "\r\n").encode())):
    with open(os.path.join(root, name), "wb") as f:
        f.write(data)
    got = GS.log_tail(name)
    assert got == ["start", "   download: 100 %", "unpacking ..."], (name, got)
    assert GS.log_tail(name, 1) == ["unpacking ..."], name
assert GS.log_tail("missing.log") == []
print("log_tail: ok")
