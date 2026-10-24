"""pysyzygos_globe: projection, hidden-side clipping, day side and SVG output, without SPICE (pure render_svg)."""
import math, os, sys, xml.etree.ElementTree as ET
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
from pysyzygos import globe as G

# Earth orientation: ITRF = J2000 (identity); star straight above lon 0, lat 0 -> that point is the disk centre
R = np.eye(3)
star = np.array([1.0, 0.0, 0.0])
basis = (np.cross([0, 0, 1.0], star), None, star)
basis = (basis[0] / np.linalg.norm(basis[0]), np.cross(star, basis[0] / np.linalg.norm(basis[0])), star)
proj = G._Proj(R, basis)
px, py, vis = proj(G.geodetic_to_itrf([0.0], [0.0]))
assert abs(px[0] - G.CX) < 1e-6 and abs(py[0] - G.CY) < 1e-6 and vis[0], (px, py)
px, py, vis = proj(G.geodetic_to_itrf([90.0, -90.0, 180.0], [0.0, 0.0, 0.0]))
assert px[0] > G.CX + G.RPX * 0.99 and px[1] < G.CX - G.RPX * 0.99, "east right, west left (seen from the star)"
assert not vis[2], "the far side is hidden"
px, py, vis = proj(G.geodetic_to_itrf([0.0], [60.0]))
assert py[0] < G.CY and vis[0], "north up"

# a line crossing to the far side is cut into visible runs only
lon = np.linspace(0, 360, 73)
lines = G._polylines(*proj(G.geodetic_to_itrf(lon, np.zeros_like(lon))), 'stroke="#000"')
assert len(lines) == 2, len(lines)                     # equator: 0..90 and 270..360 visible, the back hidden

# day side: Sun along the star direction -> the whole visible disk is day; Sun behind -> none visible
assert G._day_side(R, basis, star) is None             # degenerate (Sun on the line of sight): no polygon
day = G._day_side(R, basis, np.array([0.0, 1.0, 0.0]))  # Sun to the east: the eastern half is day
xs = [float(p.split(",")[0]) for p in day]
assert min(xs) >= G.CX - 1 and max(xs) > G.CX + G.RPX * 0.99, (min(xs), max(xs))

# a full plot from a synthetic event: valid XML, header, lines, minute labels, inset, site
centre = [(600.0 + 20 * i, -30.0 + 2 * i, 10.0 + 1.0 * i, 0.5) for i in range(30)]
paths = {"center": centre, "edge_plus": [(t, lo, la + 0.05, None) for t, lo, la, _ in centre],
         "edge_minus": [(t, lo, la - 0.05, None) for t, lo, la, _ in centre]}
axis = [(t, x, y) for t, x, y in ((540.0 + 20 * i, -9000 + 600 * i, -2000 + 100 * i) for i in range(31))]
d = dict(R=R, basis=basis, sun_dir=np.array([0.0, 1.0, 0.0]), paths=paths, axis=axis, site=(0.0, 20.0, "Here"),
         title="1 Test occults Gaia DR3 1 <&>", columns=(["Star:", " G 9.0"], ["Durations: Max = 1.00 secs"], ["Asteroid:"]),
         inset=dict(field_arcmin=120.0, mag_limit=11.0, stars=[(0.0, 0.0, 9.0), (10.0, -5.0, 10.5), (200.0, 0.0, 9.0)],
                    track=[(-20.0, 5.0), (0.0, 0.0), (20.0, -5.0)]),
         minute_label=lambda t: f"{int(t // 60) % 60:02d}", footer="PySyzygos test", style="lines")
svg = G.render_svg(d)
root = ET.fromstring(svg)                               # well-formed (title escaped)
ns = "{http://www.w3.org/2000/svg}"
texts = [t.text for t in root.iter(ns + "text")]
assert any(t and t.startswith("1 Test occults") for t in texts) and "Here" in texts
assert any(t == "11" for t in texts), "minute labels"
assert len(list(root.iter(ns + "polyline"))) > 50, "grid, coast and path lines"
assert sum(1 for c in root.iter(ns + "circle") if c.get("fill") == "#111") >= 2 + 1, "inset stars and minute dots"
assert root.find(f".//{ns}clipPath") is not None, "globe clipped below the header"
assert len(G.earth_lines()["coast"]) > 100, "Natural Earth data present (data/ne_110m_earth.json)"
# both styles: color fills land and darkens the night side, lines draws the day side and coastlines
for style in ("color", "lines"):
    svg = G.render_svg(dict(d, style=style))
    r = ET.fromstring(svg)
    fills = [p.get("fill") for p in list(r.iter(ns + "polygon")) + list(r.iter(ns + "path"))]
    if style == "color":
        assert G.STYLE["color"]["land"] in fills and "#000" in fills, "land and night side"
    else:
        assert G.STYLE["lines"]["day"] in fills and G.STYLE["color"]["land"] not in fills
assert len(G.earth_lines()["land"]) > 100, "Natural Earth land polygons present"
# land drawing: a polygon containing the far-side point is drawn inside out (outside of its outline), others normally;
# seen from the Pacific, Africa/Eurasia contains the antipode; seen from the Atlantic it does not (regression 2026-10-05)
def view(lon, lat):
    l, b = math.radians(lon), math.radians(lat)
    z = np.array([math.cos(b) * math.cos(l), math.cos(b) * math.sin(l), math.sin(b)])
    x = np.cross([0, 0, 1.0], z); x = x / np.linalg.norm(x)
    return G._Proj(np.eye(3), (x, np.cross(z, x), z))
afeu = max(G.earth_lines()["land"], key=len)                       # the largest ring: Africa + Eurasia
assert min(afeu[0::2]) < 0 < 100 < max(afeu[0::2])
pac, atl = G._land_path(view(-160, 0), afeu[0::2], afeu[1::2]), G._land_path(view(-20, 10), afeu[0::2], afeu[1::2])
square = lambda d: d.count(" Z") == 2                               # enclosing square + outline
assert pac is not None and square(pac), "seen from the Pacific: Africa/Eurasia drawn as the outside of its outline"
assert atl is not None and not square(atl), "seen from the Atlantic: drawn normally"
aus = next(r_ for r_ in G.earth_lines()["land"] if 110 < min(r_[0::2]) and max(r_[0::2]) < 160 and min(r_[1::2]) < -30)
assert G._land_path(view(-20, 10), aus[0::2], aus[1::2]) is None, "Australia is on the far side: nothing drawn"
# the geometry panels (A4 page): system_data from a stand-in for SPICE (spkpos only), checked against astrometry.deflect
from pysyzygos import astrometry as A
AU = G.AU_KM
def unit_at(deg, side=1.0, z=0.0):
    a = math.radians(deg)
    v = np.array([math.cos(a), side * math.sin(a), z])
    return v / np.linalg.norm(v)
for sun_deg, x_t in ((46.0, 0.95), (170.0, 1.6)):                    # Phaethon-like, and a main-belt one at opposition
    pos = {A.SUN: 1.0 * AU * unit_at(sun_deg), A.JUPITER: 4.4 * AU * unit_at(3, -1, 0.02), A.SATURN: 9.5 * AU * unit_at(60, -1, 0.1),
           "T": x_t * AU * star}

    class Spice:
        def spkpos(self, b, et, frame, ab, obs):
            assert frame == "J2000" and obs == "EARTH"
            return (pos[str(b)], 0.0)
    sy = G.system_data(Spice(), 0.0, "T", star, "Test", "Gaia DR3 1")
    tot = lambda q_of: sum(A.deflect(star, -pos[b], q_of(b), A.GM[b]) for b in A.DEFLECTORS)
    d_star = tot(lambda b: star)
    d_ast = tot(lambda b: A.unit(x_t * AU * star - pos[b]))
    assert abs(sy["star_mas"] - np.linalg.norm(d_star) * G.RAD2MAS) < 1e-9
    assert abs(sy["shift_mas"] - np.linalg.norm(d_star - d_ast) * G.RAD2MAS) < 1e-9
    assert abs(sy["shift_km"] - np.linalg.norm(d_star - d_ast) * x_t * AU) < 1e-6
    k = sy["curve_x"].index(min(sy["curve_x"], key=lambda x: abs(x - x_t)))
    assert abs(sy["curve_y"][k] - sy["y_target"]) < 1e-12 * max(1.0, abs(sy["y_target"])) + 1e-15, "the ray passes the target"
    ticks = G._ticks(-0.37, 6.94)
    step = ticks[1] - ticks[0]
    assert round(step / 10 ** math.floor(math.log10(step)), 9) in (1, 2, 2.5, 5), ticks       # human tick steps
    assert sy["bodies"][0]["name"] == "Sun" and abs(sy["elong"] - sun_deg) < 1e-6
    # A4 page: the view plus both panels, 210 x 297 mm; labels inside, not overlapping
    svg = G.render_svg(dict(d, system=sy, page="A4"))
    r = ET.fromstring(svg)
    assert r.get("width") == "210mm" and r.get("height") == "297mm" and r.get("viewBox") == f"0 0 {G.W} {G.PAGES['A4']}"
    texts = [t.text or "" for t in r.iter(ns + "text")]
    assert any(t.startswith("True scale") for t in texts) and any(t.startswith("Light paths") for t in texts)
    assert any(f"{sy['shift_mas']:.2f} mas = {sy['shift_km']:.1f} km" == t for t in texts), "shift label"
    assert any(t.startswith("PySyzygos test") for t in texts), "footer"
    footer_y = max(float(t.get("y")) for t in r.iter(ns + "text") if (t.text or "").startswith("PySyzygos test"))
    assert footer_y > G.H + 500, "footer at the page bottom"
# the square page: the view alone, as before
r = ET.fromstring(G.render_svg(dict(d, page="square")))
assert r.get("viewBox") == f"0 0 {G.W} {G.H}" and not any((t.text or "").startswith("Light paths") for t in r.iter(ns + "text"))
# the label placer: a label never lands on a taken spot while a free one exists
L = G._Labels(0, 0, 400, 300)
L.block(200, 150, 10)
for _ in range(6):
    L.place(200, 150, ["label text"], "#000")
boxes = L.taken
assert all(a[2] < b[0] or a[0] > b[2] or a[3] < b[1] or a[1] > b[3] for i, a in enumerate(boxes) for b in boxes[i + 1:])
print("GLOBE TESTS PASSED")
