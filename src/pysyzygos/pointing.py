"""pointing.py - favorites for other programs (a camera or mount app such as PyStarLight): the event, the star's
position for pointing, the site. Served by the GUI as JSON (read-only):

    GET /api/v1/                         what is here (version, endpoints)
    GET /api/v1/favorites                all favorites, by event time; filters: from, to (UTC, ISO or 'now'),
                                         status (comma-separated), site (name), limit
    GET /api/v1/favorites/next           the next event from now (or ?from=...), same filters
    GET /api/v1/favorites/<key>          one favorite

Local mode: open on 127.0.0.1 (this computer). Server mode: a token (pysyzygos gui --new-token NAME; header
"Authorization: Bearer <token>"), only good for GET /api/v1/, or the browser login.

Star position (degrees):
  ra_icrs, dec_icrs: the search's corrected direction at the event (Gaia proper motion to the event date, parallax,
    light deflection): ICRS/J2000 axes, what most mount drivers call "J2000".
  ra_app, dec_app: apparent place of date (true equator and equinox, "JNow": + aberration, precession-nutation;
    erfa atci13, equinox-based RA), for drivers that want JNow.
  alt, az: at the event time from the favorite's site (az from north through east), refraction not included.
User documentation (the answer's fields): SERVER_MODE.md section 6; keep the v1 field names stable."""
from pysyzygos.version import __version__
import datetime as dt
import math

API = "v1"


def _f(x):
    try:
        v = float(x)
        return None if math.isnan(v) else v
    except (TypeError, ValueError):
        return None


def _utc(text):
    """datetime (UTC, aware) of an ISO time ('Z' or no zone = UTC; 'now'), None for empty; ValueError if bad."""
    if text in (None, ""):
        return None
    if str(text).strip().lower() == "now":
        return dt.datetime.now(dt.timezone.utc)
    t = dt.datetime.fromisoformat(str(text).strip().replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def apparent(ra_deg, dec_deg, utc):
    """(ra, dec) degrees, apparent place of date (equinox based) of an ICRS direction at utc (datetime), or
    (None, None) without erfa."""
    try:
        import erfa
    except ImportError:
        return None, None
    u1, u2 = erfa.dtf2d("UTC", utc.year, utc.month, utc.day, utc.hour, utc.minute,
                        utc.second + utc.microsecond / 1e6)
    t1, t2 = erfa.taitt(*erfa.utctai(u1, u2))
    ri, di, eo = erfa.atci13(math.radians(ra_deg), math.radians(dec_deg), 0.0, 0.0, 0.0, 0.0, t1, t2)
    return math.degrees(erfa.anp(ri - eo)), math.degrees(di)


def event(entry):
    """One favorite as the API's JSON object."""
    from pysyzygos import report
    r = entry.get("record") or {}
    site = dict(entry.get("site") or {})
    name, others = report.star_label(r)
    ra, dec = _f(r.get("star_ra")), _f(r.get("star_dec"))
    utc = str(r.get("best_utc") or "")
    ra_app = dec_app = None
    if ra is not None and dec is not None and utc:
        try:
            ra_app, dec_app = apparent(ra, dec, _utc(utc))
        except ValueError:
            pass
    files = {k: f"/fav/{v}" for k, v in (entry.get("files") or {}).items() if v}
    return dict(
        key=entry.get("key"), status=entry.get("status") or "", note=entry.get("note") or "",
        target=dict(id=str(r.get("target_id") or ""), name=str(r.get("target_name") or ""),
                    kind=str(r.get("kind") or "asteroid"), radius_km=_f(r.get("r_km"))),
        utc=utc, shadow_from_utc=r.get("shadow_from_utc") or None, shadow_to_utc=r.get("shadow_to_utc") or None,
        duration_s=_f(r.get("duration_s")), max_duration_s=_f(r.get("max_duration_s")),
        mag_drop=_f(r.get("mag_drop")), chance=_f(r.get("p_site")),
        star=dict(name=name, other_names=[x for x in others.split(" · ") if x],
                  gaia_dr3=str(r.get("star") or "") or None, mag_g=_f(r.get("mag")),
                  ra_icrs=ra, dec_icrs=dec, ra_app=ra_app, dec_app=dec_app,
                  alt=_f(r.get("star_alt")), az=_f(r.get("star_az"))),
        sun_alt=_f(r.get("sun_alt")), moon_alt=_f(r.get("moon_alt_deg")), moon_sep=_f(r.get("moon_sep_deg")),
        site=dict(name=site.get("name"), lat=_f(site.get("lat")), lon=_f(site.get("lon")), ele_m=_f(site.get("ele")),
                  tz=site.get("tz")),
        files=files)


def select(entries, frm=None, to=None, status=None, site=None, limit=None):
    """Favorites in the window [frm, to] (UTC strings, 'now'), with one of the statuses (comma-separated), at the
    site (name, case-insensitive), sorted by event time; ValueError for a bad time."""
    t0, t1 = _utc(frm), _utc(to)
    want = {s.strip().lower() for s in (status or "").split(",") if s.strip()}
    out = []
    for e in entries:
        r = e.get("record") or {}
        try:
            t = _utc(r.get("best_utc"))
        except ValueError:
            continue
        if t is None or (t0 and t < t0) or (t1 and t > t1):
            continue
        if want and str(e.get("status") or "").lower() not in want:
            continue
        if site and str((e.get("site") or {}).get("name") or "").lower() != site.lower():
            continue
        out.append((t, e))
    out.sort(key=lambda x: x[0])
    rows = [e for _, e in out]
    return rows[:int(limit)] if limit else rows


def index():
    return dict(program="PySyzygos", version=__version__, api=API,
                endpoints={"/api/v1/favorites": "all favorites by event time (from, to, status, site, limit)",
                           "/api/v1/favorites/next": "the next event from now (same filters)",
                           "/api/v1/favorites/<key>": "one favorite"},
                units="degrees, UTC; ra_icrs/dec_icrs: ICRS (J2000) at the event; ra_app/dec_app: apparent of date")
