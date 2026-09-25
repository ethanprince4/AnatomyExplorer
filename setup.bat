@echo off
rem One-time setup: creates the local Python environment and a desktop shortcut.
cd /d "%~dp0"
where py >nul 2>nul && (set PY=py -3) || (set PY=python)
if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    %PY% -m venv .venv || goto :error
)
echo Installing dependencies...
".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :error
if not exist "data\anatomy\anatomy.json" (
    echo.
    echo Anatomy dataset not found - building it now ^(downloads ~400 MB once^)...
    call tools\build_all.bat || goto :error
)
echo Building 3D microanatomy models ^(about half a minute^)...
".venv\Scripts\python.exe" tools\build_micro.py || goto :error
echo Creating desktop shortcut...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop')+'\Anatomy Explorer.lnk');" ^
  "$s.TargetPath='%~dp0.venv\Scripts\pythonw.exe'; $s.Arguments='-m app'; $s.WorkingDirectory='%~dp0';" ^
  "$s.IconLocation='%~dp0app\resources\icon.ico'; $s.Description='Anatomy Explorer'; $s.Save()"
echo.
echo Done. Launch "Anatomy Explorer" from your desktop.
pause
exit /b 0
:error
echo.
echo Setup failed. See the messages above.
pause
exit /b 1
