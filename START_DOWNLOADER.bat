@echo off
title Downloader - Install and Open
cd /d "%~dp0"

echo ============================================
echo   Downloader - Setup and launch
echo ============================================
echo.

if not exist "venv\Scripts\activate.bat" (
    echo Creating Python virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo ERROR: Could not create venv. Make sure Python is installed and in PATH.
        pause
        exit /b 1
    )
    echo.
)

echo Installing/updating requirements...
call venv\Scripts\activate.bat
pip install -r requirements.txt
if errorlevel 1 (
    echo WARNING: Some packages may have failed. If run_dump.bat fails later, install enmscripting from your Ericsson wheel: pip install "path\to\enm_client_scripting-*.whl"
    echo.
) else (
    echo Requirements OK.
    echo.
)

echo Stopping previous server instances on port 8765 (if any)...
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8765" ^| findstr "LISTENING"') do (
    taskkill /F /PID %%p >nul 2>&1
)
timeout /t 1 /nobreak >nul

echo Starting Downloader and opening in browser...
start /b "" python server_downloader.py
timeout /t 2 /nobreak >nul
start "" "http://127.0.0.1:8765"

echo.
echo In the tool: choose ENM(s), user and password, set scope, click Generate Command, then Execute Dump. Logs appear in the Logs panel below.
echo.
echo Tip: Use START_DOWNLOADER_HIDDEN.vbs next time to run without this window.
echo.
pause
