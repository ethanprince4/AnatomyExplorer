@echo off
rem Launches Anatomy Explorer without a console window.
cd /d "%~dp0"
start "" ".venv\Scripts\pythonw.exe" -m app %*
