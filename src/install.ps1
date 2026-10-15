# Installs Uptime for the current user:
#  - copies the app to %USERPROFILE%\Uptime\app (data lives in %USERPROFILE%\Uptime)
#  - starts the tracker automatically at every login (Startup folder shortcut)
#  - adds an "Uptime" shortcut to the Desktop and Start menu
#  - brings over history from older installs
#
# Run it yourself (double-click "Install Uptime.cmd"), not from inside another app:
# some packaged apps silently redirect AppData writes, which hides the shortcuts.
$ErrorActionPreference = 'Stop'

$root = Join-Path $env:USERPROFILE 'Uptime'
$dest = Join-Path $root 'app'
$startup  = [Environment]::GetFolderPath('Startup')
$desktop  = [Environment]::GetFolderPath('Desktop')
$programs = [Environment]::GetFolderPath('Programs')

# Stop any running tracker so files can be replaced and data moved.
Get-CimInstance Win32_Process -Filter "Name = 'pythonw.exe'" |
    Where-Object { $_.CommandLine -match '(WastedTimeTracker|Uptime).*tracker\.pyw' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Milliseconds 500

# Bring over history from older install locations (first one found wins).
New-Item -ItemType Directory -Force $dest | Out-Null
$newDb = Join-Path $root 'data.db'
$oldDirs = @(
    (Join-Path $env:LOCALAPPDATA 'Uptime'),
    (Join-Path $env:LOCALAPPDATA 'WastedTimeTracker')
) + @(Get-ChildItem (Join-Path $env:LOCALAPPDATA 'Packages') -Directory -ErrorAction SilentlyContinue |
      ForEach-Object { Join-Path $_.FullName 'LocalCache\Local\Uptime' })
foreach ($dir in $oldDirs) {
    $oldDb = Join-Path $dir 'data.db'
    if ((Test-Path $oldDb) -and -not (Test-Path $newDb)) {
        Copy-Item $oldDb $newDb
        Write-Host "Moved your history from $dir"
    }
}
foreach ($dir in $oldDirs) {
    if ((Test-Path $dir) -and (Test-Path $newDb)) { Remove-Item -Recurse -Force $dir -ErrorAction SilentlyContinue }
}
Remove-Item -Force -ErrorAction SilentlyContinue `
    (Join-Path $startup  'Wasted Time Tracker (background).lnk'),
    (Join-Path $desktop  'Wasted Time Tracker.lnk'),
    (Join-Path $programs 'Wasted Time Tracker.lnk')

Copy-Item (Join-Path $PSScriptRoot '*.py*'), (Join-Path $PSScriptRoot 'uptime.ico') $dest -Force

$python = (Get-Command python.exe -ErrorAction Stop).Source
$pythonw = Join-Path (Split-Path $python) 'pythonw.exe'
if (-not (Test-Path $pythonw)) { throw "pythonw.exe not found next to $python" }

$shell = New-Object -ComObject WScript.Shell
function New-Shortcut($path, $script, $description) {
    $lnk = $shell.CreateShortcut($path)
    $lnk.TargetPath = $pythonw
    $lnk.Arguments = '"' + (Join-Path $dest $script) + '"'
    $lnk.WorkingDirectory = $dest
    $lnk.Description = $description
    $lnk.IconLocation = (Join-Path $dest 'uptime.ico') + ',0'
    $lnk.Save()
}

New-Shortcut (Join-Path $startup 'Uptime (background).lnk') 'tracker.pyw' 'Records locked / sleep / shutdown time'
New-Shortcut (Join-Path $desktop 'Uptime.lnk') 'dashboard.pyw' 'See where your time goes'
New-Shortcut (Join-Path $programs 'Uptime.lnk') 'dashboard.pyw' 'See where your time goes'

# Start tracking right away (it exits by itself if already running).
Start-Process $pythonw -ArgumentList ('"' + (Join-Path $dest 'tracker.pyw') + '"') -WorkingDirectory $dest

Write-Host ""
Write-Host "Installed. Tracking has started and will run at every login."
Write-Host "Open 'Uptime' from your Desktop or Start menu to see your stats."
