"""selfupdate.py - is a newer PySyzygos available, and update it (System tab), for each way it can be installed.

    pysyzygos update            # git: pull --ff-only (+ dependencies); PyPI: pip / uv tool / pipx upgrade
    pysyzygos update --check    # only say what is available

How it was installed (install_kind):
    git   a clone (the folder PySyzygos runs from has .git): the developer version, every commit (below).
    pypi  `pip install pysyzygos`, `uv tool install pysyzygos` or `pipx install pysyzygos`: the newest version on PyPI
          (only the x.y.0 releases go there, with their Zenodo DOI) against this one; the update runs the same tool
          (`uv tool upgrade`, `pipx upgrade`, else `<python> -m pip install -U`, or `uv pip` where the venv has no pip).
    zip   an unpacked source folder without .git (GitHub's "Download ZIP" or a release archive): the newest GitHub
          release with its link; no update in place (switch the folder to git, or install from PyPI).

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
DIST = "pysyzygos"


def repo_dir():
    """The folder PySyzygos runs from (src/pysyzygos/.. /..) if it is a git checkout, else None."""
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return root if os.path.exists(os.path.join(root, ".git")) else None


def source_dir():
    """The source folder PySyzygos runs from (src/pysyzygos/../.. holding pyproject.toml), git or not, else None
    (installed into site-packages)."""
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return root if os.path.isfile(os.path.join(root, "pyproject.toml")) else None


def _direct_url():
    """The installed distribution's direct_url.json (PEP 610: a local folder, a VCS or file URL; absent when installed
    from an index such as PyPI) as a dict; {} if absent; None if PySyzygos is not installed as a distribution."""
    from importlib import metadata
    try:
        d = metadata.distribution(DIST)
    except metadata.PackageNotFoundError:
        return None
    try:
        return json.loads(d.read_text("direct_url.json") or "{}")
    except (ValueError, OSError):
        return {}


def install_kind():
    """'git' (a clone), 'pypi' (installed from PyPI: pip, uv tool, pipx) or 'zip' (a source folder without git, or
    anything else installed from a local folder or file)."""
    if repo_dir():
        return "git"
    if source_dir():                                               # a source folder (ZIP; uv run / pip -e there)
        return "zip"
    du = _direct_url()
    if du == {}:                                                   # from an index; no local folder or file
        return "pypi"
    return "zip"


def upgrade_command(prefix=None):
    """The command that upgrades a PyPI install in the way it was made: uv tool / pipx environments by their tool,
    else pip of this Python (uv's own venvs have no pip: 'uv pip install --python <python>')."""
    prefix = os.path.normcase(os.path.abspath(prefix or sys.prefix))
    parts = prefix.replace("\\", "/").split("/")
    if "uv" in parts and "tools" in parts and shutil.which("uv"):
        return [shutil.which("uv"), "tool", "upgrade", DIST]
    if "pipx" in parts and shutil.which("pipx"):
        return [shutil.which("pipx"), "upgrade", DIST]
    import importlib.util
    if importlib.util.find_spec("pip") is None and shutil.which("uv"):
        return [shutil.which("uv"), "pip", "install", "--python", sys.executable, "-U", DIST]
    return [sys.executable, "-m", "pip", "install", "-U", DIST]


def latest_pypi(timeout=15):
    """dict(version, url, published) of the newest PySyzygos on PyPI, or None (offline, not published)."""
    from pysyzygos import net
    try:
        with net.urlopen(U.URL_PYPI_JSON, timeout=timeout) as r:
            d = json.load(r)
        v = d["info"]["version"]
        files = d.get("releases", {}).get(v) or [{}]
        return dict(version=v, url=U.URL_PYPI_PAGE + v + "/", published=str(files[0].get("upload_time", ""))[:10])
    except Exception:
        return None


def changelog_between(text, newer_than, upto):
    """changelog_head, without the entries above `upto` (patch versions on GitHub not yet on PyPI)."""
    out, keep = [], True
    for block in re.split(r"(?m)^(?=## \[)", changelog_head(text, newer_than)):
        m = re.match(r"## \[([^\]]+)\]", block)
        if m:
            keep = m.group(1).lower() != "unreleased" and version_tuple(m.group(1)) <= version_tuple(upto)
        if keep and block.strip():
            out.append(block.rstrip())
    return "\n\n".join(out)


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
    kind = "git" if repo else install_kind()
    if kind == "pypi":
        return pypi_status(s, fetch=fetch)
    rel = latest_release() if release else None
    s.update(release=rel, release_newer=bool(rel and version_tuple(rel["tag"]) > version_tuple(__version__)))
    if repo is None:
        s.update(kind="zip", possible=False,
                 reason="installed from a folder without git (a ZIP): no update in place. Download the new release, "
                        "or better switch the folder to git (README: 'Installed from the ZIP? Switch to git') or "
                        "install from PyPI (pip install pysyzygos)")
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


def pypi_status(s, fetch=True, latest=None):
    """status() for a PyPI install: the newest version there, its changelog entries, the upgrade command."""
    s.update(kind="pypi", command=" ".join(os.path.basename(c) if i == 0 else c
                                           for i, c in enumerate(upgrade_command())))
    p = latest if latest is not None else (latest_pypi() if fetch else None)
    s["pypi"] = p
    if not p:
        s.update(possible=False, behind=0, reason="no answer from PyPI (offline, or not published there yet)")
        return s
    newer = version_tuple(p["version"]) > version_tuple(__version__)
    s.update(remote_version=p["version"], possible=newer, behind=int(newer),
             reason="" if newer else f"up to date (PyPI {p['version']}; the developer version: {U.URL_GITHUB_REPO})")
    if newer and fetch:
        from pysyzygos import net
        try:
            with net.urlopen(U.URL_CHANGELOG_RAW, timeout=15) as r:
                s["changelog"] = changelog_between(r.read().decode("utf-8", "replace"), __version__, p["version"])
        except Exception:
            pass
    return s


def update_pypi(log=print, run=subprocess.run):
    """Upgrade a PyPI install with the tool that made it. Returns 0 on success."""
    s = status(fetch=True)
    if not s.get("possible"):
        log(f"update: nothing to do: {s.get('reason')}")
        return 0 if s.get("pypi") else 1
    cmd = upgrade_command()
    log(f"update: PySyzygos {__version__} -> {s['remote_version']} from PyPI: " + " ".join(cmd))
    p = run(cmd, capture_output=True, text=True)
    log((p.stdout or "")[-3000:] + (p.stderr or "")[-3000:])
    if p.returncode != 0:
        log("update: the upgrade failed (see above); the installed version is unchanged")
        return 1
    log("update: done. Restart PySyzygos to use it (header: power button, Restart).")
    return 0


def update(log=print, repo=None, deps=True):
    """git pull --ff-only, then the dependencies if pyproject.toml / uv.lock changed. Returns 0 on success."""
    repo = repo or repo_dir()
    if repo is None and install_kind() == "pypi":
        return update_pypi(log)
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
