@echo off
setlocal
cd /d "%~dp0"

set GIT="C:\Users\HP\AppData\Local\Microsoft\WinGet\Packages\Git.MinGit_Microsoft.Winget.Source_8wekyb3d8bbwe\cmd\git.exe"

echo ============================================================
echo   Pushing ListingPreflight to GitHub
echo   Repository: https://github.com/Praveenmanoharand/MarketPro.git
echo ============================================================
echo.

%GIT% config user.name "praveenmanoharad"
%GIT% config user.email "praveenmanohara.dev@gmail.com"
%GIT% remote remove origin 2>nul
%GIT% remote add origin https://github.com/Praveenmanoharand/MarketPro.git
%GIT% branch -M main

echo Enter your GitHub Personal Access Token (or password):
set /p TOKEN="Token: "

if "%TOKEN%"=="" (
    echo Pushing using standard credentials...
    %GIT% push -u origin main
) else (
    echo Pushing with provided token...
    %GIT% push -u https://praveenmanoharad:%TOKEN%@github.com/Praveenmanoharand/MarketPro.git main
)

echo.
pause
