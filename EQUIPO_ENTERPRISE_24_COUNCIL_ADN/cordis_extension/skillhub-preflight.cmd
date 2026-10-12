@echo off
setlocal
if "%~1"=="" (
  echo Usage: skillhub-preflight.cmd "ABSOLUTE_EXISTING_DSH_RUNTIME"
  exit /b 2
)
where node >nul 2>nul
if errorlevel 1 (
  echo Node is missing. Review package.json engines and install from its official source yourself.
  exit /b 2
)
node "%~dp0skillhub-preflight.mjs" "%~1" "%~dp0."
exit /b %errorlevel%
