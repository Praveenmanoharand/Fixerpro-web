@echo off
setlocal
cd /d "%~dp0"

py --version >nul 2>nul
if not errorlevel 1 goto use_py

python --version >nul 2>nul
if not errorlevel 1 goto use_python

echo Python was not found. Install Python 3.10 or newer, then run this file again.
pause
exit /b 1

:use_py
start "ListingPreflight server" cmd /k "py ""%~dp0server.py"""
echo Starting ListingPreflight at http://127.0.0.1:8000/
exit /b 0

:use_python
start "ListingPreflight server" cmd /k "python ""%~dp0server.py"""
echo Starting ListingPreflight at http://127.0.0.1:8000/
exit /b 0