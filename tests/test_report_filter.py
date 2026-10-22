"""report.py filter bar: each row's filter values (data-f*: mag, duration, drop, altitudes, RUWE, chance in %) and
flags (supplement star, uncertain star, double star, twilight, horizon, size estimated), and the bar and its script
in the page. No SPICE, no network."""
import os, re, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
from pysyzygos import report as R

base = dict(tid="99999999", utc="2026-11-01T01:02:03.456", body=False, mag=10.5, dur=1.25, drop=2.0, alt=35.0, sun=-25.0, ruwe=1.2, p_site=0.42,
            sflag="", star_sigma=None, rad=5.0, dhint="", hz=("", None, None), size_src="SBDB diameter")
a = R.filter_attrs(base)
vals = dict(re.findall(r'data-f(\w+)="([^"]*)"', a))
assert vals == dict(mag="10.500", dur="1.250", drop="2.000", alt="35.0", sun="-25.0", ruwe="1.20", chance="42.00",
                    flags=""), vals
e = dict(base, sflag="RUWE 1.70", star_sigma=8.0, dhint="companion", sun=-8.0, hz=("near", 20.0, 3.0),
         size_src="H only, albedo assumed", ruwe=None, p_site=None)
vals = dict(re.findall(r'data-f(\w+)="([^"]*)"', R.filter_attrs(e)))
assert vals["flags"].split() == ["sup", "unc", "dbl", "twi", "hz", "est"] and vals["ruwe"] == "" and vals["chance"] == "", vals
bar = R.filter_bar()
assert all(f'data-f="{k}"' in bar for k in ("mag", "dur", "drop", "alt", "sun", "ruwe", "chance"))
assert all(f'data-h="{k}"' in bar for k, _ in R.FILTER_FLAGS) and 'data-o="moon"' in bar and 'id="fset"' in bar
assert "/api/filters/save" in R.FILTER_JS and "pyo_filter:" in R.FILTER_JS
# the CSV downloads keep the page's rows in its order (exports.only_shown with the visible rows' event keys)
from pysyzygos import exports as X
assert 'data-ev="99999999|' in R.filter_attrs(dict(base, utc="2026-11-01T01:02:03.456"))
pairs = [({"n": i}, dict(target_id=t, best_utc=u)) for i, (t, u) in enumerate(
    [("1", "2026-11-01T00:00:00.1"), ("2", "2026-11-02T00:00:00"), ("3", "2026-11-03T00:00:00.9")])]
keys = [R.event_key("3", "2026-11-03T00:00:00.9"), R.event_key("1", "2026-11-01T00:00:00")]
assert [p[0]["n"] for p in X.only_shown(pairs, keys)] == [2, 0]             # shown rows only, in the page's order
assert X.only_shown(pairs, None) == pairs and X.only_shown(pairs, []) == []  # page not readable: all; none shown: none
print("REPORT FILTER TESTS PASSED")
