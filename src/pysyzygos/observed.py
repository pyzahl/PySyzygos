"""observed.py - the observed asteroid occultations of the IOTA / Occult archive as a results database.

    pysyzygos observed build|status|show <asteroid> [--xml FILE] [--db FILE]

Source: D. Herald's Occult archive `Asteroid~Observations.xml` (the "observations" dataset of the occultdata
add-on, downloaded in the System tab; format: its `FileFormat AsteroidObservations.htm`). Each event becomes a record
with PySyzygos's field names where they mean the same (target_id, target_name, best_utc, star, star_ra/star_dec,
mag, r_km, max_duration_s, star_ruwe, star_flag, ...) plus the archive's own (the fit, the observed position of the
asteroid in the geocentric fundamental plane, chords, satellites with their CBET numbers, observers); every
observer's disappearance and reappearance are its contacts. Written to <occult_data>/observations.db (results list
"observed", same tables as pysyzygos.db, so the Results tab, its filter bar and SQL filter work on it) and exported as
observations_log.csv (+ .runs.jsonl) for the report.

best_utc is the archive's reference time (the time its astrometric solution refers to, close to the observed
events). Records keep the archive's values as given: the star place is J2000 with proper motion and parallax to the
event date (GCRS, no light deflection); geo_x_km / geo_y_km are the observed centre of the asteroid in the
fundamental plane through the geocentre, axes of date (apparent), at best_utc. Reference only, as all Occult data:
never shipped with PySyzygos (redistribution not agreed). obscheck.py compares them with our predictions.
"""
import argparse, json, math, os, sys, time
from datetime import datetime, timedelta, timezone

from pysyzygos.version import __version__
from pysyzygos import db, occultdata

DB_FILE = "observations.db"
CSV_FILE = "observations_log.csv"
LIST = "observed"
XML_FILE = "Asteroid~Observations.xml"
FIT_QUALITY = {0: "no reliable position or size", 1: "astrometry only", 2: "limits on size", 3: "reliable size",
               4: "better than shape models", 5: "short event, no astrometry", 6: "one star of a double"}
SAT_FIT = {0: "no fit", 1: "is it a satellite?", 2: "approximate offset", 3: "offset + size", 4: "offset + shape"}
POSITIVE = {"D", "G", "d", "g"}                    # disappearance codes of a positive chord (main star, satellite, 2nd star)


def paths(base=None):
    """(xml, db, csv) paths in the add-on's folder."""
    d = occultdata.folder(base)
    return os.path.join(d, XML_FILE), os.path.join(d, DB_FILE), os.path.join(d, CSV_FILE)


def _f(x):
    try:
        v = float(str(x).strip())
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def _i(x, default=None):
    v = _f(x)
    return int(v) if v is not None else default


def _split(text):
    return [p.strip() for p in (text or "").split("|")]


def _utc(y, m, d, hours):
    """ISO UTC from a date and hours (hours may exceed 24: the next day)."""
    t = datetime(int(y), int(m), 1, tzinfo=timezone.utc) + timedelta(days=float(d) - 1, hours=float(hours))
    return t.strftime("%Y-%m-%dT%H:%M:%S.") + f"{t.microsecond // 1000:03d}"


def _hms(text):
    """hours from 'hh mm ss.ss' (None if not a time)."""
    p = (text or "").split()
    if len(p) != 3:
        return None
    try:
        return int(p[0]) + int(p[1]) / 60.0 + float(p[2]) / 3600.0
    except ValueError:
        return None


def _dms(text):
    """degrees from '+150 38 27.9' / '-33 39 51.9' (sign of the text)."""
    t = (text or "").strip()
    if not t:
        return None
    neg = t.startswith("-")
    p = t.lstrip("+-").split()
    try:
        v = sum(float(x) / 60 ** i for i, x in enumerate(p))
    except ValueError:
        return None
    return -v if neg else v


def record(ev):
    """(record, contacts) of one <Event> element. Raises ValueError for an event without a usable date."""
    g = lambda path: ev.findtext(path) or ""
    date = _split(g("Date"))
    if len(date) < 4:
        raise ValueError("no date")
    star, iss, ast = _split(g("Details/Star")), _split(g("Details/StarIssues")), _split(g("Details/Asteroid"))
    fit, unc = _split(g("Details/EventFits/EllipticFit")), _split(g("Details/EventFits/EllipseUncertainty"))
    ref, main = _split(g("Details/Astrometry/ReferenceTime")), _split(g("Details/Astrometry/MainBody"))
    conj, mpc = _split(g("Details/Astrometry/MainAtConjunction")), _split(g("Details/Astrometry/MPC"))
    num, name = (ast + ["", ""])[:2]
    tid = num if num.isdigit() and int(num) > 0 else name
    if len(ref) >= 4 and _f(ref[3]) is not None:
        best = _utc(ref[0], ref[1], ref[2], ref[3])
    else:
        best = _utc(date[0], date[1], date[2], date[3])
    q = _i(fit[5]) if len(fit) > 5 else None
    rec = dict(target_id=tid, target_name=f"{num} {name}".strip() if tid == num else name, best_utc=best,
               kind="asteroid", source="Occult archive",
               star=star[3] if len(star) > 3 and star[3] not in ("", "0") else "",
               star_catalog=f"{star[0]} {star[1]}".strip() if len(star) > 1 else "",
               star_gaia_version=_i(star[2]) if len(star) > 2 else None,
               star_ra=_f(star[4]) * 15.0 if len(star) > 4 and _f(star[4]) is not None else None,
               star_dec=_f(star[5]) if len(star) > 5 else None,
               star_ra_err_mas=_f(star[6]) if len(star) > 6 else None,
               star_dec_err_mas=_f(star[7]) if len(star) > 7 else None,
               star_diam_mas=_f(star[8]) if len(star) > 8 else None,
               mag=_f(star[13]) if len(star) > 13 else None,
               star_bp=_f(star[12]) if len(star) > 12 else None, star_rp=_f(star[14]) if len(star) > 14 else None,
               star_ruwe=_f(iss[0]) if iss and iss[0] else None,
               star_dup=_i(iss[1]) if len(iss) > 1 else None, star_no_pm=_i(iss[2]) if len(iss) > 2 else None,
               star_pm_ucac4=_i(iss[3]) if len(iss) > 3 else None,
               r_km=(_f(ast[10]) or 0.0) / 2.0 if len(ast) > 10 and _f(ast[10]) else None,
               r_unc_km=(_f(ast[11]) or 0.0) / 2.0 if len(ast) > 11 and _f(ast[11]) else None,
               m_ast=_f(ast[12]) if len(ast) > 12 else None,
               dist_au=8.794143 / _f(ast[8]) if len(ast) > 8 and _f(ast[8]) else None,
               fit_quality=q, fit_quality_text=FIT_QUALITY.get(q, ""),
               fit_major_km=_f(fit[2]) if len(fit) > 2 else None, fit_minor_km=_f(fit[3]) if len(fit) > 3 else None,
               fit_pa_deg=_f(fit[4]) if len(fit) > 4 else None,
               fit_assumed_size=_i(fit[6]) if len(fit) > 6 else None,
               fit_review=_i(fit[7]) if len(fit) > 7 else None,
               fit_x_sdev_km=_f(unc[0]) if unc and unc[0] else None,
               fit_y_sdev_km=_f(unc[1]) if len(unc) > 1 else None,
               ref_time_unc_s=_f(ref[4]) if len(ref) > 4 else None,
               ref_across_unc_mas=_f(ref[5]) if len(ref) > 5 else None,
               geo_x_km=_f(main[1]) if len(main) > 1 else None, geo_y_km=_f(main[2]) if len(main) > 2 else None,
               obs_dra_arcsec=_f(main[3]) if len(main) > 3 else None,
               obs_ddec_arcsec=_f(main[4]) if len(main) > 4 else None,
               n_chords=_i(main[8]) if len(main) > 8 else None,
               fit_code=main[10] if len(main) > 10 else "",
               conj_x_km=_f(conj[1]) if len(conj) > 1 else None, conj_y_km=_f(conj[2]) if len(conj) > 2 else None,
               conj_utc=_utc(conj[3], conj[4], 1, (_f(conj[5]) - 1.0) * 24.0) if len(conj) > 5 and _f(conj[5]) else "",
               mpc=" ".join(x for x in mpc if x), added="-".join(x.zfill(2) for x in _split(g("Added"))),
               last_edited="-".join(x.zfill(2) for x in _split(g("LastEdited"))))
    if rec["star_dup"] == 1 or (rec["star_ruwe"] or 0) >= 1.4 or rec["star_no_pm"] == 1:
        rec["star_flag"] = ", ".join(x for x in (
            f"RUWE {rec['star_ruwe']:.2f}" if (rec["star_ruwe"] or 0) >= 1.4 else "",
            "duplicated source" if rec["star_dup"] == 1 else "", "no Gaia proper motion" if rec["star_no_pm"] == 1 else "")
            if x)
    else:
        rec["star_flag"] = ""
    # shape-model fits: the number and the 'good fit' volume diameters
    good = []
    n_fits = 0
    for x in ev.iter("Fit"):
        p = _split(x.text)
        n_fits += 1
        if len(p) > 6 and _i(p[3]) == 6 and _f(p[5]) and _f(p[6]):
            good.append((_f(p[5]) + _f(p[6])) / 2.0)
    rec.update(shape_fits=n_fits, shape_dia_km=round(sum(good) / len(good), 1) if good else None)
    # satellites (with the CBET that announced an occultation discovery) and double-star solutions
    sats = [_split(s.text) for s in ev.iter("Satellite")]
    if sats:
        s = sats[0]
        rec.update(n_sat=len(sats), sat_name=", ".join(x[0] for x in sats if x[0]),
                   sat_sep_mas=_f(s[5]) if len(s) > 5 else None, sat_pa_deg=_f(s[6]) if len(s) > 6 else None,
                   sat_dia_km=_f(s[9]) if len(s) > 9 else None,
                   sat_fit=SAT_FIT.get(_i(s[12]) if len(s) > 12 else None, ""),
                   sat_cbet=", ".join(x[13] for x in sats if len(x) > 13 and x[13] not in ("", "0")))
    dbl = [_split(s.text) for s in ev.iter("Solution")]
    if dbl and len(dbl[0]) > 1:
        rec.update(star_double=f"PA {dbl[0][0]}°, separation {dbl[0][1]} mas")
    # observers: positive chords, misses, durations (main star), and each one's D and R as contacts
    contacts, names, n_pos, n_miss, n_cloud, durs, sites = [], [], 0, 0, 0, [], {}
    day0 = datetime(int(date[0]), int(date[1]), int(date[2]), tzinfo=timezone.utc)
    pred = ""
    for el in ev.find("Observations") if ev.find("Observations") is not None else []:
        if el.tag == "Prediction":
            p = _split(el.text)
            pred = pred or (p[4] if len(p) > 4 else "")
            continue
        if el.tag != "Observer":
            continue
        idf = _split(el.findtext("ID"))
        who = idf[1] if len(idf) > 1 else ""
        place = ", ".join(x for x in (idf[4] if len(idf) > 4 else "", idf[5] if len(idf) > 5 else "") if x)
        names.append(who)
        d, r = _split(el.findtext("D")), _split(el.findtext("R"))
        code_d, code_r = (d[1] if len(d) > 1 else ""), (r[1] if len(r) > 1 else "")
        if code_d in POSITIVE:
            n_pos += 1
        elif code_d == "M" or code_r == "M":
            n_miss += 1
        elif code_d == "C" or code_r == "C":
            n_cloud += 1
        hd, hr = _hms(d[0] if d else ""), _hms(r[0] if r else "")
        if code_d == "D" and code_r == "R" and hd is not None and hr is not None and hr > hd:
            durs.append((hr - hd) * 3600.0)
        cond = _split(el.findtext("Conditions"))
        site = dict(observer=who, place=place, lon=_dms(idf[6]) if len(idf) > 6 else None,
                    lat=_dms(idf[7]) if len(idf) > 7 else None, alt_m=_f(idf[8]) if len(idf) > 8 else None,
                    datum=(idf[9] if len(idf) > 9 else "").strip() or "_",
                    method=(idf[12] if len(idf) > 12 else "").strip(),
                    time_adj_s=_f(cond[3]) if len(cond) > 3 else None)
        result = ("positive" if code_d in POSITIVE else "miss" if "M" in (code_d, code_r) else
                  "clouded" if "C" in (code_d, code_r) else code_d or "?")
        k = (who, site["lon"], site["lat"])                   # one entry per observer and place (cameras, satellite chords)
        if k not in sites or result == "positive":
            sites[k] = dict(site, result=result)
        for label, part, h in (("D", d, hd), ("R", r, hr)):
            if h is not None and len(part) > 1 and part[1] not in ("", "C", "M"):
                t = day0 + timedelta(hours=h)
                contacts.append((part[1], t.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-4], None,
                                 dict(site, code=part[1], acc_s=_f(part[2]) if len(part) > 2 else None,
                                      pe_s=_f(part[3]) if len(part) > 3 else None,
                                      include=(part[5] if len(part) > 5 else "").strip() or "_")))
    who = list(dict.fromkeys(x for x in names if x))         # an observer appears once per chord (cameras, satellite)
    rec.update(n_observers=len(who) or len(names), n_records=len(names), n_positive=n_pos, n_miss=n_miss,
               n_cloud=n_cloud, max_duration_s=round(max(durs), 2) if durs else None, observers="; ".join(who),
               prediction=pred, obs_sites=list(sites.values()))
    return rec, contacts


def build(xml_file=None, db_file=None, csv_file=None, log=print):
    """Parse the archive into a fresh database (written beside, then swapped in) and export its CSV.
    Returns the number of events."""
    import xml.etree.ElementTree as ET
    x0, d0, c0 = paths()
    xml_file, db_file, csv_file = xml_file or x0, db_file or d0, csv_file or c0
    if not os.path.isfile(xml_file):
        raise SystemExit(f"{xml_file} not found: download the 'observations' dataset (System tab, Occult data, or "
                         f"pysyzygos occult-data add observations)")
    t0 = time.time()
    tmp = db_file + ".new"
    for f in (tmp, tmp + "-wal", tmp + "-shm"):
        if os.path.exists(f):
            os.remove(f)
    con = db.connect(tmp)
    con.execute("PRAGMA synchronous=OFF")
    run_id, _ = db.start_run(con, "occult-archive", lst=LIST)
    n, bad, last = 0, 0, ""
    for _, el in ET.iterparse(xml_file, events=("end",)):
        if el.tag != "Event":
            continue
        try:
            rec, contacts = record(el)
            db.add_event(con, run_id, rec, kind="asteroid", contacts=contacts, commit=False)
            n += 1
            last = max(last, rec["best_utc"])
        except (ValueError, IndexError) as ex:
            bad += 1
            log(f"skipped an event ({ex})")
        el.clear()
        if n % 2000 == 0:
            con.commit()
    db.finish_run(con, run_id, dict(kind="observed", source="IOTA / Occult archive (D. Herald), Asteroid~Observations.xml",
                                    file=os.path.basename(xml_file),
                                    file_date=time.strftime("%Y-%m-%d", time.gmtime(os.path.getmtime(xml_file))),
                                    events=n, skipped=bad, events_until=last[:10], version=__version__,
                                    run_utc=time.strftime("%Y-%m-%d %H:%M", time.gmtime())))
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    con.close()
    for f in (db_file + "-wal", db_file + "-shm"):
        if os.path.exists(f):
            os.remove(f)
    os.replace(tmp, db_file)
    con = db.connect(db_file)
    db.export(con, csv_file, lst=LIST)
    con.close()
    from pysyzygos import obscheck                            # earlier checks of our predictions: kept
    res = obscheck.load_results(os.path.join(os.path.dirname(db_file), obscheck.RESULTS))
    if res and os.path.abspath(db_file) == os.path.abspath(paths()[1]):
        obscheck.apply_to_db(res, log)
    log(f"observed events: {n} written to {db_file} and {csv_file} ({time.time() - t0:.0f} s)"
        + (f", {bad} skipped" if bad else ""))
    return n


METHODS = {"a": "video", "b": "DSLR video", "c": "photometer", "d": "sequential images", "e": "drift scan",
           "f": "visual", "g": "other"}
DATUMS = {"_": "WGS84", "": "WGS84", "N": "NAD1927", "E": "ED1950", "T": "Tokyo", "G": "GB1936", "*": "unspecified"}


def find(key, db_file=None):
    """(record, contacts [(label, utc, data)]) of the event with this key ('target|YYYY-MM-DDTHH:MM:SS', the report's
    data-ev), or (None, [])."""
    tid, utc = (key.split("|") + [""])[:2]
    con = db.connect(db_file or paths()[1])
    try:
        row = con.execute("SELECT id, record FROM events WHERE target_id=? AND best_utc LIKE ? ORDER BY id LIMIT 1",
                          (tid, utc[:19] + "%")).fetchone()
        if row is None:
            return None, []
        cts = [(r["label"], r["utc"], json.loads(r["data"])) for r in
               con.execute("SELECT label, utc, data FROM contacts WHERE event_id=? ORDER BY utc", (row["id"],))]
        return json.loads(row["record"]), cts
    finally:
        con.close()


def _v(x, fmt="{}", none="\u2014"):
    if x is None or x == "" or (isinstance(x, float) and not math.isfinite(x)):
        return none
    try:
        return fmt.format(x)
    except (ValueError, TypeError):
        return str(x)


def _sexa(deg, hours=True):
    """'02h32m08.786s' (hours=True, RA in degrees) or '+44°56'40.07"' (Dec)."""
    v = deg / 15.0 if hours else abs(deg)
    h = int(v); m = int((v - h) * 60); s = ((v - h) * 60 - m) * 60
    return (f"{h:02d}h{m:02d}m{s:06.3f}s" if hours else
            f"{'-' if deg < 0 else '+'}{h:02d}\u00b0{m:02d}'{s:05.2f}\"")


def details(rec, contacts=()):
    """The whole record as ([(section, [(label, value)])], [observer rows (dict)]) for the GUI dialog and `show`.
    Observer rows: one per observer and site: their D/R (and satellite, 2nd-star) times with accuracy and personal
    equation, result, duration, and PySyzygos's check of that chord (obs_check) when there is one."""
    r = rec
    f = lambda k, fmt="{}": _v(r.get(k), fmt)
    sec = []
    sec.append(("Event", [
        ("Asteroid", r.get("target_name", "")), ("Reference time (UT)", f"{r.get('best_utc', '')}"
                                                 + (f" \u00b1 {r['ref_time_unc_s']:.3f} s" if r.get("ref_time_unc_s") else "")),
        ("Geocentric conjunction (UT)", f("conj_utc")),
        ("Conjunction X, Y (km)", f"{_v(r.get('conj_x_km'), '{:.1f}')}, {_v(r.get('conj_y_km'), '{:.1f}')}"),
        ("Distance", f("dist_au", "{:.4f} au")),
        ("Diameter (catalog)", (f"{2 * r['r_km']:.1f} km" + (f" \u00b1 {2 * r['r_unc_km']:.1f}" if r.get("r_unc_km") else ""))
         if r.get("r_km") else "\u2014"),
        ("Asteroid magnitude", f("m_ast", "{:.2f}")), ("Prediction used", f("prediction")),
        ("Observers", f"{_v(r.get('n_observers'))} ({_v(r.get('n_positive'))} positive chords, {_v(r.get('n_miss'))} "
                      f"misses, {_v(r.get('n_cloud'))} clouded)"),
        ("Longest chord", f("max_duration_s", "{:.2f} s")), ("MPC publication", f("mpc")),
        ("Added / last edited", f"{_v(r.get('added'))} / {_v(r.get('last_edited'))}")]))
    ra, de = r.get("star_ra"), r.get("star_dec")
    sec.append(("Star", [
        (("Gaia id", f"{_v(r.get('star'))} (Gaia version {_v(r.get('star_gaia_version'))})")
         if r.get("star_gaia_version") not in (0, 9, "0", "9") else       # too bright for Gaia: Hipparcos 2 / UBSC
         ("Star", f"HIP {_v(r.get('star'))} ({'Hipparcos 2' if str(r.get('star_gaia_version')) == '0' else 'UBSC'}"
                  f" position: too bright for Gaia)")),
        ("Catalog name", f("star_catalog")),
        ("RA, Dec (J2000, at the event)", f"{_sexa(ra)} {_sexa(de, False)}  ({ra:.8f}\u00b0, {de:.8f}\u00b0)"
         if ra is not None and de is not None else "\u2014"),
        ("Uncertainty RA, Dec", f"{_v(r.get('star_ra_err_mas'))}, {_v(r.get('star_dec_err_mas'))} mas"),
        ("G, BP, RP", f"{_v(r.get('mag'), '{:.2f}')}, {_v(r.get('star_bp'), '{:.2f}')}, {_v(r.get('star_rp'), '{:.2f}')}"),
        ("Angular diameter", f("star_diam_mas", "{:.2f} mas")), ("RUWE", f("star_ruwe", "{:.2f}")),
        ("Flags", r.get("star_flag") or "none"), ("Double-star solution", f("star_double"))]))
    sec.append(("Fit to the chords (Occult)", [
        ("Quality", f"{f('fit_quality_text')} ({f('fit_quality')}); fit code {f('fit_code')}"),
        ("Ellipse", (f"{r['fit_major_km']:.1f} \u00d7 {r['fit_minor_km']:.1f} km, PA {_v(r.get('fit_pa_deg'), '{:.0f}')}\u00b0"
                     + (" (axes assumed)" if r.get("fit_assumed_size") else " (fitted)")) if r.get("fit_major_km") else "\u2014"),
        ("Centre uncertainty", f"{_v(r.get('fit_x_sdev_km'))}, {_v(r.get('fit_y_sdev_km'))} km"),
        ("Shape-model fits", f"{_v(r.get('shape_fits'))}" + (f", good fits {r['shape_dia_km']:.1f} km" if r.get("shape_dia_km") else "")),
        ("Observed centre X, Y (geocentric, of date)", f"{_v(r.get('geo_x_km'), '{:.1f}')}, {_v(r.get('geo_y_km'), '{:.1f}')} km"),
        ("Astrometry offset RA\u00b7cosDec, Dec", f"{_v(r.get('obs_dra_arcsec'), '{:.4f}')}\", {_v(r.get('obs_ddec_arcsec'), '{:.4f}')}\""),
        ("Chords used", f("n_chords")), ("Flagged for review", "yes" if r.get("fit_review") else "no")]))
    if r.get("n_sat"):
        sec.append(("Satellite", [
            ("Name", r.get("sat_name") or "(unnamed)"), ("Fit", f("sat_fit")),
            ("Separation, PA", f"{_v(r.get('sat_sep_mas'), '{:.2f}')} mas, {_v(r.get('sat_pa_deg'), '{:.1f}')}\u00b0"),
            ("Diameter", f("sat_dia_km", "{:.1f} km")), ("Announced in", f"CBET {r['sat_cbet']}" if r.get("sat_cbet") else "\u2014")]))
    if r.get("chk_v") or r.get("chk_across_km") is not None or r.get("chk_note"):
        sec.append(("PySyzygos check (obs-check)", [
            ("Chord mid-times obs \u2212 pred (median)", f("chk_site_dt_s", "{:+.3f} s")
             + (f" over {r['chk_chord_n']} chords" if r.get("chk_chord_n") else "")),
            ("Best size used", f("chk_size_best")),
            ("Archive's centre obs \u2212 pred", f"{_v(r.get('chk_across_km'), '{:+.2f}')} km across, "
                                              f"{_v(r.get('chk_along_s'), '{:+.3f}')} s along ({_v(r.get('chk_mas'), '{:.1f}')} mas)"),
            ("Note", f("chk_note"))]))
    # observers: one row per observer and site
    rows, chk = {}, {}
    for c in r.get("chk_chords") or []:
        chk[(c.get("observer"), round(c.get("lat") or 0, 4), round(c.get("lon") or 0, 4))] = c
    for label, utc, d in contacts:
        k = (d.get("observer"), d.get("lon"), d.get("lat"))
        row = rows.setdefault(k, dict(observer=d.get("observer", ""), place=d.get("place", ""), lat=d.get("lat"),
                                      lon=d.get("lon"), alt_m=d.get("alt_m"), datum=DATUMS.get(d.get("datum", "_"), d.get("datum")),
                                      method=METHODS.get(d.get("method", ""), d.get("method") or "?"), result="positive",
                                      events=[], time_adj_s=d.get("time_adj_s")))
        row.setdefault("t", {})[label] = utc
        row["events"].append(f"{label} {utc[11:]}" + (f" \u00b1{d['acc_s']:g}" if d.get("acc_s") else "")
                             + (f" PE {d['pe_s']:g}" if d.get("pe_s") else "")
                             + (" (excluded)" if (d.get("include") or "_") in ("x",) else ""))
    for s in r.get("obs_sites") or []:
        k = (s.get("observer"), s.get("lon"), s.get("lat"))
        if k not in rows:
            rows[k] = dict(observer=s.get("observer", ""), place=s.get("place", ""), lat=s.get("lat"), lon=s.get("lon"),
                           alt_m=s.get("alt_m"), datum=DATUMS.get(s.get("datum", "_"), s.get("datum")),
                           method=METHODS.get(s.get("method", ""), s.get("method") or "?"), result=s.get("result", ""),
                           events=[], time_adj_s=s.get("time_adj_s"))
    misses = {m.get("observer"): m for m in r.get("chk_misses") or []}
    out = []
    for k, row in rows.items():
        c = chk.get((row["observer"], round(row["lat"] or 0, 4), round(row["lon"] or 0, 4)))
        if c:
            row.update(dur_obs=c.get("dur_obs_s"), dt_mid=c.get("dt_mid_s"), dist_km=c.get("dist_km"),
                       dur_cat=c.get("dur_pred_s"), dur_best=c.get("dur_pred_best_s"))
        elif row["result"] == "miss" and row["observer"] in misses:
            row.update(dist_km=misses[row["observer"]].get("dist_km"))
        row["events"] = "; ".join(row["events"])
        t = row.pop("t", {})                                  # durations from the observer's own times
        def dur(a, b):
            try:
                v = (datetime.fromisoformat(t[b]) - datetime.fromisoformat(t[a])).total_seconds()
                return v if 0 < v < 3600 else None
            except (KeyError, ValueError):
                return None
        if row.get("dur_obs") is None:
            row["dur_obs"] = dur("D", "R")
        row["dur_obs2"] = dur("d", "r")                       # the second star of a double
        out.append(row)
    return sec, out


def status(base=None):
    """dict(events, events_until, built, file_date) of the database, or None if not built."""
    _, d, _ = paths(base)
    if not os.path.isfile(d):
        return None
    con = db.connect(d)
    try:
        s = (db.runs(con, lst=LIST) or [{}])[-1]
    finally:
        con.close()
    return dict(events=s.get("events"), events_until=s.get("events_until"), built=s.get("run_utc"),
                file_date=s.get("file_date"), checked=s.get("checked"))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="pysyzygos observed", description=__doc__.splitlines()[0])
    ap.add_argument("--version", action="version", version=f"PySyzygos {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="build the database from the archive's XML (the 'observations' dataset)")
    b.add_argument("--xml"); b.add_argument("--db"); b.add_argument("--csv")
    sub.add_parser("status")
    s = sub.add_parser("show", help="the observed events of one asteroid (with --date: all details of that event)")
    s.add_argument("asteroid")
    s.add_argument("--date", help="YYYY-MM-DD[THH:MM]: the full record of that event")
    a = ap.parse_args(argv)
    if a.cmd == "build":
        build(a.xml, a.db, a.csv)
    elif a.cmd == "status":
        st = status()
        print("not built (pysyzygos observed build)" if st is None else
              f"{st['events']} observed events until {st['events_until']} (archive file of {st['file_date']}, "
              f"built {st['built']} UTC)" + (f"; predictions checked {st['checked']}" if st.get("checked") else ""))
    elif a.date:
        _, d, _ = paths()
        con = db.connect(d)
        row = con.execute("SELECT best_utc FROM events WHERE target_id=? AND best_utc LIKE ? ORDER BY best_utc LIMIT 1",
                          (a.asteroid, a.date + "%")).fetchone()
        con.close()
        if row is None:
            sys.exit(f"no observed event of {a.asteroid} on {a.date}")
        rec, cts = find(f"{a.asteroid}|{row[0][:19]}")
        sec, obs = details(rec, cts)
        for title, items in sec:
            print(f"\n{title}")
            for k, v in items:
                print(f"  {k:<42} {v}")
        print("\nObservers")
        for o in obs:
            print(f"  {o['result']:<9} {o['observer'][:24]:<24} {o['place'][:30]:<30} {_v(o['lat'], '{:.5f}')} "
                  f"{_v(o['lon'], '{:.5f}')} {_v(o['alt_m'], '{:.0f}')} m {o['datum']}, {o['method']}: {o['events']}"
                  + (f"  | ours: mid {o['dt_mid']:+.3f} s, {o['dist_km']:.2f} km from the center line, duration "
                     f"{o['dur_obs']:.2f} s (catalog {_v(o.get('dur_cat'), '{:.2f}')}, best {_v(o.get('dur_best'), '{:.2f}')})"
                     if o.get("dt_mid") is not None else (f"  | ours: {o['dist_km']:.2f} km from the center line"
                                                          if o.get("dist_km") is not None else "")))
    else:
        _, d, _ = paths()
        con = db.connect(d)
        for r in con.execute("SELECT record FROM events WHERE target_id=? ORDER BY best_utc", (a.asteroid,)):
            r = json.loads(r[0])
            print(f"{r['best_utc'][:19]}  {r['target_name']:<28} G {r.get('mag') or 0:5.2f}  chords "
                  f"{r.get('n_positive')}/{r.get('n_observers')}  {r.get('fit_quality_text')}"
                  + (f"  satellite {r['sat_name'] or '?'} CBET {r['sat_cbet']}" if r.get("sat_cbet") else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
