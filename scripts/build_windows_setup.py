#!/usr/bin/env python3
"""Build PySyzygos-Setup.cmd, the Windows setup to double-click: a small cmd header + windows/setup.ps1 (CRLF).

    python3 scripts/build_windows_setup.py [--dist dist]

The setup installs PySyzygos from PyPI, so the same file works for every version: rebuild and re-attach it only
when windows/setup.ps1 changes. The workflow .github/workflows/windows-setup.yml builds it, tests it on Windows and
attaches it to a published GitHub release (README link: releases/latest/download/PySyzygos-Setup.cmd).
Standard library only.
"""
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PS1 = ROOT / "windows" / "setup.ps1"
MARKER = "#PS-BEGIN"

# cmd stops at `exit /b`, so it never reads the PowerShell part; PowerShell gets the text after the marker (the
# marker is built from two halves in the command, so the command line itself does not match)
HEADER = r"""@echo off
rem PySyzygos setup for Windows: double-click to install or update PySyzygos (for this user, no administrator
rem rights needed). Uninstall: Start menu -> PySyzygos -> Uninstall PySyzygos, or run this file with -Uninstall.
rem Other options: -Version 1.6.0, -NoDesktop.
setlocal
set "PSZ_SELF=%~f0"
set "PSZ_SETUP=%TEMP%\PySyzygos-setup-%RANDOM%.ps1"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$t = [IO.File]::ReadAllText($env:PSZ_SELF); $i = $t.IndexOf('#PS' + '-BEGIN'); [IO.File]::WriteAllText($env:PSZ_SETUP, $t.Substring($i), (New-Object Text.UTF8Encoding $true))"
if errorlevel 1 (
  echo Could not unpack the setup script.
  pause
  exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%PSZ_SETUP%" -Pause %*
set "RC=%ERRORLEVEL%"
del "%PSZ_SETUP%" >nul 2>nul
exit /b %RC%
"""


def crlf(text):
    return text.replace("\r\n", "\n").replace("\n", "\r\n")


def build_cmd(out_dir):
    ps1 = PS1.read_text(encoding="utf-8")
    if any(ord(c) > 127 for c in ps1):
        raise SystemExit("windows/setup.ps1 must be ASCII (Windows PowerShell 5.1 reads it as ANSI)")
    if MARKER in ps1:
        raise SystemExit(f"windows/setup.ps1 must not contain {MARKER}")
    out = Path(out_dir) / "PySyzygos-Setup.cmd"
    out.write_bytes(crlf(HEADER + MARKER + "\n" + ps1).encode("ascii"))
    return out


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dist", default=str(ROOT / "dist"))
    a = p.parse_args(argv)
    Path(a.dist).mkdir(parents=True, exist_ok=True)
    print(build_cmd(a.dist))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
