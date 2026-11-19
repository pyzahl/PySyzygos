"""OccultWatcher Cloud lookup (pysyzygos.owc): matching by Gaia star id or time, the cache, the table label.
No network: owc._get is replaced by a stand-in that answers like the OWC interface."""
import _testtmp  # noqa: F401  (temporary files of this run in one folder, removed at exit)
import sys, os, tempfile, json
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
from pysyzygos import owc

EVENTS = [dict(id="A-1", time="2026-Oct-09, 18:55:32", astNo=30819, star="UCAC4 466-002898", tags=None),
          dict(id="B-2", time="2026-Oct-11, 22:51:08", astNo=30819, star="TYC 0041-00123-1",
               tags=[dict(name="IBEROC")])]
DETAILS = {"A-1": dict(id="A-1", time="18:55 UT", gaia=dict(id="111"), tags=[], stations=[]),
           "B-2": dict(id="B-2", time="22:51 UT", gaia=dict(id="2514569868519950720"), tags=[dict(name="IBEROC")],
                       stations=[dict(obs="Observer One", dist=-38.6, cmtmt="Medium", report=None),
                                 dict(obs="Observer Two", dist=2.6, cmtmt="High", report={"x": 1})])}
calls = []
def fake_get(url, timeout=20):
    calls.append(url)
    if "/events/?" in url:
        assert "astNo=30819" in url and "dt=2026-10-11" in url and "bf=1" in url, url
        return EVENTS
    return DETAILS[url.rsplit("/", 1)[1]]
owc._get = fake_get

rec = dict(target_id="30819", best_utc="2026-10-11T22:47:45.120", star="2514569868519950720")
ev = owc.lookup(rec)
assert ev["id"] == "B-2" and ev["match"] == "star" and ev["tags"] == ["IBEROC"] and len(ev["stations"]) == 2
assert ev["url"].endswith("/event/B-2") and ev["stations"][1]["report"] is True
# another star at the same time: only a time match (within 10 min)
ev2 = owc.lookup(dict(rec, star="999"))
assert ev2["match"] == "time" and ev2["id"] == "B-2"
# far in time and another star: not on OWC
assert owc.lookup(dict(rec, best_utc="2026-10-11T03:00:00", star="999")) is None

# cache and label
d = tempfile.mkdtemp()
found, n, errors = owc.check([rec, dict(rec, best_utc="2026-10-11T03:00:00", star="999")], d)
assert (found, n, errors) == (1, 2, [])
cache = json.load(open(os.path.join(d, owc.CACHE)))
assert cache["30819_2026-10-11T22:47"]["event"]["id"] == "B-2" and cache["30819_2026-10-11T03:00"]["event"] is None
label, tip, url = owc.info("30819", "2026-10-11T22:47:45.120", owc.load(d))
assert label == "OWC IBEROC · 2 stations" and "Observer Two: +2.6 km from the centre line, commitment High, reported" in tip
assert owc.info("30819", "2026-10-11T03:00:00", owc.load(d)) is None and owc.info("1", "2026-01-01T00:00", {}) is None
# a failing request is reported, the rest goes on
def broken(url, timeout=20):
    raise OSError("offline")
owc._get = broken
assert owc.check([rec], d)[2] and owc.load(d)["30819_2026-10-11T22:47"]["event"]["id"] == "B-2"   # cache kept
print("OWC TESTS PASSED")
