"""gaia_local.unpack_archive: a catalog .tar.xz (one top folder) unpacked in pieces (progress during large files),
files identical, the marker file present, members outside the folder skipped."""
import _testtmp  # noqa: F401  (temporary files of this run in one folder, removed at exit)
import io, os, sys, tarfile, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
from pysyzygos import gaia_local as GL

os.chdir(tempfile.mkdtemp())
big = os.urandom(3 * 1024 * 1024 + 123)          # several pieces with a small UNPACK_CHUNK
files = {"catalog.json": b'{"gmax": 16}', "core.npy": big, "sub/part.npy": b"x" * 1000}
with tarfile.open("cat.tar.xz", "w:xz") as tf:
    for name, data in files.items():
        info = tarfile.TarInfo("gaia_dr3_g16_v2/" + name)
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))
    evil = tarfile.TarInfo("gaia_dr3_g16_v2/../../evil.txt")
    evil.size = 4
    tf.addfile(evil, io.BytesIO(b"evil"))

GL.UNPACK_CHUNK = 1 << 20
GL.unpack_archive("cat.tar.xz", "gaia_dr3_g16")
for name, data in files.items():
    with open(os.path.join("gaia_dr3_g16", *name.split("/")), "rb") as f:
        assert f.read() == data, name
assert not os.path.exists("gaia_dr3_g16.unpack"), "the staging folder is removed"
assert not os.path.exists("evil.txt") and not os.path.exists(os.path.join("..", "evil.txt")), "a ../ member skipped"
print("unpack_archive: ok")
