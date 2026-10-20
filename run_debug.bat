@echo off
rem Launches Layered Human with a console window so errors are visible.
cd /d "%~dp0"
".venv\Scripts\python.exe" -m app %*
pause
