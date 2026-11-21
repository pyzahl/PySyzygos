"""starinfo.py: WDS and VSX look-ups. Real catalog lines (GSU's wdsweb_summ2.txt, VizieR's vsx.dat) parsed at the
documented columns, a VSX line built from the ReadMe's byte positions, the vectorized and the line-by-line VSX parse
agreeing, matching (the star as primary or as companion, proper motion back to J2000, a variable's magnitude range),
a local copy saved and searched (RA wrap), a VizieR answer with two tables through a stand-in, the run's check in
local / online / off mode, and net.read_first passing over an error page answered with status 200."""
import _testtmp  # noqa: F401  (temporary files of this run in one folder, removed at exit)
import os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
import numpy as np
from pysyzygos import starinfo as S, net

WDS_LINES = [
    "07346+3153STF1110AB    1778 2026 1577 303  49   5.2   5.7  1.93  2.97 A1V+A4Vm  -206-148 -206-148 +32 1581 NO V 073435.86+315317.8",
    "07346+3153CIA  29Aa,Ab 2007 2021   16  38 293   0.0   0.0  1.93   .   A1V       -206-148          +32 1581 NO   073435.86+315317.8",
    "03082+4057LAB   2Aa,Ab 1973 2024  123 123 322   0.1   0.1  2.12  4.6  B8V       +002-001          +40  673 NO   030810.13+405720.3",
]
ZTF = (" 1547582 ZTF J000000.13+620605.8        0   0.00056  62.10163 BY                                16.571   r     "
       "     Y     0.078   r         2458386.76290          1.944997900000                                ")


def vsx_line(oid, name, v, ra, dec, typ, mx, band, mn, amp=False, period=None):
    """A vsx.dat line from the ReadMe's byte positions (1-based, inclusive)."""
    b = [" "] * S.VSX_LRECL
    def put(i, j, text, right=True):
        w = j - i + 1
        t = (text.rjust(w) if right else text.ljust(w))[:w]
        b[i - 1:j] = list(t)
    put(1, 8, str(oid)); put(10, 39, name, False); put(41, 41, str(v)); put(43, 51, f"{ra:9.5f}")
    put(53, 61, f"{dec:9.5f}"); put(63, 92, typ, False); put(96, 102, f"{mx:7.3f}"); put(106, 115, band, False)
    put(117, 117, "Y" if amp else " "); put(121, 127, f"{mn:7.3f}"); put(131, 138, band, False)
    if period:
        put(159, 177, f"{period:19.12f}")
    return "".join(b)


ALGOL = vsx_line(26202, "bet Per", 0, 47.04221, 40.95567, "EA/SD", 2.09, "V", 3.30, period=2.867343)
CONST = vsx_line(99, "const star", 2, 47.04221, 40.95567, "CST", 9.0, "V", 9.1)


def test_wds_parse():
    r = S.wds_row(WDS_LINES[0])
    ra, dec = r[0], r[1]
    assert abs(ra - (7 + 34 / 60 + 35.86 / 3600) * 15) < 1e-9 and abs(dec - (31 + 53 / 60 + 17.8 / 3600)) < 1e-9
    assert r[2:5] == ("07346+3153", "STF1110", "AB") and r[5:8] == (1778, 2026, 1577) and r[8:10] == (303, 49)
    assert r[10:14] == (5.2, 5.7, 1.93, 2.97) and r[14] == "A1V+A4Vm" and r[15] == "NO V"
    r2 = S.wds_row(WDS_LINES[1])
    assert np.isnan(r2[13]) and r2[11] == 0.0                     # mag2 '.' unknown, separation 0.0
    assert S.wds_row("    WDS   Discovr Comp  EPOCH") is None
    assert S.wds_precise("000000.08-052939.7")[1] < 0


def test_vsx_parse():
    lines = (ZTF + "\n" + ALGOL + "\n" + CONST + "\n").encode()
    a = np.frombuffer(lines, np.uint8).reshape(-1, S.VSX_LRECL + 1)
    fast = S.vsx_block(a, 17.0)
    slow = S.vsx_lines_slow(lines.splitlines(keepends=True), 17.0)
    assert len(fast) == 2 and (fast == slow).all()                # the constant star is left out
    z, al = fast[0], fast[1]
    assert z["oid"] == 1547582 and z["type"] == b"BY" and abs(z["max"] - 16.571) < 1e-4 and z["amp"] == 1
    assert abs(z["min"] - 0.078) < 1e-4 and z["band"] == b"r" and abs(z["period"] - 1.9449979) < 1e-5
    assert abs(z["dec"] - 62.10163) < 1e-9
    assert al["type"] == b"EA/SD" and al["amp"] == 0 and abs(al["min"] - 3.30) < 1e-4
    assert len(S.vsx_block(a, 10.0)) == 1                         # the 16.6 mag ZTF star is fainter than 10


def _wds_dicts():
    return [{k: (v.strip() if isinstance(v, str) else v) for k, v in zip(S.WDS_DT.names, S.wds_row(l))}
            for l in WDS_LINES]


def test_match_roles():
    rows = _wds_dicts()[:2]
    a = (rows[0]["ra"], rows[0]["dec"])
    m = S.match_wds(rows, [a])
    assert [x[1] for x in m] == ["A", "A"] and m[0][0]["comp"] == "Aa,Ab"   # the closest pair first
    b = S.offset(a[0], a[1], 49, 5.7)                             # Castor B: at the last PA / separation
    m = S.match_wds(rows, [b])
    assert len(m) == 1 and m[0][1] == "B" and m[0][2] < 0.01
    assert "the star is the companion" in S.wds_text(m[0])
    far = S.offset(a[0], a[1], 200, 20.0)
    assert S.match_wds(rows, [far]) == []
    f = S.fields(S.match_wds(rows, [a]), [], "wds local")
    assert f["wds_sep_arcsec"] == "0.00" and '<0.1"' in f["wds"] and "1778-2026, 1577 obs." in f["wds"]


def test_positions_pm():
    rec = dict(star_ra="10.0", star_dec="0.0", star_pmra="1000", star_pmdec="-500", best_utc="2026-11-21T01:02:03")
    (ra, dec), (ra0, dec0) = S.positions(rec)
    assert abs((ra - ra0) * 3600 - 26.0) < 1e-6 and abs((dec - dec0) * 3600 + 13.0) < 1e-6
    assert len(S.positions(dict(star_ra="1", star_dec="2", best_utc="2026"))) == 1


def test_vsx_magnitude_range():
    a = np.frombuffer((ALGOL + "\n").encode(), np.uint8).reshape(-1, S.VSX_LRECL + 1)
    v = S._dicts(S.vsx_block(a, 17.0), None, "vsx")
    where = [(47.04221, 40.95567)]
    assert len(S.match_vsx(v, where, 2.5)) == 1 and len(S.match_vsx(v, where, 4.6)) == 1
    assert S.match_vsx(v, where, 6.0) == []                       # a faint star next to Algol is not Algol
    assert len(S.match_vsx(v, where, None)) == 1
    f = S.fields([], S.match_vsx(v, where, 2.5), "vsx local")
    assert f["var_type"] == "EA/SD" and f["var_amp_mag"] == "1.21" and "P 2.86734 d" in f["var"]


def test_local_copy_and_check():
    base = tempfile.mkdtemp(prefix="pysyzygos-starinfo-")
    S._save("wds", np.array([S.wds_row(l) for l in WDS_LINES], dtype=S.WDS_DT), dict(source="test"), base)
    lines = (ALGOL + "\n" + vsx_line(5, "wrap", 0, 359.99995, 1.0, "RR", 12.0, "V", 12.6) + "\n").encode()
    S._save("vsx", S.vsx_block(np.frombuffer(lines, np.uint8).reshape(-1, S.VSX_LRECL + 1), 17.0),
            dict(source="test", mag_max=17.0), base)
    assert all(s["installed"] for s in S.status(base))
    arr = np.load(S.paths("wds", base)[0])
    assert (np.diff(arr["ra"]) >= 0).all()
    recs = [dict(star_ra=113.649417, star_dec=31.888278, mag="1.9", best_utc="2026-01-01"),     # Castor A
            dict(star_ra=47.04221, star_dec=40.95567, mag="2.3", best_utc="2026-01-01"),        # Algol
            dict(star_ra=0.00003, star_dec=1.0, mag="12.2", best_utc="2026-01-01"),             # across RA 0
            dict(star_ra=200.0, star_dec=-30.0, mag="12", best_utc="2026-01-01")]
    out, note = S.check(recs, base=base, how="local", log=lambda *a: None)
    assert note == "" and "STF1110" in out[0]["wds"] and out[0]["var"] == ""
    assert "LAB   2" in out[1]["wds"] and out[1]["var_type"] == "EA/SD"
    assert out[2]["var_type"] == "RR"                             # across RA 0
    assert out[3]["wds"] == out[3]["var"] == "" and out[3]["star_info"]   # looked up, nothing known
    assert out[1]["star_info"] == "wds local+vsx local"
    assert S.check(recs, base=base, how="off") == ([], "")
    S.remove("vsx", base)
    assert not S.installed("vsx", base) and S.installed("wds", base)


ASU = """#
#Coosys\tJ2000:\teq_FK5 J2000
#RESOURCE=yCat_1
#Name: B/wds
#Table\tB_wds_wds:
#Name: B/wds/wds
#Title: The Washington Double Star Catalog (main part)
_RAJ2000\t_DEJ2000\tWDS\tDisc\tComp\tObs1\tpa1\tpa2\tsep1\tsep2\tmag1\tmag2\tNotes
deg\tdeg\t \t \t \tyr\tdeg\tdeg\tarcsec\tarcsec\tmag\tmag\t
-------\t-------\t-\t-\t-\t-\t-\t-\t-\t-\t-\t-\t-
047.0422083\t+40.9556667\t03082+4057\tLAB   2\tAa,Ab\t1973\t123\t322\t0.1\t0.10\t2.12\t4.6\tNO

#RESOURCE=yCat_2
#Name: B/vsx
#Name: B/vsx/vsx
_RAJ2000\t_DEJ2000\tOID\tName\tV\tType\tmax\tn_max\tf_min\tmin\tPeriod
deg\tdeg\t \t \t \t \tmag\t \t \tmag\td
-\t-\t-\t-\t-\t-\t-\t-\t-\t-\t-
047.0422100\t+40.9556700\t26202\tbet Per\t0\tEA/SD\t2.090\tV\t\t3.300\t2.867343
"""


def test_online_stand_in():
    t = S.parse_asu(ASU)
    assert len(t["B/wds/wds"]) == 1 and t["B/vsx/vsx"][0]["Name"] == "bet Per"
    asked = []
    def fetch(url):
        asked.append(url)
        if "fail" in str(len(asked)):
            raise OSError
        return ASU
    base = tempfile.mkdtemp(prefix="pysyzygos-starinfo-")      # nothing installed: online
    rec = dict(star_ra=47.04221, star_dec=40.95567, mag="2.2", best_utc="2026-01-01")
    out, note = S.check([rec], base=base, how="auto", fetch=fetch, log=lambda *a: None)
    assert len(asked) == 1 and "B%2Fwds%2Fwds+B%2Fvsx%2Fvsx" in asked[0]
    assert out[0]["var"].startswith("bet Per: EA/SD 2.09-3.30 V") and "LAB   2" in out[0]["wds"]
    assert out[0]["star_info"] == "wds online+vsx online"
    def down(url):
        raise OSError("down")
    out, note = S.check([rec, rec], base=base, how="online", fetch=down, log=lambda *a: None)
    assert "failed for 2 of 2" in note and out[0]["wds"] == ""
    old = S.ONLINE_MAX
    S.ONLINE_MAX = 1
    try:
        out, note = S.check([rec, rec], base=base, how="online", fetch=lambda u: ASU, log=lambda *a: None)
    finally:
        S.ONLINE_MAX = old
    assert "stopped after 1 of 2" in note and out[0]["var"] and out[1]["var"] == ""


def test_read_first_error_page():
    assert net.asu_ok(ASU) and not net.asu_ok("<!doctype html><title>Page unavailable</title>")
    assert not net.asu_ok("#\n#Coosys\tJ2000\n# Report from: stdb_pg,     Status: STDB_ERR\n")
    pages = {"http://a": "<!doctype html>unavailable", "http://b": ASU}
    class R:
        def __init__(self, t): self.t = t
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return self.t.encode()
    old = net.urlopen
    net.urlopen = lambda url, timeout=30: R(pages[url.split("?")[0]])
    try:
        assert net.read_first(["http://a", "http://b"], "q", ok=net.asu_ok) == ASU
        assert net._FIRST[("http://a", "http://b")] == 1
        net._FIRST.clear()
        assert net.read_first(["http://a", "http://b"], "q").startswith("<!doctype")   # without ok: as before
    finally:
        net.urlopen = old


def test_mode(monkey=os.environ):
    for env, want in (("off", "off"), ("1", "auto"), ("local", "local"), ("bogus", "auto")):
        monkey["PYSYZYGOS_STAR_INFO"] = env
        assert S.mode() == want, env
    del monkey["PYSYZYGOS_STAR_INFO"]


if __name__ == "__main__":
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f()
            print("ok", k)
