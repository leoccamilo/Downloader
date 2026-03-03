@echo off
title Downloader - Build Nuitka
cd /d "%~dp0"
powershell -ExecutionPolicy Bypass -File build_nuitka.ps1
pause
