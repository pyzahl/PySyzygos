"""report.py filter bar: each row's filter values (data-f*: mag, duration, drop, altitudes, RUWE, chance in %) and
flags (supplement star, uncertain star, double star, twilight, horizon, size estimated), and the bar and its script
in the page. No SPICE, no network."""
import os, re, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
from pysyzygos import report as R
from pysyzygos.db import filter_to_sql as db_sql

base = dict(tid="99999999", utc="2026-11-01T01:02:03.456", body=False, mag=10.5, dur=1.25, drop=2.0, alt=35.0, sun=-25.0, ruwe=1.2, p_site=0.42,
            sflag="", star_sigma=None, rad=5.0, dhint="", hz=("", None, None), size_src="SBDB diameter")
a = R.filter_attrs(base)
vals = dict(re.findall(r'data-f(\w+)="([^"]*)"', a))
assert vals == dict(time="", mag="10.500", dur="1.250", drop="2.000", alt="35.0", sun="-25.0", ruwe="1.20", chance="42.00", az="",
                    flags="", cls="", sigpw=""), vals
e = dict(base, sflag="RUWE 1.70", star_sigma=8.0, dhint="companion", sun=-8.0, hz=("near", 20.0, 3.0),
         size_src="H only, albedo assumed", ruwe=None, p_site=None)
vals = dict(re.findall(r'data-f(\w+)="([^"]*)"', R.filter_attrs(e)))
assert vals["flags"].split() == ["sup", "unc", "dbl", "twi", "hz", "est"] and vals["ruwe"] == "" and vals["chance"] == "", vals
bar = R.filter_bar()
assert all(f'data-f="{k}"' in bar for k in ("mag", "dur", "drop", "alt", "sun", "ruwe", "chance"))
assert all(f'data-h="{k}"' in bar for k, _ in R.FILTER_FLAGS) and 'data-o="moon"' in bar and 'id="fset"' in bar
assert "/api/filters/save" in R.FILTER_JS and "pyo_filter:" in R.FILTER_JS
assert 'data-t="from"' in bar and 'data-t="to"' in bar and 'type="datetime-local"' in bar     # the time window (UTC)
from datetime import datetime, timezone
t = datetime(2026, 11, 1, 1, 2, 3, tzinfo=timezone.utc)
assert f'data-ftime="{t.timestamp():.0f}"' in R.filter_attrs(dict(base, when=t))
# the CSV downloads keep the page's rows in its order (exports.only_shown with the visible rows' event keys)
from pysyzygos import exports as X
assert 'data-ev="99999999|' in R.filter_attrs(dict(base, utc="2026-11-01T01:02:03.456"))
pairs = [({"n": i}, dict(target_id=t, best_utc=u)) for i, (t, u) in enumerate(
    [("1", "2026-11-01T00:00:00.1"), ("2", "2026-11-02T00:00:00"), ("3", "2026-11-03T00:00:00.9")])]
keys = [R.event_key("3", "2026-11-03T00:00:00.9"), R.event_key("1", "2026-11-01T00:00:00")]
assert [p[0]["n"] for p in X.only_shown(pairs, keys)] == [2, 0]             # shown rows only, in the page's order
assert X.only_shown(pairs, None) == pairs and X.only_shown(pairs, []) == []  # page not readable: all; none shown: none
# horizon clearance: rows carry azimuth and (favorites) site; the page carries the horizons of its sites
a = R.filter_attrs(dict(base, az=123.4, site=dict(name="Hill")))
assert 'data-faz="123.4"' in a and 'data-fsite="Hill"' in a and 'data-f="hzc"' in R.filter_bar()
assert "hzAlt" in R.FILTER_JS and R.horizon_js([], {}).startswith("<script>window.PYO_HZ=")
# event-time hover: start / end estimate (the site's chord inside the shadow, else the center-line duration)
when = datetime(2026, 11, 1, 1, 2, 3, 456000, tzinfo=timezone.utc)
t = R.start_end_text(dict(when=when, dur=2.0, rad=5.0, miss=3.0))          # chord 2 * 4/5 = 1.6 s: +-0.8 s
assert "start \u2248 01:02:02.656, end \u2248 01:02:04.256" in t and "your site" in t, t
t = R.start_end_text(dict(when=when, dur=2.0, rad=5.0, miss=8.0))
assert "01:02:02.456" in t and "01:02:04.456" in t and "outside the shadow" in t, t
assert R.start_end_text(dict(when=when, dur=None, rad=5.0, miss=1.0)) == ""
# OWC's SigPW: path 1-sigma / path width (2 x radius); unknown sigma passes
assert 'data-fsigpw="0.300"' in R.filter_attrs(dict(base, sigma1=3.0, rad=5.0)) and 'data-f="sigpw"' in bar
assert "sigpw:-1" in R.FILTER_JS
assert db_sql({"sigpw": 0.5}) == "(sigma IS NULL OR radius IS NULL OR radius = 0 OR sigma <= 0.5 * 2 * radius)"
# orbit class: rows carry the JPL code, the bar a choice of the pick's groups or one class, the SQL box the same
assert R.class_code({"ast_class": "apo"}) == "APO" and R.class_code({"ast_class": "nan"}) == "" and R.class_code({}) == ""
assert 'data-fcls="TJN"' in R.filter_attrs(dict(base, ccode="TJN")) and 'data-s="cls"' in bar
assert 'value="g:neo"' in bar and 'value="g:other"' in bar and 'value="IEO"' in bar
assert '"neo": ["APO", "AMO", "ATE", "IEO"]' in R.FILTER_JS and "__GROUPS__" not in R.FILTER_JS
from pysyzygos import db
assert db.filter_to_sql({"cls": "g:neo"}) == "(class IS NULL OR class IN ('APO', 'AMO', 'ATE', 'IEO'))"
assert db.filter_to_sql({"cls": "TJN", "mag": 12}) == "mag <= 12 AND (class IS NULL OR class = 'TJN')"
assert db.filter_to_sql({"cls": "g:other"}).startswith("(class IS NULL OR class NOT IN ('MBA'")
assert db.filter_to_sql({"cls": "x'; DROP"}) == ""                      # only known groups or a 3-letter code
# favorites' note: a flag under the status, the note in its hover bubble
assert R.note_flag("") == "" and R.note_flag("  ") == ""
c = R.note_flag("NEGATIVE: no event seen <b>")
assert '<span class="nflag" tabindex="0"' in c and '<span class="nbub" role="tooltip">NEGATIVE: no event seen &lt;b&gt;</span>' in c, c
# Observation Manager: results of one event grouped (same target, within 10 min), the event choice and 'results per
# event' only when asked for, rows that a click picks
from datetime import timedelta
t0 = datetime(2026, 11, 2, 1, 9, 10, tzinfo=timezone.utc)
ev = lambda tid, dt, lab="(3200) Phaethon": dict(base, tid=tid, label=lab, when=t0 + timedelta(seconds=dt),
                                                  utc=(t0 + timedelta(seconds=dt)).strftime("%Y-%m-%dT%H:%M:%S"))
evs = [ev("3200", 0), ev("3200", 70), ev("3200", 500), ev("3200", 3 * 3600), ev("709", 30, "(709) Fringilla")]
groups = R.group_events(evs)
assert [(g, n) for g, _, n in groups] == [("3200|2026-11-02T01:09", 3), ("709|2026-11-02T01:09", 1),
                                         ("3200|2026-11-02T04:09", 1)], groups
assert [e["nres"] for e in evs] == [3, 3, 3, 1, 1] and evs[2]["grp"] == "3200|2026-11-02T01:09"
assert groups[0][1] == "(3200) Phaethon 2026-11-02 01:09 UT"
vals = dict(re.findall(r'data-f(\w+)="([^"]*)"', R.filter_attrs(evs[0])))
assert vals["evt"] == "3200|2026-11-02T01:09" and vals["nres"] == "3"
assert 'data-pick="k1"' in R.filter_attrs(dict(evs[0], pick="k1"))
assert 'class="grpbtn"' in R.group_mark(evs[0]) and R.group_mark(evs[3]) == ""
bar = R.filter_bar(groups, True)
assert 'select data-s="evt"' in bar and 'data-f="nres"' in bar and "(3 results)" in bar
assert 'Several results' in bar and 'One result' in bar
assert 'data-s="evt"' not in R.filter_bar() and 'data-f="nres"' not in R.filter_bar()     # Results / Favorites: unchanged
assert "nres:1" in R.FILTER_JS and "s.evt&&r.dataset.fevt!==s.evt" in R.FILTER_JS
assert "obs_pick" in R.PICK_JS and "grpbtn" in R.PICK_JS
print("REPORT FILTER TESTS PASSED")
