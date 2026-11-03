# Observation data: from the recording to the report

How an observation gets from the camera to a report in PySyzygos' observation GUI (`pysyzygos gui-observation`),
and what each program has to provide. Draft of 2026-11-02 (PySyzygos 1.5.2, PyStarLight 0.1.0): the names marked
*proposed* do not exist yet and are open for change.

The rule: what describes the observation itself (where, when, with what, by whom) comes from the **recording**,
written by the camera tool at the time of recording, and is passed on unchanged. The report marks every field with
its origin: *the recording*, *the analysis*, *the prediction*, or *edited by hand*. A value from the recording that
is changed by hand stays marked as edited, with the recording's value next to it.

```
camera tool (capture)  ->  video + metadata  ->  PyStarLight (analysis)  ->  <movie>.event.json
      -> observation GUI (push over the network, or file)  ->  report  ->  IOTA-ES report form (.txt)
```

## 1. The recording's metadata (camera tool)

Written into the video file's metadata (ADV/AAV/RAVF/SER sidecar, FITS headers), copied by PyStarLight into
`event.json` -> `recording.metadata` as they are. Keys are upper case; the observation GUI reads them without regard to
case.

| Key | Report field | Status | Notes |
|---|---|---|---|
| `LATITUDE`, `LONGITUDE` | Latitude, Longitude | in use | decimal degrees, + north / + east, **from the GPS at the time of recording**. RAVF stores them as float32 (~0.5 m); *proposed*: also `LATITUDE-TEXT` / `LONGITUDE-TEXT` with 7 decimals |
| `ALTITUDE` | Altitude (m) | in use | from the GPS. Above the ellipsoid or above sea level (NMEA GGA gives MSL plus the geoid separation)? Say which: see `DATUM` / *proposed* `ALTITUDE-REF` |
| `DATUM` | Datum | *proposed* | `` (blank) = WGS84 (GPS), `N`, `E`, `T`, `G`, `*` as in the form |
| `ALTITUDE-REF` | (note) | *proposed* | `MSL` or `ellipsoid` |
| `OBSERVER` | Observer 1 | in use | the person responsible for this station |
| `OBSERVER-2`, `OBSERVERS-MORE` | Observer 2, more observers | *proposed* | further operators of this station |
| `STATION` | Station | *proposed* | station name, e.g. "Sternwarte Seewis Dorf (SWD)" |
| `TELESCOPE` | Telescope (description) | in use | e.g. "C-14 EHD" |
| `TELESCOPE-TYPE` | Telescope type | *proposed* | the form's code (1-8) or its name: Refractor, Newtonian, SCT, ... |
| `APERTURE-CM` | Aperture (cm) | *proposed* | |
| `FOCAL-LENGTH-CM` | Focal length (cm) | *proposed* | **effective**, with the reducer / Barlow |
| `FOCAL-REDUCER` | Focal reducer / Barlow | *proposed* | e.g. "0.4x" (today written into `TELESCOPE`: "C-14 EHD + 0.4x Red.") |
| `MOUNT` | Mount | *proposed* | |
| `INSTRUMENT` or `CAMERA-MODEL` | Camera | in use | |
| `INSTRUMENT-SERIAL`, `INSTRUMENT-SENSOR` (RAVF); `CAMERA-SERIAL-NO`, `CAMERA-SENSOR-INFO` (ADV) | Camera (appended) | in use | |
| `BINNING-X`, `BINNING-Y`, gain | (not in the form) | in use | kept with the recording |
| `TIMESTAMP-SOURCE` (RAVF) | Time source | in use | "GPS trigger pulse, GPS UTC" -> a (GPS); "..., Pi clock (NTP)" or "Pi clock (NTP)" -> b (NTP) |
| `TIME-SOURCE` | Time source | *proposed* | the form's code a-g or a word; wins over `TIMESTAMP-SOURCE` |
| `INSTRUMENT-SHUTTER` (RAVF, ns) | Exposure (s) | in use | the true exposure; without it the analysis' frame interval is used |
| `EXPOSURE-S` | Exposure (s) | *proposed* | for formats without `INSTRUMENT-SHUTTER` |
| `FRAME-TIMING-ACCURACY` (ns), `TRIGGER-DELAY-NS` (RAVF) | (accuracy, camera delay) | in use, not read yet | to be used for the D/R accuracy and the camera delay once their meaning for the report is settled |
| `GPS-FIX`, `GPS-SATELLITES`, `GPS-HDOP`, `GPS-POSITION-UTC` | (checks) | *proposed* | the fix the position came from; no position is written without a fix |
| `GEOID-SEPARATION-M` | (altitude above the ellipsoid) | *proposed* | NMEA GGA field 11; ellipsoid height = `ALTITUDE` + it |
| `CAMERA-DELAY-S` | Personal equation / camera delay (s) | *proposed* | the camera's timing offset, if known (applied or not: say which) |
| `OBSERVING-METHOD` | Observing method | *proposed* | the form's code: a = video, d = sequential images, ... |
| `OBJNAME` | Asteroid number and name | in use | "(709) Fringilla occ. UCAC4 644-038283" |

## 2. One layout for every video format: `recording.station`

Recordings come as **RAVF** (PyStarLight's capture), **ADV** (DVTI CamControl, OccuRec: other key names, e.g.
`CAMERA-SERIAL-NO`, `CAMERA-SENSOR-INFO`, `AUTHOR`, `ACQUISITION-DELAY`) or **SER** (its header holds only observer,
instrument and telescope, 40 characters each; the rest must come from a sidecar, `.times` / `.meta.json`). PyStarLight
reads each format and writes the station data in one layout into `event.json`, next to the raw metadata, so that
PySyzygos does not need to know every format. PySyzygos uses `recording.station` first and the raw keys of section 1
only where it is missing:

```json
"recording": {
  "date": "...", "first_utc": "...", "last_utc": "...",
  "metadata": { "...": "the movie's metadata as read, unchanged" },
  "station": {
    "format": "RAVF | ADV | SER",
    "recorder": "PyStarLight capture 0.1.0 | DvtiCamControl 5.9.0 | OccuRec ... | SharpCap ...",
    "site": {"lat": 46.9924869, "lon": 9.6401519, "alt_m": 972.8, "alt_ref": "MSL | ellipsoid",
             "geoid_separation_m": 48.2, "datum": "", "source": "GPS | config | none",
             "gps_fix": "3D", "satellites": 11, "hdop": 0.8, "position_utc": "2025-01-16T17:54:34Z"},
    "station": "Sternwarte Seewis Dorf (SWD)",
    "observers": ["Observer 1", "Observer 2"],
    "equipment": {"telescope": "C-14 EHD", "telescope_type": "SCT", "aperture_cm": 35.6,
                  "focal_length_cm": 62.2, "focal_reducer": "0.4x", "mount": "10 Micron GM2000",
                  "camera": "DVTI+CAM", "serial": "43", "sensor": "Sony IMX430", "method": "a"},
    "timing": {"source": "GPS | NTP | ...", "exposure_s": 0.075, "accuracy_s": 0.0001,
               "camera_delay_s": 0.0, "delay_applied": false}
  }
}
```

Rules: `site.source` says where the position came from (only "GPS" is the observation's own position); values not in
the recording are left out, not filled from the config, unless marked (`source: "config"`); `delay_applied` says
whether the time stamps already contain the camera delay.

## 2b. PyStarLight's analysis: `<movie>.event.json`

Used today (the viewer writes it with every result plot):

- `software`, `created_utc`, `movie`, `object`
- `target`: `name`, `ids` (`UCAC4`, `Gaia DR3`, `TYC`) -> star, Gaia DR3 id
- `recording`: `date`, `first_utc`, `last_utc` (start / end of the recording), `metadata` (section 1)
- `step_fit`: `frame_interval_s` (exposure until `EXPOSURE-S` exists), `levels[0].flux_scatter`,
  `transitions[i].sigma_s` (accuracy of D and R), `flux_before` / `flux_after` (signal/noise = step / scatter
  before the event), `events[k]`: `D_utc`, `R_utc`, `duration_s`; the first event is the main D/R, further ones go to
  "More events" (their codes, second star or satellite, are set by hand)

To cross-check with the form's requirements:

- Accuracy: the form asks for the timing accuracy of D and R. Today: the 1-sigma of the step fit. Add the time base
  (frame time stamps, camera delay)?
- Signal/noise: which definition does the form expect?
- A negative observation: the analysis has no event; does the form need the searched interval as M lines?
- The light curve (CSV) and the plots: a path or the data, to attach to a report.

## 3. Sending an analysis to the observation GUI

```
GET  /api/obs/v1/            -> {"ok": true, "version": ..., "inbox": n, "send": "/api/obs/v1/analysis"}
POST /api/obs/v1/analysis    body: the event.json (application/json, up to 20 MB)
     -> {"ok": true, "file": "<stored name>", "asteroid": "709 Fringilla", "date": "2025-01-16",
         "favorites": ["709_20250116T1755", ...], "msg": "..."}       400: not an analysis, 413: too large
```

- Usual case: PyStarLight analyses the copied videos on the computer that runs PySyzygos
  (`pysyzygos gui-observation`, 127.0.0.1:8081, or the next free port up to 8090: the connection file's `url` says
  which; or the search GUI's Favorites button "Observations", which starts
  it). The connection sets itself up: at every start the observation GUI writes `observation_api.json` into the
  user's PySyzygos settings folder (Linux `~/.config/pysyzygos/`, macOS `~/Library/Application Support/PySyzygos/`,
  Windows `%APPDATA%\PySyzygos\`; mode 600) with `url`, `send`, `inbox`, `data_folder` and a `token` made at the
  first start. PyStarLight reads it and sends with `Authorization: Bearer <token>` (401 without). When the GUI is not
  running, PyStarLight copies the event.json into `inbox` instead (temporary name, then rename); it is listed at the
  next start.
- With the observation GUI in server mode (e.g. started by the search GUI's button while that runs with
  `--host 0.0.0.0`), the connection file's key still works, from this computer only.
- From another computer (the camera's Raspberry Pi): start it as `pysyzygos gui-observation --host 0.0.0.0` with
  the search GUI's login (`pysyzygos gui --set-password`) and give the camera tool a token:
  `pysyzygos gui --new-token PyStarLight` (shown once). The program sends `Authorization: Bearer <token>`; that token
  can only use `/api/obs/v1/` (not the pages). See SERVER_MODE.md for HTTPS and access from outside.
- Stored in `observations/inbox/`; the Events tab lists them under "Received from PyStarLight" and opens the report
  of the matching favorite (same asteroid and night) with the analysis applied. Dropping an `event.json` into that
  folder by hand works as well.

## 4. The report form

The report is written as the IOTA-ES asteroidal occultation report form 2.03 (the DVTI+CAM template's layout). Its
first line names the versions (provisional, until the receiving side has a rule):

```
#IOTA-ES ASTEROIDAL OCCULTATION - REPORT FORM 2.03 - PySyzygos 1.5.2; data from PyStarLight 0.1.0
```

PySyzygos' own lines under EXTRA_FIELDS (switch "PySyzygos extra fields"): `TelescopeModel`, `FocalReducer`,
`PersonalEquationSec`, `GaiaDR3`, `MoreEvents`, and `DataFrom` (which fields came from the recording, the analysis,
the prediction, or were edited by hand).

Open: the submission itself, and the forms of the other IOTA regions (North America, Australia / New Zealand,
...), which may ask for other fields or layouts.
