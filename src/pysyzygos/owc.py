"""owc.py - look up events in OccultWatcher Cloud (OWC): the prediction feeds (tags such as IBEROC) and the
observers who signed up (stations). On by default since 1.3.3 (config `owc_feeds`, before: `owc_lookup`, off): the
"Check OWC Feeds" button in the GUI's Results and Favorites tabs.

It uses the interface behind OWC's public event pages (no login; undocumented, so it can change): per event one
search by asteroid number and date, `events/?astNo=&dt=&bf=`, and one detail request, `event/<id>`. The OWC event is
matched by the star's Gaia DR3 id, else by time. Requests go one at a time with a pause, name PySyzygos in the user
agent, and run only when the user clicks the button. Results are kept in <data folder>/owc_cache.json (shown in
the report and favorites tables, linked to the OWC event page). Standard library only.
"""
from pysyzygos.version import __version__, __url__
from pysyzygos import net                      # https with certifi's certificate authorities
from pysyzygos import urls as U
import json, os, tempfile, time, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timezone

CACHE = "owc_cache.json"
PAUSE_S = 1.0                     # between requests: gentle on OWC's server
TIME_TOL_MIN = 10.0               # a match by time only: OWC's central time within this of ours (no Gaia id)
SEARCH_TOL_MIN = 120.0            # candidates looked at in detail
UA = f"PySyzygos/{__version__} (+{__url__})"
_last = [0.0]


def _get(url, timeout=20):
    """JSON from url (one polite request)."""
    wait = PAUSE_S - (time.time() - _last[0])
    if wait > 0:
        time.sleep(wait)
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with net.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as ex:                         # name the request: which one failed, and how
        raise OSError(f"HTTP {ex.code} {ex.reason} for {url}") from None
    except urllib.error.URLError as ex:
        raise OSError(f"{ex.reason} for {url}") from None
    finally:
        _last[0] = time.time()


def search(ast_no, date, buffer_days=1):
    """OWC events of an asteroid within date +/- buffer_days (list of dicts: id, time, star, tags, rank, ...)."""
    q = urllib.parse.urlencode({"astNo": int(ast_no), "dt": date, "bf": int(buffer_days)})
    return _get(f"{U.URL_OWC_API}/events/?{q}") or []


def event(event_id):
    """One OWC event in detail (tags, stations, gaia, predictions, ...)."""
    return _get(f"{U.URL_OWC_API}/event/{urllib.parse.quote(str(event_id), safe='')}")


def _owc_time(text):
    """'2026-Oct-11, 22:51:08' -> aware UTC datetime, or None."""
    try:
        return datetime.strptime(str(text).replace(",", "").strip(), "%Y-%b-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _utc(text):
    base = str(text).strip().rstrip("Z").split(".")[0]
    return datetime.fromisoformat(base).replace(tzinfo=timezone.utc)


def summary(detail, match):
    """The cache entry of an OWC event: id, page url, tags, stations (observer, signed distance from the centre line
    in km, commitment), match ('star' or 'time')."""
    st = [dict(obs=s.get("obs") or "", dist=s.get("dist"), cmtmt=s.get("cmtmt") or "", report=bool(s.get("report")))
          for s in (detail.get("stations") or [])]
    return dict(id=detail.get("id"), url=U.URL_OWC_EVENT_PAGE + str(detail.get("id")), time=detail.get("time"),
                tags=[t.get("name") for t in (detail.get("tags") or []) if t.get("name")], stations=st, match=match)


def lookup(record):
    """The OWC event for a hit_log record (target_id, best_utc, star): summary(...) or None (not on OWC)."""
    when = _utc(record["best_utc"])
    found = search(record["target_id"], when.strftime("%Y-%m-%d"), 1)
    cands = []
    for e in found:
        t = _owc_time(e.get("time"))
        if t is not None and abs((t - when).total_seconds()) <= SEARCH_TOL_MIN * 60:
            cands.append((abs((t - when).total_seconds()), e))
    cands.sort(key=lambda x: x[0])
    star = str(record.get("star", "")).split(".")[0]
    first = None
    for dt_s, e in cands[:3]:
        d = event(e["id"])
        if str(((d or {}).get("gaia") or {}).get("id") or "") == star and star:
            return summary(d, "star")
        if first is None and dt_s <= TIME_TOL_MIN * 60:
            first = d
    return summary(first, "time") if first else None


def key(record):
    return f"{str(record['target_id']).strip()}_{str(record['best_utc'])[:16]}"


def load(folder="."):
    try:
        with open(os.path.join(folder, CACHE), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def check(records, folder=".", progress=None):
    """Look up the records in OWC and save the results in the cache (also 'not on OWC'). Returns (found, checked,
    errors). progress(i, n): optional callback."""
    cache, found, errors = load(folder), 0, []
    for i, r in enumerate(records, 1):
        try:
            res = lookup(r)
        except Exception as ex:                                   # network trouble: keep going, report it
            errors.append(f"{r.get('target_id')} {str(r.get('best_utc'))[:16]}: {str(ex)[:300]}")
            continue
        cache[key(r)] = dict(checked=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"), event=res)
        found += res is not None
        if progress:
            progress(i, len(records))
    fd, tmp = tempfile.mkstemp(dir=os.path.abspath(folder), suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=1)
    os.replace(tmp, os.path.join(folder, CACHE))
    return found, len(records) - len(errors), errors


def info(target_id, best_utc, cache):
    """(label, hover text, url) for the tables, or None if not checked or not on OWC."""
    entry = cache.get(f"{str(target_id).strip()}_{str(best_utc)[:16]}")
    ev = (entry or {}).get("event")
    if not ev:
        return None
    n = len(ev["stations"])
    label = "OWC" + (" " + " ".join(ev["tags"]) if ev["tags"] else "") + f" · {n} station{'s' if n != 1 else ''}"
    lines = [f"OccultWatcher Cloud event {ev['id']} ({ev.get('time') or ''}), checked {entry['checked'][:16]} UTC"
             + ("" if ev.get("match") == "star" else "; matched by time only")]
    for s in ev["stations"]:
        d = f"{s['dist']:+.1f} km" if isinstance(s.get("dist"), (int, float)) else "?"
        lines.append(f"{s['obs']}: {d} from the centre line, commitment {s['cmtmt'] or '?'}"
                     + (", reported" if s.get("report") else ""))
    return label, "\n".join(lines), ev["url"]
