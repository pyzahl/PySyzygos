"""urls.py - every download and web address PySyzygos uses, in one place (change them here only).

Kept apart from pysyzygos_config.py on purpose: that file reads sites.py and chooses the site when it is imported,
while some modules need these addresses before a sites.py exists (setup.py downloads the kernels and looks
up the site) or run without the configuration at all (report.py). This file has no side effects.

Not here: XML namespaces of the SVG and KML formats (fixed identifiers, not downloads) and the project's own GitHub
address (version.__url__).
"""

# --- NAIF SPICE kernels (kernels.py)
URL_NAIF_LSK = "https://naif.jpl.nasa.gov/pub/naif/generic_kernels/lsk/naif0012.tls"                 # leap seconds
URL_NAIF_LSK_DIR = "https://naif.jpl.nasa.gov/pub/naif/generic_kernels/lsk/"    # listing: a newer naifNNNN.tls?
URL_NAIF_DE440 = "https://naif.jpl.nasa.gov/pub/naif/generic_kernels/spk/planets/de440.bsp"         # planets
URL_NAIF_PCK = "https://naif.jpl.nasa.gov/pub/naif/generic_kernels/pck/pck00010.tpc"                # body constants
URL_NAIF_SATELLITES = "https://naif.jpl.nasa.gov/pub/naif/generic_kernels/spk/satellites/"  # + jup365.bsp (optional)
URL_NAIF_EARTH_PCK = "https://naif.jpl.nasa.gov/pub/naif/generic_kernels/pck/earth_latest_high_prec.bpc"  # Earth orientation
URL_NAIF_PCK_DIR = "https://naif.jpl.nasa.gov/pub/naif/generic_kernels/pck/"   # + earth_1962_*_combined.bpc (historic)

# --- Gaia DR3 bulk files at ESA (gaia_local.py build)
URL_GAIA_DR3_FILES = "https://cdn.gea.esac.esa.int/Gaia/gdr3/gaia_source/"     # + file name
URL_GAIA_DR3_LISTING = "https://gaia.eu-1.cdn77-storage.com/"                   # S3-style listing of the same files
GAIA_DR3_LISTING_PREFIX = "Gaia/gdr3/gaia_source/"                               # its prefix parameter

# --- ready-made local catalogs on Zenodo (gaia_local.py, setup.py)
URL_GITHUB_LATEST_RELEASE = "https://api.github.com/repos/pyzahl/PySyzygos/releases/latest"   # selfupdate.py
URL_CHANGELOG = "https://github.com/pyzahl/PySyzygos/blob/main/CHANGELOG.md"                 # System tab link
URL_ZENODO_CATALOG_RECORD = "https://zenodo.org/api/records/23113337"           # concept record: newest version
# mirrors of the ready-made catalog archives (starcat.fetch; the same file names, checked against the SHA-256 stored
# in starcat.ARCHIVE_SHA256): folder addresses ending in /, tried with Zenodo, the fastest wins. Env
# PYSYZYGOS_CATALOG_MIRROR adds one (e.g. a club's or institute's copy).
URL_CATALOG_MIRRORS = [
    "https://bnlbox.sdcc.bnl.gov/public.php/dav/files/2byYPzX4odRZRfR/catalog_v2.1/",   # temporary BNL box (1.3.2+)
]
# shared pre-screens (prescreen.py fetch/remote): folders with prescreens.json and <name>.tar.xz (+ .sha256); env
# PYSYZYGOS_PRESCREEN_MIRROR adds one. Filled by `pysyzygos prescreen publish` (local release/world-prescreens/).
URL_PRESCREEN_MIRRORS = [
    "https://bnlbox.sdcc.bnl.gov/public.php/dav/files/2byYPzX4odRZRfR/world-prescreens/",   # temporary BNL box
]
URL_UCAC4_ZONES = "https://cdsarc.cds.unistra.fr/ftp/I/322A/UCAC4/u4b/"        # UCAC4 zone files z001..z900 (xref)
URL_CDS_XMATCH = "https://cdsxmatch.u-strasbg.fr/xmatch/api/v1/sync"             # CDS XMatch (supplement pm: UCAC5/4)

# --- JPL Solar System Dynamics
URL_JPL_HORIZONS_API = "https://ssd.jpl.nasa.gov/api/horizons.api"              # asteroid orbits as SPK (search.py)
URL_JPL_SBDB_API = "https://ssd-api.jpl.nasa.gov/sbdb.api"                      # one asteroid's data (search.py)
URL_JPL_SBDB_QUERY_API = "https://ssd-api.jpl.nasa.gov/sbdb_query.api"          # all asteroids in bulk (pick tool)
URL_JPL_SBDB_PAGE = "https://ssd.jpl.nasa.gov/tools/sbdb_lookup.html#/?sstr="   # web page, + asteroid number (report)

# --- earlier occultation results (pysyzygos/occultations.py): NASA PDS Small Bodies Node archive
URL_PDS_OCCULTATIONS_PAGE = "https://sbn.psi.edu/pds/resource/occ.html"                       # all versions
URL_OCCULT_DATA = "https://www.occultations.org/sw/occult/"   # + <File>.zip (case-sensitive): occultdata.py add-on
URL_PDS_OCCULTATIONS_ZIP = "https://sbnarchive.psi.edu/pds4/non_mission/smallbodiesoccultations_V4_0.zip"  # V4.0

# --- asteroid satellites (pysyzygos/binaries.py)
URL_PDS_BINARIES_ZIP = "https://sbnarchive.psi.edu/pds4/non_mission/ast_binary_parameters_compilation_V3_0.zip"
URL_JOHNSTON_ASTEROID_MOONS = "https://www.johnstonsarchive.net/astro/asteroidmoons.html"   # current list (web)

# --- OccultWatcher Cloud (pysyzygos/owc.py; config owc_feeds): the interface of its public event pages
URL_OWC_API = "https://www.occultwatcher.net/api2/v1/owc"                     # + events/?astNo=&dt=&bf=, event/<id>
URL_OWC_EVENT_PAGE = "https://cloud.occultwatcher.net/event/"                  # + event id (web page)

# --- Minor Planet Center (geo.py, GUI Site tab)
URL_MPC_OBSCODES = "https://minorplanetcenter.net/iau/lists/ObsCodes.html"      # observatory codes

# --- star pages (report)
URL_VIZIER_ASU = "https://vizier.cds.unistra.fr/viz-bin/asu-tsv"                 # VizieR queries (double-star check)
URL_VIZIER_GAIA_DR3 = "https://vizier.cds.unistra.fr/viz-bin/VizieR-5?-source=I/355/gaiadr3&Source="  # + Gaia DR3 id

# --- places, elevation, time zones (geo.py)
URL_OPENMETEO_ELEVATION = "https://api.open-meteo.com/v1/elevation"
URL_OPENMETEO_GEOCODING = "https://geocoding-api.open-meteo.com/v1/search"
URL_OPENMETEO_FORECAST = "https://api.open-meteo.com/v1/forecast"               # used for the time zone only
URL_IPINFO = "https://ipinfo.io/json"                                           # approximate position from the IP
# EGM96 geoid, 15-minute grid in GeographicLib's PGM format (NGA's EGM96, public domain); the source of
# data/egm96_30min.npy (`python -m pysyzygos.geoid build`; not downloaded at run time)
URL_EGM96_GEOID = "https://sourceforge.net/projects/geographiclib/files/geoids-distrib/egm96-15.tar.bz2/download"

# --- maps in the report and favorites pages
URL_OSM_TILES = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"               # report --tile-url default
URL_LEAFLET_CSS = "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css"
URL_LEAFLET_JS = "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"
URL_GOOGLE_MAPS_SEARCH = "https://www.google.com/maps/search/?api=1&query="    # + "lat,lon"

# --- planetarium programs on this computer
URL_STELLARIUM_API = "http://localhost:8090/api"    # Stellarium's Remote Control plugin (default port 8090)
