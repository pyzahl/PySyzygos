"""Close and double stars (pysyzygos.doubles): neighbours at the event date, the blended drop, Gaia's hints, the online
query and the hit-log update. No network: the archive answer is a stand-in DataFrame."""
import sys, os, csv, tempfile, math
import numpy as np, pandas as pd
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
from pysyzygos import doubles as D

# drop: equal star and companion, faint asteroid -> at most 0.75 mag; no companion -> the star's own drop
assert abs(D.blended_drop(10.0, 30.0, [10.0]) - 2.5 * math.log10(2)) < 1e-3
own = 2.5 * math.log10(1 + 10 ** (0.4 * (14.0 - 10.0)))
assert abs(D.blended_drop(10.0, 14.0, []) - own) < 1e-9
assert D.blended_drop(10.0, 14.0, [12.0]) < own                         # the companion's light stays
assert D.blended_drop(10.0, None, [11.0]) > 0

# neighbours: within the radius at the event date (proper motion), not the star itself, not too faint
ra0, de0 = 100.0, 20.0
stars = pd.DataFrame(dict(source_id=[1, 2, 3, 4, 5],
                          ra=[ra0, ra0 + 1.5 / 3600 / math.cos(math.radians(de0)), ra0, ra0, ra0],
                          dec=[de0, de0, de0 + 10 / 3600, de0 - 2.0 / 3600, de0 + 0.5 / 3600],
                          pmra=[0, 0, 0, 0, 0], pmdec=[0, 0, 0, 200.0, 0],          # #4 moves 2 arcsec in 10 yr
                          phot_g_mean_mag=[10.0, 11.0, 9.0, 12.0, 16.0]))
c4 = D.companions(stars, 1, ra0, de0, 10.0, 0.0, 4.0)                    # at the Gaia epoch
assert [x[2] for x in c4] == [2, 4] and abs(c4[0][0] - 1.5) < 0.01 and abs(c4[1][0] - 2.0) < 0.01, c4
# #3 is 10 arcsec away, #5 is 6 mag fainter than the star: both ignored
c10 = D.companions(stars, 1, ra0, de0, 10.0, 10.0, 4.0)                  # 10 years later: #4 moved 2" north
assert [x[2] for x in c10] == [4, 2] and c10[0][0] < 0.01, c10
f = D.fields(c4, 10.0, 15.0)
assert f["blend_n"] == 2 and f["blend_sep_arcsec"] == 1.5 and f["blend_g"] == 11.0 and f["double_check"] == "local"
assert "companion G 11.0 at 1.5″ (+1 more)" in f["double_hint"] and f["mag_drop_blended"] < 2.5 * math.log10(1 + 10 ** 2)
faint = D.fields([(2.0, 15.0, 9)], 10.0, 12.0)                           # changes the drop by < 0.1 mag
assert faint["blend_n"] == 1 and faint["double_hint"] == "", faint
none = D.fields([], 10.0, 15.0)
assert none["double_hint"] == "" and none["blend_n"] == 0 and np.isnan(none["mag_drop_blended"])

# online: one query for all events; Gaia's flags of the star and neighbours the local catalog leaves out
q = D.query_text([(ra0, de0), (200.0, -5.0)], 4.0)
assert q.count("CIRCLE") == 2 and " OR " in q and "gaiadr3.gaia_source" in q and "ipd_frac_multi_peak" in q
archive = stars.assign(ruwe=[1.1, 2.5, 1.0, 1.0, 1.0], non_single_star=[1, 0, 0, 0, 0],
                       ipd_frac_multi_peak=[12, 0, 0, 0, 0], duplicated_source=[False] * 5)
rec = dict(target_id="5", best_utc="2026-10-08T22:10:05.939", best_et=0.0, star=1, star_ra=ra0, star_dec=de0,
           mag=10.0, m_ast=15.0)
on = D.online_fields([rec], 4.0, archive)[0]
assert on["double_check"] == "gaia online" and on["gaia_nss"] == 1 and on["gaia_multi_peak"] == 12
assert "non-single star" in on["double_hint"] and "two peaks in 12 %" in on["double_hint"], on["double_hint"]

# the VizieR check (stand-in answers in VizieR's tab-separated layout: # lines, header, units, dashes, rows)
WDS_TSV = ("#\n#comment\nWDS\tDisc\tComp\tObs1\tObs2\tNobs\tpa2\tsep2\tmag1\tmag2\tSpType\tNotes\t_r\n"
           " \t \t \tyr\tyr\t \tdeg\tarcsec\tmag\tmag\t \t \tarcsec\n"
           "--\t--\t--\t--\t--\t--\t--\t--\t--\t--\t--\t--\t--\n"
           "06275+2432\tAG  112\tAB\t1902\t2023\t24\t208\t2.80\t9.830\t9.88\t\tNO\t3.1\n")
GAIA_TSV = ("RUWE\tIPDfmp\tIPDgofha\tepsi\tsepsi\tE(BP/RP)\tDup\tNSS\n \t%\t \tmas\t \t \t \t \n"
            "--\t--\t--\t--\t--\t--\t--\t--\n\t41\t0.316\t19.754\t318500\t1.245\t0\t0\n")
urls = []
fetch = lambda url: (urls.append(url), WDS_TSV if "B%2Fwds" in url else GAIA_TSV)[1]
v = D.vizier_check(3383655504436521856, 96.874689, 24.532785, fetch=fetch)
assert len(urls) == 2 and "Source=3383655504436521856" in urls[1] and "-c.rs=30" in urls[0]
assert v["wds"][0]["Disc"] == "AG  112" and v["wds"][0]["sep2"] == "2.80" and v["gaia"]["IPDfmp"] == "41"
h = " | ".join(v["hints"])
assert "two peaks in 41 %" in h and "elongated image" in h and "excess noise" in h and "orbit is known (ORB6)" in h, h
assert "RUWE" not in h                                            # empty RUWE (2-parameter star): no reading
txt = "\n".join(D.vizier_text(v))
assert "WDS 06275+2432 AG  112 AB: 2.80\" at 208" in txt and "Gaia DR3:" in txt, txt
assert D.vizier_text(None) == []

print("DOUBLE STAR TESTS PASSED")
