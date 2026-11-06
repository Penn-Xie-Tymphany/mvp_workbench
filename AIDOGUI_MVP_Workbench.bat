@echo off
setlocal EnableExtensions
REM AIDOGUI MVP Workbench — desktop App launcher (does NOT write user PATH)
REM Prefer pythonw / VBS so no black console flashes for the GUI.
cd /d "%~dp0"
set "APP_ROOT=%CD%"
set "AIDOGUI_APP_ROOT=%APP_ROOT%"
set "AIDOGUI_WB_ROOT=%APP_ROOT%"
set "AIDOGUI_ENGINE_ROOT=%APP_ROOT%\engine"
set "PYTHONPATH=%APP_ROOT%"

REM Prefer PyInstaller onedir only when BOTH exe AND sibling _internal\ exist.
REM A lone .exe (without _internal) fails: Failed to load Python DLL ... _internal\python3xx.dll
if exist "%APP_ROOT%\AIDOGUI_MVP_Workbench.exe" if exist "%APP_ROOT%\_internal\" (
  start "" "%APP_ROOT%\AIDOGUI_MVP_Workbench.exe"
  exit /b 0
)
if exist "%APP_ROOT%\AIDOGUI_MVP_Workbench.exe" if not exist "%APP_ROOT%\_internal\" (
  echo [AIDOGUI] Found AIDOGUI_MVP_Workbench.exe but missing _internal\ beside it.
  echo   Re-run: powershell -File desktop_app\packaging\build_exe.ps1
  echo   Or fall through to pythonw / Tools.bat ...
  echo.
)

set "PYW="
if exist "%APP_ROOT%\runtime\python\pythonw.exe" set "PYW=%APP_ROOT%\runtime\python\pythonw.exe"
if not defined PYW if exist "%APP_ROOT%\runtime\python\python.exe" set "PYW=%APP_ROOT%\runtime\python\python.exe"

if defined PYW (
  "%PYW%" -c "import tkinter" >nul 2>&1
  if errorlevel 1 (
    echo [AIDOGUI] Bundled Python has no tkinter. Falling back to system Python / Tools.bat
    set "PYW="
  )
)

if defined PYW (
  start "" "%PYW%" -m desktop_app
  exit /b 0
)

REM System Python — prefer pythonw.exe to avoid console window.
REM NOTE: keep set/use of PYEXE / PYWEXE OUTSIDE one parenthesized block —
REM %VAR% inside a ( ) block expands at parse time, before the set runs.
set "PYEXE="
for /f "delims=" %%P in ('py -3 -c "import sys; print(sys.executable)" 2^>nul') do set "PYEXE=%%P"
if not defined PYEXE for /f "delims=" %%P in ('python -c "import sys; print(sys.executable)" 2^>nul') do set "PYEXE=%%P"

if not defined PYEXE goto :nopython
"%PYEXE%" -c "import tkinter" >nul 2>&1
if errorlevel 1 goto :nopython

set "PYWEXE=%PYEXE%"
if /I "%PYEXE:~-10%"=="python.exe" set "PYWEXE=%PYEXE:~0,-10%pythonw.exe"

if exist "%PYWEXE%" (
  start "" "%PYWEXE%" -m desktop_app
  exit /b 0
)

REM VBS hidden launch if only python.exe exists
set "VBS=%TEMP%\aidogui_launch_%RANDOM%.vbs"
>"%VBS%" echo Set sh = CreateObject("Wscript.Shell")
>>"%VBS%" echo sh.CurrentDirectory = "%APP_ROOT%"
>>"%VBS%" echo sh.Run """%PYEXE%"" -m desktop_app", 0, False
wscript //nologo "%VBS%"
del "%VBS%" >nul 2>&1
exit /b 0

:nopython
echo.
echo [AIDOGUI] No Python+tkinter found, and no complete onedir exe ^(exe + _internal^) yet.
echo   - Install Python 3.11+ from python.org ^(check "tcl/tk"^), then re-run this bat
echo   - OR run:  powershell -File desktop_app\packaging\build_exe.ps1
echo     ^(publishes exe AND _internal\ — keep them together^)
echo   - OR double-click Tools.bat for Detect / Build / Run Sim without the GUI
echo.
pause
exit /b 1
