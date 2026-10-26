"""pmcheck.py - the proper-motion estimates of a 2-parameter star (Gaia DR3 measured its position only), from VizieR,
and how far apart they put the star at the event date: the realistic uncertainty of its position and the alternative
shadow paths.

Gaia DR3 has no proper motion for these stars; the catalog keeps the one with the smallest quoted error
(ABOUT.md 2.4.1). For close doubles, the usual case, the quoted errors are too small: the estimates disagree by more.
Four estimates, all from one UCAC5 and one UCAC4 row:

    UCAC5                    its proper motion (UCAC positions re-reduced against Gaia DR1, + Gaia DR1 2015.0)
    UCAC4                    its own proper motion
    UCAC4 epoch to Gaia      UCAC4's measured position (central epoch, ~1998) to Gaia's 2016.0 (starcat.epoch_pm)
    UCAC4 J2000 to Gaia      UCAC4's J2000 position to Gaia's 2016.0: the motion Occult uses for such stars

`estimates` returns them with the star's offset at the event from the position with the proper motion used
(east, north, mas); `spread_mas` is their RMS, the star's realistic 1-sigma when larger than the quoted error. A
VizieR answer per event (two queries, ~1 s); never raises (an empty list offline). Standard library + numpy.
"""
from pysyzygos.version import __version__
from pysyzygos import urls as U
import math, urllib.parse
import numpy as np

UCAC5, UCAC4 = "I/340/ucac5", "I/322A/out"
UCAC5_COLS = "RAgaia,DEgaia,pmRA,e_pmRA,pmDE,e_pmDE,Gmag"
UCAC4_COLS = "UCAC4,RAJ2000,DEJ2000,e_RAJ2000,e_DEJ2000,EpRA,EpDE,pmRA,e_pmRA,pmDE,e_pmDE,f.mag,a.mag"
RADIUS_ARCSEC = 3.0
MATCH_ARCSEC = 1.0                                  # the catalog's position (moved to 2016) within this of Gaia's
GAIA_EPOCH = 2016.0
LABEL_J2000 = "UCAC4 J2000 to Gaia (as Occult)"


def _tsv(text):
    """Rows (dicts) of a VizieR ASU tab-separated answer: '#' comments, header, units row, dashes row."""
    lines = [ln for ln in text.splitlines() if ln.strip() and not ln.startswith("#")]
    if len(lines) < 3:
        return []
    head = [h.strip() for h in lines[0].split("\t")]
    out = []
    for ln in lines[3:]:
        f = [x.strip() for x in ln.split("\t")]
        if len(f) == len(head):
            out.append(dict(zip(head, f)))
    return out


def _query(source, cols, ra, dec, fetch=None):
    q = urllib.parse.urlencode({"-source": source, "-c": f"{ra:.6f} {dec:+.6f}", "-c.rs": f"{RADIUS_ARCSEC:g}",
                                "-out": cols, "-out.max": "20"})
    url = f"{U.URL_VIZIER_ASU}?{q}"
    if fetch is not None:
        return _tsv(fetch(url))
    from pysyzygos.net import urlopen
    with urlopen(url, timeout=30) as r:
        return _tsv(r.read().decode("utf-8", "replace"))


def _num(row, k):
    try:
        v = float(row.get(k, ""))
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def _sep_arcsec(ra1, de1, ra2, de2):
    c = math.cos(math.radians((de1 + de2) / 2))
    return 3600.0 * math.hypot(((ra1 - ra2 + 180) % 360 - 180) * c, de1 - de2)


FAILED = []      # (ra, dec) of stars whose VizieR query failed in this process (search.run_warnings)


def estimates(ra, dec, g, used=(0.0, 0.0), years=10.0, ra_err=None, dec_err=None, fetch=None):
    """The proper-motion estimates of the star at (ra, dec) (Gaia DR3 2016.0, deg), magnitude G: list of dicts
    label, pmra, pmdec (mas/yr, pmRA*cosDec), err (larger axis, mas/yr; None if not given), east, north (mas: its
    position at the event minus the one with the motion `used`, after `years` since 2016.0). Empty if VizieR does not
    answer or nothing matches. fetch(url) -> text stands in for VizieR (tests)."""
    out = []
    try:
        u5 = _query(UCAC5, UCAC5_COLS, ra, dec, fetch)
        u4 = _query(UCAC4, UCAC4_COLS, ra, dec, fetch)
    except Exception:
        FAILED.append((ra, dec))                      # the search's run warnings count these
        return []
    best = None
    for r in u5:                                      # UCAC5: its Gaia DR1 position (2015.0) next to DR3's
        p = [_num(r, k) for k in ("RAgaia", "DEgaia", "pmRA", "pmDE")]
        if None in p or (_num(r, "Gmag") is not None and abs(_num(r, "Gmag") - g) > 0.5):
            continue
        s = _sep_arcsec(ra, dec, p[0], p[1])
        if s <= MATCH_ARCSEC and (best is None or s < best[0]):
            best = (s, r)
    if best:
        r = best[1]
        e = [x for x in (_num(r, "e_pmRA"), _num(r, "e_pmDE")) if x is not None]
        out.append(dict(label="UCAC5", pmra=_num(r, "pmRA"), pmdec=_num(r, "pmDE"), err=max(e) if e else None))
    best = None
    cosd = math.cos(math.radians(dec))
    for r in u4:                                      # UCAC4: its J2000 position moved with its motion to 2016
        p = [_num(r, k) for k in ("RAJ2000", "DEJ2000", "pmRA", "pmDE")]
        if None in p:
            continue
        mag = _num(r, "f.mag") if _num(r, "f.mag") is not None else _num(r, "a.mag")
        if mag is not None and abs(mag - g) > 1.5:
            continue
        s = _sep_arcsec(ra, dec, p[0] + p[2] * 16.0 / 3.6e6 / cosd, p[1] + p[3] * 16.0 / 3.6e6)
        if s <= MATCH_ARCSEC and (best is None or s < best[0]):
            best = (s, r)
    if best:
        r = best[1]
        ra4, de4, pa, pd = (_num(r, k) for k in ("RAJ2000", "DEJ2000", "pmRA", "pmDE"))
        e = [x for x in (_num(r, "e_pmRA"), _num(r, "e_pmDE")) if x is not None]
        out.append(dict(label="UCAC4", pmra=pa, pmdec=pd, err=max(e) if e else None))
        era, ede = _num(r, "EpRA"), _num(r, "EpDE")
        sra, sde = _num(r, "e_RAJ2000"), _num(r, "e_DEJ2000")
        if era and ede and sra is not None and sde is not None:     # the same formula as the catalog (starcat)
            from pysyzygos import starcat
            rec = np.zeros(1, starcat.UCAC4_REC)
            rec["ra"], rec["spd"] = round(ra4 * 3.6e6), round((de4 + 90.0) * 3.6e6)
            rec["cepra"], rec["cepdc"] = round((era - 1900.0) * 100), round((ede - 1900.0) * 100)
            rec["pmrac"], rec["pmdc"] = round(pa * 10), round(pd * 10)
            rec["sigra"], rec["sigdc"] = min(int(sra), 255) - 128, min(int(sde), 255) - 128
            a, d, s1, s2, ok = starcat.epoch_pm(rec, [ra], [dec], None if ra_err is None else [ra_err],
                                                None if dec_err is None else [dec_err])
            if ok[0]:
                out.append(dict(label="UCAC4 epoch to Gaia", pmra=float(a[0]), pmdec=float(d[0]),
                                err=float(max(s1[0], s2[0]))))
        dt = GAIA_EPOCH - 2000.0                       # Occult's way: from the J2000 position to Gaia's
        out.append(dict(label=LABEL_J2000, pmra=((ra - ra4 + 180) % 360 - 180) * cosd * 3.6e6 / dt,
                        pmdec=(dec - de4) * 3.6e6 / dt, err=None))
    for e in out:
        e["east"] = (e["pmra"] - float(used[0])) * years
        e["north"] = (e["pmdec"] - float(used[1])) * years
    return out


def spread_mas(ests):
    """RMS distance (mas) of the estimates' positions at the event from the one used: the star's realistic 1-sigma
    when it is larger than the quoted error (each estimate a plausible true motion). None without estimates."""
    d = [math.hypot(e["east"], e["north"]) for e in ests]
    return float(math.sqrt(sum(x * x for x in d) / len(d))) if d else None


def shifted_dir(star_dir, east_mas, north_mas):
    """The unit star direction moved by (east, north) mas on the sky (x east = z x s, y north)."""
    s = np.asarray(star_dir, float) / np.linalg.norm(star_dir)
    e = np.cross([0.0, 0.0, 1.0], s)
    e /= np.linalg.norm(e)
    n = np.cross(s, e)
    k = math.radians(1.0 / 3.6e6)
    v = s + k * (east_mas * e + north_mas * n)
    return v / np.linalg.norm(v)


def summary(ests, used_label=""):
    """'UCAC5 -4.0, -13.0 ±1.7 (used); UCAC4 epoch to Gaia -3.3, -10.5 ±2.3 (28 mas); ...' for the record."""
    parts = []
    for e in ests:
        d = math.hypot(e["east"], e["north"])
        err = f" ±{e['err']:.1f}" if e.get("err") is not None else ""
        tag = "used" if e["label"] == used_label or d < 0.5 else f"{d:.0f} mas"
        parts.append(f"{e['label']} {e['pmra']:+.1f}, {e['pmdec']:+.1f}{err} ({tag})")
    return "; ".join(parts)
