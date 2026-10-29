"""server_mode.py: login (Basic once, then the signed cookie, the WebSocket included), password file, and the cross-site
guard of both modes, against a stand-in ASGI app (no NiceGUI needed)."""
import asyncio, base64, os, stat, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
from pysyzygos import server_mode as S

S.ITERATIONS = 1000                                        # fast for the test (the record keeps its own count)
S.FAIL_DELAY_S = 0.0
auth = S.make_auth("observer", "secret-pass")
assert S.check_password(auth, "observer", "secret-pass")
assert not S.check_password(auth, "observer", "wrong") and not S.check_password(auth, "other", "secret-pass")
assert "secret-pass" not in str(auth)

with tempfile.TemporaryDirectory() as d:                   # stored with mode 600, read back
    p = os.path.join(d, S.AUTH_FILE)
    S.save_auth(p, auth)
    assert stat.S_IMODE(os.stat(p).st_mode) == 0o600
    assert S.load_auth(p) == auth
    assert S.load_auth(os.path.join(d, "none.json")) is None

c = S.make_cookie(auth)
assert S.cookie_ok(auth, c) and not S.cookie_ok(auth, c[:-1] + ("0" if c[-1] != "0" else "1"))
assert not S.cookie_ok(auth, S.make_cookie(auth, now=1.0))            # expired
assert not S.cookie_ok(S.make_auth("observer", "secret-pass"), c)     # a new password: old cookies are void
assert not S.cookie_ok(auth, None) and not S.cookie_ok(auth, "junk")
assert S.is_loopback("127.0.0.1") and S.is_loopback("[::1]") and not S.is_loopback("0.0.0.0")


async def inner(scope, receive, send):                     # stand-in for the NiceGUI app
    if scope["type"] == "websocket":
        await send({"type": "websocket.accept"})
        return
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


def call(guard, path="/", kind="http", **hdr):
    scope = dict(type=kind, path=path, scheme="http",
                 headers=[(k.replace("_", "-").encode(), v.encode()) for k, v in hdr.items()])
    sent = []

    async def send(m):
        sent.append(m)

    async def receive():
        return {"type": "http.request"}
    asyncio.run(guard(scope, receive, send))
    if kind == "websocket":
        return sent[0]["type"], None
    h = {k.decode(): v.decode() for k, v in sent[0].get("headers", [])}
    return sent[0]["status"], h


basic = "Basic " + base64.b64encode(b"observer:secret-pass").decode()
G = S.Guard(inner, auth)
st, h = call(G, host="srv:8080")
assert st == 401 and h["www-authenticate"].startswith("Basic"), (st, h)
st, h = call(G, host="srv:8080", authorization="Basic " + base64.b64encode(b"observer:nope").decode())
assert st == 401
st, h = call(G, host="srv:8080", authorization=basic)
assert st == 200 and h["set-cookie"].startswith(S.COOKIE + "=") and "SameSite=Strict" in h["set-cookie"]
assert "HttpOnly" in h["set-cookie"] and "Secure" not in h["set-cookie"]
st, h = call(G, host="srv:8080", authorization=basic, x_forwarded_proto="https")
assert "; Secure" in h["set-cookie"]                       # behind a TLS proxy
cookie = h["set-cookie"].split(";")[0]
assert call(G, host="srv:8080", cookie=cookie)[0] == 200 and "set-cookie" not in call(G, host="srv:8080", cookie=cookie)[1]
assert call(G, "/_nicegui_ws/", "websocket", host="srv:8080", origin="http://srv:8080", cookie=cookie)[0] == "websocket.accept"
assert call(G, "/_nicegui_ws/", "websocket", host="srv:8080", origin="http://srv:8080")[0] == "websocket.close"

# cross-site guard: refused even with a valid login (the browser would send the cookie or cached Basic credentials)
assert call(G, "/api/favorites/remove", host="srv:8080", cookie=cookie, sec_fetch_site="cross-site",
            sec_fetch_mode="no-cors")[0] == 403
assert call(G, "/api/favorites/remove", host="srv:8080", cookie=cookie, sec_fetch_site="cross-site",
            sec_fetch_mode="navigate")[0] == 403              # a link to an /api address
assert call(G, "/", host="srv:8080", cookie=cookie, sec_fetch_site="cross-site", sec_fetch_mode="navigate")[0] == 200
assert call(G, "/out/hits_report.html", host="srv:8080", cookie=cookie, sec_fetch_site="cross-site",
            sec_fetch_mode="no-cors")[0] == 403
assert call(G, "/api/favorites/keys", host="srv:8080", cookie=cookie, sec_fetch_site="same-origin")[0] == 200
assert call(G, "/api/x", host="srv:8080", cookie=cookie, origin="http://evil.example")[0] == 403   # no Sec-Fetch
assert call(G, "/_nicegui_ws/", "websocket", host="srv:8080", origin="http://evil.example",
            cookie=cookie)[0] == "websocket.close"

# local mode: no login, the cross-site guard stays
L = S.Guard(inner, None)
assert call(L, "/", host="127.0.0.1:8080")[0] == 200
assert call(L, "/api/favorites/keys", host="127.0.0.1:8080", sec_fetch_site="same-origin")[0] == 200
assert call(L, "/api/favorites/remove", host="127.0.0.1:8080", sec_fetch_site="cross-site", sec_fetch_mode="no-cors")[0] == 403
assert call(L, "/_nicegui_ws/", "websocket", host="127.0.0.1:8080", origin="http://127.0.0.1:8080")[0] == "websocket.accept"
assert call(L, "/_nicegui_ws/", "websocket", host="127.0.0.1:8080", origin="https://evil.example")[0] == "websocket.close"
assert call(L, "/_nicegui_ws/", "websocket", host="127.0.0.1:8080")[0] == "websocket.accept"   # no Origin: not a page
print("SERVER MODE TESTS PASSED")

# tokens for programs: read-only, /api/v1/ and /fav/ only
with tempfile.TemporaryDirectory() as d:
    p = os.path.join(d, S.AUTH_FILE)
    S.save_auth(p, auth)
    tok = S.new_token(p, "PyStarLight")
    assert tok.startswith("pysz_") and tok not in open(p).read()
    a2 = S.load_auth(p)
    assert S.token_ok(a2, tok) == "PyStarLight" and S.token_ok(a2, tok + "x") is None
    T = S.Guard(inner, auth, path=p)                        # the file is read again: the new token works at once
    bearer = "Bearer " + tok
    assert call(T, "/api/v1/favorites", host="srv:8080", authorization=bearer)[0] == 200
    assert call(T, "/fav/x/x.svg", host="srv:8080", authorization=bearer)[0] == 200
    assert call(T, "/", host="srv:8080", authorization=bearer)[0] == 403              # not the GUI
    assert call(T, "/api/favorites/remove", host="srv:8080", authorization=bearer)[0] == 403
    assert call(T, "/api/v1/favorites", host="srv:8080", authorization="Bearer pysz_wrong")[0] == 401
    st, h = call(T, "/api/v1/favorites", host="srv:8080", authorization=bearer)
    assert "set-cookie" not in h                                                       # no session for programs
    # a new password keeps the tokens, but logs browsers out
    S.save_auth(p, S.make_auth("observer", "other-pass", S.load_auth(p)["tokens"]))
    assert call(T, "/api/v1/favorites", host="srv:8080", authorization=bearer)[0] == 200
    assert call(T, "/", host="srv:8080", cookie=cookie)[0] == 401
    assert S.revoke_token(p, "PyStarLight") and not S.revoke_token(p, "PyStarLight")
    assert call(T, "/api/v1/favorites", host="srv:8080", authorization=bearer)[0] == 401
print("TOKEN TESTS PASSED")

# pointing.py: selection by time window, status, site; the apparent place (erfa, if installed)
from pysyzygos import pointing as P
fav = lambda k, utc, st="planned", site="Home": dict(key=k, status=st, site=dict(name=site),
                                                       record=dict(best_utc=utc, star_ra="56.36", star_dec="14.05"))
E = [fav("b", "2026-11-02T03:00:00"), fav("a", "2026-11-01T22:00:00.5"), fav("c", "2026-11-05T01:00:00", "done"),
     fav("d", "2026-11-03T01:00:00", site="Observatory"), fav("x", "")]
assert [e["key"] for e in P.select(E)] == ["a", "b", "d", "c"]
assert [e["key"] for e in P.select(E, "2026-11-02T00:00Z")] == ["b", "d", "c"]
assert [e["key"] for e in P.select(E, to="2026-11-02T03:00:00")] == ["a", "b"]
assert [e["key"] for e in P.select(E, status="planned,observed", site="home")] == ["a", "b"]
assert [e["key"] for e in P.select(E, limit=1)] == ["a"]
try:
    P.select(E, "yesterday")
    raise AssertionError("bad time accepted")
except ValueError:
    pass
try:
    import erfa  # noqa: F401
    ra, dec = P.apparent(56.361111688398715, 14.053753835648845, P._utc("2026-10-17T04:36:28.345"))
    assert abs(ra - 56.742350767510395) < 1e-6 and abs(dec - 14.139654084700615) < 1e-6, (ra, dec)  # = astropy TETE
except ImportError:
    pass
print("POINTING TESTS PASSED")
