"""kernels.py - download the generic SPICE kernels PySyzygos needs into the working folder (once; the Earth
orientation file is refreshed after earth_pck_max_age days). Used by search.py at start-up and by setup.py.
Standard library only (downloads with the system curl)."""
from pysyzygos.version import __version__
from pysyzygos import urls as U
import glob, os, re, subprocess
from datetime import datetime
from pathlib import Path

KERNELS = ("naif0012.tls", "de440.bsp", "pck00010.tpc", "earth_latest_high_prec.bpc")
EARTH_PCK = "earth_latest_high_prec.bpc"           # Earth orientation 2000-01-01 .. ~3 months ahead (refreshed)
# Earth orientation before 2000 (historic events): NAIF's combined file, measured from 1962, e.g.
# earth_1962_260806_2126_combined.bpc (31 MB; the name changes with each NAIF update: the newest matching file is used).
# Loaded BEFORE EARTH_PCK, so where both cover a time SPICE uses EARTH_PCK (the last loaded file wins).
EARTH_HISTORIC_GLOB = "earth_1962_*_combined.bpc"
EARTH_HISTORIC_RE = re.compile(r"earth_1962_\d{6}_\d{4}_combined\.bpc")


# Leap seconds: NAIF's leap-second kernel. naif0012.tls has every leap second up to the last one (end of 2016); a new
# one (naif0013.tls, ...) would come only with a new leap second (none announced; leap seconds end with 2027-05-20,
# CGPM 2026). The newest local naifNNNN.tls is used; refresh_lsk looks for a newer one on NAIF's server, at most once
# per earth_pck_max_age days (with the Earth orientation refresh).
LSK = "naif0012.tls"
LSK_RE = re.compile(r"naif(\d{4})\.tls")
LSK_MARKER = ".lsk_checked"                       # when NAIF's leap-second directory was last looked at


_ALIASES = {}            # body name -> NAIF code, set by body_alias (kept in the kernel pool)


def body_alias(spice, name, code):
    """Make name a SPICE name of the body code (e.g. an asteroid number '218001' for its SPK object 20218001), through
    the kernel pool (NAIF_BODY_NAME / NAIF_BODY_CODE, as a text kernel would set them). Not boddef: CSPICE N0067 holds
    853 name/code pairs, ~692 of them built in, so boddef fails after ~161 names (SPICE(TOOMANYPAIRS); a search of 400
    targets, 2026-10-19); the pool takes thousands. The pool variable is replaced as a whole, so the full list is set
    each time; a later spice.kclear() empties it (call this again after loading). Pool names win over built-in ones."""
    name = str(name).strip()
    if _ALIASES.get(name) == int(code):
        try:
            if spice.bodn2c(name) == int(code):
                return
        except Exception:
            pass
    _ALIASES[name] = int(code)
    spice.pcpool("NAIF_BODY_NAME", list(_ALIASES))
    spice.pipool("NAIF_BODY_CODE", list(_ALIASES.values()))


def lsk_file(folder="."):
    """The newest local leap-second kernel (path): naifNNNN.tls with the highest NNNN, else LSK."""
    try:
        names = [n for n in os.listdir(folder) if LSK_RE.fullmatch(n)]
    except OSError:
        names = []
    return os.path.join(folder, max(names, key=lambda n: int(LSK_RE.fullmatch(n)[1])) if names else LSK)


def _curl(url, out=None, timeout=60):
    """Text of url (out None) or a download to out (via .part); None/False on any failure."""
    try:
        if out is None:
            r = subprocess.run(["curl", "-s", "-f", "-L", "-A", "Mozilla/5.0", "--max-time", str(timeout), url],
                               capture_output=True, check=True)
            return r.stdout.decode("utf-8", errors="replace")
        subprocess.run(["curl", "-s", "-f", "-L", "-A", "Mozilla/5.0", "--max-time", str(timeout), url, "-o", out + ".part"],
                       check=True)
        os.replace(out + ".part", out)
        return True
    except (subprocess.CalledProcessError, OSError):
        if out is not None and os.path.exists(out + ".part"):
            os.remove(out + ".part")
        return None if out is None else False


def refresh_lsk(folder=".", max_age_days=7, fetch=_curl):
    """Look for a newer leap-second kernel on NAIF's server (at most once per max_age_days; offline: nothing) and
    download it next to the old one. Returns the new file's name, or None. Never raises."""
    marker = os.path.join(folder, LSK_MARKER)
    try:
        if max_age_days >= 0 and os.path.isfile(marker) and \
                (datetime.now().timestamp() - os.path.getmtime(marker)) < max_age_days * 86400:
            return None
        listing = fetch(U.URL_NAIF_LSK_DIR)
        if not listing:
            return None                                   # offline: try again next time (marker not touched)
        nums = [int(n) for n in LSK_RE.findall(listing)]
        Path(marker).touch()
        have = int(LSK_RE.fullmatch(os.path.basename(lsk_file(folder)))[1])
        if not nums or max(nums) <= have:
            return None
        name = f"naif{max(nums):04d}.tls"
        if fetch(U.URL_NAIF_LSK_DIR + name, os.path.join(folder, name)):
            print(f"* new leap-second kernel from NAIF: {name} (used from now on)")
            return name
    except Exception as e:                                # never stop a run for this
        print(f"(leap-second kernel check skipped: {str(e)[:120]})")
    return None


def historic_earth_pck(folder="."):
    """The newest local historic Earth orientation file (path), or None."""
    files = sorted(glob.glob(os.path.join(folder, EARTH_HISTORIC_GLOB)))
    return files[-1] if files else None


def earth_kernels(folder="."):
    """The Earth orientation files to load, in load order: the historic one (if any) first, then EARTH_PCK."""
    h = historic_earth_pck(folder)
    return ([h] if h else []) + [os.path.join(folder, EARTH_PCK)]


def window_coverage(spans, et0, et1):
    """Which loaded Earth orientation files cover a window. spans: [(name, start_et, stop_et)] in LOAD ORDER (the last
    loaded wins where they overlap). Returns (ok, problem): ok when every time in et0..et1 lies in some file's span;
    problem: a short text when the window starts before or ends after what the files cover together."""
    if not spans:
        return False, "no Earth orientation file loaded"
    lo, hi = min(s[1] for s in spans), max(s[2] for s in spans)
    if et0 < lo:
        return False, "starts before"
    if et1 > hi:
        return False, "ends after"
    # gaps between the files' spans inside the window
    edges = sorted((s[1], s[2]) for s in spans)
    reach = edges[0][1]
    for a, b in edges[1:]:
        if a > reach and a > et0 and reach < et1:
            return False, "gap"
        reach = max(reach, b)
    return True, ""


def download_historic_earth_pck(folder="."):
    """Download NAIF's newest earth_1962_*_combined.bpc (Earth orientation from 1962, ~31 MB) into folder, found in the
    PCK directory listing. Returns its path, or None (offline: a message is printed)."""
    import urllib.request
    try:
        from pysyzygos import net
        html = net.urlopen(urllib.request.Request(U.URL_NAIF_PCK_DIR, headers={"User-Agent": "Mozilla/5.0"}),
                           timeout=60).read().decode("latin-1")
        names = sorted(set(EARTH_HISTORIC_RE.findall(html)))
        if not names:
            raise RuntimeError(f"no earth_1962_*_combined.bpc listed at {U.URL_NAIF_PCK_DIR}")
    except Exception as e:
        print(f"🚨 historic Earth orientation file: listing failed ({str(e)[:160]})")
        return None
    name = names[-1]
    dst = os.path.join(folder, name)
    if os.path.isfile(dst):
        return dst
    print(f"Downloading {name} (Earth orientation from 1962, ~31 MB) via system curl...")
    try:
        subprocess.run(["curl", "-f", "-L", "-A", "Mozilla/5.0", U.URL_NAIF_PCK_DIR + name, "-o", dst + ".part"],
                       check=True)
        os.replace(dst + ".part", dst)
    except (subprocess.CalledProcessError, OSError) as e:
        if os.path.exists(dst + ".part"):
            os.remove(dst + ".part")
        print(f"🚨 download of {name} failed: {e}")
        return None
    return dst


def pck_span(spice, path, frame=3000):
    """(start_et, stop_et) of an Earth orientation PCK (frame 3000 = ITRF93)."""
    cover = spice.cell_double(2000) if hasattr(spice, "cell_double") else spice.stypes.SPICEDOUBLE_CELL(2000)
    spice.pckcov(path, frame, cover)
    n = spice.wncard(cover)
    return spice.wnfetd(cover, 0)[0], spice.wnfetd(cover, n - 1)[1]


def check_file_age(file_path_str, days=-1):
    file_path = Path(file_path_str)
    if not file_path.is_file(): ## does not exist => False
        #print(f"Error: The file '{file_path_str}' does not exist.")
        return False

    if days < 0:  ## do not care (always good) => True
        return True
    
    now = datetime.now()
    
    # Get last modification time and creation time (with fallback for Unix)
    last_write_date = datetime.fromtimestamp(file_path.stat().st_mtime)
    try:
        ctime_timestamp = file_path.stat().st_birthtime
    except AttributeError:
        ctime_timestamp = file_path.stat().st_ctime
    creation_date = datetime.fromtimestamp(ctime_timestamp)

    # Calculate age in days
    age_since_creation = (now - creation_date).days
    age_since_write = (now - last_write_date).days

    #print(f"File: {file_path.name}")
    #print(f"Created: {creation_date} ({age_since_creation} days old)")
    #print(f"Modified: {last_write_date} ({age_since_write} days old)")
    return age_since_write <= days ## older than days => False
    

def pck_comment_dates(path="earth_latest_high_prec.bpc"):
    """{'created', 'last_datum'} from the comment block of NAIF's Earth PCK (ISO strings, None if not found). Values
    after the last datum (measured Earth orientation) up to the file's coverage end are predictions."""
    import re
    try:
        with open(path, "rb") as f:
            text = f.read(1 << 20).decode("latin-1")
    except OSError:
        return dict(created=None, last_datum=None)
    m1 = re.search(r"Creation date:\s+(\d{4}-\d\d-\d\dT[\d:]+)", text)
    m2 = re.search(r"UTC Epoch of last datum:\s+(\d{4} \w{3} \d\d)", text)
    last = datetime.strptime(m2.group(1), "%Y %b %d").strftime("%Y-%m-%d") if m2 else None
    return dict(created=m1.group(1) if m1 else None, last_datum=last)


# Basic Kerenls and Data
def download_kernels(earth_pck_max_age=7):
    urls = {
        # fname: [url, maxage]
        "naif0012.tls": [U.URL_NAIF_LSK, -1],
        "de440.bsp": [U.URL_NAIF_DE440, -1],
        "pck00010.tpc": [U.URL_NAIF_PCK, -1],
        "earth_latest_high_prec.bpc": [U.URL_NAIF_EARTH_PCK, earth_pck_max_age],
    }
    
    # Complete browser headers to clear security checks
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1"
    }

    for name, [url, maxage] in urls.items():
        #print (f"{name}: {url} ** maxage: {maxage} d")
        
        # Clean check: Delete the file if it somehow contains HTML text
        if os.path.exists(name):
            with open(name, 'r', errors='ignore') as f:
                first_line = f.readline()
                if "<!doctype" in first_line.lower() or "<html" in first_line.lower():
                    print(f"Purging old HTML file from cache: {name}")
                    os.remove(name)

        # Download using the system curl pipeline if it doesn't exist
        if not check_file_age (name, maxage):
            print(f"Downloading {name} via system curl...")
            part = name + ".part"
            try:
                # -L follows redirects, -f fails on server errors (no error page saved as a kernel); into .part,
                # renamed when complete, so a broken download never looks like a kernel
                subprocess.run(["curl", "-f", "-L", "-A", "Mozilla/5.0", url, "-o", part], check=True)
                os.replace(part, name)
            except (subprocess.CalledProcessError, OSError) as e:
                if os.path.exists(part):
                    os.remove(part)
                why = "curl not found: install curl" if isinstance(e, FileNotFoundError) else e
                print(f"🚨 Curl download failed for {name}: {why}\n"
                      f"   URL: {url}\n   (offline, server down, or blocked; behind a proxy set https_proxy, e.g. "
                      f"export https_proxy=http://proxy.example:8080)")
                if os.path.exists(name):                     # a refresh failed: the older copy still works
                    print(f"   keeping the existing {name} (older than {maxage} days); refreshed on a later run")
                    continue
                return False
                
    refresh_lsk(".", earth_pck_max_age)                  # a newer leap-second kernel? (weekly, with the Earth file)
    print("✅ All kernels verified and downloaded cleanly via curl.")

    return True
