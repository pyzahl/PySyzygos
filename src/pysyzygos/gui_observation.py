"""gui_observation.py - the observation GUI: results and observation reports, separate from the search GUI.

    pysyzygos gui-observation [--port 8081] [--no-browser] [--host 0.0.0.0 | --server]

Its own web app (default port 8081, so it can run beside the search GUI on 8080), its own process and settings
(gui_observation_state.json in the data folder). It only reads the favorites, the saved favorites lists and the
Occult archive of observed events (observed.py); it writes only observation reports (obsreport.py,
observations/<event>/). Tabs:

    Status   what is there: favorites marked observed, saved lists, the Occult archive, PyStarLight analyses,
             saved reports, and what is not built yet
    Events   the events to report on: favorites (observed), a saved list, the Occult archive, analyses received
             from PyStarLight, or saved reports
    Report   the observation report of one event and station: prefilled from the event, imports (PyStarLight
             analysis, an IOTA-ES report form; each field shows where it came from: the recording, the analysis, the
             prediction, or edited by hand), saved, and written as an IOTA-ES report form (.txt) for submission

API for PyStarLight (docs/observation_interface.md): GET /api/obs/v1/ (status), POST /api/obs/v1/analysis (its
<movie>.event.json as the body) -> observations/inbox/. Local (127.0.0.1): the key of the connection file
(obsreport.api_file(), written at every start, the key made at the first: PyStarLight on this computer reads it);
from the network (--host 0.0.0.0 or --server) with the search GUI's login and program tokens (server_auth.json:
`pysyzygos gui --set-password`, `pysyzygos gui --new-token PyStarLight`), a token may only use /api/obs/v1/.
"""
from pysyzygos.version import __version__, __codename__, __author__, __copyright__, __license__, __url__
from pysyzygos import favorites, obsreport, observed
from pysyzygos.home import HOME as ROOT, PKG
import argparse, json, os, sqlite3

STATE = "gui_observation_state.json"
RUN = {}                                  # how this app was started (restart: the same port, host and mode)
PORT = 8081                               # default port; if taken, the next free one up to PORT + PORTS - 1
PORTS = 10                                # (the connection file says which: the search GUI's button reads it)
ARCHIVE_LIMIT = 300                       # rows of the Occult archive shown per search
API = "/api/obs/v1/"                      # the API for PyStarLight (token: read and send here only)


def load_state():
    try:
        with open(os.path.join(ROOT, STATE), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_state(**kw):
    s = load_state()
    s.update(kw)
    tmp = os.path.join(ROOT, STATE + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(s, f, indent=1)
    os.replace(tmp, os.path.join(ROOT, STATE))


def pystarlight_roots():
    """Folders searched for PyStarLight analyses: the setting, else ../PyStarLight beside the data folder."""
    s = load_state().get("pystarlight_dirs")
    if s:
        return [p for p in s if p]
    guess = os.path.join(os.path.dirname(os.path.abspath(ROOT)), "PyStarLight")
    return [guess] if os.path.isdir(guess) else []


def sources():
    """[(value, label)] of the event sources."""
    out = [("fav", "Favorites marked observed"), ("favall", "All favorites")]
    for m in favorites.lists():
        out.append((f"list:{m['slug']}", f"List “{m['name']}” ({m['n']})"))
    st = observed.status()
    out.append(("archive", "Occult archive" + (f" ({st['events']} events)" if st else " (not installed)")))
    out.append(("inbox", f"Received from PyStarLight ({len(obsreport.inbox(obsreport.DIR))})"))
    out.append(("reports", "Saved reports"))
    return out


def _fav_row(e):
    r, site = e.get("record") or {}, e.get("site") or {}
    num, name = obsreport._name_parts(r.get("target_id"), r.get("target_name"))
    return dict(id=e["key"], date=str(r.get("best_utc", ""))[:19].replace("T", " "),
                asteroid=" ".join(x for x in (f"({num})" if num else "", name) if x),
                star=obsreport._star_name(r), site=site.get("name", ""), status=e.get("status", ""),
                note=(e.get("note") or "")[:60])


def list_entries(src):
    """The favorites entries of a source 'fav' / 'favall' / 'list:<slug>'."""
    if src in ("fav", "favall"):
        items = favorites.load()
        return [e for e in items if src == "favall" or e.get("status") == "observed"]
    if src.startswith("list:"):
        p = os.path.join(favorites.DIR, favorites.LISTS, src[5:], "list.json")
        try:
            with open(p, encoding="utf-8") as f:
                return json.load(f).get("entries", [])
        except (OSError, ValueError):
            return []
    return []


def archive_rows(query):
    """Occult archive events matching an asteroid number, a name or a date ('2025-11', '2025-11-21'), newest first."""
    q = str(query or "").strip()
    _, db_file, _ = observed.paths()
    if not os.path.isfile(db_file):
        return []
    con = sqlite3.connect(f"file:{db_file}?mode=ro", uri=True)
    try:
        sql = ("SELECT target_id, best_utc, json_extract(record, '$.target_name'), "
               "json_extract(record, '$.star_catalog'), json_extract(record, '$.n_observers'), "
               "json_extract(record, '$.n_positive') FROM events")
        args = []
        if q:
            sql += " WHERE target_id = ? OR json_extract(record, '$.target_name') LIKE ? OR best_utc LIKE ?"
            args = [q, f"%{q}%", f"{q}%"]
        rows = con.execute(sql + f" ORDER BY best_utc DESC LIMIT {ARCHIVE_LIMIT}", args).fetchall()
    finally:
        con.close()
    return [dict(id=f"{t}|{str(u)[:19]}", date=str(u)[:19].replace("T", " "), asteroid=n or t, star=s or "",
                 site=f"{o or 0} observer(s)", status=f"{p or 0} positive", note="") for t, u, n, s, o, p in rows]


def rows_for(src, query=""):
    if src == "archive":
        return archive_rows(query)
    if src == "inbox":
        q = str(query or "").lower()
        return [dict(id=r["path"], date=r["date"], asteroid=r["object"], star="", site=r["software"],
                     status="received", note=f"received {r['received']} UT")
                for r in obsreport.inbox(obsreport.DIR) if q in json.dumps(r).lower()]
    if src == "reports":
        q = str(query or "").lower()
        return [dict(id=r["path"], date=r["date"], asteroid=r["asteroid"], star="", site=r["station"],
                     status=r["outcome"], note=f"saved {r['saved'][:16].replace('T', ' ')}")
                for r in obsreport.saved(obsreport.DIR) if q in json.dumps(r).lower()]
    q = str(query or "").lower()
    rows = [_fav_row(e) for e in list_entries(src)]
    return [r for r in rows if not q or q in json.dumps(r).lower()]


def sites_dict():
    """sites.py's sites (for the equipment of a favorite's site), or {}."""
    try:
        import runpy
        p = os.path.join(ROOT, "sites.py")
        return runpy.run_path(p).get("sites", {}) if os.path.isfile(p) else {}
    except Exception:
        return {}


def status_lines():
    """[(label, value)] for the Status tab."""
    items = favorites.load()
    obs = [e for e in items if e.get("status") == "observed"]
    lists = favorites.lists()
    st = observed.status()
    reports = obsreport.saved(obsreport.DIR)
    roots = pystarlight_roots()
    return [
        ("PySyzygos", f"{__version__} (observation GUI)"),
        ("Data folder", ROOT),
        ("Favorites", f"{len(items)}, of them {len(obs)} marked observed"),
        ("Saved favorites lists", ", ".join(f"{m['name']} ({m['n']})" for m in lists) or "none"),
        ("Occult archive (observed events)",
         f"{st['events']} events until {st['events_until']}" if st else
         "not installed: System tab of the search GUI, Occult data, 'observations'"),
        ("PyStarLight analyses searched in", ", ".join(roots) or "no folder set (Report tab, PyStarLight folder)"),
        ("Received from PyStarLight", f"{len(obsreport.inbox(obsreport.DIR))} analyses in "
                                      f"{os.path.join(ROOT, obsreport.inbox_dir())} (API {API})"),
        ("Saved reports", f"{len(reports)} in {os.path.join(ROOT, obsreport.DIR)}"),
        ("Connection for PyStarLight", f"{obsreport.api_file()} (address, key, inbox; read by PyStarLight)"),
    ]


NOT_YET = """**Not built yet** (this first version: lists, archive, report form, imports, IOTA-ES text):

- Online submission (IOTA-ES / SODIS, Occult's format): the form is written as text, to submit by hand.
- More than one D/R pair per report as separate events (second star, satellite): kept as lines under 'More events'.
- The light curve itself (PyStarLight CSV, plots) attached to a report; Occult's LightData/LightValues.
- Observer profile kept once (name, e-mail, address, equipment per site): entered per report for now.
- Several stations of one observer / several observers of one event shown together; a chord plot.
- Online submission per IOTA region (IOTA-ES, IOTA North America, RASNZ/IOTA ANZ, ...): which forms and channels.
- Observer profiles and several operators / chord stations: from the camera tool, to be managed.
"""


def build_page():
    from nicegui import ui
    S = dict(src=load_state().get("source", "fav"), sel=None, entry=None, archive=None, source=None,
             imports=[], report_path=None, origin={}, given={}, setting=False)
    W = {}

    ui.page_title("PySyzygos Observation Manager")
    with ui.header().classes("items-center bg-slate-800"):          # as the search GUI's header
        ui.element("img").props('src=/pysyzygos_logo.svg alt=""').classes("w-9 h-9")
        ui.label("PySyzygos").classes("text-xl font-semibold")
        ui.label(f"v{__version__}").classes("text-xs text-slate-400 self-end mb-1").tooltip(
            f"PySyzygos {__version__} \u201c{__codename__}\u201d")
        ui.label("observation manager").classes("text-slate-300")
        ui.space()
        ui.label(os.path.basename(os.path.abspath(ROOT)) or ROOT).classes("text-slate-300 text-sm").tooltip(
            f"Data folder: {ROOT}")
        ui.button("About", on_click=lambda: about.open()).props("flat dense color=white no-caps")
        ui.button(icon="power_settings_new", on_click=lambda: quit_dialog()).props(
            "flat dense round color=white").tooltip("Restart or quit the observation GUI (this app only; the search "
                                                    "GUI is a separate program)")

    def quit_dialog():
        with ui.dialog() as qd, ui.card().classes("max-w-md"):
            ui.label("Restart or quit the observation GUI?").classes("font-semibold")
            ui.label("Restart: it starts again on the same port (with any update you installed) and this page "
                     "reconnects by itself. " + ("(Server mode: no Quit here; stop it on the server.)" if RUN.get("server")
                                                 else "Quit: it ends; close this browser tab afterwards.")
                     + " The search GUI is not affected.").classes("text-sm")
            with ui.row():
                ui.button("Restart", on_click=lambda: (qd.close(), restart_app())).props("color=primary")
                if not RUN.get("server"):
                    ui.button("Quit", on_click=lambda: (qd.close(), quit_app())).props("color=negative")
                ui.button("Cancel", on_click=qd.close).props("flat")
        qd.open()
    with ui.dialog() as about, ui.card().classes("max-w-xl"):
        with ui.row().classes("items-center gap-4 no-wrap"):
            ui.element("img").props('src=/pysyzygos_logo.svg alt=""').classes("w-20 h-20")
            with ui.column().classes("gap-0"):
                ui.label("PySyzygos Observation Manager").classes("text-2xl font-semibold")
                ui.label(f"Version {__version__} \u201c{__codename__}\u201d").classes("text-slate-600")
                ui.label(f"by {__author__}").classes("text-sm text-slate-600")
        ui.label("The observation side of PySyzygos, a separate app beside the search GUI: your observed events "
                 "(favorites marked observed, saved lists), the IOTA / Occult archive of observed occultations, and "
                 "the observation report of each event and station. The report is prefilled from the prediction, "
                 "takes the recording's own data (GPS site and time, camera, telescope, observers) and the light-"
                 "curve analysis from PyStarLight, shows where every value came from, and is written as an IOTA-ES "
                 "report form for the submission. Every observed event, positive or negative, adds to what we know "
                 "about the sizes, shapes and orbits of the small bodies of the Solar System.").classes("text-sm")
        ui.label("Automated video analysis from PyStarLight is imported directly: the D and R times with their "
                 "accuracy from its light-curve fit, and the recording's own data (GPS site and time, camera, "
                 "telescope, observers), sent by PyStarLight (on this computer the connection sets itself up), found "
                 "in your recording folders, or loaded as its .event.json; no retyping.").classes("text-sm mt-2")
        ui.label("Early version: lists, archive, report form, imports and the IOTA-ES text. The submission itself, "
                 "the forms of the other IOTA regions and several stations of one event are still to come (Status "
                 "tab).").classes("text-sm mt-2")
        ui.label("Credits").classes("font-semibold mt-2")
        ui.label("Report form: IOTA-ES (European Section of the International Occultation Timing Association) \u00b7 "
                 "archive of observed occultations: D. Herald's Occult data, published by IOTA, and NASA PDS Small "
                 "Bodies Node (Herald, Dunham et al.) \u00b7 light curves and recording data: PyStarLight \u00b7 "
                 "stars: ESA Gaia DR3 \u00b7 interface: NiceGUI \u00b7 developed with the help of Claude "
                 "(Anthropic) via Claude Code. Full references: README.md.").classes("text-xs text-slate-600")
        ui.label(f"Data folder: {ROOT} \u00b7 reports in {os.path.join(ROOT, obsreport.DIR)} \u00b7 connection "
                 f"for PyStarLight: {obsreport.api_file()}").classes("text-xs text-slate-600 mt-2")
        ui.label(f"{__copyright__}. Free software under the GNU GPL v3 or later ({__license__}); no warranty.").classes(
            "text-xs text-slate-600 mt-2")
        with ui.row().classes("w-full items-center justify-between mt-2"):
            ui.link(__url__, __url__, new_tab=True).classes("text-sm")
            ui.link("OBSERVATION-MANAGER.md", __url__.rstrip("/") + "/blob/main/OBSERVATION-MANAGER.md",
                    new_tab=True).classes("text-sm")
            ui.button("Close", on_click=about.close).props("flat")
    with ui.tabs().classes("w-full") as tabs:
        t_status, t_events, t_report = ui.tab("Status"), ui.tab("Events"), ui.tab("Report")
    with ui.tab_panels(tabs, value=t_events).classes("w-full"):
        with ui.tab_panel(t_status):
            status_box = ui.column().classes("w-full gap-1")
            ui.button("Refresh", on_click=lambda: show_status()).props("flat dense")
            ui.markdown(NOT_YET).classes("text-sm")
        with ui.tab_panel(t_events):
            with ui.row().classes("w-full items-end gap-3"):
                src_sel = ui.select(dict(sources()), value=S["src"] if S["src"] in dict(sources()) else "fav",
                                    label="Events from").classes("w-72")
                q_in = ui.input("Search (asteroid, star, site, date; archive: number, name or date)").classes(
                    "grow")
                ui.button("Search", on_click=lambda: fill_table()).props("outline")
            table = ui.table(columns=[dict(name=k, label=lab, field=k, sortable=True, align="left")
                                      for k, lab in (("date", "Date (UT)"), ("asteroid", "Asteroid"),
                                                     ("star", "Star"), ("site", "Site / observers"),
                                                     ("status", "Status"), ("note", "Note"))],
                             rows=[], row_key="id", selection="single", pagination=25).classes("w-full")
            with ui.row().classes("items-end gap-3"):
                obs_sel = ui.select({}, label="Observer of the archive event (prefills station and D/R)").classes(
                    "w-96")
                obs_sel.set_visibility(False)
                ui.button("Open the report form", on_click=lambda: open_report()).props("color=primary")
        with ui.tab_panel(t_report):
            title = ui.label("No event chosen: Events tab, choose one, 'Open the report form'.").classes(
                "text-lg font-semibold")
            with ui.row().classes("items-center gap-2"):
                ui.button("Find PyStarLight analysis", on_click=lambda: find_psl()).props("outline dense").tooltip(
                    "Search the PyStarLight folder(s) for <movie>.event.json of this date and asteroid and fill "
                    "D/R times, errors, recording, camera and site from it")
                ui.upload(label="PyStarLight .event.json", auto_upload=True,
                          on_upload=lambda e: upload(e, "psl")).props("accept=.json dense flat").classes("w-56")
                ui.upload(label="IOTA-ES report .txt", auto_upload=True,
                          on_upload=lambda e: upload(e, "iotaes")).props("accept=.txt dense flat").classes("w-56")
                ui.button("Save", on_click=lambda: do_save()).props("color=primary")
                ui.button("IOTA-ES report (.txt)", on_click=lambda: do_export()).props("outline").tooltip(
                    "Save, then download the report as IOTA-ES report form text (for the submission)")
                extras_chk = ui.checkbox("PySyzygos extra fields", value=bool(load_state().get("extras", True))).tooltip(
                    "Also write PySyzygos' own lines into the report form (Gaia DR3 id, personal equation, telescope "
                    "model, focal reducer, more events, and where each field came from). Off: only the form's lines")
                extras_chk.on_value_change(lambda e: save_state(extras=bool(e.value)))
            psl_in = ui.input("PyStarLight folder(s), comma separated",
                              value=", ".join(pystarlight_roots())).classes("w-full")
            missing_lbl = ui.label("").classes("text-sm text-amber-700")
            for sec in obsreport.SECTIONS:
                with ui.expansion(sec, value=sec in ("Event", "Observation")).classes("w-full border rounded"):
                    with ui.grid(columns=3).classes("w-full gap-x-4"):
                        for key, lab, s_, kind, choices in obsreport.FIELDS:
                            if s_ != sec:
                                continue
                            if kind == "choice":
                                opts = ({c: c for c in choices} if isinstance(choices, tuple) else
                                        {c: f"{c or '_'} {t}" for c, t in choices.items()})
                                W[key] = ui.select({"": "—", **opts} if "" not in opts else opts, label=lab,
                                                   value="")
                            elif kind == "area":
                                W[key] = ui.textarea(lab).classes("col-span-3").props("rows=2")
                            else:
                                W[key] = ui.input(lab)
                            W[key].on_value_change(lambda e, key=key: edited(key))

    def get_fields():
        return {k: ("" if w.value is None else w.value) for k, w in W.items()}

    def mark(key):
        """The field's hint: where its value came from (the recording's are the authentic data)."""
        o = S["origin"].get(key, "")
        hint = ""
        if o.startswith("edited"):
            hint = f"edited by hand (from {obsreport.PSL_ORIGIN.get(o.split(' ', 1)[-1], '?')}: " \
                   f"{S['given'].get(key, '')})"
        elif o:
            hint = f"from {obsreport.PSL_ORIGIN.get(o, o)}"
        W[key].props(f'hint="{hint}"' if hint else "hint=''")
        W[key].classes(replace="text-amber-800" if o.startswith("edited") else
                       "text-green-800" if o == "recording" else "")

    def edited(key):
        if not S["setting"]:
            o = S["origin"].get(key, "")
            if o and not o.startswith("edited") and str(W[key].value or "") != str(S["given"].get(key, "")):
                S["origin"][key] = f"edited {o}"
                mark(key)
            elif o.startswith("edited") and str(W[key].value or "") == str(S["given"].get(key, "")):
                S["origin"][key] = o.split(" ", 1)[1]
                mark(key)
        show_missing()

    def set_fields(f, only_known=False, origin=None):
        S["setting"] = True
        try:
            _set_fields(f, only_known)
        finally:
            S["setting"] = False
        for k in f:
            if k in W and (not only_known or f[k] not in ("", None)):
                if origin and k in origin:
                    S["origin"][k], S["given"][k] = origin[k], "" if f[k] is None else str(f[k])
                elif not only_known:
                    S["origin"].pop(k, None)
                mark(k)
        show_missing()

    def _set_fields(f, only_known=False):
        for k, w in W.items():
            if only_known and (k not in f or f[k] in ("", None)):
                continue
            v = f.get(k, "")
            v = "" if v is None else v
            if isinstance(w, ui.select):
                opts = w.options if isinstance(w.options, dict) else {o: o for o in w.options}
                if str(v) not in opts:
                    w.options = {**opts, str(v): str(v)}
                    w.update()
                w.value = str(v)
            else:
                w.value = str(v)

    def show_missing():
        m = obsreport.missing(get_fields())
        missing_lbl.text = ("Still missing for a submission: " + ", ".join(m)) if m else "Complete for a submission."

    def show_status():
        status_box.clear()
        with status_box:
            with ui.grid(columns=2).classes("gap-x-6 gap-y-1"):
                for k, v in status_lines():
                    ui.label(k).classes("font-medium")
                    ui.label(v)

    def fill_table():
        S["src"] = src_sel.value
        save_state(source=src_sel.value)
        table.rows = rows_for(src_sel.value, q_in.value)
        table.selected = []
        table.update()
        obs_sel.set_visibility(False)

    def on_select(e):
        rows = e.selection if hasattr(e, "selection") else table.selected
        S["sel"] = rows[0]["id"] if rows else None
        if S["sel"] and src_sel.value == "archive":
            rec, cts = observed.find(S["sel"])
            names = [s.get("observer") for s in (rec or {}).get("obs_sites") or [] if s.get("observer")]
            obs_sel.options = {"": "— the event only —", **{n: n for n in names}}
            obs_sel.value = ""
            obs_sel.update()
            obs_sel.set_visibility(True)
        else:
            obs_sel.set_visibility(False)
    table.on_select(on_select)

    def open_report():
        if not S["sel"]:
            ui.notify("Choose an event in the table first", type="warning")
            return
        src, S["imports"], S["report_path"], S["origin"], S["given"] = src_sel.value, [], None, {}, {}
        psl = None
        if src == "inbox":
            g, note, og = obsreport.from_pystarlight(S["sel"])
            entries = list_entries("favall") + [e for v, _ in sources() if v.startswith("list:")
                                                for e in list_entries(v)]
            hit = obsreport.matching(g, entries)
            f = obsreport.from_favorite(hit[0], sites_dict()) if hit else obsreport.blank()
            S["source"] = dict(kind="pystarlight inbox", file=os.path.basename(S["sel"]),
                               key=hit[0]["key"] if hit else "")
            psl = (g, note, og)
        elif src == "archive":
            rec, cts = observed.find(S["sel"])
            f = obsreport.from_archive(rec or {}, cts, obs_sel.value or None)
            S["source"] = dict(kind="occult archive", key=S["sel"], observer=obs_sel.value or "")
        elif src == "reports":
            r = obsreport.load(S["sel"])
            f, S["source"], S["report_path"] = r.get("fields") or {}, r.get("source") or {}, S["sel"]
        else:
            e = next((x for x in list_entries(src) if x["key"] == S["sel"]), None)
            if e is None:
                ui.notify("That favorite is gone (list changed?)", type="warning")
                return
            f = obsreport.from_favorite(e, sites_dict())
            S["source"] = dict(kind="favorite" if src.startswith("fav") else "list", key=e["key"],
                               list=src[5:] if src.startswith("list:") else "")
        pred = {k: "prediction" for k in ("predict_time", "pred_d", "pred_r", "probability", "pred_duration",
                                          "dist_center_km", "path_width_km") if f.get(k) not in ("", None)}
        set_fields({**obsreport.blank(), **f}, origin=pred)
        if psl:
            apply_import(*psl, kind="pystarlight", software=obsreport.software_of(S["sel"]))
        elif S["report_path"]:
            r = obsreport.load(S["report_path"])
            S["origin"].update(r.get("origin") or {})
            for k in S["origin"]:
                if k in W:
                    mark(k)
        f = get_fields()                                         # with the imports
        title.text = (f"({f.get('asteroid_number')}) " if f.get("asteroid_number") else "") + \
            f"{f.get('asteroid_name', '')} occults {f.get('star', '')} on {f.get('date', '')}" + \
            (f" {f['predict_time']} UT" if f.get("predict_time") else "") + \
            (f" \u00b7 {f['station'] or f.get('observer1', '')}" if f.get("station") or f.get("observer1") else "")
        tabs.value = t_report

    def apply_import(f, note, origin=None, kind="", software=""):
        set_fields(f, only_known=True, origin=origin)
        S["imports"].append(dict(kind=kind, note=note, software=software))
        ui.notify(note, type="positive", multi_line=True)

    def find_psl():
        f = get_fields()
        roots = [p.strip() for p in (psl_in.value or "").split(",") if p.strip()]
        save_state(pystarlight_dirs=roots)
        found = obsreport.find_pystarlight(roots, f.get("date") or None, f.get("asteroid_number") or None,
                                           f.get("asteroid_name") or None)
        if not found:
            ui.notify("No PyStarLight analysis of this date and asteroid in " + (", ".join(roots) or "no folder"),
                      type="warning")
            return
        with ui.dialog() as dlg, ui.card().classes("w-[760px] max-w-full"):
            ui.label("PyStarLight analyses found").classes("font-semibold")
            for p, obj, day in found:
                with ui.row().classes("w-full items-center no-wrap"):
                    ui.label(f"{day} · {obj}").classes("grow")
                    ui.label(os.path.relpath(p, roots[0]) if roots else p).classes("text-xs text-slate-500")
                    ui.button("Use", on_click=lambda p=p: (dlg.close(), apply_import(
                        *obsreport.from_pystarlight(p), kind="pystarlight", software=obsreport.software_of(p)))
                              ).props("dense")
            ui.button("Close", on_click=dlg.close).props("flat")
        dlg.open()

    async def upload(e, kind):
        data = (await e.file.read()).decode("utf-8", errors="replace")
        name = getattr(e.file, "name", "the file")
        if kind == "psl":
            tmp = os.path.join(ROOT, obsreport.DIR, ".upload.event.json")
            os.makedirs(os.path.dirname(tmp), exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as fh:
                fh.write(data)
            try:
                f, note, og = obsreport.from_pystarlight(tmp)
                soft = obsreport.software_of(tmp)
            except (ValueError, KeyError) as ex:
                ui.notify(f"{name}: not a PyStarLight analysis ({ex})", type="warning")
                return
            finally:
                os.remove(tmp)
            apply_import(f, note.replace(".upload.event.json", name), og, "pystarlight", soft)
        else:
            f = obsreport.from_iotaes(data)
            if not f:
                ui.notify(f"{name}: no report form fields found", type="warning")
                return
            apply_import(f, f"IOTA-ES report {name}: {len(f)} fields", None, "iotaes")

    def do_save():
        f = get_fields()
        if not (f.get("date") and (f.get("asteroid_number") or f.get("asteroid_name"))):
            ui.notify("Date and asteroid are needed to save", type="warning")
            return None
        p = obsreport.save(f, os.path.join(ROOT, obsreport.DIR), S.get("source"), S["imports"], S["origin"])
        S["imports"], S["report_path"] = [], p
        ui.notify(f"Saved: {os.path.relpath(p, ROOT)}", type="positive")
        return p

    def do_export():
        p = do_save()
        if not p:
            return
        txt = p[:-5] + "_IOTA-ES.txt"
        r = obsreport.load(p)
        soft = [i.get("software") for i in r.get("imports", []) if i.get("software")]
        with open(txt, "w", encoding="utf-8") as fh:
            fh.write(obsreport.to_iotaes(r["fields"], extras=bool(extras_chk.value), origin=r.get("origin"),
                                         sources=soft))
        ui.download(txt, os.path.basename(txt))

    src_sel.on_value_change(lambda *_: fill_table())
    show_status()
    fill_table()
    show_missing()


def quit_app():
    """End this app (the power button's 'Quit')."""
    import asyncio
    from nicegui import app, ui
    ui.notify("The observation GUI is quitting: you can close this tab", type="warning", timeout=4000)
    asyncio.get_event_loop().call_later(1.0, app.shutdown)


def restart_app():
    """Start this app again in its process (exec, the same port, host and mode; the page reconnects by itself)."""
    import asyncio, sys
    from nicegui import ui
    ui.notify("The observation GUI restarts: this page reconnects in a few seconds", type="info", timeout=6000)

    def again():
        os.environ["PYSYZYGOS_HOME"] = ROOT
        os.execv(sys.executable, [sys.executable, "-m", "pysyzygos", "gui-observation", "--no-browser",
                                  "--port", str(RUN["port"]), "--host", RUN["host"]]
                 + ["--server"] * bool(RUN.get("server_flag")) + ["--no-auth"] * bool(RUN.get("no_auth")))
    asyncio.get_event_loop().call_later(1.0, again)


def port_free(host, port):
    """True if a server could listen on host:port now (0.0.0.0 also needs the port free on 127.0.0.1)."""
    import socket
    fam = socket.AF_INET6 if ":" in str(host) else socket.AF_INET
    with socket.socket(fam, socket.SOCK_STREAM) as s:
        if os.name != "nt":                   # as the web server: closed connections (TIME_WAIT) do not block,
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)    # a listening program does
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def free_port(host="127.0.0.1"):
    """The first free port from PORT on (PORTS of them), or None."""
    return next((p for p in range(PORT, PORT + PORTS) if port_free(host, p)), None)


def add_api(app, local=True):
    """GET /api/obs/v1/ (status) and POST /api/obs/v1/analysis (a PyStarLight event.json) for PyStarLight. local:
    sending needs the connection file's key (in server mode the guard checks the program tokens instead)."""
    from fastapi import Request
    from fastapi.responses import JSONResponse

    @app.get(API)
    def api_status():
        return dict(ok=True, app="PySyzygos observation GUI", version=__version__,
                    inbox=len(obsreport.inbox(obsreport.DIR)), send=API + "analysis")

    @app.post(API + "analysis")
    async def api_analysis(request: Request):
        if local and not obsreport.api_key_ok(request.headers.get("authorization")):
            return JSONResponse(dict(ok=False, msg=f"key missing or wrong: see {obsreport.api_file()}"),
                                status_code=401)
        body = await request.body()
        if len(body) > obsreport.INBOX_MAX_BYTES:
            return JSONResponse(dict(ok=False, msg="too large"), status_code=413)
        try:
            js = json.loads(body)
            p = obsreport.store_analysis(js, obsreport.DIR)
        except ValueError as ex:
            return JSONResponse(dict(ok=False, msg=str(ex)), status_code=400)
        f, note, _ = obsreport.from_pystarlight(p)
        entries = list_entries("favall") + [e for v, _ in sources() if v.startswith("list:") for e in list_entries(v)]
        keys = [e["key"] for e in obsreport.matching(f, entries)]
        return dict(ok=True, file=os.path.basename(p), asteroid=" ".join(
            x for x in (f.get("asteroid_number"), f.get("asteroid_name")) if x), date=f.get("date", ""),
                    favorites=keys, msg=note)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=f"PySyzygos {__version__}")
    ap.add_argument("--port", type=int, default=None,
                    help=f"default: {PORT}, or the next free one up to {PORT + PORTS - 1} (the search GUI uses 8080)")
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--host", default="127.0.0.1",
                    help="address to listen on; another than 127.0.0.1 (e.g. 0.0.0.0) is server mode with a login")
    ap.add_argument("--server", action="store_true", help="server mode (login) also on 127.0.0.1")
    ap.add_argument("--no-auth", action="store_true", help="server mode without the built-in login (behind a proxy)")
    a = ap.parse_args(argv)
    if a.port is None:
        a.port = free_port(a.host)
        if a.port is None:
            raise SystemExit(f"ports {PORT}-{PORT + PORTS - 1} are all taken on {a.host}: choose one with --port")
    elif not port_free(a.host, a.port):
        raise SystemExit(f"port {a.port} is taken on {a.host} (another program): choose another with --port")
    from nicegui import app, ui
    from pysyzygos import server_mode
    auth_path = os.path.join(ROOT, server_mode.AUTH_FILE)
    server = a.server or a.no_auth or not server_mode.is_loopback(a.host)
    RUN.update(port=a.port, host=a.host, server=server, server_flag=a.server, no_auth=a.no_auth)
    auth = None
    if server and not a.no_auth:
        auth = server_mode.load_auth(auth_path)
        if auth is None:
            raise SystemExit(f"server mode needs a login: pysyzygos gui --set-password (writes {auth_path}); a program "
                             f"such as PyStarLight then gets a token: pysyzygos gui --new-token PyStarLight")
    # the connection file's key (PyStarLight on this computer): checked by the API in local mode, and in server mode
    # by the guard for requests from this computer (127.0.0.1 is served too when listening on 0.0.0.0)
    key_ok = lambda t: obsreport.api_key_ok("Bearer " + str(t))
    app.add_middleware(server_mode.Guard, auth=auth, path=None if auth is None else auth_path, token_paths=(API,),
                       token_post=(API,), local_key=key_ok)
    add_api(app, local=not server)
    if server_mode.is_loopback(a.host) or a.host in ("0.0.0.0", "::", ""):
        obsreport.api_setup(f"http://127.0.0.1:{a.port}", obsreport.inbox_dir(os.path.join(ROOT, obsreport.DIR)), ROOT)
    print(f"PySyzygos {__version__} observation GUI on {a.host}:{a.port}, data folder: {ROOT}"
          + (f"; server mode, login {auth['user']}; tokens may use {API}" if auth else
             "; server mode WITHOUT login (--no-auth)" if server else "")
          + f"; connection for PyStarLight on this computer: {obsreport.api_file()}")
    app.add_static_file(local_file=os.path.join(PKG, "pysyzygos_logo.svg"), url_path="/pysyzygos_logo.svg")
    ui.page("/")(build_page)
    ui.add_head_html("<script>document.documentElement.lang = 'en';</script>", shared=True)
    ui.number.default_props("lang=en")
    ui.run(host=a.host, port=a.port, title="PySyzygos Observation Manager",
           favicon=os.path.join(PKG, "pysyzygos_logo.svg"), show=not (a.no_browser or server), reload=False,
           language="en-US")


if __name__ in {"__main__", "__mp_main__"}:
    main()
