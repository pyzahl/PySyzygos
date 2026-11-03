"""obsreport.py: observation reports prefilled from a favorite and an Occult archive event, imported from a PyStarLight
analysis (<movie>.event.json) and an IOTA-ES report form, written as IOTA-ES text (read back the same), found on disk
(links not followed), saved and listed. Temporary folders; no network, no SPICE, no GUI."""
import json, os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
from pysyzygos import obsreport as R

tmp = tempfile.mkdtemp()

# a favorite: event, predicted D/R at the site (chord of a straight shadow edge), site and its equipment, prediction
fav = dict(key="3200_20261102T0109", status="observed", note="NEGATIVE: no event seen", version="1.5.1",
           record=dict(target_id="3200", target_name="3200 Phaethon (1983 TB)", best_utc="2026-11-02T01:09:10.379",
                       star="1963716673315870848", star_ucac4="634-113397", r_km="3.125", ground_dist_km="0.87",
                       max_duration_s="0.4", mag="11.196", m_ast="17.6", mag_drop="4.43", p_site="0.944",
                       star_alt="73.2", star_az="232.6", moon_illum_pct="5", moon_sep_deg="120"),
           site=dict(name="Home", lat=40.9552, lon=-72.92787, ele=61), phys=dict(orbit=["JPL#1029 of 2026-10-28", "x"]))
f = R.from_favorite(fav, sites={"home": dict(name="Home", aperture_cm=28)})
assert (f["asteroid_number"], f["asteroid_name"], f["star"], f["gaia_id"]) == \
    ("3200", "Phaethon", "UCAC4 634-113397", "1963716673315870848"), f
assert f["date"] == "2026-11-02" and f["predict_time"] == "01:09:10.4" and f["outcome"] == "NEGATIVE"
chord = 0.4 * (1 - (0.87 / 3.125) ** 2) ** 0.5                               # 0.384 s
assert f["pred_duration"] == round(chord, 2) and f["pred_d"] == "01:09:10.2" and f["pred_r"] == "01:09:10.6", f
assert f["station"] == "Home" and f["aperture_cm"] == 28 and f["path_width_km"] == 6.25 and f["probability"] == 94.4
assert f["feed"] == "PySyzygos 1.5.1, orbit JPL#1029 of 2026-10-28" and f["moon"] == "5 % lit, 120 deg away"
assert set(f) == set(R.KEYS)
assert R.from_favorite(dict(record=dict(target_id="2026 ED138", target_name="(2026 ED138)",
                                        best_utc="2026-11-26T06:41:23")))["asteroid_name"] == "2026 ED138"

# an archive event and one of its observers: station and D/R from the contacts
rec = dict(target_id="3200", target_name="3200 Phaethon", best_utc="2025-11-21T09:02:35.936", star="342304980777309184",
           star_catalog="UCAC4 632-006130", mag=12.45, r_km=2.5, m_ast=17.69, prediction="JPL#962+Ephem",
           obs_sites=[dict(observer="D Dunham", place="Marfa, TX", lon=-104.2313, lat=29.9627, alt_m=1486.0, datum="_",
                           method="a", result="positive")])
cts = [("D", "2025-11-21T09:02:35.84", dict(observer="D Dunham", code="D", acc_s=0.016, pe_s=None)),
       ("R", "2025-11-21T09:02:36.00", dict(observer="D Dunham", code="R", acc_s=0.016, pe_s=None))]
a = R.from_archive(rec, cts, "D Dunham")
assert a["star"] == "UCAC4 632-006130" and a["observer1"] == "D Dunham" and a["outcome"] == "POSITIVE"
assert (a["d_code"], a["d_time"], a["d_acc"], a["r_time"]) == ("D", "09:02:35.840", 0.016, "09:02:36.000"), a
assert a["duration"] == 0.16 and a["datum"] == "" and a["method"] == "a"
assert R.from_archive(rec)["observer1"] == ""

# a PyStarLight analysis: the first D/R pair, its errors, SNR from the step and the first level's scatter
psl = dict(software="PyStarLight 0.1.0", created_utc="2026-11-01T17:28:03Z", object="(709) Fringilla occ. UCAC4 644-038283",
           target=dict(name="UCAC4 644-038283", ids={"Gaia DR3": "Gaia DR3 944967984227916160", "UCAC4": "UCAC4 644-038283"}),
           recording=dict(date="2025-01-16", first_utc="17:54:35.006", last_utc="17:55:34.847",
                          metadata=dict(OBSERVER="An Observer", LATITUDE="46.9924869", LONGITUDE="9.6401519",
                                        ALTITUDE="972.8", INSTRUMENT="DVTI+CAM #43", TELESCOPE="C-14")),
           step_fit=dict(frame_interval_s=0.075, levels=[dict(flux=0.1768, flux_scatter=0.0172)],
                         transitions=[dict(sigma_s=0.0252, flux_before=0.1768, flux_after=0.1159),
                                      dict(sigma_s=0.03), dict(sigma_s=0.027), dict(sigma_s=0.034)],
                         events=[dict(D=0, R=3, D_utc="2025-01-16T17:54:59.7261Z", R_utc="2025-01-16T17:55:09.8235Z",
                                      duration_s=10.0973),
                                 dict(D=1, R=2, D_utc="2025-01-16T17:55:03.3520Z", R_utc="2025-01-16T17:55:06.1230Z")]))
d = os.path.join(tmp, "PyStarLight", "rec")
os.makedirs(d)
pp = os.path.join(d, "movie.event.json")
json.dump(psl, open(pp, "w"))
g, note, origin = R.from_pystarlight(pp)
assert (g["asteroid_number"], g["asteroid_name"], g["star"], g["gaia_id"]) == \
    ("709", "Fringilla", "UCAC4 644-038283", "944967984227916160"), g
assert (g["d_time"], g["d_acc"], g["r_time"], g["r_acc"], g["duration"]) == \
    ("17:54:59.726", 0.025, "17:55:09.823", 0.034, 10.097), g
assert g["snr"] == 3.5 and g["exp_time"] == 0.075 and g["observer1"] == "An Observer" and g["alt_m"] == 972.8
assert g["extra_events"] == "D 17:55:03.352 0.03\nR 17:55:06.123 0.027" and "1 more event" in note, g
# where each value came from: the recording (camera, GPS) or the analysis
assert origin["lat"] == origin["camera"] == origin["start_obs"] == origin["observer1"] == "recording"
assert origin["d_time"] == origin["star"] == origin["snr"] == "analysis" and set(origin) == set(g)
assert R.software_of(pp) == "PyStarLight 0.1.0" and R.software_of("/nonexistent") == ""
# all the camera tool's keys (docs/observation_interface.md), as far as the recording has them
cam = dict(psl, recording=dict(psl["recording"], metadata={
    "OBSERVER": "A", "observer-2": "B", "STATION": "Deck", "TELESCOPE": "C-14", "TELESCOPE-TYPE": "SCT",
    "APERTURE-CM": "35.6", "FOCAL-LENGTH-CM": "155.6", "FOCAL-REDUCER": "0.4x", "MOUNT": "GM2000",
    "TIME-SOURCE": "GPS (PPS)", "OBSERVING-METHOD": "a", "EXPOSURE-S": "0.07", "CAMERA-DELAY-S": "0.002",
    "CAMERA-MODEL": "IMX178 cam", "CAMERA-SERIAL-NO": "7", "CAMERA-SENSOR-INFO": "Sony IMX178",
    "LATITUDE": "40.1", "LONGITUDE": "-73.2", "ALTITUDE": "61.4", "DATUM": "*"}))
json.dump(cam, open(os.path.join(d, "cam.event.json"), "w"))
c, _, oc = R.from_pystarlight(os.path.join(d, "cam.event.json"))
assert (c["observer2"], c["station"], c["telescope"], c["aperture_cm"], c["focal_cm"], c["reducer"], c["mount"]) == \
    ("B", "Deck", "3", 35.6, 155.6, "0.4x", "GM2000"), c
assert (c["time_source"], c["method"], c["exp_time"], c["pe_s"], c["datum"]) == ("a", "a", 0.07, 0.002, "*"), c
assert c["camera"] == "IMX178 cam, serial 7; Sony IMX178" and oc["reducer"] == oc["time_source"] == "recording"
os.remove(os.path.join(d, "cam.event.json"))
# PyStarLight's capture (RAVF): exposure in ns, serial and sensor, the time stamps' source
for src_text, code in (("GPS trigger pulse, GPS UTC", "a"), ("GPS trigger pulse, Pi clock (NTP)", "b"),
                       ("Pi clock (NTP)", "b")):
    rv = dict(psl, recording=dict(psl["recording"], metadata={
        "INSTRUMENT": "VEYE MV-MIPI-IMX178M", "INSTRUMENT-SERIAL": "1234", "INSTRUMENT-SENSOR": "IMX178M",
        "INSTRUMENT-SHUTTER": "70000000", "TIMESTAMP-SOURCE": src_text}))
    json.dump(rv, open(os.path.join(d, "rv.event.json"), "w"))
    c, _, oc = R.from_pystarlight(os.path.join(d, "rv.event.json"))
    assert c["time_source"] == code and c["exp_time"] == 0.07 and oc["exp_time"] == "recording", (src_text, c)
    assert c["camera"] == "VEYE MV-MIPI-IMX178M, serial 1234; IMX178M", c
os.remove(os.path.join(d, "rv.event.json"))
# recording.station: the same data from any format (RAVF, ADV, SER), normalized by PyStarLight; wins over raw keys
st = dict(format="SER", site=dict(lat=40.95520123, lon=-72.92787456, alt_m=61.43, datum="", source="GPS"),
          station="Deck", observers=["A", "B", "C", "D"],
          equipment=dict(telescope="C-14", telescope_type="SCT", aperture_cm=35.6, focal_length_cm=62.2,
                         focal_reducer="0.4x", mount="GM2000", camera="QHY174", serial="9", sensor="IMX174",
                         method="a"),
          timing=dict(source="GPS", exposure_s=0.04, camera_delay_s=0.0012))
nj = dict(psl, recording=dict(psl["recording"], station=st))
json.dump(nj, open(os.path.join(d, "st.event.json"), "w"))
c, _, oc = R.from_pystarlight(os.path.join(d, "st.event.json"))
assert (c["lat"], c["lon"], c["alt_m"], c["station"]) == (40.955201, -72.927875, 61.4, "Deck"), c
assert (c["observer1"], c["observer2"], c["more_obs"]) == ("A", "B", "C, D"), c
assert (c["telescope"], c["focal_cm"], c["reducer"], c["method"], c["time_source"]) == ("3", 62.2, "0.4x", "a", "a")
assert c["camera"] == "QHY174, 9, IMX174" and c["exp_time"] == 0.04 and c["pe_s"] == 0.0012, c
assert all(oc[k] == "recording" for k in ("lat", "observer2", "camera", "exp_time", "pe_s"))
os.remove(os.path.join(d, "st.event.json"))
# found by date and asteroid, not through a link (e.g. to the recordings on an external drive)
other = os.path.join(tmp, "elsewhere")
os.makedirs(other)
json.dump(dict(psl, object="(709) Fringilla occ. X"), open(os.path.join(other, "b.event.json"), "w"))
os.symlink(other, os.path.join(tmp, "PyStarLight", "link"))
found = R.find_pystarlight([os.path.join(tmp, "PyStarLight")], "2025-01-16", "709")
assert [p for p, _, _ in found] == [pp], found
assert R.find_pystarlight([os.path.join(tmp, "PyStarLight")], "2025-03-01", "709") == []
assert R.find_pystarlight([os.path.join(tmp, "PyStarLight")], None, None, "fringilla")

# IOTA-ES report form: written and read back to the same fields
full = {**R.blank(), **f, **{k: str(v) for k, v in g.items()          # the favorite's event, the analysis' times
                              if k not in ("asteroid_number", "asteroid_name", "star", "gaia_id", "date", "outcome")}}
full.update(observer1="An Observer", method="a", time_source="a", telescope="3", transparency="1", stability="2",
            comments="no\nproblems", datum="")
txt = R.to_iotaes(full, origin=origin, sources=["PyStarLight 0.1.0"])
assert txt.splitlines()[0] == f"#{R.FORM} - PySyzygos {R.__version__}; data from PyStarLight 0.1.0"
assert "#DataFrom: analysis: outcome, star, gaia_id, d_code, d_time" in txt and "#GaiaDR3: " in txt
assert "; recording: asteroid_number, asteroid_name, date, observer1, lat, lon, alt_m" in txt
plain = R.to_iotaes(full, extras=False)
assert "#GaiaDR3" not in plain and "#DataFrom" not in plain and "#MoreEvents" not in plain and "#Moon:" in plain
assert R.header() == f"#{R.FORM} - PySyzygos {R.__version__}"
assert txt.startswith("#" + R.FORM) and "#D: D17:54:59.726" in txt and "#Latitude: +46 59 32.953" in txt
assert "#Longitude: +009 38 24.547" in txt and "#Comments: no problems" in txt
back = R.from_iotaes(txt)
for k in R.KEYS:
    want, got = str(full.get(k, "")), str(back.get(k, ""))
    if k in ("lat", "lon"):
        assert abs(float(got) - float(want)) < 1e-5, (k, want, got)
    elif k == "comments":
        assert got == "no problems"
    elif k in ("pred_d", "pred_r"):                                            # not in the form
        continue
    elif k == "predict_time":                                                  # the form: whole seconds
        assert got == want[:8], (want, got)
    else:
        assert got == want, (k, want, got)
dv = R.from_iotaes("#DATE: 16 Jan 2025, 17:55:04\n#PREDICTTIME: 16 Jan 2025, 17:55:04\n#D: D17:54:59.752\n"
                   "#Latitude:  +46 59 33.000\n#Longitude: -009 38 24.299\n#MpcObsCode: -\n#Notes:\tSWD\n")
assert dv == dict(date="2025-01-16", predict_time="17:55:04", d_code="D", d_time="17:54:59.752", lat=46.9925,
                  lon=-9.6400831, mpc_code="", station_note="SWD"), dv
assert R._dms(-0.5, 2) == "-00 30 00.000" and R._dms(9.99999999, 3) == "+010 00 00.000"

# saved per event and station; listed; what is still missing
obs = os.path.join(tmp, "observations")
p = R.save(full, obs, dict(kind="favorite", key=fav["key"]), [dict(kind="pystarlight", note=note)], origin)
assert p == os.path.join(obs, R.event_key(full), "Home.json") and R.event_key(full) == "3200_20261102T0109", p
r = R.load(p)
assert r["fields"]["d_time"] == "17:54:59.726" and r["source"]["key"] == fav["key"] and len(r["imports"]) == 1
p2 = R.save(dict(full, comments="edited"), obs)
assert p2 == p and R.load(p)["created"] == r["created"] and R.load(p)["source"] == r["source"]
assert R.load(p)["origin"]["lat"] == "recording"
assert [s["station"] for s in R.saved(obs)] == ["Home"] and R.saved(obs)[0]["outcome"] == "NEGATIVE"
assert R.missing(full) == []
m = R.missing(dict(full, outcome="POSITIVE", d_time="", time_source=""))
assert m == ["Time source", "D time (UT)"], m
assert R.seconds_of_day("D17:54:59.752") == 64499.752 and R.seconds_of_day("x") is None
# inbox: analyses sent by PyStarLight; matched to the favorite of the same asteroid and night
q = R.store_analysis(psl, obs)
assert os.path.dirname(q) == R.inbox_dir(obs) and q.endswith("_movie.event.json") is False and q.endswith(".event.json")
assert [x["object"] for x in R.inbox(obs)] == [psl["object"]] and R.inbox(obs)[0]["software"] == "PyStarLight 0.1.0"
for bad in ([], {"x": 1}, "text"):
    try:
        R.store_analysis(bad, obs)
        raise AssertionError("refused")
    except ValueError:
        pass
e709 = dict(key="709_20250116T1755", record=dict(target_id="709", target_name="709 Fringilla",
                                                 best_utc="2025-01-16T17:55:04"))
assert R.matching(g, [fav, e709]) == [e709] and R.matching(dict(g, date="2025-02-01"), [e709]) == []
assert R.matching(dict(asteroid_name="2026 ED138", date="2026-11-26"),
                  [dict(record=dict(target_id="2026 ED138", target_name="(2026 ED138)", best_utc="2026-11-26T06:41"))])
# the connection file for PyStarLight: key made once and kept, readable by the user only, checked in constant time
cf = os.path.join(tmp, "cfg", "observation_api.json")
c1 = R.api_setup("http://127.0.0.1:8088", os.path.join(obs, "inbox"), tmp, path=cf)
assert c1["token"].startswith("pyobs_") and len(c1["token"]) > 40 and c1["send"].endswith("/api/obs/v1/analysis")
assert oct(os.stat(cf).st_mode & 0o777) == "0o600"
c2 = R.api_setup("http://127.0.0.1:8099", os.path.join(obs, "inbox"), tmp, path=cf)
assert c2["token"] == c1["token"] and c2["url"] == "http://127.0.0.1:8099"
assert R.api_key_ok("Bearer " + c1["token"], cf) and R.api_key_ok("bearer  " + c1["token"], cf)
assert not R.api_key_ok("Bearer wrong", cf) and not R.api_key_ok("", cf) and not R.api_key_ok(None, cf)
assert not R.api_key_ok("Bearer " + c1["token"], os.path.join(tmp, "none.json"))
print("OBSREPORT TESTS PASSED")
