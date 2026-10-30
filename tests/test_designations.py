"""Unnumbered asteroids as targets by provisional designation ('2026 ED138'): the target list parser, the designation
test, the Horizons COMMAND (quoted for the space), the globe's short name, and that OWC (numbers only) is skipped.
No network, no SPICE."""
import ast, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
from pysyzygos import sbdb as S, owc

assert S.is_designation("2026 ED138") and S.is_designation("1999 KW4") and S.is_designation("1937 UB")
assert not S.is_designation("2026") and not S.is_designation("2026 IA") and not S.is_designation("P:Jupiter")
assert not S.is_designation("218001") and not S.is_designation("2026ED138")        # the list parser normalizes that
cases = {"2026 ED138": ["2026 ED138"],
         "3200, 2026 ED138 P:Jupiter": ["3200", "2026 ED138", "P:Jupiter"],
         "2026_ED138 2026ED138": ["2026 ED138", "2026 ED138"],
         "2026 218001": ["2026", "218001"],                     # asteroid (2026) and 218001, not a designation
         "2026": ["2026"], "": [],
         "1999 KW4 66391": ["1999 KW4", "66391"],
         "2026 ED138,1937 UB": ["2026 ED138", "1937 UB"],
         # commas separate, spaces trimmed
         "3200,  2026   ED138 , P:Jupiter,": ["3200", "2026 ED138", "P:Jupiter"],
         "2026 , 218001": ["2026", "218001"],
         "2026_ED138, 2026ED138": ["2026 ED138", "2026 ED138"],
         "3200 218001": ["3200", "218001"],                     # no comma: spaces separate, as before
         "2026, ED138": ["2026", "ED138"]}                      # a comma is a hard boundary
for text, want in cases.items():
    assert S.split_targets(text) == want, (text, S.split_targets(text))

# search.py is not import-safe (kernels at import): its horizons_command on its own
src = open(os.path.join(os.path.dirname(S.__file__), "search.py")).read()
fn = next(n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name == "horizons_command")
ns = {}
exec(ast.get_source_segment(src, fn), ns)
assert ns["horizons_command"]("218001") == "218001;"
assert ns["horizons_command"]("2026 ED138") == "'DES=2026 ED138;'"          # unquoted: 'missing COMMAND content'

# globe: the short name of an unnumbered one's full name "(2026 ED138)" (was an IndexError)
for name, want in (("(2026 ED138)", "(2026 ED138)"), ("3200 Phaethon (1983 TB)", "Phaethon"), ("218001 (2001 XQ72)", "218001")):
    short = name.split("(")[0].strip()
    short = " ".join(short.split()[1:]) if len(short.split()) > 1 and short.split()[0].isdigit() else short
    assert (short or name) == want, (name, short)
gsrc = open(os.path.join(os.path.dirname(S.__file__), "globe.py")).read()
assert 'if len(short.split()) > 1 and short.split()[0].isdigit() else short' in gsrc   # the same lines as tested here

assert owc.lookup({"target_id": "2026 ED138", "best_utc": "2026-11-26T06:41:23"}) is None   # no request made
print("DESIGNATION TESTS PASSED")
