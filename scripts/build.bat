@echo off
setlocal
if exist "%~dp0..\toolchain\env.bat" call "%~dp0..\toolchain\env.bat"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build.ps1" %*
exit /b %ERRORLEVEL%
