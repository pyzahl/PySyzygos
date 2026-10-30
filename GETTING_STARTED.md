# Getting started: your first prediction in six steps

This page takes you from a fresh install to your first predicted occultation and a look at everything PySyzygos
knows about it. No Python knowledge is needed. The full details are in [README.md](README.md); what is computed and
how is in [ABOUT.md](ABOUT.md).

**What you will do:** tell PySyzygos where you observe and with what (once), let it look through all known
asteroids for events at your site, compute the best of them exactly, and keep the ones you like.

**What to expect the first time:** the first run of each step downloads data and is slow (minutes). Everything is
kept, so later runs take seconds. See [Why the first run is slow](#why-the-first-run-is-slow) at the end.

---

## 1. Install and set up (once, about 15 minutes)

1. Install [uv](https://docs.astral.sh/uv/getting-started/installation/), a small tool that brings the right Python
   and all packages by itself:
   * Linux / macOS, in a terminal: `curl -LsSf https://astral.sh/uv/install.sh | sh`
   * Windows, in PowerShell: `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`

   Then open a new terminal.
2. Get PySyzygos: `git clone https://github.com/pyzahl/PySyzygos`, or on GitHub the green **Code** button,
   **Download ZIP**, and unpack it.
3. In the PySyzygos folder, run the setup:

   ```bash
   cd PySyzygos
   uv run pysyzygos setup
   ```

   It asks a few questions:
   * **your site**: type **s** (skip) and Enter. Setup then uses an example site (New York), and you set up your
     own in the web interface in the next step, on a map, which is easier.
   * **the star catalog**: Enter = stars to magnitude G 16, the right choice for most telescopes.
   * **its parts**: Enter = core + quality (4 GB on disk).

   Then it downloads the planet and Earth data (about 120 MB) and the star catalog (about 3 GB). If it is
   interrupted, run the same command again: it continues where it stopped.

## 2. Start the program and set your site

```bash
uv run pysyzygos
```

Your web browser opens PySyzygos (it runs only on your computer). Work through the tabs from left to right.

In the **Site** tab:
* Move the marker to where you observe, or paste your coordinates from a map or GPS into the **Latitude** field
  (most formats work, e.g. `40.7128, -74.0060`). An exact position matters: a shadow can be only a few km wide.
* Enter your telescope: aperture, focal length, and your camera (type its name or sensor, e.g. "174", in
  **Sensor (cameras)**).
* **Give your site a name**: type it in **New site name** (e.g. "Home" or "Backyard"), then click **Add as new
  site**. Your site is saved and selected at the top right (**Site for all runs**), where every run takes it from.
  The example site can go: select it at the top right and click **Remove site**.

Later changes to a site (another camera, a correction of the position, a new photo): select it at the top right,
change the form, and click **Save changes** (the save button turns amber with that label as soon as the form differs
from what is saved). Switching to another site with unsaved changes asks first: save them, discard them, or cancel
(stay). A run saves the selected site's changes by itself. You can keep several sites, e.g. home and a dark-sky spot,
and switch between them at the top right. **Add site** makes a new site from the form's position, equipment and
limits; a horizon, photo or description it takes only if you changed them in the form, so nothing of the site shown
before carries over.

From this, PySyzygos works out how faint a star your equipment can use (shown as **Star G limit** in the next
tabs).

Optional, under **Horizon**: your own horizon (trees, buildings, hills), so that events whose star is behind it are
marked. Either load OccultWatcher's `UserHorizon.txt`, or make the horizon from a **360° photo** of the site:
1. Take the photo level at the telescope on a day with a reasonably clear blue sky (a 360° camera or a phone's
   photo sphere), and note the time.
2. **Load a 360° photo**: the horizon line is found in it automatically (a few clouds are fine).
3. **Sun at** is filled from the photo's own time when it has one (most cameras store it), and with the Sun in the
   photo it is aligned by itself: turned so that the Sun in it sits where the Sun really was. Otherwise type the time
   you took it (your local time, e.g. `4:45 pm`) and click **Align by the Sun**. Azimuth ticks every 5° and 10° help
   to check.
4. **Horizon from the photo** turns the line into horizon points; **Save sites.py** keeps everything.
   **UserHorizon.txt** downloads the horizon for OccultWatcher too.

<img width="1890" height="1731" alt="image" src="https://github.com/user-attachments/assets/a8a6e041-bccc-4bff-bbc4-f83ee9f3809b" />

*Demo photo: [Spherical panorama Blue Bridge St James Park](https://commons.wikimedia.org/wiki/File:Spherical_panorama_Blue_Bridge_St_James_Park_20250522.jpg)
by Domob, Wikimedia Commons, [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/); horizon line drawn by
PySyzygos.*

## 3. Pick: which asteroids pass in front of a star for you?

In the **Pick** tab: keep the start date (today) and choose the number of days, e.g. 7 for a first try. Click
**Run pick**.

PySyzygos now checks every known asteroid brighter than H 17, about 465,000 of them, against the stars along its
path for events at your site. The log at the bottom shows its progress.

> **The first pick is the slow one.** It first downloads JPL's list of all asteroids (about 100 MB, a minute or
> two), then screens them: several minutes, more for a long window. Later picks reuse the list.

**Only some asteroids?** The box **Which asteroids to screen** chooses them by orbit: untick **Main belt** to screen
only Jupiter Trojans, NEOs, TNOs and the other rarer kinds (~15,000 instead of ~465,000: seconds), or set a range of
the semi-major axis (click a band, e.g. Hildas). A line there says how many asteroids your choice screens. See
"Which asteroids" in the [README](README.md#which-asteroids-groups-orbit-class-and-a-range).

When it is done, the table shows the events found. Click **Use for search**: it sets the Search tab to the same
window and takes you there.

<img width="2377" height="1911" alt="image" src="https://github.com/user-attachments/assets/1ac48938-9dbc-4c16-b9a6-c9fa8380c187" />



## 4. Search: the exact predictions

In the **Search** tab, click **Run search**. For each picked asteroid PySyzygos downloads its current orbit from JPL
and its size data, then computes each event exactly: the time at your site, the shadow's path on the Earth, the
star's drop in brightness and the duration.

> **The first search takes a little longer:** about a second per asteroid for the downloads (orbits two at a time).
> A search again within a day uses them directly and takes seconds. Orbits older than a day are downloaded again,
> so your predictions always use JPL's latest orbit.

<img width="2246" height="1818" alt="image" src="https://github.com/user-attachments/assets/beb2c54c-0ab2-4050-ab65-38b82c77d165" />


## 5. Results: look at the events

The **Results** tab lists every event, best first. For each one:
* **Map**: the shadow's path near you, with its edges and uncertainty limits, and your site.
* **Preview**: the star field as your camera will see it.
* **Globe**: the whole Earth as seen from the star, with the path and minute marks; below it, the geometry at true
  scale and how the Sun's gravity bends the starlight.
* **KML**: the path for Google Earth.
* **Stellarium** (and on Linux **KStars**): points the planetarium program at the star at the event time, from
  your site, and marks the star (Stellarium selects it; in KStars a crosshair field-of-view symbol of your own marks
  the center, see the README).
* **☆**: keeps the event in your favorites.

Star the events you like.

A long list? Open **Filter** above the table: for example a date range, G ≤ 12, duration ≥ 0.5 s, Sun ≤ −12° (no
twilight), "clear of horizon ≥ 5°" (uses your site's horizon, also for searches made before you set it) and "hide
uncertain star". **Save as...** keeps such a filter under a name for later (also in Favorites). **CSV** downloads
exactly what the table shows. For anything else there is the **SQL filter** on the Results tab, e.g.
`mag < 11 AND chance > 30`: it starts with your filter's settings, which you can then change.

<img width="2246" height="1818" alt="image" src="https://github.com/user-attachments/assets/c4f4c7d9-f685-46d0-ba22-780502e32452" />


## 6. Favorites: everything about one event

In the **Favorites** tab, **click a row**. Below the table you get:
* the star-field preview and the path map side by side;
* an event summary: when the shadow is on the Earth, magnitudes and drop, duration, the Moon, the Sun's distance,
  the star's position and whether Gaia flags it as double, the asteroid's size, distance and motion;
* the uncertainty: ellipses for the asteroid's and the star's position, and how far the path may lie from its
  prediction, in km;
* the asteroid's size, shape and rotation where known, and earlier occultations by it;
* a **status** (planned, observed, cancelled, clouded) and a **note** to keep.

**Will it be clear?** The **Cloud forecast** button at the top of the Favorites tab fetches the weather forecast for
every favorite in the next 16 days: a symbol with the cloud cover under each event's time (🌙 clear ... ☁ overcast),
and the hours around the event in the panel. Click it again closer to the night: only the last 1-3 days are reliable.

Each favorite keeps its own copy of map and preview, so later searches do not change them.

<img width="2338" height="2043" alt="image" src="https://github.com/user-attachments/assets/a87d10bc-e415-4cf6-9a1d-20facc6dc75a" />

<img width="1906" height="1671" alt="image" src="https://github.com/user-attachments/assets/85e57582-7a79-433f-88a3-82d889f9cf24" />


<img width="2246" height="1818" alt="image" src="https://github.com/user-attachments/assets/441cb3fe-b8e5-497a-8540-edcf5f1b7d01" />

<img width="2292" height="1963" alt="image" src="https://github.com/user-attachments/assets/85cef7b2-f6d3-4590-ad08-1a1b29f1460b" />

**All the details of the computation:** tick **Path verification** at the top of the Favorites tab, then click an
event (anywhere in its row, e.g. on the date, just not on a link) and scroll down to the section "Path
verification". **Step by step** computes and shows every step for this event: the star from the Gaia catalog through
each correction, the asteroid, the shadow's geometry and the points on the ground. There you can also cross-check
the path automatically against a path listing exported from Occult.

**That's it.** Next time: `uv run pysyzygos`, and run a new pick when your window has passed.


---

## Why the first run is slow

PySyzygos works from local copies of the data it needs. The first time, it has to fetch them:

| When | What is downloaded | How long | Kept |
|---|---|---|---|
| setup | planet and Earth data (120 MB), star catalog (3 GB) | minutes, depending on your internet | for good (checked for updates weekly) |
| first pick | JPL's list of all asteroids (100 MB) | a minute or two | 30 days, then fetched again |
| first search | each asteroid's orbit and size | about 1 s per asteroid | orbits 1 day, sizes 30 days |

**Where the downloads are kept:** in a cache folder: on Linux in memory (`/dev/shm`, emptied when you restart the
computer), on macOS and Windows in the system's temporary folder (emptied from time to time). After a restart the
first pick and search are therefore slow again. To keep them for good, and to work without internet (e.g. at a
remote observing site): **System** tab, tick **Keep copies of orbit downloads for use without network**. After a
restart the pick then takes the asteroid list from that copy (while it is younger than 30 days) instead of
downloading it again.

**Speeding up picks:** a **pre-screen** (Pick tab, **Pre-screens** panel) does the site-independent part of the pick
once for a window; picks within it then take seconds instead of minutes. Building one takes about as long as a few
full picks (an hour or two for a month), so it pays off when you pick more than once: for several sites (home, a
dark-sky spot, travel), when you try other settings (camera, star limit, reach), or for weekly picks within a month.
If you only pick once per window for one site, just run the pick. Tips: build it overnight (it can be stopped and
resumed); rebuild it after a few weeks, as it uses the orbits of its build day; "whole Earth" serves any site and trip
(about 1 GB per month). See "Pick" in the [README](README.md).

## If something goes wrong

* **Nothing happens / no events:** check the log at the bottom of the page. A short window (1-2 days) or a small
  telescope can simply have no events; try 7-14 days.
* **A download fails:** offline, or a server is busy. Run it again later; it resumes.
* **The System tab** shows what data PySyzygos has and uses (catalog, orbits, Earth data and their dates), and
  **Setup status** checks the installation.
* More help: [README.md](README.md), section by section.
