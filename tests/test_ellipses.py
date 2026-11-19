"""Error ellipses (pysyzygos.ellipses): covariance round trip, the star's ellipse from Gaia errors carried to the event
date, the combined ellipse and the error across the track, the SVG; favorites.backfill_errors with stand-ins.
Reference: OccultWatcher's event page of (369152) 2008 SJ52 on 2026-10-12 (Horizons SMAA/SMIA/Theta 3-sigma 0.084",
0.067", -4.444 deg; star 0.28 x 0.26 mas at PA 90; combined 28.00 x 22.30 mas at PA 94)."""
import _testtmp  # noqa: F401  (temporary files of this run in one folder, removed at exit)
import sys, os, math, tempfile, xml.etree.ElementTree as ET
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
from pysyzygos import ellipses as E, favorites as F

for a, b, pa in ((28.0, 22.33, 94.44), (3.0, 1.0, 10.0), (2.0, 0.5, 170.0)):
    a2, b2, pa2 = E.ellipse(E.cov(a, b, pa))
    assert abs(a2 - a) < 1e-9 and abs(b2 - b) < 1e-9 and abs(pa2 - pa) < 1e-6, (a2, b2, pa2)
ast = (84.0 / 3, 67.0 / 3, (90 - (-4.444)) % 180)                         # Horizons 3-sigma arcsec -> 1-sigma mas, PA
star = E.star_ellipse(dict(ra_error=0.02, dec_error=0.02, pmra_error=0.026, pmdec_error=0.024), 10.78)
assert abs(star[0] - 0.28) < 0.005 and abs(star[1] - 0.26) < 0.005 and abs(star[2] - 90) < 1, star
comb = E.ellipse(E.add(E.cov(*ast), E.cov(*star)))
assert abs(comb[0] - 28.0) < 0.05 and abs(comb[1] - 22.3) < 0.05 and round(comb[2]) == 94, comb
assert E.star_ellipse(dict(ra_error=0.1, dec_error=0.1), 10) is None, "2-parameter source: no proper motion errors"
# across the track: an ellipse along the motion gives its minor axis, across it the major axis
c = E.cov(3.0, 1.0, 90.0)                                                 # major axis east-west
assert abs(E.across_track(c, 1.0, 0.0) - 1.0) < 1e-9 and abs(E.across_track(c, 0.0, 1.0) - 3.0) < 1e-9
svg = E.svg(ast, star, (20.75, -10.72), note="n")
root = ET.fromstring(svg)
ns = "{http://www.w3.org/2000/svg}"
els = list(root.iter(ns + "ellipse"))
assert len(els) == 3 and els[2].get("fill") == "none", "target and star filled, combined as an outline"
assert abs(float(els[1].get("ry")) / float(els[0].get("ry")) - 0.28 / 28.0) < 0.002, "one scale: the star stays tiny"
assert "Combined: (28.00 × 22.33) mas @ 94°" in svg
assert "no error data" in E.svg(None, None)

# favorites: the ellipses filled in once (Horizons and Gaia stand-ins), the SVG with the error across the track
tmp = tempfile.mkdtemp()
fav, maps = os.path.join(tmp, "favorites"), os.path.join(tmp, "maps")
os.makedirs(maps)
rec = dict(target_id="369152", target_name="369152 (2008 SJ52)", best_utc="2026-10-12T04:58:57.081", best_et="845139606.3",
           star="3160985089639151616", mag="8.05", r_km="0.945", motion_ra_ash="20.75", motion_dec_ash="-10.72",
           dist_au="3.0826")
assert F.add(rec, dict(site=dict(name="S", lat=1.0, lon=2.0)), maps, fav)[0]
calls = []
def hz(tid, utc):
    calls.append(tid)
    return dict(dist_au=3.08, ast_err_smaa_mas=ast[0], ast_err_smia_mas=ast[1], ast_err_pa_deg=ast[2])
gaia = lambda ids: {3160985089639151616: dict(ra_error=0.02, dec_error=0.02, pmra_error=0.026, pmdec_error=0.024)}
assert F.backfill_errors(hz, gaia, fav) == 1
r = F.load(fav)[0]["record"]
assert abs(float(r["star_err_smaa_mas"]) - 0.28) < 0.005 and abs(float(r["ast_err_smaa_mas"]) - 28.0) < 1e-9
assert F.backfill_errors(hz, gaia, fav) == 0 and calls == ["369152"], "once per favorite"
s = F.error_svg(F.load(fav)[0])
assert "across track" in s and " km" in s and s.count("<ellipse") == 3
# a star too small to see gets a "+"; a missing ellipse a legend line saying why
assert 'stroke="#16a34a" stroke-width="1.5"' in svg, "star marker"
s2 = E.svg(ast, None, missing={"Star": "not fetched yet"})
assert "Star: not fetched yet" in s2 and s2.count("<ellipse") == 2
e2 = F.load(fav)[0]
e2["record"] = {k: v for k, v in e2["record"].items() if not k.startswith("star_err")}
e2.pop("err_checked", None)
s3 = F.error_svg(e2)                                                     # no Gaia errors: a typical star, marked "!"
assert "Star !:" in s3 and "typical for G 8." in s3 and s3.count("<ellipse") == 3
st = E.typical_star(8.05, 10.78)
assert 0.15 < st[0] < 0.35 and st[0] == st[1], st                         # the real star: 0.30 x 0.22 mas
# the star as seen from the site: -(axis - observer) / distance, its ellipse drawn there too, with the target disk
e3 = F.load(fav)[0]
e3["record"].update(offset_east_km="0.9", offset_north_km="-1.2", r_km="0.945")
s4 = F.error_svg(e3)
k = 206264806.2 / (3.0826 * 1.495978707e8)
assert f"{1.5 * k:.1f} mas = 1.5 km, outside" in s4 and s4.count("<circle") == 1 and s4.count("<ellipse") == 4
e3["record"].update(offset_east_km="3.0", offset_north_km="-4.0")          # 5 km > 2 shadow widths: no zoom out
s5 = F.error_svg(e3)
assert "5.0 km off (> 2 widths, not drawn)" in s5 and s5.count("<ellipse") == 3 and "<circle" not in s5
sv = E.svg(ast, star, (1.0, 0.0), star_at=(10.0, 0.0), disk_mas=2.0)
at = [x for x in ET.fromstring(sv).iter(ns + "ellipse") if x.get("stroke-dasharray") == "3 2"]
assert len(at) == 1 and float(at[0].get("cx")) < 150, "a star east of the centre is drawn left (east left)"
print("ELLIPSES TESTS PASSED")
