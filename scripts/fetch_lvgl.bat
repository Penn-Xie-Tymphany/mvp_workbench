@echo off
setlocal
call "%~dp0..\toolchain\env.bat"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0fetch_lvgl.ps1" %*
exit /b %ERRORLEVEL%
