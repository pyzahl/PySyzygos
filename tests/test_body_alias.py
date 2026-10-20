"""kernels.body_alias: asteroid numbers as SPICE names through the kernel pool, far beyond boddef's ~161 user names
(CSPICE N0067: 853 pairs, ~692 built in; a search of 400 targets failed with SPICE(TOOMANYPAIRS), 2026-10-19).
Uses the real SpiceyPy when installed (no kernel files needed), else skips."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
try:
    import spiceypy as spice
except ImportError:
    print("test_body_alias: SpiceyPy not installed, skipped")
    sys.exit(0)
from pysyzygos import kernels as K

spice.kclear()
K._ALIASES.clear()
for k in range(1500):                                       # far more than boddef allows
    K.body_alias(spice, str(100000 + k), 20100000 + k)
assert spice.bodn2c("100000") == 20100000 and spice.bodn2c("101499") == 20101499
assert spice.bodc2n(20100007) == "100007"
assert spice.bodn2c("MARS") == 499 and spice.bodn2c("EARTH") == 399            # built-in names still there
K.body_alias(spice, "M:Io", 501)                            # planets/moons use it too
assert spice.bodn2c("M:IO") == 501
K.body_alias(spice, "100000", 20100000)                     # again: unchanged
assert spice.bodn2c("100000") == 20100000
spice.kclear()                                              # the pool is emptied; the next call restores all names
K.body_alias(spice, "123456", 20123456)
assert spice.bodn2c("100001") == 20100001 and spice.bodn2c("123456") == 20123456
spice.kclear()
print("BODY ALIAS TESTS PASSED")
