@echo off
rem Microanatomy Model Viewer: double-click to start, or drop a .glb onto this file.
setlocal
set "ROOT=%~dp0.."
set "PY=%ROOT%\.venv\Scripts\pythonw.exe"
if not exist "%PY%" set "PY=C:\Users\Ethan\Desktop\Desktop Stuff\Claude Anatomy\.venv\Scripts\pythonw.exe"
if not exist "%PY%" (
  echo Could not find the Anatomy Explorer .venv. Run setup.bat in the app folder first.
  pause
  exit /b 1
)
pushd "%ROOT%"
start "" "%PY%" -m viewer %*
popd
