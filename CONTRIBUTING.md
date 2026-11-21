# Contributing to PySyzygos

Additions, fixes and patches are welcome. This guide shows how to get a working copy, make a change on a branch,
check it, and offer it for integration. It also explains how to work on PySyzygos with Claude Code, the way most of
it was written.

## 1. Get your own copy and a branch

PySyzygos lives at https://github.com/pyzahl/PySyzygos. Fork it on GitHub (button "Fork"), then:

```bash
git clone https://github.com/<you>/PySyzygos.git
cd PySyzygos
git remote add upstream https://github.com/pyzahl/PySyzygos.git     # to stay up to date with the original
git checkout -b my-feature                                          # one branch per change
```

Later, to pick up new work from the original before you continue:

```bash
git fetch upstream
git rebase upstream/main            # or: git merge upstream/main
```

## 2. Install and set up

With uv (as in the README, "Easiest: with uv"): `uv run pysyzygos setup --gmax 16 --source zenodo`, then
`uv run pysyzygos` or `uv run python tests/test_home.py`. Or with pip, as in the README (sections 1-4):

```bash
python -m venv .venv
source .venv/bin/activate           # Windows: .venv\Scripts\activate
pip install -e .
pysyzygos setup --gmax 16 --source zenodo    # kernels + the small G <= 16 catalog (2.1 GB), enough for development
```

Setup asks for your observing site and writes `sites.py`. That file is private and stays out of git.

## 3. Know the code before you change it

The code is a standard Python package (PEP 621 `pyproject.toml`, src layout): modules in `src/pysyzygos/`, imported as
`from pysyzygos import screen` (never by file path). `pip install -e .` makes your edits live at once. Commands are
listed in `src/pysyzygos/__main__.py` (`COMMANDS`): a new tool gets a module with a `main()` and an entry there. Tools
run in the data folder (`pysyzygos.home.HOME`: the project folder in a checkout), so data paths stay relative.

- `README.md`: what the tools do and how to use them.
- `ABOUT.md`: how the predictions are computed, the data sources, the validation and the open items (Part 6 is a
  good list of things to work on).
- `CLAUDE.md`: the project notes: what each file does, the conventions that matter (coordinate frames, SPICE
  rules, cache handling, test stand-ins) and the current status. Read it even if you do not use Claude Code: it is
  the shortest complete map of the project.

## 4. Working with Claude Code

[Claude Code](https://claude.com/claude-code) reads `CLAUDE.md` automatically when you start it in the project
folder, so it knows the structure and conventions from the first prompt:

```bash
cd PySyzygos
claude                              # then describe the change you want
```

Good practice:

- Work on your branch, one topic per session or branch.
- Ask it to run the tests (below) and, for anything that changes predictions, to compare with a known result
  (`pysyzygos/owc_check.py`, see VERIFICATION.md).
- Keep `CLAUDE.md` current: when a change adds a file, a convention or a known limitation, update the matching
  section (Files, Conventions that matter, Status, Ideas not built yet) in the same branch. It is the memory for the
  next developer and the next session.
- Review what it wrote before you commit; you are responsible for the change.
- Add a line for your change to `CHANGELOG.md` (section of the coming version).
- A new package: add it to `dependencies` in `pyproject.toml` and run `uv lock`; commit `uv.lock` with it.
- Mark commits made with its help with this last line in the commit message:
  `Co-Authored-By: Claude <noreply@anthropic.com>` (Claude Code adds the exact model name for you).

## 5. Check your change

```bash
for t in tests/*.py; do python "$t" > /dev/null || echo "FAILED: $t"; done
```

The tests use stand-ins for SPICE, astropy and the network, so they run in seconds without kernels or a catalog.
Each one is a plain script: `python tests/test_solver.py` runs one. If you change a function signature that a
stand-in imitates, update the stand-in so it stays honest. Add a test for new behaviour where you can. A new test
starts with `import _testtmp`: its temporary files then go to one folder that is deleted when it ends.

If your change affects results (orbits, solver, sizes, magnitudes, the pick), run a real search and the GUI once,
and say in the pull request what you compared it with.

## 6. Never commit private or generated files

`.gitignore` already keeps them out; please do not force them in:

- your sites and settings: `sites.py` (coordinates of your observing places), `pysyzygos_config.py`, `owc_reference.txt`, `owc_refs/`, `picks/`,
  `favorites/` (they name your sites)
- downloads and generated data: SPICE kernels (`*.bsp`, `*.bpc`, `*.tls`, `*.tpc`), Gaia catalogs (`gaia_dr3_*/`),
  run outputs (`hits_log.csv`, `hits_report.html`, `maps/`, `targets.py`, ...)

Never put real coordinates into tracked files (examples use New York City Hall, see `src/pysyzygos/templates/sites_example.py`).

## 7. Offer it for integration

```bash
git push origin my-feature
```

Then open a pull request on GitHub from your branch to `pyzahl/PySyzygos` `main`. In the description, say what it
changes and why, how you tested it, and anything a reviewer should look at closely. Small, focused pull requests
are easier to review and merge. For bigger ideas, open an issue first to agree on the approach.

No GitHub account? A patch file works too: `git format-patch upstream/main` and send the files to the maintainer.

## 8. License

PySyzygos is licensed under GPL-3.0-or-later (see `LICENSE`). By contributing you agree that your contribution is
licensed under the same terms. Data used by PySyzygos keep their own terms (Gaia DR3: CC BY-NC 3.0 IGO).

By contributing you also grant the maintainer (Percy Zahl) a non-exclusive, perpetual, worldwide right to license
your contribution, as part of PySyzygos, under other terms as well: for example a written permission that lets
another program include PySyzygos, or a later change of the project's license. Your contribution always stays
available under GPL-3.0-or-later, and you keep your copyright. If you cannot agree to this, say so in your pull
request before it is merged.
