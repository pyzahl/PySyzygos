"""stellarium.py - point a running Stellarium at an event through its Remote Control plugin (HTTP, default port
8090). Stellarium setup, once: Configuration (F2) > Plugins > Remote Control: "Load at startup", restart; then
its "configure": "Server enabled" and "Enable automatically on startup", port 8090 (default), no authentication,
"Save settings". Sets the observer site (optional), the event time with the clock stopped, the view on
the target star (J2000 direction) and the field of view. Any system; never raises.

Used by gui.py (/api/stellarium/show), which the report's Stellarium buttons call when the GUI serves the report.
No status check first: a click simply tries and reports what happened. Standard library only.
"""
from pysyzygos.version import __version__
from pysyzygos import urls as U
from pysyzygos.net import urlopen
import json, math, sys, time, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timezone


def _post(path, timeout=3.0, **fields):
    """POST form fields to the Remote Control API. Returns (ok, text)."""
    req = urllib.request.Request(f"{U.URL_STELLARIUM_API}/{path}", data=urllib.parse.urlencode(fields).encode(), method="POST")
    try:
        with urlopen(req, timeout=timeout) as r:
            return True, r.read().decode("utf-8", "replace").strip()
    except urllib.error.HTTPError as ex:
        return False, f"HTTP {ex.code} {ex.reason}" + (" (Remote Control password set?)" if ex.code == 401 else "")
    except (urllib.error.URLError, OSError) as ex:
        return False, str(getattr(ex, "reason", ex))


def current_time_zone():
    """Stellarium's time zone setting (StelCore.currentTimeZone, e.g. 'Europe/Zurich'), or None."""
    try:
        with urlopen(f"{U.URL_STELLARIUM_API}/stelproperty/list", timeout=3.0) as r:
            return json.loads(r.read().decode("utf-8", "replace")).get("StelCore.currentTimeZone", {}).get("value")
    except (urllib.error.URLError, OSError, ValueError):
        return None


def julian_day(t):
    """Julian Day (UT, as Stellarium's time) of a UTC datetime."""
    return t.timestamp() / 86400.0 + 2440587.5


def j2000_vector(ra_deg, dec_deg):
    ra, dec = math.radians(ra_deg), math.radians(dec_deg)
    return [math.cos(dec) * math.cos(ra), math.cos(dec) * math.sin(ra), math.sin(dec)]


def mark(names, wait_s=3.5, every_s=0.4, view=None):
    """Select (mark) the star in Stellarium by the first of its names Stellarium knows (main/focus, mode 'mark': the
    selection marker, the view stays). Stellarium answers 'true' or 'false'; it knows 'HIP n' and, when its star
    catalogs reach the star, 'Gaia DR3 <id>'. Its deeper catalogs are loaded only for the region in view once it is
    drawn, so a faint star may be found only a moment after the view moved: asked again for up to wait_s. view (main/view
    fields): set again before each new round, and once more at the end. Stellarium applies a new time or location at
    its next drawn frame, which in its idle mode can be seconds away (0.02-1 frames/s seen); a view set before that
    frame can end up elsewhere (a first click once landed at the Pleiades), the last one set wins. Returns the name
    marked, or None (then the selection is cleared, so no other star stays marked)."""
    end = time.time() + wait_s
    while True:
        for n in names or ():
            ok, out = _post("main/focus", target=n, mode="mark")
            if not ok:                                         # Stellarium gone: no point in waiting
                return None
            if out.strip().lower() == "true":
                return n
        if not names or time.time() >= end:
            break
        time.sleep(every_s)
        if view:
            _post("main/view", **view)
    _post("main/focus")                                       # none known: clear the selection (it may be another star)
    return None


def show(ra_deg, dec_deg, utc, fov_deg=2.0, lat=None, lon=None, ele=0.0, set_location=True, name="PySyzygos site",
         tz=None, names=()):
    """Centre Stellarium on (ra, dec) (J2000 degrees) at the UTC time utc (ISO), clock stopped, field fov_deg; with
    set_location and the site lat/lon also move Stellarium's location there and, with tz (IANA name, e.g.
    "Europe/Zurich"), its clock's time zone (StelCore.currentTimeZone; a custom location has none, so Stellarium would
    keep showing the computer's zone: the instant is right either way, the time is given as a Julian Day in UT).
    names: the star's names (report.sky_names), the first one Stellarium knows is marked (selected).
    Returns (ok, message); never raises."""
    try:
        t = datetime.fromisoformat(str(utc).strip().rstrip("Z")[:19]).replace(tzinfo=timezone.utc)
        ra_deg, dec_deg, fov_deg = float(ra_deg), float(dec_deg), max(0.01, min(float(fov_deg), 180.0))
    except (TypeError, ValueError) as ex:
        return False, f"bad event data: {ex}"
    note, zone_changed = "", False
    if set_location and lat is not None and lon is not None:
        ok, out = _post("location/setlocationfields", latitude=f"{float(lat):.6f}", longitude=f"{float(lon):.6f}",
                        altitude=f"{float(ele or 0.0):.0f}", name=name, planet="Earth")
        if not ok:
            return False, f"Stellarium not reachable ({out}): Remote Control plugin running on port 8090?"
        note = "; Stellarium location set to the site"
        if tz and current_time_zone() != str(tz):             # a zone change: the event time is sent again below
            ok, out = _post("stelproperty/set", id="StelCore.currentTimeZone", value=str(tz))
            zone_changed = ok and out.lower().startswith("ok")
            note += f", its clock to {tz}" if zone_changed else f" (its time zone not set: {out[:80]})"
    ok, out = _post("main/time", time=f"{julian_day(t):.8f}", timerate="0")
    if not ok:
        return False, f"Stellarium not reachable ({out}): Remote Control plugin running on port 8090?"
    if zone_changed:                # a new time zone takes effect at Stellarium's next frame and could move the clock
        time.sleep(1.0)             # (user 2026-10-22: first click wrong after a zone change): the event time again
        _post("main/time", time=f"{julian_day(t):.8f}", timerate="0")
    _post("main/focus")             # no selection: a selected (tracked) star would pull the view back to itself
    v = j2000_vector(ra_deg, dec_deg)
    view = dict(j2000=json.dumps([round(x, 9) for x in v]))
    for path, fields in (("main/view", view), ("main/fov", dict(fov=f"{fov_deg:.4f}"))):
        ok, out = _post(path, **fields)
        if not ok:
            return False, f"Stellarium {path} failed: {out[:200]}"
    if names:
        marked = mark(names, view=view)
        note += f"; {marked} marked" if marked else "; the star is not in Stellarium's catalogs by name (view centered on it)"
    time.sleep(0.5)
    _post("main/view", **view)                                  # once more, after Stellarium's next frame (see mark)"
    return True, (f"Stellarium: {t:%Y-%m-%d %H:%M:%S} UT (clock stopped), RA {ra_deg:.4f} Dec {dec_deg:+.4f}, "
                  f"field {fov_deg:.2f} deg{note}")


def main():
    if len(sys.argv) >= 4:                       # pysyzygos stellarium <ra_deg> <dec_deg> <utc> [fov_deg]
        print(show(*sys.argv[1:4], *(sys.argv[4:5] or [2.0])))
    else:
        print("usage: pysyzygos stellarium <ra_deg> <dec_deg> <utc> [fov_deg]")


if __name__ == "__main__":
    sys.exit(main())
