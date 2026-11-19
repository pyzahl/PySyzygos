import _testtmp  # noqa: F401  (temporary files of this run in one folder, removed at exit)
import numpy as np
from astropy.time import Time

d = np.load("maps/27847_20261029T0746_path.npz")

print(list(d["columns"]))                       # ['et', 'lon_deg', 'lat_deg', 'dur_s']
print('Target:', str(d["target_name"]), ' Star:', int(d["star"]), ' best @ UTC: ', str(d["best_utc"]), str(d["ellipsoid"]))

c = d["center"]                                 # rows: et, lon, lat, dur
utc = (Time("J2000", scale="tdb") + c[:, 0] / 86400.0).utc.isot   # ET (TDB s since J2000.0) -> UTC strings
for t, lon, lat, dur in zip(utc, c[:, 1], c[:, 2], c[:, 3]):
    print(f"{t}  lon {lon:10.5f}  lat {lat:9.5f}  dur {dur:.2f} s")
    
