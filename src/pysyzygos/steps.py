"""steps.py - where a run's time went: named steps with their time and how many items they handled, printed as a
table at the end of the run and as one machine-readable line that the GUI shows as the run summary.

    S = Steps("search")
    with S.step("orbit downloads", n=40):        # a block
        ...
    S.add("maps", 4.7, n=46)                    # a measured time
    f = S.wrap("exact solve", f)                # every call of f counted and timed (time and calls add up)
    S.emit()                                    # the table, and the line "PYSYZYGOS-STEPS {json}"

Steps can be parts of another (group=<its name>): the table lists them indented under it. The total is the time since the
command started (env PYSYZYGOS_T0, set by the dispatcher, else when Steps was made); what no step covers is listed as
"other". Standard library only (imported by the GUI).
"""
from pysyzygos.version import __version__
import contextlib, functools, json, os, sys, time

MARK = "PYSYZYGOS-STEPS "


class Steps:
    def __init__(self, tool):
        self.tool = tool
        self.t0 = float(os.environ.get("PYSYZYGOS_T0") or time.time())
        self.items = {}                                   # name -> dict(s, n, unit, group, order)
        self.info = {}

    def add(self, name, seconds, n=None, unit="", group=""):
        it = self.items.setdefault(name, dict(s=0.0, n=None, unit=unit, group=group, order=len(self.items)))
        it["s"] += float(seconds)
        if unit and not it["unit"]:                              # a placeholder (order only) gets its unit later
            it["unit"] = unit
        if n is not None:
            it["n"] = (it["n"] or 0) + n
        return it

    @contextlib.contextmanager
    def step(self, name, n=None, unit="", group=""):
        t = time.time()
        try:
            yield
        finally:
            self.add(name, time.time() - t, n, unit, group)

    def wrap(self, name, f, unit="calls", group=""):
        """f, timed: each call adds its time and 1 to the count (nested wrapped calls are counted in both)."""
        @functools.wraps(f)
        def g(*a, **k):
            t = time.time()
            try:
                return f(*a, **k)
            finally:
                self.add(name, time.time() - t, 1, unit, group)
        return g

    def summary(self):
        total = time.time() - self.t0
        rows = sorted(self.items.items(), key=lambda kv: kv[1]["order"])
        top = sum(v["s"] for k, v in rows if not v["group"])        # grouped steps are parts of a top-level one
        row = lambda k, v: dict(name=k, s=round(v["s"], 3), n=v["n"], unit=v["unit"], group=v["group"])
        out, names = [], {k for k, v in rows if not v["group"]}
        for k, v in rows:                                           # each top-level step, then its parts
            if not v["group"]:
                out.append(row(k, v))
                out += [row(k2, v2) for k2, v2 in rows if v2["group"] == k]
        out += [row(k, v) for k, v in rows if v["group"] and v["group"] not in names]
        if total - top > 0.05:
            out.append(dict(name="other", s=round(total - top, 3), n=None, unit="", group=""))
        return dict(tool=self.tool, total_s=round(total, 3), steps=out, info=self.info, version=__version__)

    def emit(self, file=None):
        """Print the table and the machine-readable line (for the GUI)."""
        f = file or sys.stdout
        summary = s = self.summary()
        print(f"\nSteps of this {self.tool} ({s['total_s']:.1f} s in all):", file=f)
        for r in summary["steps"]:
            share = 100.0 * r["s"] / s["total_s"] if s["total_s"] else 0.0
            cnt = f"{r['n']} {r['unit']}".strip() if r["n"] is not None else ""
            print(f"  {'  ' if r['group'] else ''}{r['name']:<{42 if r['group'] else 44}} {r['s']:8.1f} s {share:5.1f} %  "
                  f"{cnt}", file=f)
        print(MARK + json.dumps(summary), file=f, flush=True)
        return summary


def parse(line):
    """The summary dict of a 'PYSYZYGOS-STEPS {json}' line, else None."""
    if not line.startswith(MARK):
        return None
    try:
        return json.loads(line[len(MARK):])
    except ValueError:
        return None
