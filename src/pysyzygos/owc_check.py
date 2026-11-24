"""owc_check.py - regression check against an OWC (Occult Watcher Cloud) search result.

Paste an OWC search result (the page text: the "Search Results for filter ..." line and the event table) into
owc_reference.txt (private, not in git: it names your site). This script reads the events and the search settings
from it (distance from shadow, StarMag, MinDur, Aperture, DetectionFrames, MinStarAltitude), runs search.py
(corridor mode) for those asteroids over the events' dates at your site (sites.py), then matches every OWC event to
our hits and checks: time within 10 s, magnitude drop within 0.25 mag, maximum duration within 10 %.
pysyzygos_config.py is not changed: the settings override it for this run only. Hits go to owc_check_hits.csv, no maps.

    pysyzygos owc-check                 # search + compare
    pysyzygos owc-check --compare-only  # compare an existing owc_check_hits.csv
    pysyzygos owc-check --ref other_owc_result.txt
    pysyzygos owc-check --sea-level     # our side at elevation 0, as OWC online (it ignores the site height)
    pysyzygos owc-check --compare-only --hits saved_hits.csv --markdown list.md   # full list as a Markdown table

Duration = diameter / shadow speed. The report shows our diameter and the one OWC's duration implies (OWC duration x our
speed); when only the diameters differ, the result is "ok, size differs", not a failure. Drops above DROP_TOTAL mag
are not compared (they differ only by the asteroid's own magnitude estimate).
"""
from pysyzygos.version import __version__
import argparse, os, re, runpy, sys
import pandas as pd

REF = "owc_reference.txt"
OUT = "owc_check_hits.csv"
TOL_T, TOL_DROP, TOL_DUR = 10.0, 0.25, 0.10
WARN_T = 1.5              # Markdown list: a match with a larger time difference is highlighted
DROP_TOTAL = 5.0          # drops above this are total occultations either way: not compared
EVENT = re.compile(r"\((\d+)\)\s*([^\t]*)\t\s*(\d{4}-[A-Za-z]{3}-\d{2}),\s*(\d{2}:\d{2}:\d{2})"
                   r"\s*(?:\u263c\s*(-?\d+(?:\.\d+)?)\s*\u00b0?)?"           # twilight events: "\u263c -5\u00b0" = Sun altitude
                   r"\s*\t\s*([\d.]+)\s*\t\s*([\d.]+)\s*\t\s*([\d.]+)\s*\t\s*(\d+)")


def _clean_name(text):
    """'2000 SB350 NALowMagMDMattson' -> '2000 SB350', '1999 VT109 IBEROC' -> '1999 VT109': drop OWC's trailing tag words
    (capitals run into lowercase, or all capitals)."""
    words = text.split()
    while words and len(words) > 1 and re.match(r"^(?:[A-Z]{2,}[A-Za-z]*[a-z]|[A-Z]{4,})[A-Za-z]*$", words[-1]):
        words.pop()
    return " ".join(words)


def read_owc(path):
    """(events DataFrame, settings dict) from an OWC search result pasted as text."""
    text = open(path, encoding="utf-8").read()
    rows = [dict(target_id=int(m[1]), name=_clean_name(m[2]),
                 event_utc=pd.Timestamp(f"{m[3]} {m[4]}").strftime("%Y-%m-%dT%H:%M:%S"),
                 sun_alt_deg=float(m[5]) if m[5] else float("nan"), star_mag_v=float(m[6]),
                 mag_drop_v=float(m[7]), max_dur_s=float(m[8]), altitude_deg=float(m[9])) for m in EVENT.finditer(text)]
    if not rows:
        sys.exit(f"no OWC events found in {path}")
    ref = pd.DataFrame(rows)
    f = re.search(r"Search Results for filter(.*)", text)
    f = f[1] if f else ""
    num = lambda pat, d: float(m[1]) if (m := re.search(pat, f, re.I)) else d
    t0 = pd.Timestamp(ref.event_utc.min()).normalize() - pd.Timedelta(days=1)
    t1 = pd.Timestamp(ref.event_utc.max()).normalize() + pd.Timedelta(days=2)
    settings = dict(max_shadow_dist=num(r"([\d.]+)\s*km from shadow", 20.0), MAG_MIN=num(r"StarMag:\s*([\d.]+)", 15.0),
                    pick_min_dur_s=num(r"MinDur:\s*([\d.]+)", 0.4), pick_aperture_cm=num(r"Aperture:\s*([\d.]+)", 25.0),
                    pick_frames=int(num(r"DetectionFrames:\s*(\d+)", 4)), MIN_STAR_ALT=num(r"MinStarAltitude:\s*([\d.]+)", 10.0),
                    horizon_limit=False,     # OWC's flat MinStarAltitude, like for like
                    ct=t0.strftime("%Y-%m-%dT%H:%M:%S"), days=(t1 - t0).days, write_maps=False, search_mode="corridor")
    if ref.sun_alt_deg.notna().any():               # OWC lists twilight events: allow the Sun up to the brightest one
        settings["MAX_SUN_ALT"] = float(ref.sun_alt_deg.max()) + 1.0
    return ref, settings


def run(ref, settings):
    from pysyzygos import config
    for k, v in settings.items():
        setattr(config, k, v)
    config.targets = [str(t) for t in ref.target_id]
    config.targets_source = "list"
    config.hits_output_cvs_file = OUT
    config.results_db = "owc_check.db"                  # its own results database: never mixed with your results
    config.results_new_series = True
    if os.path.isfile(OUT):
        os.remove(OUT)
    runpy.run_module("pysyzygos.search", run_name="__main__", alter_sys=True)


def compare(ref, hits_csv=OUT, markdown=None):
    hits = pd.read_csv(hits_csv) if os.path.isfile(hits_csv) else pd.DataFrame(columns=["target_id", "best_utc"])
    hits["t"] = pd.to_datetime(hits["best_utc"])
    rows, used = [], set()
    for r in ref.itertuples():
        h = hits[hits.target_id == r.target_id]
        dt = (h.t - pd.Timestamp(r.event_utc)).dt.total_seconds()
        if len(h) == 0 or dt.abs().min() > 600:
            rows.append(dict(target=r.target_id, name=r.name, owc_utc=r.event_utc, star_V=r.star_mag_v,
                             owc_drop=r.mag_drop_v, owc_dur=r.max_dur_s, result="NOT FOUND"))
            continue
        i = dt.abs().idxmin()
        used.add(i)
        x = h.loc[i]
        ok_t = abs(dt[i]) <= TOL_T
        ok_drop = abs(x.mag_drop - r.mag_drop_v) <= TOL_DROP or min(x.mag_drop, r.mag_drop_v) > DROP_TOTAL
        ok_dur = abs(x.max_duration_s / r.max_dur_s - 1) <= TOL_DUR
        d_owc = r.max_dur_s * x.speed_kms                                  # diameter OWC's duration implies at our speed
        rows.append(dict(target=r.target_id, name=r.name, owc_utc=r.event_utc, dt_s=round(dt[i], 1),
                         star_G=round(x.mag, 2), star_V=r.star_mag_v,
                         drop=round(x.mag_drop, 2), owc_drop=r.mag_drop_v,
                         dur_s=round(x.max_duration_s, 2), owc_dur=r.max_dur_s,
                         miss_km=round(x.min_distance, 1), D_km=round(2 * x.r_km, 2), D_owc_km=round(d_owc, 2),
                         size_src="H+albedo" if str(x.size_source).startswith("H only") else str(x.size_source)[:14],
                         result="ok" if ok_t and ok_drop and ok_dur else
                         ("ok, size differs" if ok_t and ok_drop else
                          "FAIL " + ",".join(n for n, ok in (("time", ok_t), ("drop", ok_drop)) if not ok)
                          + (" (+size)" if not ok_dur else ""))))
    tab = pd.DataFrame(rows)
    with pd.option_context("display.width", 250, "display.max_columns", 30):
        print(tab.to_string(index=False))
    extra = hits.drop(index=list(used))
    if len(extra):
        print(f"\nOur hits not in the OWC list ({len(extra)}):")
        print(extra[["target_id", "best_utc", "mag", "mag_drop", "max_duration_s", "min_distance"]].to_string(index=False))
    n_ok = tab.result.str.startswith("ok").sum()
    n_size = (tab.result == "ok, size differs").sum()
    print(f"\n{n_ok}/{len(tab)} OWC events match (time {TOL_T:g} s, drop {TOL_DROP} mag below {DROP_TOTAL:g}); "
          f"{n_size} of them with a different diameter (duration off > {TOL_DUR:.0%})")
    if markdown:
        with open(markdown, "w", encoding="utf-8") as f:
            f.write(to_markdown(tab, extra))
        print(f"full list -> {markdown}")
    return n_ok == len(tab)


def to_markdown(tab, extra):
    """The full comparison as a Markdown table, by star magnitude: every OWC event and our extra hits, marked
    ✅ match, 🟠 match with |dt| > WARN_T s, 🔴 OWC event not found or not matching, 🔵 only ours."""
    f = lambda v, nd=2: "" if v is None or pd.isna(v) else f"{v:.{nd}f}"
    rows = []
    for r in tab.to_dict("records"):
        res, dt = r["result"], r.get("dt_s")
        if res.startswith("ok"):
            mark = "🟠" if abs(dt) > WARN_T else "✅"
            text = "match" + (", *size differs*" if res == "ok, size differs" else "")
        else:
            mark, text = "🔴", "**not found**" if res == "NOT FOUND" else f"**{res.lower().replace('fail', 'differs:')}**"
        dts = "" if dt is None or pd.isna(dt) else (f"**{dt:+.1f}**" if abs(dt) > WARN_T else f"{dt:+.1f}")
        mag = r.get("star_G") if r.get("star_G") is not None and not pd.isna(r.get("star_G")) else None
        rows.append((mag if mag is not None else float("nan"), r["star_V"] if "star_V" in r and not pd.isna(r.get("star_V"))
                     else float("nan"),
                     f"| {mark} | ({r['target']}) {r['name']} | {str(r['owc_utc'])[:19].replace('T', ' ')} | {dts} | "
                     f"{f(mag) or f(r.get('star_V')) + ' (OWC)'} | {f(r.get('drop'))} / {f(r.get('owc_drop'))} | {f(r.get('dur_s'))} / "
                     f"{f(r.get('owc_dur'))} | {f(r.get('D_km'))} / {f(r.get('D_owc_km'))} | {f(r.get('miss_km'), 1)} | {text} |"))
    for x in extra.to_dict("records"):
        rows.append((x["mag"], x["mag"],
                     f"| 🔵 | ({x['target_id']}) | {str(x['best_utc'])[:19].replace('T', ' ')} (ours) | | {f(x['mag'])} | "
                     f"{f(x['mag_drop'])} / — | {f(x['max_duration_s'])} / — | {f(2 * x['r_km'])} / — | "
                     f"{f(x['min_distance'], 1)} | **only ours** |"))
    key = lambda t: t[0] if not pd.isna(t[0]) else (t[1] if not pd.isna(t[1]) else 99.0)
    rows.sort(key=key)
    # OWC events we did not find have no G of ours: place them by OWC's magnitude
    head = ("| | Asteroid | OWC time (UT) | Δt (s) | Star G | Drop ours / OWC | Duration ours / OWC (s) | "
            "Diameter ours / OWC-implied (km) | Shadow dist (km) | Result |\n|---|---|---|---:|---:|---|---|---|---:|---|\n")
    return head + "\n".join(t[2] for t in rows) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=f"PySyzygos {__version__}")
    ap.add_argument("--compare-only", action="store_true")
    ap.add_argument("--ref", default=REF, help="OWC search result as text (default owc_reference.txt)")
    ap.add_argument("--hits", default=OUT, help=f"our hits to compare (default {OUT}; with --compare-only e.g. a saved copy)")
    ap.add_argument("--markdown", help="also write the full list (OWC events and our extras, by star magnitude) as Markdown")
    ap.add_argument("--sea-level", action="store_true",
                    help="compute at elevation 0 like OWC online (it ignores the site's height); for high sites")
    a = ap.parse_args()
    ref, settings = read_owc(a.ref)
    if a.sea_level:
        settings["ELE"] = 0.0
        print("site elevation set to 0 m (sea level), as OWC online computes", flush=True)
    print(f"{len(ref)} OWC events, {settings['ct'][:10]} + {settings['days']} d, reach {settings['max_shadow_dist']:g} km, "
          f"G <= {settings['MAG_MIN']:g}, min alt {settings['MIN_STAR_ALT']:g}, {settings['pick_aperture_cm']:g} cm, "
          f"{settings['pick_frames']} frames", flush=True)
    if not a.compare_only:
        run(ref, settings)
    sys.exit(0 if compare(ref, a.hits, a.markdown) else 1)


if __name__ == "__main__":
    sys.exit(main())
