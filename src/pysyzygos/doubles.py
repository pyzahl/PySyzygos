"""doubles.py - close and double stars at an event: neighbours whose light blends with the target star's in the
camera, the drop with that light included, and Gaia's hints that the star itself is double.

Local check (every event, from the local catalog): stars within companion_radius_arcsec of the target star at the
event date. Their light stays when the target star is covered, so the real drop is smaller than the star's own:
    drop = 2.5 log10((F_star + F_comp + F_ast) / (F_comp + F_ast))
Online check (optional, gaia_online_check; one query per run to the Gaia DR3 archive): the same neighbours without
the local catalog's limits (fainter stars, and stars with RUWE >= 1.4 that the catalog leaves out, often unresolved
doubles), and Gaia's flags for the target star: non_single_star (a known binary solution), ipd_frac_multi_peak
(% of scans with two peaks: a resolved close pair), duplicated_source, ruwe.

With a format-2 catalog that has its quality part (starcat.py), Gaia's flags of the star and its error ellipse come
from the local catalog at once (no network); the online check still adds neighbours fainter than the catalog.

Record fields: blend_n (neighbours within the radius), blend_sep_arcsec and blend_g (the closest one),
mag_drop_blended, double_hint (text for the report), double_check ("local" or "gaia online"); online, or locally with
the quality part, also gaia_ruwe, gaia_nss, gaia_multi_peak, gaia_dup and the star's error ellipse (star_err_*). Reference information: events are flagged, not removed.
"""
from pysyzygos.version import __version__
import csv, math, os, tempfile, threading
import numpy as np

DMAG = 5.0                 # neighbours more than this fainter than the star are ignored (< 1 % of its light)
MULTI_PEAK = 2             # ipd_frac_multi_peak above this (%): Gaia saw two peaks, likely a close pair
NOTE_DMAG = 0.1            # a neighbour is noted (double_hint) when it lowers the drop by at least this
GAIA_EPOCH = 2016.0


def _sep_arcsec(ra1, de1, ra2, de2):
    """Angular separation in arcsec (vectorised; degrees in)."""
    r1, d1, r2, d2 = (np.radians(np.asarray(x, float)) for x in (ra1, de1, ra2, de2))
    s = np.sin((d2 - d1) / 2) ** 2 + np.cos(d1) * np.cos(d2) * np.sin((r2 - r1) / 2) ** 2
    return np.degrees(2 * np.arcsin(np.sqrt(np.clip(s, 0, 1)))) * 3600.0


def _propagate(ra, dec, pmra, pmdec, years):
    """Positions at GAIA_EPOCH + years (linear proper motion; missing motion = 0)."""
    pmra, pmdec = np.nan_to_num(np.asarray(pmra, float)), np.nan_to_num(np.asarray(pmdec, float))
    cosd = np.maximum(np.cos(np.radians(np.asarray(dec, float))), 1e-6)
    return (np.asarray(ra, float) + pmra / cosd * years / 3.6e6) % 360.0, np.asarray(dec, float) + pmdec * years / 3.6e6


def companions(stars, star_id, ra, dec, g_star, years, radius_arcsec):
    """[(sep_arcsec, G, source_id)] of the stars (DataFrame with source_id, ra, dec, pmra, pmdec, phot_g_mean_mag;
    Gaia epoch) within radius_arcsec of (ra, dec) at the event (years after 2016.0), not the star itself and not more
    than DMAG fainter; closest first."""
    if stars is None or len(stars) == 0:
        return []
    s = stars[stars["source_id"].astype("int64") != int(star_id)]
    s = s[np.isfinite(s["phot_g_mean_mag"].astype(float)) & (s["phot_g_mean_mag"].astype(float) <= g_star + DMAG)]
    if len(s) == 0:
        return []
    r, d = _propagate(s["ra"], s["dec"], s["pmra"], s["pmdec"], years)
    sep = _sep_arcsec(ra, dec, r, d)
    keep = sep <= radius_arcsec
    out = sorted(zip(sep[keep].tolist(), s["phot_g_mean_mag"].astype(float)[keep].tolist(),
                     s["source_id"].astype("int64")[keep].tolist()))
    return [(round(a, 2), round(b, 2), c) for a, b, c in out]


def blended_drop(m_star, m_ast, comp_mags):
    """Drop (mag) when the star is covered and its neighbours' light (comp_mags) stays."""
    f = lambda m: 10 ** (-0.4 * m)
    f_ast = f(m_ast) if m_ast is not None and np.isfinite(m_ast) else 0.0
    f_comp = sum(f(m) for m in comp_mags)
    if f_ast + f_comp <= 0:
        return float("inf")
    return 2.5 * math.log10((f(m_star) + f_comp + f_ast) / (f_comp + f_ast))


def fields(comps, m_star, m_ast, source="local", flags=None):
    """The record fields (module doc) from the neighbours list and, online, Gaia's flags of the star."""
    flags = flags or {}
    hints = []
    if flags.get("gaia_nss"):
        hints.append(f"Gaia: non-single star (NSS {int(flags['gaia_nss'])})")
    if (flags.get("gaia_multi_peak") or 0) > MULTI_PEAK:
        hints.append(f"Gaia: two peaks in {int(flags['gaia_multi_peak'])} % of scans (close pair?)")
    if flags.get("gaia_dup"):
        hints.append("Gaia: duplicated source")
    blended = blended_drop(m_star, m_ast, [c[1] for c in comps]) if comps else float("nan")
    if comps and blended_drop(m_star, m_ast, []) - blended >= NOTE_DMAG:
        sep, g, _ = comps[0]
        more = f" (+{len(comps) - 1} more)" if len(comps) > 1 else ""
        hints.append(f"companion G {g:.1f} at {sep:.1f}″{more}: drop {blended_drop(m_star, m_ast, [c[1] for c in comps]):.2f} mag "
                     "with its light")
    out = dict(blend_n=len(comps), blend_sep_arcsec=comps[0][0] if comps else np.nan,
               blend_g=comps[0][1] if comps else np.nan,
               mag_drop_blended=blended if comps else np.nan,
               double_hint="; ".join(hints), double_check=source)
    out.update(flags)
    return out


# ---------------------------------------------------------------- online check (Gaia archive, network only)
ERROR_COLS = "ra_error, dec_error, pmra_error, pmdec_error, ra_dec_corr, pmra_pmdec_corr, ra_pmra_corr, ra_pmdec_corr, " \
             "dec_pmra_corr, dec_pmdec_corr"                     # the star's error ellipse (ellipses.star_ellipse)
ARCHIVE_COLS = "source_id, ra, dec, pmra, pmdec, phot_g_mean_mag, ruwe, non_single_star, ipd_frac_multi_peak, " \
               "duplicated_source, " + ERROR_COLS


def query_text(points, radius_arcsec):
    """One ADQL query for all events: circles around each (ra, dec) at the Gaia epoch, padded for proper motion."""
    r = (radius_arcsec + 3.0) / 3600.0
    circles = " OR ".join(f"1=CONTAINS(POINT('ICRS', ra, dec), CIRCLE('ICRS', {ra:.7f}, {de:.7f}, {r:.6f}))"
                          for ra, de in points)
    return f"SELECT {ARCHIVE_COLS} FROM gaiadr3.gaia_source WHERE {circles}"


def fetch_online(points, radius_arcsec, timeout_s=120):
    """DataFrame of archive stars around the points, or None (offline, slow, failed); waited for at most timeout_s
    in a daemon thread. Synchronous queries of CHUNK points each: a few stars per circle stay far below the
    synchronous 2000-row cap (checked: a chunk that reaches it is reported); the asynchronous job's status polling
    hung for minutes in 2026-10 while the synchronous query answered in seconds."""
    import pandas as pd
    box = {"parts": []}

    def work():
        try:
            from astroquery.gaia import Gaia
            for i in range(0, len(points), CHUNK):
                t = Gaia.launch_job(query_text(points[i:i + CHUNK], radius_arcsec), verbose=False).get_results()
                if len(t) >= 2000:
                    print(f"* Gaia online check: {len(t)} rows for {len(points[i:i + CHUNK])} events, may be cut")
                box["parts"].append(t.to_pandas())
            box["done"] = True
        except Exception as ex:                                   # network, archive or astroquery trouble
            box["err"] = ex
    th = threading.Thread(target=work, daemon=True)
    th.start()
    th.join(timeout_s)
    if not box.get("done"):
        print(f"* Gaia online check skipped: {box.get('err', f'no answer within {timeout_s} s')}")
        return None
    df = pd.concat(box["parts"], ignore_index=True) if box["parts"] else pd.DataFrame()
    df.columns = [c.lower() for c in df.columns]
    return df


CHUNK = 50                # events per synchronous archive query (fetch_online)


def fetch_star_errors(source_ids, timeout_s=120):
    """{source_id: Gaia DR3 row (dict) with the error columns} for these stars; None when the archive cannot be
    reached (favorites.backfill_errors). Synchronous queries of at most 1000 ids each: a lookup by source_id returns
    at most one row per id, so the synchronous 2000-row cap cannot cut it (the asynchronous job's status polling
    hung for minutes in 2026-10 while the synchronous query answered in seconds)."""
    ids = sorted({int(s) for s in source_ids})
    if not ids:
        return {}
    box = {"rows": []}

    def work():
        try:
            from astroquery.gaia import Gaia
            for i in range(0, len(ids), 1000):
                q = (f"SELECT source_id, {ERROR_COLS} FROM gaiadr3.gaia_source "
                     f"WHERE source_id IN ({', '.join(map(str, ids[i:i + 1000]))})")
                df = Gaia.launch_job(q, verbose=False).get_results().to_pandas()
                df.columns = [c.lower() for c in df.columns]
                box["rows"] += df.to_dict("records")
            box["done"] = True
        except Exception as ex:
            box["err"] = ex
    th = threading.Thread(target=work, daemon=True)
    th.start()
    th.join(timeout_s)
    if not box.get("done"):
        return None
    return {int(r["source_id"]): r for r in box["rows"]}


def star_flags(stars, star_id, years):
    """Gaia's flags and the 1-sigma error ellipse of the star from catalog rows with Gaia's column names (the online
    check's archive rows, or a format-2 local catalog with its quality part: starcat.StarCatalog.cone); {} if the star
    is not there or the rows have no such columns."""
    if stars is None or len(stars) == 0 or "non_single_star" not in stars:
        return {}
    me = stars[stars["source_id"].astype("int64") == int(star_id)]
    if not len(me):
        return {}
    m = me.iloc[0]
    g = lambda k: None if k not in m or m[k] is None or (isinstance(m[k], float) and not np.isfinite(m[k])) else m[k]
    flags = dict(gaia_ruwe=g("ruwe"), gaia_nss=int(g("non_single_star") or 0),
                 gaia_multi_peak=int(g("ipd_frac_multi_peak") or 0), gaia_dup=bool(g("duplicated_source")))
    from pysyzygos import ellipses
    se = ellipses.star_ellipse(m, years) if "ra_error" in m else None
    if se:                                                        # the star's 1-sigma ellipse at the event date
        flags.update(star_err_smaa_mas=se[0], star_err_smia_mas=se[1], star_err_pa_deg=se[2])
    return flags


def online_fields(records, radius_arcsec, archive):
    """Per record (dicts with star, star_ra, star_dec, mag, m_ast, best_et): the fields from the archive stars."""
    out = []
    for r in records:
        years = 2000.0 + float(r["best_et"]) / (365.25 * 86400) - GAIA_EPOCH
        sid = int(r["star"])
        flags = star_flags(archive, sid, years)
        comps = companions(archive, sid, float(r["star_ra"]), float(r["star_dec"]), float(r["mag"]), years,
                           radius_arcsec)
        out.append(fields(comps, float(r["mag"]), r.get("m_ast"), "gaia online", flags))
    return out



# ---------------------------------------------------------------- VizieR check (on demand: the favorites panel)
WDS_COLS = ("WDS", "Disc", "Comp", "Obs1", "Obs2", "Nobs", "pa2", "sep2", "mag1", "mag2", "SpType", "Notes", "_r")
GAIA_COLS = ("RUWE", "IPDfmp", "IPDgofha", "epsi", "sepsi", "E(BP/RP)", "Dup", "NSS")


def _vizier(params, timeout=60, fetch=None):
    """Rows (list of dicts) of a VizieR ASU tab-separated query (urls.URL_VIZIER_ASU)."""
    import urllib.parse
    from pysyzygos import net, urls as U
    url = U.URL_VIZIER_ASU + "?" + urllib.parse.urlencode(params)
    if fetch is None:
        with net.urlopen(url, timeout=timeout) as r:
            text = r.read().decode("utf-8", errors="replace")
    else:
        text = fetch(url)
    lines = [ln for ln in text.splitlines() if ln and not ln.startswith("#")]
    if len(lines) < 3:
        return []
    head = [h.strip() for h in lines[0].split("\t")]
    out = []
    for ln in lines[3:]:                                          # (after the header: units and a dashes line)
        v = [x.strip() for x in ln.split("\t")]
        if len(v) >= len(head):
            out.append(dict(zip(head, v)))
    return out


def vizier_check(star_id, ra_deg, dec_deg, radius_arcsec=30.0, fetch=None):
    """Known pairs and Gaia's binarity signs of a star, from VizieR (needs the network; a few seconds):
    'wds': the Washington Double Star Catalog's pairs within radius_arcsec (WDS positions are often good to a few
    arcsec only), each with discoverer code, components, first/last observation, last PA and separation, magnitudes,
    notes ('O': an orbit in ORB6); 'gaia': Gaia DR3's RUWE, ipd_frac_multi_peak, ipd_gof_harmonic_amplitude,
    astrometric_excess_noise (+ significance), phot_bp_rp_excess_factor, duplicated_source, non_single_star;
    'hints': short readings of them. Raises OSError when VizieR cannot be reached."""
    import time
    wds = _vizier({"-source": "B/wds/wds", "-c": f"{ra_deg:.6f} {dec_deg:+.6f}", "-c.rs": f"{radius_arcsec:g}",
                   "-out": ",".join(WDS_COLS), "-sort": "_r", "-out.max": "50"}, fetch=fetch)
    gaia = _vizier({"-source": "I/355/gaiadr3", "Source": str(int(star_id)), "-out": ",".join(GAIA_COLS),
                    "-out.max": "1"}, fetch=fetch)
    g = gaia[0] if gaia else {}
    f = lambda k: (lambda v: v if v == v else None)(float(g[k])) if str(g.get(k, "")).strip() not in ("", "nan") else None
    hints = []
    if (f("RUWE") or 0) >= 1.4:
        hints.append(f"RUWE {f('RUWE'):.2f}: the single-star solution fits poorly (often an unresolved pair)")
    if (f("IPDfmp") or 0) > MULTI_PEAK:
        hints.append(f"two peaks in {f('IPDfmp'):.0f} % of the scans: a close pair (~0.1-1\")")
    if (f("IPDgofha") or 0) > 0.1:
        hints.append(f"elongated image (harmonic amplitude {f('IPDgofha'):.2f}): a close pair along one direction?")
    if (f("sepsi") or 0) > 2:
        hints.append(f"significant excess noise {f('epsi'):.2f} mas (significance {f('sepsi'):.0f}): "
                     f"an unresolved companion?")
    if str(g.get("Dup", "")).strip() in ("1", "True", "true"):
        hints.append("duplicated source in Gaia")
    if str(g.get("NSS", "")).strip() not in ("", "0"):
        hints.append(f"Gaia binary solution (non_single_star {g.get('NSS')})")
    if (f("E(BP/RP)") or 0) > 1.5:
        hints.append(f"colour excess {f('E(BP/RP)'):.2f}: light of a neighbour in Gaia's 3.5\" colour window?")
    for p in wds:
        if "O" in p.get("Notes", ""):
            hints.append(f"WDS {p.get('WDS')} {p.get('Disc')} {p.get('Comp')}: an orbit is known (ORB6)")
    return dict(checked=time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()), radius_arcsec=radius_arcsec, wds=wds,
                gaia=g, hints=hints)


def vizier_text(v):
    """Lines for the favorites panel from vizier_check's result."""
    if not v:
        return []
    lines = [f"VizieR check of {v.get('checked', '?')} (WDS within {v.get('radius_arcsec', 30):g}\", Gaia DR3):"]
    w = v.get("wds") or []
    if w:
        for p in w[:12]:
            lines.append(f"WDS {p.get('WDS', '')} {p.get('Disc', '')} {p.get('Comp', '')}".rstrip() +
                         f": {p.get('sep2', '?')}\" at {p.get('pa2', '?')}\u00b0 ({p.get('Obs2', '?')}), "
                         f"mag {p.get('mag1', '?')} / {p.get('mag2', '?')}, {p.get('Nobs', '?')} obs. "
                         f"since {p.get('Obs1', '?')}" + (f", notes {p['Notes']}" if p.get("Notes") else "") +
                         (f" [{float(p['_r']):.0f}\" from the star]" if p.get("_r") else ""))
    else:
        lines.append("WDS: no known pair within the radius")
    g = v.get("gaia") or {}
    if g:
        lines.append("Gaia DR3: " + ", ".join(f"{k} {g[k]}" for k in GAIA_COLS if str(g.get(k, "")).strip()))
    lines += [f"\u2192 {h}" for h in v.get("hints") or []] or ["\u2192 no sign of a companion in these sources"]
    return lines
