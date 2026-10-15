# Removes Uptime's shortcuts and stops the tracker. Your history (data.db) is kept
# in %USERPROFILE%\Uptime unless you pass -DeleteData.
param([switch]$DeleteData)

Get-CimInstance Win32_Process -Filter "Name = 'pythonw.exe'" |
    Where-Object { $_.CommandLine -match 'Uptime\\app.*tracker\.pyw' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }

Remove-Item -Force -ErrorAction SilentlyContinue `
    (Join-Path ([Environment]::GetFolderPath('Startup'))  'Uptime (background).lnk'),
    (Join-Path ([Environment]::GetFolderPath('Desktop'))  'Uptime.lnk'),
    (Join-Path ([Environment]::GetFolderPath('Programs')) 'Uptime.lnk')

$root = Join-Path $env:USERPROFILE 'Uptime'
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue (Join-Path $root 'app')
if ($DeleteData) { Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $root }
Write-Host "Uninstalled."
