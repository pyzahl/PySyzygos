"""panorama.py: a made-up equirectangular photo with a known horizon (transparent sky) and a known azimuth at its left
edge: profile, UserHorizon points, the azimuth fit, thumbnail/meta files, the SVG. Needs Pillow."""
import os, re, sys, tempfile
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
assert re.fullmatch(r"My_site_1_\d{8}-\d{6}\.jpg", os.path.basename(jpg)) and Image.open(jpg).size == (1440, 720)
__import__("time").sleep(1.1)                                    # a second photo: a new file, the first one stays
jpg2 = P.save(buf.getvalue(), "My site/1", folder=os.path.join(d0, "horizons"))[0]
assert jpg2 != jpg and os.path.isfile(jpg) and os.path.isfile(jpg2)
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
# a photo without a transparent sky: the sky found by colour (sky_mask) - blue sky with a white cloud, ground with a
# skyline from 5 to 25 deg, a blue lake below it (not connected to the sky: stays ground)
from PIL import Image as _I
W2, H2 = 1440, 720
yy, xx = np.mgrid[0:H2, 0:W2]
alt_px = 90 - 180 * yy / H2
sky_alt = 5 + 20 * (xx >= W2 // 2)                                      # skyline: 5 deg left half, 25 deg right half
photo = np.zeros((H2, W2, 3), np.uint8)
photo[...] = (90, 140, 210)                                             # blue sky
photo[(alt_px > 50) & (alt_px < 56) & (xx > 300) & (xx < 380)] = (245, 245, 245)     # a cloud
ground_px = alt_px < sky_alt
photo[ground_px] = (60, 90, 40)                                          # green ground
photo[ground_px & (alt_px < -10) & (alt_px > -20) & (xx > 100) & (xx < 400)] = (70, 120, 200)   # a blue lake
im2 = _I.fromarray(photo, "RGB")
mask, how = P.ground(im2)
assert how == "sky detection"
prof2 = P.profile(im2)
left, right = prof2[: len(prof2) // 2 - 4], prof2[len(prof2) // 2 + 4:]
assert abs(np.median(left) - 5) < 0.6 and abs(np.median(right) - 25) < 0.6, (np.median(left), np.median(right))
assert prof2.max() < 30                                                   # the cloud is not taken for ground
assert mask[(alt_px < -12) & (alt_px > -18) & (xx > 150) & (xx < 350)].all()   # the lake stays ground
grey = _I.fromarray(np.full((H2, W2, 3), 90, np.uint8), "RGB")            # no sky at all: no profile
assert P.profile(grey) is None and P.ground(grey) == (None, "")
# the Sun for lining up a photo: NOAA formulas vs astropy (Greenwich, refraction), and the Sun's disk in a photo
from datetime import datetime, timezone
REF = {(2026, 6, 21, 12, 0): (179.112, 61.966), (2026, 10, 22, 15, 30): (236.247, 10.810),
       (2026, 12, 21, 9, 0): (139.751, 5.674)}                          # astropy get_sun + AltAz with refraction
for (yy_, mo, dd, hh, mi), (az_ref, alt_ref) in REF.items():
    az_, alt_ = P.sun_altaz(51.4769, -0.0005, datetime(yy_, mo, dd, hh, mi, tzinfo=timezone.utc))
    assert abs(az_ - az_ref) < 0.05 and abs(alt_ - alt_ref) < 0.05, (az_, alt_, az_ref, alt_ref)
sunpic = photo.copy()
sunpic[(np.hypot(xx - 1000, yy - 300) < 6)] = (255, 255, 255)            # the Sun's disk at 250 deg, 15 deg up
jp = os.path.join(d0, "sun.png")
_I.fromarray(sunpic, "RGB").save(jp)
xs_, as_ = P.sun_in_photo(jp)
assert abs(xs_ - 1000 / W2 * 360) < 0.3 and abs(as_ - (90 - 300 / H2 * 180)) < 0.3, (xs_, as_)
_I.fromarray(photo, "RGB").save(jp)
assert P.sun_in_photo(jp) is None                                         # no disk: None
assert "Sun 250.0" in P.svg(jp, 0.0, sun=(250.0, 15.0)) and ">10</text>" in P.svg(jp, 0.0)   # marker, 10-deg ticks
# the capture time from EXIF (read before the photo is shrunk): GPS time, camera time with offset, camera time only
import io as _io
from PIL import Image as _Im
def _jpg(fill):
    im = _Im.new("RGB", (64, 32), (90, 140, 220)); ex = im.getexif(); fill(ex)
    b = _io.BytesIO(); im.save(b, "JPEG", exif=ex); return b.getvalue()
def _gps(ex):
    g = ex.get_ifd(0x8825); g[29] = "2026:10:22"; g[7] = (20.0, 45.0, 4.0)
    ex.get_ifd(0x8769)[36867] = "2026:10:22 16:45:00"
def _off(ex):
    e = ex.get_ifd(0x8769); e[36867] = "2026:10:22 16:45:04"; e[36881] = "-04:00"; e[37521] = "5"
def _loc(ex):
    ex.get_ifd(0x8769)[36867] = "2026:10:22 16:45:04"
assert P.photo_time(_jpg(_gps)) == dict(utc="2026-10-22T20:45:04Z", local=None, how="GPS time (UTC)")
t = P.photo_time(_jpg(_off))
assert t["utc"] == "2026-10-22T20:45:04Z" and "offset" in t["how"], t
t = P.photo_time(_jpg(_loc))
assert t["utc"] is None and t["local"] == "2026-10-22 16:45:04" and "unknown" in t["how"], t
assert P.photo_time(_jpg(lambda ex: None)) is None
# the GPS position from EXIF (offered for the site): degrees/minutes/seconds with N/S/E/W; an empty fix: None
def _pos(ex):
    g = ex.get_ifd(0x8825); g[1] = "N"; g[2] = (40.0, 52.0, 11.75); g[3] = "W"; g[4] = (72.0, 51.0, 43.09); g[5] = 0; g[6] = 29.5
w = P.photo_location(_jpg(_pos))
assert abs(w["lat"] - 40.869931) < 1e-6 and abs(w["lon"] + 72.861969) < 1e-6 and w["alt_m"] == 29.5, w
assert P.photo_location(_jpg(_loc)) is None
print("PANORAMA TESTS PASSED")
