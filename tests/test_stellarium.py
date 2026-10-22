"""Stellarium pointing (pysyzygos.stellarium): the Remote Control requests (location, time as JD UT with the clock
stopped, J2000 view vector, field), against a small local HTTP server; and a clean failure without Stellarium."""
import sys, os, json, threading, urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
from pysyzygos import stellarium as S, urls as U

got = []
class H(BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        q = dict(urllib.parse.parse_qsl(self.rfile.read(n).decode()))
        got.append((self.path, q))
        body = b"ok"
        if self.path == "/api/main/focus" and "target" in q:          # Stellarium knows only this name here
            body = b"true" if q["target"] == "Gaia DR3 7" else b"false"
        self.send_response(200); self.end_headers(); self.wfile.write(body)
    def do_GET(self):                                                    # stelproperty/list: the current zone
        got.append((self.path, {}))
        body = json.dumps({"StelCore.currentTimeZone": {"value": ZONE[0]}}).encode()
        self.send_response(200); self.end_headers(); self.wfile.write(body)
    def log_message(self, *a): pass
ZONE = ["America/New_York"]
srv = HTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
U.URL_STELLARIUM_API = f"http://127.0.0.1:{srv.server_port}/api"

ok, msg = S.show(90.0, 0.0, "2026-10-15T03:13:07", 0.5, lat=47.0, lon=9.6, ele=958)
assert ok, msg
paths = [p for p, _ in got]
assert paths == ["/api/location/setlocationfields", "/api/main/time", "/api/main/focus", "/api/main/view",
                 "/api/main/fov", "/api/main/view"], paths        # focus: the old selection cleared first; the view
                                                                  # set again at the end (Stellarium's next frame)
f = dict(got)
assert f["/api/location/setlocationfields"]["latitude"] == "47.000000" and f["/api/location/setlocationfields"]["altitude"] == "958"
assert abs(float(f["/api/main/time"]["time"]) - 2461328.6341088) < 1e-6 and f["/api/main/time"]["timerate"] == "0"
v = json.loads(f["/api/main/view"]["j2000"])
assert abs(v[0]) < 1e-9 and abs(v[1] - 1) < 1e-9 and abs(v[2]) < 1e-9, v
assert f["/api/main/fov"]["fov"] == "0.5000"
got.clear()
assert S.show(90.0, 0.0, "2026-10-15T03:13:07", set_location=False, lat=47.0, lon=9.6)[0] and got[0][0] == "/api/main/time"
# marking the star by name: names tried in order, mode 'mark'; none known: the selection is cleared
got.clear()
ok, msg = S.show(90.0, 0.0, "2026-10-15T03:13:07", set_location=False, names=["HIP 1", "Gaia DR3 7"])
focus = [q for p, q in got if p == "/api/main/focus"]
assert ok and "Gaia DR3 7 marked" in msg and focus == [{}, {"target": "HIP 1", "mode": "mark"},
                                                       {"target": "Gaia DR3 7", "mode": "mark"}], (msg, focus)
got.clear()
ok, msg = S.show(90.0, 0.0, "2026-10-15T03:13:07", set_location=False, names=["Gaia DR3 8"])
focus = [q for p, q in got if p == "/api/main/focus"]
assert ok and "not in Stellarium's catalogs" in msg and focus[0] == {} and focus[-1] == {} and \
    {"target": "Gaia DR3 8", "mode": "mark"} in focus and len(focus) > 3, focus      # asked again while waiting
views = [q for p, q in got if p == "/api/main/view"]
assert len(views) > 3 and all(q == views[0] for q in views), views                  # the view re-set while waiting
S_wait = S.mark.__defaults__
S.mark.__defaults__ = (0.0, 0.0, None)                            # no waiting for the rest of the test
assert S.mark(["Gaia DR3 8"]) is None and S.mark(["Gaia DR3 7"]) == "Gaia DR3 7"
S.mark.__defaults__ = S_wait
got.clear()
assert S.show(90.0, 0.0, "2026-10-15T03:13:07", set_location=False)[0] and \
    [q for p, q in got if p == "/api/main/focus"] == [{}]            # no names: only the selection cleared
# time zone: set only when it differs; after a change the event time is sent again (it takes effect at the next frame)
got.clear()
ok, msg = S.show(90.0, 0.0, "2026-10-15T03:13:07", lat=47.0, lon=9.6, tz="Europe/Zurich")
posts = [p for p, q in got if p != "/api/stelproperty/list"]
assert ok and "/api/stelproperty/set" in posts and posts.count("/api/main/time") == 2, posts
got.clear()
ZONE[0] = "Europe/Zurich"
ok, msg = S.show(90.0, 0.0, "2026-10-15T03:13:07", lat=47.0, lon=9.6, tz="Europe/Zurich")
posts = [p for p, q in got if p != "/api/stelproperty/list"]
assert ok and "/api/stelproperty/set" not in posts and posts.count("/api/main/time") == 1, posts
srv.shutdown(); srv.server_close()
ok, msg = S.show(90.0, 0.0, "2026-10-15T03:13:07")                  # nobody listening: a message, no exception
assert not ok and "not reachable" in msg, msg
assert not S.show(90.0, 0.0, "not a time")[0]
print("STELLARIUM TESTS PASSED")
