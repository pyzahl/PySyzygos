"""kstars.py - point a running KStars at an event: the observer site, the event time, the target star, a field
like the preview. Linux only (KStars' D-Bus interface, called with the gdbus or dbus-send command line tools). On any
other system, or without KStars running, available() says why not and show() does nothing: never raises.

Used by gui.py (/api/kstars/...), which the report's KStars buttons call when the GUI serves the report.
Standard library only.
"""
from pysyzygos.version import __version__
import json, shutil, subprocess, sys
from datetime import datetime, timedelta, timezone

DEST, PATH, IFACE = "org.kde.kstars", "/KStars", "org.kde.kstars"


def _tool():
    return shutil.which("gdbus") or shutil.which("dbus-send")


def _call(method, *args, timeout=5.0):
    """Call a KStars D-Bus method. args: (type, value) with type 'd' double, 'i' int, 'b' bool, 's' string.
    Returns (ok, output text)."""
    tool = _tool()
    if not tool:
        return False, "no gdbus or dbus-send"
    if tool.endswith("gdbus"):
        txt = lambda t, v: ("true" if v else "false") if t == "b" else repr(float(v)) if t == "d" else str(v)
        cmd = [tool, "call", "--session", "--dest", DEST, "--object-path", PATH, "--method", f"{IFACE}.{method}"]
        cmd += ["--"] + [txt(t, v) for t, v in args]            # "--": negative numbers are not options
    else:
        kind = dict(d="double", i="int32", b="boolean", s="string")
        cmd = [tool, "--session", "--print-reply", f"--dest={DEST}", PATH, f"{IFACE}.{method}"]
        cmd += [f"{kind[t]}:{('true' if v else 'false') if t == 'b' else v}" for t, v in args]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as ex:
        return False, str(ex)
    return r.returncode == 0, (r.stdout or r.stderr).strip()


def available():
    """(ok, reason): KStars can be driven from here (Linux, a D-Bus tool, KStars running)."""
    if not sys.platform.startswith("linux"):
        return False, "KStars control works on Linux only"
    if not _tool():
        return False, "gdbus or dbus-send not found"
    ok, out = _call("location", timeout=3.0)
    return (True, "KStars is running") if ok else (False, "KStars is not running (or not on the session D-Bus)")


def location():
    """KStars' current location as a dict (name, latitude, longitude, tz, ...), or None."""
    ok, out = _call("location")
    if not ok:
        return None
    try:
        return json.loads(out[out.index("{"):out.rindex("}") + 1].replace("\\\"", "\""))
    except (ValueError, KeyError):
        return None


def _km(lat1, lon1, lat2, lon2):
    import math
    p1, p2, dl = math.radians(lat1), math.radians(lat2), math.radians(lon2 - lon1)
    c = math.sin(p1) * math.sin(p2) + math.cos(p1) * math.cos(p2) * math.cos(dl)
    return 6371.0 * math.acos(max(-1.0, min(1.0, c)))


def _tz_hours():
    """KStars' current time zone offset (hours, with DST) from its location; 0 if unknown."""
    ok, out = _call("location")
    if not ok:
        return 0.0
    try:
        txt = out[out.index("{"):out.rindex("}") + 1].replace("\\\"", "\"")
        return float(json.loads(txt).get("tz", 0.0))
    except (ValueError, KeyError):
        return 0.0


LABEL = {}                     # the star labelled last ("name"): its label is removed before the next one is set


def mark(names):
    """Label the star in KStars by the first of its names KStars knows (getObjectDataXML answers '<xml></xml>' for an
    unknown name; addLabel puts the name next to the star). KStars finds stars by proper or Bayer name only (checked
    with KStars 3.6.2: not by HIP, HD, SAO, TYC or Gaia numbers), so most occultation stars stay unlabelled. The
    previous label is removed. Returns the name labelled, or None."""
    found = None
    for n in names or ():
        ok, out = _call("getObjectDataXML", ("s", n))
        if ok and "<object" in out:
            found = n
            break
    if LABEL.get("name") and LABEL["name"] != found:
        _call("removeLabel", ("s", LABEL["name"]))
        LABEL.pop("name", None)
    if found:
        _call("addLabel", ("s", found))
        LABEL["name"] = found
    return found


def show(ra_deg, dec_deg, utc, fov_deg=2.0, lat=None, lon=None, ele=0.0, set_location=True, warn_km=50.0, names=()):
    """Centre KStars on (ra, dec) (J2000 degrees) at the UTC time utc (ISO), field fov_deg. With the site lat/lon:
    set_location moves KStars' location there (if it is more than 1 km away; the message says from where), else
    KStars keeps its location and the message warns if that is more than warn_km from the site (horizon and
    altitudes are then for that place). names: the star's names (report.sky_names), labelled if KStars knows one.
    Returns (ok, message); never raises."""
    ok, why = available()
    if not ok:
        return False, why
    try:
        t = datetime.fromisoformat(str(utc).strip().rstrip("Z")[:19]).replace(tzinfo=timezone.utc)
        ra_deg, dec_deg, fov_deg = float(ra_deg), float(dec_deg), max(0.05, min(float(fov_deg), 90.0))
    except (TypeError, ValueError) as ex:
        return False, f"bad event data: {ex}"
    note = ""
    if lat is not None and lon is not None:
        here = location() or {}
        try:
            away = _km(float(here["latitude"]), float(here["longitude"]), float(lat), float(lon))
        except (KeyError, TypeError, ValueError):
            away = None
        name = here.get("name") or "?"
        if set_location and (away is None or away > 1.0):
            _call("setGPSLocation", ("d", float(lon)), ("d", float(lat)), ("d", float(ele or 0.0)), ("d", 0.0))
            note = (f"; KStars location changed from {name}" + (f" ({away:.0f} km away)" if away is not None else "")
                    + " to the site")
        elif not set_location and away is not None and away > warn_km:
            note = (f"; note: KStars location {name} is {away:.0f} km from the site, so horizon and altitudes "
                    f"are for {name}")
    for _ in range(3):              # KStars takes local time; its offset (DST) depends on the date shown: settle it
        tz = _tz_hours()
        local = t + timedelta(hours=tz)
        ok, out = _call("setLocalTime", ("i", local.year), ("i", local.month), ("i", local.day),
                        ("i", local.hour), ("i", local.minute), ("i", local.second))
        if not ok:
            return False, f"KStars setLocalTime failed: {out[:200]}"
        if _tz_hours() == tz:
            break
    steps = [("setRaDecJ2000", [("d", ra_deg / 15.0), ("d", dec_deg)]),              # RA in hours
             ("setTracking", [("b", True)]),
             ("setApproxFOV", [("d", fov_deg)])]
    for method, args in steps:
        ok, out = _call(method, *args)
        if not ok:
            return False, f"KStars {method} failed: {out[:200]}"
    if names:
        marked = mark(names)
        note += (f"; {marked} labelled" if marked else
                 "; the star has no name KStars knows: it is at the center (a crosshair FOV symbol marks it, README)")
    return True, f"KStars: {t:%Y-%m-%d %H:%M:%S} UT, RA {ra_deg:.4f} Dec {dec_deg:+.4f}, field {fov_deg:.2f} deg{note}"


def main():
    print(available())
    if len(sys.argv) >= 4:                       # pysyzygos kstars <ra_deg> <dec_deg> <utc> [fov_deg]
        print(show(*sys.argv[1:4], *(sys.argv[4:5] or [2.0])))


if __name__ == "__main__":
    sys.exit(main())
