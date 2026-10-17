# Observing sites. Copy this file to sites.py (not in git) and enter your own sites there.
# pysyzygos_config.py uses `default_site`, or the site named in the environment variable PYSYZYGOS_SITE:
#     PYSYZYGOS_SITE=field ./pysyzygos.py
#
# Required: lat, lon (geodetic degrees, longitude east-positive, west is negative), ele (metres above mean sea level,
# as maps give it; ele_ref="ellipsoid" for a height above the WGS84 ellipsoid, e.g. from an MPC code). geoid_m (the
# geoid's height above the ellipsoid there, EGM96) is filled in by the GUI and by `pysyzygos setup --geoid`.
# Optional (defaults in pysyzygos_config.py):
#   view      min_alt (deg, lowest usable star altitude, default 10), max_sun_alt (deg, default 0; twilight events marked),
#             reach_km (km you can travel from here, default max_shadow_dist)
#   equipment for OWC's General Observability Criterion, StarMag < 5 log10(aperture_cm)
#             + 2.5 log10(MaxDuration / frames) + 8.5 + mag_adjust:
#             aperture_cm (default 25), frames (detection frames, default 4), mag_adjust (default 0; + for dark sky or
#             a sensitive camera, - for worse), extinction (mag per airmass at the star's altitude, default 0 = off,
#             ~0.2 typical), min_dur_s (hard limit, default 0.4), max_exp_s (longest usable exposure, default 0.64).
#             The faintest star searched follows (25 cm: G 15.0, 50 cm: G 16.5), or set it with mag_limit.
#   camera    focal_mm (default f/10 = 100 x aperture_cm), sensor_mm (width, height; default (5.6, 3.2)):
#             the camera field drawn in the event preview.
#   identity  mpc_code: the site's official Minor Planet Center observatory code, if it has one (e.g. "695" for
#             Kitt Peak); shown in the report header. The GUI fills it in when you pick an MPC observatory.
#   horizon   (set in the GUI, Site tab, "Horizon") horizon: [[az, alt], ...] whole degrees as OccultWatcher's
#             UserHorizon.txt, horizon_name, horizon_margin (deg, default 15: stars closer are marked), horizon_filter
#             (True: leave out events behind it); horizon_image (360-degree photo, horizons/<site>.jpg) and
#             horizon_image_az (azimuth at the photo's left edge, deg).

sites = {
    "nyc": dict(lat=40.7128, lon=-74.0060, ele=10, name="New York City Hall (example)",
                aperture_cm=25, min_alt=20),
    "field": dict(lat=41.3000, lon=-74.6000, ele=450, name="Dark-sky field (example)",
                  aperture_cm=35, min_alt=10, max_sun_alt=-12, reach_km=50),
}

default_site = "nyc"
