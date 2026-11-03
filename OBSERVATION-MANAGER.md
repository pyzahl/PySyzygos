# PySyzygos Observation Manager

The observation side of PySyzygos: after the night, it collects your observed events, takes the **automated video
analysis from PyStarLight directly**, and writes the observation report of each event and station. It is a separate
web app beside the search GUI (the prediction tool), with its own process, port and settings.

```bash
uv run pysyzygos gui-observation          # http://127.0.0.1:8081 (the search GUI stays on 8080; both can run)
                                          # 8081 taken by another program: the next free one, 8082 ... 8090
```

Or from the search GUI: Favorites tab, **Observations** (starts it in the background if needed and opens it).

Early version: lists, the archive of observed events, the report form, the imports and the IOTA-ES report text.
Still to come: the submission itself, the forms of the other IOTA regions, several stations of one event with a chord
plot, observer profiles.

## Contents

- [From the recording to the report](#from-the-recording-to-the-report)
- [Importing PyStarLight's video analysis](#importing-pystarlights-video-analysis)
- [The tabs](#the-tabs)
- [Where every value came from](#where-every-value-came-from)
- [The report form](#the-report-form)
- [Running it: modes, ports, restart](#running-it-modes-ports-restart)
- [Files](#files)

## From the recording to the report

```
camera tool (capture)  ->  video + its metadata (GPS site and time, camera, telescope, observers)
      ->  PyStarLight (video analysis: light curve, D/R times with errors)  ->  <movie>.event.json
      ->  Observation Manager (imported directly)  ->  report  ->  IOTA-ES report form (.txt)
```

What describes the observation itself (where, when, with what, by whom) comes from the **recording**, written by
the camera tool at recording time, and reaches the report unchanged. The **analysis** adds the D and R times, their
accuracy, the duration, the signal/noise and the star. The **prediction** (your favorite) adds the event, the
predicted times at your site and the prediction details.

## Importing PyStarLight's video analysis

PyStarLight's viewer (`pystarlight-view`) analyses the video: it extracts the light curve, fits the steps and computes
the chord times. Its result, `<movie>.event.json`, is imported **directly**, with no retyping, in three ways:

1. **Sent by PyStarLight** (automatic): PyStarLight posts the analysis to the Observation Manager
   (`POST /api/obs/v1/analysis`). It appears in the Events tab under **Received from PyStarLight** and opens with the
   matching favorite (same asteroid and night) and the analysis applied. On the same computer this sets itself up:
   the Observation Manager writes a connection file at every start, `observation_api.json` in your PySyzygos
   settings folder (Linux `~/.config/pysyzygos/`, macOS `~/Library/Application Support/PySyzygos/`, Windows
   `%APPDATA%\PySyzygos\`; readable by you only), with its address, the inbox and a key made at the first start.
   PyStarLight reads it; nothing to copy by hand. When the Observation Manager is not running, PyStarLight copies
   the analysis into its inbox folder instead, listed at the next start.
2. **Found**: in the Report tab, **Find PyStarLight analysis** searches your PyStarLight and recording folders for
   the `event.json` of that night and asteroid (links inside them are not followed: list a recordings drive's
   folder itself).
3. **Loaded by hand**: a `.event.json` file (upload in the Report tab).

Taken from the analysis file:

| From | Report fields |
|---|---|
| the recording's metadata (any format: RAVF, ADV, SER with its sidecar; or PyStarLight's common `recording.station` block) | latitude, longitude, altitude (GPS), datum, station, observers, telescope and type, aperture, focal length, focal reducer, mount, camera with serial and sensor, observing method, time source, exposure, camera delay, start and end of the recording |
| the analysis (step fit) | result, D and R times with their 1-sigma accuracy, duration, signal/noise, the star (UCAC4, Gaia DR3), further dips ("More events": set their codes by hand) |

The exact keys, the connection file, the API and what the camera tool should still provide:
[docs/observation_interface.md](docs/observation_interface.md).

## The tabs

* **Status**: favorites marked observed, saved lists, the Occult archive, where PyStarLight analyses are searched,
  analyses received, saved reports, the connection file, and what is not built yet.
* **Events**: the events to report on: favorites marked observed (or all), a saved list (e.g. the one the search
  GUI's "Move past observed to list…" fills), the Occult archive of observed occultations (with the Occult data
  add-on; search by number, name or date; choose one of its observers to see that chord), the analyses **Received
  from PyStarLight**, or your saved reports. **Open the report form** for the chosen one.
* **Report**: the observation report of one event and station. Prefilled from the event: asteroid, star (UCAC4 and
  Gaia DR3 id), date, predicted time and the predicted D and R at your site, the site, the prediction details. Then
  the PyStarLight analysis (above), or an IOTA-ES report form (`.txt`, e.g. from the DVTI tools). An orange line lists
  what a submission still needs. **Save** keeps the report; **IOTA-ES report (.txt)** saves it and downloads it as
  report form text, to submit.

## Where every value came from

Every field says where its value came from: **the recording** (the camera tool's data: the authentic ones), **the
analysis**, **the prediction**, or **edited by hand**. A value from the recording that is changed by hand stays
marked as edited and shows the recording's value; changed back, the mark goes. The origins are saved with the report
and, with the extra fields on, written into it (`DataFrom`).

## The report form

The fields are those of the IOTA-ES asteroidal occultation report form 2.03 (the layout of the DVTI+CAM template),
which also carries what Occult's archive keeps per observer: result, event, observer, station, equipment, D/R times
with accuracy, conditions, prediction details. The first line names the programs and versions (provisional):

```
#IOTA-ES ASTEROIDAL OCCULTATION - REPORT FORM 2.03 - PySyzygos 1.5.2; data from PyStarLight 0.1.0
```

**PySyzygos extra fields** (a switch) adds our own lines under EXTRA_FIELDS: telescope model, focal reducer,
personal equation, Gaia DR3 id, more events, and where each field came from. Off: only the form's lines.

Online submission is not built yet: submit the text the usual way.

## Running it: modes, ports, restart

- **Port**: 8081, or the next free one up to 8090 if another program has it (the connection file says which). An
  explicit `--port` that is taken stops with a message.
- **From the search GUI**: Favorites tab, **Observations**: started in the search GUI's mode if it is not running,
  then opened at `<the address you use>:<its port>`. In server mode it runs on the same address with the same login
  (the browser carries the login over); a reverse proxy has to pass its port as well.
- **Server mode** (another computer, e.g. the camera's Raspberry Pi, sends the analyses):
  `pysyzygos gui-observation --host 0.0.0.0` with the search GUI's login (`pysyzygos gui --set-password`) and a token
  for the camera tool (`pysyzygos gui --new-token PyStarLight`); that token may only use `/api/obs/v1/`. The
  connection file's key keeps working from this computer only. Details: [SERVER_MODE.md](SERVER_MODE.md).
- **Restart / Quit**: the power button at the top right (this app only; the search GUI is not affected). Restart keeps
  the port, address and mode and the page reconnects; no Quit in server mode.

## Files

| What | Where |
|---|---|
| reports | `observations/<event>/<station>.json` and `..._IOTA-ES.txt` in the data folder (private, gitignored; `pysyzygos cleanup` never deletes them) |
| analyses received | `observations/inbox/` |
| settings | `gui_observation_state.json` in the data folder |
| connection for PyStarLight | `observation_api.json` in the PySyzygos settings folder (mode 600) |
| code | `src/pysyzygos/gui_observation.py` (the app), `src/pysyzygos/obsreport.py` (fields, imports, report form, inbox; standard library only), `tests/test_obsreport.py` |

It only reads the favorites, the saved lists and the Occult archive; it never changes them, and it never writes into
PyStarLight's folders.
