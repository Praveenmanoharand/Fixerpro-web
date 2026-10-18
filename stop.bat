@echo off
setlocal
set "LISTING_PREFLIGHT_DIR=%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -Command "$script = [IO.Path]::GetFullPath((Join-Path $env:LISTING_PREFLIGHT_DIR 'server.py')); $serverProcesses = @(Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and $_.CommandLine.IndexOf($script, [StringComparison]::OrdinalIgnoreCase) -ge 0 }); if ($serverProcesses.Count -eq 0) { Write-Host 'No ListingPreflight server process was found.'; exit 0 }; $serverProcesses | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }; Write-Host 'ListingPreflight server stopped.'"
if errorlevel 1 (
    echo Could not stop the server. Try running this file from the same Windows account that started it.
    exit /b 1
)