"""panorama.py: a made-up equirectangular photo with a known horizon (transparent sky) and a known azimuth at its left
edge: profile, UserHorizon points, the azimuth fit, thumbnail/meta files, the SVG. Needs Pillow."""
import os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import numpy as np
from PIL import Image
from pysyzygos import panorama as P, horizon as H

W, HT, AZ_LEFT = 1440, 720, 123.0
true = lambda az: 12 + 10 * np.sin(np.radians(az)) + np.where((az > 250) & (az < 290), 25, 0)   # a tree 250..290
az_col = (AZ_LEFT + (np.arange(W) + 0.5) * 360 / W) % 360
rows = np.arange(HT)[:, None]
alt_row = 90 - 180 * (rows + 0.5) / HT
img = np.zeros((HT, W, 4), np.uint8)
img[..., :3] = 90
img[..., 3] = np.where(alt_row < true(az_col)[None, :], 255, 0)
img[100, :, 3] = 255                                                   # a wire across the sky: not the horizon
im = Image.fromarray(img, "RGBA")

prof = P.profile(im)
assert len(prof) == 1440
got = P.at_azimuth(prof, AZ_LEFT)
want = true(np.arange(1440) * 0.25)
edge = np.abs(np.diff(np.append(want, want[0]))) > 5                    # the tree's vertical sides
assert np.percentile(np.abs(got - want)[~edge], 99) < 0.6, np.abs(got - want).max()

pts = P.points(prof, AZ_LEFT)
H.check(pts)                                                           # OccultWatcher's rules
assert pts[0][0] == 0 and pts[-1][0] == 360 and all(isinstance(a, int) and isinstance(h, int) for a, h in pts)
for a in range(0, 360, 5):                                             # never below the true horizon by > 1 deg
    assert H.altitude(pts, a + 0.5) >= true(np.array([a + 0.5]))[0] - 1.2, (a, H.altitude(pts, a + 0.5))
assert 26.5 <= H.altitude(pts, 270) <= 28.5                                # the tree: 12 - 10 + 25

hand = [(a, int(round(float(true(np.array([a]))[0])))) for a in range(0, 361, 5)]      # points as made by hand
for ref in (pts, hand):
    az0, d = P.fit_az_left(prof, ref)                                  # whole degrees: about a degree is the limit
    assert abs((az0 - AZ_LEFT + 180) % 360 - 180) <= 1.5 and d < 1.0, (az0, d)

d0 = tempfile.mkdtemp()
buf = __import__("io").BytesIO()
im.save(buf, "PNG")
jpg, meta = P.save(buf.getvalue(), "My site/1", folder=os.path.join(d0, "horizons"), source="/x/pano.png")
assert os.path.basename(jpg) == "My_site_1.jpg" and Image.open(jpg).size == (1440, 720)
assert P.load_meta(jpg)["profile"][:3] == meta["profile"][:3] and meta["source"] == "pano.png"
s = P.svg(jpg, AZ_LEFT, pts, 15, star=(270, 30), label="star 30°")
assert s.count("<image") == 2 and "data:image/jpeg;base64," in s and "star 30°" in s and s.count("<polyline") == 2
try:
    P.check_size(Image.new("RGB", (300, 200)))
    raise AssertionError("3:2 accepted")
except ValueError:
    pass
rgb = __import__("io").BytesIO()
im.convert("RGB").save(rgb, "JPEG")
assert P.save(rgb.getvalue(), "plain", folder=os.path.join(d0, "horizons"))[1]["profile"] is None   # no alpha
print("PANORAMA TESTS PASSED")
