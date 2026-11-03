"""gui_observed.py - the whole record of an observed event of the Occult archive (observed.details) in a dialog:
the event, star, fit and satellite sections, every observer with their times, and our check (obs-check). Shared by
the search GUI (Results tab, 'Observed events': with its button that checks the event at every site) and the
Observation Manager (read only). NiceGUI only; no SPICE."""
from nicegui import ui


def dialog(key, buttons=None, title_extra=""):
    """Open the record of the archive event key ('target|YYYY-MM-DDTHH:MM:SS'). buttons(dlg, rec, obs): adds the
    caller's buttons to the header."""
    from pysyzygos import observed
    rec, cts = observed.find(key)
    if rec is None:
        ui.notify(f"{key}: not in the observations database", type="warning")
        return
    sec, obs = observed.details(rec, cts)
    with ui.dialog() as dlg, ui.card().classes("w-[96vw] max-w-[1500px]"):
        with ui.row().classes("w-full items-center justify-between"):
            ui.label(f"{rec.get('target_name', '')}, {str(rec.get('best_utc', ''))[:19].replace('T', ' ')} UT"
                     + title_extra).classes("text-lg font-semibold")
            with ui.row().classes("items-center gap-2"):
                if buttons:
                    buttons(dlg, rec, obs)
                ui.button(icon="close", on_click=dlg.close).props("flat dense round")
        with ui.scroll_area().classes("w-full h-[78vh]"):
            with ui.element("div").classes("w-full grid gap-x-8 gap-y-2").style(
                    "grid-template-columns: repeat(auto-fill, minmax(420px, 1fr))"):
                for title, items in sec:
                    with ui.column().classes("gap-0"):
                        ui.label(title).classes("font-semibold text-sm mt-1")
                        for k, v in items:
                            with ui.row().classes("w-full no-wrap gap-2 text-sm"):
                                ui.label(k).classes("text-slate-500 w-56 shrink-0")
                                ui.label(str(v)).classes("break-words min-w-0")
            ui.label(f"Observers ({len(obs)})").classes("font-semibold text-sm mt-3")
            f = lambda x, fmt: "" if x is None else fmt.format(x)
            rows = [dict(i=i, result=o["result"], observer=o["observer"], place=o["place"],
                         pos=f"{f(o['lat'], '{:.5f}')}, {f(o['lon'], '{:.5f}')}", alt=f(o.get("alt_m"), "{:.0f}"),
                         datum=o["datum"], method=o["method"], times=o["events"], adj=f(o.get("time_adj_s"), "{:+.2f}"),
                         dur=f(o.get("dur_obs"), "{:.2f}") + (f" (2nd star {o['dur_obs2']:.2f})" if o.get("dur_obs2") else ""), dt=f(o.get("dt_mid"), "{:+.3f}"), dist=f(o.get("dist_km"), "{:.2f}"),
                         dcat=f(o.get("dur_cat"), "{:.2f}"), dbest=f(o.get("dur_best"), "{:.2f}"))
                    for i, o in enumerate(obs)]
            cols = [("result", "Result"), ("observer", "Observer"), ("place", "Place"), ("pos", "Lat, Lon (\u00b0)"),
                    ("alt", "Height (m)"), ("datum", "Datum"), ("method", "Method"),
                    ("times", "Times (UT, \u00b1 s, personal equation)"), ("adj", "Time adj. (s)"),
                    ("dur", "Duration (s)"), ("dt", "Ours: mid obs \u2212 pred (s)"), ("dist", "Ours: from center line (km)"),
                    ("dcat", "Ours: duration, catalog size (s)"), ("dbest", "Ours: duration, best size (s)")]
            ui.table(columns=[dict(name=k, label=lbl, field=k, align="left", sortable=True) for k, lbl in cols],
                     rows=rows, row_key="i").props("dense flat wrap-cells").classes("w-full text-xs")
            ui.label("Times as the observers reported them (D, R: main star; G, B: satellite; d, r: second star), a "
                     "visual observer's personal equation (PE) as reported; 'excluded': left out of Occult's fit. "
                     "Ours: PySyzygos's prediction at that site (obs-check).").classes("text-xs text-slate-500")
    dlg.open()
