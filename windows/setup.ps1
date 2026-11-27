<#
PySyzygos setup for Windows: install, update or uninstall, per user (no administrator rights).

Normally run by PySyzygos-Setup.cmd (double-click; it is this script behind a small cmd header, built by
scripts/build_windows_setup.py). Later the Start menu's "Update PySyzygos" and "Uninstall PySyzygos" run the copy
in %LOCALAPPDATA%\PySyzygos\setup.ps1; the System tab's Update button does too.

What it does:
  1. uv (astral.sh) into %LOCALAPPDATA%\PySyzygos\bin: a private copy, PATH is not changed.
  2. PySyzygos from PyPI (`uv tool install pysyzygos`) with uv's own Python 3.12, in %LOCALAPPDATA%\PySyzygos.
  3. Start menu folder PySyzygos: PySyzygos, Observation Manager, Data setup, Command prompt, Data folder,
     Check installation, Update, Uninstall; a desktop icon PySyzygos.
  4. The first time: the data setup (`pysyzygos setup`: data folder, your site, SPICE kernels, the Gaia star
     catalog: about 5 GB, asks before each download, resumable), then PySyzygos starts in your browser.

  PySyzygos-Setup.cmd                    install or update to the newest version on PyPI
  PySyzygos-Setup.cmd -Version 1.6.0     a given version
  PySyzygos-Setup.cmd -Uninstall         remove the program (keeps your data folder and its settings)
  PySyzygos-Setup.cmd -Uninstall -Purge  also remove the data-folder setting (the data folder itself stays)
  -Wheel X.whl                           install a local build (tests); -NoDesktop no desktop icon
  -NoSetup                               skip the first-time data setup (tests)
  -Force                                 end a running PySyzygos without asking
  -Restart                               start PySyzygos when done (the GUI's Update button)
#>
param(
    [switch]$Uninstall,
    [switch]$Purge,
    [string]$Version = 'latest',
    [string]$Wheel = '',
    [switch]$NoDesktop,
    [switch]$NoSetup,
    [switch]$Force,
    [switch]$Restart,
    [switch]$Pause
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'        # Invoke-WebRequest crawls with a progress bar (PS 5.1)
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Pkg = 'pysyzygos'
$App = Join-Path $env:LOCALAPPDATA 'PySyzygos'
$Bin = Join-Path $App 'bin'
$Tools = Join-Path $App 'tools'
$PyDir = Join-Path $App 'python'
$Uv = Join-Path $Bin 'uv.exe'
$Exe = Join-Path $Bin 'pysyzygos.exe'
$Icon = Join-Path $App 'pysyzygos.ico'
$Settings = Join-Path $env:APPDATA 'PySyzygos'           # PySyzygos's own: the data-folder setting ('home')
$Pointer = Join-Path $Settings 'home'
$DefaultData = Join-Path $env:USERPROFILE 'PySyzygos'
$StartDir = Join-Path ([Environment]::GetFolderPath('Programs')) 'PySyzygos'
$DesktopDir = [Environment]::GetFolderPath('Desktop')
$PsExe = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'

$env:UV_TOOL_DIR = $Tools
$env:UV_TOOL_BIN_DIR = $Bin
$env:UV_PYTHON_INSTALL_DIR = $PyDir
$env:UV_NO_MODIFY_PATH = '1'
$env:PYTHONUTF8 = '1'
Remove-Item Env:VIRTUAL_ENV -ErrorAction SilentlyContinue
$Host.UI.RawUI.WindowTitle = 'PySyzygos setup'

function Say([string]$msg) { Write-Host $msg }
function Step([string]$msg) { Write-Host ''; Write-Host "== $msg" -ForegroundColor Cyan }
function Fail([string]$msg) { Write-Host ''; Write-Host "ERROR: $msg" -ForegroundColor Red; Finish 1 }
function Finish([int]$code) {
    if ($Pause) { Write-Host ''; Read-Host 'Press Enter to close' | Out-Null }
    exit $code
}

function Invoke-Native([scriptblock]$cmd) {
    # Windows PowerShell 5.1 turns a native program's stderr into errors, which 'Stop' would make
    # fatal: run with 'Continue' and judge by the exit code
    $old = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { & $cmd } finally { $ErrorActionPreference = $old }
}

function Running-Programs {
    @(Get-Process -ErrorAction SilentlyContinue | Where-Object {
        $_.Path -and $_.Path.StartsWith($App, [StringComparison]::OrdinalIgnoreCase) })
}

function Ensure-Closed([string]$what) {
    # Windows does not let files of a running program be replaced or deleted
    if ($Force -and $Restart) { Start-Sleep -Seconds 3 }     # the GUI's Update: let it answer first
    $p = Running-Programs
    if (-not $p) { return }
    Write-Host ''
    Write-Host '   PySyzygos is running (its window, a search or a catalog download).' -ForegroundColor Yellow
    if ($Force) {
        $p | Stop-Process -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2
    } elseif ($Pause) {
        $a = Read-Host '   Close its window, then press Enter; or type STOP to end it now'
        if ($a -match '^\s*stop\s*$') {
            Running-Programs | Stop-Process -Force -ErrorAction SilentlyContinue
            Start-Sleep -Seconds 2
        }
    }
    if (Running-Programs) { Fail "close PySyzygos, then $what again (or run it with -Force)" }
}

function Download([string]$url, [string]$out) {
    Say "   $url"
    Invoke-WebRequest -Uri $url -OutFile $out -UseBasicParsing -Headers @{ 'User-Agent' = 'PySyzygos-setup' }
}

function Data-Folder {
    # the data folder PySyzygos uses: its setting (written by `pysyzygos setup`), else the default
    if (Test-Path $Pointer) {
        $d = (Get-Content $Pointer -Raw -ErrorAction SilentlyContinue)
        if ($d -and $d.Trim()) { return $d.Trim() }
    }
    return $DefaultData
}

function Data-Ready {
    # set up before: a data folder (its setting, or the default folder with its config file) that holds a
    # complete star catalog (PySyzygos checks: gaia_local.find_catalogs); without one, setup runs (it resumes)
    if (-not ((Test-Path $Pointer) -or (Test-Path (Join-Path $DefaultData 'pysyzygos_config.py')))) { return $false }
    $py = Join-Path $Tools "$Pkg\Scripts\python.exe"
    $code = "from pysyzygos import home, gaia_local; import os; " +
            "print('yes' if os.path.isdir(home.HOME) and any(c[2] for c in gaia_local.find_catalogs(home.HOME)) else 'no')"
    $r = (Invoke-Native { & $py -c $code 2>$null }) -join ''
    if ($r -match 'yes') { return $true }
    Say '   the data folder has no complete star catalog yet'
    return $false
}

# --------------------------------------------------------------------------------------------- uv
function Get-Uv {
    if (Test-Path $Uv) { return }
    Step 'uv (package manager, private copy)'
    $arch = if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64') { 'aarch64' } else { 'x86_64' }
    $zip = Join-Path $env:TEMP "uv-$arch.zip"
    Download "https://github.com/astral-sh/uv/releases/latest/download/uv-$arch-pc-windows-msvc.zip" $zip
    $tmp = Join-Path $env:TEMP 'pysyzygos-uv'
    if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
    # .NET directly: Expand-Archive fails when this Windows PowerShell 5.1 was started from PowerShell 7
    # (it inherits PS 7's module path and loads an incompatible Archive module)
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [IO.Compression.ZipFile]::ExtractToDirectory($zip, $tmp)
    New-Item -ItemType Directory -Force -Path $Bin | Out-Null
    Get-ChildItem $tmp -Recurse -Include 'uv.exe', 'uvx.exe' | ForEach-Object { Copy-Item $_.FullName $Bin -Force }
    Remove-Item $tmp -Recurse -Force
    Remove-Item $zip -Force
    if (-not (Test-Path $Uv)) { Fail 'uv.exe not found in the download' }
    Say ('   ' + (& $Uv --version))
}

# --------------------------------------------------------------------------------------------- package
function Installed-Version {
    if (-not (Test-Path $Exe)) { return '' }
    try {
        $v = (Invoke-Native { & $Exe --version 2>$null }) -join ' '
        if ($v -match '(\d+\.\d+\.\d+\S*)') { return $Matches[1] }
    } catch { }
    return ''
}

function Latest-Version {
    if ($Wheel) { return 'local' }
    if ($Version -ne 'latest') { return $Version.TrimStart('v') }
    try {
        $j = Invoke-RestMethod -Uri "https://pypi.org/pypi/$Pkg/json" -UseBasicParsing `
             -Headers @{ 'User-Agent' = 'PySyzygos-setup' }
        return [string]$j.info.version
    } catch {
        Fail "cannot reach PyPI (pypi.org): $($_.Exception.Message)"
    }
}

function Install-Package([string]$want) {
    Step "PySyzygos $want (Python and the packages; the first time takes a few minutes)"
    $spec = if ($Wheel) { "$Pkg @ $(([Uri](Resolve-Path $Wheel).Path).AbsoluteUri)" } else { "$Pkg==$want" }
    $uvArgs = @('tool', 'install', '--force', '--python-preference', 'only-managed', '--python', '3.12', $spec)
    # uv's hint that its folder is not on PATH is left out: the setup keeps it private on purpose
    Invoke-Native { & $Uv @uvArgs 2>&1 | ForEach-Object { "$_" } |
                    Where-Object { $_ -notmatch 'is not on your PATH|uv tool update-shell|^\s*`?\$env:PATH' } |
                    ForEach-Object { Write-Host $_ } }
    if ($LASTEXITCODE -ne 0) { Fail "uv tool install failed (exit $LASTEXITCODE)" }
    Say ('   ' + (Invoke-Native { & $Exe --version }))
}

# --------------------------------------------------------------------------------------------- Start menu
function New-Shortcut([string]$path, [string]$target, [string]$arguments, [string]$description) {
    $sh = New-Object -ComObject WScript.Shell
    $lnk = $sh.CreateShortcut($path)
    $lnk.TargetPath = $target
    $lnk.Arguments = $arguments
    $lnk.Description = $description
    $lnk.WorkingDirectory = $env:USERPROFILE
    if (Test-Path $Icon) { $lnk.IconLocation = "$Icon,0" }
    $lnk.Save()
}

function Make-Icon {
    # the logo as a Windows icon, with Pillow from PySyzygos's own environment
    $py = Join-Path $Tools "$Pkg\Scripts\python.exe"
    $code = "import os, pysyzygos; from PIL import Image; " +
            "im = Image.open(os.path.join(os.path.dirname(pysyzygos.__file__), 'pysyzygos_logo.png')).convert('RGBA'); " +
            "s = max(im.size); sq = Image.new('RGBA', (s, s)); sq.paste(im, ((s - im.width) // 2, (s - im.height) // 2)); " +
            "sq.save(r'$Icon', sizes=[(256, 256), (48, 48), (32, 32), (16, 16)])"
    Invoke-Native { & $py -c $code 2>&1 | Out-Null }
}

function Install-Shortcuts {
    Step 'Start menu and desktop'
    Make-Icon
    if (Test-Path $StartDir) { Remove-Item $StartDir -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $StartDir | Out-Null
    Copy-Item $PSCommandPath (Join-Path $App 'setup.ps1') -Force -ErrorAction SilentlyContinue
    $setup = "-NoProfile -ExecutionPolicy Bypass -File `"$(Join-Path $App 'setup.ps1')`""
    $cmd = Join-Path $env:SystemRoot 'System32\cmd.exe'
    $folder = "-NoProfile -WindowStyle Hidden -Command `"`$p = Join-Path `$env:APPDATA 'PySyzygos\home'; " +
              "`$d = if (Test-Path `$p) { (Get-Content `$p -Raw).Trim() } else { Join-Path `$env:USERPROFILE 'PySyzygos' }; " +
              "explorer.exe `$d`""
    $items = @(
        @('PySyzygos', $Exe, '', 'Occultation predictions: opens in your browser; this window keeps it running'),
        @('PySyzygos Observation Manager', $Exe, 'gui-observation', 'Observation reports (opens in your browser)'),
        @('Data setup (site, kernels, star catalog)', $cmd, "/k title PySyzygos data setup & `"$Exe`" setup", 'pysyzygos setup: rerun or extend the data setup'),
        @('PySyzygos command prompt', $cmd, "/k title PySyzygos & set `"PATH=$Bin;%PATH%`" & pysyzygos --help", 'A command prompt with the pysyzygos command'),
        @('Data folder', $PsExe, $folder, 'Your PySyzygos data: sites, settings, catalog, results'),
        @('Check installation', $cmd, "/k title PySyzygos & `"$Exe`" setup --status", 'pysyzygos setup --status'),
        @('Update PySyzygos', $PsExe, "$setup -Pause", 'Install the newest version'),
        @('Uninstall PySyzygos', $PsExe, "$setup -Uninstall -Pause", 'Remove the program (keeps your data)')
    )
    foreach ($i in $items) { New-Shortcut (Join-Path $StartDir "$($i[0]).lnk") $i[1] $i[2] $i[3] }
    if (-not $NoDesktop) {
        $i = $items[0]
        New-Shortcut (Join-Path $DesktopDir "$($i[0]).lnk") $i[1] $i[2] $i[3]
    }
    Say "   $StartDir"
}

function Start-PySyzygos {
    Start-Process -FilePath $Exe -WorkingDirectory $env:USERPROFILE
    Say '   PySyzygos starts in its own window and opens your browser (http://127.0.0.1:8080).'
}

function First-Setup {
    Step 'Data setup'
    Say '   PySyzygos now sets up its data folder. It asks a few questions (Enter takes the suggestion):'
    Say "   - the data folder: Enter = $DefaultData (keep it out of OneDrive: the catalog is large)"
    Say '   - your observing site (it can guess it from your internet address or look up a place)'
    Say '   - the SPICE kernels and the Gaia star catalog: downloads of about 3 GB, about 5 GB on disk'
    Say '   It can be stopped any time (Ctrl+C) and resumed: Start menu -> PySyzygos -> Data setup.'
    Write-Host ''
    # attached to this console window (not through PowerShell's output, which would hold back its questions)
    $p = Start-Process -FilePath $Exe -ArgumentList 'setup' -NoNewWindow -Wait -PassThru
    if ($p.ExitCode -ne 0) { Say "   the data setup ended with code $($p.ExitCode)" }
}

# --------------------------------------------------------------------------------------------- uninstall
function Remove-All {
    Step 'Uninstall PySyzygos'
    Ensure-Closed 'uninstall'
    if (Test-Path $StartDir) { Remove-Item $StartDir -Recurse -Force }
    Remove-Item (Join-Path $DesktopDir 'PySyzygos.lnk') -Force -ErrorAction SilentlyContinue
    if (Test-Path $Uv) { Invoke-Native { & $Uv tool uninstall $Pkg 2>&1 | Out-Null } }
    foreach ($d in 'tools', 'python', 'bin') {
        $p = Join-Path $App $d
        if (Test-Path $p) { Remove-Item $p -Recurse -Force -ErrorAction SilentlyContinue }
    }
    Remove-Item $Icon, (Join-Path $App 'setup.ps1') -Force -ErrorAction SilentlyContinue
    $left = @('tools', 'python', 'bin' | Where-Object { Test-Path (Join-Path $App $_) })
    if ($left) {
        Write-Host "   could not remove $($left -join ', ') in $App (a file in use? sign out and in, then" -ForegroundColor Yellow
        Write-Host '   delete the folder by hand)' -ForegroundColor Yellow
    } elseif ((Test-Path $App) -and -not (Get-ChildItem $App -Force)) {
        Remove-Item $App -Force -ErrorAction SilentlyContinue
    }
    $data = Data-Folder
    if ($Purge) {
        Remove-Item $Settings -Recurse -Force -ErrorAction SilentlyContinue
        Say "   data-folder setting removed ($Settings)"
    }
    Say "   your data folder stays: $data"
    Say '   (sites, settings, star catalog, results; delete it by hand if you no longer need it)'
    Say '   done'
}

# --------------------------------------------------------------------------------------------- main
if ($Uninstall) {
    # running from the installed copy: continue from a temporary copy, so the folder can go
    if ($PSCommandPath -and $PSCommandPath.StartsWith($App, [StringComparison]::OrdinalIgnoreCase)) {
        $tmp = Join-Path $env:TEMP 'PySyzygos-uninstall.ps1'
        Copy-Item $PSCommandPath $tmp -Force
        $rest = @('-Uninstall')
        if ($Purge) { $rest += '-Purge' }
        if ($Pause) { $rest += '-Pause' }
        & $PsExe -NoProfile -ExecutionPolicy Bypass -File $tmp @rest
        exit $LASTEXITCODE
    }
    Remove-All
    Finish 0
}

New-Item -ItemType Directory -Force -Path $App | Out-Null
Get-Uv
$before = Installed-Version
$want = Latest-Version
if ($before -and $want -ne 'local' -and $before -eq $want) {
    Step "PySyzygos $before is the newest version: nothing to install"
} else {
    if ($before) { Say "   installed: $before, new: $want" }
    Ensure-Closed 'the setup'
    Install-Package $want
}
Install-Shortcuts

$ready = Data-Ready
if (-not $ready -and -not $NoSetup) {
    First-Setup
    $ready = Data-Ready                 # done when a complete star catalog is there
}

Write-Host ''
Write-Host "PySyzygos $(Installed-Version) is installed." -ForegroundColor Green
Say '  Start menu: PySyzygos -> PySyzygos, Observation Manager, Data setup, Command prompt, Data folder,'
Say '  Check installation, Update, Uninstall. Desktop: PySyzygos.'
Say "  Your data folder: $(Data-Folder)"
if (-not $ready) {
    Write-Host '  No star catalog yet: Start menu -> PySyzygos -> Data setup, or in PySyzygos: System tab ->' -ForegroundColor Yellow
    Write-Host '  Star catalog -> Ready-made catalogs -> Download.' -ForegroundColor Yellow
}
if ($Restart -or (-not $NoSetup -and -not $before)) {     # the first install: open it (without a catalog
    Start-PySyzygos                                        # too: its System tab downloads one)
} elseif (-not $NoSetup -and $Pause) {
    $a = Read-Host '  Start PySyzygos now? [Y/n]'
    if ($a -notmatch '^\s*n') { Start-PySyzygos }
}
Finish 0
