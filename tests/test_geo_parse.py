"""Site coordinates pasted as text (pysyzygos.geo.parse_coords): labels in any order, DMS / decimal minutes / decimal
degrees, N/S/E/W or signs, heights in m/ft/km, and where a single value was pasted. No network."""
import _testtmp  # noqa: F401  (temporary files of this run in one folder, removed at exit)
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
from pysyzygos.geo import parse_coords as P

LAT, LON = 37 + 1 / 60 + 27 / 3600, -(121 + 57 / 60 + 19 / 3600)


def near(c, lat=None, lon=None, ele=None):
    for k, v in (("lat", lat), ("lon", lon), ("ele", ele)):
        if v is None:
            assert c[k] is None, (k, c)
        else:
            assert c[k] is not None and abs(c[k] - v) < 1e-4, (k, c)


near(P('Lng: -121° 57\' 19", Lat: +37° 01\' 27", Alt: 132 m'), LAT, LON, 132)
near(P("37°01'27\"N 121°57'19\"W"), LAT, LON)
near(P("37°01′27″N 121°57′19″W"), LAT, LON)                          # typographic primes
near(P("N 37 01 27 W 121 57 19"), LAT, LON)
near(P("37:01:27 -121:57:19 132m"), LAT, LON, 132)
near(P("37.0242° N, 121.9553° W"), 37.0242, -121.9553)
near(P("37.02417, -121.95528"), 37.02417, -121.95528)                # Google Maps: latitude first
near(P("-121.95528, 37.02417"), 37.02417, -121.95528)                # longitude first: swapped by range
near(P("37.0242 -121.9553 132"), 37.0242, -121.9553, 132)
near(P("N 37 01.45 W 121 57.32"), 37 + 1.45 / 60, -(121 + 57.32 / 60))   # decimal minutes
near(P("Latitude: 37.0242 Longitude: -121.9553 Elevation: 433 ft"), 37.0242, -121.9553, 433 * 0.3048)
near(P("lat=46.83 lon=9.59 h=1200"), 46.83, 9.59, 1200)
near(P("Höhe: 958 m, Breite 46.83, Länge 9.59"), 46.83, 9.59, 958)
near(P("34° 54' 30\" S, 138° 36' 0\" E"), -(34 + 54.5 / 60), 138.6)  # southern / eastern hemisphere
near(P("40.8, 287.1"), 40.8, 287.1 - 360)                            # longitude 0..360 -> -180..180
near(P("121° 57' 19\" W"), None, LON)                                # hemisphere decides the field
near(P("46.83", field="lat"), 46.83)
near(P("9.59", field="lon"), None, 9.59)
near(P("95, 10"), 10, 95)                                            # only valid as longitude, latitude
for bad in ("hello", "", "95, 100", "37 75 10, 121 0 0"):
    try:
        P(bad)
        raise AssertionError(f"{bad!r} must be refused")
    except ValueError:
        pass
print("GEO PARSE TESTS PASSED")
