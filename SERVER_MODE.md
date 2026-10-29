# PySyzygos server mode: the GUI from the observatory computer, a phone, or another program

Normally PySyzygos runs on your own computer and only that computer can open it (`http://127.0.0.1:8080`). In
**server mode** it runs on one computer at home, the one with the star catalog, the kernels and the memory for
picks, and you use it from any browser on your network: the observatory computer, a phone, a tablet. Other
programs, such as a camera or mount app, can read your favorites from it to point the telescope.

It is meant for **one user** for now: everyone who logs in shares the same sites, results and favorites. The local
mode (`pysyzygos`, 127.0.0.1) is unchanged.

Contents:
- [1. Password, then start](#1-password-then-start)
- [2. What is different in server mode](#2-what-is-different-in-server-mode)
- [3. Keep it running: systemd](#3-keep-it-running-systemd)
- [4. Encrypt it: HTTPS](#4-encrypt-it-https)
- [5. From outside your home network](#5-from-outside-your-home-network-phone-on-mobile-data-a-remote-observatory)
- [6. Programs: the favorites API](#6-programs-the-favorites-api-eg-a-camera-app-pointing-the-telescope)
- [7. Phones and tablets](#7-phones-and-tablets)
- [8. Behind a proxy that has its own login](#8-behind-a-proxy-that-has-its-own-login)
- [9. Security notes](#9-security-notes)
- [10. Not yet](#10-not-yet)

## 1. Password, then start

```bash
pysyzygos gui --set-password               # once: user name and password
pysyzygos gui --host 0.0.0.0 --port 8080   # all network interfaces: server mode
```

Open `http://<server name or address>:8080` on the other device. The browser asks once for the login, then
remembers it for 30 days (a session cookie). Running `--set-password` again changes the password and logs every
browser out (program tokens stay valid, see section 6).

Without a password, server mode does not start (it tells you to run `--set-password`). The password is stored
hashed (PBKDF2-SHA256), never in clear, in `server_auth.json` in your data folder, readable by you only; `pysyzygos
cleanup --all` removes it.

Any `--host` other than this computer (127.0.0.1, localhost) turns server mode on. `--server` turns it on for
127.0.0.1 as well, for a proxy on the same computer (sections 4 and 5).

## 2. What is different in server mode

| | local mode (`pysyzygos`) | server mode |
|---|---|---|
| listens on | 127.0.0.1 (this computer) | `--host` (e.g. 0.0.0.0) |
| login | none | user + password, then a 30-day cookie |
| KStars / Stellarium buttons, "set its location" option | yes | off: they would move the planetarium on the server |
| Quit | yes | off; Restart stays (otherwise the service would stay down until you are at the server) |
| browser opened at start | yes | no |
| favorites API for programs | open on 127.0.0.1 | with a token per program |

Both modes refuse requests made by pages of other web sites: a page of another site open in the same browser
cannot delete favorites or start runs.

## 3. Keep it running: systemd

[deploy/pysyzygos.service](deploy/pysyzygos.service) is a systemd **user** service: it runs as you, with your data
folder.

```bash
mkdir -p ~/.config/systemd/user && cp deploy/pysyzygos.service ~/.config/systemd/user/
# edit ExecStart (the path of your checkout) and, if needed, PYSYZYGOS_HOME
systemctl --user daemon-reload && systemctl --user enable --now pysyzygos
sudo loginctl enable-linger $USER          # keep it running when you are logged out, and start it at boot
```

Afterwards: `systemctl --user restart pysyzygos`, its output: `journalctl --user -u pysyzygos -f`. The GUI's
Restart button (power icon) works under systemd too.

## 4. Encrypt it: HTTPS

Without HTTPS the password and all pages travel readable on the network. That is fine on a home network you trust,
not on a shared one (an observatory club's Wi-Fi, a hotel).

With [Caddy](https://caddyserver.com) in front ([deploy/Caddyfile](deploy/Caddyfile)), PySyzygos listens on the
server only and Caddy does HTTPS:

```bash
pysyzygos gui --host 127.0.0.1 --port 8080 --server
```

For a name on your home network, Caddy makes its own certificate authority (`tls internal`): trust it once on each
device, or accept the browser's warning once. The session cookie is then marked Secure. Caddy passes the
WebSocket and the Host header through by itself; another proxy (nginx) must be set up to do both.

## 5. From outside your home network (phone on mobile data, a remote observatory)

Do **not** open a port on the router: PySyzygos starts programs and holds your site coordinates, and the login would
be the only barrier. Use a private network instead:

- **Tailscale** (easiest; free for personal use): install it on the server and the phone, log in to the same
  account; the phone reaches the server under its Tailscale name. `tailscale serve --bg 8080` adds HTTPS with a
  real certificate (then start PySyzygos with `--host 127.0.0.1 --server`). The built-in login stays on.
- **WireGuard** or your router's VPN: the same idea, set up yourself.

## 6. Programs: the favorites API (e.g. a camera app pointing the telescope)

Your favorites, read-only as JSON, for a camera or mount program: the event time, the shadow window, and the star's
position for pointing, altitude and azimuth from the favorite's site, names (UCAC4, Gaia DR3, TYC, HIP), magnitude
and drop.

### Tokens

Give each program its own token instead of your password:

```bash
pysyzygos gui --new-token PyStarLight      # shown once: put it in the program's settings
pysyzygos gui --list-tokens
pysyzygos gui --revoke-token PyStarLight   # e.g. if the device is lost
```

The program sends it in every request: `Authorization: Bearer <token>`. A token only reads `/api/v1/...` and
`/fav/...` (the favorites' preview and map files): it cannot open the GUI, start runs or change favorites. A new or
revoked token counts at once, without a restart. On the same computer in local mode (127.0.0.1) the API needs no
token.

### Requests

| request | answer |
|---|---|
| `GET /api/v1/` | version and endpoints |
| `GET /api/v1/favorites?from=now&to=2026-11-30&status=planned&site=Home&limit=10` | favorites by event time (all filters optional; `status` comma-separated) |
| `GET /api/v1/favorites/next` | the next event from now (`from`, `status`, `site` as above); `null` if there is none |
| `GET /api/v1/favorites/<key>` | one favorite (key as in the favorites list, e.g. `158772_20261017T0436`) |

Times are UTC (ISO 8601, a date alone, or `now`). A bad time answers 400, an unknown key 404.

### The answer for one favorite

```json
{
 "key": "158772_20261017T0436", "status": "planned", "note": "",
 "target": {"id": "158772", "name": "158772 (2003 SB60)", "kind": "asteroid", "radius_km": 1.91},
 "utc": "2026-10-17T04:36:28.345",
 "shadow_from_utc": "2026-10-17T04:31:45", "shadow_to_utc": "2026-10-17T04:55:30",
 "duration_s": 0.261, "max_duration_s": 0.493, "mag_drop": 10.35, "chance": 0.113,
 "star": {"name": "UCAC4 521-006590", "other_names": ["Gaia DR3 38249436846981120", "TYC 664-451-1"],
          "gaia_dr3": "38249436846981120", "mag_g": 9.333,
          "ra_icrs": 56.361112, "dec_icrs": 14.053754, "ra_app": 56.742351, "dec_app": 14.139654,
          "alt": 41.80, "az": 233.35},
 "sun_alt": -17.9, "moon_alt": -65.9, "moon_sep": 138.9,
 "site": {"name": "Royal Observatory", "lat": 51.47738, "lon": 0.0, "ele_m": 66.0, "tz": "Europe/London"},
 "files": {"kml": "/fav/.../....kml", "svg": "/fav/.../....svg", "globe": "/fav/.../..._globe.svg"}
}
```

Angles in degrees:
- `ra_icrs`, `dec_icrs`: the search's corrected star position at the event (Gaia proper motion to the event date,
  parallax, light deflection) in ICRS axes: what most mount drivers call "J2000".
- `ra_app`, `dec_app`: the apparent place of date (true equator and equinox, aberration included): "JNow", for
  drivers that want it.
- `alt`, `az`: at the event time from the favorite's site; `az` from north through east; refraction not included.
- `chance`: the probability that the shadow passes the site (0 to 1); `null` where unknown.

The field names of `/api/v1/` stay as they are; changes would come as `/api/v2/`.

### In Python

```python
import requests
r = requests.get("http://server:8080/api/v1/favorites/next",
                 headers={"Authorization": "Bearer pysz_..."}, timeout=10)
ev = r.json()["favorite"]                    # None if there is no later favorite
star = ev["star"]
print(ev["utc"], ev["target"]["name"], star["name"], star["ra_icrs"], star["dec_icrs"])   # or ra_app / dec_app
```

## 7. Phones and tablets

The pages work in mobile browsers, but the layout is made for a computer screen: wide tables (Results, Favorites)
scroll sideways. Fine for looking at tonight's events, a favorite's map and preview, or starting a search; setting
up sites and catalogs is easier at a computer.

## 8. Behind a proxy that has its own login

`--no-auth` turns the built-in login off (server mode otherwise). Only when a proxy in front asks for a login for
every request (e.g. Authelia, oauth2-proxy) and PySyzygos listens on 127.0.0.1. Tokens are not checked then: the
proxy decides who gets in.

## 9. Security notes

- The login is HTTP Basic once per browser, then a signed session cookie (HttpOnly, SameSite=Strict, Secure over
  HTTPS), checked on every request, including the GUI's WebSocket. A wrong password or token waits a second
  before the answer (slows guessing).
- Basic sends the password in the first request: use HTTPS (section 4) or a private network (section 5) where
  others could read the traffic.
- Requests to `/api/...` and the WebSocket must come from the GUI's own pages; other paths refuse cross-site
  requests except a plain link or bookmark to the GUI. This guard is on in local mode too.
- Tokens are random 256-bit values, stored as SHA-256 hashes; they are shown once when made.
- Everything that can start programs (search, pick, setup, update) needs the login; tokens cannot.

## 10. Not yet

Several users with their own sites and results (one PySyzygos process per user behind a small front end), a job
queue shared between users, a layout for phones.
