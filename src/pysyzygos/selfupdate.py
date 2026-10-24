"""selfupdate.py - is a newer PySyzygos available, and update a git checkout (System tab).

    pysyzygos update            # git pull --ff-only (+ the dependencies when they changed)
    pysyzygos update --check    # only say what is available

A git checkout (the folder PySyzygos runs from has .git): `git fetch`, then the commits the tracked branch is ahead
by, the version and the CHANGELOG entry there. The update is `git pull --ff-only`: it never merges and never touches
local changes; it refuses when the checkout has changes to tracked files, has diverged, or tracks no branch. When
pyproject.toml or uv.lock changed: `uv sync` (an install made by uv) or `pip install -e .` (the folder's venv).
Without git (a ZIP): the newest GitHub release against this version, with its link. Standard library only.
"""
import argparse, json, os, re, shutil, subprocess, sys

from pysyzygos.version import __version__
from pysyzygos import urls as U

TIMEOUT_S = 30


def repo_dir():
    """The folder PySyzygos runs from (src/pysyzygos/.. /..) if it is a git checkout, else None."""
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return root if os.path.exists(os.path.join(root, ".git")) else None


def git(*args, repo=None, timeout=TIMEOUT_S):
    """(returncode, stdout, stderr) of a git command in the checkout; never asks for a password."""
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", LC_ALL="C")
    try:
        p = subprocess.run(["git", *args], cwd=repo or repo_dir(), capture_output=True, text=True, timeout=timeout,
                           env=env)
        return p.returncode, p.stdout.rstrip(), p.stderr.strip()    # (leading blanks matter: git status)
    except (OSError, subprocess.SubprocessError) as ex:
        return 1, "", str(ex)


def version_tuple(v):
    """(1, 4, 0) from '1.4.0' or 'v1.2.01' (missing parts 0)."""
    nums = [int(x) for x in re.findall(r"\d+", str(v))[:3]]
    return tuple(nums + [0] * (3 - len(nums)))


def changelog_head(text, newer_than=__version__):
    """The CHANGELOG's entries above this version (the newest first): the text up to '## [<this version>]'."""
    out, keep = [], False
    for line in text.splitlines():
        m = re.match(r"## \[([^\]]+)\]", line)
        if m:
            v = m.group(1)
            if v.lower() != "unreleased" and version_tuple(v) <= version_tuple(newer_than):
                break
            keep = True
        if keep:
            out.append(line)
    return "\n".join(out).strip()


def latest_release(timeout=15):
    """dict(tag, name, url, published) of the newest GitHub release, or None (offline, no release)."""
    from pysyzygos import net
    try:
        with net.urlopen(U.URL_GITHUB_LATEST_RELEASE, timeout=timeout) as r:
            d = json.load(r)
        return dict(tag=d.get("tag_name", ""), name=d.get("name", ""), url=d.get("html_url", ""),
                    published=str(d.get("published_at", ""))[:10])
    except Exception:
        return None


def status(fetch=True, repo=None, release=True):
    """What is available: dict(kind 'git' | 'zip', version, and for git: branch, upstream, behind, ahead, dirty
    (changed tracked files), commits [(hash, subject)], remote_version, changelog (the new entries), possible
    (an update can be pulled), reason (why not), error; for a ZIP: release (latest_release), newer (bool)."""
    s = dict(version=__version__, changelog_url=U.URL_CHANGELOG)
    repo = repo or repo_dir()
    rel = latest_release() if release else None
    s.update(release=rel, release_newer=bool(rel and version_tuple(rel["tag"]) > version_tuple(__version__)))
    if repo is None:
        s.update(kind="zip", possible=False, reason="not a git checkout (installed from a ZIP): download the release")
        return s
    s["kind"] = "git"
    if shutil.which("git") is None:
        s.update(possible=False, reason="git is not installed", behind=0)
        return s
    rc, branch, _ = git("rev-parse", "--abbrev-ref", "HEAD", repo=repo)
    rc2, upstream, _ = git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}", repo=repo)
    s.update(branch=branch, upstream=upstream if rc2 == 0 else "")
    if rc2 != 0:
        s.update(possible=False, reason=f"the branch '{branch}' tracks no remote branch", behind=0)
        return s
    if fetch:
        rc, _, err = git("fetch", "--quiet", repo=repo, timeout=60)
        if rc != 0:
            s.update(possible=False, reason=f"git fetch failed (offline?): {err[:160]}", behind=0, error=err)
            return s
    _, counts, _ = git("rev-list", "--left-right", "--count", "HEAD...@{u}", repo=repo)
    try:
        ahead, behind = (int(x) for x in counts.split())
    except ValueError:
        ahead = behind = 0
    _, dirty, _ = git("status", "--porcelain", "--untracked-files=no", repo=repo)
    _, log, _ = git("log", "--format=%h %s", "HEAD..@{u}", repo=repo)
    s.update(ahead=ahead, behind=behind, dirty=[l[3:] for l in dirty.splitlines() if l.strip()],
             commits=[tuple(l.split(" ", 1)) for l in log.splitlines() if l.strip()][:50])
    if behind:
        _, vtxt, _ = git("show", "@{u}:src/pysyzygos/version.py", repo=repo)
        m = re.search(r'__version__\s*=\s*"([^"]+)"', vtxt)
        s["remote_version"] = m.group(1) if m else ""
        _, ctxt, _ = git("show", "@{u}:CHANGELOG.md", repo=repo)
        s["changelog"] = changelog_head(ctxt)
    reason = ("up to date" if not behind else
              "local changes to tracked files: " + ", ".join(s["dirty"][:5]) if s["dirty"] else
              f"this checkout has {ahead} commit(s) the remote does not have (diverged): update by hand" if ahead else "")
    s.update(possible=bool(behind) and not reason, reason=reason)
    return s


def update(log=print, repo=None, deps=True):
    """git pull --ff-only, then the dependencies if pyproject.toml / uv.lock changed. Returns 0 on success."""
    repo = repo or repo_dir()
    s = status(fetch=True, repo=repo, release=False)
    if s["kind"] != "git" or not s.get("possible"):
        log(f"update: not possible: {s.get('reason')}")
        return 1
    _, old, _ = git("rev-parse", "HEAD", repo=repo)
    log(f"update: {s['behind']} new commit(s) from {s['upstream']}" + (f" (version {s.get('remote_version')})"
                                                                       if s.get("remote_version") else ""))
    rc, out, err = git("pull", "--ff-only", repo=repo, timeout=300)
    log(out or err)
    if rc != 0:
        log("update: git pull failed; nothing changed")
        return 1
    _, changed, _ = git("diff", "--name-only", old, "HEAD", repo=repo)
    changed = changed.splitlines()
    if deps and any(f in ("pyproject.toml", "uv.lock") for f in changed):
        uv = shutil.which("uv")
        if uv and os.path.isfile(os.path.join(repo, "uv.lock")) and os.path.isdir(os.path.join(repo, ".venv")):
            cmd = [uv, "sync"]
        else:
            cmd = [sys.executable, "-m", "pip", "install", "-e", repo]
        log("update: the dependencies changed: " + " ".join(cmd))
        p = subprocess.run(cmd, cwd=repo, capture_output=True, text=True)
        log((p.stdout or "")[-2000:] + (p.stderr or "")[-2000:])
        if p.returncode != 0:
            log("update: installing the dependencies failed (see above); the code is updated")
            return 1
    log(f"update: done ({len(changed)} file(s) changed). Restart PySyzygos to use it (header: power button, Restart).")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="pysyzygos update", description=__doc__.splitlines()[0])
    ap.add_argument("--version", action="version", version=f"PySyzygos {__version__}")
    ap.add_argument("--check", action="store_true", help="only say what is available")
    a = ap.parse_args(argv)
    if a.check:
        s = status()
        print(json.dumps({k: v for k, v in s.items() if k != "changelog"}, indent=1))
        if s.get("changelog"):
            print(s["changelog"])
        return 0
    return update(lambda *x: print(*x, flush=True))


if __name__ == "__main__":
    sys.exit(main())
