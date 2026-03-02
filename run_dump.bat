@echo off
cd /d "%~dp0"

if not exist "venv\Scripts\activate.bat" (
    echo Run START_DOWNLOADER.bat first to create venv and install requirements.
    pause
    exit /b 1
)

if "%~1"=="" (
    echo Usage: run_dump.bat ^<config.json^>
    echo   config.json = file exported from Downloader (Export for script)
    pause
    exit /b 1
)

call venv\Scripts\activate.bat
python dump_multiple_enms.py "%~1"
pause
