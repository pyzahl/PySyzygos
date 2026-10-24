"""gui_site.py - Site tab: the observing sites (sites.py) on a map, their equipment and view, the star limits of the
runs, the horizon (OccultWatcher file or 360-degree photo).

Part of the GUI (gui.py builds the page): panel(pg) adds the tab's controls, handlers(pg) its functions, connect(pg)
wires them up; pg holds the page's elements and functions shared between the tabs.
"""
import math, os, re

from pysyzygos import cameras, geo, starcat
from pysyzygos.home import HOME as ROOT
from nicegui import background_tasks, run, ui
from pysyzygos.sitesfile import load_sites, save_sites
from pysyzygos.gui_common import SITE_KEYS, fov, load_ui_state, mag_limit, save_ui_state


def panel(pg):
    """The site tab's controls (inside its ui.tab_panel)."""
    with ui.tab_panel(pg.t_site):
        with ui.row().classes("w-full items-end gap-4"):
            pg.site_title = ui.label().classes("text-lg font-semibold")
            pg.new_name = ui.input("New site name").classes("w-48")
            ui.button("Add site", on_click=lambda: pg.add_site()).props("outline").tooltip(
                "The position, equipment and limits in the form as a new site named above; its description, horizon "
                "and photo only if you changed them here (nothing else of the site shown carries over)")
            pg.is_default = ui.checkbox("Default for command-line runs").tooltip(
                "default_site in sites.py: used by `pysyzygos search` / `pysyzygos pick` run without the GUI")
            pg.save_btn = ui.button("Save sites.py", on_click=lambda: pg.save()).props("color=primary")
            ui.button("Remove site", on_click=lambda: pg.remove_site()).props("outline color=negative").tooltip(
                "Remove the site selected at the top right from sites.py (asks first; saved at once)")
            pg.unsaved = ui.label().classes("text-sm text-amber-700")
        with ui.row().classes("w-full no-wrap gap-4"):
            with ui.column().classes("w-1/2"):
                pg.m = ui.leaflet(center=(40.7, -74.0), zoom=9).classes("w-full").style("height: 430px")
                pg.marker = pg.m.marker(latlng=(40.7, -74.0))
                with ui.row().classes("w-full items-end"):
                    pg.q = ui.input("Find a place").classes("grow")
                    ui.button("Search", on_click=lambda: pg.find_place()).props("outline")
                    ui.button("My IP location", on_click=lambda: pg.ip_loc()).props("outline")
                pg.hits = ui.column().classes("w-full gap-1")
                pg.occ = geo.mpc_observatories()               # MPC observatory codes (downloaded once into data/)
                with ui.row().classes("w-full no-wrap gap-4"):
                    pg.occ_sel = ui.select({i: f"{x['code']} {x['name']}" for i, x in enumerate(pg.occ)},  # searchable:
                                                                                  # code and name only
                                           with_input=True, clearable=True,
                                           label="MPC observatory (type code or name)" if pg.occ else
                                           "MPC observatory list: not available (offline?)").classes("w-1/2").props(
                        "dense options-dense" + ("" if pg.occ else " disable")).tooltip(
                        f"{len(pg.occ)} observatories with their official MPC codes (Minor Planet Center): sets position, "
                        "elevation, description and MPC code; the equipment stays as it is")
                    pg.cam_sel = ui.select({i: cameras.label(c) for i, c in enumerate(cameras.SENSORS)},
                                           with_input=True, clearable=True,
                                           label="Sensor (cameras; type a name)").classes(
                        "grow").props("dense options-dense").tooltip(
                        "Sensors common in occultation work, each with the cameras built with it (MM / MC, M / C: "
                        "the mono and color versions of a camera, same sensor size). Picking one fills sensor "
                        "width and height, computed from pixel count and pixel size. Not listed, or a cropped "
                        "readout: enter width and height yourself")
                ui.button("Add as new site", on_click=lambda: pg.add_site()).props("outline").tooltip(
                    "Add the current map site (position, description, MPC code and the equipment in the form) as a "
                    "new site to the site selector at the top right, named as in 'New site name'; saved at once")
                ui.label("Click the map to set the position; the elevation is looked up. "
                         "Use an exact position (GPS, map) for observing.").classes("text-xs text-slate-500")
            with ui.column().classes("w-1/2"):
                with ui.row().classes("w-full no-wrap gap-4"):
                    pg.desc = ui.input("Description").classes("grow")
                    pg.mpc = ui.input("MPC code").classes("w-28").tooltip(
                           "The site's official Minor Planet Center observatory code, if it has one (kept in sites.py "
                        "as mpc_code; filled in when you pick an observatory below)")
                with ui.row():
                    paste_tip = ("Paste coordinates in any usual format into Latitude, Longitude or Elevation, "
                                 "e.g. Lng: -121° 57' 19\", Lat: +37° 01' 27\", Alt: 132 m  or  37.02417, "
                                 "-121.95528  or  37°01'27\"N 121°57'19\"W: all three fields are filled (the "
                                 "elevation is looked up if not given)")
                    pg.lat = ui.number("Latitude (°)", format="%.5f", step=0.0001).tooltip(paste_tip)
                    pg.lon = ui.number("Longitude (°, east +)", format="%.5f", step=0.0001).tooltip(paste_tip)
                    pg.ele = ui.number("Elevation (m)", format="%.0f", step=1).tooltip(paste_tip)
                    pg.ele_ref = ui.select({"msl": "above sea level", "ellipsoid": "above WGS84 ellipsoid"},
                                           value="msl", label="Elevation is").tooltip(
                        "Maps, Open-Meteo and most GPS displays give the height above mean sea level; PySyzygos "
                        "adds the geoid's height there (EGM96, saved in sites.py as geoid_m). MPC observatory "
                        "codes (and GPS set to ellipsoid height) give it above the WGS84 ellipsoid already.")
                pg.fields = {}
                with ui.grid(columns=3).classes("w-full"):
                    for key, label, default, step in SITE_KEYS:
                        pg.fields[key] = ui.number(label, value=default, step=step)
                pg.derived = ui.label().classes("text-sm text-slate-600")
                with ui.expansion("Horizon (optional): trees, buildings, hills").classes("w-full") as hz_exp:
                    ui.label("Load OccultWatcher's UserHorizon.txt (the same file works in both programs) for "
                             "the site in this form, then save the site: events whose star is behind your horizon "
                             "are marked \u26f0 yellow, those closer to it than the margin red, in the results and "
                             "favorites. A file with several stations: the one named like the site, else the "
                             "first.").classes(
                        "text-xs text-slate-500")
                    with ui.row().classes("items-center gap-3"):
                        ui.upload(label="Load UserHorizon.txt", auto_upload=True,
                                  on_upload=lambda e: pg.hz_upload(e)).props("accept=.txt flat dense").classes("w-56")
                        pg.hz_margin = ui.number("Margin (°)", value=15, min=0, max=45, step=1).classes("w-28").tooltip(
                            "A star closer than this to the horizon line, in any direction, is marked (red); "
                            "OccultWatcher's default warning threshold is 15°")
                        pg.hz_filter = ui.checkbox("leave out events behind it").tooltip(
                            "Otherwise they are kept and marked yellow (as OccultWatcher does)")
                        ui.button("Remove", on_click=lambda: pg.hz_set(None)).props("flat dense color=negative")
                    with ui.row().classes("items-center gap-3"):
                        ui.upload(label="Load a 360° photo", auto_upload=True,
                                  on_upload=lambda e: pg.pano_upload(e)).props(
                            "accept=.jpg,.jpeg,.png flat dense").classes("w-56").tooltip(
                            "Equirectangular (2:1), as a 360° camera or a phone's photo sphere saves it, taken "
                            "level at the telescope. The horizon line is read from it: from a transparent sky (PNG), "
                            "or found automatically in a photo with a reasonably clear blue sky (check the line)")
                        pg.hz_az = ui.number("Azimuth at the photo's left edge (°)", value=0, min=0, max=360,
                                             step=0.5).classes("w-56").on_value_change(lambda e: pg.hz_draw())
                        pg.hz_fit = ui.button("Fit to the horizon line", on_click=lambda: pg.pano_fit()).props(
                            "flat dense").tooltip("Turn the photo so that its horizon lies best on the horizon "
                                                  "points above (needs a horizon line read from the photo)")
                        pg.hz_from = ui.button("Horizon from the photo", on_click=lambda: pg.pano_points()).props(
                            "flat dense").tooltip("The horizon points from the photo's horizon line (whole "
                                                  "degrees, as UserHorizon.txt); replaces the points above")
                        pg.hz_dl = ui.button("UserHorizon.txt", on_click=lambda: pg.hz_download()).props(
                            "flat dense").tooltip("Download the horizon as OccultWatcher's UserHorizon.txt")
                        ui.button("Remove photo", on_click=lambda: pg.pano_set(None)).props(
                            "flat dense color=negative")
                    with ui.row().classes("items-center gap-3"):
                        pg.hz_sun_in = ui.input("Sun at (site's local time)", placeholder="16:45:04 or 2026-10-22 16:45"
                                                ).classes("w-64").props("dense clearable").tooltip(
                            "When the photo was taken: the Sun's position then is drawn on the photo (yellow); turn "
                            "the photo (azimuth at its left edge) until the Sun in it sits in the ring. Time only: today")
                        ui.button("Show Sun", on_click=lambda: pg.hz_sun()).props("flat dense")
                        ui.button("Align by the Sun", on_click=lambda: pg.hz_sun_align()).props("flat dense").tooltip(
                            "Find the Sun's disk in the photo and set the azimuth at its left edge so that it sits at "
                            "the Sun's position at the time above")
                        pg.hz_sun_info = ui.label().classes("text-sm text-slate-600")
                    pg.hz_info = ui.label().classes("text-sm text-slate-600")
                    pg.hz_pic = ui.html("")


def handlers(pg):
    """The site tab's functions and state, as attributes of pg."""
    pg.SITE_GEN = [0]                     # counts site switches: an answer that arrives after a switch is dropped

    def stale(gen, what=""):
        """True (and a notice) if the site shown changed since gen: a lookup started for another site must not land
        in this one's form."""
        if gen == pg.SITE_GEN[0]:
            return False
        if what:
            ui.notify(f"{what}: not applied, the site was changed meanwhile", type="warning")
        return True
    pg.site_stale = stale

    def show_site(name):
        s = pg.sites[name]
        pg.SITE_GEN[0] += 1
        pg.state["name"] = name
        pg.lat.value, pg.lon.value, pg.ele.value, pg.desc.value = s["lat"], s["lon"], s["ele"], s.get("name", name)
        pg.ele_ref.value = s.get("ele_ref", "msl")
        pg.mpc.value = str(s.get("mpc_code", "") or "")
        for key, _, default, _ in SITE_KEYS:
            if key == "sensor_w_mm":
                pg.fields[key].value = s.get("sensor_mm", (5.6, 3.2))[0]
            elif key == "sensor_h_mm":
                pg.fields[key].value = s.get("sensor_mm", (5.6, 3.2))[1]
            else:
                pg.fields[key].value = s.get(key, default)
        pg.is_default.value = name == pg.state.get("default", pg.default_site)
        pg.hz_margin.value = s.get("horizon_margin", 15)
        pg.hz_filter.value = bool(s.get("horizon_filter", False))
        pg.HZ["image"] = s.get("horizon_image") if s.get("horizon_image") and os.path.isfile(s["horizon_image"]) else None
        pg.hz_az.value = float(s.get("horizon_image_az", 0.0))
        pg.HZ["sun"] = None                                          # the Sun marker belongs to the site shown before
        pg.hz_sun_info.text = ""
        pg.hz_sun_in.value = ""
        if pg.HZ["image"]:                                           # the photo's capture time, if it had one
            from pysyzygos import panorama
            taken = panorama.load_meta(pg.HZ["image"]).get("taken") or {}
            if taken.get("local") or taken.get("utc"):
                background_tasks.create(pg.hz_photo_time(pg.HZ["image"]))
        pg.hz_set([tuple(p) for p in s.get("horizon") or []] or None, s.get("horizon_name", ""))
        pg.site_title.text = f"Site: {name}"
        try:
            pg.load_pick()
            pg.prescreen_options()
        except NameError:                         # first call, while the page is built: load_pick() runs later
            pass
        for note in (pg.site_note_s, pg.site_note_p, pg.site_note_b):
            note.text = (f"Runs use site {name} ({s['lat']:.4f}, {s['lon']:.4f}, {s.get('aperture_cm', 25):g} cm); "
                         f"change it at the top right.")
        pg.marker.move(s["lat"], s["lon"])
        pg.m.set_center((s["lat"], s["lon"]))
        pg.update_derived()
    pg.show_site = show_site

    pg.HZ = dict(pts=None, name="", image=None, sun=None)           # the horizon in the form (horizon.py, panorama.py)
    pg.HZ_TZ = {}                                                     # site (lat, lon) -> IANA time zone (looked up once)

    async def hz_sun():
        """The Sun's azimuth and altitude at the form's site at the time typed (the site's local time; time only:
        today there), drawn on the photo to line it up (panorama.sun_altaz)."""
        import datetime as dt
        from zoneinfo import ZoneInfo
        from pysyzygos import panorama
        txt = (pg.hz_sun_in.value or "").strip()
        if not txt:
            pg.HZ["sun"] = None
            pg.hz_sun_info.text = ""
            pg.hz_draw()
            return
        try:
            la, lo = float(pg.lat.value), float(pg.lon.value)
        except (TypeError, ValueError):
            ui.notify("Set the site's position first", type="warning")
            return
        key = (round(la, 3), round(lo, 3))
        gen = pg.SITE_GEN[0]
        if key not in pg.HZ_TZ:
            pg.HZ_TZ[key] = await run.io_bound(geo.timezone, la, lo)
        if stale(gen):
            return
        tzname = pg.HZ_TZ.get(key)
        tz = ZoneInfo(tzname) if tzname else dt.datetime.now().astimezone().tzinfo
        m = re.fullmatch(r"(?:(\d{4}-\d\d-\d\d)[ T])?(\d{1,2}):(\d\d)(?::(\d\d(?:\.\d*)?))?\s*([aApP][mM])?", txt)
        if not m:
            ui.notify("Time as 16:45:04, 4:45:04 pm or 2026-10-22 16:45", type="warning")
            return
        day = dt.date.fromisoformat(m.group(1)) if m.group(1) else dt.datetime.now(tz).date()
        hh, mm, ss = int(m.group(2)), int(m.group(3)), float(m.group(4) or 0)
        if m.group(5):
            hh = hh % 12 + (12 if m.group(5).lower() == "pm" else 0)
        t = dt.datetime(day.year, day.month, day.day, hh, mm, int(ss), int((ss % 1) * 1e6), tzinfo=tz)
        az, alt = panorama.sun_altaz(la, lo, t)
        pg.HZ["sun"] = (az, alt)
        pg.hz_sun_info.text = (f"Sun at {t:%Y-%m-%d %H:%M:%S} {tzname or t.tzname()} "
                               f"({t.astimezone(dt.timezone.utc):%H:%M:%S} UTC): azimuth {az:.1f}°, altitude {alt:.1f}°"
                               + ("  (below the horizon)" if alt < -0.8 else ""))
        pg.hz_draw()
    pg.hz_sun = hz_sun

    async def hz_sun_align():
        from pysyzygos import panorama
        if not pg.HZ.get("image"):
            ui.notify("Load a 360° photo first", type="warning")
            return
        await hz_sun()
        if not pg.HZ.get("sun"):
            ui.notify("Type the photo's time first (Sun at ...)", type="warning")
            return
        gen = pg.SITE_GEN[0]
        found = await run.io_bound(panorama.sun_in_photo, pg.HZ["image"])
        if stale(gen, "Align by the Sun"):
            return
        if not found:
            ui.notify("No Sun found in the photo (no clear saturated disk above the horizon)", type="warning")
            return
        x_deg, alt_photo = found
        az, alt = pg.HZ["sun"]
        pg.hz_az.value = round((az - x_deg) % 360.0, 1)          # redraws (hz_az's change handler)
        ui.notify(f"Azimuth at the photo's left edge set to {pg.hz_az.value:.1f}° (the Sun's disk at {x_deg:.1f}° in "
                  f"the photo, its azimuth then {az:.1f}°); its height in the photo {alt_photo:.1f}° against "
                  f"{alt:.1f}°: save the site to keep it", type="positive", multi_line=True, timeout=10000)
    pg.hz_sun_align = hz_sun_align

    async def hz_photo_time(img):
        """The photo's capture time (panorama.photo_time, stored with it) into 'Sun at', in the site's local time.
        Returns the source of the time ('GPS time (UTC)', ...) or None."""
        import datetime as dt
        from zoneinfo import ZoneInfo
        from pysyzygos import panorama
        taken = panorama.load_meta(img).get("taken") if img else None
        if not taken:
            return None
        if taken.get("utc"):
            try:
                la, lo = float(pg.lat.value), float(pg.lon.value)
            except (TypeError, ValueError):
                return None
            key = (round(la, 3), round(lo, 3))
            gen = pg.SITE_GEN[0]
            if key not in pg.HZ_TZ:
                pg.HZ_TZ[key] = await run.io_bound(geo.timezone, la, lo)
            if stale(gen):
                return None
            tz = ZoneInfo(pg.HZ_TZ[key]) if pg.HZ_TZ.get(key) else dt.datetime.now().astimezone().tzinfo
            t = dt.datetime.fromisoformat(taken["utc"].replace("Z", "+00:00")).astimezone(tz)
            pg.hz_sun_in.value = t.strftime("%Y-%m-%d %H:%M:%S")
        else:
            pg.hz_sun_in.value = taken["local"]
        return taken.get("how")
    pg.hz_photo_time = hz_photo_time

    def hz_draw():
        from pysyzygos import horizon, panorama
        pts, img = pg.HZ["pts"], pg.HZ["image"]
        prof = panorama.load_meta(img).get("profile") if img else None
        pg.hz_fit.set_visibility(bool(img and prof and pts))
        pg.hz_from.set_visibility(bool(img and prof))
        pg.hz_dl.set_visibility(bool(pts))
        if img:
            pg.hz_pic.content = panorama.svg(img, float(pg.hz_az.value or 0), pts, float(pg.hz_margin.value or 15),
                                             width=900, sun=pg.HZ.get("sun"))
        else:
            pg.hz_pic.content = horizon.svg(pts, width=540, height=110) if pts else ""
        txt = (f"{pg.HZ['name'] or 'horizon'}: {len(pts)} points, highest {max(h for _, h in pts)}°" if pts
               else "no horizon: a flat horizon is assumed")
        pg.hz_info.text = txt + (f" · photo {os.path.basename(img)}" if img else "") + " (saved with the site)"
        try:
            pg.update_derived()                                         # marks "unsaved changes"
        except NameError:                                            # while the page is built
            pass
    pg.hz_draw = hz_draw

    def hz_set(pts, name=""):
        pg.HZ["pts"], pg.HZ["name"] = (pts, name) if pts else (None, "")
        pg.hz_draw()
    pg.hz_set = hz_set

    def pano_set(img):
        pg.HZ["image"] = img
        pg.hz_draw()
    pg.pano_set = pano_set

    async def pano_upload(e):
        from pysyzygos import panorama
        gen, site = pg.SITE_GEN[0], pg.state["name"]
        data = await e.file.read()
        e.sender.reset()
        try:
            img, meta = await run.io_bound(panorama.save, data, site, source=e.file.name)
        except Exception as ex:
            ui.notify(f"Not loaded: {ex}", type="warning", timeout=8000)
            return
        if stale(gen, f"Photo for site {site}"):
            return
        pg.HZ["image"] = img
        if meta.get("profile") and pg.HZ["pts"]:
            pg.pano_fit()
        pg.hz_draw()
        await photo_where(meta.get("where"))                         # the photo's GPS position: offer it for the site
        how_t = await hz_photo_time(img)                             # the capture time from the photo (EXIF)
        if how_t and not stale(gen):
            from pysyzygos import panorama
            ui.notify(f"Photo taken {pg.hz_sun_in.value} (site's local time; {how_t})", type="info", timeout=8000)
            if await run.io_bound(panorama.sun_in_photo, img) and not stale(gen):   # the Sun in it: align at once
                await pg.hz_sun_align()
            else:
                await pg.hz_sun()
        how = {"transparent sky": " (horizon line from its transparent sky)",
               "sky detection": " (horizon line found automatically: check it, e.g. with 'Horizon from the photo')"}
        ui.notify(f"Photo set for site {pg.state['name']}" + (how.get(meta.get("profile_from"), "") if meta.get("profile")
                  else " (no sky found: set the azimuth at its left edge by hand)") + ": save the site to keep it",
                  type="positive", timeout=8000)
    pg.pano_upload = pano_upload

    async def photo_where(where):
        """The photo has a GPS position more than 100 m from the form's: offer it for the site (the height then looked
        up, as for a click on the map; the photo's GPS height shown for comparison)."""
        import math
        if not where:
            return
        try:
            la, lo = float(pg.lat.value), float(pg.lon.value)
            d = 6371.0 * math.hypot(math.radians(where["lat"] - la),
                                    math.radians(where["lon"] - lo) * math.cos(math.radians(la)))
        except (TypeError, ValueError):
            d = None
        if d is not None and d < 0.1:
            ui.notify(f"The photo's GPS position agrees with the site's ({d * 1000:.0f} m)", type="info")
            return

        async def use():
            dlg.close()
            gen = pg.SITE_GEN[0]
            pg.set_position(where["lat"], where["lon"])
            pg.m.set_center((where["lat"], where["lon"]))
            el = await run.io_bound(geo.elevation, where["lat"], where["lon"])
            if stale(gen, "Height lookup"):
                return
            if el is not None:
                pg.ele.value = round(el)
                pg.ele_ref.value = "msl"
            ui.notify("Site position from the photo: save the site to keep it", type="positive")
        with ui.dialog() as dlg, ui.card().classes("max-w-lg"):
            ui.label("The photo has a GPS position").classes("font-semibold")
            ui.label(f"Photo: {where['lat']:.6f}, {where['lon']:.6f}"
                     + (f", {where['alt_m']:.0f} m (GPS height)" if where.get("alt_m") is not None else "")
                     + (f"\nSite: {la:.6f}, {lo:.6f}: {d:.2f} km apart" if d is not None else "")
                     ).classes("text-sm whitespace-pre-line")
            ui.label("Use the photo's position for this site? (The height is then looked up for it; a phone's GPS is "
                     "good to a few meters, the map's position may be better.)").classes("text-sm")
            with ui.row():
                ui.button("Use it", on_click=use).props("color=primary")
                ui.button("Keep the site's", on_click=dlg.close).props("flat")
        dlg.open()
    pg.photo_where = photo_where

    def pano_fit():
        from pysyzygos import panorama
        prof = panorama.load_meta(pg.HZ["image"]).get("profile") if pg.HZ["image"] else None
        if not (prof and pg.HZ["pts"]):
            return
        az0, d = panorama.fit_az_left(prof, pg.HZ["pts"])
        pg.hz_az.value = az0
        ui.notify(f"Azimuth at the left edge {az0:g}° (photo and horizon points differ by {d:.1f}° in the median)",
                  type="info", timeout=8000)
    pg.pano_fit = pano_fit

    def pano_points():
        from pysyzygos import panorama
        prof = panorama.load_meta(pg.HZ["image"]).get("profile") if pg.HZ["image"] else None
        if prof:
            pg.hz_set(panorama.points(prof, float(pg.hz_az.value or 0)), f"{pg.state['name']} (from the photo)")
    pg.pano_points = pano_points

    def hz_download():
        from pysyzygos import horizon
        if pg.HZ["pts"]:
            ui.download(horizon.to_text(pg.HZ["name"] or pg.state["name"], pg.HZ["pts"]).encode(), "UserHorizon.txt")
    pg.hz_download = hz_download

    async def hz_upload(e):
        from pysyzygos import horizon
        gen = pg.SITE_GEN[0]
        text = (await e.file.read()).decode("utf-8-sig", errors="replace")
        e.sender.reset()                                             # the same file can be loaded again
        if stale(gen, "Horizon file"):
            return
        try:
            stations = horizon.parse(text)
        except horizon.HorizonError as ex:
            ui.notify(f"Not loaded: {ex}", type="warning", timeout=8000)
            return
        site = pg.state["name"]
        names = list(stations)
        key = lambda x: "".join(ch for ch in x.lower() if ch.isalnum())
        pick = next((n for n in names if key(n) == key(site)), None) or \
            next((n for n in names if key(site) and key(site) in key(n)), None) or names[0]
        pg.hz_set(stations[pick], pick)
        more = f" (of {len(names)} stations in the file: {', '.join(names)})" if len(names) > 1 else ""
        ui.notify(f"Horizon '{pick}' set for site {site}{more}: save the site to keep it", type="positive",
                  timeout=8000)
    pg.hz_upload = hz_upload

    def collect():
        s = dict(lat=float(pg.lat.value or 0), lon=float(pg.lon.value or 0), ele=float(pg.ele.value or 0),
                 name=pg.desc.value or pg.state["name"])
        if pg.HZ["pts"]:
            s.update(horizon=[list(p) for p in pg.HZ["pts"]], horizon_name=pg.HZ["name"],
                     horizon_margin=float(pg.hz_margin.value or 15), horizon_filter=bool(pg.hz_filter.value))
        if pg.HZ["image"]:
            s.update(horizon_image=pg.HZ["image"].replace(os.sep, "/"), horizon_image_az=float(pg.hz_az.value or 0))
        if pg.ele_ref.value == "ellipsoid":
            s["ele_ref"] = "ellipsoid"                            # else above sea level: geoid_m added when saved
        if (pg.mpc.value or "").strip():
            s["mpc_code"] = pg.mpc.value.strip()
        for key, _, default, _ in SITE_KEYS:
            v = pg.fields[key].value
            if key in ("sensor_w_mm", "sensor_h_mm") or v is None or v == "":
                continue
            s[key] = int(v) if key == "frames" else float(v)
        s["sensor_mm"] = (float(pg.fields["sensor_w_mm"].value or 5.6), float(pg.fields["sensor_h_mm"].value or 3.2))
        from pysyzygos import geoid
        return geoid.fill(s)                              # geoid_m as saving would set it (an older file differs)
    pg.collect = collect

    def pick_mag_default(s):
        """Faintest star for the pick: the site's telescope limit, capped at the selected catalog's G limit."""
        return round(min(mag_limit(s), pg.cat_gmax.get(pg.cat_sel.value, 18.0)), 1)
    pg.pick_mag_default = pick_mag_default

    # the star G limits of Pick, Search and Planets & Moons: the site's default unless overridden (kept until reset with
    # the ↺ button, also across restarts: gui_state mag_override); a note says where the value comes from
    pg.MAG = dict(setting=False, override={k: float(v) for k, v in (load_ui_state().get("mag_override") or {}).items()})
    pg.INDEX_GB = {15: 1.2, 16: 2.6, 17: 5.0, 18: 10.0}             # bright-star index sizes on disk (measured: 15, 16, 18)

    def mag_fields():
        return {"pick": (pg.p_mag, pg.p_mag_note), "search": (pg.s_mag, pg.s_mag_note), "bodies": (pg.b_mag, pg.b_mag_note)}
    pg.mag_fields = mag_fields

    def mag_source(s):
        lim, cap = mag_limit(s), pg.cat_gmax.get(pg.cat_sel.value, 18.0)
        how = (f"mag_limit {float(s['mag_limit']):g} in sites.py" if s.get("mag_limit") else
               f"{s.get('aperture_cm', 25.0):g} cm, {int(s.get('frames', 4))} frames, longest exposure "
               f"{s.get('max_exp_s', 0.64):g} s, MagAdjust {s.get('mag_adjust', 0.0):+g}")
        return (f"Star limit from site {pg.state['name']}: {how} → G {lim:.1f}"
                + (f", capped at the catalog's {cap:g}" if lim > cap else ""))
    pg.mag_source = mag_source

    def mag_apply(s=None):
        s = s or pg.collect()
        d = pg.pick_mag_default(s)
        pg.MAG["setting"] = True
        try:
            for kind, (f, note) in pg.mag_fields().items():
                ov = pg.MAG["override"].get(kind)
                f.value = d if ov is None else ov
                v = float(f.value or d)
                text = (f"Star limit G {v:g}: your override (site default {d:g}; ↺ resets)" if ov is not None
                        else pg.mag_source(s))
                if kind == "pick":
                    n = max(15, math.ceil(v - 1e-9))
                    cd = os.path.join(ROOT, pg.cat_sel.value or "")
                    if not starcat.is_format2(cd) and not os.path.isfile(os.path.join(cd, f"bright_G{float(n):.1f}.v2.npy")):
                        text += (f" · the G ≤ {n} star index is not built yet: the next pick builds it once "
                                 f"(several minutes, ~{pg.INDEX_GB.get(n, 10):g} GB on disk)")
                note.text = text
        finally:
            pg.MAG["setting"] = False
    pg.mag_apply = mag_apply

    def mag_changed(kind, e):
        if pg.MAG["setting"]:
            return
        d = pg.pick_mag_default(pg.collect())
        v = e.value
        pg.MAG["override"][kind] = None if v in (None, "") or abs(float(v) - d) < 1e-9 else float(v)
        save_ui_state(mag_override={k: x for k, x in pg.MAG["override"].items() if x is not None})
        pg.mag_apply()
    pg.mag_changed = mag_changed

    def mag_reset(kind):
        pg.MAG["override"][kind] = None
        save_ui_state(mag_override={k: x for k, x in pg.MAG["override"].items() if x is not None})
        pg.mag_apply()
    pg.mag_reset = mag_reset

    def show_unsaved(changed):
        """The unsaved state: a note and the Save button in amber ('Save changes')."""
        pg.unsaved.text = f"unsaved changes to {pg.state['name']}" if changed else ""
        pg.save_btn.text = "Save changes" if changed else "Save sites.py"
        pg.save_btn.props(f"color={'warning' if changed else 'primary'}")
    pg.show_unsaved = show_unsaved

    def update_derived(*_):
        s = pg.collect()
        show_unsaved(pg.saved_site(pg.state["name"]) != pg.effective(s, pg.state["name"]))
        w, h = fov(s)
        pg.mag_apply(s)
        pg.derived.text = (f"Stars searched to G {mag_limit(s):.1f} · camera field {w:.1f}′ × {h:.1f}′ "
                           f"(focal {s.get('focal_mm') or 100 * s.get('aperture_cm', 25):.0f} mm)")
    pg.update_derived = update_derived

    def set_position(la, lo, el=None):
        pg.lat.value, pg.lon.value = round(la, 5), round(lo, 5)
        if el is not None:
            pg.ele.value = round(el)
        pg.marker.move(la, lo)
    pg.set_position = set_position

    async def on_click(e):
        ll = e.args.get("latlng", {})
        gen = pg.SITE_GEN[0]
        pg.set_position(ll["lat"], ll["lng"])
        el = await run.io_bound(geo.elevation, ll["lat"], ll["lng"])
        if stale(gen, "Height lookup"):
            return
        if el is not None:
            pg.ele.value = round(el)
            pg.ele_ref.value = "msl"                                 # Open-Meteo: above sea level
    pg.on_click = on_click

    # pasted coordinates: a number field drops text, so text that is not a plain number is taken from the paste
    # event in the browser and parsed here (geo.parse_coords: DMS, decimal, N/S/E/W, labels, heights)
    pg.PASTE_JS = ("(e) => { const t = (e.clipboardData || window.clipboardData).getData('text'); "
                   "if (!/^\\s*[+-]?\\d*\\.?\\d+\\s*$/.test(t)) { e.preventDefault(); emit(t); } }")

    async def on_paste(field, e):
        text = e.args if isinstance(e.args, str) else (e.args[0] if e.args else "")
        if re.fullmatch(r"\s*[+-]?\d+,\d+\s*", text):           # one number with a decimal comma (German, Swiss)
            text = text.replace(",", ".")                      # the fields always use the decimal point
        try:
            c = geo.parse_coords(text, field)
        except ValueError as ex:
            ui.notify(f"Coordinates not understood: {ex}", type="warning")
            return
        la = c["lat"] if c["lat"] is not None else pg.lat.value
        lo = c["lon"] if c["lon"] is not None else pg.lon.value
        if c["ele"] is not None:
            pg.ele.value = round(c["ele"])
        if la is None or lo is None:
            if c["lat"] is not None:
                pg.lat.value = round(c["lat"], 5)
            if c["lon"] is not None:
                pg.lon.value = round(c["lon"], 5)
            return
        pg.set_position(float(la), float(lo))
        pg.m.set_center((float(la), float(lo)))
        got = ", ".join(k for k in ("lat", "lon", "ele") if c[k] is not None)
        if c["ele"] is None and c["lat"] is not None and c["lon"] is not None:
            gen = pg.SITE_GEN[0]
            el = await run.io_bound(geo.elevation, float(la), float(lo))
            if stale(gen, "Height lookup"):
                return
            if el is not None:
                pg.ele.value = round(el)
                got += " (elevation looked up)"
        ui.notify(f"Pasted coordinates: {got}: {float(la):.5f}, {float(lo):.5f}"
                  + (f", {pg.ele.value:.0f} m" if pg.ele.value is not None else ""), type="positive")
    pg.on_paste = on_paste

    async def pick_occult(e):
        if e.value is None:
            return
        x = pg.occ[e.value]
        pg.set_position(x["lat"], x["lon"], x["ele"] if x["ele_ok"] else None)
        pg.ele_ref.value = "ellipsoid" if x["ele_ok"] else "msl"     # MPC parallax constants: height above WGS84
        pg.m.set_center((x["lat"], x["lon"]))
        pg.desc.value, pg.mpc.value = x["name"], x["code"]
        auto = f"{x['code']} {x['name'].split(',')[0].strip()}"
        if not (pg.new_name.value or "").strip() or pg.new_name.value == pg.state.get("auto_name"):   # keep a name you typed
            pg.new_name.value = auto
        pg.state["auto_name"] = auto
        if not x["ele_ok"]:                                       # old low-precision entry: look the height up
            gen = pg.SITE_GEN[0]
            el = await run.io_bound(geo.elevation, x["lat"], x["lon"])
            if stale(gen, "Height lookup"):
                return
            if el is not None:
                pg.ele.value = round(el)
        ui.notify(f"MPC {x['code']} {x['name']}: shown on the map and in the form. 'Add as new site' adds it to the "
                  f"site selector; 'Save sites.py' would instead move {pg.state['name']} there.",
                  multi_line=True, timeout=9000)
    pg.pick_occult = pick_occult

    def pick_camera(e):
        if e.value is None:
            return
        c = cameras.SENSORS[e.value]
        w, h = cameras.sensor_mm(c)
        pg.fields["sensor_w_mm"].value, pg.fields["sensor_h_mm"].value = w, h       # updates the camera field line too
        ui.notify(f"{c[0]} ({c[4]}): sensor {w:.2f} × {h:.2f} mm; 'Save sites.py' keeps it for this site",
                  timeout=6000)
    pg.pick_camera = pick_camera

    async def find_place():
        pg.hits.clear()
        gen = pg.SITE_GEN[0]
        res = await run.io_bound(geo.places, pg.q.value or "")
        if stale(gen, "Place search"):
            return
        with pg.hits:
            if not res:
                ui.label("No place found (or offline)").classes("text-sm text-slate-500")
            for la, lo, el, label in res:
                ui.button(f"{label}: {la:.4f}, {lo:.4f}, {el or 0:.0f} m",
                          on_click=lambda la=la, lo=lo, el=el: (pg.set_position(la, lo, el), pg.m.set_center((la, lo)),
                                                                pg.hits.clear())).props("flat dense no-caps align=left")
    pg.find_place = find_place

    async def ip_loc():
        gen = pg.SITE_GEN[0]
        r = await run.io_bound(geo.ip_location)
        if stale(gen, "IP location"):
            return
        if r is None:
            ui.notify("IP lookup failed", type="warning")
            return
        pg.set_position(r[0], r[1], r[2])
        pg.m.set_center((r[0], r[1]))
        ui.notify(f"Approximate (from your IP address): {r[3]}")
    pg.ip_loc = ip_loc

    HZ_KEYS = ("horizon", "horizon_name", "horizon_margin", "horizon_filter", "horizon_image", "horizon_image_az")

    def new_site_from_form(name):
        """The form as a new site: position, equipment and limits; the description, MPC code, horizon and photo only
        if they were changed in the form (still those of the site shown: left out, the description becomes the name),
        so nothing of the shown site carries over to the new one."""
        import json
        s = pg.collect()
        try:
            old = load_sites()[0].get(pg.state["name"]) or {}
        except Exception:
            old = {}
        same = lambda k: json.dumps(s.get(k), default=list) == json.dumps(old.get(k), default=list)
        if all(same(k) for k in HZ_KEYS):                         # the shown site's horizon and photo: not taken
            for k in HZ_KEYS:
                s.pop(k, None)
        elif same("horizon_image"):                               # a new horizon, but the old site's photo
            s.pop("horizon_image", None)
            s.pop("horizon_image_az", None)
        if s.get("name") == old.get("name"):
            s["name"] = name
        if s.get("mpc_code") and same("mpc_code"):
            s.pop("mpc_code")
        return s
    pg.new_site_from_form = new_site_from_form

    def add_site():
        """The position and settings in the form as a new site (name from 'New site name'), selected and saved;
        nothing of the site shown before carries over that was not changed in the form (new_site_from_form)."""
        name = (pg.new_name.value or "").strip()
        if not name or name in pg.sites:
            ui.notify("Enter a new, unused site name (field 'New site name' at the top)", type="warning")
            return
        pg.sites[name] = new_site_from_form(name)
        pg.sel.options = list(pg.sites)
        pg.sel.update()
        pg.state["name"] = name                                      # the form is this new site: no save question
        pg.sel.value = name                                          # makes it the run site
        pg.show_site(name)
        pg.new_name.value, pg.state["auto_name"] = "", None
        save_sites(pg.sites, pg.state.get("default", pg.default_site))
        show_unsaved(False)
        ui.notify(f"Site {name} added and saved in sites.py; it is now selected for all runs (top right)",
                  type="positive")
    pg.add_site = add_site

    async def switch_site(new):
        """The header's site selector changed: with unsaved changes to the site shown, ask first (Save / Discard /
        Cancel); then show the new site. Nothing of the old form carries over."""
        old = pg.state["name"]
        if new == old or new not in pg.sites:
            return
        if old in pg.sites and pg.saved_site(old) != pg.effective(pg.collect(), old):
            with ui.dialog().props("persistent") as dlg, ui.card().classes("max-w-md"):
                ui.label(f"Unsaved changes to site {old}").classes("font-semibold")
                ui.label(f"Save them before showing {new}?").classes("text-sm")
                with ui.row():
                    ui.button(f"Save {old}", on_click=lambda: dlg.submit("save")).props("color=primary")
                    ui.button("Discard", on_click=lambda: dlg.submit("discard")).props("outline color=negative")
                    ui.button("Cancel", on_click=lambda: dlg.submit("cancel")).props("flat")
            choice = await dlg
            if choice not in ("save", "discard"):                    # cancel: stay on the old site
                pg.sel.value = old
                return
            if choice == "save":
                pg.save()
        pg.show_site(new)
        save_ui_state(site=new, catalog=pg.cat_sel.value)
    pg.switch_site = switch_site

    def effective(s, name):
        """A site with every optional key filled in with its default, for comparing form and file."""
        e = {k: (tuple(v) if isinstance(v, list) else v) for k, v in s.items()}
        e.setdefault("name", name)
        e.setdefault("sensor_mm", (5.6, 3.2))
        for key, _, default, _ in SITE_KEYS:
            if key not in ("sensor_w_mm", "sensor_h_mm") and default is not None:
                e.setdefault(key, default)
        return e
    pg.effective = effective

    def saved_site(name):
        """The site as it is in sites.py now (what a run will use), with defaults filled in; None if not there."""
        try:
            s = load_sites()[0].get(name)
        except Exception:
            return None
        return pg.effective(s, name) if s else None
    pg.saved_site = saved_site

    def ensure_saved():
        """Runs read sites.py: save the selected site first if it was edited or is new."""
        s = pg.collect()
        if not os.path.isfile("sites.py") or pg.saved_site(pg.state["name"]) != pg.effective(s, pg.state["name"]):
            pg.save()
            ui.notify(f"Saved the changes to site {pg.state['name']} for this run", type="info")
    pg.ensure_saved = ensure_saved

    async def remove_site():
        name = pg.state["name"]
        if len(pg.sites) < 2:
            ui.notify("This is the only site: add another one before removing it", type="warning")
            return
        with ui.dialog() as dlg, ui.card():
            ui.label(f"Remove site {name} ({pg.sites[name].get('name', name)}) from sites.py?")
            with ui.row():
                ui.button("Remove", on_click=lambda: dlg.submit(True)).props("color=negative")
                ui.button("Cancel", on_click=lambda: dlg.submit(False)).props("flat")
        if not await dlg:
            return
        del pg.sites[name]
        default = pg.state.get("default", pg.default_site)
        note = ""
        if default == name or default not in pg.sites:
            default = pg.state["default"] = next(iter(pg.sites))
            note = f"; {default} is now the default for command-line runs"
        save_sites(pg.sites, default)
        pg.sel.options = list(pg.sites)
        pg.sel.update()
        pg.sel.value = default                                       # shows it (show_site)
        show_unsaved(False)
        ui.notify(f"Site {name} removed from sites.py{note}", type="positive")
    pg.remove_site = remove_site

    def save():
        pg.sites[pg.state["name"]] = pg.collect()
        if pg.is_default.value:
            pg.state["default"] = pg.state["name"]
        save_sites(pg.sites, pg.state.get("default", pg.default_site))
        ui.notify(f"sites.py saved (default site: {pg.state.get('default', pg.default_site)})", type="positive")
        show_unsaved(False)
    pg.save = save


def connect(pg):
    """Wire the tab up and fill it (run after all tabs' handlers)."""
    for _kind, (_f, _n) in pg.mag_fields().items():
        _f.on_value_change(lambda e, k=_kind: pg.mag_changed(k, e))

    for el in [pg.lat, pg.lon, pg.ele, pg.mpc, *pg.fields.values()]:
        el.on_value_change(pg.update_derived)

    pg.m.on("map-click", pg.on_click)

    for f_, el_ in (("lat", pg.lat), ("lon", pg.lon), ("ele", pg.ele)):
        el_.on("paste", lambda e, f_=f_: pg.on_paste(f_, e), js_handler=pg.PASTE_JS)

    pg.occ_sel.on_value_change(pg.pick_occult)

    pg.cam_sel.on_value_change(pg.pick_camera)

    pg.hz_margin.on_value_change(lambda e: pg.hz_draw())
