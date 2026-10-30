"""selfupdate.py on throwaway repositories (no network): a 'release' remote, an install cloned from it, a new version
pushed; status sees it (commits, version, CHANGELOG entry), update fast-forwards; local changes and a diverged
checkout are refused and left untouched. Needs git."""
import os, shutil, subprocess, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
from pysyzygos import selfupdate as S

if shutil.which("git") is None:
    print("SELFUPDATE TESTS SKIPPED (no git)"); sys.exit(0)
assert S.version_tuple("v1.2.01") == (1, 2, 1) and S.version_tuple("1.4") == (1, 4, 0)
log = "# Changelog\n\n## [Unreleased]\n- x\n\n## [1.5.0] \"B\" - 2026-11-01\n- new\n\n## [1.4.0] \"B\"\n- old\n"
assert S.changelog_head(log, "1.4.0").splitlines() == ["## [Unreleased]", "- x", "", '## [1.5.0] "B" - 2026-11-01', "- new"]

T = tempfile.mkdtemp()
run = lambda *a, cwd=T: subprocess.run(a, cwd=cwd, check=True, capture_output=True, text=True)
env_git = ["-c", "user.email=t@t", "-c", "user.name=t"]
def write(repo, version, entry):
    os.makedirs(os.path.join(repo, "src", "pysyzygos"), exist_ok=True)
    open(os.path.join(repo, "src", "pysyzygos", "version.py"), "w").write(f'__version__ = "{version}"\n')
    open(os.path.join(repo, "CHANGELOG.md"), "w").write(f"# Changelog\n\n{entry}## [1.4.0] \"B\"\n- old\n")
run("git", "init", "-q", "--bare", "-b", "main", "remote.git")
run("git", "clone", "-q", "remote.git", "dev")
dev = os.path.join(T, "dev")
write(dev, "1.4.0", "")
run("git", "add", "-A", cwd=dev); run("git", *env_git, "commit", "-qm", "1.4.0", cwd=dev); run("git", "push", "-q", "origin", "main", cwd=dev)
run("git", "clone", "-q", "remote.git", "inst")
inst = os.path.join(T, "inst")
s = S.status(repo=inst, release=False)
assert s["kind"] == "git" and s["behind"] == 0 and not s["possible"] and s["reason"] == "up to date", s
# far above any real version: the CHANGELOG lines newer than the running one
write(dev, "99.0.0", "## [99.0.0] \"B\" - 2026-11-01\n- new feature\n\n")
run("git", "add", "-A", cwd=dev); run("git", *env_git, "commit", "-qm", "99.0.0: new feature", cwd=dev); run("git", "push", "-q", "origin", "main", cwd=dev)
s = S.status(repo=inst, release=False)
assert s["behind"] == 1 and s["possible"] and s["remote_version"] == "99.0.0" and "new feature" in s["changelog"], s
assert s["commits"][0][1] == "99.0.0: new feature"
# local change to a tracked file: refused, untouched
open(os.path.join(inst, "CHANGELOG.md"), "a").write("my note\n")
s = S.status(repo=inst, release=False)
assert not s["possible"] and s["dirty"] == ["CHANGELOG.md"] and "local changes" in s["reason"], s
assert S.update(lambda *a: None, repo=inst) == 1 and "my note" in open(os.path.join(inst, "CHANGELOG.md")).read()
run("git", "checkout", "--", "CHANGELOG.md", cwd=inst)
open(os.path.join(inst, "sites.py"), "w").write("private = 1\n")              # untracked files do not block
msgs = []
assert S.update(msgs.append, repo=inst, deps=False) == 0, msgs
assert '99.0.0' in open(os.path.join(inst, "src", "pysyzygos", "version.py")).read() and os.path.isfile(os.path.join(inst, "sites.py"))
assert S.status(repo=inst, release=False)["behind"] == 0
# diverged: a local commit plus a new remote one: refused
write(dev, "1.6.0", "## [1.6.0]\n- more\n\n")
run("git", "add", "-A", cwd=dev); run("git", *env_git, "commit", "-qm", "1.6.0", cwd=dev); run("git", "push", "-q", "origin", "main", cwd=dev)
open(os.path.join(inst, "mine.txt"), "w").write("x")
run("git", "add", "mine.txt", cwd=inst); run("git", *env_git, "commit", "-qm", "mine", cwd=inst)
s = S.status(repo=inst, release=False)
assert not s["possible"] and s["ahead"] == 1 and "diverged" in s["reason"], s
shutil.rmtree(T)
print("SELFUPDATE TESTS PASSED")
