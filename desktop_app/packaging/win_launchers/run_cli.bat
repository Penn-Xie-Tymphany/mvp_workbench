@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "APP_ROOT=%CD%"
set "AIDOGUI_APP_ROOT=%APP_ROOT%"
set "AIDOGUI_WB_ROOT=%APP_ROOT%"
set "AIDOGUI_ENGINE_ROOT=%APP_ROOT%\engine"
set "PYTHONPATH=%APP_ROOT%"

set "PY="
if exist "%APP_ROOT%\runtime\python\python.exe" set "PY=%APP_ROOT%\runtime\python\python.exe"
if not defined PY (
  where py >nul 2>&1 && set "PY=py -3"
)
if not defined PY (
  where python >nul 2>&1 && set "PY=python"
)
if not defined PY (
  echo [run_cli] No Python. Use Tools.bat instead.
  exit /b 1
)

if "%~1"=="" (
  %PY% -m desktop_app --self-check
) else (
  %PY% -m desktop_app %*
)
exit /b %ERRORLEVEL%
