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
import json, math, sys, urllib.error, urllib.parse, urllib.request
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


def julian_day(t):
    """Julian Day (UT, as Stellarium's time) of a UTC datetime."""
    return t.timestamp() / 86400.0 + 2440587.5


def j2000_vector(ra_deg, dec_deg):
    ra, dec = math.radians(ra_deg), math.radians(dec_deg)
    return [math.cos(dec) * math.cos(ra), math.cos(dec) * math.sin(ra), math.sin(dec)]


def show(ra_deg, dec_deg, utc, fov_deg=2.0, lat=None, lon=None, ele=0.0, set_location=True, name="PySyzygos site",
         tz=None):
    """Centre Stellarium on (ra, dec) (J2000 degrees) at the UTC time utc (ISO), clock stopped, field fov_deg; with
    set_location and the site lat/lon also move Stellarium's location there and, with tz (IANA name, e.g.
    "Europe/Zurich"), its clock's time zone (StelCore.currentTimeZone; a custom location has none, so Stellarium would
    keep showing the computer's zone: the instant is right either way, the time is given as a Julian Day in UT).
    Returns (ok, message); never raises."""
    try:
        t = datetime.fromisoformat(str(utc).strip().rstrip("Z")[:19]).replace(tzinfo=timezone.utc)
        ra_deg, dec_deg, fov_deg = float(ra_deg), float(dec_deg), max(0.01, min(float(fov_deg), 180.0))
    except (TypeError, ValueError) as ex:
        return False, f"bad event data: {ex}"
    note = ""
    if set_location and lat is not None and lon is not None:
        ok, out = _post("location/setlocationfields", latitude=f"{float(lat):.6f}", longitude=f"{float(lon):.6f}",
                        altitude=f"{float(ele or 0.0):.0f}", name=name, planet="Earth")
        if not ok:
            return False, f"Stellarium not reachable ({out}): Remote Control plugin running on port 8090?"
        note = "; Stellarium location set to the site"
        if tz:
            ok, out = _post("stelproperty/set", id="StelCore.currentTimeZone", value=str(tz))
            note += f", its clock to {tz}" if ok and out.lower().startswith("ok") else \
                f" (its time zone not set: {out[:80]})"
    ok, out = _post("main/time", time=f"{julian_day(t):.8f}", timerate="0")
    if not ok:
        return False, f"Stellarium not reachable ({out}): Remote Control plugin running on port 8090?"
    v = j2000_vector(ra_deg, dec_deg)
    for path, fields in (("main/view", dict(j2000=json.dumps([round(x, 9) for x in v]))), ("main/fov", dict(fov=f"{fov_deg:.4f}"))):
        ok, out = _post(path, **fields)
        if not ok:
            return False, f"Stellarium {path} failed: {out[:200]}"
    return True, (f"Stellarium: {t:%Y-%m-%d %H:%M:%S} UT (clock stopped), RA {ra_deg:.4f} Dec {dec_deg:+.4f}, "
                  f"field {fov_deg:.2f} deg{note}")


def main():
    if len(sys.argv) >= 4:                       # pysyzygos stellarium <ra_deg> <dec_deg> <utc> [fov_deg]
        print(show(*sys.argv[1:4], *(sys.argv[4:5] or [2.0])))
    else:
        print("usage: pysyzygos stellarium <ra_deg> <dec_deg> <utc> [fov_deg]")


if __name__ == "__main__":
    sys.exit(main())
