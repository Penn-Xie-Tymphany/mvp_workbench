@echo off
setlocal
call "%~dp0..\toolchain\env.bat"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_sim.ps1" %*
exit /b %ERRORLEVEL%
