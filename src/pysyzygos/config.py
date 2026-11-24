"""config.py - the run configuration, as attributes of this module (`from pysyzygos import config`; config.LAT, ...).

Your settings are in pysyzygos_config.py in the data folder (pysyzygos.home.HOME), next to sites.py. It is created from
templates/pysyzygos_config.py when missing. The template runs first, then your file, so a setting your (older) file
does not have yet keeps the template's default. Tools may override attributes for one run (pysyzygos/runner.py, GUI);
the file is not changed.
"""
import os, runpy, shutil, sys
from pysyzygos.home import HOME, PKG, legacy_files

TEMPLATE = os.path.join(PKG, "templates", "pysyzygos_config.py")
USER = os.path.join(HOME, "pysyzygos_config.py")

if HOME not in sys.path:
    sys.path.insert(0, HOME)                                      # sites.py, targets.py
if os.path.join(PKG, "templates") not in sys.path:
    sys.path.append(os.path.join(PKG, "templates"))               # sites_example (fallback of older config files)
for _m in legacy_files(HOME):                                      # files of a version before 1.0.0 (PyOccult)
    print(f"renamed {_m} (PyOccult is now PySyzygos)", file=sys.stderr)
if not os.path.isfile(USER):
    shutil.copyfile(TEMPLATE, USER)
    print(f"created {USER} from the template (your run settings; edit it as you like)", file=sys.stderr)

_ns = runpy.run_path(TEMPLATE)
_ns.update(runpy.run_path(USER))
# heights: sites.py's ele is above mean sea level; the geometry needs the WGS84 ellipsoid (+ geoid_m, filled in when the
# site is saved). Done here, after both files: older user files set ELE = site["ele"] themselves; a different ELE
# chosen in the user file is kept.
_site = _ns.get("site") if isinstance(_ns.get("site"), dict) else {}
if "ele" in _site and _ns.get("ELE") == _site["ele"]:
    _ns["ELE_MSL"], _ns["GEOID_M"] = _site["ele"], float(_site.get("geoid_m", 0.0) or 0.0)
    _ns["ELE"] = _ns["ELE_MSL"] + _ns["GEOID_M"]
# the site's horizon replaces min_alt (horizon_limit): the flat limit becomes the horizon's lowest point (never below
# 0: the screens' altitude floor), so the pick's and search's early gates stay loose; the final test is the horizon
# line at the star's azimuth (screen.screen, search.handle_star). MIN_STAR_ALT_SITE keeps the site's min_alt. Here,
# after both files: older user files set MIN_STAR_ALT = site.get("min_alt") themselves.
_ns["HORIZON"] = [(float(a), float(h)) for a, h in (_site.get("horizon") or [])]
_ns["MIN_STAR_ALT_SITE"] = _ns.get("MIN_STAR_ALT")
_ns["HORIZON_MARGIN"] = float(15.0 if _site.get("horizon_margin") is None else _site["horizon_margin"])
if _ns["HORIZON"] and _ns.get("horizon_limit", True):                 # a negative margin lowers the line (horizon.limit)
    _ns["MIN_STAR_ALT"] = max(0.0, min(h for _, h in _ns["HORIZON"]) - max(0.0, -_ns["HORIZON_MARGIN"]))
globals().update({k: v for k, v in _ns.items() if not k.startswith("__")})
del _ns, _site
