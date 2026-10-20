"""occultations.py - what earlier occultations measured of an asteroid, from NASA's archive of observed occultations
(PDS Small Bodies Node, "Small Bodies Occultations", Herald, Dunham et al.; doi:10.26033/ehqs-jp27). Reference
information only: it is shown with the asteroid's size data (favorites panel) and does not change the predictions.

data/occultations_pds.json is a compact extract, per numbered asteroid: number of events and years, the event
quality counts, the best measured profile (fitted ellipse of the best-quality event whose size was not assumed) and
the volume-equivalent diameter from fitting all its events to shape models (DAMIT / ISAM), where the archive has
one. Not kept: the chord timings and the observers' names and positions.

Event quality codes of the archive (bundle_description.txt):
  0 no reliable position or size, 1 astrometry only (no reliable size), 2 limits on size but no shape,
  3 reliable size (can fit shape models), 4 resolution better than shape models.

Refresh after a new archive version (about yearly; maintainers, then commit the JSON):
    python -m pysyzygos.occultations build <unpacked bundle folder or .zip>
"""
from pysyzygos.version import __version__
from pysyzygos import urls as U
import csv, io, json, os, sys, zipfile

FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "occultations_pds.json")
QUALITY = {0: "unreliable", 1: "astrometry only", 2: "limits on size", 3: "reliable size",
           4: "better than shape models", 5: "short event, no astrometry",       # 5, 6: Occult's archive (add-on)
           6: "one star of a double"}
_DATA = None


def _tables(src):
    """{'summary': rows, 'diameters': rows} from the bundle folder or its zip (the newest *_<date>.psv tables)."""
    if zipfile.is_zipfile(src):
        with zipfile.ZipFile(src) as z:
            blobs = {os.path.basename(n): n for n in z.namelist() if n.endswith(".psv")}
            blobs = {b: z.read(n) for b, n in blobs.items()
                     if b.startswith(("AsteroidSummary_", "AsteroidDiameters_"))}
    else:
        blobs = {}
        for root, _, fs in os.walk(src):
            for f in fs:
                if f.endswith(".psv") and f.startswith(("AsteroidSummary_", "AsteroidDiameters_")):
                    with open(os.path.join(root, f), "rb") as fh:
                        blobs[f] = fh.read()
    out = {}
    for key, prefix in (("summary", "AsteroidSummary_"), ("diameters", "AsteroidDiameters_")):
        n = sorted(x for x in blobs if x.startswith(prefix))
        if not n:
            raise ValueError(f"{prefix}*.psv not found in {src}")
        text = blobs[n[-1]].decode("utf-8", errors="replace")
        out[key], out[key + "_file"] = list(csv.DictReader(io.StringIO(text), delimiter="|")), n[-1]
    return out


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def extract(tables):
    """The compact per-asteroid dict (see the module doc) from the archive tables."""
    ast = {}
    for r in tables["summary"]:
        num = (r.get("AST_DESIG") or "").strip()
        if not num.isdigit():
            continue                                          # comets and unnamed rows
        a = ast.setdefault(num, dict(name=(r.get("AST_NAME") or "").strip(), n=0, first=None, last=None,
                                     q={}, best=None))
        date, q = (r.get("OBS_DATE") or "").strip(), int(_f(r.get("FIT_QUAL_CODE")) or 0)
        a["n"] += 1
        a["first"] = min(a["first"] or date, date)
        a["last"] = max(a["last"] or date, date)
        a["q"][str(q)] = a["q"].get(str(q), 0) + 1
        major, minor = _f(r.get("MAJOR_AXIS")), _f(r.get("MINOR_AXIS"))
        if q >= 2 and r.get("USED_ASSUMED_DIA_FLAG", "").strip() == "0" and major and minor:
            cand = dict(date=date, q=q, major=major, minor=minor, pa=_f(r.get("MAJOR_AXIS_PA")),
                        major_u=_f(r.get("MAJOR_AXIS_UNCERT")), minor_u=_f(r.get("MINOR_AXIS_UNCERT")))
            b = a["best"]
            if b is None or (q, date) > (b["q"], b["date"]):      # best quality, then the latest
                a["best"] = cand
    for r in tables["diameters"]:
        num = (r.get("Designation") or "").strip()
        d = _f(r.get("Diameter_Nominal"))
        if num.isdigit() and d:
            events = sum(int(_f(r.get(f"Events_{k}")) or 0) for k in range(1, 5))
            models = [f"{r.get(f'Model_Source_{k}')} {r.get(f'Model_Number_{k}')}" for k in range(1, 5)
                      if (r.get(f"Model_Source_{k}") or "").strip()]
            ast.setdefault(num, dict(name=(r.get("Name") or "").strip(), n=0, first=None, last=None, q={},
                                     best=None))["shape_dia"] = dict(d=d, u=_f(r.get("Uncert")), events=events,
                                                                     models=models)
    dates = [a["last"] for a in ast.values() if a["last"]]
    meta = dict(source="NASA PDS Small Bodies Node, Small Bodies Occultations (Herald, Dunham et al.)",
                doi="10.26033/ehqs-jp27", url=U.URL_PDS_OCCULTATIONS_PAGE, tables=[tables["summary_file"],
                tables["diameters_file"]], events_until=max(dates) if dates else None, asteroids=len(ast))
    return dict(meta=meta, asteroids=ast)


def build(src, out=FILE):
    """Write the compact JSON from an archive folder or zip. Returns the number of asteroids."""
    data = extract(_tables(src))
    tmp = out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, separators=(",", ":"))
    os.replace(tmp, out)
    return data["meta"]["asteroids"]


def load(path=None):
    """The archive extract: the Occult data add-on's (occultdata.py, updated by IOTA continuously) when installed,
    else the PDS extract shipped in data/. path: a given extract (tests)."""
    global _DATA
    if _DATA is None:
        if path is None:
            try:
                from pysyzygos import occultdata
                path = occultdata.observations_file() or FILE
            except Exception:                                     # no data folder (tests, early start-up)
                path = FILE
        try:
            with open(path, encoding="utf-8") as f:
                _DATA = json.load(f)
        except (OSError, ValueError):
            _DATA = dict(meta={}, asteroids={})
    return _DATA


def lookup(number):
    """The archive's entry for an asteroid number, or None."""
    return load()["asteroids"].get(str(number).strip())


def text(number):
    """One line for the asteroid's data: 'Occultations (PDS, to 2023-12): 12 events 1983-2021, 3 reliable size;
    shape-model diameter 107.8 +- 5.6 km (8 events); best profile 2019-03-02: 112.0 x 98.5 km (reliable size)'."""
    data = load()
    if not data["asteroids"]:
        return ""
    until = (data["meta"].get("events_until") or "")[:10 if data["meta"].get("label") else 7]
    a = lookup(number)
    head = f"Occultations ({data['meta'].get('label', 'NASA PDS archive')}, to {until})"
    if not a or not a["n"]:
        return f"{head}: none observed yet" + (f"; shape-model diameter {a['shape_dia']['d']:g} km" if a and
                                              a.get("shape_dia") else "")
    years = a["first"][:4] if a["first"][:4] == a["last"][:4] else f"{a['first'][:4]}-{a['last'][:4]}"
    qs = ", ".join(f"{n} {QUALITY.get(int(q), 'code ' + q)}" for q, n in sorted(a["q"].items(), key=lambda x: -int(x[0])))
    parts = [f"{head}: {a['n']} event{'s' if a['n'] > 1 else ''} {years} ({qs})"]
    s = a.get("shape_dia")
    if s:
        parts.append(f"shape-model diameter {s['d']:g}" + (f" ± {s['u']:g}" if s.get("u") else "")
                     + f" km ({s['events']} event{'s' if s['events'] != 1 else ''}" + (f", {s['method']})" if s.get("method") else ")"))
    b = a.get("best")
    if b:
        parts.append(f"best profile {b['date']}: {b['major']:g} × {b['minor']:g} km "
                     f"({QUALITY.get(b['q'], 'code ' + str(b['q']))})")
    return "; ".join(parts)


def main():
    if len(sys.argv) < 3 or sys.argv[1] != "build":
        sys.exit(__doc__)
    n = build(sys.argv[2])
    print(f"{n} asteroids -> {FILE}  (events until {load()['meta'].get('events_until')})")


if __name__ == "__main__":
    sys.exit(main())
