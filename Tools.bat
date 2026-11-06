@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "APP_ROOT=%CD%"
set "AIDOGUI_APP_ROOT=%APP_ROOT%"
set "AIDOGUI_WB_ROOT=%APP_ROOT%"
set "AIDOGUI_ENGINE_ROOT=%APP_ROOT%\engine"

REM Isolate toolchain into THIS cmd window only (never user PATH)
if exist "%APP_ROOT%\toolchain\env.bat" (
  call "%APP_ROOT%\toolchain\env.bat"
) else (
  echo [Tools] WARN: toolchain\env.bat missing
)

:menu
echo.
echo ========== AIDOGUI MVP Workbench · Tools ==========
echo   APP_ROOT=%APP_ROOT%
echo   1^) Detect Env
echo   2^) Build
echo   3^) Run Sim
echo   4^) Run Script ^(CSV^)
echo   5^) Open cmd with isolated PATH
echo   0^) Exit
echo ===================================================
set /p CHOICE=Select: 
if "%CHOICE%"=="1" goto detect
if "%CHOICE%"=="2" goto build
if "%CHOICE%"=="3" goto sim
if "%CHOICE%"=="4" goto script
if "%CHOICE%"=="5" goto shell
if "%CHOICE%"=="0" exit /b 0
goto menu

:detect
call "%APP_ROOT%\scripts\detect_env.bat"
pause
goto menu

:build
call "%APP_ROOT%\scripts\build.bat"
pause
goto menu

:sim
call "%APP_ROOT%\scripts\run_sim.bat"
pause
goto menu

:script
call "%APP_ROOT%\scripts\run_script.bat"
pause
goto menu

:shell
echo [Tools] Isolated shell. Type exit to return.
cmd /k
goto menu
