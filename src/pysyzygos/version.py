"""version.py - the PySyzygos version and project facts, kept in this one place. Every module and tool takes
them from here (GUI header and About box, --version of the tools, run summaries, CITATION.cff by hand).

Semantic versioning: MAJOR.MINOR.PATCH. Raise PATCH for fixes, MINOR for new features, MAJOR for changes that break
existing files or results (and update CITATION.cff's version with it). The code name changes at major milestones.
Every version increase gets its entry in CHANGELOG.md.
"""
__version__ = "1.5.1"
__codename__ = "Beyond Horizons"   # since 1.1.0 (before: "New Horizons", JPL Horizons orbits; New Horizons' target
                                   # Arrokoth was first shaped by occultations): still JPL Horizons orbits, now with the
                                   # astrometry checked beyond them against Occult, whole paths across the globe
__author__ = "Percy Zahl (pyzahl)"
__copyright__ = "(C) 2026 Percy Zahl"
__license__ = "GPL-3.0-or-later"
__url__ = "https://github.com/pyzahl/PySyzygos"
