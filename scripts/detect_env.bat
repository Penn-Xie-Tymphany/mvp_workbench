@echo off
setlocal
REM Prefer bundled env if present (full package)
if exist "%~dp0..\toolchain\env.bat" call "%~dp0..\toolchain\env.bat"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0detect_env.ps1" %*
exit /b %ERRORLEVEL%
