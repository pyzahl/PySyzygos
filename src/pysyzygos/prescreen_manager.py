"""prescreen_manager.py - pre-screen manager for a build server: a terminal screen (curses, works over ssh) and a
non-interactive maintenance step for a timer, so whole-Earth pre-screens are built, published to the mirror, and
withdrawn / deleted when they are old, without typing the commands.

    pysyzygos prescreen manage --share ~/Nextcloud/world-prescreens    # once: the mirror's synced folder (saved)
    pysyzygos prescreen manage                                         # the screen
    pysyzygos prescreen manage --status                                # the same as text, and what --auto would do
    pysyzygos prescreen manage --auto [--dry-run]                      # one maintenance step (cron / systemd timer)

Timer: daily, e.g. `30 3 * * * cd ~/PySyzygos && .venv/bin/pysyzygos prescreen manage --auto >> logs/prescreen_manager.log
2>&1`. Not monthly: a finished build is published only at the next run, and coverage could run out between runs.
Only one machine builds with --auto (auto_build False on the others: they do not see each other's running builds).

The share folder is the mirror's pre-screen folder (world-prescreens/) synced to this machine (Nextcloud client):
publishing packs into it (`prescreen publish --to SHARE --synced`), withdrawing deletes there, and the sync client
uploads. Its prescreens.json is the mirror's list; copies the sync client makes on a conflict ("prescreens
(conflicted copy ...).json") are merged into it (key m, and every --auto step).

Maintenance step (plan(); the screen shows it, key a runs it):
  1. publish a finished, current whole-Earth pre-screen that is not on the mirror yet (one at a time): in slices
     (prescreen_slices.py: `prescreen split`, downloaded on demand) and/or as the packed archive (publish_mode);
  2. delete local pre-screens whose window is over, or that a newer build covers (superseded); stale partial builds;
  3. withdraw such ones from the mirror;
  4. start the next whole-Earth build (start today, `days` long) when the newest one covers fewer than `lead_days`
     days ahead and no build runs; a stopped build of the same kind is resumed instead. Not started when memory or
     disk are short (max_swap_frac, min_avail_gb, min_disk_gb): a build with full swap froze a desktop once.
The newest `keep_min` pre-screens are never deleted or withdrawn by it. Settings: HOME/prescreen_manager.json (key c).
Jobs run detached (own session): closing the screen or the ssh connection does not stop them. Logs in logs/.
POSIX only (curses, process groups).
"""
from pysyzygos.version import __version__
import datetime as dt, glob, json, os, re, signal, sqlite3, subprocess, sys, time
from pysyzygos import prescreen as PS
from pysyzygos import prescreen_slices as SL

STATE = "prescreen_manager.json"
DEFAULTS = dict(share_dir=None,                  # the mirror's synced pre-screen folder
                days=70.0, cam_limit=16.0, hmax=17.0,      # next build (hmax None: all asteroids)
                workers=max(1, (os.cpu_count() or 2) // 2), mem_frac=0.6, catalog=None,
                lead_days=21.0,                  # start the next build when coverage ahead drops below this
                keep_min=1,                      # newest pre-screens never removed automatically
                auto_build=True, auto_publish=True,
                delete_expired=True, delete_superseded=True,      # local
                withdraw_expired=True, withdraw_superseded=True,  # mirror
                max_swap_frac=0.8, min_avail_gb=4.0, min_disk_gb=10.0,
                publish_mode="both",             # "slices" (downloaded on demand), "archive" (one .tar.xz), "both"
                g_edges="13,14,15,16", h_split=17.0)      # the slices: G bands, H < / >= h_split
SETTING_HELP = dict(share_dir="mirror's synced pre-screen folder", days="window of a new build, days",
                    cam_limit="star limit G of a new build", hmax="H limit (empty: all asteroids)",
                    workers="worker processes", mem_frac="share of free memory a build may use",
                    catalog="star catalog folder (empty: config)", lead_days="build when fewer days ahead",
                    keep_min="never remove the newest N", auto_build="start builds", auto_publish="publish builds",
                    delete_expired="delete local: window over", delete_superseded="delete local: newer one covers it",
                    withdraw_expired="mirror: withdraw when over", withdraw_superseded="mirror: withdraw superseded",
                    max_swap_frac="no build above this swap use", min_avail_gb="no build below this free memory, GB",
                    min_disk_gb="no build below this free disk, GB",
                    publish_mode="slices / archive / both", g_edges="slices: G band edges",
                    h_split="slices: H < this / >= this")
NAME_RE = re.compile(r"__(\d{4}-\d\d-\d\d)_([\d.]+)d_G([\d.]+)")
CONFLICT_GLOB = "prescreens*conflict*.json"
SLICES_CONFLICT_GLOB = "prescreen_slices*conflict*.json"


# ------------------------------------------------------------------ settings and job state
def load_state():
    try:
        with open(STATE) as f:
            st = json.load(f)
    except (OSError, ValueError):
        st = {}
    st["settings"] = dict(DEFAULTS, **st.get("settings", {}))
    st.setdefault("jobs", [])
    return st


def save_state(st):
    with open(STATE + ".tmp", "w") as f:
        json.dump(st, f, indent=1)
    os.replace(STATE + ".tmp", STATE)


def today_utc():
    return dt.datetime.now(dt.timezone.utc).date()


def _date(s):
    return dt.date.fromisoformat(str(s)[:10])


# ------------------------------------------------------------------ inventory
def _item(m, **kw):
    from pysyzygos import picks as PK
    start = _date(m["start"])
    x = dict(name=m.get("name"), start=start, end=start + dt.timedelta(days=float(m["days"])), days=float(m["days"]),
             cam_limit=float(m.get("cam_limit") or 0), hmax=m.get("hmax"), built=str(m.get("built") or ""),
             region=m.get("region"), restricted=PK.restricted(PS.meta_selection(m)),
             n_events=m.get("n_events"), n_asteroids=m.get("n_asteroids"))
    x["kind"] = "global" if not x["region"] else "region"
    x.update(kw)
    return x


def local_items(folder=PS.DIR):
    out = []
    for p, m in PS.list_files(folder):
        files = [p] + ([PS._meta_path(p), PS._idx_path(p)] if PS.is_global(p) else [])
        x = _item(m, path=p, name=os.path.basename(p).rsplit(".global.npy", 1)[0].rsplit(".db", 1)[0],
                  bytes=sum(os.path.getsize(f) for f in files if os.path.exists(f)),
                  indexed=PS.has_index(p) if PS.is_global(p) else True)
        out.append(x)
    return out


def partial_items(folder=PS.DIR):
    out = []
    for p in sorted(glob.glob(os.path.join(folder, "*.partial"))):
        x = dict(path=p, name=os.path.basename(p)[:-len(".partial")], bytes=os.path.getsize(p),
                 mtime=os.path.getmtime(p), settings=None, done=None)
        try:
            con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
            try:
                row = con.execute("SELECT value FROM meta WHERE key = 'settings'").fetchone()
                x["settings"] = json.loads(row[0]) if row else None
                x["done"] = con.execute("SELECT COUNT(*) FROM done").fetchone()[0]
            finally:
                con.close()
        except sqlite3.Error:
            pass
        s = x["settings"]
        if s and s.get("start"):
            x.update(start=_date(s["start"]), days=float(s["days"]), cam_limit=float(s["cam_limit"]),
                     kind="global" if not s.get("region") else "region", hmax=s.get("hmax"),
                     restricted=bool(s.get("selection")))
            x["end"] = x["start"] + dt.timedelta(days=x["days"])
        out.append(x)
    return out


def share_items(share):
    """(entries with 'state' ok / incomplete / missing, orphan files, conflict copies) of the share folder."""
    if not share or not os.path.isdir(share):
        return [], [], []
    man = PS.load_manifest(os.path.join(share, PS.MANIFEST)) or {}
    items = []
    for e in man.get("prescreens", []):
        a = os.path.join(share, e["archive"])
        st = ("missing" if not os.path.isfile(a) else
              "ok" if os.path.getsize(a) == e.get("archive_bytes") and os.path.isfile(a + ".sha256") else "incomplete")
        try:
            items.append(_item(e, name=e["name"], archive=e["archive"], bytes=e.get("archive_bytes"), state=st,
                               published=str(e.get("published") or "")))
        except (KeyError, ValueError):
            continue
    for x in items:
        x["sliced"] = None
    by = {x["name"]: x for x in items}
    sman = SL.load(os.path.join(share, SL.MANIFEST)) or {}
    for e in sman.get("prescreens", []):                     # the same build in slices: one row with both forms
        st = SL.folder_state(share, e)
        x = by.get(e["name"])
        if x is not None and x["built"] == str(e.get("built") or ""):
            x["sliced"] = st
            continue
        try:
            items.append(_item(e, name=e["name"], archive=None, bytes=e.get("total_bytes"), state=st, sliced=st,
                               published=str(e.get("published") or "")))
        except (KeyError, ValueError):
            continue
    listed = {e["archive"] for e in man.get("prescreens", [])}
    folders = {e["folder"] for e in sman.get("prescreens", [])}
    orphans = sorted(f for f in os.listdir(share)
                     if (f.endswith((".tar.xz", ".part")) and f not in listed and f[:-len(".part")] not in listed)
                     or (f.endswith(".tar.xz.sha256") and f[:-len(".sha256")] not in listed)
                     or (f.endswith((".slices", ".slices.part")) and f not in folders))
    conflicts = sorted(glob.glob(os.path.join(share, CONFLICT_GLOB)) + glob.glob(os.path.join(share, SLICES_CONFLICT_GLOB)))
    return items, orphans, conflicts


def _covers(y, x, today):
    """y (a newer build) makes x superfluous: same kind of whole-Earth pre-screen, no fainter-limited, built later,
    and its window holds what is left of x's."""
    return (x.get("kind") == y.get("kind") == "global" and not x.get("restricted") and not y.get("restricted")
            and y["end"] > today and y["built"] > x["built"] and y["cam_limit"] >= x["cam_limit"] - 1e-9
            and (y["hmax"] is None or (x["hmax"] is not None and float(y["hmax"]) >= float(x["hmax"])))
            and y["start"] <= max(today, x["start"]) and y["end"] >= x["end"])


def mark(items, today, others=()):
    """Sets expired (window over) and superseded (covered by another of items or others) on each item."""
    for x in items:
        x["expired"] = x["end"] <= today
        x["superseded"] = not x["expired"] and any(_covers(y, x, today) for y in list(items) + list(others)
                                                   if y is not x and y.get("state", "ok") == "ok")
    return items


def protected(items, n):
    """Names of the newest n items (by start, then build time): never removed automatically."""
    return {x["name"] for x in sorted(items, key=lambda x: (x["start"], x["built"]), reverse=True)[:max(0, int(n))]}


# ------------------------------------------------------------------ jobs (detached processes)
def _proc_argv(pid):
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            return [a.decode("utf-8", "replace") for a in f.read().split(b"\0") if a]
    except OSError:
        return None


def alive(pid):
    """The process runs (not a zombie) and is still a PySyzygos process (no reused pid)."""
    try:
        with open(f"/proc/{int(pid)}/stat") as f:
            if f.read().rsplit(")", 1)[1].split()[0] == "Z":
                return False
    except (OSError, IndexError):
        if not os.path.isdir("/proc"):                   # no /proc (macOS): a signal 0 test
            try:
                os.kill(int(pid), 0)
                return True
            except (ProcessLookupError, PermissionError, ValueError):
                return False
        return False
    argv = _proc_argv(pid) or []
    return any("pysyzygos" in a for a in argv)


def reap():
    """Collect our finished children (else they stay zombies while the screen is open)."""
    try:
        while os.waitpid(-1, os.WNOHANG)[0]:
            pass
    except (ChildProcessError, OSError):
        pass


def _arg(argv, key):
    for i, a in enumerate(argv):
        if a == key and i + 1 < len(argv):
            return argv[i + 1]
        if a.startswith(key + "="):
            return a[len(key) + 1:]
    return None


def out_of(argv):
    """The output file of a `prescreen build|publish|index` command line."""
    i = argv.index("prescreen")
    sub, rest = argv[i + 1], argv[i + 2:]
    if sub in ("publish", "index", "split"):
        return next((a for a in rest if not a.startswith("-")), None)
    o = _arg(rest, "-o") or _arg(rest, "--output")
    if o or "--global" not in rest:
        return o
    s, d, g = _arg(rest, "--start"), _arg(rest, "--days") or "30", _arg(rest, "--cam-limit") or "16"
    return os.path.join(PS.DIR, f"{_arg(rest, '--name') or 'global'}__{s}_{float(d):g}d_G{float(g):g}.global.npy")


def scan_processes(home=None):
    """Running `pysyzygos prescreen build|publish|index` processes of this data folder (also started by hand or by
    the GUI): [{pid, kind, argv, out}]."""
    home = os.path.realpath(home or os.getcwd())
    out = []
    if not os.path.isdir("/proc"):
        return out
    for d in os.listdir("/proc"):
        if not d.isdigit() or int(d) == os.getpid():
            continue
        argv = _proc_argv(d)
        if not argv or os.path.basename(argv[0]) in ("sh", "bash", "dash", "zsh") or "prescreen" not in argv:
            continue
        i = argv.index("prescreen")
        if i + 1 >= len(argv) or argv[i + 1] not in ("build", "publish", "index", "split") \
                or not any("pysyzygos" in a for a in argv[:i]):
            continue
        try:
            if os.path.realpath(os.readlink(f"/proc/{d}/cwd")) != home:
                continue
        except OSError:
            continue
        try:
            o = out_of(argv)
        except (ValueError, IndexError):
            o = None
        out.append(dict(pid=int(d), kind=argv[i + 1], argv=argv[i:], out=o))
    return out


def log_tail(path, size=64000):
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - size))
            text = f.read().decode("utf-8", "replace")
    except (OSError, TypeError):
        return []
    return [ln.rsplit("\r", 1)[-1] for ln in text.splitlines() if ln.strip()]


PROGRESS_RE = re.compile(r"(\d+)/(\d+) asteroids \(([\d.]+)%\).*?ETA ([\d:]+)"
                         r"(?:.*?mem available ([\d.]+ GB))?(?:.*?swap used ([\d.]+ GB))?")


def progress_text(lines):
    for ln in reversed(lines):
        m = PROGRESS_RE.search(ln)
        if m:
            t = f"{m.group(3)} % ({m.group(1)}/{m.group(2)}), ETA {m.group(4)}"
            return t + (f", mem {m.group(5)}" if m.group(5) else "") + (f", swap {m.group(6)}" if m.group(6) else "")
    return lines[-1][:120] if lines else ""


def exit_code(lines):
    for ln in reversed(lines[-5:]):
        m = re.match(r"--- exit code (-?\d+)", ln)
        if m:
            return int(m.group(1))
    return None


def jobs(st, home=None):
    """Our launched jobs (alive or finished, with their logs) + running ones started elsewhere."""
    reap()
    out, seen = [], set()
    for j in st["jobs"]:
        j = dict(j, alive=alive(j["pid"]))
        lines = log_tail(j.get("log"))
        j["progress"] = progress_text(lines) if j["alive"] else ""
        j["exit"] = None if j["alive"] else exit_code(lines)
        out.append(j)
        seen.add(j["pid"])
    for p in scan_processes(home):
        if p["pid"] not in seen and not any(alive(j["pid"]) and j.get("out") == p["out"] for j in out if j["alive"]):
            out.append(dict(p, alive=True, log=None, started=None, progress="(started elsewhere)", exit=None))
    return out


def launch(st, kind, args, out):
    """Start `pysyzygos prescreen <args>` detached (own session), output to logs/<stamp>_prescreen_<kind>.log, with
    a last line '--- exit code N'. Returns the job."""
    os.makedirs("logs", exist_ok=True)
    log = os.path.join("logs", time.strftime("%Y%m%d-%H%M%S") + f"_prescreen_{kind}.log")
    cmd = [sys.executable, "-u", "-m", "pysyzygos", "prescreen"] + [str(a) for a in args]
    src = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = dict(os.environ, PYSYZYGOS_HOME=os.getcwd(), PYTHONUTF8="1", PYTHONIOENCODING="utf-8",
               PYTHONPATH=os.pathsep.join([src] + [p for p in os.environ.get("PYTHONPATH", "").split(os.pathsep) if p]))
    with open(log, "a", encoding="utf-8") as fh:
        fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  PySyzygos {__version__}  (prescreen manager)\n"
                 f"$ pysyzygos prescreen {' '.join(cmd[5:])}\n")
        fh.flush()
        p = subprocess.Popen(["/bin/sh", "-c", '"$@"; echo "--- exit code $?"', "sh"] + cmd, stdout=fh,
                             stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env=env, start_new_session=True)
    j = dict(pid=p.pid, kind=kind, argv=["prescreen"] + [str(a) for a in args], out=out, log=log,
             started=time.strftime("%Y-%m-%d %H:%M:%S"))
    st["jobs"] = (st["jobs"] + [j])[-30:]                       # the last 30 (finished ones show their exit code)
    save_state(st)
    return j


def stop(job):
    """SIGTERM to the job's process group (a build saves its progress and ends its workers)."""
    try:
        os.killpg(int(job["pid"]), signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        try:
            os.kill(int(job["pid"]), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass


# ------------------------------------------------------------------ commands of the actions
def build_args(cfg, start):
    out = os.path.join(PS.DIR, f"global__{start}_{float(cfg['days']):g}d_G{float(cfg['cam_limit']):g}.global.npy")
    a = ["build", "--start", str(start), "--days", f"{float(cfg['days']):g}", "--global",
         "--cam-limit", f"{float(cfg['cam_limit']):g}", "--workers", str(int(cfg["workers"])),
         "--mem-frac", f"{float(cfg['mem_frac']):g}", "-o", out]
    a += ["--all"] if cfg.get("hmax") in (None, "") else ["--hmax", f"{float(cfg['hmax']):g}"]
    return a + (["--catalog", cfg["catalog"]] if cfg.get("catalog") else []), out


def resume_args(cfg, part):
    """The build command that resumes a partial build (its stored settings, so open_partial accepts them), or None
    for one with an asteroid selection (resume that by hand)."""
    s = part.get("settings") or {}
    if not s.get("start") or s.get("selection"):
        return None, None
    out = part["path"][:-len(".partial")]
    a = ["build", "--start", s["start"], "--days", repr(float(s["days"])), "--cam-limit", repr(float(s["cam_limit"])),
         "--min-drop", repr(float(s["min_drop"])), "--reach", repr(float(s["reach_km"])),
         "--max-sun-alt", repr(float(s["max_sun_alt"])), "--min-alt", repr(float(s["min_alt"])),
         "--workers", str(int(cfg["workers"])), "--mem-frac", f"{float(cfg['mem_frac']):g}", "-o", out,
         "--name", os.path.basename(out).split("__")[0]]
    a += ["--all"] if s.get("hmax") is None else ["--hmax", repr(float(s["hmax"]))]
    if s.get("region"):
        r = s["region"]
        a.append("--region=" + ",".join(repr(float(r[k])) for k in ("lat_min", "lat_max", "lon_min", "lon_max")))
        if s.get("reach_sigma"):
            a += ["--reach-sigma", str(int(s["reach_sigma"]))]
    else:
        a.append("--global")
    if s.get("catalog"):
        a += ["--catalog", s["catalog"]]
    return a, out


def merge_share(share, extra=(), log=print):
    """The share folder's prescreens.json merged with the sync client's conflict copies (and extra lists: files or
    URLs), entries without their archive there left out; the conflict copies are deleted afterwards."""
    mp = os.path.join(share, PS.MANIFEST)
    conflicts = sorted(glob.glob(os.path.join(share, CONFLICT_GLOB)))
    lists = [PS.load_manifest(mp)] + [PS.load_manifest(c) for c in conflicts] + [PS.load_manifest(x) for x in extra]
    man = PS.merge_manifests(lists)
    man = PS.on_mirror(man, PS.synced_remote(share)[0], log=log)
    PS.write_manifest(PS.merge_manifests([man]), mp)
    for c in conflicts:
        os.remove(c)
        log(f"   merged and deleted {os.path.basename(c)}")
    log(f"{mp}: {len(man['prescreens'])} pre-screen(s)")
    sp = os.path.join(share, SL.MANIFEST)                          # the sliced list, the same way
    sconf = sorted(glob.glob(os.path.join(share, SLICES_CONFLICT_GLOB)))
    if sconf or os.path.exists(sp):
        sman = SL.merge([SL.load(sp)] + [SL.load(c) for c in sconf])
        sman = dict(sman, prescreens=[e for e in sman["prescreens"] if SL.folder_ok(share, e)])
        SL.write(sman, sp)
        for c in sconf:
            os.remove(c)
            log(f"   merged and deleted {os.path.basename(c)}")
        log(f"{sp}: {len(sman['prescreens'])} sliced pre-screen(s)")
    return man


def mem_check(cfg):
    """(ok, text) for starting a build: free memory, swap, disk."""
    m = PS._meminfo()
    disk = None
    try:
        import shutil
        disk = shutil.disk_usage(PS.DIR if os.path.isdir(PS.DIR) else ".").free
    except OSError:
        pass
    if disk is not None and disk < float(cfg["min_disk_gb"]) * 1e9:
        return False, f"only {disk / 1e9:.1f} GB free disk (< {float(cfg['min_disk_gb']):g} GB)"
    if not m:
        return True, "memory unknown"
    avail, st = m.get("MemAvailable", 0), m.get("SwapTotal", 0)
    su = st - m.get("SwapFree", 0)
    text = f"{avail / 1e9:.1f} GB free memory, swap {su / 1e9:.1f} of {st / 1e9:.1f} GB"
    if avail < float(cfg["min_avail_gb"]) * 1e9:
        return False, f"only {avail / 1e9:.1f} GB memory available (< {float(cfg['min_avail_gb']):g} GB)"
    if st and su / st > float(cfg["max_swap_frac"]):
        return False, f"swap {su / st:.0%} full (> {float(cfg['max_swap_frac']):.0%})"
    return True, text


# ------------------------------------------------------------------ the maintenance plan
def window_of(name):
    """(start, end) dates from a pre-screen name 'x__YYYY-MM-DD_70d_G16...', else None."""
    m = NAME_RE.search(str(name or ""))
    if not m:
        return None
    s = _date(m.group(1))
    return s, s + dt.timedelta(days=float(m.group(2)))


def inventory(st, today=None):
    today = today or today_utc()
    cfg = st["settings"]
    share = cfg.get("share_dir")
    mirror, orphans, conflicts = share_items(share)
    mark(mirror, today)
    local = mark(local_items(), today, others=mirror)
    names = {x["name"]: x for x in mirror}
    mode = cfg.get("publish_mode", "both")
    for x in local:
        e = names.get(x["name"])
        same = bool(e and e["built"] == x["built"])
        x["on_archive"] = same and bool(e.get("archive")) and e["state"] != "missing"
        x["on_slices"] = same and e.get("sliced") not in (None, "missing")
        x["published"] = ((x["on_archive"] or mode == "slices") and (x["on_slices"] or mode == "archive"))
    return dict(today=today, local=local, partials=partial_items(), mirror=mirror, orphans=orphans,
                conflicts=conflicts, jobs=jobs(st), share=share, settings=cfg)


def plan(inv, mem=(True, "")):
    """[(action, target, reason)] of one maintenance step; actions publish, delete, delete_partial, withdraw, merge,
    build, resume, wait (nothing done: why)."""
    cfg, today, acts = inv["settings"], inv["today"], []
    share = inv["share"] if inv["share"] and os.path.isdir(inv["share"]) else None
    run = [j for j in inv["jobs"] if j["alive"]]
    busy = {os.path.normpath(j["out"]) for j in run if j.get("out")}
    is_busy = lambda p: os.path.normpath(p) in busy or os.path.normpath(p[:-len(".partial")]) in busy
    if share and inv["conflicts"]:
        acts.append(("merge", share, f"{len(inv['conflicts'])} conflict copy(ies) of {PS.MANIFEST}"))
    gl = [x for x in inv["local"] if x["kind"] == "global"]
    if share and cfg["auto_publish"] and not any(j["kind"] in ("publish", "split") for j in run):
        todo = [x for x in gl if not x["published"] and not x["expired"] and not x["superseded"] and x["indexed"]
                and not x["restricted"] and not is_busy(x["path"])]
        mode = cfg.get("publish_mode", "both")
        for x in sorted(todo, key=lambda x: x["start"])[:1]:
            if mode in ("slices", "both") and not x.get("on_slices"):
                acts.append(("split", x["path"], "not on the mirror in slices yet"))
            elif mode in ("archive", "both") and not x.get("on_archive"):
                acts.append(("publish", x["path"], "not in the mirror's archive list yet"))
    keep = protected(inv["local"], cfg["keep_min"])
    for x in inv["local"]:
        if x["name"] in keep or is_busy(x["path"]):
            continue
        if x["expired"] and cfg["delete_expired"]:
            acts.append(("delete", x["path"], f"window ended {x['end']}"))
        elif x["superseded"] and cfg["delete_superseded"]:
            acts.append(("delete", x["path"], "a newer build covers its window"))
    for p in inv["partials"]:
        if not is_busy(p["path"]) and p.get("end") and p["end"] <= today + dt.timedelta(days=float(cfg["lead_days"])) \
                and cfg["delete_expired"]:
            acts.append(("delete_partial", p["path"], f"stopped build, window ends {p['end']}"))
    if share:
        mkeep = protected([e for e in inv["mirror"] if e["state"] == "ok"], cfg["keep_min"])
        for e in inv["mirror"]:
            if e["name"] in mkeep:
                continue
            if e["expired"] and cfg["withdraw_expired"]:
                acts.append(("withdraw", e["name"], f"window ended {e['end']}"))
            elif e["superseded"] and cfg["withdraw_superseded"]:
                acts.append(("withdraw", e["name"], "a newer build covers its window"))
            elif e["state"] == "missing":
                acts.append(("withdraw", e["name"], "listed, archive not in the folder"))
    if cfg["auto_build"]:
        acts += _build_step(inv, cfg, today, run, is_busy, mem)
    return acts


def _fits(x, cfg):
    return (x.get("kind") == "global" and not x.get("restricted")
            and float(x.get("cam_limit") or 0) >= float(cfg["cam_limit"]) - 1e-9)


def _build_step(inv, cfg, today, run, is_busy, mem):
    if any(j["kind"] == "build" for j in run):
        b = next(j for j in run if j["kind"] == "build")
        return [("wait", None, f"build running (pid {b['pid']}{': ' + b['progress'] if b.get('progress') else ''})")]
    ends = [x["end"] for x in inv["local"] + [e for e in inv["mirror"] if e["state"] == "ok"]
            if _fits(x, cfg) and not x["expired"]]
    ahead = (max(ends) - today).days if ends else None
    lead = float(cfg["lead_days"])
    if ahead is not None and ahead >= lead:
        return [("wait", None, f"covered {ahead} days ahead (until {max(ends)}; next build below {lead:g})")]
    why = ("no current whole-Earth pre-screen" if ahead is None else f"only {ahead} days ahead covered (< {lead:g})")
    ok, text = mem
    if not ok:
        return [("wait", None, f"{why}, but not starting a build: {text}")]
    parts = [p for p in inv["partials"] if _fits(p, cfg) and p.get("end") and not is_busy(p["path"])
             and (p["end"] - today).days > lead and resume_args(cfg, p)[0]]
    if parts:
        p = max(parts, key=lambda p: (p["start"], p["done"] or 0))
        return [("resume", p["path"], f"{why}; resume the stopped build ({p['done']} asteroids done)")]
    return [("build", str(today), f"{why}: {today} + {float(cfg['days']):g} d, G {float(cfg['cam_limit']):g}")]


def execute(st, act, log=print):
    """Do one planned action; returns the job for the ones that run in the background."""
    kind, target, why = act
    cfg = st["settings"]
    if kind == "publish":
        return launch(st, "publish", ["publish", target, "--to", cfg["share_dir"], "--synced"], target)
    if kind == "split":
        return launch(st, "split", ["split", target, "--to", cfg["share_dir"], "--synced", "--g-edges",
                                    str(cfg.get("g_edges") or "13,14,15,16"), "--h-split",
                                    f"{float(cfg.get('h_split') or 17):g}"], target)
    if kind == "delete":
        PS.remove(target)
        log(f"deleted {target} ({why})")
    elif kind == "delete_partial":
        os.remove(target)
        log(f"deleted {target} ({why})")
    elif kind == "withdraw":
        PS.withdraw(target, cfg["share_dir"], log=log)
    elif kind == "merge":
        merge_share(target, log=log)
    elif kind == "build":
        args, out = build_args(cfg, target)
        return launch(st, "build", args, out)
    elif kind == "resume":
        part = next(p for p in partial_items() if p["path"] == target)
        args, out = resume_args(cfg, part)
        return launch(st, "build", args, out)
    elif kind == "index":
        return launch(st, "index", ["index", target, "--workers", str(int(cfg["workers"]))], target)
    return None


def auto(st, dry_run=False, log=print):
    """One maintenance step: the plan, done (or only printed). Returns the plan."""
    inv = inventory(st)
    acts = plan(inv, mem_check(st["settings"]))
    for a in acts:
        log(f"{'(dry run) ' if dry_run and a[0] != 'wait' else ''}{a[0]:15s} {a[1] or '':60s} {a[2]}")
        if not dry_run and a[0] != "wait":
            try:
                j = execute(st, a, log)
                if j:
                    log(f"   started pid {j['pid']}, log {j['log']}")
            except Exception as e:                                 # one failed action must not stop the others
                log(f"   FAILED: {type(e).__name__}: {e}")
    if not acts:
        log("nothing to do")
    return acts


# ------------------------------------------------------------------ text views
def _gb(b):
    return "-" if b is None else f"{b / 1e9:.2f} GB" if b >= 1e8 else f"{b / 1e6:.0f} MB"


def _flags(x):
    f = []
    if x.get("expired"):
        f.append("expired")
    elif x.get("superseded"):
        f.append("superseded")
    if "path" in x and (x.get("on_archive") or x.get("on_slices")):
        f.append("on mirror (" + "+".join(k for k, v in (("archive", x.get("on_archive")), ("slices", x.get("on_slices")))
                                          if v) + ")")
    if x.get("what") == "mirror" or "archive" in x:
        forms = [k for k, v in (("archive", x.get("archive")), ("slices", x.get("sliced") not in (None, "missing")))
                 if v]
        if forms and "path" not in x:
            f.append("+".join(forms) + ("" if x.get("sliced") in (None, "ok", "missing") else f" (slices {x['sliced']})"))
    if x.get("kind") == "global" and not x.get("indexed", True):
        f.append("no index")
    if x.get("state") and x["state"] != "ok":
        f.append(x["state"])
    if x.get("restricted"):
        f.append("selection")
    return ", ".join(f)


def rows(inv):
    """[(section, label, data)] of the screen and --status; data = the item the keys act on (None: a heading)."""
    out = [("local", f"LOCAL  {os.path.abspath(PS.DIR)}", None)]
    for x in sorted(inv["local"], key=lambda x: x["start"]):
        out.append(("local", f"  {x['name'][:46]:46s} {x['start']}..{x['end']}  G{x['cam_limit']:g}  "
                    f"{_gb(x['bytes']):>9s}  {_flags(x)}", x))
    if not inv["local"]:
        out.append(("local", "  (none)", None))
    out.append(("jobs", "JOBS AND STOPPED BUILDS", None))
    n0 = len(out)
    js = [j for j in inv["jobs"] if j["alive"]] + [j for j in inv["jobs"] if not j["alive"]][-6:]
    for j in js:
        state = "running" if j["alive"] else ("done" if j["exit"] == 0 else f"exit {j['exit']}" if j["exit"] is not None
                                              else "ended")
        out.append(("jobs", f"  {j['kind']:8s} pid {j['pid']:<8d} {state:9s} {os.path.basename(str(j.get('out') or ''))[:40]:40s} "
                    f"{j.get('progress') or (j.get('started') or '')}", dict(j, what="job")))
    for p in inv["partials"]:
        busy = any(j["alive"] and j.get("out") and os.path.normpath(j["out"]) == os.path.normpath(p["path"][:-8])
                   for j in inv["jobs"])
        out.append(("jobs", f"  partial  {p['name'][:56]:56s} {p['done'] if p['done'] is not None else '?'} asteroids done"
                    f"{', running' if busy else ', stopped'}  {_gb(p['bytes'])}", dict(p, what="partial")))
    if len(out) == n0:
        out.append(("jobs", "  (none)", None))
    sh = inv["share"]
    out.append(("mirror", f"MIRROR  {sh or '(no share folder set: key c)'}"
                + ("  NOT FOUND" if sh and not os.path.isdir(sh) else ""), None))
    for e in sorted(inv["mirror"], key=lambda x: x["start"]):
        out.append(("mirror", f"  {e['name'][:46]:46s} {e['start']}..{e['end']}  G{e['cam_limit']:g}  "
                    f"{_gb(e['bytes']):>9s}  {_flags(e)}  published {e['published'][:10]}", dict(e, what="mirror")))
    for f in inv["orphans"]:
        out.append(("mirror", f"  ? {f}  (not in the list)", dict(name=f, what="orphan")))
    for c in inv["conflicts"]:
        out.append(("mirror", f"  ! {os.path.basename(c)}  (sync conflict copy: key m merges)", None))
    if sh and os.path.isdir(sh) and not (inv["mirror"] or inv["orphans"]):
        out.append(("mirror", "  (empty)", None))
    return out


def status_text(st):
    inv = inventory(st)
    mem = mem_check(st["settings"])
    lines = [f"PySyzygos {__version__} pre-screen manager, {os.getcwd()}, today {inv['today']} (UTC); {mem[1]}", ""]
    lines += [r[1] for r in rows(inv)]
    lines += ["", "PLAN (--auto would do):"] + [f"  {a:15s} {t or '':50s} {w}" for a, t, w in plan(inv, mem)]
    return "\n".join(lines)


# ------------------------------------------------------------------ the screen (curses)
HELP = ("up/down move  n new build  r resume  s stop  p publish (slices/archive)  d delete/withdraw  i index  m merge lists  "
        "a run plan  c settings  l log  q quit")


def tui(st):
    import curses

    def main(scr):
        curses.curs_set(0)
        curses.use_default_colors()
        for i, c in enumerate((curses.COLOR_GREEN, curses.COLOR_YELLOW, curses.COLOR_RED, curses.COLOR_CYAN), 1):
            curses.init_pair(i, c, -1)
        scr.timeout(5000)
        sel, top, msg, cache = 0, 0, "", None
        while True:
            if cache is None or time.time() - cache[0] > 5:
                inv = inventory(st)
                mem = mem_check(st["settings"])
                cache = (time.time(), inv, mem, rows(inv), plan(inv, mem))
            _, inv, mem, rs, acts = cache
            pickable = [i for i, r in enumerate(rs) if r[2] is not None]
            if pickable:
                sel = min(max(sel, 0), len(pickable) - 1)
            h, w = scr.getmaxyx()
            scr.erase()
            put = lambda y, x, s, a=0: (scr.addnstr(y, x, s, max(0, w - x - 1), a) if 0 <= y < h else None)
            put(0, 0, f"PySyzygos {__version__} pre-screens  {inv['today']} UTC  {mem[1]}", curses.A_BOLD)
            body = max(1, h - 4 - min(len(acts) + 1, max(3, h // 3)))
            cur = pickable[sel] if pickable else -1
            if cur >= 0:
                top = min(max(top, cur - body + 1), cur)
            for k, (sec, label, data) in enumerate(rs[top:top + body]):
                i = k + top
                attr = curses.A_BOLD if data is None else 0
                if data is not None:
                    fl = label
                    attr |= (curses.color_pair(3) if "expired" in fl or "missing" in fl or "exit " in fl else
                             curses.color_pair(2) if "superseded" in fl or "stopped" in fl or "incomplete" in fl else
                             curses.color_pair(1) if "running" in fl or "on mirror" in fl else 0)
                if i == cur:
                    attr |= curses.A_REVERSE
                put(1 + k, 0, label, attr)
            y = 1 + body
            put(y, 0, "PLAN (key a runs it)", curses.A_BOLD | curses.color_pair(4))
            for a, t, why in acts[:h - y - 3]:
                y += 1
                put(y, 2, f"{a:14s} {os.path.basename(str(t or '')):44s} {why}")
            put(h - 2, 0, msg, curses.color_pair(2))
            put(h - 1, 0, HELP, curses.A_DIM)
            scr.refresh()
            ch = scr.getch()
            if ch == -1:
                continue
            msg = ""
            item = rs[pickable[sel]][2] if pickable else None
            key = chr(ch) if 0 < ch < 256 else ""
            try:
                if ch in (curses.KEY_UP, ord("k")):
                    sel -= 1
                elif ch in (curses.KEY_DOWN, ord("j")):
                    sel += 1
                elif ch == curses.KEY_PPAGE:
                    sel -= 10
                elif ch == curses.KEY_NPAGE:
                    sel += 10
                elif key == "q":
                    return
                elif key == "a":
                    todo = [x for x in acts if x[0] != "wait"]
                    if not todo:
                        msg = "nothing to do: " + "; ".join(x[2] for x in acts)
                    elif confirm(scr, f"run {len(todo)} action(s): " + ", ".join(f"{x[0]} {os.path.basename(str(x[1]))}"
                                                                              for x in todo) + "?"):
                        out = []
                        for x in todo:
                            j = execute(st, x, log=out.append)
                            out.append(f"{x[0]} started (pid {j['pid']})" if j else "")
                        msg = "; ".join(o for o in out if o)[-300:]
                elif key == "n":
                    msg = new_build(scr, st)
                elif key == "c":
                    msg = edit_settings(scr, st)
                elif key == "m":
                    sh = st["settings"].get("share_dir")
                    if not sh or not os.path.isdir(sh):
                        msg = "no share folder (key c)"
                    else:
                        extra = ask(scr, "also merge another list (file or URL, empty: none)", "")
                        out = []
                        merge_share(sh, [extra] if extra else [], log=out.append)
                        msg = out[-1] if out else ""
                elif item is None:
                    msg = "nothing selected"
                elif key == "l":
                    view_log(scr, item.get("log"))
                elif key == "s":
                    if item.get("what") == "job" and item["alive"] and confirm(scr, f"stop pid {item['pid']} "
                                                                                    f"({item['kind']})? A build resumes later."):
                        stop(item)
                        msg = f"stopped {item['pid']}"
                elif key == "r":
                    if item.get("what") != "partial":
                        msg = "select a stopped build (partial)"
                    else:
                        args, out = resume_args(st["settings"], item)
                        ok, text = mem_check(st["settings"])
                        if not args:
                            msg = "this partial has an asteroid selection: resume it by hand"
                        elif (ok or confirm(scr, f"{text}. Start anyway?")) and confirm(scr, f"resume {item['name']}?"):
                            j = launch(st, "build", args, out)
                            msg = f"resumed, pid {j['pid']}, log {j['log']}"
                elif key == "p":
                    sh = st["settings"].get("share_dir")
                    if item.get("kind") != "global" or "path" not in item or item.get("what"):
                        msg = "select a local whole-Earth pre-screen"
                    elif not sh or not os.path.isdir(sh):
                        msg = "no share folder (key c)"
                    else:
                        mode = st["settings"].get("publish_mode", "both")
                        dflt = "s" if mode in ("slices", "both") and not item.get("on_slices") else "a"
                        how = ask(scr, f"publish {item['name']} to {sh} as (s)lices, (a)rchive, or (n)o", dflt).lower()
                        if how.startswith(("s", "a")):
                            kind = "split" if how.startswith("s") else "publish"
                            j = execute(st, (kind, item["path"], "by hand"))
                            msg = f"{'splitting' if kind == 'split' else 'packing'}, pid {j['pid']}, log {j['log']}"
                elif key == "i":
                    if item.get("kind") == "global" and not item.get("what"):
                        j = execute(st, ("index", item["path"], "by hand"))
                        msg = f"indexing, pid {j['pid']}"
                elif key == "d":
                    msg = delete(scr, st, item, inv)
                if key and key in "acmnrspid":
                    cache = None
            except Exception as e:                                         # keep the screen alive
                msg = f"{type(e).__name__}: {e}"
                cache = None

    curses.wrapper(main)


def delete(scr, st, item, inv):
    what = item.get("what")
    if what == "job":
        return "a job: key s stops it"
    if what == "partial":
        if confirm(scr, f"delete the stopped build {item['name']} ({item['done']} asteroids done)?"):
            os.remove(item["path"])
            return f"deleted {item['path']}"
    elif what == "mirror":
        if confirm(scr, f"withdraw {item['name']} from the mirror (delete its archive in the synced folder)?"):
            PS.withdraw(item["name"], inv["share"], log=lambda *a: None)
            return f"withdrawn {item['name']}"
    elif what == "orphan":
        if confirm(scr, f"delete {item['name']} in the share folder?"):
            os.remove(os.path.join(inv["share"], item["name"]))
            return f"deleted {item['name']}"
    elif "path" in item:
        busy = any(j["alive"] and j.get("out") and os.path.normpath(j["out"]) == os.path.normpath(item["path"])
                   for j in inv["jobs"])
        if busy:
            return "a job is using it"
        if confirm(scr, f"delete {item['path']} ({_gb(item['bytes'])}"
                        f"{', NOT on the mirror' if item['kind'] == 'global' and not item.get('published') else ''})?"):
            PS.remove(item["path"])
            return f"deleted {item['path']}"
    return ""


def ask(scr, label, default):
    import curses
    h, w = scr.getmaxyx()
    scr.timeout(-1)
    curses.curs_set(1)
    try:
        scr.move(h - 2, 0)
        scr.clrtoeol()
        prompt = f"{label} [{default}]: "
        scr.addnstr(h - 2, 0, prompt, w - 1, curses.A_BOLD)
        curses.echo()
        s = scr.getstr(h - 2, min(len(prompt), w - 2), 200).decode("utf-8", "replace").strip()
    finally:
        curses.noecho()
        curses.curs_set(0)
        scr.timeout(5000)
    return s if s else str(default)


def confirm(scr, text):
    return ask(scr, text + " (y/N)", "n").lower().startswith("y")


def _parse(key, s):
    d = DEFAULTS[key]
    if s in ("", "none", "None", "-") and key in ("hmax", "catalog", "share_dir"):
        return None
    if isinstance(d, bool):
        return s.lower() in ("1", "y", "yes", "true", "on")
    if isinstance(d, int) and key in ("keep_min", "workers"):
        return int(s)
    if isinstance(d, float) or key == "hmax":
        return float(s)
    return os.path.expanduser(s) if key == "share_dir" else s


def edit_settings(scr, st):
    import curses
    keys = list(DEFAULTS)
    i = 0
    scr.timeout(-1)
    try:
        while True:
            h, w = scr.getmaxyx()
            scr.erase()
            scr.addnstr(0, 0, f"Settings ({STATE}): Enter edits, q back", w - 1, curses.A_BOLD)
            for k, key in enumerate(keys[:h - 3]):
                v = st["settings"].get(key)
                scr.addnstr(2 + k, 0, f"  {key:20s} {str(v):40s} {SETTING_HELP.get(key, '')}", w - 1,
                            curses.A_REVERSE if k == i else 0)
            scr.refresh()
            ch = scr.getch()
            if ch in (ord("q"), 27):
                return "settings saved"
            if ch in (curses.KEY_UP, ord("k")):
                i = max(0, i - 1)
            elif ch in (curses.KEY_DOWN, ord("j")):
                i = min(len(keys) - 1, i + 1)
            elif ch in (10, 13, curses.KEY_ENTER):
                key = keys[i]
                s = ask(scr, key, "" if st["settings"].get(key) is None else st["settings"][key])
                try:
                    st["settings"][key] = _parse(key, s)
                    save_state(st)
                except ValueError:
                    pass
                scr.timeout(-1)
    finally:
        scr.timeout(5000)


def new_build(scr, st):
    cfg = dict(st["settings"])
    start = ask(scr, "start (UTC date)", str(today_utc()))
    try:
        _date(start)
        cfg["days"] = float(ask(scr, "days", f"{float(cfg['days']):g}"))
        cfg["cam_limit"] = float(ask(scr, "star limit G", f"{float(cfg['cam_limit']):g}"))
        cfg["hmax"] = _parse("hmax", ask(scr, "H limit (none: all asteroids)", cfg["hmax"] if cfg["hmax"] is not None else "none"))
        cfg["workers"] = int(ask(scr, "workers", cfg["workers"]))
    except ValueError as e:
        return f"not started: {e}"
    ok, text = mem_check(cfg)
    if not ok and not confirm(scr, f"{text}. Start anyway?"):
        return "not started"
    args, out = build_args(cfg, start)
    if not confirm(scr, f"start whole-Earth build {os.path.basename(out)}?"):
        return "not started"
    j = launch(st, "build", args, out)
    return f"started pid {j['pid']}, log {j['log']}"


def view_log(scr, path):
    import curses
    if not path:
        return
    lines = log_tail(path, 400000)
    pos = max(0, len(lines) - (scr.getmaxyx()[0] - 1))
    scr.timeout(-1)
    try:
        while True:
            h, w = scr.getmaxyx()
            scr.erase()
            for k, ln in enumerate(lines[pos:pos + h - 1]):
                scr.addnstr(k, 0, ln, w - 1)
            scr.addnstr(h - 1, 0, f"{path}  line {pos + 1}/{len(lines)}  up/down/PgUp/PgDn, g/G, q back", w - 1,
                        curses.A_REVERSE)
            scr.refresh()
            ch = scr.getch()
            if ch in (ord("q"), 27):
                return
            step = {curses.KEY_UP: -1, ord("k"): -1, curses.KEY_DOWN: 1, ord("j"): 1, curses.KEY_PPAGE: -(h - 2),
                    curses.KEY_NPAGE: h - 2}.get(ch, 0)
            if ch == ord("g"):
                pos = 0
            elif ch == ord("G"):
                pos = max(0, len(lines) - h + 1)
            pos = min(max(0, pos + step), max(0, len(lines) - 1))
    finally:
        scr.timeout(5000)


# ------------------------------------------------------------------ command line
def add_arguments(p):
    p.add_argument("--share", metavar="DIR", help="the mirror's synced pre-screen folder (saved for later runs)")
    p.add_argument("--auto", action="store_true", help="one maintenance step, no screen (for cron / a systemd timer)")
    p.add_argument("--dry-run", action="store_true", help="with --auto: only print what it would do")
    p.add_argument("--status", action="store_true", help="print the overview and the plan, no screen")


def main(a):
    st = load_state()
    if a.share:
        sh = os.path.abspath(os.path.expanduser(a.share))
        if not os.path.isdir(sh):
            sys.exit(f"share folder {sh} does not exist")
        st["settings"]["share_dir"] = sh
        save_state(st)
    if a.auto:
        print(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  PySyzygos {__version__} pre-screen manager --auto"
              + (" (dry run)" if a.dry_run else ""))
        auto(st, a.dry_run)
        return 0
    if a.status or not sys.stdout.isatty():
        print(status_text(st))
        return 0
    if os.name != "posix":
        sys.exit("the screen needs curses (Linux/macOS); use --status / --auto")
    tui(st)
    return 0
