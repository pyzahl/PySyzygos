"""server_mode.py - the GUI in server mode (intranet, one user for a start), beside the local mode.

    pysyzygos gui --set-password                 # once: user name and password (stored hashed in the data folder)
    pysyzygos gui --host 0.0.0.0 --port 8080     # server mode: reachable from other computers, login required
    pysyzygos gui --new-token PyStarLight        # a read-only token for another program (pointing.py's API)

Local mode (the default, 127.0.0.1) is unchanged except for the cross-site guard, which protects both modes.
Server mode (`--host` other than this computer, or `--server`):
  - login: HTTP Basic once per browser, then a signed session cookie (SameSite=Strict, HttpOnly; Secure over https),
    checked on every request, the NiceGUI WebSocket included. The password is stored as PBKDF2-SHA256 in
    <data folder>/server_auth.json (mode 600), never in clear.
  - parts that act on the computer the GUI runs on, not on the user's, are off: KStars and Stellarium buttons
    (they would move the server's planetarium), Quit (Restart stays: under systemd the service would stay down).
  - no browser is opened on the server.
  - programs (a camera or mount app) use a token instead of the password: "Authorization: Bearer <token>", only
    for GET /api/v1/... and /fav/... (read-only: favorites for pointing, pysyzygos/pointing.py). Tokens are
    stored as SHA-256 (random 256-bit values: no slow hash needed), shown once when made, revoked by name.
Basic auth sends the password in every request until the cookie is set: over plain http on an intranet that is
readable on the wire, so put a TLS proxy (Caddy, nginx: deploy/) in front when the network is not trusted.
User documentation: SERVER_MODE.md (keep it in step).

Cross-site guard (both modes): a page of another site open in the same browser must not drive the GUI. Requests
to /api/... and the WebSocket must come from this origin (Sec-Fetch-Site same-origin/none, or an Origin equal to
the Host); other paths refuse cross-site requests except a plain navigation (a link or bookmark to the GUI).
Before, any web page could call e.g. /api/favorites/remove on 127.0.0.1:8080 with an image tag.
Standard library only (pure ASGI), so tests run without NiceGUI."""
from pysyzygos.version import __version__
import asyncio, base64, hashlib, hmac, json, os, secrets, time

AUTH_FILE = "server_auth.json"           # in the data folder (gitignored, cleanup --all)
COOKIE = "pysyzygos_session"
SESSION_DAYS = 30
ITERATIONS = 300_000                      # PBKDF2-SHA256 rounds (~0.2 s per check: only at login, not per request)
FAIL_DELAY_S = 1.0                        # a wrong password waits (slows guessing)
LOOPBACK = ("127.0.0.1", "localhost", "::1")
TOKEN_PATHS = ("/api/v1/", "/fav/")       # what a token may read (GET only)

MODE = dict(server=False)                # set by gui.main; read by the GUI parts that act on this computer


def is_loopback(host):
    return str(host).strip("[]") in LOOPBACK


# ---------------------------------------------------------------- the password file
def _hash(password, salt, iterations):
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations).hex()


def make_auth(user, password, tokens=None):
    """The stored record: user, salt, PBKDF2 hash, iterations, the secret that signs session cookies (new each
    time: setting a password logs every browser out) and the programs' tokens (kept)."""
    salt = secrets.token_bytes(16)
    return dict(user=user, salt=salt.hex(), hash=_hash(password, salt, ITERATIONS), iterations=ITERATIONS,
                secret=secrets.token_hex(32), set=time.strftime("%Y-%m-%d %H:%M:%S"), version=__version__,
                tokens=dict(tokens or {}))


def save_auth(path, auth):
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(auth, f, indent=1)
    os.replace(tmp, path)


def load_auth(path):
    """The record, or None if there is none (or it is unreadable)."""
    try:
        with open(path, encoding="utf-8") as f:
            a = json.load(f)
        return a if all(k in a for k in ("user", "salt", "hash", "secret")) else None
    except (OSError, ValueError):
        return None


def check_password(auth, user, password):
    if not hmac.compare_digest(str(user), str(auth["user"])):
        return False
    h = _hash(password, bytes.fromhex(auth["salt"]), int(auth.get("iterations", ITERATIONS)))
    return hmac.compare_digest(h, auth["hash"])


def set_password_interactive(path):
    """pysyzygos gui --set-password: asks for user name and password (twice), saves the record."""
    import getpass
    old = load_auth(path)
    user = input(f"user name [{(old or {}).get('user') or 'observer'}]: ").strip() or (old or {}).get("user") or "observer"
    while True:
        p1 = getpass.getpass("password (at least 8 characters): ")
        if len(p1) < 8:
            print("too short")
            continue
        if getpass.getpass("again: ") == p1:
            break
        print("not the same, once more")
    save_auth(path, make_auth(user, p1, (old or {}).get("tokens")))
    print(f"saved {path} (hashed; open browsers have to log in again; program tokens kept)")


# ---------------------------------------------------------------- tokens for programs (read-only)
def _token_hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_token(path, name):
    """A new token for a program, saved by name (an old one of that name is replaced); returns it (shown once)."""
    auth = load_auth(path)
    if auth is None:
        raise SystemExit("set the password first: pysyzygos gui --set-password")
    token = "pysz_" + secrets.token_urlsafe(32)
    auth.setdefault("tokens", {})[name] = dict(sha256=_token_hash(token), created=time.strftime("%Y-%m-%d %H:%M:%S"))
    save_auth(path, auth)
    return token


def revoke_token(path, name):
    auth = load_auth(path) or {}
    gone = (auth.get("tokens") or {}).pop(name, None) is not None
    if gone:
        save_auth(path, auth)
    return gone


def token_names(auth):
    return {n: t.get("created", "") for n, t in ((auth or {}).get("tokens") or {}).items()}


def token_ok(auth, token):
    """The token's name if it is one of the record's, else None."""
    if not token:
        return None
    h = _token_hash(token)
    return next((n for n, t in (auth.get("tokens") or {}).items() if hmac.compare_digest(h, t.get("sha256", ""))), None)


def token_main(path, new=None, revoke=None, listing=False):
    """pysyzygos gui --new-token NAME | --revoke-token NAME | --list-tokens"""
    if new:
        tok = new_token(path, new)
        print(f"token {new!r} (shown only now; store it in the program's settings):\n\n  {tok}\n\n"
              f"use: Authorization: Bearer <token>, read-only (GET /api/v1/..., /fav/...)")
    if revoke:
        print(f"token {revoke!r} " + ("revoked" if revoke_token(path, revoke) else "not found"))
    if listing:
        names = token_names(load_auth(path))
        print("\n".join(f"  {n:24s} made {c}" for n, c in names.items()) if names else "no tokens")


# ---------------------------------------------------------------- session cookies
def make_cookie(auth, now=None):
    exp = int((now or time.time()) + SESSION_DAYS * 86400)
    sig = hmac.new(bytes.fromhex(auth["secret"]), f"{auth['user']}|{exp}".encode(), hashlib.sha256).hexdigest()
    return f"{exp}.{sig}"


def cookie_ok(auth, value, now=None):
    try:
        exp, sig = value.split(".", 1)
        if int(exp) < (now or time.time()):
            return False
    except (AttributeError, ValueError):
        return False
    good = hmac.new(bytes.fromhex(auth["secret"]), f"{auth['user']}|{exp}".encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, good)


def _cookies(headers):
    out = {}
    for part in headers.get("cookie", "").split(";"):
        k, _, v = part.strip().partition("=")
        if k:
            out[k] = v
    return out


def _bearer(headers):
    h = headers.get("authorization", "")
    return h[7:].strip() if h.lower().startswith("bearer ") else None


def _basic(headers):
    """(user, password) from an Authorization: Basic header, else None."""
    h = headers.get("authorization", "")
    if not h.lower().startswith("basic "):
        return None
    try:
        user, _, pw = base64.b64decode(h[6:].strip()).decode("utf-8").partition(":")
        return user, pw
    except (ValueError, UnicodeDecodeError):
        return None


# ---------------------------------------------------------------- the cross-site rule
def cross_site_refused(scope, headers):
    """A short reason when this request comes from another site's page, else None (see the module text)."""
    path = scope.get("path", "")
    site = headers.get("sec-fetch-site")                    # sent by all current browsers
    origin = headers.get("origin")
    host = headers.get("host", "")
    foreign_origin = bool(origin) and origin != "null" and origin.split("://", 1)[-1] != host
    if scope["type"] == "websocket":
        return "WebSocket from another origin" if (foreign_origin or origin == "null") else None
    if site in ("cross-site", "same-site"):
        if path.startswith("/api/"):
            return f"/api request from another site ({site})"
        if headers.get("sec-fetch-mode") != "navigate":
            return f"request from another site ({site})"
    if site is None and foreign_origin:                      # older browsers: the Origin header
        return "request from another origin"
    return None


# ---------------------------------------------------------------- the ASGI guard
class Guard:
    """ASGI middleware: cross-site guard always; with auth (server mode) a login for every request and the
    WebSocket. auth: the record of load_auth, or None (local mode, or --no-auth behind an authenticating proxy);
    path: the record's file, read again when it changes (a token made while the GUI runs works at once)."""

    def __init__(self, app, auth=None, path=None):
        self.app, self.auth, self.path, self._mtime = app, auth, path, None

    def _reload(self):
        try:
            st = os.stat(self.path)
        except OSError:
            return
        m = (st.st_ino, st.st_mtime_ns)                     # save_auth replaces the file: a new inode each time
        if m != self._mtime:
            self._mtime = m
            self.auth = load_auth(self.path) or self.auth

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        why = cross_site_refused(scope, headers)
        if why:
            return await self._refuse(scope, send, 403, why)
        if self.auth is None:
            return await self.app(scope, receive, send)
        if self.path:
            self._reload()
        token = _bearer(headers)
        if token is not None:
            if not token_ok(self.auth, token):
                await asyncio.sleep(FAIL_DELAY_S)
                return await self._refuse(scope, send, 401, "unknown token")
            if scope["type"] != "http" or scope.get("method", "GET") not in ("GET", "HEAD") \
                    or not scope.get("path", "").startswith(TOKEN_PATHS):
                return await self._refuse(scope, send, 403, "a token only reads /api/v1/ and /fav/")
            return await self.app(scope, receive, send)
        if cookie_ok(self.auth, _cookies(headers).get(COOKIE)):
            return await self.app(scope, receive, send)
        cred = _basic(headers)
        if cred and await asyncio.to_thread(check_password, self.auth, *cred):
            if scope["type"] == "websocket":
                return await self.app(scope, receive, send)
            secure = scope.get("scheme") == "https" or headers.get("x-forwarded-proto") == "https"
            cookie = (f"{COOKIE}={make_cookie(self.auth)}; Path=/; Max-Age={SESSION_DAYS * 86400}; HttpOnly; "
                      f"SameSite=Strict" + ("; Secure" if secure else ""))

            async def send_with_cookie(msg):
                if msg["type"] == "http.response.start":
                    msg = dict(msg, headers=list(msg.get("headers", [])) + [(b"set-cookie", cookie.encode())])
                await send(msg)
            return await self.app(scope, receive, send_with_cookie)
        if cred:
            await asyncio.sleep(FAIL_DELAY_S)
        return await self._refuse(scope, send, 401, "login required")

    @staticmethod
    async def _refuse(scope, send, status, why):
        if scope["type"] == "websocket":
            return await send({"type": "websocket.close", "code": 1008})
        body = f"PySyzygos: {why}\n".encode()
        headers = [(b"content-type", b"text/plain; charset=utf-8"), (b"content-length", str(len(body)).encode())]
        if status == 401:
            headers.append((b"www-authenticate", b'Basic realm="PySyzygos", charset="UTF-8"'))
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": body})
