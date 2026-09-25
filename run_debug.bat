@echo off
rem Launches Anatomy Explorer with a console window so errors are visible.
cd /d "%~dp0"
".venv\Scripts\python.exe" -m app %*
pause
