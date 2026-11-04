"""obsreport.py - observation reports: the data of one observed occultation, as entered after the night.

One report per event and observer (station): the fields of the IOTA-ES asteroidal occultation report form (version
2.03, the form behind the online submission and the DVTI+CAM template), which carries what Occult's archive keeps
per observer (<Observer>: ID, Conditions, D, R; occult_data/FileFormat AsteroidObservations.htm). Filled from

    a favorite (favorites.py, also a saved list): asteroid, star, date, predicted times, site, prediction details
    an event of the Occult archive (observed.py): event and, optionally, one of its observers with D/R
    a PyStarLight analysis (<movie>.event.json of its viewer): D/R times with errors, recording, camera, site
    an IOTA-ES report form (.txt), e.g. one written by the DVTI tools or by this module

and written as an IOTA-ES report form text (`to_iotaes`) for the submission. Saved per event in
<data folder>/observations/<event key>/<station>.json (private, gitignored). Used by gui_observation.py (the
separate observation GUI, `pysyzygos gui-observation`). Standard library only.
"""
from pysyzygos.version import __version__
import glob, hmac, json, math, os, re, secrets, tempfile
from datetime import datetime, timedelta, timezone

DIR = "observations"
FORM = "IOTA-ES ASTEROIDAL OCCULTATION - REPORT FORM 2.03"

# codes as in the IOTA-ES form (and Occult's archive)
OUTCOMES = ("POSITIVE", "NEGATIVE", "CLOUDED OUT", "TECHNICAL PROBLEMS", "NO OBSERVATION")
DATUM = {"": "WGS84", "N": "NAD1927", "E": "ED1950", "T": "Tokyo", "G": "GB1936", "*": "unspecified, or other"}
TELESCOPE = {"": "unstated", "1": "Refractor", "2": "Newtonian", "3": "SCT", "4": "Dobsonian", "5": "Binoculars",
             "6": "Other", "7": "None", "8": "Electronic (small self-aligning telescope with a detector)"}
METHOD = {"": "unspecified", "a": "Analogue & digital video", "b": "Digital SLR-camera video", "c": "Photometer",
          "d": "Sequential images", "e": "Drift scan", "f": "Visual", "g": "Other"}
TIME_SOURCE = {"": "unspecified", "a": "GPS", "b": "NTP", "c": "Telephone (fixed or mobile)",
               "d": "Radio time signal", "e": "Internal clock of recorder", "f": "Stopwatch", "g": "Other"}
D_CODES = {"D": "main star", "d": "second star", "G": "satellite, main star", "g": "satellite, second star",
           "N": "ring", "M": "non-detection", "C": "not seen (cloud)"}
R_CODES = {"R": "main star", "r": "second star", "B": "satellite, main star", "b": "satellite, second star",
           "N": "ring", "M": "non-detection", "C": "not seen (cloud)"}
TRANSPARENCY = {"": "unstated", "1": "Clear", "2": "Fog", "3": "Thin cloud (< 2 mag loss)",
                "4": "Thick cloud (> 2 mag loss)", "5": "Broken opaque cloud (through gaps)", "6": "Star faint",
                "7": "By averted vision"}
STABILITY = {"": "unstated", "1": "Steady", "2": "Slight flickering", "3": "Strong flickering"}

# (key, label, section, kind, choices): kinds text / num / choice / area; the order is the form's
FIELDS = [
    ("outcome", "Result", "Event", "choice", OUTCOMES),
    ("asteroid_number", "Asteroid number", "Event", "text", None),
    ("asteroid_name", "Asteroid name", "Event", "text", None),
    ("star", "Star (catalog name)", "Event", "text", None),
    ("gaia_id", "Gaia DR3 source id", "Event", "text", None),
    ("date", "Date (UT, YYYY-MM-DD)", "Event", "text", None),
    ("predict_time", "Predicted time (UT)", "Event", "text", None),
    ("pred_d", "Predicted D at the site (UT)", "Event", "text", None),
    ("pred_r", "Predicted R at the site (UT)", "Event", "text", None),
    ("observer1", "Observer 1", "Observer", "text", None),
    ("observer2", "Observer 2", "Observer", "text", None),
    ("more_obs", "More observers", "Observer", "text", None),
    ("email", "E-mail", "Observer", "text", None),
    ("address", "Address", "Observer", "text", None),
    ("station", "Station", "Station", "text", None),
    ("station_note", "Station note (short name)", "Station", "text", None),
    ("nearest_city", "Nearest city", "Station", "text", None),
    ("country", "Country code", "Station", "text", None),
    ("lat", "Latitude (deg, + north)", "Station", "num", None),
    ("lon", "Longitude (deg, + east)", "Station", "num", None),
    ("alt_m", "Altitude (m)", "Station", "num", None),
    ("datum", "Datum", "Station", "choice", DATUM),
    ("mpc_code", "MPC observatory code", "Station", "text", None),
    ("telescope", "Telescope type", "Equipment", "choice", TELESCOPE),
    ("telescope_text", "Telescope (description)", "Equipment", "text", None),
    ("aperture_cm", "Aperture (cm)", "Equipment", "num", None),
    ("focal_cm", "Focal length (cm)", "Equipment", "num", None),
    ("reducer", "Focal reducer / Barlow", "Equipment", "text", None),
    ("mount", "Mount", "Equipment", "text", None),
    ("method", "Observing method", "Equipment", "choice", METHOD),
    ("time_source", "Time source", "Equipment", "choice", TIME_SOURCE),
    ("camera", "Camera", "Equipment", "text", None),
    ("start_obs", "Start of recording (UT)", "Observation", "text", None),
    ("end_obs", "End of recording (UT)", "Observation", "text", None),
    ("d_code", "D event", "Observation", "choice", D_CODES),
    ("d_time", "D time (UT)", "Observation", "text", None),
    ("d_acc", "D accuracy (s)", "Observation", "num", None),
    ("r_code", "R event", "Observation", "choice", R_CODES),
    ("r_time", "R time (UT)", "Observation", "text", None),
    ("r_acc", "R accuracy (s)", "Observation", "num", None),
    ("duration", "Duration (s)", "Observation", "num", None),
    ("exp_time", "Exposure (s)", "Observation", "num", None),
    ("pe_s", "Personal equation / camera delay (s)", "Observation", "num", None),
    ("snr", "Signal/noise", "Observation", "num", None),
    ("extra_events", "More events (one per line: code time accuracy, e.g. 'd 17:55:01.20 0.05')", "Observation",
     "area", None),
    ("transparency", "Transparency", "Conditions", "choice", TRANSPARENCY),
    ("stability", "Stability", "Conditions", "choice", STABILITY),
    ("wind", "Wind", "Conditions", "text", None),
    ("temperature", "Temperature (C)", "Conditions", "text", None),
    ("comments", "Comments", "Conditions", "area", None),
    ("feed", "Prediction source (feed)", "Prediction", "text", None),
    ("probability", "Probability (%)", "Prediction", "num", None),
    ("pred_duration", "Predicted duration (s)", "Prediction", "num", None),
    ("dist_center_km", "Distance from the center line (km)", "Prediction", "num", None),
    ("path_width_km", "Path width (km)", "Prediction", "num", None),
    ("star_mag", "Star magnitude (G)", "Prediction", "num", None),
    ("star_alt", "Star altitude (deg)", "Prediction", "num", None),
    ("star_az", "Star azimuth (deg)", "Prediction", "num", None),
    ("constellation", "Constellation", "Prediction", "text", None),
    ("asteroid_mag", "Asteroid magnitude", "Prediction", "num", None),
    ("asteroid_diam_km", "Asteroid diameter (km)", "Prediction", "num", None),
    ("combined_mag", "Combined magnitude", "Prediction", "num", None),
    ("delta_mag", "Magnitude drop", "Prediction", "num", None),
    ("moon", "Moon", "Prediction", "text", None),
]
KEYS = [f[0] for f in FIELDS]
SECTIONS = list(dict.fromkeys(f[2] for f in FIELDS))


def blank():
    return {k: "" for k in KEYS}


def _num(x, nd=None):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return ""
    if not math.isfinite(v):
        return ""
    return round(v, nd) if nd is not None else v


def _hms(utc, nd=1):
    """'HH:MM:SS.s' of an ISO time ('2026-11-02T01:09:10.379' -> '01:09:10.4'); '' if not readable."""
    t = _parse_utc(utc)
    if t is None:
        return ""
    s = t.second + t.microsecond / 1e6
    return f"{t:%H:%M}:{s:0{3 + nd if nd else 2}.{nd}f}"


def _parse_utc(text):
    s = str(text or "").strip().rstrip("Z").replace(" ", "T")
    if not s:
        return None
    try:
        return datetime.fromisoformat(s[:26])
    except ValueError:
        return None


def seconds_of_day(hms):
    """'17:54:59.752' (hours may be >= 24) -> seconds, or None."""
    m = re.fullmatch(r"\s*[A-Za-z]?\s*(\d{1,2})[: ](\d{1,2})[: ](\d{1,2}(?:\.\d*)?)\s*", str(hms or ""))
    if not m:
        return None
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))


def _name_parts(target_id, target_name):
    """('3200', 'Phaethon') from '3200' / '3200 Phaethon (1983 TB)'; ('', '2026 ED138') for an unnumbered one."""
    tid, name = str(target_id or "").strip(), str(target_name or "").strip()
    m = re.match(r"^(\d+)\+(?:P|S\d)$", tid)          # a binary's body searched on its own: the asteroid's report
    if m:
        from pysyzygos import binaries
        return m.group(1), (binaries.lookup(m.group(1)) or {}).get("name") or re.sub(r"^\(?\d+\)?\s*", "", name).split(" I")[0]
    if not tid.isdigit():
        return "", tid or name
    rest = re.sub(r"^\(?\d+\)?\s*", "", name)
    rest = re.sub(r"\s*\([^()]*\)\s*$", "", rest).strip()
    return tid, rest


def _star_name(r):
    if str(r.get("star_ucac4") or "").strip():
        return f"UCAC4 {str(r['star_ucac4']).strip()}"
    if str(r.get("star_tyc") or "").strip():
        return f"TYC {str(r['star_tyc']).strip()}"
    if str(r.get("star_catalog") or "").strip():
        return str(r["star_catalog"]).strip()
    return f"Gaia DR3 {r['star']}" if str(r.get("star") or "").strip() else ""


def _outcome_from(status, note):
    n = str(note or "").strip().upper()
    for o in OUTCOMES:
        if n.startswith(o) or n.startswith(o.split()[0]):
            return o
    return {"clouded": "CLOUDED OUT"}.get(str(status or ""), "")


def from_favorite(entry, sites=None):
    """Report fields from a favorite (favorites.load() entry): event, predicted times at its site, the site and its
    equipment (sites: sites.py's dict, matched by the site's name), prediction details. Returns a dict (KEYS)."""
    r, site = entry.get("record") or {}, entry.get("site") or {}
    f = blank()
    num, name = _name_parts(r.get("target_id"), r.get("target_name"))
    when = _parse_utc(r.get("best_utc"))
    rad, d = _num(r.get("r_km")), _num(r.get("ground_dist_km") if r.get("ground_dist_km") not in (None, "") else
                                        r.get("min_distance"))
    dur = _num(r.get("max_duration_s"))
    chord = ""
    if when and rad and dur and d != "" and d < rad:
        chord = dur * math.sqrt(1 - (d / rad) ** 2)                # the site's chord (straight shadow edge model)
    f.update(asteroid_number=num, asteroid_name=name, star=_star_name(r), gaia_id=str(r.get("star") or "").strip(),
             date=f"{when:%Y-%m-%d}" if when else "", predict_time=_hms(r.get("best_utc")),
             outcome=_outcome_from(entry.get("status"), entry.get("note")))
    if chord:
        f.update(pred_d=_hms((when - timedelta(seconds=chord / 2)).isoformat()),
                 pred_r=_hms((when + timedelta(seconds=chord / 2)).isoformat()), pred_duration=round(chord, 2))
    f.update(station=site.get("name") or "", lat=_num(site.get("lat"), 6), lon=_num(site.get("lon"), 6),
             alt_m=_num(site.get("ele"), 1), mpc_code=site.get("mpc_code") or "")
    s = next((v for v in (sites or {}).values() if isinstance(v, dict) and v.get("name") == site.get("name")), None)
    if s:
        f.update(aperture_cm=_num(s.get("aperture_cm")) if s.get("aperture_cm") else "",
                 alt_m=f["alt_m"] if f["alt_m"] != "" else _num(s.get("ele"), 1),
                 mpc_code=f["mpc_code"] or s.get("mpc_code") or "")
    p = _num(r.get("p_site"))
    moon = ""
    if _num(r.get("moon_illum_pct")) != "":
        moon = f"{_num(r.get('moon_illum_pct'), 0):.0f} % lit" + (
            f", {_num(r.get('moon_sep_deg'), 0):.0f} deg away" if _num(r.get("moon_sep_deg")) != "" else "")
    orbit = (entry.get("phys") or {}).get("orbit")
    orbit = orbit[0] if isinstance(orbit, (list, tuple)) and orbit else ""
    f.update(feed=f"PySyzygos {entry.get('version') or ''}".strip() + (f", orbit {orbit}" if orbit else ""),
             probability=round(100 * p, 1) if p != "" else "", dist_center_km=round(d, 2) if d != "" else "",
             path_width_km=round(2 * rad, 2) if rad else "", star_mag=_num(r.get("mag"), 2),
             star_alt=_num(r.get("star_alt"), 0), star_az=_num(r.get("star_az"), 0),
             constellation=r.get("constellation") or "", asteroid_mag=_num(r.get("m_ast"), 2),
             asteroid_diam_km=round(2 * rad, 2) if rad else "", combined_mag=_num(r.get("m_combined"), 2),
             delta_mag=_num(r.get("mag_drop"), 2), moon=moon)
    if not f["pred_duration"] and dur:
        f["pred_duration"] = round(dur, 2)
    return f


def from_archive(rec, contacts=(), observer=None):
    """Report fields from an event of the Occult archive (observed.find): the event, and with observer (a name of
    rec['obs_sites']) that observer's station and D/R times."""
    f = blank()
    num, name = _name_parts(rec.get("target_id"), rec.get("target_name"))
    f.update(asteroid_number=num, asteroid_name=name, star=_star_name(rec), gaia_id=str(rec.get("star") or ""),
             date=str(rec.get("best_utc") or "")[:10], predict_time=_hms(rec.get("best_utc")),
             feed=str(rec.get("prediction") or ""), star_mag=_num(rec.get("mag"), 2),
             asteroid_mag=_num(rec.get("m_ast"), 2),
             asteroid_diam_km=round(2 * rec["r_km"], 2) if _num(rec.get("r_km")) else "")
    if observer:
        o = next((s for s in rec.get("obs_sites") or [] if s.get("observer") == observer), None) or {}
        f.update(observer1=observer, nearest_city=o.get("place") or "", lat=_num(o.get("lat"), 6),
                 lon=_num(o.get("lon"), 6), alt_m=_num(o.get("alt_m"), 1),
                 datum="" if o.get("datum") in (None, "_") else o["datum"], method=o.get("method") or "",
                 outcome={"positive": "POSITIVE", "miss": "NEGATIVE", "clouded": "CLOUDED OUT"}.get(
                     o.get("result"), ""))
        for label, utc, data in contacts:
            if data.get("observer") != observer:
                continue
            side = "d" if label in D_CODES else "r" if label in R_CODES else None
            if side and not f[f"{side}_time"]:
                f[f"{side}_code"], f[f"{side}_time"] = label, _hms(utc, 3)
                f[f"{side}_acc"] = _num(data.get("acc_s"))
                if data.get("pe_s") not in (None, ""):
                    f["pe_s"] = _num(data["pe_s"])
        _duration(f)
    return f


def _duration(f):
    a, b = seconds_of_day(f.get("d_time")), seconds_of_day(f.get("r_time"))
    if a is not None and b is not None:
        f["duration"] = round((b - a) % 86400, 3)


# The recording's metadata (written by the camera tool into the video: PyStarLight's capture, DVTI, ...) -> report
# fields. These are the authentic data of the observation (GPS site and time, camera, telescope, observers): they are
# marked 'recording' and a later change by hand is shown and kept as such. Names beyond those of today's recordings are
# the proposal of docs/observation_interface.md for the camera tool.
RECORDING_KEYS = (("OBSERVER", "observer1"), ("OBSERVER-2", "observer2"), ("OBSERVERS-MORE", "more_obs"),
                  ("STATION", "station"), ("TELESCOPE", "telescope_text"), ("TELESCOPE-TYPE", "telescope"),
                  ("APERTURE-CM", "aperture_cm"), ("FOCAL-LENGTH-CM", "focal_cm"), ("FOCAL-REDUCER", "reducer"),
                  ("MOUNT", "mount"), ("DATUM", "datum"), ("TIME-SOURCE", "time_source"),
                  ("OBSERVING-METHOD", "method"), ("EXPOSURE-S", "exp_time"), ("CAMERA-DELAY-S", "pe_s"),
                  ("TIMESTAMP-SOURCE", "time_source"))         # RAVF (PyStarLight capture): 'GPS trigger pulse, ...'

TIME_SOURCE_WORDS = {"gps utc": "a", "ntp": "b", "gps": "a", "phone": "c", "radio": "d",   # first match wins:
                     "internal": "e", "clock": "e"}         # 'GPS trigger pulse, Pi clock (NTP)' is NTP time
PSL_ORIGIN = {"recording": "the recording (camera, GPS)", "analysis": "the PyStarLight analysis",
              "prediction": "the prediction", "edited": "edited by hand"}


def _code_of(table, words, v):
    v = str(v or "").strip()
    if v in table:
        return v
    low = v.lower()
    return next((c for w, c in words.items() if w in low), "") if words else \
        next((c for c, t in table.items() if c and t.lower() == low), "")


def from_pystarlight(path):
    """(fields, note, origin) from a PyStarLight analysis (<movie>.event.json of its viewer): the recording's
    metadata (site from the GPS, camera and sensor, telescope, observers, start/end; origin 'recording'), and from the
    analysis the star and the first D/R event of the step fit (times, 1-sigma errors, duration, SNR; origin
    'analysis'). Only the fields it knows; origin = {field: 'recording' | 'analysis'}."""
    with open(path, encoding="utf-8") as fh:
        js = json.load(fh)
    rec, fit = js.get("recording") or {}, js.get("step_fit") or {}
    meta = {str(k).upper(): v for k, v in (rec.get("metadata") or {}).items()}
    f, origin = {}, {}

    def put(key, value, where):
        if value not in (None, ""):
            f[key], origin[key] = value, where
    obj = str(js.get("object") or meta.get("OBJNAME") or "")
    m = re.match(r"^\s*\((\d+)\)\s*([^\s].*?)\s+occ\.?", obj)
    if m:
        put("asteroid_number", m.group(1), "recording")
        put("asteroid_name", m.group(2).strip(), "recording")
    t = js.get("target") or {}
    ids = t.get("ids") or {}
    put("star", ids.get("UCAC4") or t.get("name"), "analysis")
    if ids.get("Gaia DR3"):
        put("gaia_id", str(ids["Gaia DR3"]).replace("Gaia DR3", "").strip(), "analysis")
    put("date", rec.get("date"), "recording")
    put("start_obs", rec.get("first_utc"), "recording")
    put("end_obs", rec.get("last_utc"), "recording")
    put("exp_time", fit.get("frame_interval_s"), "recording")
    shutter = _num(meta.get("INSTRUMENT-SHUTTER"))                 # RAVF: the exposure in ns (the true one)
    if shutter:
        put("exp_time", round(shutter / 1e9, 6), "recording")
    for k, key in RECORDING_KEYS:
        if key in f and origin.get(key) == "recording" and k in ("TIMESTAMP-SOURCE",):
            continue                                                  # TIME-SOURCE given: it wins
        v = str(meta.get(k) if meta.get(k) is not None else "").strip()
        if key == "time_source":
            v = _code_of(TIME_SOURCE, TIME_SOURCE_WORDS, v)
        elif key == "telescope":
            v = _code_of(TELESCOPE, None, v)
        elif key == "method":
            v = _code_of(METHOD, None, v)
        elif key in ("aperture_cm", "focal_cm", "exp_time", "pe_s"):
            v = _num(v)
        put(key, v, "recording")
    cam = str(meta.get("INSTRUMENT") or meta.get("CAMERA-MODEL") or "").strip()
    sensor = str(meta.get("CAMERA-SENSOR-INFO") or meta.get("INSTRUMENT-SENSOR") or "").strip()
    serial = str(meta.get("CAMERA-SERIAL-NO") or meta.get("INSTRUMENT-SERIAL") or "").strip()
    if cam:
        named = serial and re.search(rf"(#|serial\s*){re.escape(serial)}\b", cam, re.I)      # 'DVTI+CAM #43 ...'
        cam += (f", serial {serial}" if serial and not named else "") + (f"; {sensor}" if sensor else "")
    put("camera", cam, "recording")
    for k, key, nd in (("LATITUDE", "lat", 6), ("LONGITUDE", "lon", 6), ("ALTITUDE", "alt_m", 1)):
        put(key, _num(meta.get(k), nd), "recording")
    _from_station(rec.get("station") or {}, put)
    events, trans = fit.get("events") or [], fit.get("transitions") or []
    note = f"PyStarLight analysis {os.path.basename(path)} ({js.get('software', '?')}, {js.get('created_utc', '?')})"
    if events:
        ev = events[0]
        sig = lambda i: trans[i].get("sigma_s") if isinstance(i, int) and i < len(trans) else None
        for key, v in (("d_code", "D"), ("d_time", _hms(ev.get("D_utc"), 3)), ("r_code", "R"),
                       ("r_time", _hms(ev.get("R_utc"), 3)), ("outcome", "POSITIVE")):
            put(key, v, "analysis")
        if sig(ev.get("D")) is not None:
            put("d_acc", round(sig(ev["D"]), 3), "analysis")
        if sig(ev.get("R")) is not None:
            put("r_acc", round(sig(ev["R"]), 3), "analysis")
        if ev.get("duration_s") is not None:
            put("duration", round(ev["duration_s"], 3), "analysis")
        first = trans[ev["D"]] if isinstance(ev.get("D"), int) and ev["D"] < len(trans) else {}
        lev = (fit.get("levels") or [{}])[0]
        if first.get("flux_before") and first.get("flux_after") is not None and lev.get("flux_scatter"):
            put("snr", round((first["flux_before"] - first["flux_after"]) / lev["flux_scatter"], 1), "analysis")
        extra = [f"{x} {_hms(e.get(x + '_utc'), 3)} {round(sig(e.get(x)), 3) if sig(e.get(x)) is not None else ''}"
                 .strip() for e in events[1:] for x in ("D", "R") if e.get(x + "_utc")]
        if extra:
            put("extra_events", "\n".join(extra), "analysis")
            note += f"; {len(events) - 1} more event(s) in 'More events': set their codes (d, G, ...)"
    else:
        note += "; no D/R event in its step fit"
    return f, note, origin


# recording.station of event.json (docs/observation_interface.md section 2): the station data PyStarLight takes
# from any video format (RAVF, ADV, SER + sidecar) in one layout; it wins over the raw metadata keys
STATION_PATHS = (("site", "lat", "lat", 6), ("site", "lon", "lon", 6), ("site", "alt_m", "alt_m", 1),
                 ("site", "datum", "datum", None), ("", "station", "station", None),
                 ("equipment", "telescope", "telescope_text", None), ("equipment", "aperture_cm", "aperture_cm", None),
                 ("equipment", "focal_length_cm", "focal_cm", None), ("equipment", "focal_reducer", "reducer", None),
                 ("equipment", "mount", "mount", None), ("timing", "exposure_s", "exp_time", None),
                 ("timing", "camera_delay_s", "pe_s", None))


def _from_station(st, put):
    """Put the fields of a recording.station block (all origin 'recording')."""
    if not isinstance(st, dict) or not st:
        return
    for part, k, key, nd in STATION_PATHS:
        v = (st.get(part) or {}).get(k) if part else st.get(k)
        if v in (None, ""):
            continue
        put(key, _num(v, nd) if nd is not None else v, "recording")
    obs = [o for o in st.get("observers") or [] if str(o or "").strip()]
    for key, v in (("observer1", obs[:1]), ("observer2", obs[1:2]), ("more_obs", obs[2:])):
        if v:
            put(key, ", ".join(v), "recording")
    eq, tm = st.get("equipment") or {}, st.get("timing") or {}
    if eq.get("telescope_type"):
        put("telescope", _code_of(TELESCOPE, None, eq["telescope_type"]), "recording")
    if eq.get("method"):
        put("method", _code_of(METHOD, None, eq["method"]), "recording")
    if tm.get("source"):
        put("time_source", _code_of(TIME_SOURCE, TIME_SOURCE_WORDS, tm["source"]), "recording")
    cam = ", ".join(str(eq[k]) for k in ("camera", "serial", "sensor") if eq.get(k))
    if cam:
        put("camera", cam, "recording")


def software_of(path):
    """'PyStarLight 0.1.0' of an analysis file, or ''."""
    try:
        with open(path, encoding="utf-8") as fh:
            return str(json.load(fh).get("software") or "")
    except (OSError, ValueError):
        return ""


def find_pystarlight(roots, date=None, number=None, name=None, limit=200):
    """PyStarLight analyses (*.event.json) under the folders roots (symbolic links not followed: e.g. a link to the
    recordings on an external drive), newest first; with date / number / name only those of that day (or the day
    before or after) and asteroid. Returns [(path, object, date)]."""
    out = []
    want_days = set()
    d0 = _parse_utc(date) if date else None
    if d0:
        want_days = {f"{d0 + timedelta(days=k):%Y-%m-%d}" for k in (-1, 0, 1)}
    for root in roots:
        if not root or not os.path.isdir(root):
            continue
        for base, dirs, files in os.walk(root):
            dirs[:] = [x for x in dirs if not x.startswith(".")]
            for fn in files:
                if not fn.endswith(".event.json"):
                    continue
                p = os.path.join(base, fn)
                try:
                    with open(p, encoding="utf-8") as fh:
                        js = json.load(fh)
                except (OSError, ValueError):
                    continue
                obj = str(js.get("object") or "")
                day = str((js.get("recording") or {}).get("date") or "")
                if want_days and day not in want_days:
                    continue
                if number and not re.search(rf"\(\s*{re.escape(str(number))}\s*\)", obj):
                    if not (name and name.lower() in obj.lower()):
                        continue
                elif name and not number and name.lower() not in obj.lower():
                    continue
                out.append((p, obj, day))
                if len(out) >= limit:
                    break
    return sorted(out, key=lambda x: (x[2], x[0]), reverse=True)


# ------------------------------------------------------------------------------------------- IOTA-ES report form
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _dms(deg, width):
    """+46 59 33.000 / +009 38 24.299 (width 2 or 3 for the degrees)."""
    v = _num(deg)
    if v == "":
        return ""
    s = "+" if v >= 0 else "-"
    v = abs(v)
    d = int(v)
    m = int((v - d) * 60)
    sec = (v - d - m / 60) * 3600
    if sec >= 59.9995:
        sec, m = 0.0, m + 1
    if m >= 60:
        m, d = 0, d + 1
    return f"{s}{d:0{width}d} {m:02d} {sec:06.3f}"


def _from_dms(text):
    m = re.fullmatch(r"\s*([+-]?)(\d+)\s+(\d+)\s+(\d+(?:\.\d*)?)\s*", str(text or ""))
    if not m:
        return _num(text)
    v = int(m.group(2)) + int(m.group(3)) / 60 + float(m.group(4)) / 3600
    return round(-v if m.group(1) == "-" else v, 7)


def _form_date(date, hms):
    d = _parse_utc(date)
    if d is None:
        return ""
    return f"{d.day} {MONTHS[d.month - 1]} {d.year}" + (f", {str(hms)[:8]}" if hms else "")


def _code(table, v):
    return v if v in table else ""


def header(sources=()):
    """The form's first line: the form version, PySyzygos and the programs the data came from (provisional, until
    the receiving side has a rule): '... REPORT FORM 2.03 - PySyzygos 1.5.2; data from PyStarLight 0.1.0'."""
    src = [x for x in dict.fromkeys(sources) if x]
    return f"#{FORM} - PySyzygos {__version__}" + (f"; data from {', '.join(src)}" if src else "")


def origin_text(origin):
    """'recording: lat, lon, ...; analysis: d_time, ...; edited: ...' (the provenance line of the extras)."""
    by = {}
    for k in KEYS:
        o = (origin or {}).get(k)
        if o:
            by.setdefault(o.split(" ")[0], []).append(k)
    return "; ".join(f"{o}: {', '.join(ks)}" for o, ks in by.items())


def to_iotaes(f, extras=True, origin=None, sources=()):
    """The report as IOTA-ES report form text (version 2.03, the layout of the DVTI+CAM template), for the online
    submission. extras: also PySyzygos' own lines under EXTRA_FIELDS (Gaia DR3 id, personal equation, telescope
    model, focal reducer, more events, where each field came from); off: the template's lines only."""
    g = lambda k: "" if f.get(k) in (None, "") else str(f[k])
    tel = TELESCOPE.get(g("telescope"), "")
    lines = [header(sources), "#Event", f"#Occultation: {g('outcome')}",
             f"#DATE: {_form_date(g('date'), g('predict_time'))}",
             f"#PREDICTTIME: {_form_date(g('date'), g('predict_time'))}",
             f"#STAR: {g('star')}", f"#ASTEROID: {g('asteroid_name')}", f"#Nr: {g('asteroid_number')}",
             "#OBSERVER", f"#Observer1: {g('observer1')}", f"#Observer2: {g('observer2')}",
             f"#moreObs: {g('more_obs')}", f"#E-mail: {g('email')}", f"#Address: {g('address')}",
             "#OBSERVING_STATION", f"#Station: {g('station')}", f"#NearestCity: {g('nearest_city')}",
             f"#Countrycode: {g('country')}", "#Coordinates LAT +/-DD MM SS.S  LON +/-DDD MM SS.S ",
             f"#Latitude: {_dms(f.get('lat'), 2)}", f"#Longitude: {_dms(f.get('lon'), 3)}",
             f"#Altitude: {g('alt_m')}", f"#Notes: {g('station_note')}",
             "#Datum _blank=WGS84 N=NAD1927 E=ED1950 T=Tokyo G=GB1936 *=unspecified, or other",
             f"#Datum: {_code(DATUM, g('datum'))}",
             "#Teleskop _=unstated 1=Refractor 2=Newtonian 3=SCT 4=Dobsonian 5=Binoculars 6=Other 7=None 8=eVscope ",
             f"#Telescope: {_code(TELESCOPE, g('telescope'))}", "#Aperture in cm", f"#Aperture: {g('aperture_cm')}",
             "#FocalLength in cm", f"#FocalLength: {g('focal_cm')}",
             "#ObservingMethod   _=unspecified a=Analogue & digital video b=Digital SLR-camera video c=Photometer "
             "d=Sequential images e=Drift scan f=Visual g=Other ",
             f"#ObservingMethod: {_code(METHOD, g('method'))}", "#Observation", f"#StartObs: {g('start_obs')}",
             "#D D=Main Star d=second Star G=satellite main star g=satellite 2nd star N=ring  M=non detection +time "
             "hh:mm:ss.s",
             f"#D: {g('d_code')}{g('d_time')}" if g("d_time") else f"#D: {g('d_code')}", f"#Acc_D: {g('d_acc')}",
             "#R R=Main Star r=second Star B=satellite main star b=satellite 2nd star N=ring  M=non detection +time "
             "hh:mm:ss.s",
             f"#R: {g('r_code')}{g('r_time')}" if g("r_time") else f"#R: {g('r_code')}", f"#Acc_R: {g('r_acc')}",
             f"#EndObs: {g('end_obs')}", f"#Duration: {g('duration')}", f"#Exp_Time: {g('exp_time')}",
             "#Timesource  _=unspecified a=GPS b=NTP c=Telephone (fixed or mobile) d=Radio time signal e=Internal "
             "clock of recorder f=Stopwatch g=Other",
             f"#Timesource: {_code(TIME_SOURCE, g('time_source'))}", f"#Camera: {g('camera')}",
             f"#Signal/Noise: {g('snr')}", "#Weatherconditions", f"#Wind: {g('wind')}",
             f"#Temperature: {g('temperature')}",
             "#Transparency 1=Clear 2=Fog 3=Thin cloud <2 [mag loss <2 mag.] 4=Thick cloud >2 [mag loss >2 mag. "
             "5=Broken opaque cloud [that is, observed thru gaps in the cloud] 6=Star faint 7=By averted vision",
             f"#Transparency: {_code(TRANSPARENCY, g('transparency'))}",
             "#Stability _=unstated 1=Steady 2=Slight flickering 3=Strong flickering",
             f"#Stability: {_code(STABILITY, g('stability'))}",
             f"#Comments: {' '.join(g('comments').split())}", "#", "#EXTRA_FIELDS",
             f"#Feed: {g('feed')}", f"#MpcObsCode: {g('mpc_code') or '-'}",
             f"#Prediction: {'yes' if g('predict_time') else 'no'}", f"#ProbabilityPercent: {g('probability')}",
             f"#PredictedDurationSec: {g('pred_duration')}", f"#DistanceCentralLineKm: {g('dist_center_km')}",
             f"#PathWidthKm: {g('path_width_km')}", f"#StarMag: {g('star_mag')}", f"#StarAltDeg: {g('star_alt')}",
             f"#StarAzDeg: {g('star_az')}", f"#StarConstellation: {g('constellation')}",
             f"#AsteroidMag: {g('asteroid_mag')}", f"#AsteroidDiameterKm: {g('asteroid_diam_km')}",
             f"#CombinedMag: {g('combined_mag')}", f"#DeltaMag: {g('delta_mag')}", f"#Moon: {g('moon')}",
             f"#TelescopeType: {tel if g('telescope') else ''}", f"#MountModel: {g('mount')}"]
    if extras:
        lines += [f"#TelescopeModel: {g('telescope_text')}", f"#FocalReducer: {g('reducer')}",
                  f"#PersonalEquationSec: {g('pe_s')}", f"#GaiaDR3: {g('gaia_id')}"]
        lines += [f"#MoreEvents: {ln.strip()}" for ln in g("extra_events").splitlines() if ln.strip()]
        if origin:
            lines.append(f"#DataFrom: {origin_text(origin)}")
    return "\n".join(lines) + "\n"


IOTAES_KEYS = {"Occultation": "outcome", "STAR": "star", "ASTEROID": "asteroid_name", "Nr": "asteroid_number",
               "Observer1": "observer1", "Observer2": "observer2", "moreObs": "more_obs", "E-mail": "email",
               "Address": "address", "Station": "station", "NearestCity": "nearest_city", "Countrycode": "country",
               "Altitude": "alt_m", "Datum": "datum", "Telescope": "telescope", "Aperture": "aperture_cm",
               "FocalLength": "focal_cm", "ObservingMethod": "method", "StartObs": "start_obs",
               "Acc_D": "d_acc", "Acc_R": "r_acc", "EndObs": "end_obs", "Duration": "duration",
               "Exp_Time": "exp_time", "Timesource": "time_source", "Camera": "camera", "Signal/Noise": "snr",
               "Wind": "wind", "Temperature": "temperature", "Transparency": "transparency",
               "Stability": "stability", "Comments": "comments", "Feed": "feed", "MpcObsCode": "mpc_code",
               "ProbabilityPercent": "probability", "PredictedDurationSec": "pred_duration",
               "DistanceCentralLineKm": "dist_center_km", "PathWidthKm": "path_width_km", "StarMag": "star_mag",
               "StarAltDeg": "star_alt", "StarAzDeg": "star_az", "StarConstellation": "constellation",
               "AsteroidMag": "asteroid_mag", "AsteroidDiameterKm": "asteroid_diam_km",
               "CombinedMag": "combined_mag", "DeltaMag": "delta_mag", "Moon": "moon", "MountModel": "mount",
               "TelescopeModel": "telescope_text", "FocalReducer": "reducer",
               "PersonalEquationSec": "pe_s", "GaiaDR3": "gaia_id"}


def from_iotaes(text):
    """Report fields from an IOTA-ES report form text ('#Key: value' lines; the DVTI+CAM template or ours)."""
    f, extra = {}, []
    for ln in str(text).splitlines():
        m = re.match(r"^#\s*([A-Za-z0-9_/\-]+):\s?(.*)$", ln.rstrip())
        if not m:
            continue
        k, v = m.group(1), m.group(2).strip()
        if k in ("DATE", "PREDICTTIME"):
            mm = re.match(r"(\d{1,2}) (\w{3}) (\d{4})(?:, (\d\d:\d\d:\d\d(?:\.\d*)?))?", v)
            if mm and mm.group(2) in MONTHS:
                f["date"] = f"{mm.group(3)}-{MONTHS.index(mm.group(2)) + 1:02d}-{int(mm.group(1)):02d}"
                if k == "PREDICTTIME" and mm.group(4):
                    f["predict_time"] = mm.group(4)
        elif k in ("Latitude", "Longitude"):
            f["lat" if k == "Latitude" else "lon"] = _from_dms(v)
        elif k in ("D", "R"):
            mm = re.match(r"^([A-Za-z]?)\s*(\d.*)?$", v)
            if mm:
                side = k.lower()
                f[f"{side}_code"], f[f"{side}_time"] = mm.group(1) or "", (mm.group(2) or "").strip()
        elif k == "MoreEvents":
            extra.append(v)
        elif k == "Notes":
            f["station_note"] = v
        elif k in IOTAES_KEYS:
            f[IOTAES_KEYS[k]] = v
    if extra:
        f["extra_events"] = "\n".join(extra)
    if f.get("mpc_code") == "-":
        f["mpc_code"] = ""
    return f


# ------------------------------------------------------------------------------------------- saved reports
def event_key(f):
    """'<asteroid>_<YYYYMMDDTHHMM>' as the favorites' keys (number, else the name without spaces)."""
    tid = str(f.get("asteroid_number") or "").strip() or re.sub(r"\W+", "_", str(f.get("asteroid_name") or "x"))
    hm = (seconds_of_day(f.get("predict_time")) or 0) // 60
    day = str(f.get("date") or "0000-00-00").replace("-", "")
    return f"{tid}_{day}T{int(hm // 60):02d}{int(hm % 60):02d}"


def _slug(text):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", str(text or "").strip()).strip("._") or "report"


def save(fields, folder=DIR, source=None, imports=(), origin=None):
    """Save a report: observations/<event key>/<station or observer>.json (atomic); origin: {field: where it came
    from} (from_pystarlight; 'edited' after a change by hand). Returns the path."""
    f = {k: fields.get(k, "") for k in KEYS}
    _duration(f) if not f.get("duration") else None
    key = event_key(f)
    d = os.path.join(folder, key)
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, _slug(f.get("station") or f.get("observer1")) + ".json")
    old = load(p) if os.path.isfile(p) else {}
    rec = dict(key=key, version=__version__, saved=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
               created=old.get("created") or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
               source=source or old.get("source") or {}, imports=list(old.get("imports", [])) + list(imports),
               origin={**old.get("origin", {}), **(origin or {})}, fields=f)
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(rec, fh, indent=1)
    os.replace(tmp, p)
    return p


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def saved(folder=DIR):
    """All saved reports, newest event first: [dict(path, key, station, outcome, date, asteroid, saved)]."""
    out = []
    for p in glob.glob(os.path.join(glob.escape(folder), "*", "*.json")):
        try:
            r = load(p)
        except (OSError, ValueError):
            continue
        f = r.get("fields") or {}
        out.append(dict(path=p, key=r.get("key", ""), station=f.get("station") or f.get("observer1") or "",
                        outcome=f.get("outcome", ""), date=f.get("date", ""), saved=r.get("saved", ""),
                        asteroid=" ".join(x for x in (f.get("asteroid_number"), f.get("asteroid_name")) if x)))
    return sorted(out, key=lambda x: (x["date"], x["key"]), reverse=True)


def missing(f):
    """What the report still lacks before a submission: [labels]."""
    need = ["outcome", "asteroid_name", "star", "date", "observer1", "lat", "lon", "alt_m", "method",
            "time_source", "start_obs", "end_obs"]
    if f.get("outcome") == "POSITIVE":
        need += ["d_time", "d_acc", "r_time", "r_acc"]
    labels = {k: lab for k, lab, *_ in FIELDS}
    return [labels[k] for k in need if str(f.get(k) if f.get(k) is not None else "").strip() == ""]


# ------------------------------------------------------------------------------------------- inbox (PyStarLight)
INBOX = "inbox"
INBOX_MAX_BYTES = 20_000_000


def inbox_dir(folder=DIR):
    return os.path.join(folder, INBOX)


def store_analysis(js, folder=DIR):
    """Keep an analysis sent by PyStarLight (its event.json as a dict) in observations/inbox/ (atomic). Raises
    ValueError if it is not one. Returns the path."""
    if not isinstance(js, dict) or not (js.get("step_fit") is not None or js.get("recording") is not None):
        raise ValueError("not a PyStarLight analysis (no step_fit / recording)")
    d = inbox_dir(folder)
    os.makedirs(d, exist_ok=True)
    stamp = re.sub(r"\D", "", str(js.get("created_utc") or datetime.now(timezone.utc).isoformat()))[:14]
    movie = os.path.splitext(os.path.basename(str(js.get("movie") or "analysis")))[0]
    p = os.path.join(d, f"{stamp}_{_slug(movie)}.event.json")
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(js, fh, indent=1)
    os.replace(tmp, p)
    return p


def inbox(folder=DIR):
    """Analyses in the inbox, newest first: [dict(path, object, date, software, received)]."""
    out = []
    for p in glob.glob(os.path.join(glob.escape(inbox_dir(folder)), "*.event.json")):
        try:
            js = load(p)
        except (OSError, ValueError):
            continue
        out.append(dict(path=p, object=str(js.get("object") or ""), date=str((js.get("recording") or {}).get("date")
                                                                             or ""),
                        software=str(js.get("software") or ""),
                        received=datetime.fromtimestamp(os.path.getmtime(p), timezone.utc).strftime("%Y-%m-%d %H:%M")))
    return sorted(out, key=lambda x: x["received"], reverse=True)


def matching(fields, entries):
    """The favorites entries (favorites.load(), a list's entries) of the same asteroid and night as these report
    fields (number, else name; event date within a day): the event an analysis belongs to."""
    num, name = str(fields.get("asteroid_number") or ""), str(fields.get("asteroid_name") or "").lower()
    d = _parse_utc(fields.get("date"))
    out = []
    for e in entries:
        r = e.get("record") or {}
        tid = str(r.get("target_id") or "").strip()
        same = (num and tid == num) or (not num and name and name in str(r.get("target_name") or "").lower())
        t = _parse_utc(r.get("best_utc"))
        if same and (d is None or (t is not None and abs((t.date() - d.date()).days) <= 1)):
            out.append(e)
    return out


# ------------------------------------------------------------------------------------------- local API handshake
# The observation GUI writes, at every start, a connection file in the user's PySyzygos settings folder (beside the
# data-folder setting, home.POINTER): url, inbox and a key made at the first start. PyStarLight on this computer reads
# it and sends its analyses with that key; nothing to copy by hand. Readable by the user only.
API_FILE = "observation_api.json"


def api_file():
    from pysyzygos import home
    return os.path.join(home.config_dir(), API_FILE)


def api_setup(url, inbox, data_folder, path=None):
    """Write (or refresh) the connection file; the key is made once and kept. Returns its content."""
    path = path or api_file()
    try:
        with open(path, encoding="utf-8") as fh:
            old = json.load(fh)
    except (OSError, ValueError):
        old = {}
    rec = dict(app="PySyzygos observation GUI", version=__version__, url=url, send=url.rstrip("/") + "/api/obs/v1/analysis",
               inbox=os.path.abspath(inbox), data_folder=os.path.abspath(data_folder),
               token=old.get("token") or "pyobs_" + secrets.token_urlsafe(32),
               header="Authorization: Bearer <token>",
               written=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(rec, fh, indent=1)
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, path)
    return rec


def api_key_ok(headers_authorization, path=None):
    """True if 'Bearer <key>' is the key of the connection file."""
    try:
        with open(path or api_file(), encoding="utf-8") as fh:
            key = json.load(fh).get("token") or ""
    except (OSError, ValueError):
        return False
    a = str(headers_authorization or "")
    return bool(key) and a.lower().startswith("bearer ") and hmac.compare_digest(a[7:].strip(), key)
