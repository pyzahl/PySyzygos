"""net.py - open web addresses with the standard library (urllib) and a known list of certificate authorities.

Some Python installations (often on macOS) have no certificate authorities for urllib, so every https request fails
with "CERTIFICATE_VERIFY_FAILED: unable to get local issuer certificate", while browsers and the requests package
(which brings certifi) work. urlopen() here uses certifi's list (installed with requests) when available, else the
system's. Standard library otherwise.
"""
from pysyzygos.version import __version__
import ssl, urllib.request

_CTX = []


def context():
    """The SSL context for https requests (certifi's certificate authorities if installed)."""
    if not _CTX:
        try:
            import certifi
            _CTX.append(ssl.create_default_context(cafile=certifi.where()))
        except ImportError:                                       # no certifi: the system's list
            _CTX.append(ssl.create_default_context())
    return _CTX[0]


def urlopen(req, timeout=30):
    """urllib.request.urlopen with the context above (req: an address or a urllib.request.Request)."""
    return urllib.request.urlopen(req, timeout=timeout, context=context())


_FIRST = {}                                                       # per list of addresses: the one that answered last


def asu_ok(text):
    """A VizieR ASU answer, not an error page in its place: CDS and CfA have answered with status 200 and an HTML
    page ('Page unavailable') or a database error ('STDB_ERR', 'Postgres connect error') when down (2026-11-21)."""
    t = text.lstrip()[:4000]
    return not t.startswith("<") and "STDB_ERR" not in t and "#Coosys" in t


def read_first(bases, query, timeout=30, ok=None):
    """The text of base + '?' + query from the first of bases that answers (a primary server, then its mirrors in
    turn; the next request starts at the one that answered). ok(text) False (an error page with status 200) counts
    as no answer. Raises the last error when none answers."""
    key = tuple(bases)
    start = _FIRST.get(key, 0)
    err = None
    for k in range(len(bases)):
        i = (start + k) % len(bases)
        try:
            with urlopen(f"{bases[i]}?{query}", timeout=timeout) as r:
                text = r.read().decode("utf-8", "replace")
            if ok is not None and not ok(text):
                raise OSError(f"{bases[i]}: no valid answer (server error page)")
            _FIRST[key] = i
            return text
        except OSError as ex:                                     # URLError, HTTPError and timeouts are OSErrors
            err = ex
    raise err
