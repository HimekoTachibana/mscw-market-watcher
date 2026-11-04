@echo off
setlocal
cd /d "%~dp0"
echo === MSCW Market Watcher - Windows build ===

rem Find Python (py launcher first, then python on PATH)
set PY=
where py >nul 2>nul && set PY=py -3
if "%PY%"=="" where python >nul 2>nul && set PY=python
if "%PY%"=="" (
  echo.
  echo Python was not found. Install Python 3.12 from https://www.python.org/downloads/
  echo and tick "Add python.exe to PATH" during setup, then run this file again.
  pause
  exit /b 1
)

echo Creating build environment...
%PY% -m venv .buildenv || goto :fail
call .buildenv\Scripts\activate.bat || goto :fail

echo Installing requirements...
python -m pip install --upgrade pip >nul
python -m pip install -r requirements.txt pyinstaller || goto :fail

for /f "delims=" %%n in ('python tools\version.py name') do set APPNAME=%%n
echo Building "%APPNAME%" ...
pyinstaller --noconfirm --clean mesowatcher.spec || goto :fail

if not exist "dist\%APPNAME%\%APPNAME%.exe" goto :fail
python tools\package.py
echo.
echo SUCCESS
echo   Folder: dist\%APPNAME%\   (run "%APPNAME%.exe" inside it)
echo   Zip:    release\
echo (Windows SmartScreen may warn about an unsigned app: More info -^> Run anyway.)
explorer "dist\%APPNAME%"
pause
exit /b 0

:fail
echo.
echo BUILD FAILED. Scroll up for the error and send it to Claude.
pause
exit /b 1
