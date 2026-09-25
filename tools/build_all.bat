@echo off
rem Rebuilds data\anatomy from the Z-Anatomy source. Downloads are skipped if already present.
setlocal
cd /d "%~dp0.."
set RAW=data\raw
set BLENDER_DIR=tools\blender-3.6.23-windows-x64
if not exist "%RAW%" mkdir "%RAW%"

if not exist "%RAW%\Z-Anatomy.zip" (
    echo Downloading Z-Anatomy dataset...
    curl -L -o "%RAW%\Z-Anatomy.zip" https://github.com/Z-Anatomy/Models-of-human-anatomy/raw/master/Z-Anatomy.zip || exit /b 1
)
if not exist "%RAW%\TA2.csv" (
    curl -L -o "%RAW%\TA2.csv" https://raw.githubusercontent.com/Z-Anatomy/Models-of-human-anatomy/master/TA2.csv || exit /b 1
)
if not exist "%RAW%\zanat\Z-Anatomy\Startup.blend" (
    echo Extracting Z-Anatomy...
    if not exist "%RAW%\zanat" mkdir "%RAW%\zanat"
    tar -xf "%RAW%\Z-Anatomy.zip" -C "%RAW%\zanat" || exit /b 1
)
if not exist "%BLENDER_DIR%\blender.exe" (
    echo Downloading portable Blender 3.6 LTS ^(used only to read the .blend file^)...
    curl -L -o tools\blender.zip https://download.blender.org/release/Blender3.6/blender-3.6.23-windows-x64.zip || exit /b 1
    tar -xf tools\blender.zip -C tools || exit /b 1
    del tools\blender.zip
)
echo Extracting meshes and metadata with Blender...
if not exist data\extracted mkdir data\extracted
"%BLENDER_DIR%\blender.exe" -b "%RAW%\zanat\Z-Anatomy\Startup.blend" --factory-startup --python tools\export_zanatomy.py -- "%CD%\data\extracted" > data\extracted\blender_stdout.txt 2>&1
if not exist data\extracted\meta.json (
    echo Blender export failed - see data\extracted\blender_stdout.txt
    exit /b 1
)
echo Building runtime dataset...
".venv\Scripts\python.exe" tools\build_dataset.py || exit /b 1
echo Dataset ready in data\anatomy
endlocal
