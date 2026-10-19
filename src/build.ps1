# Builds dist\Uptime.exe: all of Uptime in one file that runs without Python installed.
#
# Building needs Python 3. PyInstaller is installed into a private build folder,
# %USERPROFILE%\.uptime-build, not into your Python, and the repo only gets dist\Uptime.exe.
$ErrorActionPreference = 'Stop'

$repo  = Split-Path $PSScriptRoot
$work  = Join-Path $env:USERPROFILE '.uptime-build'
$venv  = Join-Path $work 'venv'
$py    = Join-Path $venv 'Scripts\python.exe'
$stage = Join-Path $work 'src'

if (-not (Test-Path $py)) {
    Write-Host "Setting up the build tools (first time only)..."
    python -m venv $venv
    if ($LASTEXITCODE) { throw "Couldn't create the build environment. Is Python 3 installed?" }
}
& $py -m pip install --disable-pip-version-check --quiet pyinstaller==6.11.1
if ($LASTEXITCODE) { throw "Couldn't install PyInstaller." }

# PyInstaller only bundles .py modules, so build from a copy with .pyw renamed to .py.
Remove-Item -Recurse -Force $stage -ErrorAction SilentlyContinue
New-Item -ItemType Directory $stage | Out-Null
Get-ChildItem $PSScriptRoot -File | Where-Object { $_.Extension -in '.py', '.pyw' } |
    ForEach-Object { Copy-Item $_.FullName (Join-Path $stage ($_.BaseName + '.py')) }
$icon = Join-Path $stage 'uptime.ico'
Copy-Item (Join-Path $PSScriptRoot 'uptime.ico') $icon

Write-Host "Building Uptime.exe..."
& $py -m PyInstaller --noconfirm --clean --log-level WARN --onefile --windowed --name Uptime `
    --icon $icon --add-data "$icon;." `
    --distpath (Join-Path $repo 'dist') --workpath (Join-Path $work 'build') --specpath $work `
    (Join-Path $stage 'uptime.py')
if ($LASTEXITCODE) { throw "PyInstaller failed." }

Write-Host ""
Write-Host "Built $(Join-Path $repo 'dist\Uptime.exe')"
Write-Host "Double-click it to install Uptime (your history and settings are kept)."
