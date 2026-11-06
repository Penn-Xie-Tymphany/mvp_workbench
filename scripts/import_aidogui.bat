@echo off
setlocal
call "%~dp0..\toolchain\env.bat"
if "%~1"=="" (
  echo Usage: %~nx0 ^<aidogui_export_dir^> [project_name]
  exit /b 2
)
if "%~2"=="" (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0import_aidogui.ps1" -ExportDir "%~1"
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0import_aidogui.ps1" -ExportDir "%~1" -ProjectName "%~2"
)
exit /b %ERRORLEVEL%
