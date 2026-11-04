# PySyzygos Observation Manager

The observation side of PySyzygos: after the night, it collects your observed events, takes the **automated video
analysis from PyStarLight directly**, and writes the observation report of each event and station. It is a separate
web app beside the search GUI (the prediction tool), with its own process, port and settings.

```bash
uv run pysyzygos gui-observation          # http://127.0.0.1:8081 (the search GUI stays on 8080; both can run)
                                          # 8081 taken by another program: the next free one, 8082 ... 8090
```

Or from the search GUI: Favorites tab, **Observations** (starts it in the background if needed and opens it).

Early version: lists, the archive of observed events, the report form, the imports, the IOTA-ES report text and the
chord plot of an event. Still to come: the submission itself, the forms of the other IOTA regions, observer profiles.

## Contents

- [From the recording to the report](#from-the-recording-to-the-report)
- [Importing PyStarLight's video analysis](#importing-pystarlights-video-analysis)
- [The tabs](#the-tabs)
- [Where every value came from](#where-every-value-came-from)
- [The report form](#the-report-form)
- [Chords: the profile of an event](#chords-the-profile-of-an-event)
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
  from PyStarLight**, or your saved reports. Click a row to choose it, then **Open the report form**.
  Favorites, lists and the archive are shown as the Results table with its **filter bar**, plus two filters found
  only here:
  * **event**: only the results of one event, i.e. the same target with times within 10 minutes (several stations,
    several sites, the observers of an archive event checked by obs-check). The **n results** button beside the
    target does the same; click it again to show all.
  * **results per event ≥**: multi-chord events. It counts the results of the event in the list; in the archive it
    counts the event's observers. 2 = every event with more than one chord.

  **Archive record** opens the event's whole record in the IOTA / Occult archive, the same view as the search GUI's
  Results tab (event, star, Occult's fit, satellite, every observer with their times, our check); for a favorite, a
  report or a received analysis, the archive's event of the same asteroid and time, when the archive has it.

  Saved filter sets stay in this browser. Without a search, the archive shows its newest 3,000 events (all 17,000
  take ~15 s to show); search a number, name, year or month (`2023`, `2023-12`) for the others.
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

## Chords: the profile of an event

All stations of one event together, as Occult draws them: choose the event in the Events tab, **Chord plot**.

* **Past events**: an event of the Occult archive, with every observer's D and R as the archive has them.
* **Fresh data**: our saved reports, one per station (each one made from PyStarLight's analysis, or typed in). A
  report, or a favorite of the event, brings all saved reports of that event (same asteroid, times within 10 minutes).
  Saved a report since? The plot is computed again by itself.

How: each station's D and R become points in the fundamental plane, the station's position relative to the
asteroid's predicted center at those times (JPL Horizons orbit seen from the station, the star as the search takes
it, axes of date like Occult's). A positive station gives a chord from D to R, a miss its whole track (dashed). An
ellipse is fitted to the chords' ends (least squares of their radial distances); its center is the observed minus
predicted position. With 3 chords or more an ellipse, with 2 a circle, with 1 the predicted diameter (**Shape
fitted**; or choose one). **Misses as limits** keeps the outline off the misses' tracks.

Satellites and double stars: each of a station's chords is its own entry. Chords of a satellite (Occult's codes G/B,
e.g. Menoetius for (617) Patroclus) are drawn in orange with their own fitted outline; chords on the 2nd star of a
double (d/r) in teal, not fitted. The main body's fit uses only its own chords.

**Binary asteroids: watch for several bodies.** JPL's orbit of a binary such as (617) Patroclus describes the
*system* (one orbit for the pair), the point a plain prediction uses (Occult's "JPL#.." too): no body need be there.
PySyzygos' search takes each body as its own target where JPL has their ephemerides (ABOUT.md 4.2). Where JPL also has the bodies' own ephemerides (Horizons 920000617 = Patroclus, 120000617 = Menoetius), the plot
marks each body's predicted position (✚) and gives the observed minus predicted against it. Patroclus 2026-01-04:
Menoetius observed 84 km from its own prediction; Patroclus, predicted ~190 km east of the system point, had no
station on its path (the archive's "Unseen primary"). A station with only a D or only an R
(the recording began or ended inside the event) is a one-sided chord: a single point of the outline, in the fit.
Planets and moons of the archive (e.g. Ganymede 2025-10-14) are fitted at their known size, as Occult does; comets
and Venus are not supported yet.

The **Chords** tab shows:

* the plot: north up, east left; D (□) and R (○) with their timing accuracy (amber), the fit, the predicted size at
  the predicted center (+), and for archive events Occult's own fit (dotted) for comparison;
* a table of the stations: untick one to leave it out of the fit (the plot and the fit follow at once; chords Occult
  excluded start unticked), with each chord's O−C at D and R in seconds (along the track, against the fitted outline)
  and in km (radial);
* **Compute again** (today's orbit; your choices are kept) and **Download SVG**.

Check: (135) Hertha 2008 Dec 11, 20 chords. We get 101.9 ± 2.8 × 60.7 ± 2.6 km, PA 41.7 ± 2.8°; Occult's archive
fit is 103.6 × 59.9 km, PA 40.6°. Both centers sit 14 km east and 7 km north of our prediction (within 0.4 km). The
same stations entered as our own reports give the same points (within a millimeter).

Command line: `pysyzygos chords archive "135|2008-12-11T07:45:46"`, `pysyzygos chords reports <report.json>`,
`pysyzygos chords fit <chords.json> --mode circle --exclude 21` (files in `observations/chords/<event>/`).

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
| chords | `observations/chords/<event>/chords.json` (stations in the plane, fit, your choices) and `profile.svg` |
| settings | `gui_observation_state.json` in the data folder |
| connection for PyStarLight | `observation_api.json` in the PySyzygos settings folder (mode 600) |
| code | `src/pysyzygos/gui_observation.py` (the app), `src/pysyzygos/obsreport.py` (fields, imports, report form, inbox; standard library only), `src/pysyzygos/chords.py` (chords, fit, plot), `tests/test_obsreport.py`, `tests/test_chords.py` |

It only reads the favorites, the saved lists and the Occult archive; it never changes them, and it never writes into
PyStarLight's folders.
