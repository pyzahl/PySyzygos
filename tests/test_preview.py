import os, sys, math, xml.etree.ElementTree as ET, numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
from pysyzygos import preview as P

# camera field of view: 2 atan(s / 2f); 5.6 x 3.2 mm at 2500 mm is 7.70' x 4.40'
w, h = P.camera_fov_arcmin(2500.0, (5.6, 3.2))
assert abs(w - 7.7006) < 1e-3 and abs(h - 4.4004) < 1e-3, (w, h)

# synthetic field: target at (100, 20), a star 3' east and 2' north of it, one far outside the field
ra0, dec0 = 100.0, 20.0
east, north = 3.0 / 60 / math.cos(math.radians(dec0)), 2.0 / 60
stars = dict(ra=np.array([ra0, ra0 + east, ra0 + 5.0]), dec=np.array([dec0, dec0 + north, dec0]), g=np.array([11.0, 14.0, 9.0]))
track = [(m, ra0 + m * 0.5 / 3600, dec0) for m in range(-60, 61, 10)]       # 0.5"/min eastwards
svg = P.render_svg(stars, dict(ra=ra0, dec=dec0, g=11.0), track, (w, h), title="T <test> & co", subtitle="s")
root = ET.fromstring(svg)                                                      # valid XML (title is escaped)
ns = "{http://www.w3.org/2000/svg}"
circles = [c for c in root.iter(ns + "circle")]
star_dots = [c for c in circles if c.find(ns + "title") is not None]
assert len(star_dots) == 2, len(star_dots)                                      # the far star is outside the field
field = max(3 * max(w, h), 10.0); scale = P.SIZE / field
c0 = next(c for c in star_dots if c.find(ns + "title").text == "G 11.00")
c1 = next(c for c in star_dots if c.find(ns + "title").text == "G 14.00")
assert abs(float(c0.get("cx")) - P.SIZE / 2) < 0.1 and abs(float(c0.get("cy")) - P.SIZE / 2) < 0.1
assert abs(float(c1.get("cx")) - (P.SIZE / 2 - 3.0 * scale)) < 0.3, "east must be left"
assert abs(float(c1.get("cy")) - (P.SIZE / 2 - 2.0 * scale)) < 0.3, "north must be up"
assert float(c0.get("r")) > float(c1.get("r")), "brighter stars are larger"
poly = next(root.iter(ns + "polyline")); xs = [float(p.split(",")[0]) for p in poly.get("points").split()]
assert xs[0] > xs[-1], "eastward motion goes to the left"
assert "T &lt;test&gt; &amp; co" in svg and "camera 7.7" in svg and "track -60 to +60 min" in svg
# search corridor: two dotted lines parallel to the (east-west) track, half-width above and below
svg = P.render_svg(stars, dict(ra=ra0, dec=dec0, g=11.0), track, (w, h), corridor_arcsec=30.0, corridor_km=6578.0)
lines = [p_ for p_ in ET.fromstring(svg).iter(ns + "polyline") if p_.get("stroke-dasharray") == "1 4"]
assert len(lines) == 2 and "search corridor ±30.0″ (±6,578 km)" in svg
ys = sorted(float(l.get("points").split()[6].split(",")[1]) for l in lines)
assert abs(ys[0] - (P.SIZE / 2 - 0.5 * scale)) < 0.3 and abs(ys[1] - (P.SIZE / 2 + 0.5 * scale)) < 0.3, ys
# planets and moons: every moon gets a "+" (also a tiny one), the planet none
svg = P.render_svg(stars, dict(ra=ra0, dec=dec0, g=11.0), track, (w, h), disks=[
    dict(ra=ra0, dec=dec0, r_arcsec=20.0, label="Jupiter", main=True, moon=False),
    dict(ra=ra0 + east, dec=dec0, r_arcsec=0.01, label="Amalthea", main=False, moon=True)])
plus = [p_ for p_ in ET.fromstring(svg).iter(ns + "path") if p_.get("stroke") == "#22d3ee"]
assert len(plus) == 1 and plus[0].find(ns + "title").text == "Amalthea"
# magnifier: a companion 2" east and 1" north, 1 mag fainter; the asteroid moves east at 1"/s through the target
assert P.zoom_field_arcsec(None) == 30.0 and P.zoom_field_arcsec(0.4) == 10.0 and P.zoom_field_arcsec(12.0) == 36.0
assert P.zoom_field_arcsec(30.0) == 30.0 and P.zoom_field_arcsec(2.0, fixed=20.0) == 20.0
ce, cn = 2.0 / 3600 / math.cos(math.radians(dec0)), 1.0 / 3600
zs = dict(ra=np.array([ra0, ra0 + ce]), dec=np.array([dec0, dec0 + cn]), g=np.array([11.0, 12.0]))
ztr = [(t_, ra0 + t_ / 3600 / math.cos(math.radians(dec0)), dec0) for t_ in range(-6, 7, 2)]
z = dict(stars=zs, field_arcsec=10.0, track=ztr, delta_km=1.5e8, r_km=10.0, seeing_arcsec=2.0)
svg = P.render_svg(stars, dict(ra=ra0, dec=dec0, g=11.0), track, (w, h), zoom=z)
root = ET.fromstring(svg)
k = P.ZOOM_PX / 10.0
cores = {c.find(ns + "title").text: c for c in root.iter(ns + "circle")
         if c.find(ns + "title") is not None and c.get("fill") == "#f8fafc" and c.get("r") and float(c.get("r")) > 1.0}
comp = next(c for t_, c in cores.items() if "\u0394G +1.00" in t_)
tip = comp.find(ns + "title").text
assert abs(float(comp.get("cx")) - (P.ZOOM_PX / 2 - 2.0 * k)) < 0.3 and abs(float(comp.get("cy")) - (P.ZOOM_PX / 2 - 1.0 * k)) < 0.3
assert "2.24\u2033 at PA 63\u00b0" in tip, tip                               # east of north: atan2(2, 1)
assert "passes it +2.0 s" in tip, tip                                             # 2" ahead along the motion at 1"/s
assert f"{math.radians(1 / 3600) * 1.5e8:,.0f} km" in tip, tip                 # 1" across the track at 1.5e8 km
assert "\u0394G +1.0 \u00b7 2.2\u2033" in svg and "zoom 10\u2033" in svg and "asteroid \u2300 28 mas" in svg
print("PREVIEW TESTS PASSED")
