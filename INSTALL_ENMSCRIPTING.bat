@echo off
title Install enmscripting (Ericsson)
cd /d "%~dp0"

echo ============================================
echo   Install enmscripting for Downloader
echo ============================================
echo.

if not exist "venv\Scripts\activate.bat" (
    echo Run START_DOWNLOADER.bat first to create the virtual environment.
    echo Then run this script again.
    pause
    exit /b 1
)

set "WHL="

REM 1) Look in C:\Tools (common company location)
if exist "C:\Tools\enm_client_scripting-*.whl" (
    for %%F in ("C:\Tools\enm_client_scripting-*.whl") do set "WHL=%%F"
)

REM 2) Look in this folder
if not defined WHL (
    for %%F in ("enm_client_scripting-*.whl") do set "WHL=%%F"
)

REM 3) Look in wheels subfolder
if not defined WHL (
    for %%F in ("wheels\enm_client_scripting-*.whl") do set "WHL=%%F"
)

if not defined WHL (
    echo enmscripting is not on PyPI. You need the Ericsson wheel file.
    echo.
    echo Place the wheel in one of these locations:
    echo   - C:\Tools\enm_client_scripting-*.whl
    echo   - This folder ^(where INSTALL_ENMSCRIPTING.bat is^)
    echo   - This folder\wheels\
    echo.
    echo Then run this script again.
    echo.
    pause
    exit /b 1
)

echo Found: %WHL%
echo Installing into Downloader VENV (so Execute Dump finds it)...
venv\Scripts\pip.exe install "%WHL%"
if errorlevel 1 (
    echo Install failed.
    pause
    exit /b 1
)

echo.
echo enmscripting installed in this folder's venv. Run START_DOWNLOADER.bat and use Execute Dump.
echo.
pause
